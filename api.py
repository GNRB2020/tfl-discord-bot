# api.py – FINAL STABLE VERSION
import os
import asyncio
from aiohttp import web
from shared import (
    API_CACHE_UPCOMING,
    API_CACHE_RESULTS,
)

# -------------------------------
# HANDLER
# -------------------------------

async def api_upcoming_handler(request):
    items = API_CACHE_UPCOMING[:5]
    return web.json_response({"items": items})

async def api_results_handler(request):
    items = API_CACHE_RESULTS[:5]
    return web.json_response({"items": items})

async def health_handler(request):
    return web.json_response({"status": "ok"})


# -------------------------------
# START API SERVER
# -------------------------------

async def start_api():
    app = web.Application()
    app.router.add_get("/health", health_handler)
    app.router.add_get("/api/upcoming", api_upcoming_handler)
    app.router.add_get("/api/results", api_results_handler)

    port = int(os.getenv("PORT", "10000"))
    runner = web.AppRunner(app)

    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    print(f"[API] Running at http://0.0.0.0:{port}")

    # API läuft dauerhaft
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(start_api())
