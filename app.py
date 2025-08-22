"""
Town Square application.

This FastAPI app implements a privacy‑first local chat where users join
city‑/circle‑based rooms.  It provides endpoints for real‑time chat via
WebSockets, as well as REST endpoints to enumerate available cities,
circles and nearby suggestions.  Messages are stored in memory by default
or, optionally, in a short‑term SQLite database controlled by the
``RETENTION_HOURS`` environment variable.
"""

import os
import time
import math
import sqlite3
from typing import Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path

# ---- Configuration ----

# number of hours to retain messages; 0 = keep only in memory
RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "0"))
# default city used when no geolocation is available on the client
DEFAULT_CITY = os.getenv("DEFAULT_CITY", "konigsbrunn").lower()
# allowed CORS origins; multiple origins may be comma separated
_cors = os.getenv("CORS_ORIGINS", "").split(",") if os.getenv("CORS_ORIGINS") else []
ORIGINS = [o.strip() for o in _cors if o.strip()]

# known city centres and optional labels; used for geolocation suggestions
CITY_CENTERS = {
    "konigsbrunn": (48.268, 10.889),
    "munich": (48.137, 11.575),
    "augsburg": (48.371, 10.898),
    "new_york": (40.7128, -74.0060),
}

# available circles (e.g. age groups or other community groups) per city
# these lists can be customised by editing this dictionary
CITY_CIRCLES: Dict[str, List[str]] = {
    "konigsbrunn": ["18-25", "25-35", "35-50", "50+"],
    "munich": ["18-30", "30-45", "45-60", "60+"],
    "augsburg": ["18-30", "30-45", "45-60"],
    "new_york": ["18-25", "25-40", "40+"],
}

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
                city TEXT NOT NULL,
                circle TEXT NOT NULL,
                nick TEXT NOT NULL,
                text TEXT NOT NULL,
                ts INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_city_circle_ts ON messages(city, circle, ts)"
        )
        con.commit()


def db_save(city: str, circle: str, nick: str, text: str, ts: int) -> None:
    """Persist a message to SQLite when retention is enabled."""
    if RETENTION_HOURS <= 0:
        return
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT INTO messages(city, circle, nick, text, ts) VALUES(?,?,?,?,?)",
            (city, circle, nick, text, ts),
        )
        con.commit()


def db_recent(city: str, circle: str, limit: int = 50) -> List[tuple]:
    """Fetch recent messages for a city/circle pair from SQLite."""
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
            WHERE city = ? AND circle = ? AND ts >= ?
            ORDER BY ts DESC LIMIT ?
            """,
            (city, circle, cutoff, limit),
        )
        rows = cur.fetchall()
    # return in ascending order of timestamp (oldest first) for display
    return list(reversed(rows))


# initialise database if needed
db_init()


# ---- WebSocket connection management ----

class ConnectionManager:
    """Track active WebSocket connections for each room."""

    def __init__(self) -> None:
        # key is "city::circle"; value is list of WebSocket connections
        self.rooms: Dict[str, List[WebSocket]] = {}

    def key(self, city: str, circle: str) -> str:
        return f"{city.lower()}::{circle.lower()}"

    async def connect(self, city: str, circle: str, websocket: WebSocket) -> None:
        await websocket.accept()
        k = self.key(city, circle)
        self.rooms.setdefault(k, []).append(websocket)

    def disconnect(self, city: str, circle: str, websocket: WebSocket) -> None:
        k = self.key(city, circle)
        if k in self.rooms and websocket in self.rooms[k]:
            self.rooms[k].remove(websocket)
            if not self.rooms[k]:
                self.rooms.pop(k, None)

    async def broadcast(self, city: str, circle: str, message: dict) -> None:
        """Send a message to all clients in a room and remove dead connections."""
        k = self.key(city, circle)
        dead: List[WebSocket] = []
        for ws in self.rooms.get(k, []):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(city, circle, ws)


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


# ---- Routes ----

@app.get("/health")
def health() -> dict:
    """Simple health‑check endpoint."""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    """Landing page: choose nickname, city and circle."""
    return templates.TemplateResponse(
        "index.html", {"request": request, "default_city": DEFAULT_CITY}
    )


@app.get("/square/{city}/{circle}", response_class=HTMLResponse)
def square_page(request: Request, city: str, circle: str) -> HTMLResponse:
    city = sanitize(city.lower().replace(" ", "_"))
    circle = sanitize(circle.lower().replace(" ", "_"))
    history = db_recent(city, circle, limit=50)
    return templates.TemplateResponse(
        "square.html",
        {
            "request": request,
            "city": city,
            "circle": circle,
            "history": history,
        },
    )


@app.websocket("/ws/{city}/{circle}")
async def ws_square(websocket: WebSocket, city: str, circle: str) -> None:
    city = sanitize(city)
    circle = sanitize(circle)
    await manager.connect(city, circle, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            nick = sanitize(data.get("nick", "anon")) or "anon"
            text = sanitize(data.get("text", ""))
            if not text:
                continue
            ts = int(time.time())
            db_save(city, circle, nick, text, ts)
            msg = {"nick": nick, "text": text, "ts": ts}
            await manager.broadcast(city, circle, msg)
    except WebSocketDisconnect:
        manager.disconnect(city, circle, websocket)


@app.get("/api/nearby")
def nearby(lat: float, lon: float) -> dict:
    """Suggest up to three closest known cities to the given lat/lon."""
    best = sorted(
        (
            (name, haversine(lat, lon, coords[0], coords[1]))
            for name, coords in CITY_CENTERS.items()
        ),
        key=lambda x: x[1],
    )[:3]
    return {"nearby": [{"city": name, "distance_km": round(dist, 1)} for name, dist in best]}


@app.get("/api/cities")
def list_cities() -> dict:
    """Return the list of available cities."""
    return {"cities": list(CITY_CENTERS.keys())}


@app.get("/api/circles/{city}")
def list_circles(city: str) -> dict:
    """Return the list of circles for a given city (empty if none)."""
    key = sanitize(city.lower())
    circles = CITY_CIRCLES.get(key, [])
    return {"circles": circles}