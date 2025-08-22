# Town Square

A lightweight, privacy‑first **town square** app.  Join a city circle (e.g. `munich/28‑35`) and chat in real‑time.
No ads, no feeds — just people nearby.  The goal is to restore the simple village plaza in digital form.

## ✨ Features

- 🔁 **Real‑time chat** via WebSockets — each square is a separate room based on city and circle (for example, age group).
- 🗺️ **Selectable rooms** — choose your city and circle from dropdowns; misspellings are a thing of the past.
- 📍 **Nearby suggestions** — if you grant geolocation, the app suggests the closest cities for you to join.
- 🧰 **Simple storage** — messages are stored in memory by default; enable short‑lived SQLite persistence via `RETENTION_HOURS`.
- 🔐 **No accounts** — users pick a nickname that can be changed at any time.  We never store IP addresses or personal identifiers.

## Quickstart

```bash
# create and activate a virtual environment
python -m venv .venv
# on Windows (PowerShell)
. .venv\Scripts\Activate.ps1
# on macOS/Linux
# source .venv/bin/activate

# install dependencies
pip install -r requirements.txt

# start the server on port 8080
uvicorn app:app --reload --port 8080

# open http://localhost:8080 in your browser
```

## Environment options

You can customise behaviour using environment variables (create a `.env` file or export them):

```
# how long to retain messages in hours (0 = in‑memory only)
RETENTION_HOURS=12

# default city when no geolocation is available
DEFAULT_CITY=konigsbrunn

# comma‑separated list of allowed origins for CORS (for example, if hosting the frontend separately)
CORS_ORIGINS=http://localhost:8080
```

## API/URLs

Endpoint                    | Description
---------------------------|---------------------------------------------------------------
`GET /`                    | join page (pick nickname, city and circle)
`GET /square/{city}/{circle}` | chat UI for that square
`WS /ws/{city}/{circle}`   | WebSocket endpoint for messages
`GET /api/cities`          | returns the list of available cities
`GET /api/circles/{city}`  | returns the list of circles for a city
`GET /api/nearby?lat=..&lon=..` | suggests nearby cities (simple demo)
`GET /health`              | health‑check (returns JSON)

## Notes on privacy

- **No accounts:** users choose a nickname; no IP addresses are stored.
- **Ephemeral by default:** messages live in memory only unless `RETENTION_HOURS` is set.
- **Local suggestions:** geolocation is processed client‑side and never stored on the server.

## Roadmap

- Invite links and per‑circle rules (moderation by local stewards).
- Show active user counts per square.
- Federated squares so that multiple servers can discover each other.
- Presence pings to indicate who is nearby without revealing location.

---

Made by Abstergo LLC.