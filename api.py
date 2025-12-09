# api.py – FINAL FIXED RENDER VERSION (MIT /api/results-db)
import os
import asyncio
from aiohttp import web
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import datetime

# =========================================================
# GOOGLE SHEETS INIT
# =========================================================
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
SPREADSHEET_TITLE = os.getenv("SPREADSHEET_TITLE", "Season #4 - Spielbetrieb")

try:
    CREDS = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    GC = gspread.authorize(CREDS)
    WB = GC.open(SPREADSHEET_TITLE)
    print("✅ API: Google Sheet verbunden")
except Exception as e:
    WB = None
    print(f"❌ API: Fehler beim Verbindungsaufbau zu Google Sheets: {e}")


# =========================================================
# GLOBAL CACHE
# =========================================================
CACHE = {
    "upcoming": [],
    "results": []
}

CACHE_FILE = "cache.json"


# =========================================================
# LOAD + SAVE CACHE
# =========================================================
def load_cache():
    global CACHE
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                CACHE = json.load(f)
                print(f"[API] Cache geladen ({len(CACHE.get('upcoming', []))} upcoming, {len(CACHE.get('results', []))} results)")
        except Exception as e:
            print(f"[API] Fehler beim Laden des Cache: {e}")


def save_cache():
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(CACHE, f, ensure_ascii=False, indent=2)
        print("[API] Cache gespeichert")
    except Exception as e:
        print(f"[API] Fehler beim Speichern des Cache: {e}")


# =========================================================
# HELPERS
# =========================================================
def normalize_ws_name(s: str) -> str:
    """Entfernt Problemzeichen aus Worksheet-Namen."""
    return (
        s.replace(" ", "")
         .replace("\u00A0", "")
         .replace("\u2007", "")
         .replace("\u202F", "")
         .replace("\u2002", "")
         .replace("\u2003", "")
         .replace("\u2009", "")
         .replace("\u200A", "")
         .replace("\ufeff", "")
         .replace(".", "")
         .lower()
    )


def find_ws(name: str):
    """Finde Worksheet 100% tolerant."""
    if WB is None:
        raise RuntimeError("Google Sheet nicht verbunden.")

    target = normalize_ws_name(name)

    for ws in WB.worksheets():
        if normalize_ws_name(ws.title) == target:
            return ws

    raise KeyError(f"Worksheet '{name}' nicht gefunden.")


def parse_date_safe(d: str):
    try:
        return datetime.datetime.strptime(d, "%d.%m.%Y")
    except:
        return datetime.datetime.min


# =========================================================
# GET ENDPOINTS (Frontend / Matchcenter)
# =========================================================
async def health(request):
    return web.json_response({"status": "ok"})


async def get_upcoming(request):
    return web.json_response({"items": CACHE["upcoming"][:20]})


async def get_results(request):
    return web.json_response({"items": CACHE["results"][:20]})


# =========================================================
# NEW: /api/results-db  ➜ Ergebnisse direkt aus Google Sheet
# =========================================================
async def get_results_db(request):
    division = request.query.get("division")
    limit = int(request.query.get("limit", "200"))

    if division not in ["1", "2", "3", "4", "5", "6"]:
        return web.json_response({"items": []})

    try:
        ws = find_ws(f"{division}.DIV")
        rows = ws.get_all_values()
    except Exception as e:
        print(f"[API] results-db ERROR: {e}")
        return web.json_response({"items": []})

    data = rows[1:]
    items = []

    for row in data:
        date = row[1].strip() if len(row) > 1 else ""
        mode = row[2].strip() if len(row) > 2 else ""
        p1 = row[3].strip() if len(row) > 3 else ""
        score = row[4].strip() if len(row) > 4 else ""
        p2 = row[5].strip() if len(row) > 5 else ""
        link = row[6].strip() if len(row) > 6 else ""
        reporter = row[7].strip() if len(row) > 7 else ""

        if "vs" in score.lower():
            continue
        if not date or not p1 or not p2:
            continue

        items.append({
            "date": date,
            "player1": p1,
            "score": score,
            "player2": p2,
            "mode": mode,
            "link": link,
            "reporter": reporter,
        })

    items.sort(key=lambda x: parse_date_safe(x["date"]), reverse=True)

    return web.json_response({"items": items[:limit]})


# =========================================================
# UPDATE ENDPOINTS (Bot -> API)
# =========================================================
async def update_upcoming(request):
    try:
        data = await request.json()
        items = data.get("items", [])
        CACHE["upcoming"] = items
        save_cache()
        print(f"[API] UPDATED upcoming: {len(items)} Items")
        return web.json_response({"status": "ok"})
    except Exception as e:
        print(f"[API] Fehler beim Update upcoming: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def update_results(request):
    try:
        data = await request.json()
        items = data.get("items", [])
        CACHE["results"] = items
        save_cache()
        print(f"[API] UPDATED results: {len(items)} Items")
        return web.json_response({"status": "ok"})
    except Exception as e:
        print(f"[API] Fehler beim Update results: {e}")
        return web.json_response({"error": str(e)}, status=500)


# =========================================================
# START SERVER
# =========================================================
async def start():
    load_cache()

    @web.middleware
    async def cors_middleware(request, handler):
        response = await handler(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    app = web.Application(middlewares=[cors_middleware])

    # Public GET routes
    app.router.add_get("/health", health)
    app.router.add_get("/api/upcoming", get_upcoming)
    app.router.add_get("/api/results", get_results)
    app.router.add_get("/api/results-db", get_results_db)

    # Bot → API update routes
    app.router.add_post("/api/update/upcoming", update_upcoming)
    app.router.add_post("/api/update/results", update_results)

    port = int(os.getenv("PORT", "10000"))
    print(f"[API] STARTING on port {port}")

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    print("[API] RUNNING...")
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(start())
