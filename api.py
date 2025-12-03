import os
import asyncio
import datetime
from aiohttp import web
from shared import (
    BERLIN_TZ,
    _cell,
    sheets_required,
    WB
)

# ---------------------------------------------------------
# CACHE
# ---------------------------------------------------------
CACHE = {
    "upcoming": [],
    "results": []
}
CACHE_TS = {
    "upcoming": None,
    "results": None
}

CACHE_TTL = datetime.timedelta(minutes=10)


# ---------------------------------------------------------
# FETCH UPCOMING
# ---------------------------------------------------------
async def fetch_upcoming_events():
    sheets_required()
    ws = WB.worksheet("League & Cup Schedule")

    rows = ws.get_all_values()
    now = datetime.datetime.now(BERLIN_TZ)

    events = []
    for r in rows[1:]:
        div = _cell(r, 0)
        date = _cell(r, 1)
        time = _cell(r, 2)
        p1 = _cell(r, 3)
        p2 = _cell(r, 4)

        if not date or not time:
            continue

        try:
            dt = datetime.datetime.strptime(
                f"{date} {time}", "%d.%m.%Y %H:%M"
            )
            dt = BERLIN_TZ.localize(dt)
        except:
            continue

        if dt >= now:
            events.append({
                "division": div,
                "datetime": dt.isoformat(),
                "player1": p1,
                "player2": p2
            })

    events.sort(key=lambda x: x["datetime"])
    return events


# ---------------------------------------------------------
# FETCH RESULTS
# ---------------------------------------------------------
async def fetch_results():
    sheets_required()
    ws = WB.worksheet("League & Cup Results")

    rows = ws.get_all_values()
    results = []

    for r in rows[1:]:
        div = _cell(r, 0)
        date = _cell(r, 1)
        p1 = _cell(r, 2)
        p2 = _cell(r, 3)
        score = _cell(r, 4)

        if not date or not score:
            continue

        results.append({
            "division": div,
            "date": date,
            "player1": p1,
            "player2": p2,
            "score": score
        })

    return results


# ---------------------------------------------------------
# LOOP
# ---------------------------------------------------------
async def fetch_loop():
    while True:
        try:
            up = await fetch_upcoming_events()
            CACHE["upcoming"] = up
            CACHE_TS["upcoming"] = datetime.datetime.now(BERLIN_TZ)
            print(f"[CACHE] Upcoming aktualisiert ({len(up)} Events)")

            res = await fetch_results()
            CACHE["results"] = res
            CACHE_TS["results"] = datetime.datetime.now(BERLIN_TZ)
            print(f"[CACHE] Results aktualisiert ({len(res)} Einträge)")

        except Exception as e:
            print("[CACHE ERROR]", e)

        await asyncio.sleep(60)


# ---------------------------------------------------------
# HTTP HANDLER
# ---------------------------------------------------------
async def handle_upcoming(request):
    return web.json_response({"items": CACHE["upcoming"][:5]})


async def handle_results(request):
    return web.json_response({"items": CACHE["results"][:5]})


async def health(request):
    return web.json_response({"status": "ok"})


# ---------------------------------------------------------
# START
# ---------------------------------------------------------
async def start_api():
    app = web.Application()
    app.add_routes([
        web.get("/health", health),
        web.get("/api/upcoming", handle_upcoming),
        web.get("/api/results", handle_results),
    ])

    # Fetch-Loop starten
    asyncio.create_task(fetch_loop())

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
