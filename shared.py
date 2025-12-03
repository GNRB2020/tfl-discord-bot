import os
import pytz
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import datetime
import discord

# ========== CONFIG ==========
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0"))
RESULTS_CHANNEL_ID = int(os.getenv("RESULTS_CHANNEL_ID", "0"))
EVENT_CHANNEL_ID = int(os.getenv("DISCORD_EVENT_CHANNEL_ID", "0"))

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


# =========================================================
# DISCORD CLIENT (nur für API-Fetch – KEIN Bot!)
# =========================================================
intents = discord.Intents.none()
_api_client = discord.Client(intents=intents)


# =========================================================
# DISCORD FETCH: UPCOMING EVENTS
# =========================================================
async def fetch_upcoming_events():
    """Lädt alle kommenden Discord-Events."""
    try:
        await _api_client.login(TOKEN)
        guild = await _api_client.fetch_guild(GUILD_ID)
        events = await guild.fetch_scheduled_events()

        now = datetime.datetime.now(tz=BERLIN_TZ)
        upcoming = []

        for ev in events:
            if ev.start_time and ev.start_time > now:
                upcoming.append({
                    "name": ev.name,
                    "description": ev.description,
                    "start": ev.start_time.isoformat(),
                    "url": ev.url,
                    "location": ev.location,
                })

        return upcoming

    except Exception as e:
        print("[API] Fehler in fetch_upcoming_events:", e)
        return []

    finally:
        try:
            await _api_client.close()
        except:
            pass


# =========================================================
# DISCORD FETCH: RESULTS (Vergangene Events)
# =========================================================
async def fetch_results():
    """Lädt die letzten abgeschlossenen Discord-Events."""
    try:
        await _api_client.login(TOKEN)
        guild = await _api_client.fetch_guild(GUILD_ID)
        events = await guild.fetch_scheduled_events()

        now = datetime.datetime.now(tz=BERLIN_TZ)
        results = []

        for ev in events:
            if ev.end_time and ev.end_time < now:
                results.append({
                    "name": ev.name,
                    "description": ev.description,
                    "time": ev.end_time.isoformat(),
                    "content": ev.description or "",
                })

        # neueste zuerst
        results.sort(key=lambda x: x["time"], reverse=True)
        return results

    except Exception as e:
        print("[API] Fehler in fetch_results:", e)
        return []

    finally:
        try:
            await _api_client.close()
        except:
            pass
