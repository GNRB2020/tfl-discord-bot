import os
import pytz
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import datetime

# ========== CONFIG ==========
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))
RESULTS_CHANNEL_ID = int(os.getenv("RESULTS_CHANNEL_ID", "0"))

BERLIN_TZ = pytz.timezone("Europe/Berlin")

SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

CREDS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
SPREADSHEET_TITLE = os.getenv("SPREADSHEET_TITLE", "Season #4 - Spielbetrieb")

# ========== SHEETS ==========
SHEETS_ENABLED = True
GC = WB = None

try:
    CREDS = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    GC = gspread.authorize(CREDS)
    WB = GC.open(SPREADSHEET_TITLE)
except Exception:
    SHEETS_ENABLED = False
    WB = None

def sheets_required():
    if not SHEETS_ENABLED:
        raise RuntimeError("Google Sheets nicht verbunden")
    if WB is None:
        raise RuntimeError("Workbook fehlt")

def _cell(row, idx0):
    return row[idx0].strip() if 0 <= idx0 < len(row) else ""

# ============================================================
# FETCH FUNCTIONS FÜR DIE API
# ============================================================

async def fetch_upcoming_events():
    """
    Gibt Events für die Website zurück (5-20 kommende Spiele)
    Rückgabeformat: Liste von dicts
    """
    sheets_required()
    ws = WB.worksheet("League & Cup Schedule")
    all_rows = ws.get_all_values()

    result = []
    now = datetime.datetime.now(BERLIN_TZ)

    for r in all_rows[1:]:
        div = _cell(r, 0)
        date = _cell(r, 1)
        time = _cell(r, 2)
        p1 = _cell(r, 3)
        p2 = _cell(r, 4)
        mode = _cell(r, 5)
        link = _cell(r, 6)

        if not date or not time:
            continue

        try:
            dt = datetime.datetime.strptime(f"{date} {time}", "%d.%m.%Y %H:%M")
            dt = BERLIN_TZ.localize(dt)
        except:
            continue

        if dt >= now:
            result.append({
                "name": f"{p1} vs {p2}",
                "start": dt.isoformat(),
                "location": link,
                "description": f"Division {div}",
            })

    # Sortieren nach Datum
    result.sort(key=lambda x: x["start"])

    return result


async def fetch_results():
    """
    Holt fertige Ergebnisse aus dem RESULTS_CHANNEL.
    Rückgabeformat: Liste von dicts
    """
    import discord
    from discord import Intents

    if RESULTS_CHANNEL_ID == 0:
        return []

    intents = Intents.default()
    client = discord.Client(intents=intents)

    messages = []

    async def runner():
        await client.login(TOKEN)
        await client.connect()

    async def fetch_msgs():
        await client.wait_until_ready()
        channel = client.get_channel(RESULTS_CHANNEL_ID)
        async for msg in channel.history(limit=50):
            messages.append({
                "content": msg.content,
                "time": msg.created_at.replace(tzinfo=datetime.timezone.utc).astimezone(BERLIN_TZ).isoformat()
            })
        await client.close()

    client.loop.create_task(fetch_msgs())
    await runner()

    # Nur Messages mit Content
    return [m for m in messages if m["content"]]
