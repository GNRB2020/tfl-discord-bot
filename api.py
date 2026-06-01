# api.py – VERSION MIT /api/results-db + TFNL Ranking Endpoints
import os
import asyncio
from aiohttp import web
import json

# =========================================================
# GLOBAL CACHE
# =========================================================
CACHE = {
    "upcoming": [],
    "results": [],
    "tfnl_season_ranking": [],
    "tfnl_overall_ranking": []
}

CACHE_FILE = "cache.json"

API_PERFORMANCE_VERSION = "api-performance-v2-ranking-endpoints"
print(f"[API] geladen: {API_PERFORMANCE_VERSION}")

RESULTS_DB_CACHE: dict[str, list[dict]] = {}
_RESULTS_CACHE_SIGNATURE: tuple[int, int] | None = None


def ensure_cache_keys():
    """
    Sorgt dafür, dass alte cache.json-Dateien ohne neue Keys weiter funktionieren.
    """
    CACHE.setdefault("upcoming", [])
    CACHE.setdefault("results", [])
    CACHE.setdefault("tfnl_season_ranking", [])
    CACHE.setdefault("tfnl_overall_ranking", [])


def invalidate_results_db_cache():
    global RESULTS_DB_CACHE, _RESULTS_CACHE_SIGNATURE
    RESULTS_DB_CACHE = {}
    _RESULTS_CACHE_SIGNATURE = None


def get_results_signature(results_raw: list[dict]) -> tuple[int, int]:
    if not results_raw:
        return (0, 0)
    return (len(results_raw), hash(json.dumps(results_raw, ensure_ascii=False, sort_keys=True)))


def get_results_db_items_for_division(division: str) -> list[dict]:
    global _RESULTS_CACHE_SIGNATURE

    results_raw = CACHE.get("results", []) or []
    signature = get_results_signature(results_raw)

    if signature != _RESULTS_CACHE_SIGNATURE:
        RESULTS_DB_CACHE.clear()
        _RESULTS_CACHE_SIGNATURE = signature

    if division in RESULTS_DB_CACHE:
        return RESULTS_DB_CACHE[division]

    items: list[dict] = []
    for entry in results_raw:
        item = parse_result_entry(entry, division=division)
        if item is not None:
            items.append(item)

    RESULTS_DB_CACHE[division] = items
    return items


# =========================================================
# LOAD + SAVE CACHE
# =========================================================
def load_cache():
    global CACHE
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    CACHE.update(loaded)

                ensure_cache_keys()
                invalidate_results_db_cache()

                print(
                    f"[API] Cache geladen "
                    f"({len(CACHE.get('upcoming', []))} upcoming, "
                    f"{len(CACHE.get('results', []))} results, "
                    f"{len(CACHE.get('tfnl_season_ranking', []))} season-ranking, "
                    f"{len(CACHE.get('tfnl_overall_ranking', []))} overall-ranking)"
                )
        except Exception as e:
            ensure_cache_keys()
            print(f"[API] Fehler beim Laden des Cache: {e}")
    else:
        ensure_cache_keys()


def save_cache():
    ensure_cache_keys()
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


def parse_limit(request: web.Request, default: int = 500, maximum: int = 5000) -> int:
    try:
        limit = int(request.query.get("limit", str(default)))
    except Exception:
        limit = default

    return max(1, min(maximum, limit))


def normalize_items_payload(data: dict) -> list[dict]:
    """
    Akzeptiert:
    - {"items": [...]}
    - {"rows": [...]}
    - direkt eine Liste wird außerhalb abgefangen
    """
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return items

        rows = data.get("rows")
        if isinstance(rows, list):
            return rows

    return []


# =========================================================
# GET ENDPOINTS (Frontend / Matchcenter)
# =========================================================
async def health(request):
    ensure_cache_keys()
    return web.json_response({
        "status": "ok",
        "version": API_PERFORMANCE_VERSION,
        "counts": {
            "upcoming": len(CACHE.get("upcoming", [])),
            "results": len(CACHE.get("results", [])),
            "tfnl_season_ranking": len(CACHE.get("tfnl_season_ranking", [])),
            "tfnl_overall_ranking": len(CACHE.get("tfnl_overall_ranking", [])),
        }
    })


async def get_upcoming(request):
    ensure_cache_keys()
    limit = parse_limit(request, default=20, maximum=200)
    return web.json_response({
        "items": CACHE.get("upcoming", [])[:limit]
    })


async def get_results(request):
    ensure_cache_keys()
    limit = parse_limit(request, default=20, maximum=200)
    return web.json_response({
        "items": CACHE.get("results", [])[:limit]
    })


