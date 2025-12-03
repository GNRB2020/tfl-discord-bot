# ============================
# TFL Discord API – final stable
# ============================

import os
import asyncio
import datetime
from aiohttp import web

# Wir importieren NUR die Cache-Variablen aus shared.py
from shared import (
    API_CACHE_UPCOMING,
    API_CACHE_RESULTS,
)

# Falls die Variablen nicht existieren, legen wir Dummy an
if "data" not in API_CACHE_UPCOMING:
    API_CACHE_UPCOMING["data"] = []
if "data" not in API_CACHE_RESULTS:
    API_CACHE_RESULTS["data"] = []


# ------------------------------------------------------------
# API HANDLER
# ------------------------------------------------------------
async def api_upcoming_handler(request):
    # wir geben maximal 20 zurück – gefiltert macht das JS im Frontend
    data = API_CACHE_UPCOMING["data"]
    return web.json_response({"items": data})


async def api_results_handler(request):
    data = API_CACHE_RESULTS["data"]
    return web.json_response({"items": data})


async def health_handler(request):
    return web.json_response({"status": "ok"})


# ------------------------------------------------------------
# API START
# ------------------------------------------------------------
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

    print(f"[API] running at http://0.0.0.0:{port}")

    # API läuft dauerhaft
    while True:
        await asyncio.sleep(3600)


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(start_api())
