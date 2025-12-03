import os
import asyncio
import datetime
from aiohttp import web

from shared import (
    fetch_upcoming_events,
    fetch_results,
    BERLIN_TZ
)

# ============================================================
# CACHE
# ============================================================

_API_CACHE = {
    "upcoming": {"ts": None, "data": []},
    "results": {"ts": None, "data": []},
}

API_CACHE_TTL = datetime.timedelta(minutes=5)


async def cache_updater():
    """Füllt den Cache alle 5 Minuten."""
    while True:
        try:
            up = await fetch_upcoming_events()
            _API_CACHE["upcoming"]["data"] = up
            print(f"[CACHE] Upcoming aktualisiert ({len(up)} Events)")

            res = await fetch_results()
            _API_CACHE["results"]["data"] = res
            print(f"[CACHE] Results aktualisiert ({len(res)} Einträge)")
        except Exception as e:
            print("[CACHE] Fehler:", e)

        await asyncio.sleep(300)


# ============================================================
# API HANDLER
# ============================================================

async def api_upcoming_handler(request):
    return web.json_response({"items": _API_CACHE["upcoming"]["data"][:20]})


async def api_results_handler(request):
    return web.json_response({"items": _API_CACHE["results"]["data"][:20]})


async def health_handler(request):
    return web.json_response({"status": "ok"})


# ============================================================
# START
# ============================================================

async def start_api():
    app = web.Application()
    app.add_routes([
        web.get("/health", health_handler),
        web.get("/api/upcoming", api_upcoming_handler),
        web.get("/api/results", api_results_handler),
    ])

    asyncio.create_task(cache_updater())

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
