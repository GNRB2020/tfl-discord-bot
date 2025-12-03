from aiohttp import web
import asyncio
import os

# Import der Dummy-Funktionen aus shared.py
from shared import fetch_upcoming_events, fetch_results

# ===========================
# API HANDLER
# ===========================

async def api_upcoming(request):
    try:
        items = await fetch_upcoming_events()
        return web.json_response({"items": items[:5]})
    except Exception as e:
        print("[API] Error upcoming:", e)
        return web.json_response({"items": []})

async def api_results(request):
    try:
        items = await fetch_results()
        return web.json_response({"items": items[:5]})
    except Exception as e:
        print("[API] Error results:", e)
        return web.json_response({"items": []})

async def health(request):
    return web.json_response({"status": "ok"})


# ===========================
# SERVER START
# ===========================

async def start_api():
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/api/upcoming", api_upcoming)
    app.router.add_get("/api/results", api_results)

    port = int(os.getenv("PORT", 10000))
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"[API] running on port {port}")

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(start_api())
