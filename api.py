# =========================================================
# TFL Discord API – Vollständige funktionierende Version
# =========================================================

import os
import asyncio
import datetime
from aiohttp import web

from shared import (
    BERLIN_TZ,
    _cell,
    GUILD_ID,
    RESULTS_CHANNEL_ID,
    fetch_upcoming_events,
    fetch_results,
    sheets_required,
)

# =========================================================
# Global Cache
# =========================================================
_API_CACHE = {
    "upcoming": {"ts": None, "data": []},
    "results": {"ts": None, "data": []},
}

API_CACHE_TTL = datetime.timedelta(minutes=10)


# =========================================================
# API Handler
# =========================================================
async def api_upcoming_handler(request):
    data = _API_CACHE["upcoming"]["data"]
    return web.json_response({"items": data[:20]})


async def api_results_handler(request):
    data = _API_CACHE["results"]["data"]
    return web.json_response({"items": data[:20]})


async def health_handler(request):
    return web.json_response({"status": "ok"})


# =========================================================
# Hintergrund-Loop: Discord Events abholen + Cache aktualisieren
# =========================================================
async def fetch_loop():
    import traceback

    print("[API] Starte Hintergrund-Update-Loop…")

    while True:
        try:
            # Upcoming Events laden
            up = await fetch_upcoming_events()
            if isinstance(up, list):
                _API_CACHE["upcoming"]["data"] = up
                print(f"[CACHE] Upcoming aktualisiert ({len(up)} Events)")
            else:
                print("[CACHE] Upcoming: Fehler oder None")

            # Results laden
            res = await fetch_results()
            if isinstance(res, list):
                _API_CACHE["results"]["data"] = res
                print(f"[CACHE] Results aktualisiert ({len(res)} Einträge)")
            else:
                print("[CACHE] Results: Fehler oder None")

        except Exception as e:
            print("[API] Fehler im Fetch-Loop:", e)
            traceback.print_exc()

        await asyncio.sleep(60)  # 60 Sekunden Pause


# =========================================================
# API Server starten
# =========================================================
async def start_api():
    app = web.Application()
    app.add_routes([
        web.get("/health", health_handler),
        web.get("/api/upcoming", api_upcoming_handler),
        web.get("/api/results", api_results_handler),
    ])

    # Hintergrundtask starten
    asyncio.create_task(fetch_loop())

    port = int(os.getenv("PORT", "10000"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)

    print(f"[API] Starte Server auf Port {port} …")
    await site.start()

    # API läuft für immer, kein Exit
    while True:
        await asyncio.sleep(3600)


# =========================================================
# ENTRYPOINT
# =========================================================
if __name__ == "__main__":
    asyncio.run(start_api())
