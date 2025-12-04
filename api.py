# api.py – FINAL PUSH-ARCHITECTURE VERSION
import os
import json
import asyncio
from aiohttp import web

CACHE_FILE = "tfl_cache.json"

# ------------------------------------------------------
# CACHE HANDLING
# ------------------------------------------------------

def load_cache():
    if not os.path.exists(CACHE_FILE):
        return {"upcoming": [], "results": []}
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_cache(data):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

CACHE = load_cache()

# ------------------------------------------------------
# HANDLER
# ------------------------------------------------------

async def api_upcoming_handler(request):
    return web.json_response({"items": CACHE.get("upcoming", [])[:5]})

async def api_results_handler(request):
    return web.json_response({"items": CACHE.get("results", [])[:5]})

async def api_update_upcoming(request):
    data = await request.json()
    CACHE["upcoming"] = data.get("items", [])
    save_cache(CACHE)
    print("[API] Updated UPCOMING cache")
    return web.json_response({"status": "ok"})

async def api_update_results(request):
    data = await request.json()
    CACHE["results"] = data.get("items", [])
    save_cache(CACHE)
    print("[API] Updated RESULTS cache")
    return web.json_response({"status": "ok"})

async def health_handler(request):
    return web.json_response({"status": "ok"})

# ------------------------------------------------------
# SERVER START
# ------------------------------------------------------

async def start_api():
    app = web.Application()

    # GET
    app.router.add_get("/health", health_handler)
    app.router.add_get("/api/upcoming", api_upcoming_handler)
    app.router.add_get("/api/results", api_results_handler)

    # POST (vom Bot)
    app.router.add_post("/api/update/upcoming", api_update_upcoming)
    app.router.add_post("/api/update/results", api_update_results)

    port = int(os.getenv("PORT", "10000"))
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"[API] Running at http://0.0.0.0:{port}")

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(start_api())
