"""
Town Square application.

This FastAPI app implements a privacy‑first local chat.  Unlike
traditional chat services that require you to join predefined cities or
servers, Town Square derives every room from the participant’s
geolocation.  When you load the site the browser obtains your
coordinates (with your permission) and the server generates a handful
of nearby *room buckets*.  You then choose an **age** or **interest**
circle and join the conversation.

Messages are stored in memory by default.  You can optionally
configure a retention period by setting the ``RETENTION_HOURS``
environment variable; messages older than that will be pruned from the
SQLite database.
"""

import os
import time
import math
import sqlite3
from typing import Dict, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path

# ---- Configuration ----

# number of hours to retain messages; 0 = keep only in memory
RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "0"))
# allowed CORS origins; multiple origins may be comma separated
_cors = os.getenv("CORS_ORIGINS", "").split(",") if os.getenv("CORS_ORIGINS") else []
ORIGINS = [o.strip() for o in _cors if o.strip()]

# generic circles: age ranges and interest groups
AGE_CIRCLES: List[str] = [
    "18-28",
    "29-38",
    "39-48",
    "49-58",
    "59+",
]
INTEREST_CIRCLES: List[str] = [
    "sports",
    "music",
    "gaming",
    "coding",
    "travel",
    "foodies",
    "photography",
]

# paths
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "square.db"

# ---- App setup ----

app = FastAPI(title="Town Square")

# configure CORS if origins are provided
if ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# ---- Database helpers ----

def db_init() -> None:
    """Initialise the SQLite database if message retention is enabled."""
    if RETENTION_HOURS <= 0:
        return
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room TEXT NOT NULL,
                circle TEXT NOT NULL,
                nick TEXT NOT NULL,
                text TEXT NOT NULL,
                ts INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_room_circle_ts ON messages(room, circle, ts)"
        )
        con.commit()


def db_save(room: str, circle: str, nick: str, text: str, ts: int) -> None:
    """Persist a message to SQLite when retention is enabled."""
    if RETENTION_HOURS <= 0:
        return
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT INTO messages(room, circle, nick, text, ts) VALUES(?,?,?,?,?)",
            (room, circle, nick, text, ts),
        )
        con.commit()


def db_recent(room: str, circle: str, limit: int = 50) -> List[tuple]:
    """Fetch recent messages for a room/circle pair from SQLite."""
    if RETENTION_HOURS <= 0:
        return []
    cutoff = int(time.time()) - RETENTION_HOURS * 3600
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        # prune old messages
        cur.execute("DELETE FROM messages WHERE ts < ?", (cutoff,))
        cur.execute(
            """
            SELECT nick, text, ts FROM messages
            WHERE room = ? AND circle = ? AND ts >= ?
            ORDER BY ts DESC LIMIT ?
            """,
            (room, circle, cutoff, limit),
        )
        rows = cur.fetchall()
    # return in ascending order of timestamp (oldest first) for display
    return list(reversed(rows))


# initialise database if needed
db_init()

# ---- User tracking for active users ----
# Map each room key ("room::circle") to a dictionary of WebSocket connections
# and their associated nicknames.  This allows us to broadcast the list of
# active users to everyone in the room whenever someone joins or leaves.
room_users: Dict[str, Dict[WebSocket, str]] = {}


# ---- WebSocket connection management ----

class ConnectionManager:
    """Track active WebSocket connections for each room."""

    def __init__(self) -> None:
        # key is "room::circle"; value is list of WebSocket connections
        self.rooms: Dict[str, List[WebSocket]] = {}

    def key(self, room: str, circle: str) -> str:
        return f"{room.lower()}::{circle.lower()}"

    async def connect(self, room: str, circle: str, websocket: WebSocket) -> None:
        await websocket.accept()
        k = self.key(room, circle)
        self.rooms.setdefault(k, []).append(websocket)

    def disconnect(self, room: str, circle: str, websocket: WebSocket) -> None:
        k = self.key(room, circle)
        if k in self.rooms and websocket in self.rooms[k]:
            self.rooms[k].remove(websocket)
            if not self.rooms[k]:
                self.rooms.pop(k, None)

    async def broadcast(self, room: str, circle: str, message: dict) -> None:
        """Send a message to all clients in a room and remove dead connections."""
        k = self.key(room, circle)
        dead: List[WebSocket] = []
        for ws in self.rooms.get(k, []):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(room, circle, ws)


manager = ConnectionManager()


# ---- Pydantic model ----

class Post(BaseModel):
    nick: str
    text: str


# ---- Utility functions ----

