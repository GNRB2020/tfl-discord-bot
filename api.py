from aiohttp import web
import asyncio
import datetime
from shared import BERLIN_TZ, _cell, GUILD_ID, RESULTS_CHANNEL_ID
from shared import _cell, WB, sheets_required

# API Cache
_API_CACHE = {
    "upcoming": {"ts": None, "data": []},
    "results": {"ts": None, "data": []},
}
API_CACHE_TTL = datetime.timedelta(minutes=10)


async def api_upcoming_handler(request):
    data = _API_CACHE["upcoming"]["data"]
    return web.json_response({"items": data[:5]})


async def api_results_handler(request):
    data = _API_CACHE["results"]["data"]
    return web.json_response({"items": data[:5]})


async def health_handler(request):
    return web.json_response({"status": "ok"})


async def start_api():
    app = web.Application()
    app.add_routes([
        web.get("/health", health_handler),
        web.get("/api/upcoming", api_upcoming_handler),
        web.get("/api/results", api_results_handler),
    ])

    port = int(os.getenv("PORT", "10000"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    print(f"[API] running at 0.0.0.0:{port}")

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(start_api())