async def get_results_db(request: web.Request):
    """
    Route:
    /api/results-db?division=1&limit=50

    - division: "1"–"6"
    - limit: max. Anzahl Einträge
    """
    ensure_cache_keys()

    division = request.query.get("division")
    if division not in ["1", "2", "3", "4", "5", "6"]:
        return web.json_response({"items": []})

    limit = parse_limit(request, default=50, maximum=336)

    # Neueste zuerst: nach Eintrags-Reihenfolge rückwärts,
    # da CACHE["results"] vom Bot chronologisch gefüllt wird.
    items = get_results_db_items_for_division(division)
    items = items[-limit:][::-1]

    return web.json_response({"items": items})


async def get_tfnl_season_ranking(request: web.Request):
    """
    Neue Route für den Joomla-Beitrag:
    /api/tfnl-season-ranking

    Erwartetes Frontend-Format:
    {"items": [...]}

    Die Daten müssen vom Bot/Ranking-Prozess per
    POST /api/update/tfnl-season-ranking aktualisiert werden.
    """
    ensure_cache_keys()
    limit = parse_limit(request, default=5000, maximum=20000)
    items = CACHE.get("tfnl_season_ranking", []) or []

    return web.json_response({
        "items": items[:limit],
        "count": len(items)
    })


async def get_tfnl_overall_ranking(request: web.Request):
    """
    Neue Route für den Joomla-Beitrag:
    /api/tfnl-overall-ranking

    Erwartetes Frontend-Format:
    {"items": [...]}

    Die Daten müssen vom Bot/Ranking-Prozess per
    POST /api/update/tfnl-overall-ranking aktualisiert werden.
    """
    ensure_cache_keys()
    limit = parse_limit(request, default=5000, maximum=20000)
    items = CACHE.get("tfnl_overall_ranking", []) or []

    return web.json_response({
        "items": items[:limit],
        "count": len(items)
    })


# =========================================================
# UPDATE ENDPOINTS (Bot -> API)
# =========================================================
async def update_upcoming(request):
    ensure_cache_keys()
    try:
        data = await request.json()
        items = normalize_items_payload(data)
        CACHE["upcoming"] = items
        save_cache()
        print(f"[API] UPDATED upcoming: {len(items)} Items")
        return web.json_response({"status": "ok", "count": len(items)})
    except Exception as e:
        print(f"[API] Fehler beim Update upcoming: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def update_results(request):
    ensure_cache_keys()
    try:
        data = await request.json()
        items = normalize_items_payload(data)
        CACHE["results"] = items
        invalidate_results_db_cache()
        save_cache()
        print(f"[API] UPDATED results: {len(items)} Items")
        return web.json_response({"status": "ok", "count": len(items)})
    except Exception as e:
        print(f"[API] Fehler beim Update results: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def update_tfnl_season_ranking(request):
    ensure_cache_keys()
    try:
        data = await request.json()

        if isinstance(data, list):
            items = data
        else:
            items = normalize_items_payload(data)

        CACHE["tfnl_season_ranking"] = items
        save_cache()
        print(f"[API] UPDATED tfnl_season_ranking: {len(items)} Items")
        return web.json_response({"status": "ok", "count": len(items)})
    except Exception as e:
        print(f"[API] Fehler beim Update tfnl_season_ranking: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def update_tfnl_overall_ranking(request):
    ensure_cache_keys()
    try:
        data = await request.json()

        if isinstance(data, list):
            items = data
        else:
            items = normalize_items_payload(data)

        CACHE["tfnl_overall_ranking"] = items
        save_cache()
        print(f"[API] UPDATED tfnl_overall_ranking: {len(items)} Items")
        return web.json_response({"status": "ok", "count": len(items)})
    except Exception as e:
        print(f"[API] Fehler beim Update tfnl_overall_ranking: {e}")
        return web.json_response({"error": str(e)}, status=500)


# =========================================================
# START SERVER
# =========================================================
async def start():
    load_cache()

    # CORS MIDDLEWARE
    @web.middleware
    async def cors_middleware(request, handler):
        if request.method == "OPTIONS":
            response = web.Response(status=204)
        else:
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

    # TFNL Ranking GET Routes für Joomla
    app.router.add_get("/api/tfnl-season-ranking", get_tfnl_season_ranking)
    app.router.add_get("/api/tfnl-overall-ranking", get_tfnl_overall_ranking)

    # Bot → API update routes
    app.router.add_post("/api/update/upcoming", update_upcoming)
    app.router.add_post("/api/update/results", update_results)

    # Bot/Ranking-Prozess → API update routes
    app.router.add_post("/api/update/tfnl-season-ranking", update_tfnl_season_ranking)
    app.router.add_post("/api/update/tfnl-overall-ranking", update_tfnl_overall_ranking)

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
