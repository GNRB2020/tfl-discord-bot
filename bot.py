import os
print("BOT FILE PATH:", os.path.abspath(__file__))

import asyncio
import datetime
import re
import sys
import traceback
from datetime import datetime as dt, timedelta

import aiohttp
import discord
import gspread
import pytz
from aiohttp import web
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials

from sheet_guard import (
    col_values_cached,
    get_all_values_cached,
    sheet_write_call,
)
from tfnl_ranking_api_sync import publish_tfnl_rankings_to_api
from sheets_connection import get_season_spreadsheet, get_season_worksheet
from division_tables import division_table_loop

print("🔍 DEBUG: bot.py wurde geladen")

BOT_PERFORMANCE_VERSION = "bot-performance-v6-admin-runner-twitch"
print(f"[BOT] geladen: {BOT_PERFORMANCE_VERSION}")


def _fatal(e: Exception):
    print("FATAL ERROR BEFORE on_ready():", e)
    traceback.print_exc()
    sys.exit(1)


# =========================================================
# .env laden / Konfiguration
# =========================================================
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0"))
EVENT_CHANNEL_ID = int(os.getenv("EVENT_CHANNEL_ID", os.getenv("DISCORD_EVENT_CHANNEL_ID", "0")))
RESTREAM_CHANNEL_ID = int(os.getenv("RESTREAM_CHANNEL_ID", "0"))
SHOWRESTREAMS_CHANNEL_ID = int(os.getenv("SHOWRESTREAMS_CHANNEL_ID", "1277949546650931241"))
CREDS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", "0"))
TFL_ROLE_ID = int(os.getenv("TFL_ROLE_ID", "0"))
RESULTS_CHANNEL_ID = int(os.getenv("RESULTS_CHANNEL_ID", "1275077562984435853"))
ZSR_RESTREAM_URL = os.getenv("ZSR_RESTREAM_URL", "https://www.twitch.tv/zeldaspeedruns")
SPREADSHEET_TITLE = os.getenv("SPREADSHEET_TITLE", "Season #4 - Spielbetrieb")
API_BASE = os.getenv("TFL_API_BASE", "https://tfl-discord-api.onrender.com")

print("DEBUG CREDS_FILE =", CREDS_FILE)

BERLIN_TZ = pytz.timezone("Europe/Berlin")
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

BOT_SHEET_CACHE_TTL_SECONDS = int(os.getenv("BOT_SHEET_CACHE_TTL_SECONDS", "90"))
BOT_PLAYER_CACHE_TTL_SECONDS = int(os.getenv("BOT_PLAYER_CACHE_TTL_SECONDS", "120"))
BOT_WEB_RESULTS_CACHE_TTL_SECONDS = int(os.getenv("BOT_WEB_RESULTS_CACHE_TTL_SECONDS", "60"))

# =========================================================
# Discord Client erstellen
# =========================================================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

print("DEBUG Intents:", intents)


DISABLED_MANUAL_COMMANDS = {
    "matchcenter",
    "showpicks",
    "result",
    "asyncplay",
    "cupresult",
    "cuptermin",
    "pick",
    "quali",
    "rest",
    "signup",
    "streich",
    "termin",
}


def remove_disabled_manual_commands(tree: app_commands.CommandTree, guild: discord.Object):
    """
    Entfernt nur die manuelle Slash-Command-Registrierung.
    Die Extensions bleiben geladen, damit Views/Buttons aus /player weiter funktionieren.
    """
    for cmd_name in DISABLED_MANUAL_COMMANDS:
        removed_global = tree.remove_command(cmd_name)
        removed_guild = tree.remove_command(cmd_name, guild=guild)

        if removed_global or removed_guild:
            print(f"🧹 Slash-Command deaktiviert: /{cmd_name}")


class TFLBot(commands.Bot):
    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)

        extensions = [
            "signup",
            "schedule",
            #"ladder",    #deaktiviert
            "matchcenter",
            "asnyc",
            "player",
            "restream_requests",
        ]

        for ext in extensions:
            try:
                await self.load_extension(ext)
                print(f"✅ {ext}.py geladen")
            except Exception:
                print(f"❌ FEHLER beim Laden von {ext}.py:")
                traceback.print_exc()
