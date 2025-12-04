# api.py – FINAL FIXED RENDER VERSION
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
# GET ENDPOINTS (Frontend / Matchcenter)
# =========================================================
async def health(request):
    return web.json_response({"status": "ok"})


async def get_upcoming(request):
    return web.json_response({
        "items": CACHE["upcoming"][:20]
    })


async def get_results(request):
    return web.json_response({
        "items": CACHE["results"][:20]
    })


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

    app = web.Application()

    # Public GET Routes
    app.router.add_get("/health", health)
    app.router.add_get("/api/upcoming", get_upcoming)
    app.router.add_get("/api/results", get_results)

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
