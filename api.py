import os
from aiohttp import web
import datetime

from shared import (
    API_CACHE_UPCOMING,
    API_CACHE_RESULTS,
    API_CACHE_TIMESTAMP,
    API_CACHE_TTL,
)

async def health(request):
    return web.json_response({"status": "ok"})

async def api_upcoming(request):
    n = int(request.query.get("n", "5"))
    return web.json_response({"items": API_CACHE_UPCOMING[:n]})

async def api_results(request):
    n = int(request.query.get("n", "5"))
    return web.json_response({"items": API_CACHE_RESULTS[:n]})

async def start_api():
    app = web.Application()

    app.router.add_get("/health", health)
    app.router.add_get("/api/upcoming", api_upcoming)
    app.router.add_get("/api/results", api_results)

    port = int(os.getenv("PORT", "10000"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    print(f"[API] running at 0.0.0.0:{port}")

    # Keep process alive
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    import asyncio
    asyncio.run(start_api())
