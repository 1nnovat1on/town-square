Town Square
===========

**Town Square** is a privacy-first local communication app. Instead of
predefined cities or channels, all chat rooms are derived from the
participant’s location. When you open the app it requests your
geolocation (never sent to third-party services) and shows a handful of
nearby room identifiers. You can then choose an **age** or **interest**
circle and join the conversation.

---
**Abstergo Communication System**
---

### Features

* 📍 **Location-based rooms.** No hard-coded cities; rooms are generated
  from latitude/longitude buckets. Users in the same neighbourhood see
  the same set of rooms.
* 🧓 **Age and interest circles.** Pick a circle such as *18-28*,
  *29-38*, *sports*, *music*, etc. Age circles prompt for your age and
  verify you fit the range on the client side.
* 👤 **Active users list.** Each room shows a collapsible list of
  connected users and a typing indicator so there are no lurking
  strangers.
* 💬 **Real-time chat.** Built on WebSockets using FastAPI. Messages are
  stored in memory by default or persisted for a few hours if desired
  via the `RETENTION_HOURS` environment variable.
* 🔐 **Privacy first.** No accounts, no IP logging. Rooms are based on
  location buckets only. Geolocation is processed client-side and shared
  only with your own server to compute nearby buckets.
* 🛠️ **Easy deployment.** The server is a single Python file. Deploy on
  a Raspberry Pi, set up a systemd unit and serve it over a private
  network like Tailscale or your own tunnel.

### Quickstart (local dev)

```bash
git clone <your fork URL>
cd town-square
python -m venv .venv
source .venv/bin/activate   # On Windows use: .venv\Scripts\activate
pip install -r requirements.txt

# start the server
uvicorn app:app --reload --port 8080

# visit http://localhost:8080 in your browser
````

### Raspberry Pi Deployment

1. **Install Python & Git**

   ```bash
   sudo apt update && sudo apt upgrade -y
   sudo apt install python3 python3-venv python3-pip git -y
   ```

2. **Clone the repo & set up venv**

   ```bash
   git clone <your fork URL> town-square
   cd town-square
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Run the server**

   ```bash
   uvicorn app:app --host 0.0.0.0 --port 8080
   ```

   Now your Pi serves the app at `http://<your_pi_ip>:8080`.

4. **Optional: run on startup with systemd**
   Create a service file:

   ```bash
   sudo nano /etc/systemd/system/townsquare.service
   ```

   Paste:

   ```
   [Unit]
   Description=Town Square App
   After=network.target

   [Service]
   User=pi
   WorkingDirectory=/home/pi/town-square
   ExecStart=/home/pi/town-square/.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8080
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```

   Then enable:

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable townsquare
   sudo systemctl start townsquare
   ```

5. **Secure access with Tailscale (recommended)**
   Install Tailscale:

   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up
   ```

   Once connected, you and invited peers can access the app privately at
   `http://<pi_tailscale_ip>:8080`.

---

### Environment variables

* `RETENTION_HOURS` – number of hours to keep messages in SQLite. If
  unset or `0` (default) messages are stored only in memory.
* `CORS_ORIGINS` – optional comma-separated list of origins allowed to
  access the API (useful if you host the frontend elsewhere).

### License

MIT
