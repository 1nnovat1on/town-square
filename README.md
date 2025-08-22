Town Square
===========

**Town Square** is a privacy‑first local communication app. Instead of
predefined cities or channels, all chat rooms are derived from the
participant’s location. When you open the app it requests your
geolocation (never sent to third‑party services) and shows a handful of
nearby room identifiers. You can then choose an **age** or **interest**
circle and join the conversation.

---
**Abstergo Communication System**
---

### Features

* 📍 **Location‑based rooms.** No hard‑coded cities; rooms are generated
  from latitude/longitude buckets. Users in the same neighbourhood see
  the same set of rooms.
* 🧓 **Age and interest circles.** Pick a circle such as *18‑28*,
  *29‑38*, *sports*, *music*, etc. Age circles prompt for your age and
  verify you fit the range on the client side.
* 👤 **Active users list.** Each room shows a collapsible list of
  connected users and a typing indicator so there are no lurking
  strangers.
* 💬 **Real‑time chat.** Built on WebSockets using FastAPI. Messages are
  stored in memory by default or persisted for a few hours if desired
  via the `RETENTION_HOURS` environment variable.
* 🔐 **Privacy first.** No accounts, no IP logging. Rooms are based on
  location buckets only. Geolocation is processed client‑side and shared
  only with your own server to compute nearby buckets.
* 🛠️ **Easy deployment.** The server is a single Python file. Deploy on
  a Raspberry Pi, set up a systemd unit and serve it over a private
  network like Tailscale or your own tunnel.

### Quickstart

```bash
git clone <your fork URL>
cd town-square
python -m venv .venv
source .venv/bin/activate   # On Windows use: .venv\Scripts\activate
pip install -r requirements.txt

# start the server
uvicorn app:app --reload --port 8080

# visit http://localhost:8080 in your browser
```

### Environment variables

* `RETENTION_HOURS` – number of hours to keep messages in SQLite. If
  unset or `0` (default) messages are stored only in memory.
* `CORS_ORIGINS` – optional comma‑separated list of origins allowed to
  access the API (useful if you host the frontend elsewhere).

### License

MIT
