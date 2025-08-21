# Town Square

A lightweight, privacy-first **local town square** app. Join a city circle (e.g., `munich/28-35`) and chat in real-time.
No ads, no feeds — just people nearby. Works on desktop & mobile.

## ✨ What's new
- ✅ **Nearby rooms**: detects closest cities and shows **click-to-join rooms**
- ✅ **Select boxes**: cities & circles are chosen from dropdowns to prevent typos
- ✅ **Room presets**: configurable circle presets per city (age bands & interests)

## Quickstart

```bash
python -m venv .venv
. .venv\Scripts\Activate.ps1   # Windows
# source .venv/bin/activate      # macOS/Linux
pip install -r requirements.txt
uvicorn app:app --reload --port 8080
# open http://localhost:8080
```

## Configuration
- Edit `app.py` to adjust `CITY_CENTERS` and `CITY_CIRCLES` (presets)
- Optional env var `RETENTION_HOURS` (0 = in-memory only)

---

Made by Abstergo LLC.
