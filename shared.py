import os
import pytz
import datetime

# ========== KONFIGURATION ==========
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0"))
RESULTS_CHANNEL_ID = int(os.getenv("RESULTS_CHANNEL_ID", "0"))

BERLIN_TZ = pytz.timezone("Europe/Berlin")

# ========== GLOBALER CACHE ==========
API_CACHE_UPCOMING = []   # vom Bot befüllt
API_CACHE_RESULTS = []    # vom Bot befüllt

API_CACHE_TIMESTAMP = {
    "upcoming": None,
    "results": None
}

API_CACHE_TTL = datetime.timedelta(minutes=10)

def cache_set_upcoming(items):
    global API_CACHE_UPCOMING
    API_CACHE_UPCOMING = items
    API_CACHE_TIMESTAMP["upcoming"] = datetime.datetime.now(tz=BERLIN_TZ)

def cache_set_results(items):
    global API_CACHE_RESULTS
    API_CACHE_RESULTS = items
    API_CACHE_TIMESTAMP["results"] = datetime.datetime.now(tz=BERLIN_TZ)
