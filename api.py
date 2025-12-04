# api.py – FIXED WORKING VERSION FOR RENDER
import os
import asyncio
from aiohttp import web
import json

CACHE = {
    "upcoming": [],
    "results": []
}

CACHE_FILE = "cache.json"


# ------------------------------- Cache
def load_cache():
    global CACHE
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                CACHE = json.load(f)
        except:
            pass


def save_cache():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(CACHE, f, ensure_ascii=False, indent=2)


# ------------------------------- Handlers
async def health(request):
    return web.json_response({"status": "ok"})


async def get_upcoming(request):
    return web.json_response({"items": CACHE["upcoming"][:20]})


async def get_results(request):
    return web.json_response({"items": CACHE["results"][:20]})


async def update_upcoming(request):
    data = await request.json()
    CACHE["upcoming"] = data.get("items", [])
    save_cache()
    return web.json_response({"status": "ok"})


async def update_results(request):
    data = await request.json()
    CACHE["results"] = data.get("items", [])
    save_cache()
    return web.json_response({"status": "ok"})


# ------------------------------- START SERVER
async def start():
    load_cache()

    app = web.Application()

    app.router.add_get("/health", health)
    app.router.add_get("/api/upcoming", get_upcoming)
    app.router.add_get("/api/results", get_results)

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
