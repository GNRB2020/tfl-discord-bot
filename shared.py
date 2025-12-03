# shared.py – FINAL STABLE VERSION
# Keine Sheets!
# Kein Google!
# Nur API-Cache.

API_CACHE_UPCOMING = []
API_CACHE_RESULTS = []

def cache_set_upcoming(items):
    global API_CACHE_UPCOMING
    API_CACHE_UPCOMING = items

def cache_set_results(items):
    global API_CACHE_RESULTS
    API_CACHE_RESULTS = items

# Diese IDs nutzt der Bot – NICHT die API
import os

GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0"))
RESULTS_CHANNEL_ID = int(os.getenv("RESULTS_CHANNEL_ID", "0"))
