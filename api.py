# api.py – VERSION MIT /api/results-db
import os
import asyncio
from aiohttp import web
import json

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
                print(
                    f"[API] Cache geladen "
                    f"({len(CACHE.get('upcoming', []))} upcoming, "
                    f"{len(CACHE.get('results', []))} results)"
                )
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
# HELFER: Discord-Result-Post -> strukturiertes Item
# =========================================================
def parse_result_entry(entry: dict, division: str | None = None) -> dict | None:
    """
    Erwartetes Format im 'content' (aus dem Bot):

    Zeile 1: **[Division X]** 07.12.2025 10:47
    Zeile 2: **Crackerito** vs **Steinchen** → **2:0**
    Zeile 3: Modus: crosskeys
    Zeile 4: Raceroom: https://...

    division:
        - None  -> keine Filterung
        - "1"–"6" -> nur, wenn [Division X] passt
    """
    content = entry.get("content", "") or ""
    if not content.strip():
        return None

    lines = content.splitlines()
    if not lines:
        return None

    header = lines[0].strip()

    # Division filtern (falls gewünscht)
    if division is not None:
        marker = f"Division {division}"
        if marker not in header:
            return None

    # Header: **[Division X]** 07.12.2025 10:47
    header_clean = header.replace("*", "").strip()
    # nach ']' splitten, alles dahinter ist Datum(+Uhrzeit)
    if "]" in header_clean:
        parts = header_clean.split("]")
        date_part = parts[-1].strip()  # "07.12.2025 10:47"
    else:
        date_part = header_clean

    date_str = date_part

    player1 = ""
    player2 = ""
    score = ""
    mode = ""
    link = ""

    # Zeile 2: **Crackerito** vs **Steinchen** → **2:0**
    if len(lines) >= 2:
        line2 = lines[1].replace("*", "").strip()
        # auf Pfeil splitten
        if "→" in line2:
            left, right = line2.split("→", 1)
            score = right.strip()
        else:
            left = line2

        if "vs" in left:
            p_parts = left.split("vs", 1)
            player1 = p_parts[0].strip()
            player2 = p_parts[1].strip()

    # Zeile 3: Modus: ...
    if len(lines) >= 3:
        line3 = lines[2].replace("*", "").strip()
        if line3.lower().startswith("modus:"):
            mode = line3.split(":", 1)[1].strip()

    # Zeile 4: Raceroom: ...
    if len(lines) >= 4:
        line4 = lines[3].replace("*", "").strip()
        if ":" in line4:
            _, rest = line4.split(":", 1)
            link = rest.strip()

    # Nur fertige Ergebnisse (kein "vs" als Ergebnis)
    if score.lower() == "vs" or "vs" in score.lower():
        return None

    # Minimale Plausibilitätsprüfung
    if not date_str or not player1 or not player2 or not score:
        return None

    reporter = entry.get("author", "")

    return {
        "date": date_str,
        "player1": player1,
        "score": score,
        "player2": player2,
        "mode": mode,
        "link": link,
        "reporter": reporter,
    }


# =========================================================
# GET ENDPOINTS (Frontend / Matchcenter)
# =========================================================
async def health(request):
    return web.json_response({"status": "ok"})


async def get_upcoming(request):
    return web.json_response({
        "items": CACHE.get("upcoming", [])[:20]
    })


async def get_results(request):
    return web.json_response({
        "items": CACHE.get("results", [])[:20]
    })


async def get_results_db(request: web.Request):
    """
    Neue Route:
    /api/results-db?division=1&limit=50

    - division: "1"–"6"
    - limit: max. Anzahl Einträge
    """
    division = request.query.get("division")
    if division not in ["1", "2", "3", "4", "5", "6"]:
        return web.json_response({"items": []})

    try:
        limit = int(request.query.get("limit", "50"))
    except Exception:
        limit = 50
    limit = max(1, min(336, limit))

    results_raw = CACHE.get("results", []) or []
    items: list[dict] = []

    for entry in results_raw:
        item = parse_result_entry(entry, division=division)
        if item is not None:
            items.append(item)

    # Neueste zuerst: nach date-Feld sortieren (nur String-Vergleich)
    # Wir sortieren einfach nach Eintrags-Reihenfolge rückwärts,
    # da CACHE["results"] vom Bot chronologisch gefüllt wird.
    items = items[-limit:][::-1]

    return web.json_response({"items": items})


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

    # CORS MIDDLEWARE
    @web.middleware
    async def cors_middleware(request, handler):
        response = await handler(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    app = web.Application(middlewares=[cors_middleware])

    # Public GET Routes
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
