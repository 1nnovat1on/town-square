import os
import time
import math
import sqlite3
from typing import Dict, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

# ---- Config ----
RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "0"))  # 0 = memory only
DEFAULT_CITY = os.getenv("DEFAULT_CITY", "konigsbrunn").lower()

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "square.db"

app = FastAPI(title="Local Square")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# ---- Presets: cities & circle names ----
CITY_CENTERS: Dict[str, tuple] = {
    "konigsbrunn": (48.268, 10.889),
    "munich": (48.137, 11.575),
    "augsburg": (48.371, 10.898),
    "new_york": (40.7128, -74.0060),
}

# Default circle presets per city (configurable)
CITY_CIRCLES: Dict[str, List[str]] = {
    "konigsbrunn": ["28-35", "18-27", "musicians", "fitness"],
    "munich": ["28-35", "tech", "artists", "music"],
    "augsburg": ["28-35", "parents", "students", "football"],
    "new_york": ["28-35", "tech", "film", "music"],
}

# ---- Storage: memory + optional SQLite ----
def db_init():
    if RETENTION_HOURS <= 0:
        return
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city TEXT NOT NULL,
            circle TEXT NOT NULL,
            nick TEXT NOT NULL,
            text TEXT NOT NULL,
            ts INTEGER NOT NULL
        )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_city_circle_ts ON messages(city, circle, ts)")
        con.commit()

db_init()

def db_save(city: str, circle: str, nick: str, text: str, ts: int):
    if RETENTION_HOURS <= 0:
        return
    with sqlite3.connect(DB_PATH) as con:
        con.execute("INSERT INTO messages(city,circle,nick,text,ts) VALUES(?,?,?,?,?)",
                    (city, circle, nick, text, ts))
        con.commit()

def db_recent(city: str, circle: str, limit=50):
    if RETENTION_HOURS <= 0:
        return []
    cutoff = int(time.time()) - RETENTION_HOURS * 3600
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("DELETE FROM messages WHERE ts < ?", (cutoff,))
        cur.execute("""
            SELECT nick, text, ts FROM messages
            WHERE city=? AND circle=? AND ts>=?
            ORDER BY ts DESC LIMIT ?
        """, (city, circle, cutoff, limit))
        rows = cur.fetchall()
    return list(reversed(rows))

class ConnectionManager:
    def __init__(self):
        self.rooms: Dict[str, List[WebSocket]] = {}

    def key(self, city: str, circle: str) -> str:
        return f"{city.lower()}::{circle.lower()}"

    async def connect(self, city: str, circle: str, websocket: WebSocket):
        await websocket.accept()
        k = self.key(city, circle)
        self.rooms.setdefault(k, []).append(websocket)

    def disconnect(self, city: str, circle: str, websocket: WebSocket):
        k = self.key(city, circle)
        if k in self.rooms and websocket in self.rooms[k]:
            self.rooms[k].remove(websocket)
            if not self.rooms[k]:
                self.rooms.pop(k, None)

    async def broadcast(self, city: str, circle: str, message: dict):
        k = self.key(city, circle)
        dead = []
        for ws in self.rooms.get(k, []):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(city, circle, ws)

manager = ConnectionManager()

def sanitize(s: str) -> str:
    return (s or "").strip()[:200]

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    from math import radians, sin, cos, sqrt, atan2
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c

# ---- API ----
@app.get("/api/cities")
def api_cities():
    return {"cities": list(CITY_CENTERS.keys())}

@app.get("/api/circles")
def api_circles(city: Optional[str] = Query(None)):
    if city and city in CITY_CIRCLES:
        return {"city": city, "circles": CITY_CIRCLES[city]}
    seen = set()
    out = []
    for clist in CITY_CIRCLES.values():
        for c in clist:
            if c not in seen:
                seen.add(c)
                out.append(c)
    return {"city": None, "circles": out}

@app.get("/api/nearby")
def nearby(lat: float, lon: float):
    best = sorted(
        ((name, haversine(lat, lon, c[0], c[1])) for name, c in CITY_CENTERS.items()),
        key=lambda x: x[1]
    )[:3]
    return {"nearby": [{"city": name, "distance_km": round(d, 1)} for name, d in best]}

# ---- Pages ----
@app.get("/health")
def health():
    return {"status": "ok"}

from fastapi import Response

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "default_city": DEFAULT_CITY})

@app.get("/square/{city}/{circle}", response_class=HTMLResponse)
def square_page(request: Request, city: str, circle: str):
    city = sanitize(city.lower().replace(" ", "_"))
    circle = sanitize(circle.lower().replace(" ", "_"))
    history = db_recent(city, circle, limit=50)
    return templates.TemplateResponse("square.html", {
        "request": request,
        "city": city,
        "circle": circle,
        "history": history,
    })

@app.websocket("/ws/{city}/{circle}")
async def ws_square(websocket: WebSocket, city: str, circle: str):
    city = sanitize(city)
    circle = sanitize(circle)
    await manager.connect(city, circle, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            nick = sanitize(data.get("nick", "anon"))
            text = sanitize(data.get("text", ""))
            if not text:
                continue
            ts = int(time.time())
            db_save(city, circle, nick, text, ts)
            msg = {"nick": nick, "text": text, "ts": ts}
            await manager.broadcast(city, circle, msg)
    except WebSocketDisconnect:
        manager.disconnect(city, circle, websocket)