def sanitize(s: str) -> str:
    """Trim and truncate to a reasonable length (for nicknames, circles, etc.)."""
    return (s or "").strip()[:200]


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great‑circle distance between two points on Earth."""
    R = 6371.0  # kilometres
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def room_bucket(lat: float, lon: float, precision: int = 3) -> str:
    """Bucketize latitude and longitude to create a deterministic room ID.

    The ``precision`` determines rounding precision; default 3 means ~100–150 m
    resolution.  Adjust this value to control how large a geographic area
    each room covers.
    """
    return f"{round(lat, precision)}_{round(lon, precision)}"


def neighbor_buckets(lat: float, lon: float, step: float = 0.001) -> List[tuple[str, float, float]]:
    """Generate a 3×3 neighbourhood of buckets centred on the given lat/lon.

    Returns a list of tuples ``(room_id, bucket_lat, bucket_lon)`` for the
    centre and its eight immediate neighbours.  The ``step`` argument
    controls how far apart each neighbouring bucket is (default 0.001
    degrees ≈ 100 m).  You can modify this value if you choose a
    different bucket precision.
    """
    rooms: List[tuple[str, float, float]] = []
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            rlat = lat + di * step
            rlon = lon + dj * step
            rid = room_bucket(rlat, rlon)
            rooms.append((rid, rlat, rlon))
    return rooms


# ---- Routes ----

@app.get("/health")
def health() -> dict:
    """Simple health‑check endpoint."""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    """Landing page: choose nickname, room (derived from location) and circle."""
    return templates.TemplateResponse(
        "index.html",
        {"request": request},
    )


@app.get("/square/{room}/{circle}", response_class=HTMLResponse)
def square_page(request: Request, room: str, circle: str) -> HTMLResponse:
    room = sanitize(room.lower().replace(" ", "_"))
    circle = sanitize(circle.lower().replace(" ", "_"))
    history = db_recent(room, circle, limit=50)
    return templates.TemplateResponse(
        "square.html",
        {
            "request": request,
            "room": room,
            "circle": circle,
            "history": history,
        },
    )


@app.websocket("/ws/{room}/{circle}")
async def ws_square(websocket: WebSocket, room: str, circle: str) -> None:
    room = sanitize(room)
    circle = sanitize(circle)
    await manager.connect(room, circle, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            # Handle a join event.  The client sends {"join": nickname} once upon connection
            if "join" in data:
                nick = sanitize(data.get("join", "anon")) or "anon"
                key = manager.key(room, circle)
                # register nickname for this websocket
                room_users.setdefault(key, {})[websocket] = nick
                # broadcast updated user list (type: users)
                user_list = list(room_users[key].values())
                await manager.broadcast(room, circle, {
                    "type": "users",
                    "users": user_list,
                    "count": len(user_list),
                })
                continue

            # Handle typing notifications
            if data.get("type") == "typing":
                nick = sanitize(data.get("nick", "anon")) or "anon"
                # broadcast typing status to all clients
                await manager.broadcast(room, circle, {
                    "type": "typing",
                    "nick": nick,
                    "typing": bool(data.get("typing")),
                })
                continue

            # Otherwise treat as a chat message
            nick = sanitize(data.get("nick", "anon")) or "anon"
            text = sanitize(data.get("text", ""))
            if not text:
                continue
            key = manager.key(room, circle)
            # update stored nickname for this websocket (in case it changed)
            room_users.setdefault(key, {})[websocket] = nick
            ts = int(time.time())
            db_save(room, circle, nick, text, ts)
            msg = {"nick": nick, "text": text, "ts": ts}
            await manager.broadcast(room, circle, msg)
            # broadcast updated user list after message (ensures list stays fresh)
            user_list = list(room_users[key].values())
            await manager.broadcast(room, circle, {
                "type": "users",
                "users": user_list,
                "count": len(user_list),
            })
    except WebSocketDisconnect:
        # remove connection from connection manager and user tracking
        manager.disconnect(room, circle, websocket)
        key = manager.key(room, circle)
        if key in room_users and websocket in room_users[key]:
            room_users[key].pop(websocket, None)
            # Only broadcast updated users list if there are other connections
            if manager.rooms.get(key):
                user_list = list(room_users[key].values())
                await manager.broadcast(room, circle, {
                    "type": "users",
                    "users": user_list,
                    "count": len(user_list),
                })


@app.get("/api/rooms")
def api_rooms(lat: float, lon: float) -> dict:
    """Return a list of nearby room buckets and distances from the supplied coordinate.

    The centre bucket (the one containing the provided coordinate) is
    marked with ``is_center = True``.  Distances are reported in
    kilometres and rounded to two decimal places.
    """
    # compute centre id
    centre_id = room_bucket(lat, lon)
    rooms = []
    for rid, rlat, rlon in neighbor_buckets(lat, lon):
        rooms.append({
            "id": rid,
            "lat": rlat,
            "lon": rlon,
            "distance_km": round(haversine(lat, lon, rlat, rlon), 2),
            "is_center": rid == centre_id,
        })
    rooms.sort(key=lambda x: (not x["is_center"], x["distance_km"]))
    return {"rooms": rooms}


@app.get("/api/circles")
def api_circles() -> dict:
    """Return the available age and interest circles.

    Age circles are numeric ranges (e.g. ``18-28``) or plus ranges
    (``59+``).  Interest circles are words (e.g. ``music``, ``coding``).
    """
    return {"age": AGE_CIRCLES, "interests": INTEREST_CIRCLES}
