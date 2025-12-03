import os
import pytz
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import datetime

# ===========================================
# API-Caches – werden vom Bot befüllt
# ===========================================
API_CACHE_UPCOMING = {"data": [], "ts": None}
API_CACHE_RESULTS  = {"data": [], "ts": None}

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
