import os
import asyncio
from aiohttp import web
import datetime

# Wir importieren NUR das, was es wirklich gibt
from shared import (
    API_CACHE_UPCOMING,
    API_CACHE_RESULTS,
)

# Maximale Anzahl an Einträgen für die Website
MAX_ITEMS = 20


# ============================================================
# API HANDLER
# ============================================================

async def api_upcoming_handler(request):
    """Gibt die gecachten Upcoming-Events zurück."""
    data = API_CACHE_UPCOMING.get("data", [])
    return web.json_response({"items": data[:MAX_ITEMS]})


async def api_results_handler(request):
    """Gibt die gecachten Ergebnisse zurück."""
    data = API_CACHE_RESULTS.get("data", [])
    return web.json_response({"items": data[:MAX_ITEMS]})


async def health_handler(request):
    return web.json_response({"status": "ok"})


# ============================================================
# API STARTER
# ============================================================

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

    # API bleibt lebendig
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(start_api())
