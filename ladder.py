import os
import re
import random
import asyncio
import time
from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import aiohttp
import discord
import gspread
import pyz3r
import yaml
from discord import app_commands
from discord.ext import commands, tasks
from oauth2client.service_account import ServiceAccountCredentials

from sheet_guard import (
    get_all_records_cached,
    get_all_values_cached,
    row_values_cached,
    sheet_write_call,
    invalidate_cache as invalidate_global_sheet_cache,
    should_log_quota_warning,
    seconds_until_quota_retry,
)
from ladder_elo import create_elo_pairings
from ladder_elo_sheets import (
    SCOPE_SEASON_OVERALL,
    SCOPE_SEASON_MODE,
    SCOPE_ALLTIME_OVERALL,
    SCOPE_ALLTIME_MODE,
    ensure_ladder_elo_sheets,
    build_pairing_players,
    process_match_elo,
    rebuild_elo_from_matches,
    build_standings_rows as build_elo_standings_rows,
    get_match_elo_changes,
    get_slot_elo_changes,
)


# =========================================================
# TFNL SETTINGS
# =========================================================

GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0").strip())

TFNL_SPREADSHEET_ID = os.getenv(
    "TFNL_SPREADSHEET_ID",
    "1TamFbS5cRCcgSJFoQEohXdv03tVhk0VynvleeiVBQsM",
).strip()

CREDS_FILE = os.getenv(
    "GOOGLE_CREDENTIALS_FILE",
    os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials.json"),
).strip()

TFNL_SCHEDULE_CHANNEL_ID = int(
    os.getenv("TFNL_SCHEDULE_CHANNEL_ID", "1502031472574337204").strip()
)

TFNL_SIGNUP_CHANNEL_ID = int(
    os.getenv("TFNL_SIGNUP_CHANNEL_ID", "1502062610227531877").strip()
)

TFNL_LADDER_ROLE_ID = int(
    os.getenv("TFNL_LADDER_ROLE_ID", "1502062912552833185").strip()
)

TFNL_CATEGORY_ID = int(
    os.getenv("TFNL_CATEGORY_ID", "1502014179803005009").strip()
)

TFNL_LOG_CHANNEL_ID = int(
    os.getenv("TFNL_LOG_CHANNEL_ID", "1494265084208222208").strip()
)

TFNL_STANDINGS_CHANNEL_ID = int(
    os.getenv("TFNL_STANDINGS_CHANNEL_ID", "1502236644290465892").strip()
)

TFNL_RESULTS_CHANNEL_ID = int(
    os.getenv("TFNL_RESULTS_CHANNEL_ID", "1503146168589353001").strip()
)

BERLIN_TZ = ZoneInfo("Europe/Berlin")

LADDER_PERFORMANCE_PATCH_VERSION = "ladder-output-v32-v31-transient-fix-on-current-base"
print(f"[TFNL LADDER] geladen: {LADDER_PERFORMANCE_PATCH_VERSION}")

TFNL_LOOP_INTERVAL_SECONDS = int(
    os.getenv("TFNL_LOOP_INTERVAL_SECONDS", "10").strip()
)

TFNL_STARTUP_STAGGER_SECONDS = int(
    os.getenv("TFNL_STARTUP_STAGGER_SECONDS", "45").strip()
)

TFNL_AUTO_EVALUATE_INTERVAL_MINUTES = int(
    os.getenv("TFNL_AUTO_EVALUATE_INTERVAL_MINUTES", "3").strip()
)

TFNL_STANDINGS_PUBLISH_DELAY_SECONDS = int(
    os.getenv("TFNL_STANDINGS_PUBLISH_DELAY_SECONDS", "120").strip()
)

TFNL_AUTO_PUBLISH_STANDINGS_AFTER_SLOT = (
    os.getenv("TFNL_AUTO_PUBLISH_STANDINGS_AFTER_SLOT", "1").strip().lower()
    not in ("0", "false", "no", "nein", "off")
)

TFNL_FF_PENALTY_FREE_COUNT = int(
    os.getenv("TFNL_FF_PENALTY_FREE_COUNT", "4").strip()
)

TFNL_FF_PENALTY_POINTS = int(
    os.getenv("TFNL_FF_PENALTY_POINTS", "2").strip()
)

SCHEDULE_SHEET_NAME = "Schedule"
SIGNUP_SHEET_NAME = "Signup"
MATCHES_SHEET_NAME = "Matches"
PLAYERS_SHEET_NAME = "Players"
SETTINGS_SHEET_NAME = "Settings"

ARCHIVE_SCHEDULE_SHEET_NAME = "Archive_Schedule"
ARCHIVE_SIGNUP_SHEET_NAME = "Archive_Signup"
ARCHIVE_MATCHES_SHEET_NAME = "Archive_Matches"
ARCHIVE_PLAYERS_SHEET_NAME = "Archive_Players"

DEFAULT_ACTIVE_SEASON = os.getenv("TFNL_ACTIVE_SEASON", "TFNL-S1").strip()

SCHEDULE_ANNOUNCEMENT_COL = "Signup Announcement Sent"
SCHEDULE_COMPLETED_AT_COL = "Completed At"
SCHEDULE_PRESTART_DM_COL = "Prestart DM Sent"

SAHASRAHBOT_PRESET_BASE_URL = (
    "https://raw.githubusercontent.com/tcprescott/sahasrahbot/master/presets/alttpr"
)

SIGNUP_HEADERS = [
    "Slot ID",
    "Discord ID",
    "Discord Display Name",
    "Angemeldet um",
    "DM geprüft",
    "Status",
    "Season",
]

MATCHES_HEADERS = [
    "Match ID",
    "Slot ID",
    "Matchtyp",
    "Spieler 1 Discord ID",
    "Spieler 1 Name",
    "Spieler 2 Discord ID",
    "Spieler 2 Name",
    "Spieler 3 Discord ID",
    "Spieler 3 Name",
    "Seed URL",
    "Startzeit",
    "Zeit Spieler 1",
    "Zeit Spieler 2",
    "Zeit Spieler 3",
    "Ergebnis Spieler 1",
    "Ergebnis Spieler 2",
    "Ergebnis Spieler 3",
    "Punkte Spieler 1",
    "Punkte Spieler 2",
    "Punkte Spieler 3",
    "Status",
    "Veröffentlicht",
    "Season",
]

PLAYERS_HEADERS = [
    "Discord ID",
    "Discord Display Name",
    "Punkte",
    "Starts",
    "Siege",
    "Remis",
    "Niederlagen",
    "Forfeits",
    "Letzter Gegner",
    "Letzter Start",
    "Season",
]

SETTINGS_HEADERS = [
    "Key",
    "Value",
]

SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

HEADER_CACHE = {}
WORKSHEET_CACHE = {}
SPREADSHEET_CACHE = None

# Rebuild + Tabellenposting liest live + archivierte Sheets.
# 45 Sekunden waren für größere Seasons zu knapp, weil direkt nach einem
# Rebuild mehrere Tabellen nacheinander gebaut werden. 300 Sekunden reduziert
# Google-Sheets-Reads deutlich, ohne den laufenden Slotbetrieb zu verfälschen.
SHEET_READ_CACHE_TTL_SECONDS = int(
    os.getenv("TFNL_SHEET_CACHE_TTL_SECONDS", "300").strip()
)

TFNL_TRANSIENT_ERROR_BACKOFF_SECONDS = int(
    os.getenv("TFNL_TRANSIENT_ERROR_BACKOFF_SECONDS", "30").strip()
)

TFNL_TRANSIENT_ERROR_LOG_COOLDOWN_SECONDS = int(
    os.getenv("TFNL_TRANSIENT_ERROR_LOG_COOLDOWN_SECONDS", "3600").strip()
)

TRANSIENT_GOOGLE_ERROR_LOG_AT: dict[str, float] = {}


def is_transient_google_api_error(error_text: str) -> bool:
    """
    Erkennt temporäre Google-/Netzwerkfehler, die bei späterem Versuch
    normalerweise von allein verschwinden. Diese Fehler dürfen den Admin-Log
    nicht im Minutentakt fluten.
    """
    value = normalize_text(error_text).lower()

    transient_markers = (
        "[500]",
        "internal error encountered",
        "[502]",
        "[503]",
        "backend error",
        "temporarily unavailable",
        "connection reset",
        "connection aborted",
        "connectionreseterror",
        "protocolerror",
        "read timed out",
        "timed out",
        "timeout",
        "ssl",
    )

    return any(marker in value for marker in transient_markers)


def should_log_transient_google_error(scope: str) -> bool:
    now = time.monotonic()
    last = TRANSIENT_GOOGLE_ERROR_LOG_AT.get(scope, 0.0)

    if now - last >= TFNL_TRANSIENT_ERROR_LOG_COOLDOWN_SECONDS:
        TRANSIENT_GOOGLE_ERROR_LOG_AT[scope] = now
        return True

    return False



def invalidate_sheet_cache(sheet_name: str | None = None):
    if sheet_name is None:
        invalidate_global_sheet_cache()
        HEADER_CACHE.clear()
        return

    invalidate_global_sheet_cache(f"records:{sheet_name}")
    invalidate_global_sheet_cache(f"values:{sheet_name}")
    invalidate_global_sheet_cache(f"row:{sheet_name}:")
    invalidate_global_sheet_cache(f"col:{sheet_name}:")
    invalidate_global_sheet_cache(f"cell:{sheet_name}:")


def get_cached_records(
    sheet_name: str,
    sheet_getter,
    ttl_seconds: int = SHEET_READ_CACHE_TTL_SECONDS,
    force_refresh: bool = False,
):
    return get_all_records_cached(
        sheet_getter,
        sheet_name=sheet_name,
        ttl_seconds=ttl_seconds,
        force_refresh=force_refresh,
    )
# =========================================================
# MODE / PRESET MAPPING

# =========================================================
# MODE / PRESET MAPPING
# =========================================================

TFNL_MODE_PRESETS = {
    "casual boots": "casualboots",
    "open": "open",
    "inverted": "inverted",
    "open ad boots": "adboots",
    "invrosia": "invrosia",
    "ambrosia": "ambrosia",
    "ludicrous speed": "ludicrousspeed",
    "hard standard": "standhard",
    "standard": "standard",
    "tfl hard standard": "mormacil/harder_standard",
    "keysanity": "keysanity",
    "ad keysanity mit boots": "adkeys_boots",
    "ad keys": "adkeys",
    "mc boss": "phoenix-aut/mcboss",
    "influkeys": "alttprleague/influkeys",
    "crosskeys": "crosskeys",
}

TFNL_MODE_ALIASES = {
    "casualboots": "casual boots",
    "boots": "casual boots",

    "ad boots": "open ad boots",
    "open adboots": "open ad boots",
    "adboots": "open ad boots",

    "ludi": "ludicrous speed",
    "ludicrousspeed": "ludicrous speed",

    "hardstandard": "hard standard",
    "hard std": "hard standard",
    "standhard": "hard standard",

    "tfl hard": "tfl hard standard",
    "harder standard": "tfl hard standard",
    "mormacil/harder_standard": "tfl hard standard",

    "adkeys boots": "ad keysanity mit boots",
    "adkeys mit boots": "ad keysanity mit boots",
    "ad keys boots": "ad keysanity mit boots",
    "adkeys_boots": "ad keysanity mit boots",

    "adkeys": "ad keys",

    "xkeys": "crosskeys",
    "cross keys": "crosskeys",

    "mcboss": "mc boss",
    "phoenix-aut/mcboss": "mc boss",
}


print("DEBUG TFNL_SPREADSHEET_ID =", repr(TFNL_SPREADSHEET_ID))
print("DEBUG TFNL CREDS_FILE =", repr(CREDS_FILE))
print("DEBUG TFNL_SCHEDULE_CHANNEL_ID =", TFNL_SCHEDULE_CHANNEL_ID)
print("DEBUG TFNL_SIGNUP_CHANNEL_ID =", TFNL_SIGNUP_CHANNEL_ID)
print("DEBUG TFNL_LADDER_ROLE_ID =", TFNL_LADDER_ROLE_ID)
print("DEBUG TFNL_CATEGORY_ID =", TFNL_CATEGORY_ID)
print("DEBUG TFNL_LOG_CHANNEL_ID =", TFNL_LOG_CHANNEL_ID)
print("DEBUG TFNL_STANDINGS_CHANNEL_ID =", TFNL_STANDINGS_CHANNEL_ID)


# =========================================================
# GOOGLE SHEETS
# =========================================================

def normalize_text(value) -> str:
    return str(value or "").strip()


def get_tfnl_spreadsheet():
    global SPREADSHEET_CACHE

    if SPREADSHEET_CACHE is not None:
        return SPREADSHEET_CACHE

    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    client = gspread.authorize(creds)
    SPREADSHEET_CACHE = client.open_by_key(TFNL_SPREADSHEET_ID)
    return SPREADSHEET_CACHE


def ensure_header_column(sheet, sheet_name: str, column_name: str):
    headers = HEADER_CACHE.get(sheet_name)

    if headers is None:
        headers = row_values_cached(
            lambda: sheet,
            sheet_name=sheet_name,
            row=1,
            ttl_seconds=300,
        )
        HEADER_CACHE[sheet_name] = headers

    if column_name not in headers:
        next_col = len(headers) + 1

        sheet_write_call(
            lambda: sheet.update_cell(1, next_col, column_name),
            invalidate_prefixes=[
                f"records:{sheet_name}",
                f"values:{sheet_name}",
                f"row:{sheet_name}:",
            ],
        )

        headers.append(column_name)
        HEADER_CACHE[sheet_name] = headers

def get_or_create_worksheet(
    spreadsheet,
    title: str,
    headers: list[str],
    rows: int = 1000,
    cols: int = 30,
):
    cached_sheet = WORKSHEET_CACHE.get(title)

    if cached_sheet is not None:
        return cached_sheet

    try:
        sheet = spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)

    existing_headers = row_values_cached(
        lambda: sheet,
        sheet_name=title,
        row=1,
        ttl_seconds=300,
    )

    if existing_headers != headers:
        sheet_write_call(
            lambda: sheet.update("A1", [headers]),
            invalidate_prefixes=[
                f"records:{title}",
                f"values:{title}",
                f"row:{title}:",
            ],
        )
        HEADER_CACHE[title] = headers
    else:
        HEADER_CACHE[title] = existing_headers

    WORKSHEET_CACHE[title] = sheet
    return sheet

def get_settings_sheet():
    spreadsheet = get_tfnl_spreadsheet()
    return get_or_create_worksheet(
        spreadsheet=spreadsheet,
        title=SETTINGS_SHEET_NAME,
        headers=SETTINGS_HEADERS,
        rows=100,
        cols=len(SETTINGS_HEADERS),
    )


def get_setting_value(key: str, default: str = "") -> str:
    sheet = get_settings_sheet()
    rows = get_cached_records(SETTINGS_SHEET_NAME, get_settings_sheet)

    for row in rows:
        if normalize_text(row.get("Key")) == key:
            value = normalize_text(row.get("Value"))
            return value or default

    sheet_write_call(
        lambda: sheet.append_row([key, default], value_input_option="USER_ENTERED"),
        invalidate_prefixes=[
            f"records:{SETTINGS_SHEET_NAME}",
            f"values:{SETTINGS_SHEET_NAME}",
        ],
    )
    return default

def get_active_season() -> str:
    return get_setting_value("ACTIVE_SEASON", DEFAULT_ACTIVE_SEASON)


def row_matches_season(row: dict, season: str) -> bool:
    return normalize_text(row.get("Season")) == normalize_text(season)


def filter_rows_by_season(rows: list[dict], season: str | None = None) -> list[dict]:
    selected_season = normalize_text(season) or get_active_season()
    return [row for row in rows if row_matches_season(row, selected_season)]


def get_active_season_for_row(row: dict | None = None) -> str:
    if row:
        season = normalize_text(row.get("Season"))
        if season:
            return season

    return get_active_season()


def get_header_index(sheet, sheet_name: str, column_name: str):
    if sheet_name not in HEADER_CACHE:
        HEADER_CACHE[sheet_name] = row_values_cached(
            lambda: sheet,
            sheet_name=sheet_name,
            row=1,
            ttl_seconds=300,
        )

    headers = HEADER_CACHE[sheet_name]

    try:
        return headers.index(column_name) + 1
    except ValueError:
        return None

def get_schedule_sheet():
    cached_sheet = WORKSHEET_CACHE.get(SCHEDULE_SHEET_NAME)

    if cached_sheet is not None:
        return cached_sheet

    spreadsheet = get_tfnl_spreadsheet()
    sheet = spreadsheet.worksheet(SCHEDULE_SHEET_NAME)

    ensure_header_column(sheet, SCHEDULE_SHEET_NAME, SCHEDULE_ANNOUNCEMENT_COL)
    ensure_header_column(sheet, SCHEDULE_SHEET_NAME, SCHEDULE_COMPLETED_AT_COL)
    ensure_header_column(sheet, SCHEDULE_SHEET_NAME, SCHEDULE_PRESTART_DM_COL)
    ensure_header_column(sheet, SCHEDULE_SHEET_NAME, "Season")

    WORKSHEET_CACHE[SCHEDULE_SHEET_NAME] = sheet
    return sheet


def get_signup_sheet():
    spreadsheet = get_tfnl_spreadsheet()
    return get_or_create_worksheet(
        spreadsheet=spreadsheet,
        title=SIGNUP_SHEET_NAME,
        headers=SIGNUP_HEADERS,
        rows=1000,
        cols=len(SIGNUP_HEADERS),
    )


def get_matches_sheet():
    spreadsheet = get_tfnl_spreadsheet()
    return get_or_create_worksheet(
        spreadsheet=spreadsheet,
        title=MATCHES_SHEET_NAME,
        headers=MATCHES_HEADERS,
        rows=1000,
        cols=len(MATCHES_HEADERS),
    )


def get_players_sheet():
    spreadsheet = get_tfnl_spreadsheet()
    return get_or_create_worksheet(
        spreadsheet=spreadsheet,
        title=PLAYERS_SHEET_NAME,
        headers=PLAYERS_HEADERS,
        rows=1000,
        cols=len(PLAYERS_HEADERS),
    )


def load_schedule_rows_all(force_refresh: bool = False):
    return get_cached_records(
        SCHEDULE_SHEET_NAME,
        get_schedule_sheet,
        force_refresh=force_refresh,
    )


def load_schedule_rows(force_refresh: bool = False):
    return filter_rows_by_season(load_schedule_rows_all(force_refresh=force_refresh))


def load_schedule_rows_with_index(force_refresh: bool = False):
    selected_season = get_active_season()
    rows = load_schedule_rows_all(force_refresh=force_refresh)
    return [
        (index, row)
        for index, row in enumerate(rows, start=2)
        if row_matches_season(row, selected_season)
    ]


def load_signup_rows_all(force_refresh: bool = False):
    return get_cached_records(
        SIGNUP_SHEET_NAME,
        get_signup_sheet,
        force_refresh=force_refresh,
    )


def load_signup_rows(force_refresh: bool = False):
    return filter_rows_by_season(load_signup_rows_all(force_refresh=force_refresh))


def load_signup_rows_with_index(force_refresh: bool = False):
    selected_season = get_active_season()
    rows = load_signup_rows_all(force_refresh=force_refresh)
    return [
        (index, row)
        for index, row in enumerate(rows, start=2)
        if row_matches_season(row, selected_season)
    ]


def load_matches_rows_all(force_refresh: bool = False):
    return get_cached_records(
        MATCHES_SHEET_NAME,
        get_matches_sheet,
        force_refresh=force_refresh,
    )


def load_matches_rows(force_refresh: bool = False):
    return filter_rows_by_season(load_matches_rows_all(force_refresh=force_refresh))


def load_matches_rows_with_index(force_refresh: bool = False):
    selected_season = get_active_season()
    rows = load_matches_rows_all(force_refresh=force_refresh)
    return [
        (index, row)
        for index, row in enumerate(rows, start=2)
        if row_matches_season(row, selected_season)
    ]


def load_players_rows_all():
    return get_cached_records(PLAYERS_SHEET_NAME, get_players_sheet)


def load_players_rows():
    return filter_rows_by_season(load_players_rows_all())


def load_players_rows_with_index():
    selected_season = get_active_season()
    rows = load_players_rows_all()
    return [
        (index, row)
        for index, row in enumerate(rows, start=2)
        if row_matches_season(row, selected_season)
    ]


def get_archive_sheet_name_for_source(source_sheet_name: str) -> str:
    mapping = {
        SCHEDULE_SHEET_NAME: ARCHIVE_SCHEDULE_SHEET_NAME,
        SIGNUP_SHEET_NAME: ARCHIVE_SIGNUP_SHEET_NAME,
        MATCHES_SHEET_NAME: ARCHIVE_MATCHES_SHEET_NAME,
        PLAYERS_SHEET_NAME: ARCHIVE_PLAYERS_SHEET_NAME,
    }
    return mapping.get(source_sheet_name, "")


def load_archive_rows_for_source(source_sheet_name: str, force_refresh: bool = False) -> list[dict]:
    """
    Liest das passende Archive_* Sheet, falls es existiert.
    Fehlende Archive-Sheets liefern bewusst [] zurück.
    Diese Funktion erstellt keine Archive-Sheets.
    """
    archive_name = get_archive_sheet_name_for_source(source_sheet_name)

    if not archive_name:
        return []

    archive_sheet = WORKSHEET_CACHE.get(archive_name)

    if archive_sheet is None:
        try:
            spreadsheet = get_tfnl_spreadsheet()
            archive_sheet = spreadsheet.worksheet(archive_name)
            WORKSHEET_CACHE[archive_name] = archive_sheet
        except gspread.WorksheetNotFound:
            return []

    return get_all_records_cached(
        lambda archive_sheet=archive_sheet: archive_sheet,
        sheet_name=archive_name,
        ttl_seconds=SHEET_READ_CACHE_TTL_SECONDS,
        force_refresh=force_refresh,
    )


def merge_live_and_archive_rows(source_sheet_name: str, live_rows: list[dict], archive_rows: list[dict]) -> list[dict]:
    """
    Kombiniert Archive + Live ohne Dopplungen.
    Falls eine Zeile in beiden Bereichen existiert, gewinnt Live.
    Dadurch bleibt delete_from_live=False ungefährlich, und delete_from_live=True
    funktioniert ebenfalls sauber.
    """
    merged: dict[str, dict] = {}

    for row in archive_rows:
        season = get_active_season_for_row(row)
        key = get_archive_unique_key(source_sheet_name, row, season)
        if key:
            merged[key] = row

    for row in live_rows:
        season = get_active_season_for_row(row)
        key = get_archive_unique_key(source_sheet_name, row, season)
        if key:
            merged[key] = row

    return list(merged.values())


def load_schedule_rows_all_combined(force_refresh: bool = False) -> list[dict]:
    return merge_live_and_archive_rows(
        SCHEDULE_SHEET_NAME,
        live_rows=load_schedule_rows_all(force_refresh=force_refresh),
        archive_rows=load_archive_rows_for_source(SCHEDULE_SHEET_NAME, force_refresh=force_refresh),
    )


def load_schedule_rows_combined(season: str | None = None, force_refresh: bool = False) -> list[dict]:
    return filter_rows_by_season(
        load_schedule_rows_all_combined(force_refresh=force_refresh),
        season,
    )


def load_matches_rows_all_combined(force_refresh: bool = False) -> list[dict]:
    return merge_live_and_archive_rows(
        MATCHES_SHEET_NAME,
        live_rows=load_matches_rows_all(force_refresh=force_refresh),
        archive_rows=load_archive_rows_for_source(MATCHES_SHEET_NAME, force_refresh=force_refresh),
    )


def load_matches_rows_combined(season: str | None = None, force_refresh: bool = False) -> list[dict]:
    return filter_rows_by_season(
        load_matches_rows_all_combined(force_refresh=force_refresh),
        season,
    )


def load_signup_rows_all_combined(force_refresh: bool = False) -> list[dict]:
    return merge_live_and_archive_rows(
        SIGNUP_SHEET_NAME,
        live_rows=load_signup_rows_all(force_refresh=force_refresh),
        archive_rows=load_archive_rows_for_source(SIGNUP_SHEET_NAME, force_refresh=force_refresh),
    )


def load_players_rows_all_combined(force_refresh: bool = False) -> list[dict]:
    return merge_live_and_archive_rows(
        PLAYERS_SHEET_NAME,
        live_rows=load_players_rows_all(),
        archive_rows=load_archive_rows_for_source(PLAYERS_SHEET_NAME, force_refresh=force_refresh),
    )


def append_signup(slot_id: str, user_id: int, display_name: str):
    now = datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M:%S")

    sheet_write_call(
        lambda: get_signup_sheet().append_row(
            [
                slot_id,
                str(user_id),
                display_name,
                now,
                "Ja",
                "signed_up",
                get_active_season(),
            ],
            value_input_option="USER_ENTERED",
        ),
        invalidate_prefixes=[
            f"records:{SIGNUP_SHEET_NAME}",
            f"values:{SIGNUP_SHEET_NAME}",
        ],
    )

def append_matches(match_rows: list[list]):
    if not match_rows:
        return

    sheet_write_call(
        lambda: get_matches_sheet().append_rows(
            match_rows,
            value_input_option="USER_ENTERED",
        ),
        invalidate_prefixes=[
            f"records:{MATCHES_SHEET_NAME}",
            f"values:{MATCHES_SHEET_NAME}",
        ],
    )

def find_schedule_row(slot_id: str):
    for row_index, row in load_schedule_rows_with_index():
        if normalize_text(row.get("Slot ID")) == slot_id:
            return row_index, row

    return None, None


def find_match_row(match_id: str):
    for row_index, row in load_matches_rows_with_index():
        if normalize_text(row.get("Match ID")) == match_id:
            return row_index, row

    return None, None


def update_schedule_cell(slot_id: str, column_name: str, value: str):
    sheet = get_schedule_sheet()
    row_index, _ = find_schedule_row(slot_id)

    if not row_index:
        return

    col_index = get_header_index(sheet, SCHEDULE_SHEET_NAME, column_name)

    if not col_index:
        return

    sheet_write_call(
        lambda: sheet.update_cell(row_index, col_index, value),
        invalidate_prefixes=[
            f"records:{SCHEDULE_SHEET_NAME}",
            f"values:{SCHEDULE_SHEET_NAME}",
            f"row:{SCHEDULE_SHEET_NAME}:",
            f"cell:{SCHEDULE_SHEET_NAME}:",
        ],
    )

def update_schedule_cells(slot_id: str, values: dict[str, str]):
    sheet = get_schedule_sheet()
    row_index, _ = find_schedule_row(slot_id)

    if not row_index:
        return

    requests = []

    for column_name, value in values.items():
        col_index = get_header_index(sheet, SCHEDULE_SHEET_NAME, column_name)

        if not col_index:
            continue

        requests.append(
            {
                "range": gspread.utils.rowcol_to_a1(row_index, col_index),
                "values": [[value]],
            }
        )

    if requests:
        sheet_write_call(
            lambda: sheet.batch_update(requests, value_input_option="USER_ENTERED"),
            invalidate_prefixes=[
                f"records:{SCHEDULE_SHEET_NAME}",
                f"values:{SCHEDULE_SHEET_NAME}",
                f"row:{SCHEDULE_SHEET_NAME}:",
                f"cell:{SCHEDULE_SHEET_NAME}:",
            ],
        )

def update_schedule_cell_by_row(row_index: int, column_name: str, value: str):
    sheet = get_schedule_sheet()
    col_index = get_header_index(sheet, SCHEDULE_SHEET_NAME, column_name)

    if not col_index:
        return

    sheet_write_call(
        lambda: sheet.update_cell(row_index, col_index, value),
        invalidate_prefixes=[
            f"records:{SCHEDULE_SHEET_NAME}",
            f"values:{SCHEDULE_SHEET_NAME}",
            f"row:{SCHEDULE_SHEET_NAME}:",
            f"cell:{SCHEDULE_SHEET_NAME}:",
        ],
    )

def normalize_slot_id_part(value: str) -> str:
    value = normalize_text(value).upper()
    value = re.sub(r"[^A-Z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "SLOT"


def build_base_slot_id(row: dict) -> str:
    parsed_date = parse_german_date(row.get("Datum"))
    date_part = parsed_date.isoformat() if parsed_date else normalize_slot_id_part(row.get("Datum"))
    slot_part = normalize_slot_id_part(row.get("Slot"))
    start_part = normalize_slot_id_part(normalize_text(row.get("Startzeit")).replace(":", ""))

    if start_part:
        return f"TFNL-{date_part}-{slot_part}-{start_part}"

    return f"TFNL-{date_part}-{slot_part}"


def make_unique_slot_id(row: dict, used_slot_ids: set[str]) -> str:
    base = build_base_slot_id(row)
    candidate = base
    counter = 2

    while candidate in used_slot_ids:
        candidate = f"{base}-{counter}"
        counter += 1

    return candidate


def ensure_unique_schedule_slot_ids() -> list[dict]:
    rows_with_index = load_schedule_rows_with_index()
    used_slot_ids = set()
    changes = []

    for row_index, row in rows_with_index:
        current_slot_id = normalize_text(row.get("Slot ID"))

        if current_slot_id and current_slot_id not in used_slot_ids:
            used_slot_ids.add(current_slot_id)
            continue

        old_slot_id = current_slot_id or ""
        new_slot_id = make_unique_slot_id(row, used_slot_ids)
        used_slot_ids.add(new_slot_id)

        update_schedule_cell_by_row(row_index, "Slot ID", new_slot_id)

        changes.append(
            {
                "row_index": row_index,
                "old_slot_id": old_slot_id,
                "new_slot_id": new_slot_id,
                "datum": normalize_text(row.get("Datum")),
                "slot": normalize_text(row.get("Slot")),
                "startzeit": normalize_text(row.get("Startzeit")),
            }
        )

    return changes


def update_match_cell(match_id: str, column_name: str, value: str):
    update_match_cells(match_id, {column_name: value})


def update_match_cells(match_id: str, values: dict[str, str]):
    sheet = get_matches_sheet()
    row_index, _ = find_match_row(match_id)

    if not row_index:
        return

    requests = []

    for column_name, value in values.items():
        col_index = get_header_index(sheet, MATCHES_SHEET_NAME, column_name)

        if not col_index:
            continue

        requests.append(
            {
                "range": gspread.utils.rowcol_to_a1(row_index, col_index),
                "values": [[value]],
            }
        )

    if requests:
        sheet_write_call(
            lambda: sheet.batch_update(requests, value_input_option="USER_ENTERED"),
            invalidate_prefixes=[
                f"records:{MATCHES_SHEET_NAME}",
                f"values:{MATCHES_SHEET_NAME}",
                f"row:{MATCHES_SHEET_NAME}:",
                f"cell:{MATCHES_SHEET_NAME}:",
            ],
        )

def update_schedule_status(slot_id: str, status: str):
    update_schedule_cell(slot_id, "Status", status)


def update_schedule_channel_id(slot_id: str, channel_id: int):
    update_schedule_cell(slot_id, "Slot Channel ID", str(channel_id))


def update_schedule_announcement_sent(slot_id: str):
    update_schedule_cell(slot_id, SCHEDULE_ANNOUNCEMENT_COL, "Ja")


def set_schedule_completed(slot_id: str):
    completed_at = datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M:%S")

    update_schedule_cells(
        slot_id,
        {
            "Status": "completed",
            SCHEDULE_COMPLETED_AT_COL: completed_at,
        },
    )

    return completed_at


def set_schedule_cancelled(slot_id: str):
    cancelled_at = datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M:%S")

    update_schedule_cells(
        slot_id,
        {
            "Status": "cancelled",
            SCHEDULE_COMPLETED_AT_COL: cancelled_at,
        },
    )

    return cancelled_at


# =========================================================
# TIME HELPERS
# =========================================================

def parse_german_date(value):
    if not value:
        return None

    value = normalize_text(value)

    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass

    return None


def parse_time(value):
    if not value:
        return None

    value = normalize_text(value)

    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            pass

    return None


def parse_completed_at(value):
    value = normalize_text(value)

    if not value:
        return None

    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.replace(tzinfo=BERLIN_TZ)
        except ValueError:
            pass

    return None


def build_datetime(date_value, time_value):
    parsed_date = parse_german_date(date_value)
    parsed_time = parse_time(time_value)

    if not parsed_date or not parsed_time:
        return None

    return datetime.combine(parsed_date, parsed_time, tzinfo=BERLIN_TZ)


def get_slot_start_dt(row: dict):
    return build_datetime(row.get("Datum"), row.get("Startzeit"))


def get_slot_end_dt(row: dict):
    start = get_slot_start_dt(row)
    end = build_datetime(row.get("Datum"), row.get("Ende"))

    if not start or not end:
        return end

    if end <= start:
        end += timedelta(days=1)

    return end


def is_registration_open(row: dict) -> bool:
    now = datetime.now(BERLIN_TZ)
    start = build_datetime(row.get("Datum"), row.get("Anmeldebeginn"))
    end = build_datetime(row.get("Datum"), row.get("Anmeldeschluss"))

    if not start or not end:
        return False

    return start <= now < end


def is_registration_due_for_pairing(row: dict) -> bool:
    now = datetime.now(BERLIN_TZ)
    deadline = build_datetime(row.get("Datum"), row.get("Anmeldeschluss"))

    if not deadline:
        return False

    return now >= deadline


def is_seed_due(row: dict) -> bool:
    start = get_slot_start_dt(row)

    if not start:
        return False

    return datetime.now(BERLIN_TZ) >= start - timedelta(minutes=5)


def is_prestart_dm_due(row: dict) -> bool:
    start = get_slot_start_dt(row)

    if not start:
        return False

    return datetime.now(BERLIN_TZ) >= start - timedelta(minutes=1)


def was_prestart_dm_sent(row: dict) -> bool:
    return normalize_text(row.get(SCHEDULE_PRESTART_DM_COL)).lower() == "ja"


def is_countdown_due(row: dict) -> bool:
    start = get_slot_start_dt(row)

    if not start:
        return False

    # Countdown-Tasks werden bewusst früh vorbereitet.
    # Die Task schläft intern bis exakt Startzeit -10 Sekunden.
    # Die Vorbereitung passiert weiterhin nur einmal über den Status countdown_sent.
    return datetime.now(BERLIN_TZ) >= start - timedelta(seconds=90)


def is_start_due(row: dict) -> bool:
    start = get_slot_start_dt(row)

    if not start:
        return False

    return datetime.now(BERLIN_TZ) >= start


def is_slot_end_due(row: dict) -> bool:
    end = get_slot_end_dt(row)

    if not end:
        return False

    return datetime.now(BERLIN_TZ) >= end


def is_completed_channel_delete_due(row: dict) -> bool:
    completed_at = parse_completed_at(row.get(SCHEDULE_COMPLETED_AT_COL))

    if not completed_at:
        return False

    return datetime.now(BERLIN_TZ) >= completed_at + timedelta(minutes=60)


def is_cancelled_channel_delete_due(row: dict) -> bool:
    cancelled_at = parse_completed_at(row.get(SCHEDULE_COMPLETED_AT_COL))

    if not cancelled_at:
        return False

    return datetime.now(BERLIN_TZ) >= cancelled_at + timedelta(minutes=15)


def seconds_to_timecode(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def timecode_to_seconds(value: str):
    value = normalize_text(value)

    if not value or value.upper() == "FF":
        return None

    parts = value.split(":")

    if len(parts) != 3:
        return None

    try:
        h, m, s = [int(p) for p in parts]
    except ValueError:
        return None

    return h * 3600 + m * 60 + s


# =========================================================
# MODE / SEED HELPERS
# =========================================================

def normalize_mode_name(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def get_canonical_mode_name(mode_name: str) -> str:
    normalized = normalize_mode_name(mode_name)
    return TFNL_MODE_ALIASES.get(normalized, normalized)


def get_preset_key_for_mode(mode_name: str) -> str | None:
    canonical = get_canonical_mode_name(mode_name)
    return TFNL_MODE_PRESETS.get(canonical)


def build_sahasrahbot_preset_url(preset_key: str) -> str:
    return f"{SAHASRAHBOT_PRESET_BASE_URL}/{preset_key}.yaml"


async def fetch_yaml_url(url: str) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=30) as response:
            if response.status != 200:
                raise RuntimeError(
                    f"Preset konnte nicht geladen werden: HTTP {response.status} | {url}"
                )

            text = await response.text()
            data = yaml.safe_load(text)

            if not isinstance(data, dict):
                raise RuntimeError(f"Preset YAML ist ungültig: {url}")

            return data


def ensure_list_value(values, required_value: str) -> list:
    if not isinstance(values, list):
        values = []

    if required_value not in values:
        values.insert(0, required_value)

    return values


def force_quickswap_flags(settings: dict):
    """
    Hinweis:
    Quick Swap ist bei pyz3r primär eine ROM-Patch-Option.
    Der Bot erzeugt aktuell nur Seed-Links und patched keine ROM.
    Diese Flags bleiben trotzdem bewusst gesetzt, damit sie bei unterstützten
    API-/Preset-Pfaden nicht verloren gehen.
    """
    settings["allow_quickswap"] = True
    settings["quickswap"] = True
    settings["quick_swap"] = True
    settings["quickSwap"] = True


def get_tfnl_generation_endpoint(customizer_enabled: bool) -> str:
    return "/api/customizer" if customizer_enabled else "/api/randomizer"


async def create_pyz3r_seed(customizer_enabled: bool, settings: dict):
    endpoint = get_tfnl_generation_endpoint(customizer_enabled)

    return await pyz3r.ALTTPR.generate(
        settings=settings,
        endpoint=endpoint,
    )


def force_tfnl_mode_settings(canonical_mode: str, raw_settings: dict, customizer_enabled: bool) -> dict:
    settings = deepcopy(raw_settings)

    if canonical_mode == "casual boots":
        settings["mode"] = "standard"
        settings["weapons"] = "assured"
        settings["eq"] = ensure_list_value(settings.get("eq"), "PegasusBoots")

        # SahasrahBot Casual Boots startet zusätzlich mit 3 BossHeartContainern.
        # Falls das YAML beschädigt/unvollständig geladen wird, ergänzen wir mindestens die Boots hart.
        if "BossHeartContainer" not in settings["eq"]:
            settings["eq"].extend(
                [
                    "BossHeartContainer",
                    "BossHeartContainer",
                    "BossHeartContainer",
                ]
            )

        settings["tournament"] = True
        settings["spoilers"] = "off"

    elif canonical_mode == "open":
        settings["mode"] = "open"
        settings["entrances"] = "none"
        settings["tournament"] = True
        settings["spoilers"] = False

    elif canonical_mode == "crosskeys":
        settings["mode"] = "open"
        settings["entrances"] = "crossed"
        settings["dungeon_items"] = "full"
        settings["accessibility"] = "locations"
        settings["tournament"] = True
        settings["spoilers"] = False

    else:
        settings["tournament"] = True
        settings["spoilers"] = settings.get("spoilers", False)

    force_quickswap_flags(settings)

    return settings


def validate_tfnl_seed_settings(
    canonical_mode: str,
    preset_key: str,
    customizer_enabled: bool,
    raw_settings: dict,
):
    if canonical_mode == "casual boots":
        if preset_key != "casualboots":
            raise RuntimeError(
                f"Casual Boots muss Preset `casualboots` verwenden, erhalten: `{preset_key}`"
            )

        if not customizer_enabled:
            raise RuntimeError(
                "Casual Boots muss als Customizer-Preset erzeugt werden. "
                "Sonst werden Startboots nicht zuverlässig gesetzt."
            )

        eq = raw_settings.get("eq")

        if not isinstance(eq, list) or "PegasusBoots" not in eq:
            raise RuntimeError(
                "Casual Boots wurde abgebrochen: `PegasusBoots` fehlt im Start-Equipment."
            )

        if normalize_mode_name(raw_settings.get("mode")) != "standard":
            raise RuntimeError(
                f"Casual Boots wurde abgebrochen: mode ist nicht `standard`, sondern `{raw_settings.get('mode')}`."
            )

    if canonical_mode == "open":
        if normalize_mode_name(raw_settings.get("mode")) != "open":
            raise RuntimeError(
                f"Open wurde abgebrochen: mode ist nicht `open`, sondern `{raw_settings.get('mode')}`."
            )

        if normalize_mode_name(raw_settings.get("entrances")) not in ("none", ""):
            raise RuntimeError(
                f"Open wurde abgebrochen: entrances ist nicht `none`, sondern `{raw_settings.get('entrances')}`."
            )

    if canonical_mode == "crosskeys":
        if normalize_mode_name(raw_settings.get("mode")) != "open":
            raise RuntimeError(
                f"Crosskeys wurde abgebrochen: mode ist nicht `open`, sondern `{raw_settings.get('mode')}`."
            )

        if normalize_mode_name(raw_settings.get("entrances")) != "crossed":
            raise RuntimeError(
                f"Crosskeys wurde abgebrochen: entrances ist nicht `crossed`, sondern `{raw_settings.get('entrances')}`."
            )

        if normalize_mode_name(raw_settings.get("dungeon_items")) != "full":
            raise RuntimeError(
                f"Crosskeys wurde abgebrochen: dungeon_items ist nicht `full`, sondern `{raw_settings.get('dungeon_items')}`."
            )


def build_seed_diagnostics(
    mode_name: str,
    preset_key: str,
    preset_url: str,
    customizer_enabled: bool,
    raw_settings: dict,
) -> dict:
    return {
        "mode": mode_name,
        "canonical_mode": get_canonical_mode_name(mode_name),
        "preset_key": preset_key,
        "preset_url": preset_url,
        "customizer": customizer_enabled,
        "mode_setting": raw_settings.get("mode"),
        "entrances": raw_settings.get("entrances"),
        "dungeon_items": raw_settings.get("dungeon_items"),
        "accessibility": raw_settings.get("accessibility"),
        "eq": raw_settings.get("eq") if isinstance(raw_settings.get("eq"), list) else [],
        "has_pegasus_boots": "PegasusBoots" in raw_settings.get("eq", []),
        "quickswap_flags_set": True,
        "allow_quickswap": raw_settings.get("allow_quickswap"),
        "endpoint": get_tfnl_generation_endpoint(customizer_enabled),
        "pyz3r_api": "ALTTPR.generate",
    }


async def generate_alttpr_seed_for_mode(mode_name: str) -> tuple[str, dict]:
    canonical_mode = get_canonical_mode_name(mode_name)
    preset_key = get_preset_key_for_mode(canonical_mode)

    if not preset_key:
        raise RuntimeError(f"Kein Seed-Mapping für Modus `{mode_name}` gefunden.")

    preset_url = build_sahasrahbot_preset_url(preset_key)
    preset_data = await fetch_yaml_url(preset_url)

    raw_settings = preset_data.get("settings")
    customizer_enabled = bool(preset_data.get("customizer", False))

    if not isinstance(raw_settings, dict):
        raise RuntimeError(f"Preset enthält keine gültigen settings: {preset_key}")

    raw_settings = force_tfnl_mode_settings(
        canonical_mode=canonical_mode,
        raw_settings=raw_settings,
        customizer_enabled=customizer_enabled,
    )

    validate_tfnl_seed_settings(
        canonical_mode=canonical_mode,
        preset_key=preset_key,
        customizer_enabled=customizer_enabled,
        raw_settings=raw_settings,
    )

    diagnostics = build_seed_diagnostics(
        mode_name=mode_name,
        preset_key=preset_key,
        preset_url=preset_url,
        customizer_enabled=customizer_enabled,
        raw_settings=raw_settings,
    )

    if customizer_enabled:
        customizer_settings = deepcopy(raw_settings)
        customizer_settings["tournament"] = True
        customizer_settings["spoilers"] = "off"
        force_quickswap_flags(customizer_settings)

        # SahasrahBot-ALttPR-Presets sind bereits API-Payloads.
        # Customizer-Presets wie casualboots.yaml dürfen nicht konvertiert werden,
        # weil dadurch Startitems aus dem SahasrahBot-YAML verloren gehen können.
        seed = await create_pyz3r_seed(
            customizer_enabled=True,
            settings=customizer_settings,
        )

    else:
        normal_settings = deepcopy(raw_settings)
        normal_settings["tournament"] = True
        normal_settings["spoilers"] = False
        force_quickswap_flags(normal_settings)

        seed = await create_pyz3r_seed(
            customizer_enabled=False,
            settings=normal_settings,
        )

    seed_url = str(getattr(seed, "url", "") or "").strip()

    if not seed_url:
        raise RuntimeError(f"ALTTPR hat keine Seed URL geliefert: {preset_key}")

    return seed_url, diagnostics


async def generate_alttpr_seed_from_preset(preset_key: str) -> str:
    """
    Kompatibilitätsfunktion für alte Aufrufe.
    Neue TFNL-Seed-Erzeugung sollte generate_alttpr_seed_for_mode(mode_name) verwenden,
    damit modus-spezifische Validierungen greifen.
    """
    preset_url = build_sahasrahbot_preset_url(preset_key)
    preset_data = await fetch_yaml_url(preset_url)

    settings = preset_data.get("settings")
    customizer_enabled = bool(preset_data.get("customizer", False))

    if not isinstance(settings, dict):
        raise RuntimeError(f"Preset enthält keine gültigen settings: {preset_key}")

    settings = deepcopy(settings)
    settings["tournament"] = True
    settings["spoilers"] = settings.get("spoilers", False)
    force_quickswap_flags(settings)

    if customizer_enabled:
        customizer_settings = deepcopy(settings)
        customizer_settings["tournament"] = True
        customizer_settings["spoilers"] = "off"
        force_quickswap_flags(customizer_settings)

        seed = await create_pyz3r_seed(
            customizer_enabled=True,
            settings=customizer_settings,
        )
    else:
        normal_settings = deepcopy(settings)
        normal_settings["tournament"] = True
        normal_settings["spoilers"] = False
        force_quickswap_flags(normal_settings)

        seed = await create_pyz3r_seed(
            customizer_enabled=False,
            settings=normal_settings,
        )

    seed_url = str(getattr(seed, "url", "") or "").strip()

    if not seed_url:
        raise RuntimeError(f"ALTTPR hat keine Seed URL geliefert: {preset_key}")

    return seed_url


# =========================================================
# DISPLAY HELPERS
# =========================================================

def signup_announcement_already_sent(row: dict) -> bool:
    value = normalize_text(row.get(SCHEDULE_ANNOUNCEMENT_COL)).lower()
    return value in ("ja", "yes", "true", "1")


def get_seed_url(row: dict) -> str:
    for key in ("Seed URL", "Seed url", "Seed Url", "SeedURL", "Seed"):
        value = normalize_text(row.get(key))
        if value:
            return value
    return ""


def sanitize_channel_name(value: str) -> str:
    value = value.lower()
    value = value.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    value = re.sub(r"[^a-z0-9\-]+", "-", value)
    value = re.sub(r"-+", "-", value)
    return value.strip("-")[:90]


def build_slot_channel_name(row: dict) -> str:
    datum = normalize_text(row.get("Datum")).replace(".", "-")
    slot = normalize_text(row.get("Slot")).lower()
    modus = normalize_text(row.get("Modus")).lower()

    return sanitize_channel_name(f"tfnl-{datum}-{slot}-{modus}")


def build_slot_line(row: dict) -> str:
    datum = normalize_text(row.get("Datum"))
    slot = normalize_text(row.get("Slot"))
    startzeit = normalize_text(row.get("Startzeit"))
    modus = normalize_text(row.get("Modus"))
    status = normalize_text(row.get("Status")) or "planned"

    return f"**{datum} | {slot} | {startzeit} Uhr** — {modus} `[{status}]`"


def build_discord_table(headers: list[str], rows: list[list], max_col_width: int = 24) -> str:
    string_rows = []

    for row in rows:
        string_row = []
        for value in row:
            text = normalize_text(value).replace("\n", " / ")
            if len(text) > max_col_width:
                text = text[: max_col_width - 1] + "…"
            string_row.append(text)
        string_rows.append(string_row)

    widths = []
    for index, header in enumerate(headers):
        values = [normalize_text(header)]
        for row in string_rows:
            if index < len(row):
                values.append(row[index])
        widths.append(min(max(len(value) for value in values), max_col_width))

    def format_row(row_values: list[str]) -> str:
        cells = []
        for index, width in enumerate(widths):
            value = row_values[index] if index < len(row_values) else ""
            if len(value) > width:
                value = value[: width - 1] + "…"
            cells.append(value.ljust(width))
        return " | ".join(cells).rstrip()

    separator = "-+-".join("-" * width for width in widths)
    lines = [format_row(headers), separator]

    for row in string_rows:
        lines.append(format_row(row))

    return "```text\n" + "\n".join(lines) + "\n```"


ANSI_RESET = "\u001b[0m"
ANSI_GREEN = "\u001b[32m"
ANSI_YELLOW = "\u001b[33m"
ANSI_LIGHT_RED = "\u001b[91m"
ANSI_RED = "\u001b[31m"
ANSI_PURPLE = "\u001b[35m"
ANSI_DARK_RED = "\u001b[31m"


def strip_ansi(value: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", str(value or ""))


def ansi_color(value, color: str) -> str:
    text = normalize_text(value)

    if text == "":
        text = "0"

    return f"{color}{text}{ANSI_RESET}"


def parse_float_value(value, default: float = 0.0) -> float:
    try:
        text = normalize_text(value).replace(",", ".").replace("+", "")
        if not text:
            return default
        return float(text)
    except Exception:
        return default


def color_elo_change(value) -> str:
    text = normalize_text(value)

    if not text:
        text = "±0.0"

    number = parse_float_value(text.replace("±", ""), 0.0)

    if number > 0:
        return ansi_color(text, ANSI_GREEN)

    if number < 0:
        return ansi_color(text, ANSI_LIGHT_RED)

    return ansi_color(text, ANSI_YELLOW)


def color_rank_delta(value) -> str:
    number = int_value(value)

    if number > 0:
        return ansi_color(f"+{number}", ANSI_GREEN)

    if number < 0:
        return ansi_color(str(number), ANSI_LIGHT_RED)

    return ansi_color("0", ANSI_YELLOW)


def calculate_ff_penalty(forfeits: int) -> int:
    return max(0, int_value(forfeits) - TFNL_FF_PENALTY_FREE_COUNT) * TFNL_FF_PENALTY_POINTS


def color_penalty_value(value) -> str:
    penalty = int_value(value)

    if penalty > 0:
        return ansi_color(f"-{penalty}", ANSI_RED)

    return ansi_color("0", ANSI_YELLOW)


def color_final_score(value) -> str:
    return normalize_text(value) or "0"


def color_stat_value(value, stat: str) -> str:
    text = normalize_text(value)

    if text == "":
        text = "0"

    if stat == "S":
        return ansi_color(text, ANSI_GREEN)

    if stat == "U":
        return ansi_color(text, ANSI_YELLOW)

    if stat == "N":
        return ansi_color(text, ANSI_RED)

    if stat == "FF":
        return ansi_color(text, ANSI_PURPLE)

    return text


def color_last_race_player_name(name: str, player_id: str, last_race_player_ids: set[str]) -> str:
    if normalize_text(player_id) in last_race_player_ids:
        return ansi_color(name, ANSI_YELLOW)

    return normalize_text(name) or "0"


def visible_len(value) -> int:
    return len(strip_ansi(normalize_text(value)))


def get_leading_ansi_color(value: str) -> str:
    match = re.match(r"^(\x1b\[[0-9;]*m)", str(value or ""))
    return match.group(1) if match else ""


def visible_truncate(value, max_width: int) -> str:
    text = normalize_text(value).replace("\n", " / ")
    plain = strip_ansi(text)

    if len(plain) <= max_width:
        return text

    truncated_plain = plain[: max_width - 1] + "…"
    color = get_leading_ansi_color(text)

    if color:
        return f"{color}{truncated_plain}{ANSI_RESET}"

    return truncated_plain


def visible_ljust(value, width: int) -> str:
    text = normalize_text(value)
    padding = max(0, width - visible_len(text))
    return text + (" " * padding)


def build_discord_ansi_table(headers: list[str], rows: list[list], max_col_width: int = 24) -> str:
    string_rows = []

    for row in rows:
        string_row = []
        for value in row:
            text = normalize_text(value).replace("\n", " / ")
            if text == "":
                text = "0"
            text = visible_truncate(text, max_col_width)
            string_row.append(text)
        string_rows.append(string_row)

    widths = []
    for index, header in enumerate(headers):
        values = [normalize_text(header)]
        for row in string_rows:
            if index < len(row):
                values.append(row[index])
        widths.append(min(max(visible_len(value) for value in values), max_col_width))

    def format_row(row_values: list[str]) -> str:
        cells = []
        for index, width in enumerate(widths):
            value = row_values[index] if index < len(row_values) else "0"
            if normalize_text(value) == "":
                value = "0"
            value = visible_truncate(value, width)
            cells.append(visible_ljust(value, width))
        return " | ".join(cells).rstrip()

    separator = "-+-".join("-" * width for width in widths)
    lines = [format_row(headers), separator]

    for row in string_rows:
        lines.append(format_row(row))

    return "```ansi\n" + "\n".join(lines) + "\n```"


def split_plain_discord_message(message: str, limit: int = 1900) -> list[str]:
    text = normalize_text(message)

    if not text:
        return [""]

    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""

    for line in text.splitlines():
        candidate = line if not current else current + "\n" + line

        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]

        current = line

    if current:
        chunks.append(current)

    return chunks or [text[:limit]]


def split_discord_message(message: str, limit: int = 1900) -> list[str]:
    """
    Discord erlaubt max. 2000 Zeichen pro Nachricht.

    Wichtig für ANSI-Tabellen:
    Niemals innerhalb eines ```ansi-Codeblocks stumpf splitten.
    Sonst fehlt im zweiten Chunk der öffnende Codeblock und Discord zeigt
    rohe ANSI-Codes wie ESC[32m an. Jeder Chunk wird deshalb als gültige,
    geschlossene Discord-Nachricht ausgegeben.
    """
    text = normalize_text(message)

    if not text:
        return [""]

    if len(text) <= limit:
        return [text]

    if "```" not in text:
        return split_plain_discord_message(text, limit=limit)

    chunks: list[str] = []
    current_lines: list[str] = []
    in_code_block = False
    code_lang = ""

    def chunk_text(lines: list[str]) -> str:
        return "\n".join(lines).strip("\n")

    def current_with_line(line: str, close_if_code: bool = True) -> str:
        lines = current_lines + [line]

        if close_if_code and in_code_block:
            # Wenn der aktuelle Chunk mitten in einem Codeblock endet,
            # muss er für Discord gültig geschlossen werden.
            if not line.strip().startswith("```"):
                lines = lines + ["```"]

        return chunk_text(lines)

    def flush_current():
        nonlocal current_lines

        if not current_lines:
            return

        lines = current_lines[:]

        if in_code_block:
            # Offenen Codeblock für diesen Discord-Chunk schließen.
            if not lines[-1].strip().startswith("```") or len(lines[-1].strip()) > 3:
                lines.append("```")

        chunk = chunk_text(lines)

        if chunk:
            chunks.append(chunk)

        current_lines = []

        if in_code_block:
            # Nächster Discord-Chunk muss den Codeblock wieder öffnen,
            # damit ANSI-Farben weiterhin sauber gerendert werden.
            current_lines = [f"```{code_lang}".rstrip()]

    def append_long_line_safely(line: str):
        nonlocal current_lines

        overhead = 16

        if in_code_block:
            overhead += len(code_lang)

        max_part_len = max(200, limit - overhead)

        remaining = line

        while len(remaining) > max_part_len:
            part = remaining[:max_part_len]
            remaining = remaining[max_part_len:]

            if current_lines:
                flush_current()

            if in_code_block and not current_lines:
                current_lines = [f"```{code_lang}".rstrip()]

            current_lines.append(part)
            flush_current()

        if remaining:
            if current_lines:
                candidate = current_with_line(remaining)

                if len(candidate) > limit:
                    flush_current()

            current_lines.append(remaining)

    for line in text.splitlines():
        stripped = line.strip()
        is_fence = stripped.startswith("```")

        candidate = current_with_line(line)

        if current_lines and len(candidate) > limit:
            flush_current()

        if len(line) > limit - 20:
            append_long_line_safely(line)
        else:
            current_lines.append(line)

        if is_fence:
            fence_lang = stripped[3:].strip()

            if in_code_block:
                # Gerade wurde ein schließender Fence verarbeitet.
                in_code_block = False
                code_lang = ""
            else:
                # Gerade wurde ein öffnender Fence verarbeitet.
                in_code_block = True
                code_lang = fence_lang

    if current_lines:
        if in_code_block:
            current_lines.append("```")

        chunk = chunk_text(current_lines)

        if chunk:
            chunks.append(chunk)

    # Finale Absicherung: Kein Chunk über Discord-Limit.
    safe_chunks: list[str] = []

    for chunk in chunks:
        if len(chunk) <= limit:
            safe_chunks.append(chunk)
        else:
            safe_chunks.extend(split_plain_discord_message(chunk, limit=limit))

    return safe_chunks or [text[:limit]]


async def send_discord_message_chunks(send_callable, message: str):
    for chunk in split_discord_message(message):
        await send_callable(chunk)


def build_signup_line(row: dict) -> str:
    slot_id = normalize_text(row.get("Slot ID"))
    datum = normalize_text(row.get("Datum"))
    slot = normalize_text(row.get("Slot"))
    startzeit = normalize_text(row.get("Startzeit"))
    anmeldeschluss = normalize_text(row.get("Anmeldeschluss"))
    modus = normalize_text(row.get("Modus"))
    signup_count = get_signup_count_for_slot(slot_id) if slot_id else 0

    return (
        f"**{datum} | {slot} | {startzeit} Uhr** — {modus}\n"
        f"Angemeldet: `{signup_count}`\n"
        f"Anmeldeschluss: `{anmeldeschluss} Uhr`"
    )


def get_upcoming_schedule(days: int = 5):
    rows = load_schedule_rows()

    today = datetime.now(BERLIN_TZ).date()
    end_date = today + timedelta(days=days)

    upcoming = []

    for row in rows:
        slot_date = parse_german_date(row.get("Datum"))

        if not slot_date:
            continue

        status = normalize_text(row.get("Status")).lower()

        if status in ("completed", "archived", "cancelled"):
            continue

        if today <= slot_date <= end_date:
            upcoming.append(row)

    upcoming.sort(
        key=lambda r: (
            parse_german_date(r.get("Datum")) or today,
            normalize_text(r.get("Startzeit")),
        )
    )

    return upcoming


def get_open_signup_slots():
    rows = load_schedule_rows()
    return sorted(
        [row for row in rows if is_registration_open(row)],
        key=lambda r: (
            parse_german_date(r.get("Datum")) or datetime.now(BERLIN_TZ).date(),
            normalize_text(r.get("Startzeit")),
        ),
    )


def build_schedule_embed(days: int = 5) -> discord.Embed:
    upcoming = get_upcoming_schedule(days=days)
    now = datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M")

    embed = discord.Embed(
        title="🗓️ TFNL-Spielplan",
        color=discord.Color.dark_teal(),
    )

    if not upcoming:
        embed.description = (
            f"**Keine offenen TFNL-Slots in den nächsten `{days}` Tagen gefunden.**\n\n"
            "Beendete, archivierte und abgesagte Slots werden ausgeblendet."
        )
        embed.set_footer(text=f"Aktualisiert: {now} Uhr")
        return embed

    weekday_names = {
        0: "Montag",
        1: "Dienstag",
        2: "Mittwoch",
        3: "Donnerstag",
        4: "Freitag",
        5: "Samstag",
        6: "Sonntag",
    }

    status_icons = {
        "planned": "🟢",
        "open": "🟢",
        "signup_open": "🟢",
        "paired": "🟡",
        "countdown_sent": "🟠",
        "running": "🔴",
        "completed": "⚫",
        "cancelled": "⚪",
        "archived": "⚫",
    }

    grouped: dict[str, list[dict]] = {}

    for row in upcoming:
        datum = normalize_text(row.get("Datum"))
        grouped.setdefault(datum, []).append(row)

    for datum, rows in grouped.items():
        parsed_date = parse_german_date(datum)
        weekday = weekday_names.get(parsed_date.weekday(), "") if parsed_date else ""
        field_name = f"📅 {weekday}, {datum}" if weekday else f"📅 {datum}"

        lines = []
        for row in sorted(rows, key=lambda r: normalize_text(r.get("Startzeit"))):
            startzeit = normalize_text(row.get("Startzeit"))
            slot = normalize_text(row.get("Slot"))
            modus = normalize_text(row.get("Modus"))
            status = normalize_text(row.get("Status")).lower() or "planned"
            status_icon = status_icons.get(status, "🔹")

            lines.append(
                f"{status_icon} `{startzeit} Uhr` **{slot}** — {modus} `[{status}]`"
            )

        embed.add_field(
            name=field_name,
            value="\n".join(lines) or "Keine Slots",
            inline=False,
        )

    embed.description = (
        f"Offene TFNL-Slots der nächsten `{days}` Tage.\n"
        "🟢 geplant/offen · 🟡 gepaart · 🔴 läuft · ⚪ abgesagt"
    )
    embed.set_footer(text=f"Beendete Slots werden ausgeblendet | Aktualisiert: {now} Uhr")
    return embed



def build_signup_embed(open_slots: list[dict]) -> discord.Embed:
    now = datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M")

    if not open_slots:
        description = (
            "**Aktuell ist keine Anmeldung geöffnet.**\n\n"
            "**Racezeiten:**\n"
            "🟩 **Mo–Do**  `18:00` & `21:00 Uhr`\n"
            "🟨 **Fr**     `15:00`, `18:00` & `21:00 Uhr`\n"
            "🟦 **Sa**     `12:00`, `15:00`, `18:00` & `21:00 Uhr`\n"
            "🟪 **So**     `12:00`, `15:00` & `21:00 Uhr`\n\n"
            "⚔️ `18:00 Uhr` sonntags bleibt frei fürs deutsche Weekly."
        )
        title = "TFNL-Anmeldung"
    else:
        table_rows = []
        for row in open_slots:
            slot_id = normalize_text(row.get("Slot ID"))
            table_rows.append(
                [
                    normalize_text(row.get("Datum")),
                    normalize_text(row.get("Slot")),
                    normalize_text(row.get("Startzeit")),
                    normalize_text(row.get("Modus")),
                    get_signup_count_for_slot(slot_id) if slot_id else 0,
                    normalize_text(row.get("Anmeldeschluss")),
                ]
            )

        description = build_discord_table(
            ["Datum", "Slot", "Start", "Modus", "Anz", "Bis"],
            table_rows,
            max_col_width=16,
        )
        description += "\nNutze die Buttons unter dieser Nachricht zum An- oder Abmelden."
        title = "TFNL-Anmeldung geöffnet"

    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.dark_teal(),
    )

    embed.set_footer(text=f"Aktualisiert: {now} Uhr")
    return embed


def build_signup_status_embed(open_slots: list[dict]) -> discord.Embed:
    now = datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M")

    if not open_slots:
        description = "Keine offene Anmeldung."
    else:
        sections = []
        for row in open_slots:
            slot_id = normalize_text(row.get("Slot ID"))
            datum = normalize_text(row.get("Datum"))
            slot = normalize_text(row.get("Slot"))
            startzeit = normalize_text(row.get("Startzeit"))
            modus = normalize_text(row.get("Modus"))
            names = get_signup_names_for_slot(slot_id)

            section_lines = [f"**{datum} | {slot} | {startzeit} Uhr — {modus}**"]

            if not names:
                section_lines.append("_Noch niemand angemeldet._")
            else:
                player_rows = [[index, name] for index, name in enumerate(names, start=1)]
                section_lines.append(build_discord_table(["#", "Spieler"], player_rows, max_col_width=30))

            sections.append("\n".join(section_lines))

        description = "\n\n".join(sections)

    embed = discord.Embed(
        title="Aktuell angemeldete Spieler",
        description=description,
        color=discord.Color.dark_teal(),
    )

    embed.set_footer(text=f"Aktualisiert: {now} Uhr")
    return embed


# =========================================================
# SIGNUP / MATCH HELPERS
# =========================================================

def get_signup_participants_for_slot(slot_id: str) -> list[dict]:
    rows = load_signup_rows()
    participants = []
    seen = set()

    for row in rows:
        row_slot_id = normalize_text(row.get("Slot ID"))
        discord_id = normalize_text(row.get("Discord ID"))
        status = normalize_text(row.get("Status")).lower()

        if row_slot_id != slot_id:
            continue

        if status != "signed_up":
            continue

        if not discord_id or discord_id in seen:
            continue

        seen.add(discord_id)

        participants.append(
            {
                "discord_id": discord_id,
                "name": normalize_text(row.get("Discord Display Name")),
            }
        )

    return participants


def get_signup_count_for_slot(slot_id: str) -> int:
    rows = load_signup_rows()
    signed_up_ids = set()

    for row in rows:
        if normalize_text(row.get("Slot ID")) != slot_id:
            continue

        if normalize_text(row.get("Status")).lower() != "signed_up":
            continue

        discord_id = normalize_text(row.get("Discord ID"))

        if discord_id:
            signed_up_ids.add(discord_id)

    return len(signed_up_ids)


def get_signup_names_for_slot(slot_id: str) -> list[str]:
    rows = load_signup_rows()
    names_by_id = {}

    for row in rows:
        if normalize_text(row.get("Slot ID")) != slot_id:
            continue

        if normalize_text(row.get("Status")).lower() != "signed_up":
            continue

        discord_id = normalize_text(row.get("Discord ID"))
        display_name = normalize_text(row.get("Discord Display Name"))

        if discord_id and display_name:
            names_by_id[discord_id] = display_name

    return sorted(names_by_id.values(), key=lambda name: name.lower())


def format_signup_names_for_slot(slot_id: str) -> str:
    names = get_signup_names_for_slot(slot_id)

    if not names:
        return "_Noch niemand angemeldet._"

    return ", ".join(names)


def user_already_signed_up(slot_id: str, user_id: int, force_refresh: bool = False) -> bool:
    rows = load_signup_rows(force_refresh=force_refresh)

    for row in rows:
        if (
            normalize_text(row.get("Slot ID")) == slot_id
            and normalize_text(row.get("Discord ID")) == str(user_id)
            and normalize_text(row.get("Status")).lower() == "signed_up"
        ):
            return True

    return False


def cancel_signup(slot_id: str, user_id: int) -> bool:
    sheet = get_signup_sheet()
    rows_with_index = load_signup_rows_with_index(force_refresh=True)

    status_col = get_header_index(sheet, SIGNUP_SHEET_NAME, "Status")

    if not status_col:
        return False

    for row_index, row in rows_with_index:
        if (
            normalize_text(row.get("Slot ID")) == slot_id
            and normalize_text(row.get("Discord ID")) == str(user_id)
            and normalize_text(row.get("Status")).lower() == "signed_up"
        ):
            sheet_write_call(
                lambda: sheet.update_cell(row_index, status_col, "cancelled"),
                invalidate_prefixes=[
                    f"records:{SIGNUP_SHEET_NAME}",
                    f"values:{SIGNUP_SHEET_NAME}",
                    f"row:{SIGNUP_SHEET_NAME}:",
                    f"cell:{SIGNUP_SHEET_NAME}:",
                ],
            )
            return True

    return False

def matches_already_created(slot_id: str) -> bool:
    rows = load_matches_rows()
    return any(normalize_text(row.get("Slot ID")) == slot_id for row in rows)


def get_matches_for_slot(slot_id: str) -> list[dict]:
    return [
        row for row in load_matches_rows()
        if normalize_text(row.get("Slot ID")) == slot_id
    ]


def get_matches_for_slot_combined(slot_id: str) -> list[dict]:
    return [
        row for row in load_matches_rows_combined()
        if normalize_text(row.get("Slot ID")) == slot_id
    ]


def get_match_players(row: dict) -> list[dict]:
    players = []

    for no in (1, 2, 3):
        player_id = normalize_text(row.get(f"Spieler {no} Discord ID"))
        player_name = normalize_text(row.get(f"Spieler {no} Name"))

        if player_id:
            players.append(
                {
                    "no": no,
                    "discord_id": player_id,
                    "name": player_name,
                    "time_col": f"Zeit Spieler {no}",
                    "result_col": f"Ergebnis Spieler {no}",
                    "points_col": f"Punkte Spieler {no}",
                }
            )

    return players


def get_last_opponents(limit: int = 5) -> dict[str, set[str]]:
    rows = load_matches_rows_all_combined()
    last_opponents: dict[str, list[str]] = {}

    for row in reversed(rows):
        if normalize_text(row.get("Veröffentlicht")).lower() != "ja":
            continue

        players = [
            normalize_text(row.get("Spieler 1 Discord ID")),
            normalize_text(row.get("Spieler 2 Discord ID")),
            normalize_text(row.get("Spieler 3 Discord ID")),
        ]
        players = [player_id for player_id in players if player_id]

        if len(players) < 2:
            continue

        for player_id in players:
            current = last_opponents.setdefault(player_id, [])

            for opponent_id in players:
                if opponent_id == player_id:
                    continue

                if opponent_id in current:
                    continue

                if len(current) >= limit:
                    continue

                current.append(opponent_id)

    return {
        player_id: set(opponents[:limit])
        for player_id, opponents in last_opponents.items()
    }


def calculate_pairing_score(groups: list[list[dict]], last_opponents: dict[str, set[str]]) -> int:
    score = 0

    for group in groups:
        ids = [p["discord_id"] for p in group]

        for player_id in ids:
            previous = last_opponents.get(player_id, set())

            for other_id in ids:
                if other_id != player_id and other_id in previous:
                    score += 1

    return score


def create_pairings(participants: list[dict], schedule_row: dict | None = None) -> list[list[dict]]:
    count = len(participants)

    if count < 2:
        return []

    if not schedule_row:
        # Fallback: alte Logik, falls die Funktion außerhalb des Slot-Kontexts genutzt wird.
        if count == 3:
            return [participants]

        last_opponents = get_last_opponents(limit=5)
        best_groups = None
        best_score = None

        for _ in range(100):
            shuffled = participants[:]
            random.shuffle(shuffled)

            groups = []

            if len(shuffled) % 2 == 1:
                three_way = shuffled[-3:]
                rest = shuffled[:-3]
            else:
                three_way = None
                rest = shuffled

            for index in range(0, len(rest), 2):
                groups.append(rest[index:index + 2])

            if three_way:
                groups.append(three_way)

            score = calculate_pairing_score(groups, last_opponents)

            if best_score is None or score < best_score:
                best_score = score
                best_groups = groups

            if score == 0:
                break

        return best_groups or []

    season = get_active_season_for_row(schedule_row)
    mode = normalize_text(schedule_row.get("Modus"))
    participant_by_id = {
        normalize_text(player.get("discord_id")): player
        for player in participants
    }

    pairing_players = build_pairing_players(
        participants=participants,
        season=season,
        mode=mode,
    )
    recent_opponents = get_last_opponents(limit=5)
    elo_groups = create_elo_pairings(pairing_players, recent_opponents)

    groups: list[list[dict]] = []

    for elo_group in elo_groups:
        group = []

        for elo_player in elo_group:
            original = participant_by_id.get(elo_player.player_id)

            if original:
                group.append(original)

        if len(group) >= 2:
            groups.append(group)

    return groups


def build_match_rows(slot_id: str, schedule_row: dict, pairings: list[list[dict]]) -> list[list]:
    rows = []
    startzeit = normalize_text(schedule_row.get("Startzeit"))
    seed_url = get_seed_url(schedule_row)

    for index, group in enumerate(pairings, start=1):
        match_id = f"{slot_id}-M{index:02d}"
        matchtyp = "3way" if len(group) == 3 else "1on1"

        p1 = group[0]
        p2 = group[1]
        p3 = group[2] if len(group) == 3 else {"discord_id": "", "name": ""}

        rows.append(
            [
                match_id,
                slot_id,
                matchtyp,
                p1["discord_id"],
                p1["name"],
                p2["discord_id"],
                p2["name"],
                p3["discord_id"],
                p3["name"],
                seed_url,
                startzeit,
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "created",
                "Nein",
                get_active_season_for_row(schedule_row),
            ]
        )

    return rows


def get_slot_completion_blockers(slot_id: str) -> list[str]:
    matches = get_matches_for_slot(slot_id)
    blockers = []

    if not matches:
        return [f"Keine Matches für Slot `{slot_id}` gefunden."]

    for match in matches:
        match_id = normalize_text(match.get("Match ID")) or "unbekannt"
        published = normalize_text(match.get("Veröffentlicht"))

        if published.lower() != "ja":
            blockers.append(
                f"Match `{match_id}` ist nicht veröffentlicht. Veröffentlicht=`{published or '-'}'"
            )

        for player in get_match_players(match):
            time_value = normalize_text(match.get(player["time_col"]))

            if not time_value:
                blockers.append(
                    f"Match `{match_id}`: `{player['name']}` hat keine Zeit/kein FF."
                )

    return blockers


def is_slot_complete(slot_id: str) -> bool:
    return len(get_slot_completion_blockers(slot_id)) == 0


# =========================================================
# RESULT LOGIC
# =========================================================

def calculate_match_result(match_row: dict):
    matchtyp = normalize_text(match_row.get("Matchtyp"))
    players = get_match_players(match_row)

    for player in players:
        player["time"] = normalize_text(match_row.get(player["time_col"]))
        player["seconds"] = timecode_to_seconds(player["time"])

    if any(not player["time"] for player in players):
        return None

    if matchtyp == "1on1":
        return calculate_1on1_result(players)

    if matchtyp == "3way":
        return calculate_3way_result(players)

    return None


def match_has_all_times(match_row: dict) -> bool:
    players = get_match_players(match_row)

    if not players:
        return False

    for player in players:
        if not normalize_text(match_row.get(player["time_col"])):
            return False

    return True


def match_needs_auto_evaluation(match_row: dict) -> bool:
    """
    Ein Match braucht Auto-Wertung, wenn alle Abschlusswerte vorhanden sind,
    es aber noch nicht sauber veröffentlicht wurde.

    Wichtig:
    Status `finished` allein darf NICHT zum Überspringen führen.
    Genau dieser Zustand kann entstehen, wenn ein Match teilweise geschrieben
    wurde, aber `Veröffentlicht` leer geblieben ist oder ein Folgepost scheiterte.
    Dann muss die Auto-Routine das Match erneut sauber durch evaluate_match_if_complete()
    laufen lassen können.
    """
    if normalize_text(match_row.get("Veröffentlicht")).lower() == "ja":
        return False

    if not match_has_all_times(match_row):
        return False

    return calculate_match_result(match_row) is not None


def calculate_1on1_result(players: list[dict]):
    p1, p2 = players[0], players[1]

    p1_ff = p1["time"].upper() == "FF"
    p2_ff = p2["time"].upper() == "FF"

    if p1_ff and p2_ff:
        return {
            p1["no"]: ("Niederlage", 0),
            p2["no"]: ("Niederlage", 0),
        }

    if p1_ff and not p2_ff:
        return {
            p1["no"]: ("Niederlage", 0),
            p2["no"]: ("Sieg", 2),
        }

    if p2_ff and not p1_ff:
        return {
            p1["no"]: ("Sieg", 2),
            p2["no"]: ("Niederlage", 0),
        }

    diff = abs(p1["seconds"] - p2["seconds"])

    if diff <= 5:
        return {
            p1["no"]: ("Remis", 1),
            p2["no"]: ("Remis", 1),
        }

    if p1["seconds"] < p2["seconds"]:
        return {
            p1["no"]: ("Sieg", 2),
            p2["no"]: ("Niederlage", 0),
        }

    return {
        p1["no"]: ("Niederlage", 0),
        p2["no"]: ("Sieg", 2),
    }


def calculate_3way_result(players: list[dict]):
    ff_players = [p for p in players if p["time"].upper() == "FF"]
    finishers = [p for p in players if p["time"].upper() != "FF"]

    if len(ff_players) == 3:
        return {p["no"]: ("Niederlage", 0) for p in players}

    finishers.sort(key=lambda p: p["seconds"])

    result = {}

    if len(finishers) == 3:
        result[finishers[0]["no"]] = ("Sieg", 2)
        result[finishers[1]["no"]] = ("Remis", 1)
        result[finishers[2]["no"]] = ("Niederlage", 0)

    elif len(finishers) == 2:
        result[finishers[0]["no"]] = ("Sieg", 2)
        result[finishers[1]["no"]] = ("Remis", 1)

        for p in ff_players:
            result[p["no"]] = ("Niederlage", 0)

    elif len(finishers) == 1:
        result[finishers[0]["no"]] = ("Sieg", 2)

        for p in ff_players:
            result[p["no"]] = ("Niederlage", 0)

    return result


def build_result_message(match_row: dict, elo_changes: dict[str, str] | None = None) -> str:
    match_id = normalize_text(match_row.get("Match ID"))
    matchtyp = normalize_text(match_row.get("Matchtyp"))
    players = get_match_players(match_row)
    elo_changes = elo_changes or get_match_elo_changes(match_id)

    lines = [
        "**TFNL-Ergebnis veröffentlicht**",
        f"`{match_id}` — `{matchtyp}`",
        "",
    ]

    for player in players:
        name = player["name"]
        player_id = player["discord_id"]
        time_value = normalize_text(match_row.get(player["time_col"]))
        result = normalize_text(match_row.get(player["result_col"]))
        elo_change = normalize_text(elo_changes.get(player_id, "±0.0"))

        lines.append(f"**{name}** — `{time_value}` — {result} (ELO {elo_change})")

    return "\n".join(lines)


def build_public_result_message(
    match_row: dict,
    schedule_row: dict | None = None,
    elo_changes: dict[str, str] | None = None,
) -> str:
    slot_id = normalize_text(match_row.get("Slot ID"))

    if schedule_row is None:
        _, schedule_row = find_schedule_row(slot_id)

    datum = normalize_text(schedule_row.get("Datum")) if schedule_row else ""
    slot = normalize_text(schedule_row.get("Slot")) if schedule_row else ""
    startzeit = normalize_text(schedule_row.get("Startzeit")) if schedule_row else ""
    modus = normalize_text(schedule_row.get("Modus")) if schedule_row else ""

    header = [
        "**TFNL Ladder Ergebnis**",
        f"Slot: `{datum} | {slot} | {startzeit} Uhr`",
        f"Modus: `{modus}`",
        "",
    ]

    return "\n".join(header) + build_result_message(match_row, elo_changes=elo_changes)


def build_slot_runner_message(schedule_row: dict) -> str:
    slot_id = normalize_text(schedule_row.get("Slot ID"))
    datum = normalize_text(schedule_row.get("Datum"))
    slot = normalize_text(schedule_row.get("Slot"))
    startzeit = normalize_text(schedule_row.get("Startzeit"))
    modus = normalize_text(schedule_row.get("Modus"))
    names = get_signup_names_for_slot(slot_id)

    lines = [
        "**Teilnehmer dieses TFNL-Slots**",
        f"`{datum} | {slot} | {startzeit} Uhr | {modus}`",
        "",
    ]

    if not names:
        lines.append("Keine Teilnehmer gefunden.")
    else:
        rows = [[index, name] for index, name in enumerate(names, start=1)]
        lines.append(build_discord_table(["#", "Runner"], rows, max_col_width=32))

    return "\n".join(lines)


def apply_result_to_match(match_id: str, result: dict[int, tuple[str, int]]):
    values = {}

    for player_no, (result_text, points) in result.items():
        values[f"Ergebnis Spieler {player_no}"] = result_text
        values[f"Punkte Spieler {player_no}"] = str(points)

    values["Status"] = "finished"
    values["Veröffentlicht"] = "Ja"

    update_match_cells(match_id, values)


def is_match_publicly_complete(match: dict) -> bool:
    """
    Schutzregel für öffentliche Ergebnis-Ausgaben:
    Ein Match darf öffentlich erst sichtbar werden, wenn alle Spieler dieses
    Matches einen Abschlusswert haben. Bei 1on1 also beide Spieler, bei 3way
    alle drei Spieler. Einzelzeiten laufender Matches dürfen niemals öffentlich
    auftauchen.
    """
    players = get_match_players(match)

    if not players:
        return False

    for player in players:
        time_value = normalize_text(match.get(player["time_col"]))
        if not time_value:
            return False

    status = normalize_text(match.get("Status")).lower()
    published = normalize_text(match.get("Veröffentlicht")).lower()

    return status == "finished" or published == "ja"


def collect_slot_results(slot_id: str, public_only_complete_matches: bool = False) -> list[dict]:
    results = []
    slot_elo_changes = get_slot_elo_changes(slot_id)

    for match in get_matches_for_slot(slot_id):
        if public_only_complete_matches and not is_match_publicly_complete(match):
            continue

        match_id = normalize_text(match.get("Match ID"))

        for player in get_match_players(match):
            time_value = normalize_text(match.get(player["time_col"]))
            result_text = normalize_text(match.get(player["result_col"]))
            points = normalize_text(match.get(player["points_col"]))
            seconds = timecode_to_seconds(time_value)

            results.append(
                {
                    "match_id": match_id,
                    "name": player["name"],
                    "discord_id": player["discord_id"],
                    "time": time_value,
                    "seconds": seconds,
                    "result": result_text,
                    "points": int_value(points),
                    "elo_change": normalize_text(slot_elo_changes.get(player["discord_id"], "±0.0")),
                    "is_ff": time_value.upper() == "FF",
                }
            )

    results.sort(
        key=lambda r: (
            r["match_id"],
            r["is_ff"],
            r["seconds"] if r["seconds"] is not None else 9999999,
            r["name"].lower(),
        )
    )

    return results


def collect_slot_match_groups(slot_id: str, public_only_complete_matches: bool = False) -> list[dict]:
    """
    Liefert Match-Gruppen für die Anzeige, damit erkennbar bleibt,
    wer gegeneinander gespielt hat (1on1 / 3way).
    """
    groups = []
    slot_elo_changes = get_slot_elo_changes(slot_id)

    for match_index, match in enumerate(get_matches_for_slot(slot_id), start=1):
        if public_only_complete_matches and not is_match_publicly_complete(match):
            continue

        players = []
        for player in get_match_players(match):
            time_value = normalize_text(match.get(player["time_col"]))
            result_text = normalize_text(match.get(player["result_col"]))
            points = normalize_text(match.get(player["points_col"]))
            seconds = timecode_to_seconds(time_value)
            players.append(
                {
                    "name": player["name"],
                    "discord_id": player["discord_id"],
                    "time": time_value,
                    "seconds": seconds,
                    "result": result_text,
                    "points": int_value(points),
                    "elo_change": normalize_text(slot_elo_changes.get(player["discord_id"], "±0.0")),
                    "is_ff": time_value.upper() == "FF",
                }
            )

        players.sort(
            key=lambda r: (
                r["is_ff"],
                r["seconds"] if r["seconds"] is not None else 9999999,
                r["name"].lower(),
            )
        )

        match_type = normalize_text(match.get("Matchtyp"))
        if not match_type:
            match_type = "3way" if len(players) == 3 else "1on1"

        groups.append(
            {
                "index": match_index,
                "match_id": normalize_text(match.get("Match ID")),
                "match_type": match_type,
                "players": players,
            }
        )

    return groups


def build_public_match_group_lines(match_groups: list[dict]) -> list[str]:
    lines: list[str] = []

    for group in match_groups:
        type_label = "3way" if group["match_type"].lower() == "3way" else "1on1"
        names = " vs ".join(player["name"] for player in group["players"])
        lines.append(f"**Match {group['index']} ({type_label}):** {names}")

        for player in group["players"]:
            lines.append(
                f"- {player['name']}: `{player['time']}` | `{player['result']}` | `{player['elo_change']}`"
            )

        lines.append("")

    while lines and not lines[-1].strip():
        lines.pop()

    return lines


def get_slot_active_runner_counts(slot_id: str) -> tuple[int, int]:
    """
    Rückgabe: (aktiv, gesamt)
    Aktiv = Spieler ohne Finish-Zeit und ohne FF.
    Gesamt = alle Spieler, die in Matches dieses Slots eingeteilt sind.
    """
    active = 0
    total = 0
    seen_player_ids: set[str] = set()

    for match in get_matches_for_slot_combined(slot_id):
        for player in get_match_players(match):
            player_id = normalize_text(player.get("discord_id"))
            player_key = player_id or f"{normalize_text(match.get('Match ID'))}:{player.get('no')}"

            if player_key in seen_player_ids:
                continue

            seen_player_ids.add(player_key)
            total += 1

            time_value = normalize_text(match.get(player["time_col"]))

            if not time_value:
                active += 1

    return active, total


def build_slot_active_status_line(slot_id: str) -> str:
    active, total = get_slot_active_runner_counts(slot_id)

    if total <= 0:
        return "🔴 **AKTIVE RUNNER: `0/0`**"

    return f"🔴 **AKTIVE RUNNER: `{active}/{total}`**"


def build_slot_active_status_message(schedule_row: dict) -> str:
    slot_id = normalize_text(schedule_row.get("Slot ID"))
    datum = normalize_text(schedule_row.get("Datum"))
    slot = normalize_text(schedule_row.get("Slot"))
    startzeit = normalize_text(schedule_row.get("Startzeit"))
    modus = normalize_text(schedule_row.get("Modus"))

    return (
        "**TFNL-Aktivitätsstatus**\n"
        f"Slot ID: `{slot_id}`\n"
        f"`{datum} | {slot} | {startzeit} Uhr | {modus}`\n\n"
        f"{build_slot_active_status_line(slot_id)}\n"
        "_Finish oder FF reduziert den aktiven Zähler._"
    )


def build_slot_overview_message(schedule_row: dict) -> str:
    slot_id = normalize_text(schedule_row.get("Slot ID"))
    datum = normalize_text(schedule_row.get("Datum"))
    slot = normalize_text(schedule_row.get("Slot"))
    modus = normalize_text(schedule_row.get("Modus"))
    seed_url = get_seed_url(schedule_row)
    results = collect_slot_results(slot_id)

    lines = [
        "**TFNL-Slot abgeschlossen**",
        f"Slot ID: `{slot_id}`",
        "",
        f"Datum: `{datum}`",
        f"Slot: `{slot}`",
        f"Modus: `{modus}`",
        f"Seed: {seed_url if seed_url else '`nicht eingetragen`'}",
        build_slot_active_status_line(slot_id),
        "",
        "**Gesamtübersicht:**",
    ]

    if not results:
        lines.append("Keine Ergebnisse gefunden.")
    else:
        table_rows = []
        for index, result in enumerate(results, start=1):
            table_rows.append(
                [
                    index,
                    result["name"],
                    result["time"],
                    result["result"],
                    color_elo_change(result["elo_change"]),
                ]
            )

        lines.append(
            build_discord_ansi_table(
                ["#", "Spieler", "Zeit", "Ergebnis", "ELO ges."],
                table_rows,
                max_col_width=20,
            )
        )

    lines.extend(["", "Der Channel wird 60 Minuten nach Abschluss gelöscht."])
    return "\n".join(lines)


def build_public_slot_results_message(schedule_row: dict, completed: bool = False) -> str:
    """
    Öffentlicher Ergebnis-Channel:
    Eine Nachricht pro Slot. Sobald ein Match vollständig abgeschlossen ist,
    wird diese Nachricht erstellt oder editiert. Die Ansicht kombiniert eine
    kompakte Tabelle mit einer klaren Match-Ansicht (1on1 / 3way).
    """
    slot_id = normalize_text(schedule_row.get("Slot ID"))
    datum = normalize_text(schedule_row.get("Datum"))
    slot = normalize_text(schedule_row.get("Slot"))
    modus = normalize_text(schedule_row.get("Modus"))
    seed_url = get_seed_url(schedule_row)
    results = collect_slot_results(slot_id, public_only_complete_matches=True)
    match_groups = collect_slot_match_groups(slot_id, public_only_complete_matches=True)

    title = "**TFNL-Slot abgeschlossen**" if completed else "**TFNL-Slot Ergebnisse**"

    lines = [
        title,
        f"Slot ID: `{slot_id}`",
        "",
        f"Datum: `{datum}`",
        f"Slot: `{slot}`",
        f"Modus: `{modus}`",
        f"Seed: {seed_url if seed_url else '`nicht eingetragen`'}",
        build_slot_active_status_line(slot_id),
        "",
        "**Bisherige vollständig abgeschlossene Matches:**" if not completed else "**Endstand:**",
    ]

    if not results:
        lines.append("Noch kein vollständig abgeschlossenes Match gefunden.")
    else:
        table_rows = []
        running_no = 1
        for group in match_groups:
            match_label = f"M{group['index']}"
            for player in group["players"]:
                table_rows.append(
                    [
                        match_label,
                        running_no,
                        player["name"],
                        player["time"],
                        player["result"],
                        color_elo_change(player["elo_change"]),
                    ]
                )
                running_no += 1

        lines.append(
            build_discord_ansi_table(
                ["Match", "#", "Spieler", "Zeit", "Ergebnis", "ELO ges."],
                table_rows,
                max_col_width=20,
            )
        )

        lines.append("")
        lines.append("**Matchübersicht:**")
        lines.extend(build_public_match_group_lines(match_groups))

    if not completed:
        lines.extend(["", "_Weitere vollständig abgeschlossene Matches werden in dieser Nachricht ergänzt._"])

    return "\n".join(lines)



def int_value(value) -> int:
    try:
        return int(value)
    except Exception:
        return 0


# =========================================================
# PLAYERS TABLE
# =========================================================

def update_players_from_match(match_row: dict):
    players_sheet = get_players_sheet()
    existing_rows = load_players_rows_with_index()
    active_season = get_active_season_for_row(match_row)

    existing_by_id = {
        normalize_text(row.get("Discord ID")): (row_index, row)
        for row_index, row in existing_rows
    }

    match_players = get_match_players(match_row)
    slot_id = normalize_text(match_row.get("Slot ID"))

    for player in match_players:
        player_id = player["discord_id"]
        player_name = player["name"]
        time_value = normalize_text(match_row.get(player["time_col"]))
        result_text = normalize_text(match_row.get(player["result_col"]))
        points = int_value(match_row.get(player["points_col"]))

        opponents = [
            p["name"] for p in match_players
            if p["discord_id"] != player_id
        ]

        if player_id in existing_by_id:
            row_index, current = existing_by_id[player_id]

            new_points = int_value(current.get("Punkte")) + points
            new_starts = int_value(current.get("Starts")) + 1
            new_wins = int_value(current.get("Siege")) + (1 if result_text == "Sieg" else 0)
            new_draws = int_value(current.get("Remis")) + (1 if result_text == "Remis" else 0)
            new_losses = int_value(current.get("Niederlagen")) + (1 if result_text == "Niederlage" else 0)
            new_forfeits = int_value(current.get("Forfeits")) + (1 if time_value.upper() == "FF" else 0)

            values = [
                player_id,
                player_name,
                new_points,
                new_starts,
                new_wins,
                new_draws,
                new_losses,
                new_forfeits,
                ", ".join(opponents),
                slot_id,
                active_season,
            ]

            sheet_write_call(
                lambda row_index=row_index, values=values: players_sheet.update(f"A{row_index}:K{row_index}", [values]),
                invalidate_prefixes=[
                    f"records:{PLAYERS_SHEET_NAME}",
                    f"values:{PLAYERS_SHEET_NAME}",
                    f"row:{PLAYERS_SHEET_NAME}:",
                ],
            )

        else:
            values = [
                player_id,
                player_name,
                points,
                1,
                1 if result_text == "Sieg" else 0,
                1 if result_text == "Remis" else 0,
                1 if result_text == "Niederlage" else 0,
                1 if time_value.upper() == "FF" else 0,
                ", ".join(opponents),
                slot_id,
                active_season,
            ]

            sheet_write_call(
                lambda values=values: players_sheet.append_row(values, value_input_option="USER_ENTERED"),
                invalidate_prefixes=[
                    f"records:{PLAYERS_SHEET_NAME}",
                    f"values:{PLAYERS_SHEET_NAME}",
                ],
            )

    sort_players_sheet()

def build_player_sheet_values(rows: list[dict]) -> list[list]:
    values = []

    for row in rows:
        values.append(
            [
                normalize_text(row.get("Discord ID")),
                normalize_text(row.get("Discord Display Name")),
                int_value(row.get("Punkte")),
                int_value(row.get("Starts")),
                int_value(row.get("Siege")),
                int_value(row.get("Remis")),
                int_value(row.get("Niederlagen")),
                int_value(row.get("Forfeits")),
                normalize_text(row.get("Letzter Gegner")),
                normalize_text(row.get("Letzter Start")),
                normalize_text(row.get("Season")),
            ]
        )

    return values


def sort_players_sheet():
    sheet = get_players_sheet()
    active_season = get_active_season()
    rows = load_players_rows_all()

    if not rows:
        return

    active_rows = [row for row in rows if row_matches_season(row, active_season)]
    other_rows = [row for row in rows if not row_matches_season(row, active_season)]

    active_rows.sort(
        key=lambda r: (
            -int_value(r.get("Punkte")),
            -int_value(r.get("Siege")),
            -int_value(r.get("Remis")),
            int_value(r.get("Forfeits")),
            normalize_text(r.get("Discord Display Name")).lower(),
        )
    )

    values = build_player_sheet_values(active_rows + other_rows)

    sheet_write_call(
        lambda: sheet.resize(rows=max(1000, len(values) + 1), cols=len(PLAYERS_HEADERS)),
        invalidate_prefixes=[],
    )
    sheet_write_call(
        lambda: sheet.batch_clear(["A2:K1000"]),
        invalidate_prefixes=[],
    )

    if values:
        sheet_write_call(
            lambda: sheet.update("A2:K", values, value_input_option="USER_ENTERED"),
            invalidate_prefixes=[
                f"records:{PLAYERS_SHEET_NAME}",
                f"values:{PLAYERS_SHEET_NAME}",
            ],
        )
    else:
        invalidate_sheet_cache(PLAYERS_SHEET_NAME)

    invalidate_sheet_cache(PLAYERS_SHEET_NAME)

def rebuild_players_from_published_matches(season: str | None = None) -> dict[str, int]:
    """
    Baut die Players-Tabelle vollständig aus Matches einer Season neu auf.

    Grundlage:
    - Matches.Season = season oder ACTIVE_SEASON
    - Matches.Status = finished
    - Matches.Veröffentlicht = Ja

    Diese Funktion ist idempotent:
    Sie kann mehrfach ausgeführt werden, ohne Punkte doppelt zu zählen.
    """
    selected_season = normalize_text(season) or get_active_season()
    matches = load_matches_rows_combined(selected_season)
    standings: dict[str, dict] = {}
    processed_matches = 0
    processed_player_results = 0

    for match in matches:
        if normalize_text(match.get("Status")).lower() != "finished":
            continue

        if normalize_text(match.get("Veröffentlicht")).lower() != "ja":
            continue

        match_players = get_match_players(match)
        slot_id = normalize_text(match.get("Slot ID"))

        if not match_players:
            continue

        match_counted = False

        for player in match_players:
            player_id = normalize_text(player.get("discord_id"))
            player_name = normalize_text(player.get("name"))

            if not player_id:
                continue

            time_value = normalize_text(match.get(player["time_col"]))
            result_text = normalize_text(match.get(player["result_col"]))
            points = int_value(match.get(player["points_col"]))

            if not time_value or not result_text:
                continue

            opponents = [
                p["name"] for p in match_players
                if p["discord_id"] != player_id
            ]

            if player_id not in standings:
                standings[player_id] = {
                    "Discord ID": player_id,
                    "Discord Display Name": player_name,
                    "Punkte": 0,
                    "Starts": 0,
                    "Siege": 0,
                    "Remis": 0,
                    "Niederlagen": 0,
                    "Forfeits": 0,
                    "Letzter Gegner": "",
                    "Letzter Start": "",
                    "Season": selected_season,
                }

            row = standings[player_id]
            row["Discord Display Name"] = player_name or row["Discord Display Name"]
            row["Punkte"] += points
            row["Starts"] += 1
            row["Siege"] += 1 if result_text == "Sieg" else 0
            row["Remis"] += 1 if result_text == "Remis" else 0
            row["Niederlagen"] += 1 if result_text == "Niederlage" else 0
            row["Forfeits"] += 1 if time_value.upper() == "FF" else 0
            row["Letzter Gegner"] = ", ".join(opponents)
            row["Letzter Start"] = slot_id

            processed_player_results += 1
            match_counted = True

        if match_counted:
            processed_matches += 1

    active_rows = list(standings.values())

    active_rows.sort(
        key=lambda r: (
            -int_value(r.get("Punkte")),
            -int_value(r.get("Siege")),
            -int_value(r.get("Remis")),
            int_value(r.get("Forfeits")),
            normalize_text(r.get("Discord Display Name")).lower(),
        )
    )

    existing_rows = load_players_rows_all()
    other_rows = [row for row in existing_rows if not row_matches_season(row, selected_season)]
    values = build_player_sheet_values(active_rows + other_rows)

    sheet = get_players_sheet()
    sheet_write_call(
        lambda: sheet.resize(rows=max(1000, len(values) + 1), cols=len(PLAYERS_HEADERS)),
        invalidate_prefixes=[],
    )
    sheet_write_call(
        lambda: sheet.batch_clear(["A2:K1000"]),
        invalidate_prefixes=[],
    )

    if values:
        sheet_write_call(
            lambda: sheet.update("A2:K", values, value_input_option="USER_ENTERED"),
            invalidate_prefixes=[
                f"records:{PLAYERS_SHEET_NAME}",
                f"values:{PLAYERS_SHEET_NAME}",
            ],
        )

    invalidate_sheet_cache(PLAYERS_SHEET_NAME)

    return {
        "season": selected_season,
        "players": len(active_rows),
        "matches": processed_matches,
        "player_results": processed_player_results,
    }


def get_latest_completed_slot_id_for_scope(mode_name: str | None = None) -> str:
    requested_mode = get_canonical_mode_name(mode_name) if normalize_text(mode_name) else ""
    schedule_modes = get_schedule_mode_map()
    matches = load_matches_rows_combined()
    best_slot_id = ""
    best_dt = None

    for row in load_schedule_rows_combined():
        slot_id = normalize_text(row.get("Slot ID"))

        if not slot_id:
            continue

        if requested_mode:
            mode = normalize_text(schedule_modes.get(slot_id) or row.get("Modus"))
            if get_canonical_mode_name(mode) != requested_mode:
                continue

        if not any(
            normalize_text(match.get("Slot ID")) == slot_id
            and normalize_text(match.get("Status")).lower() == "finished"
            and normalize_text(match.get("Veröffentlicht")).lower() == "ja"
            for match in matches
        ):
            continue

        completed_dt = parse_completed_at(row.get(SCHEDULE_COMPLETED_AT_COL))
        if completed_dt is None:
            completed_dt = get_slot_start_dt(row)

        if completed_dt is None:
            continue

        if best_dt is None or completed_dt > best_dt:
            best_dt = completed_dt
            best_slot_id = slot_id

    return best_slot_id


def get_slot_player_ids(slot_id: str) -> set[str]:
    player_ids: set[str] = set()

    if not normalize_text(slot_id):
        return player_ids

    for match in get_matches_for_slot_combined(slot_id):
        for player in get_match_players(match):
            player_id = normalize_text(player.get("discord_id"))
            if player_id:
                player_ids.add(player_id)

    return player_ids


def calculate_rank_deltas(
    rows: list[dict],
    latest_slot_id: str,
    scope: str,
) -> dict[str, int]:
    if not latest_slot_id:
        return {}

    slot_changes = get_slot_elo_changes(latest_slot_id, scope=scope)

    if not slot_changes:
        return {}

    current_rank_by_id = {
        normalize_text(row.get("Player ID")): index
        for index, row in enumerate(rows, start=1)
        if normalize_text(row.get("Player ID"))
    }

    previous_rows = []
    for row in rows:
        player_id = normalize_text(row.get("Player ID"))
        current_elo = parse_float_value(row.get("Elo"), 1000.0)
        change = parse_float_value(slot_changes.get(player_id), 0.0)
        previous_elo = current_elo - change

        previous_rows.append(
            {
                "player_id": player_id,
                "name": normalize_text(row.get("Player Name")),
                "previous_elo": previous_elo,
            }
        )

    previous_rows.sort(
        key=lambda row: (
            -row["previous_elo"],
            row["name"].lower(),
        )
    )

    previous_rank_by_id = {
        row["player_id"]: index
        for index, row in enumerate(previous_rows, start=1)
        if row["player_id"]
    }

    deltas: dict[str, int] = {}
    for player_id, current_rank in current_rank_by_id.items():
        previous_rank = previous_rank_by_id.get(player_id)

        if previous_rank is None:
            deltas[player_id] = 0
        else:
            deltas[player_id] = previous_rank - current_rank

    return deltas


def build_overall_match_stats() -> dict[str, dict]:
    """
    Statistikquelle für G/S/U/N/FF.
    ELO bleibt in Ladder_Ratings, aber die Spielstatistiken werden aus Matches
    berechnet. Dadurch können ELO und Games nicht mehr auseinanderlaufen.
    """
    stats_by_id: dict[str, dict] = {}

    for match in load_matches_rows_combined():
        if normalize_text(match.get("Veröffentlicht")).lower() != "ja":
            continue

        if normalize_text(match.get("Status")).lower() != "finished":
            continue

        for player in get_match_players(match):
            player_id = player["discord_id"]
            player_name = player["name"]
            time_value = normalize_text(match.get(player["time_col"]))
            result_text = normalize_text(match.get(player["result_col"]))

            if not player_id:
                continue

            if player_id not in stats_by_id:
                stats_by_id[player_id] = {
                    "discord_id": player_id,
                    "name": player_name,
                    "starts": 0,
                    "wins": 0,
                    "draws": 0,
                    "losses": 0,
                    "forfeits": 0,
                }

            row = stats_by_id[player_id]
            row["name"] = player_name
            row["starts"] += 1
            row["wins"] += 1 if result_text == "Sieg" else 0
            row["draws"] += 1 if result_text == "Remis" else 0
            row["losses"] += 1 if result_text == "Niederlage" else 0
            row["forfeits"] += 1 if time_value.upper() == "FF" else 0

    return stats_by_id


def get_player_forfeits_by_id() -> dict[str, int]:
    return {
        player_id: int_value(stats.get("forfeits"))
        for player_id, stats in build_overall_match_stats().items()
    }


def build_standings_messages() -> list[str]:
    timestamp = datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M")
    active_season = get_active_season()
    rows = build_elo_standings_rows(
        scope=SCOPE_SEASON_OVERALL,
        season=active_season,
        mode="",
        limit=None,
    )
    stats_by_id = build_overall_match_stats()
    latest_slot_id = get_latest_completed_slot_id_for_scope()
    last_race_player_ids = get_slot_player_ids(latest_slot_id)
    rank_deltas = calculate_rank_deltas(
        rows=rows,
        latest_slot_id=latest_slot_id,
        scope=SCOPE_SEASON_OVERALL,
    )

    if not rows:
        return [
            f"**TFNL Gesamttabelle — {active_season}**\n"
            f"Stand: `{timestamp} Uhr`\n\n"
            "Noch keine ELO-Einträge."
        ]

    table_rows = []
    for index, row in enumerate(rows, start=1):
        player_id = normalize_text(row.get("Player ID"))
        stats = stats_by_id.get(player_id, {})

        wins = int_value(stats.get("wins"))
        draws = int_value(stats.get("draws"))
        losses = int_value(stats.get("losses"))
        games = int_value(stats.get("starts"))
        forfeits = int_value(stats.get("forfeits"))

        table_rows.append(
            [
                index,
                color_rank_delta(rank_deltas.get(player_id, 0)),
                color_last_race_player_name(
                    normalize_text(row.get("Player Name")),
                    player_id,
                    last_race_player_ids,
                ),
                normalize_text(row.get("Elo")) or "1000.0",
                games,
                color_stat_value(wins, "S"),
                color_stat_value(draws, "U"),
                color_stat_value(losses, "N"),
                color_stat_value(forfeits, "FF"),
            ]
        )

    table = build_discord_ansi_table(
        ["#", "+/-", "Spieler", "ELO", "G", "S", "U", "N", "FF"],
        table_rows,
        max_col_width=18,
    )

    return [
        f"**TFNL Gesamttabelle — {active_season}**\n"
        f"Stand: `{timestamp} Uhr`\n"
        f"{table}"
    ]


def build_final_season_standings_messages() -> list[str]:
    """
    Saison-Endwertung:
    Live-ELO/Pairing bleibt unverändert. Der FF-Abzug wird ausschließlich
    in dieser Endwertung berechnet.
    """
    timestamp = datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M")
    active_season = get_active_season()
    rows = build_elo_standings_rows(
        scope=SCOPE_SEASON_OVERALL,
        season=active_season,
        mode="",
        limit=None,
    )
    stats_by_id = build_overall_match_stats()

    if not rows:
        return [
            f"**TFNL Saison-Endwertung — {active_season}**\n"
            f"Stand: `{timestamp} Uhr`\n\n"
            "Noch keine ELO-Einträge."
        ]

    final_rows = []

    for row in rows:
        player_id = normalize_text(row.get("Player ID"))
        stats = stats_by_id.get(player_id, {})

        forfeits = int_value(stats.get("forfeits"))
        penalty = calculate_ff_penalty(forfeits)
        base_score = parse_float_value(row.get("Elo"), 1000.0)
        final_score = base_score - penalty

        final_rows.append(
            {
                "player_id": player_id,
                "player_name": normalize_text(row.get("Player Name")),
                "base_score": base_score,
                "final_score": final_score,
                "penalty": penalty,
                "games": int_value(stats.get("starts")),
                "wins": int_value(stats.get("wins")),
                "draws": int_value(stats.get("draws")),
                "losses": int_value(stats.get("losses")),
                "forfeits": forfeits,
            }
        )

    final_rows.sort(
        key=lambda row: (
            -row["final_score"],
            -row["base_score"],
            row["player_name"].lower(),
        )
    )

    table_rows = []

    for index, row in enumerate(final_rows, start=1):
        table_rows.append(
            [
                index,
                row["player_name"] or "0",
                f"{row['base_score']:.1f}",
                color_penalty_value(row["penalty"]),
                f"{row['final_score']:.1f}",
                row["games"],
                color_stat_value(row["wins"], "S"),
                color_stat_value(row["draws"], "U"),
                color_stat_value(row["losses"], "N"),
                color_stat_value(row["forfeits"], "FF"),
            ]
        )

    table = build_discord_ansi_table(
        ["#", "Spieler", "Score", "FF-Abzug", "Endscore", "G", "S", "U", "N", "FF"],
        table_rows,
        max_col_width=16,
    )

    return [
        f"**TFNL Saison-Endwertung — {active_season}**\n"
        f"Stand: `{timestamp} Uhr`\n"
        f"FF-Abzug erst zur Endwertung: `(FF - {TFNL_FF_PENALTY_FREE_COUNT}) * {TFNL_FF_PENALTY_POINTS}`, mindestens `0`.\n"
        f"{table}"
    ]


# =========================================================
# MODE STANDINGS
# =========================================================

def get_schedule_mode_map() -> dict[str, str]:
    rows = load_schedule_rows_combined()

    return {
        normalize_text(row.get("Slot ID")): normalize_text(row.get("Modus"))
        for row in rows
        if normalize_text(row.get("Slot ID"))
    }


def build_mode_standings(mode_name: str) -> list[dict]:
    requested_mode = get_canonical_mode_name(mode_name)
    schedule_modes = get_schedule_mode_map()
    matches = load_matches_rows_combined()

    standings = {}

    for match in matches:
        slot_id = normalize_text(match.get("Slot ID"))
        match_mode = schedule_modes.get(slot_id, "")

        if get_canonical_mode_name(match_mode) != requested_mode:
            continue

        if normalize_text(match.get("Veröffentlicht")).lower() != "ja":
            continue

        if normalize_text(match.get("Status")).lower() != "finished":
            continue

        for player in get_match_players(match):
            player_id = player["discord_id"]
            player_name = player["name"]
            time_value = normalize_text(match.get(player["time_col"]))
            result_text = normalize_text(match.get(player["result_col"]))
            points = int_value(match.get(player["points_col"]))
            seconds = timecode_to_seconds(time_value)

            if not player_id:
                continue

            if player_id not in standings:
                standings[player_id] = {
                    "discord_id": player_id,
                    "name": player_name,
                    "points": 0,
                    "starts": 0,
                    "wins": 0,
                    "draws": 0,
                    "losses": 0,
                    "forfeits": 0,
                    "finished_seconds": [],
                }

            row = standings[player_id]

            row["name"] = player_name
            row["points"] += points
            row["starts"] += 1
            row["wins"] += 1 if result_text == "Sieg" else 0
            row["draws"] += 1 if result_text == "Remis" else 0
            row["losses"] += 1 if result_text == "Niederlage" else 0
            row["forfeits"] += 1 if time_value.upper() == "FF" else 0

            if seconds is not None:
                row["finished_seconds"].append(seconds)

    rows = list(standings.values())

    for row in rows:
        finished = row["finished_seconds"]

        row["best_seconds"] = min(finished) if finished else None
        row["avg_seconds"] = int(sum(finished) / len(finished)) if finished else None

    rows.sort(
        key=lambda r: (
            -r["points"],
            -r["wins"],
            -r["draws"],
            r["forfeits"],
            r["best_seconds"] if r["best_seconds"] is not None else 9999999,
            r["name"].lower(),
        )
    )

    return rows


def build_mode_standings_messages(mode_name: str) -> list[str]:
    timestamp = datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M")
    active_season = get_active_season()

    elo_rows = build_elo_standings_rows(
        scope=SCOPE_SEASON_MODE,
        season=active_season,
        mode=mode_name,
        limit=None,
    )

    mode_stats = build_mode_standings(mode_name)
    stats_by_id = {
        normalize_text(row.get("discord_id")): row
        for row in mode_stats
        if normalize_text(row.get("discord_id"))
    }

    latest_slot_id = get_latest_completed_slot_id_for_scope(mode_name)
    last_race_player_ids = get_slot_player_ids(latest_slot_id)
    rank_deltas = calculate_rank_deltas(
        rows=elo_rows,
        latest_slot_id=latest_slot_id,
        scope=SCOPE_SEASON_MODE,
    )

    if not elo_rows:
        return [
            f"**TFNL Modus-Tabelle: {mode_name}**\n"
            f"Stand: `{timestamp} Uhr`\n\n"
            "Keine abgeschlossenen ELO-Ergebnisse für diesen Modus gefunden."
        ]

    table_rows = []
    for index, row in enumerate(elo_rows, start=1):
        player_id = normalize_text(row.get("Player ID"))
        stats = stats_by_id.get(player_id, {})

        wins = int_value(stats.get("wins"))
        draws = int_value(stats.get("draws"))
        losses = int_value(stats.get("losses"))
        games = int_value(stats.get("starts"))
        forfeits = int_value(stats.get("forfeits"))
        best = seconds_to_timecode(stats.get("best_seconds")) if stats.get("best_seconds") is not None else "0"
        avg = seconds_to_timecode(stats.get("avg_seconds")) if stats.get("avg_seconds") is not None else "0"

        table_rows.append(
            [
                index,
                color_rank_delta(rank_deltas.get(player_id, 0)),
                color_last_race_player_name(
                    normalize_text(row.get("Player Name")),
                    player_id,
                    last_race_player_ids,
                ),
                normalize_text(row.get("Elo")) or "1000.0",
                games,
                color_stat_value(wins, "S"),
                color_stat_value(draws, "U"),
                color_stat_value(losses, "N"),
                color_stat_value(forfeits, "FF"),
                best,
                avg,
            ]
        )

    table = build_discord_ansi_table(
        ["#", "+/-", "Spieler", "ELO", "G", "S", "U", "N", "FF", "Best", "Ø"],
        table_rows,
        max_col_width=16,
    )

    return [
        f"**TFNL Modus-Tabelle: {mode_name}**\n"
        f"Stand: `{timestamp} Uhr`\n"
        f"{table}"
    ]

def get_completed_match_modes() -> list[str]:
    schedule_modes = get_schedule_mode_map()
    matches = load_matches_rows_combined()
    modes_by_canonical: dict[str, str] = {}

    for match in matches:
        if normalize_text(match.get("Status")).lower() != "finished":
            continue

        if normalize_text(match.get("Veröffentlicht")).lower() != "ja":
            continue

        slot_id = normalize_text(match.get("Slot ID"))
        mode_name = normalize_text(schedule_modes.get(slot_id))

        if not mode_name:
            continue

        canonical = get_canonical_mode_name(mode_name)

        if canonical not in modes_by_canonical:
            modes_by_canonical[canonical] = mode_name

    preferred_order = [
        "casual boots",
        "open",
        "inverted",
        "open ad boots",
        "invrosia",
        "ambrosia",
        "ludicrous speed",
        "hard standard",
        "standard",
        "tfl hard standard",
        "keysanity",
        "ad keysanity mit boots",
        "ad keys",
        "mc boss",
        "influkeys",
        "crosskeys",
    ]

    ordered_modes = []

    for canonical in preferred_order:
        if canonical in modes_by_canonical:
            ordered_modes.append(modes_by_canonical.pop(canonical))

    for canonical in sorted(modes_by_canonical):
        ordered_modes.append(modes_by_canonical[canonical])

    return ordered_modes


def build_all_mode_standings_messages() -> list[str]:
    messages = []

    for mode_name in get_completed_match_modes():
        messages.extend(build_mode_standings_messages(mode_name))

    return messages


def get_visible_race_slots_for_signup_channel() -> list[dict]:
    rows = load_schedule_rows()
    visible_statuses = {
        "registration_open",
        "paired",
        "seed_sent",
        "countdown_sent",
        "running",
    }

    visible_rows = []

    for row in rows:
        status = normalize_text(row.get("Status")).lower()

        if status not in visible_statuses:
            continue

        slot_id = normalize_text(row.get("Slot ID"))

        if not slot_id:
            continue

        visible_rows.append(row)

    today = datetime.now(BERLIN_TZ).date()

    visible_rows.sort(
        key=lambda r: (
            parse_german_date(r.get("Datum")) or today,
            normalize_text(r.get("Startzeit")),
            normalize_text(r.get("Slot ID")),
        )
    )

    return visible_rows


def build_public_race_participants_embed() -> discord.Embed:
    now = datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M")
    slots = get_visible_race_slots_for_signup_channel()

    if not slots:
        description = "Aktuell keine offene oder laufende Ladder-Anmeldung."
    else:
        sections = []

        for row in slots:
            slot_id = normalize_text(row.get("Slot ID"))
            datum = normalize_text(row.get("Datum"))
            slot = normalize_text(row.get("Slot"))
            startzeit = normalize_text(row.get("Startzeit"))
            modus = normalize_text(row.get("Modus"))
            status = normalize_text(row.get("Status")) or "planned"
            names = get_signup_names_for_slot(slot_id)

            section_lines = [
                f"**{datum} | {slot} | {startzeit} Uhr — {modus}**",
                f"Status: `{status}`",
            ]

            if not names:
                section_lines.append("_Noch niemand angemeldet._")
            else:
                player_rows = [[index, name] for index, name in enumerate(names, start=1)]
                section_lines.append(
                    build_discord_table(["#", "Runner"], player_rows, max_col_width=30)
                )

            sections.append("\n".join(section_lines))

        description = "\n\n".join(sections)

    embed = discord.Embed(
        title="TFNL – Teilnehmer laufender Slots",
        description=description,
        color=discord.Color.dark_teal(),
    )

    embed.set_footer(text=f"Bleibt bis Slot-Ende sichtbar | Aktualisiert: {now} Uhr")
    return embed



# =========================================================
# SEASON ARCHIVE
# =========================================================

def get_archive_sheet_name(source_sheet_name: str) -> str:
    mapping = {
        SCHEDULE_SHEET_NAME: ARCHIVE_SCHEDULE_SHEET_NAME,
        SIGNUP_SHEET_NAME: ARCHIVE_SIGNUP_SHEET_NAME,
        MATCHES_SHEET_NAME: ARCHIVE_MATCHES_SHEET_NAME,
        PLAYERS_SHEET_NAME: ARCHIVE_PLAYERS_SHEET_NAME,
    }
    return mapping[source_sheet_name]


def get_source_sheet_and_headers(source_sheet_name: str):
    if source_sheet_name == SCHEDULE_SHEET_NAME:
        sheet = get_schedule_sheet()
    elif source_sheet_name == SIGNUP_SHEET_NAME:
        sheet = get_signup_sheet()
    elif source_sheet_name == MATCHES_SHEET_NAME:
        sheet = get_matches_sheet()
    elif source_sheet_name == PLAYERS_SHEET_NAME:
        sheet = get_players_sheet()
    else:
        raise RuntimeError(f"Unbekanntes Sheet: {source_sheet_name}")

    headers = row_values_cached(
        lambda: sheet,
        sheet_name=source_sheet_name,
        row=1,
        ttl_seconds=300,
    )

    if "Season" not in headers:
        headers.append("Season")
        sheet_write_call(
            lambda: sheet.update("A1", [headers]),
            invalidate_prefixes=[
                f"records:{source_sheet_name}",
                f"values:{source_sheet_name}",
                f"row:{source_sheet_name}:",
            ],
        )
        HEADER_CACHE[source_sheet_name] = headers

    return sheet, headers

def get_or_create_archive_sheet(source_sheet_name: str, headers: list[str]):
    spreadsheet = get_tfnl_spreadsheet()
    archive_name = get_archive_sheet_name(source_sheet_name)

    try:
        sheet = spreadsheet.worksheet(archive_name)
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(
            title=archive_name,
            rows=1000,
            cols=max(len(headers), 1),
        )

    existing_headers = row_values_cached(
        lambda: sheet,
        sheet_name=archive_name,
        row=1,
        ttl_seconds=300,
    )

    if existing_headers != headers:
        sheet_write_call(
            lambda: sheet.update("A1", [headers]),
            invalidate_prefixes=[
                f"records:{archive_name}",
                f"values:{archive_name}",
                f"row:{archive_name}:",
            ],
        )

    return sheet

def get_archive_unique_key(source_sheet_name: str, row: dict, season: str) -> str:
    if source_sheet_name == SCHEDULE_SHEET_NAME:
        return f"{season}|{normalize_text(row.get('Slot ID'))}"

    if source_sheet_name == SIGNUP_SHEET_NAME:
        return f"{season}|{normalize_text(row.get('Slot ID'))}|{normalize_text(row.get('Discord ID'))}"

    if source_sheet_name == MATCHES_SHEET_NAME:
        return f"{season}|{normalize_text(row.get('Match ID'))}"

    if source_sheet_name == PLAYERS_SHEET_NAME:
        return f"{season}|{normalize_text(row.get('Discord ID'))}"

    return f"{season}|{repr(row)}"


def get_all_rows_for_sheet(source_sheet_name: str) -> list[dict]:
    if source_sheet_name == SCHEDULE_SHEET_NAME:
        return load_schedule_rows_all()

    if source_sheet_name == SIGNUP_SHEET_NAME:
        return load_signup_rows_all()

    if source_sheet_name == MATCHES_SHEET_NAME:
        return load_matches_rows_all()

    if source_sheet_name == PLAYERS_SHEET_NAME:
        return load_players_rows_all()

    return []


def get_source_rows_with_real_indexes(source_sheet, headers: list[str]) -> list[tuple[int, dict]]:
    sheet_name = getattr(source_sheet, "title", "source")
    values = get_all_values_cached(
        lambda: source_sheet,
        sheet_name=sheet_name,
        ttl_seconds=30,
        force_refresh=True,
    )

    if len(values) <= 1:
        return []

    rows = []

    for row_index, raw_values in enumerate(values[1:], start=2):
        if not any(normalize_text(value) for value in raw_values):
            continue

        row = {}

        for col_index, header in enumerate(headers):
            row[header] = raw_values[col_index] if col_index < len(raw_values) else ""

        rows.append((row_index, row))

    return rows

def group_contiguous_row_indexes(row_indexes: list[int]) -> list[tuple[int, int]]:
    if not row_indexes:
        return []

    sorted_rows = sorted(set(row_indexes))
    groups = []
    start = sorted_rows[0]
    previous = sorted_rows[0]

    for row_index in sorted_rows[1:]:
        if row_index == previous + 1:
            previous = row_index
            continue

        groups.append((start, previous))
        start = row_index
        previous = row_index

    groups.append((start, previous))
    return groups


def delete_rows_batch(sheet, row_indexes: list[int]) -> int:
    if not row_indexes:
        return 0

    sheet_id = int(getattr(sheet, "id", 0))
    spreadsheet = get_tfnl_spreadsheet()

    requests = []

    # Von unten nach oben löschen, damit sich die noch folgenden Zeilenindizes nicht verschieben.
    for start_row, end_row in sorted(group_contiguous_row_indexes(row_indexes), reverse=True):
        requests.append(
            {
                "deleteDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": start_row - 1,
                        "endIndex": end_row,
                    }
                }
            }
        )

    if requests:
        sheet_write_call(
            lambda: spreadsheet.batch_update({"requests": requests}),
            invalidate_prefixes=[
                f"records:{getattr(sheet, 'title', '')}",
                f"values:{getattr(sheet, 'title', '')}",
            ],
        )

    return len(set(row_indexes))

def archive_sheet_rows_for_season(source_sheet_name: str, season: str, delete_from_live: bool = False) -> dict[str, int]:
    source_sheet, headers = get_source_sheet_and_headers(source_sheet_name)
    archive_sheet = get_or_create_archive_sheet(source_sheet_name, headers)
    archive_name = get_archive_sheet_name(source_sheet_name)

    # Wichtig:
    # Für die Archivierung wird force_refresh genutzt, damit frisch eingetragene Season-Werte nicht übersehen werden.
    source_rows = get_source_rows_with_real_indexes(source_sheet, headers)
    archive_rows = get_all_records_cached(
        lambda: archive_sheet,
        sheet_name=archive_name,
        ttl_seconds=30,
        force_refresh=True,
    )

    existing_keys = {
        get_archive_unique_key(source_sheet_name, row, season)
        for row in archive_rows
        if row_matches_season(row, season)
    }

    values_to_append = []
    rows_to_delete = []
    copied = 0
    skipped = 0
    matched = 0

    for row_index, row in source_rows:
        if not row_matches_season(row, season):
            continue

        matched += 1
        key = get_archive_unique_key(source_sheet_name, row, season)

        if key in existing_keys:
            skipped += 1
        else:
            values_to_append.append([normalize_text(row.get(header)) for header in headers])
            existing_keys.add(key)
            copied += 1

        if delete_from_live:
            rows_to_delete.append(row_index)

    if values_to_append:
        sheet_write_call(
            lambda: archive_sheet.append_rows(values_to_append, value_input_option="USER_ENTERED"),
            invalidate_prefixes=[
                f"records:{archive_name}",
                f"values:{archive_name}",
            ],
        )

    deleted = 0

    if delete_from_live and rows_to_delete:
        deleted = delete_rows_batch(source_sheet, rows_to_delete)

    invalidate_sheet_cache(source_sheet_name)
    invalidate_sheet_cache(archive_name)

    return {
        "matched": matched,
        "copied": copied,
        "skipped": skipped,
        "deleted": deleted,
    }

def get_archive_source_sheet_names(sheet_name: str = "alle") -> tuple[str, ...]:
    selected_sheet = normalize_text(sheet_name).lower()

    mapping = {
        "alle": (
            SCHEDULE_SHEET_NAME,
            SIGNUP_SHEET_NAME,
            MATCHES_SHEET_NAME,
            PLAYERS_SHEET_NAME,
        ),
        "all": (
            SCHEDULE_SHEET_NAME,
            SIGNUP_SHEET_NAME,
            MATCHES_SHEET_NAME,
            PLAYERS_SHEET_NAME,
        ),
        "schedule": (SCHEDULE_SHEET_NAME,),
        "signup": (SIGNUP_SHEET_NAME,),
        "matches": (MATCHES_SHEET_NAME,),
        "players": (PLAYERS_SHEET_NAME,),
    }

    if selected_sheet not in mapping:
        raise RuntimeError(
            "Ungültiges Sheet. Erlaubt sind: alle, schedule, signup, matches, players."
        )

    return mapping[selected_sheet]


def archive_season(
    season: str,
    delete_from_live: bool = False,
    sheet_name: str = "alle",
) -> dict[str, dict[str, int]]:
    selected_season = normalize_text(season)

    if not selected_season:
        raise RuntimeError("Season fehlt.")

    stats = {}

    for source_sheet_name in get_archive_source_sheet_names(sheet_name):
        stats[source_sheet_name] = archive_sheet_rows_for_season(
            source_sheet_name=source_sheet_name,
            season=selected_season,
            delete_from_live=delete_from_live,
        )

    return stats


def build_countdown_dm_content(start_unix: int, value: int | None = None, started: bool = False) -> str:
    if started:
        return (
            "🔴 **TFNL-RACE GESTARTET** 🔴\n\n"
            f"Offizieller Start war: <t:{start_unix}:T>\n"
            "Zeitmessung läuft exakt ab der geplanten Startzeit.\n\n"
            "Die Race-Control-DM mit Finish-/Forfeit-Buttons folgt jetzt."
        )

    if value is None:
        return (
            "🔴 **TFNL COUNTDOWN VORBEREITET** 🔴\n\n"
            f"Offizieller Start: <t:{start_unix}:T>\n"
            "Die Zeitmessung läuft exakt ab der geplanten Startzeit."
        )

    return (
        "🔴 **TFNL COUNTDOWN** 🔴\n"
        "```ansi\n"
        f"{ANSI_RED}████████████████████\n"
        f"        START IN {value:02d}\n"
        f"████████████████████{ANSI_RESET}\n"
        "```\n"
        f"Offizieller Start: <t:{start_unix}:T>"
    )


def build_race_control_dm_content(schedule_row: dict) -> str:
    slot_id = normalize_text(schedule_row.get("Slot ID"))
    start_dt = get_slot_start_dt(schedule_row)
    start_unix = int(start_dt.timestamp()) if start_dt else int(datetime.now(BERLIN_TZ).timestamp())

    return (
        "🔴 **TFNL RACE-CONTROL** 🔴\n\n"
        "Das Race ist gestartet.\n"
        f"Offizieller Start: <t:{start_unix}:T>\n"
        "Zeitmessung läuft exakt ab der geplanten Startzeit.\n\n"
        f"{build_slot_active_status_line(slot_id)}\n\n"
        "Klicke `Finish`, sobald du fertig bist.\n"
        "Klicke `Forfeit`, wenn du aufgibst."
    )


# =========================================================
# DISCORD VIEWS
# =========================================================

class SignupView(discord.ui.View):
    def __init__(self, open_slots: list[dict]):
        super().__init__(timeout=None)

        for row in open_slots[:12]:
            slot_id = normalize_text(row.get("Slot ID"))
            slot = normalize_text(row.get("Slot"))
            startzeit = normalize_text(row.get("Startzeit"))
            modus = normalize_text(row.get("Modus"))
            signup_count = get_signup_count_for_slot(slot_id) if slot_id else 0

            if not slot_id:
                continue

            label_signup = f"Anmelden | {slot} {startzeit} | {modus} ({signup_count})"
            label_cancel = f"Abmelden | {slot} {startzeit}"

            self.add_item(
                discord.ui.Button(
                    label=label_signup[:80],
                    style=discord.ButtonStyle.success,
                    custom_id=f"tfnl_signup:{slot_id}",
                )
            )

            self.add_item(
                discord.ui.Button(
                    label=label_cancel[:80],
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"tfnl_unsubscribe:{slot_id}",
                )
            )


class RaceControlView(discord.ui.View):
    def __init__(self, match_id: str, player_no: int):
        super().__init__(timeout=None)

        self.add_item(
            discord.ui.Button(
                label="Finish",
                style=discord.ButtonStyle.success,
                custom_id=f"tfnl_finish:{match_id}:{player_no}",
            )
        )

        self.add_item(
            discord.ui.Button(
                label="Forfeit",
                style=discord.ButtonStyle.danger,
                custom_id=f"tfnl_forfeit:{match_id}:{player_no}",
            )
        )


class ConfirmForfeitView(discord.ui.View):
    def __init__(self, match_id: str, player_no: int):
        super().__init__(timeout=120)

        self.add_item(
            discord.ui.Button(
                label="Ja, Forfeit eintragen",
                style=discord.ButtonStyle.danger,
                custom_id=f"tfnl_confirm_ff:{match_id}:{player_no}",
            )
        )


class TfnlDmTestView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

        self.add_item(
            discord.ui.Button(
                label="Finish",
                style=discord.ButtonStyle.success,
                disabled=True,
            )
        )

        self.add_item(
            discord.ui.Button(
                label="Forfeit",
                style=discord.ButtonStyle.danger,
                disabled=True,
            )
        )


# =========================================================
# COG
# =========================================================


def build_elo_table_message(scope: str, season: str, mode: str = "", limit: int | None = None) -> str:
    rows = build_elo_standings_rows(scope=scope, season=season, mode=mode, limit=limit)

    scope_titles = {
        SCOPE_SEASON_OVERALL: "Saison Gesamt",
        SCOPE_SEASON_MODE: f"Saison Modus: {mode}",
        SCOPE_ALLTIME_OVERALL: "All-Time Gesamt",
        SCOPE_ALLTIME_MODE: f"All-Time Modus: {mode}",
    }

    title = scope_titles.get(scope, scope)

    lines = [
        f"**TFNL ELO-Tabelle — {title}**",
        f"Season: `{season}`" if scope.startswith("season_") else "Season: `ALL_TIME`",
        "",
    ]

    if not rows:
        lines.append("_Keine ELO-Daten gefunden._")
        return "\n".join(lines)

    def table_value(value, fallback: str = "0") -> str:
        if value is None:
            return fallback

        value_text = str(value).strip()

        if value_text == "":
            return fallback

        return value_text

    table_rows = []

    for index, row in enumerate(rows, start=1):
        table_rows.append(
            [
                index,
                table_value(row.get("Player Name"), ""),
                table_value(row.get("Elo"), "1000.0"),
                table_value(row.get("Wins"), "0"),
                table_value(row.get("Draws"), "0"),
                table_value(row.get("Lose"), "0"),
                f"{table_value(row.get('Winrate'), '0.0')}%",
            ]
        )

    lines.append(
        build_discord_table(
            ["#", "Name", "ELO", "W", "D", "L", "Win%"],
            table_rows,
            max_col_width=22,
        )
    )

    if limit is not None and len(rows) >= limit:
        lines.append("")
        lines.append(f"_Anzeige begrenzt auf Top {limit}._")

    return "\n".join(lines)


class LadderCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.last_schedule_message_id = None
        self.last_signup_message_id = None
        self.last_signup_status_message_id = None
        self.last_race_participants_message_id = None
        self.last_slot_id_check_at = None
        self.result_publish_lock = asyncio.Lock()
        self.slot_overview_publish_lock = asyncio.Lock()
        self.standings_publish_lock = asyncio.Lock()
        self.sheet_write_lock = asyncio.Lock()
        self.auto_evaluate_matches_lock = asyncio.Lock()
        self.pending_standings_publish_task = None
        self.race_control_dm_messages = {}

        try:
            self.elo_sheet_setup_status = ensure_ladder_elo_sheets()
            print(f"[TFNL ELO] Sheet-Setup OK: {self.elo_sheet_setup_status}")
        except Exception as e:
            self.elo_sheet_setup_status = None
            print(f"[TFNL ELO] Sheet-Setup fehlgeschlagen: {repr(e)}")

        if not self.update_schedule_channel.is_running():
            self.update_schedule_channel.start()

        if not self.update_signup_channel.is_running():
            self.update_signup_channel.start()

        if not self.process_ladder_slots.is_running():
            self.process_ladder_slots.start()

        if not self.auto_evaluate_finished_matches.is_running():
            self.auto_evaluate_finished_matches.start()

    def cog_unload(self):
        self.update_schedule_channel.cancel()
        self.update_signup_channel.cancel()
        self.process_ladder_slots.cancel()
        self.auto_evaluate_finished_matches.cancel()

        if self.pending_standings_publish_task and not self.pending_standings_publish_task.done():
            self.pending_standings_publish_task.cancel()

    # =====================================================
    # PERSISTENT COMPONENT ROUTING
    # =====================================================

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return

        data = interaction.data or {}
        custom_id = normalize_text(data.get("custom_id"))

        if not custom_id.startswith("tfnl_"):
            return

        parts = custom_id.split(":")
        action = parts[0]

        try:
            if action == "tfnl_signup" and len(parts) == 2:
                await self.handle_signup(interaction, parts[1])
                return

            if action == "tfnl_unsubscribe" and len(parts) == 2:
                await self.handle_unsubscribe(interaction, parts[1])
                return

            if action == "tfnl_finish" and len(parts) == 3:
                await self.handle_finish(interaction, parts[1], int(parts[2]))
                return

            if action == "tfnl_forfeit" and len(parts) == 3:
                view = ConfirmForfeitView(parts[1], int(parts[2]))
                await interaction.response.send_message(
                    "Forfeit wirklich eintragen?",
                    view=view,
                    ephemeral=True,
                )
                return

            if action == "tfnl_confirm_ff" and len(parts) == 3:
                await self.handle_forfeit(interaction, parts[1], int(parts[2]))
                return

            if action == "tfnl_undo_finish" and len(parts) == 3:
                await self.handle_undo_finish(interaction, parts[1], int(parts[2]))
                return

        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"Fehler bei Button-Aktion:\n```{repr(e)}```",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"Fehler bei Button-Aktion:\n```{repr(e)}```",
                    ephemeral=True,
                )

    # =====================================================
    # CHANNEL HELPERS
    # =====================================================

    async def get_text_channel(self, channel_id: int):
        channel = self.bot.get_channel(channel_id)

        if channel is None:
            channel = await self.bot.fetch_channel(channel_id)

        return channel

    async def log_tfnl(self, message: str):
        print(f"[TFNL] {message}")

        try:
            channel = await self.get_text_channel(TFNL_LOG_CHANNEL_ID)
            await channel.send(f"`TFNL` {message}")
        except Exception as e:
            print(f"[TFNL] Log konnte nicht gesendet werden: {repr(e)}")

    async def publish_schedule_to_channel(self):
        try:
            channel = await self.get_text_channel(TFNL_SCHEDULE_CHANNEL_ID)
        except Exception as e:
            print(f"[TFNL] Konnte Schedule-Channel nicht laden: {repr(e)}")
            return

        try:
            embed = build_schedule_embed(days=5)
        except Exception as e:
            print(f"[TFNL] Konnte Schedule-Embed nicht bauen: {repr(e)}")
            return

        if self.last_schedule_message_id:
            try:
                old_message = await channel.fetch_message(self.last_schedule_message_id)
                await old_message.edit(embed=embed)
                return
            except Exception:
                self.last_schedule_message_id = None

        try:
            async for message in channel.history(limit=25):
                if self.bot.user and message.author.id == self.bot.user.id:
                    try:
                        await message.delete()
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            new_message = await channel.send(embed=embed)
            self.last_schedule_message_id = new_message.id
            print("[TFNL] Spielplan im Channel aktualisiert.")
        except Exception as e:
            print(f"[TFNL] Konnte Schedule nicht senden: {repr(e)}")

    async def publish_signup_to_channel(self):
        try:
            channel = await self.get_text_channel(TFNL_SIGNUP_CHANNEL_ID)
        except Exception as e:
            print(f"[TFNL] Konnte Signup-Channel nicht laden: {repr(e)}")
            return

        try:
            open_slots = get_open_signup_slots()
            embed = build_signup_embed(open_slots)
            status_embed = build_public_race_participants_embed()
            view = SignupView(open_slots) if open_slots else None
        except Exception as e:
            print(f"[TFNL] Konnte Signup-Embeds nicht bauen: {repr(e)}")
            return

        await self.send_signup_announcements(open_slots, channel)

        if self.last_signup_message_id:
            try:
                old_message = await channel.fetch_message(self.last_signup_message_id)
                await old_message.edit(embed=embed, view=view)

                if self.last_signup_status_message_id:
                    try:
                        old_status_message = await channel.fetch_message(self.last_signup_status_message_id)
                        await old_status_message.edit(embed=status_embed, view=None)
                        return
                    except Exception:
                        self.last_signup_status_message_id = None

                status_message = await channel.send(embed=status_embed)
                self.last_signup_status_message_id = status_message.id
                return

            except Exception:
                self.last_signup_message_id = None
                self.last_signup_status_message_id = None

        try:
            async for message in channel.history(limit=25):
                if self.bot.user and message.author.id == self.bot.user.id:
                    try:
                        await message.delete()
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            new_message = await channel.send(embed=embed, view=view)
            self.last_signup_message_id = new_message.id

            status_message = await channel.send(embed=status_embed)
            self.last_signup_status_message_id = status_message.id

            print("[TFNL] Anmeldung im Channel aktualisiert.")
        except Exception as e:
            print(f"[TFNL] Konnte Signup nicht senden: {repr(e)}")

    async def delayed_publish_standings_to_channel(self, reason: str = ""):
        delay = max(0, TFNL_STANDINGS_PUBLISH_DELAY_SECONDS)

        if delay:
            await self.log_tfnl(
                f"Tabellenposting verzögert um `{delay}` Sekunden"
                + (f" ({reason})." if reason else ".")
            )
            await asyncio.sleep(delay)

        await self.publish_standings_to_channel()

    def schedule_standings_publish(self, reason: str = ""):
        if not TFNL_AUTO_PUBLISH_STANDINGS_AFTER_SLOT:
            return

        if self.pending_standings_publish_task and not self.pending_standings_publish_task.done():
            return

        self.pending_standings_publish_task = self.bot.loop.create_task(
            self.delayed_publish_standings_to_channel(reason=reason)
        )

    def preload_standings_source_cache(self, force_refresh: bool = False):
        """
        Lädt die teuren Tabellenquellen einmal vor.

        Wichtig für Quota:
        Tabellenposts bauen Gesamt- und mehrere Modus-Tabellen. Ohne Preload
        können Live/Archive-Reads an verschiedenen Stellen erneut ausgelöst werden.
        Durch den Preload plus Worksheet-/Spreadsheet-Cache werden Schedule, Matches
        und Archive-Daten in einem Lauf wiederverwendet.
        """
        load_schedule_rows_all_combined(force_refresh=force_refresh)
        load_matches_rows_all_combined(force_refresh=force_refresh)

    async def publish_standings_to_channel(self):
        async with self.standings_publish_lock:
            try:
                channel = await self.get_text_channel(TFNL_STANDINGS_CHANNEL_ID)
            except Exception as e:
                await self.log_tfnl(f"Konnte Standings-Channel nicht laden: {repr(e)}")
                return

            try:
                async for message in channel.history(limit=100):
                    if self.bot.user and message.author.id == self.bot.user.id:
                        try:
                            await message.delete()
                        except Exception:
                            pass
            except Exception:
                pass

            try:
                self.preload_standings_source_cache(force_refresh=False)

                messages = build_standings_messages()
                messages.extend(build_all_mode_standings_messages())

                for message in messages:
                    await send_discord_message_chunks(channel.send, message)

            except Exception as e:
                await self.log_tfnl(f"Gesamttabellen konnten nicht gepostet werden: {repr(e)}")

    async def publish_final_season_standings_to_channel(self, clear_existing: bool = False):
        try:
            channel = await self.get_text_channel(TFNL_STANDINGS_CHANNEL_ID)
        except Exception as e:
            await self.log_tfnl(f"Konnte Standings-Channel für Saison-Endwertung nicht laden: {repr(e)}")
            return

        if clear_existing:
            try:
                async for message in channel.history(limit=100):
                    if self.bot.user and message.author.id == self.bot.user.id:
                        try:
                            await message.delete()
                        except Exception:
                            pass
            except Exception:
                pass

        try:
            messages = build_final_season_standings_messages()

            for message in messages:
                await send_discord_message_chunks(channel.send, message)

        except Exception as e:
            await self.log_tfnl(
                f"Saison-Endwertung konnte nicht gepostet werden: {repr(e)}"
            )

    async def publish_mode_standings_to_channel(self, mode_name: str, clear_existing: bool = False):
        try:
            channel = await self.get_text_channel(TFNL_STANDINGS_CHANNEL_ID)
        except Exception as e:
            await self.log_tfnl(f"Konnte Standings-Channel für Modus-Tabelle nicht laden: {repr(e)}")
            return

        if clear_existing:
            try:
                async for message in channel.history(limit=50):
                    if self.bot.user and message.author.id == self.bot.user.id:
                        try:
                            await message.delete()
                        except Exception:
                            pass
            except Exception:
                pass

        try:
            messages = build_mode_standings_messages(mode_name)

            for message in messages:
                await send_discord_message_chunks(channel.send, message)

        except Exception as e:
            await self.log_tfnl(
                f"Modus-Tabelle `{mode_name}` konnte nicht gepostet werden: {repr(e)}"
            )

    async def send_signup_announcements(self, open_slots: list[dict], signup_channel: discord.TextChannel):
        for row in open_slots:
            slot_id = normalize_text(row.get("Slot ID"))

            if not slot_id:
                continue

            if signup_announcement_already_sent(row):
                continue

            datum = normalize_text(row.get("Datum"))
            slot = normalize_text(row.get("Slot"))
            startzeit = normalize_text(row.get("Startzeit"))
            anmeldeschluss = normalize_text(row.get("Anmeldeschluss"))
            modus = normalize_text(row.get("Modus"))

            role_mention = f"<@&{TFNL_LADDER_ROLE_ID}>"

            try:
                ping_message = await signup_channel.send(
                    f"{role_mention} **TFNL-Anmeldung geöffnet**\n"
                    f"**{datum} | {slot} | {startzeit} Uhr** — {modus}\n"
                    f"Anmeldeschluss: `{anmeldeschluss} Uhr`"
                )

                update_schedule_announcement_sent(slot_id)

                delete_at = build_datetime(row.get("Datum"), row.get("Anmeldeschluss"))

                async def delete_at_registration_close(message: discord.Message, target_time: datetime | None):
                    if target_time is None:
                        return

                    seconds_until_close = max(
                        0,
                        (target_time - datetime.now(BERLIN_TZ)).total_seconds(),
                    )

                    await asyncio.sleep(seconds_until_close)

                    try:
                        await message.delete()
                    except Exception as e:
                        print(f"[TFNL] Signup-Ping konnte nach Anmeldeschluss nicht gelöscht werden: {repr(e)}")

                self.bot.loop.create_task(
                    delete_at_registration_close(ping_message, delete_at)
                )

            except Exception as e:
                print(f"[TFNL] Signup-Announcement konnte nicht gesendet werden: {repr(e)}")

    # =====================================================
    # SIGNUP LOGIC
    # =====================================================

    async def handle_signup(self, interaction: discord.Interaction, slot_id: str):
        await interaction.response.defer(ephemeral=True)

        member = interaction.user

        if not isinstance(member, discord.Member):
            await interaction.followup.send(
                "Anmeldung fehlgeschlagen: Mitglied konnte nicht erkannt werden.",
                ephemeral=True,
            )
            return

        # v27:
        # Die Ladder-Rolle ist KEINE Voraussetzung mehr für die Raceanmeldung.
        # Entscheidend ist nur:
        # - User ist Servermitglied
        # - Anmeldung ist geöffnet
        # - Bot-DM funktioniert
        # - User ist noch nicht angemeldet
        _, schedule_row = find_schedule_row(slot_id)

        if not schedule_row:
            await interaction.followup.send(
                "Anmeldung fehlgeschlagen: Slot wurde im Schedule nicht gefunden.",
                ephemeral=True,
            )
            return

        if not is_registration_open(schedule_row):
            await interaction.followup.send(
                "Die Anmeldung für diesen Slot ist aktuell nicht geöffnet.",
                ephemeral=True,
            )
            return

        if user_already_signed_up(slot_id, member.id, force_refresh=True):
            await interaction.followup.send(
                "Du bist für diesen Slot bereits angemeldet.",
                ephemeral=True,
            )
            return

        try:
            await member.send(
                f"TFNL-DM-Test erfolgreich.\n"
                f"Du meldest dich für folgenden Slot an:\n"
                f"**{normalize_text(schedule_row.get('Datum'))} | "
                f"{normalize_text(schedule_row.get('Slot'))} | "
                f"{normalize_text(schedule_row.get('Startzeit'))} Uhr | "
                f"{normalize_text(schedule_row.get('Modus'))}**"
            )
        except Exception:
            await interaction.followup.send(
                "Anmeldung abgelehnt: Ich kann dir keine DM senden. "
                "Bitte öffne deine DMs für diesen Server und versuche es erneut.",
                ephemeral=True,
            )
            return

        try:
            async with self.sheet_write_lock:
                if user_already_signed_up(slot_id, member.id, force_refresh=True):
                    await interaction.followup.send(
                        "Du bist für diesen Slot bereits angemeldet.",
                        ephemeral=True,
                    )
                    return

                append_signup(slot_id, member.id, member.display_name)
        except Exception as e:
            await interaction.followup.send(
                f"Anmeldung fehlgeschlagen: Sheet konnte nicht beschrieben werden.\n```{repr(e)}```",
                ephemeral=True,
            )
            return

        try:
            slot_channel = await self.get_or_create_slot_channel(schedule_row)

            await slot_channel.set_permissions(
                member,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )

            await slot_channel.send(
                f"{member.mention} ist für diesen TFNL-Slot angemeldet."
            )
        except Exception as e:
            await interaction.followup.send(
                f"Anmeldung wurde gespeichert, aber der Slot-Channel konnte nicht aktualisiert werden.\n```{repr(e)}```",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "Anmeldung erfolgreich. Du wurdest dem privaten Slot-Channel hinzugefügt.",
            ephemeral=True,
        )

        await self.publish_signup_to_channel()

    async def handle_unsubscribe(self, interaction: discord.Interaction, slot_id: str):
        await interaction.response.defer(ephemeral=True)

        member = interaction.user

        if not isinstance(member, discord.Member):
            await interaction.followup.send(
                "Abmeldung fehlgeschlagen: Mitglied konnte nicht erkannt werden.",
                ephemeral=True,
            )
            return

        _, schedule_row = find_schedule_row(slot_id)

        if not schedule_row:
            await interaction.followup.send(
                "Abmeldung fehlgeschlagen: Slot wurde im Schedule nicht gefunden.",
                ephemeral=True,
            )
            return

        if not is_registration_open(schedule_row):
            await interaction.followup.send(
                "Abmeldung nicht möglich: Die Anmeldung für diesen Slot ist bereits geschlossen.",
                ephemeral=True,
            )
            return

        if not user_already_signed_up(slot_id, member.id):
            await interaction.followup.send(
                "Du bist für diesen Slot aktuell nicht angemeldet.",
                ephemeral=True,
            )
            return

        try:
            cancelled = cancel_signup(slot_id, member.id)
        except Exception as e:
            await interaction.followup.send(
                f"Abmeldung fehlgeschlagen: Sheet konnte nicht aktualisiert werden.\n```{repr(e)}```",
                ephemeral=True,
            )
            return

        if not cancelled:
            await interaction.followup.send(
                "Abmeldung fehlgeschlagen: Aktive Anmeldung wurde nicht gefunden.",
                ephemeral=True,
            )
            return

        channel_id = normalize_text(schedule_row.get("Slot Channel ID"))

        if channel_id:
            try:
                slot_channel = self.bot.get_channel(int(channel_id))

                if slot_channel is None:
                    slot_channel = await self.bot.fetch_channel(int(channel_id))

                await slot_channel.set_permissions(member, overwrite=None)
                await slot_channel.send(
                    f"{member.mention} hat sich von diesem TFNL-Slot abgemeldet."
                )
            except Exception as e:
                await self.log_tfnl(
                    f"Abmeldung gespeichert, aber Channel-Rechte konnten nicht entfernt werden: "
                    f"Slot `{slot_id}`, User `{member.id}` — {repr(e)}"
                )

        await interaction.followup.send(
            "Du wurdest von diesem Slot abgemeldet.",
            ephemeral=True,
        )

        await self.publish_signup_to_channel()

    async def get_or_create_slot_channel(self, schedule_row: dict):
        guild = self.bot.get_guild(GUILD_ID)

        if guild is None:
            guild = await self.bot.fetch_guild(GUILD_ID)

        existing_channel_id = normalize_text(schedule_row.get("Slot Channel ID"))

        if existing_channel_id:
            try:
                channel = self.bot.get_channel(int(existing_channel_id))

                if channel is None:
                    channel = await self.bot.fetch_channel(int(existing_channel_id))

                return channel
            except Exception:
                pass

        category = guild.get_channel(TFNL_CATEGORY_ID)

        if category is None:
            category = await self.bot.fetch_channel(TFNL_CATEGORY_ID)

        channel_name = build_slot_channel_name(schedule_row)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                manage_permissions=True,
            ),
        }

        channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            reason="TFNL Slot-Channel erstellt",
        )

        slot_id = normalize_text(schedule_row.get("Slot ID"))
        update_schedule_channel_id(slot_id, channel.id)

        await channel.send(
            "**TFNL Slot-Channel erstellt.**\n"
            "Die Paarungen bleiben geheim, bis Ergebnisse vorliegen."
        )

        return channel

    # =====================================================
    # SEED / RACE FLOW
    # =====================================================

    async def ensure_seed_url_for_slot(self, schedule_row: dict) -> str:
        slot_id = normalize_text(schedule_row.get("Slot ID"))
        current_seed_url = get_seed_url(schedule_row)

        if current_seed_url:
            return current_seed_url

        mode_name = normalize_text(schedule_row.get("Modus"))
        preset_key = get_preset_key_for_mode(mode_name)

        if not preset_key:
            await self.log_tfnl(
                f"Kein Seed-Mapping für Slot `{slot_id}` / Modus `{mode_name}` gefunden. "
                "Bitte gültigen Modus verwenden oder Seed URL manuell eintragen."
            )
            return ""

        try:
            await self.log_tfnl(
                f"Erzeuge ALTTPR-Seed für Slot `{slot_id}` / Modus `{mode_name}` / "
                f"Preset `{preset_key}` / YAML `{build_sahasrahbot_preset_url(preset_key)}` ..."
            )

            seed_url, diagnostics = await generate_alttpr_seed_for_mode(mode_name)

            await self.log_tfnl(
                f"Seed-Validierung OK für Slot `{slot_id}` / Modus `{mode_name}` / "
                f"Preset `{diagnostics['preset_key']}` / "
                f"Customizer `{diagnostics['customizer']}` / "
                f"PegasusBoots `{diagnostics['has_pegasus_boots']}`"
            )

        except Exception as e:
            await self.log_tfnl(
                f"Seed-Erzeugung abgebrochen für Slot `{slot_id}` / Modus `{mode_name}` / Preset `{preset_key}` — {repr(e)}"
            )
            return ""

        update_schedule_cell(slot_id, "Seed URL", seed_url)

        matches = get_matches_for_slot(slot_id)

        for match in matches:
            match_id = normalize_text(match.get("Match ID"))

            if match_id:
                update_match_cell(match_id, "Seed URL", seed_url)

        await self.log_tfnl(
            f"Seed erzeugt für Slot `{slot_id}`: {seed_url}"
        )

        return seed_url

    async def send_seed_dms(self, schedule_row: dict):
        slot_id = normalize_text(schedule_row.get("Slot ID"))

        seed_url = await self.ensure_seed_url_for_slot(schedule_row)

        if not seed_url:
            await self.log_tfnl(
                f"Seed URL fehlt weiterhin für Slot `{slot_id}`. Seed-DMs wurden nicht gesendet."
            )
            return False

        matches = get_matches_for_slot(slot_id)
        sent_to = set()

        if not matches:
            await self.log_tfnl(
                f"Keine Matches für Slot `{slot_id}` gefunden. Seed-DMs wurden nicht gesendet."
            )
            return False

        for match in matches:
            for player in get_match_players(match):
                if player["discord_id"] in sent_to:
                    continue

                sent_to.add(player["discord_id"])

                try:
                    user = await self.bot.fetch_user(int(player["discord_id"]))
                    await user.send(
                        "**TFNL Seed für deinen Slot**\n\n"
                        f"Datum: `{normalize_text(schedule_row.get('Datum'))}`\n"
                        f"Slot: `{normalize_text(schedule_row.get('Slot'))}`\n"
                        f"Modus: `{normalize_text(schedule_row.get('Modus'))}`\n"
                        f"Startzeit: `{normalize_text(schedule_row.get('Startzeit'))} Uhr`\n"
                        f"Seed-Link: {seed_url}\n\n"
                        "Die Paarungen bleiben geheim bis zum Ergebnis.\n"
                        "Kurz vor Start kommt zuerst der Countdown.\n"
                        "Nach Countdown-Ende folgt die Race-Control-DM mit Finish-/Forfeit-Buttons und Runnercounter."
                    )
                except Exception as e:
                    await self.log_tfnl(
                        f"Seed-DM konnte nicht gesendet werden: Slot `{slot_id}`, Spieler `{player['discord_id']}` — {repr(e)}"
                    )

        update_schedule_status(slot_id, "seed_sent")
        await self.publish_schedule_to_channel()

        return True

    async def send_prestart_dms(self, schedule_row: dict):
        """
        v20:
        Diese separate 1-Minuten-DM wird bewusst nicht mehr gesendet.
        Grund: Der Countdown muss in der letzten Bot-DM laufen.
        Die Race-Control-DM aus send_countdown_dms übernimmt Hinweis, Countdown und Buttons.
        """
        slot_id = normalize_text(schedule_row.get("Slot ID"))

        if slot_id:
            update_schedule_cell(slot_id, SCHEDULE_PRESTART_DM_COL, "Ja")

        return True

    async def send_countdown_dms(self, schedule_row: dict):
        slot_id = normalize_text(schedule_row.get("Slot ID"))
        start_dt = get_slot_start_dt(schedule_row)

        if not start_dt:
            await self.log_tfnl(f"Countdown nicht möglich: Startzeit fehlt für Slot `{slot_id}`.")
            return False

        matches = get_matches_for_slot(slot_id)
        sent_to = set()

        if not matches:
            await self.log_tfnl(f"Countdown nicht möglich: Keine Matches für Slot `{slot_id}` gefunden.")
            return False

        countdown_start_dt = start_dt - timedelta(seconds=10)
        start_unix = int(start_dt.timestamp())

        def build_monotonic_deadlines():
            now_wall = datetime.now(BERLIN_TZ)
            now_mono = time.monotonic()
            start_delay = max(0.0, (start_dt - now_wall).total_seconds())
            countdown_delay = max(0.0, (countdown_start_dt - now_wall).total_seconds())
            return now_mono + countdown_delay, now_mono + start_delay

        async def sleep_until_monotonic(target_mono: float):
            while True:
                remaining = target_mono - time.monotonic()

                if remaining <= 0:
                    return

                await asyncio.sleep(min(remaining, 0.25))

        async def send_or_edit_countdown(
            user: discord.User,
            message,
            content: str,
        ):
            if message is None:
                return await user.send(content)

            try:
                await message.edit(content=content)
                return message
            except Exception:
                return await user.send(content)

        async def countdown(user: discord.User, player_id: str, match_id: str, player_no: int):
            try:
                countdown_deadline, start_deadline = build_monotonic_deadlines()

                # Reihenfolge v21:
                # Seed-DM -> Countdown-DM -> Race gestartet -> danach Race-Control-DM.
                message = await send_or_edit_countdown(
                    user,
                    None,
                    build_countdown_dm_content(start_unix),
                )

                await sleep_until_monotonic(countdown_deadline)

                for value in range(10, 0, -1):
                    target = start_deadline - value
                    await sleep_until_monotonic(target)

                    # Countdown-Mechanik bleibt stabil: monotonic + absolute Zielzeit.
                    if time.monotonic() >= start_deadline - 0.10:
                        break

                    message = await send_or_edit_countdown(
                        user,
                        message,
                        build_countdown_dm_content(start_unix, value=value),
                    )

                await sleep_until_monotonic(start_deadline)

                await send_or_edit_countdown(
                    user,
                    message,
                    build_countdown_dm_content(start_unix, started=True),
                )

            except Exception as e:
                await self.log_tfnl(
                    f"Countdown-DM fehlgeschlagen: Slot `{slot_id}`, Spieler `{player_id}` — {repr(e)}"
                )

        for match in matches:
            for player in get_match_players(match):
                player_id = player["discord_id"]

                if player_id in sent_to:
                    continue

                sent_to.add(player_id)

                try:
                    user = await self.bot.fetch_user(int(player_id))
                    self.bot.loop.create_task(
                        countdown(
                            user,
                            player_id,
                            normalize_text(match.get("Match ID")),
                            int(player["no"]),
                        )
                    )
                except Exception as e:
                    await self.log_tfnl(
                        f"Countdown-DM konnte nicht vorbereitet werden: Spieler `{player_id}` — {repr(e)}"
                    )

        update_schedule_status(slot_id, "countdown_sent")
        await self.publish_schedule_to_channel()
        return True

    async def send_start_dms(self, schedule_row: dict):
        slot_id = normalize_text(schedule_row.get("Slot ID"))
        matches = get_matches_for_slot(slot_id)

        for match in matches:
            match_id = normalize_text(match.get("Match ID"))

            update_match_cell(match_id, "Status", "running")

            for player in get_match_players(match):
                try:
                    user = await self.bot.fetch_user(int(player["discord_id"]))
                    player_no = int(player["no"])
                    message = await user.send(
                        build_race_control_dm_content(schedule_row),
                        view=RaceControlView(match_id, player_no),
                    )
                    self.race_control_dm_messages[(slot_id, normalize_text(player["discord_id"]))] = {
                        "message": message,
                        "match_id": match_id,
                        "player_no": player_no,
                    }
                except Exception as e:
                    await self.log_tfnl(
                        f"Race-Control-DM konnte nicht gesendet werden: Match `{match_id}`, Spieler `{player['discord_id']}` — {repr(e)}"
                    )

        update_schedule_status(slot_id, "running")

        try:
            await self.post_slot_runners_to_channel(schedule_row)
        except Exception:
            pass

        await self.publish_schedule_to_channel()

    async def handle_finish(self, interaction: discord.Interaction, match_id: str, player_no: int):
        await interaction.response.defer(ephemeral=True)

        try:
            _, match_row = find_match_row(match_id)

            if not match_row:
                await interaction.followup.send("Match wurde nicht gefunden.", ephemeral=True)
                return

            if normalize_text(match_row.get("Veröffentlicht")).lower() == "ja":
                await interaction.followup.send(
                    "Das Ergebnis wurde bereits veröffentlicht. Undo ist nicht mehr möglich.",
                    ephemeral=True,
                )
                return

            current_time = normalize_text(match_row.get(f"Zeit Spieler {player_no}"))

            if current_time.upper() == "FF":
                await interaction.followup.send(
                    "Für dich wurde bereits ein Forfeit eingetragen. Das kann nicht per Finish überschrieben werden.",
                    ephemeral=True,
                )
                return

            if current_time:
                await interaction.followup.send(
                    f"Für dich ist bereits `{current_time}` eingetragen. Nutze zuerst `Undo Finish`, falls das ein Fehlklick war.",
                    ephemeral=True,
                )
                return

            slot_id = normalize_text(match_row.get("Slot ID"))
            _, schedule_row = find_schedule_row(slot_id)

            if not schedule_row:
                await interaction.followup.send("Slot wurde nicht gefunden.", ephemeral=True)
                return

            start_dt = get_slot_start_dt(schedule_row)

            if not start_dt:
                await interaction.followup.send("Startzeit konnte nicht gelesen werden.", ephemeral=True)
                return

            now = datetime.now(BERLIN_TZ)

            if now < start_dt:
                await interaction.followup.send(
                    "Das Race ist offiziell noch nicht gestartet. Finish ist erst ab der offiziellen Startzeit möglich.",
                    ephemeral=True,
                )
                return

            elapsed = int((now - start_dt).total_seconds())

            if elapsed < 0:
                elapsed = 0

            time_value = seconds_to_timecode(elapsed)

            update_match_cells(
                match_id,
                {
                    f"Zeit Spieler {player_no}": time_value,
                    "Status": "partial_result",
                },
            )

            await interaction.followup.send(
                f"Finish eingetragen: `{time_value}`\n"
                "Falls das ein Fehlklick war, kannst du den Finish zurücknehmen.",
                view=UndoFinishView(match_id, player_no),
                ephemeral=True,
            )

            await self.refresh_slot_active_outputs(schedule_row)

            await self.evaluate_match_if_complete(match_id)

        except Exception as e:
            await interaction.followup.send(
                f"Fehler beim Finish:\n```{repr(e)}```",
                ephemeral=True,
            )

    async def handle_undo_finish(self, interaction: discord.Interaction, match_id: str, player_no: int):
        await interaction.response.defer(ephemeral=True)

        try:
            _, match_row = find_match_row(match_id)

            if not match_row:
                await interaction.followup.send("Match wurde nicht gefunden.", ephemeral=True)
                return

            if normalize_text(match_row.get("Veröffentlicht")).lower() == "ja":
                await interaction.followup.send(
                    "Das Ergebnis wurde bereits veröffentlicht. Undo ist nicht mehr möglich.",
                    ephemeral=True,
                )
                return

            current_time = normalize_text(match_row.get(f"Zeit Spieler {player_no}"))

            if current_time.upper() == "FF":
                await interaction.followup.send(
                    "Ein Forfeit kann nicht per Undo zurückgenommen werden.",
                    ephemeral=True,
                )
                return

            if not current_time:
                await interaction.followup.send(
                    "Es ist keine Finish-Zeit eingetragen, die zurückgenommen werden kann.",
                    ephemeral=True,
                )
                return

            update_match_cells(
                match_id,
                {
                    f"Zeit Spieler {player_no}": "",
                    "Status": "running",
                },
            )

            slot_id = normalize_text(match_row.get("Slot ID"))
            _, schedule_row = find_schedule_row(slot_id)

            await interaction.followup.send(
                "Finish wurde zurückgenommen. Die Zeitmessung läuft weiter.\n"
                "Du kannst erneut finishen oder forfeiten.",
                view=RaceControlView(match_id, player_no),
                ephemeral=True,
            )

            if schedule_row:
                await self.refresh_slot_active_outputs(schedule_row)

        except Exception as e:
            await interaction.followup.send(
                f"Fehler beim Undo Finish:\n```{repr(e)}```",
                ephemeral=True,
            )

    async def handle_forfeit(self, interaction: discord.Interaction, match_id: str, player_no: int):
        await interaction.response.defer(ephemeral=True)

        try:
            _, match_row = find_match_row(match_id)

            if not match_row:
                await interaction.followup.send("Match wurde nicht gefunden.", ephemeral=True)
                return

            if normalize_text(match_row.get("Veröffentlicht")).lower() == "ja":
                await interaction.followup.send("Das Ergebnis wurde bereits veröffentlicht.", ephemeral=True)
                return

            current_time = normalize_text(match_row.get(f"Zeit Spieler {player_no}"))

            if current_time.upper() == "FF":
                await interaction.followup.send(
                    "Für dich wurde bereits ein Forfeit eingetragen.",
                    ephemeral=True,
                )
                return

            if current_time:
                await interaction.followup.send(
                    f"Für dich ist bereits `{current_time}` eingetragen. Ein nachträglicher Forfeit ist nicht möglich.",
                    ephemeral=True,
                )
                return

            slot_id = normalize_text(match_row.get("Slot ID"))
            _, schedule_row = find_schedule_row(slot_id)

            if schedule_row:
                start_dt = get_slot_start_dt(schedule_row)
                if start_dt and datetime.now(BERLIN_TZ) < start_dt:
                    await interaction.followup.send(
                        "Das Race ist offiziell noch nicht gestartet. Forfeit ist erst ab der offiziellen Startzeit möglich.",
                        ephemeral=True,
                    )
                    return

            update_match_cells(
                match_id,
                {
                    f"Zeit Spieler {player_no}": "FF",
                    "Status": "partial_result",
                },
            )

            await interaction.followup.send("Forfeit wurde eingetragen: `FF`.", ephemeral=True)

            if schedule_row:
                await self.refresh_slot_active_outputs(schedule_row)

            await self.evaluate_match_if_complete(match_id)

        except Exception as e:
            await interaction.followup.send(
                f"Fehler beim Forfeit:\n```{repr(e)}```",
                ephemeral=True,
            )

    async def find_public_slot_results_message(self, channel, slot_id: str):
        if not slot_id:
            return None

        try:
            async for message in channel.history(limit=100):
                content = message.content or ""
                if (
                    self.bot.user
                    and message.author.id == self.bot.user.id
                    and "TFNL-Slot" in content
                    and slot_id in content
                ):
                    return message
        except Exception:
            return None

        return None

    async def upsert_public_slot_results_message(self, schedule_row: dict, completed: bool = False):
        slot_id = normalize_text(schedule_row.get("Slot ID"))

        async with self.result_publish_lock:
            try:
                channel = await self.get_text_channel(TFNL_RESULTS_CHANNEL_ID)
            except Exception as e:
                await self.log_tfnl(f"Ergebnis-Channel konnte nicht geladen werden: {repr(e)}")
                return

            content = build_public_slot_results_message(schedule_row, completed=completed)
            existing_message = await self.find_public_slot_results_message(channel, slot_id)

            try:
                if existing_message is not None:
                    await existing_message.edit(content=content)
                else:
                    await channel.send(content)
            except Exception as e:
                await self.log_tfnl(
                    f"Öffentliche Slot-Ergebnisnachricht konnte nicht aktualisiert werden: `{slot_id}` — {repr(e)}"
                )

    async def publish_result_to_results_channel(
        self,
        match_row: dict,
        schedule_row: dict | None = None,
        elo_changes: dict[str, str] | None = None,
    ):
        if not schedule_row:
            return

        await self.upsert_public_slot_results_message(schedule_row, completed=False)

    async def publish_slot_overview_to_results_channel(self, schedule_row: dict):
        await self.upsert_public_slot_results_message(schedule_row, completed=True)

    async def post_slot_runners_to_channel(self, schedule_row: dict):
        try:
            slot_channel = await self.get_or_create_slot_channel(schedule_row)
            await slot_channel.send(build_slot_runner_message(schedule_row))
            await self.upsert_slot_active_status_message(schedule_row)
        except Exception as e:
            slot_id = normalize_text(schedule_row.get("Slot ID"))
            await self.log_tfnl(f"Teilnehmerliste konnte nicht gepostet werden: `{slot_id}` — {repr(e)}")

    async def find_slot_active_status_message(self, channel, slot_id: str):
        if not slot_id:
            return None

        try:
            async for message in channel.history(limit=75):
                content = message.content or ""
                if (
                    self.bot.user
                    and message.author.id == self.bot.user.id
                    and "TFNL-Aktivitätsstatus" in content
                    and slot_id in content
                ):
                    return message
        except Exception:
            return None

        return None

    async def upsert_slot_active_status_message(self, schedule_row: dict):
        slot_id = normalize_text(schedule_row.get("Slot ID"))

        if not slot_id:
            return

        try:
            slot_channel = await self.get_or_create_slot_channel(schedule_row)
        except Exception as e:
            await self.log_tfnl(
                f"Aktivitätsstatus konnte nicht geladen werden: `{slot_id}` — {repr(e)}"
            )
            return

        content = build_slot_active_status_message(schedule_row)
        existing_message = await self.find_slot_active_status_message(slot_channel, slot_id)

        try:
            if existing_message is not None:
                await existing_message.edit(content=content)
            else:
                await slot_channel.send(content)
        except Exception as e:
            await self.log_tfnl(
                f"Aktivitätsstatus konnte nicht aktualisiert werden: `{slot_id}` — {repr(e)}"
            )

    async def refresh_race_control_dm_messages(self, schedule_row: dict):
        slot_id = normalize_text(schedule_row.get("Slot ID"))

        if not slot_id:
            return

        cached_items = [
            (key, value) for key, value in self.race_control_dm_messages.items()
            if key[0] == slot_id
        ]

        if not cached_items:
            return

        content = build_race_control_dm_content(schedule_row)

        for key, data in cached_items:
            try:
                message = data.get("message")
                match_id = normalize_text(data.get("match_id"))
                player_no = int(data.get("player_no"))

                if message is None or not match_id:
                    continue

                await message.edit(
                    content=content,
                    view=RaceControlView(match_id, player_no),
                )
            except Exception as e:
                await self.log_tfnl(
                    f"Race-Control-DM konnte nicht aktualisiert werden: `{slot_id}` — {repr(e)}"
                )

    async def refresh_slot_active_outputs(self, schedule_row: dict):
        if not schedule_row:
            return

        try:
            await self.upsert_slot_active_status_message(schedule_row)
        except Exception as e:
            slot_id = normalize_text(schedule_row.get("Slot ID"))
            await self.log_tfnl(
                f"Aktivitätsstatus im Racechannel konnte nicht aktualisiert werden: `{slot_id}` — {repr(e)}"
            )

        try:
            await self.upsert_public_slot_results_message(schedule_row, completed=False)
        except Exception as e:
            slot_id = normalize_text(schedule_row.get("Slot ID"))
            await self.log_tfnl(
                f"Aktivitätsstatus im Ergebnis-Channel konnte nicht aktualisiert werden: `{slot_id}` — {repr(e)}"
            )

        try:
            await self.refresh_race_control_dm_messages(schedule_row)
        except Exception as e:
            slot_id = normalize_text(schedule_row.get("Slot ID"))
            await self.log_tfnl(
                f"Runnercounter in Race-Control-DMs konnte nicht aktualisiert werden: `{slot_id}` — {repr(e)}"
            )

    async def evaluate_match_if_complete(self, match_id: str):
        async with self.sheet_write_lock:
            _, match_row = find_match_row(match_id)

            if not match_row:
                return

            if normalize_text(match_row.get("Veröffentlicht")).lower() == "ja":
                return

            result = calculate_match_result(match_row)

            if result is None:
                return

            apply_result_to_match(match_id, result)

            _, updated_match = find_match_row(match_id)

            if not updated_match:
                return

            slot_id = normalize_text(updated_match.get("Slot ID"))
            _, schedule_row = find_schedule_row(slot_id)

            elo_changes = {}

            try:
                elo_result = process_match_elo(updated_match, schedule_row=schedule_row)
                elo_changes = elo_result.get("elo_changes", {}) if isinstance(elo_result, dict) else {}
            except Exception as e:
                await self.log_tfnl(f"ELO-Verarbeitung fehlgeschlagen für `{match_id}` — {repr(e)}")

            update_players_from_match(updated_match)

        if schedule_row:
            try:
                await self.refresh_slot_active_outputs(schedule_row)
            except Exception as e:
                await self.log_tfnl(
                    f"Aktivitätsstatus nach Auto-Wertung konnte nicht aktualisiert werden: `{slot_id}` — {repr(e)}"
                )

            try:
                slot_channel = await self.get_or_create_slot_channel(schedule_row)
                await slot_channel.send(build_result_message(updated_match, elo_changes=elo_changes))
            except Exception as e:
                await self.log_tfnl(f"Ergebnispost fehlgeschlagen für `{match_id}` — {repr(e)}")

            await self.publish_result_to_results_channel(updated_match, schedule_row, elo_changes=elo_changes)

            await self.complete_slot_if_ready(slot_id)

    async def complete_slot_if_ready(self, slot_id: str, force: bool = False, debug: bool = False) -> bool:
        _, schedule_row = find_schedule_row(slot_id)

        if not schedule_row:
            if debug:
                await self.log_tfnl(f"Slotabschluss übersprungen: Slot `{slot_id}` nicht im Schedule gefunden.")
            return False

        status = normalize_text(schedule_row.get("Status")).lower()

        if status in ("archived", "cancelled"):
            if debug:
                await self.log_tfnl(
                    f"Slotabschluss übersprungen: Slot `{slot_id}` hat Status `{status}`."
                )
            return False

        if status == "completed" and not force:
            if debug:
                await self.log_tfnl(
                    f"Slotabschluss übersprungen: Slot `{slot_id}` ist bereits completed."
                )
            return False

        completed_at_existing = normalize_text(schedule_row.get(SCHEDULE_COMPLETED_AT_COL))

        if completed_at_existing and not force:
            if debug:
                await self.log_tfnl(
                    f"Slotabschluss übersprungen: Slot `{slot_id}` hat bereits Completed At `{completed_at_existing}`."
                )
            return False

        blockers = get_slot_completion_blockers(slot_id)

        if blockers:
            if debug:
                preview = "\n".join(f"- {blocker}" for blocker in blockers[:10])

                if len(blockers) > 10:
                    preview += f"\n- ... plus {len(blockers) - 10} weitere Blocker"

                await self.log_tfnl(
                    f"Slot `{slot_id}` noch nicht complete:\n{preview}"
                )
            return False

        _, updated_schedule_row = find_schedule_row(slot_id)

        if not updated_schedule_row:
            updated_schedule_row = schedule_row

        # Private Racechannel:
        # Match-Ergebnisse werden bereits in evaluate_match_if_complete() gepostet.
        # Deshalb hier KEINE zusätzliche Slot-Gesamtübersicht mehr in denselben
        # privaten Channel senden. Bei 1-Match-Slots wirkte das wie ein doppelter
        # Ergebnispost.
        #
        # Öffentlich im Ergebnis-Channel wird weiterhin per Upsert editiert,
        # also eine Slot-Nachricht statt Dopplung.

        try:
            await self.publish_slot_overview_to_results_channel(updated_schedule_row)
        except Exception as e:
            await self.log_tfnl(
                f"Öffentliche Slot-Gesamtübersicht konnte nicht gepostet werden: `{slot_id}` — {repr(e)}"
            )

        # Tabellenposting nicht in dieselbe Google-Sheets-Spitze wie Matchwertung,
        # ELO/History/Players/Slotabschluss drücken. Stattdessen verzögert und
        # zusammengefasst posten.
        self.schedule_standings_publish(reason=f"Slotabschluss `{slot_id}`")

        # Keine zusätzliche Modus-Tabelle automatisch in den Tabellenkanal posten.
        # Der Tabellenkanal wird dadurch nur einmal aktualisiert und nicht doppelt befüllt.
        completed_at = set_schedule_completed(slot_id)

        await self.publish_schedule_to_channel()
        await self.publish_signup_to_channel()

        await self.log_tfnl(
            f"Slot `{slot_id}` completed um `{completed_at}`. Channel-Löschung in 60 Minuten."
        )

        return True

    async def finalize_slot(self, schedule_row: dict):
        slot_id = normalize_text(schedule_row.get("Slot ID"))
        matches = get_matches_for_slot(slot_id)

        for match in matches:
            match_id = normalize_text(match.get("Match ID"))

            if normalize_text(match.get("Veröffentlicht")).lower() == "ja":
                continue

            players = get_match_players(match)
            values = {}

            for player in players:
                current_time = normalize_text(match.get(player["time_col"]))

                if not current_time:
                    values[player["time_col"]] = "FF"

            if values:
                update_match_cells(match_id, values)

            await self.evaluate_match_if_complete(match_id)

        await self.complete_slot_if_ready(slot_id)

    async def delete_slot_channel_if_due(self, schedule_row: dict):
        slot_id = normalize_text(schedule_row.get("Slot ID"))
        status = normalize_text(schedule_row.get("Status")).lower()
        channel_id = normalize_text(schedule_row.get("Slot Channel ID"))

        if status == "cancelled":
            if not is_cancelled_channel_delete_due(schedule_row):
                return
            reason = "TFNL Slot 15 Minuten nach Absage gelöscht"
        else:
            if not is_completed_channel_delete_due(schedule_row):
                return
            reason = "TFNL Slot 60 Minuten nach Abschluss gelöscht"

        if not channel_id:
            update_schedule_status(slot_id, "archived")
            return

        try:
            channel = self.bot.get_channel(int(channel_id))

            if channel is None:
                channel = await self.bot.fetch_channel(int(channel_id))

            await channel.delete(reason=reason)
        except Exception as e:
            await self.log_tfnl(f"Slot-Channel konnte nicht gelöscht werden: `{slot_id}` — {repr(e)}")

        update_schedule_status(slot_id, "archived")
        await self.publish_schedule_to_channel()

    # =====================================================
    # PAIRING LOGIC
    # =====================================================

    async def process_schedule_states(self):
        now_ts = datetime.now(BERLIN_TZ).timestamp()

        if self.last_slot_id_check_at is None or now_ts - self.last_slot_id_check_at >= 300:
            self.last_slot_id_check_at = now_ts
            unique_changes = ensure_unique_schedule_slot_ids()

            if unique_changes:
                change_lines = []

                for change in unique_changes:
                    change_lines.append(
                        f"Zeile {change['row_index']}: `{change['old_slot_id'] or '-'} ` → `{change['new_slot_id']}` "
                        f"({change['datum']} {change['slot']} {change['startzeit']})"
                    )

                await self.log_tfnl(
                    "Doppelte/leere Slot IDs automatisch korrigiert:\n" + "\n".join(change_lines[:15])
                )

        rows_with_index = load_schedule_rows_with_index()

        for _, row in rows_with_index:
            slot_id = normalize_text(row.get("Slot ID"))
            status = normalize_text(row.get("Status")).lower()

            if not slot_id:
                continue

            if status == "archived":
                continue

            if status in ("completed", "cancelled"):
                await self.delete_slot_channel_if_due(row)
                continue

            if is_registration_open(row) and status not in (
                "registration_open",
                "paired",
                "seed_sent",
                "countdown_sent",
                "running",
                "completed",
            ):
                update_schedule_status(slot_id, "registration_open")
                continue

            if is_registration_due_for_pairing(row) and status in ("planned", "registration_open", ""):
                await self.close_registration_and_pair(row)
                continue

            if status == "paired" and is_seed_due(row):
                await self.send_seed_dms(row)
                await self.publish_signup_to_channel()
                continue

            # v20:
            # Keine separate 1-Minuten-DM mehr senden.
            # Der Countdown muss die letzte Bot-DM sein und läuft in der Race-Control-DM.
            # Eine nachträgliche Prestart-DM würde den Countdown wieder nach oben schieben.
            if status == "seed_sent" and is_countdown_due(row):
                await self.send_countdown_dms(row)
                await self.publish_signup_to_channel()
                continue

            if status == "countdown_sent" and is_start_due(row):
                await self.send_start_dms(row)
                await self.publish_signup_to_channel()
                continue

            if status == "running":
                if is_slot_complete(slot_id):
                    await self.complete_slot_if_ready(slot_id, debug=True)
                    continue

                if is_slot_end_due(row):
                    await self.finalize_slot(row)
                    continue

    async def close_registration_and_pair(self, schedule_row: dict):
        slot_id = normalize_text(schedule_row.get("Slot ID"))

        if not slot_id:
            return

        if matches_already_created(slot_id):
            update_schedule_status(slot_id, "paired")
            return

        participants = get_signup_participants_for_slot(slot_id)

        try:
            slot_channel = await self.get_or_create_slot_channel(schedule_row)
        except Exception as e:
            slot_channel = None
            await self.log_tfnl(f"Slot-Channel konnte beim Pairing nicht geladen/erstellt werden: {repr(e)}")

        if len(participants) < 2:
            cancelled_at = set_schedule_cancelled(slot_id)

            if slot_channel:
                await slot_channel.send(
                    "**Anmeldung geschlossen.**\n"
                    "Der Slot wurde abgesagt, da weniger als 2 Spieler angemeldet sind.\n"
                    "Dieser Raceroom wird in 15 Minuten geschlossen."
                )

            await self.log_tfnl(
                f"Slot `{slot_id}` cancelled um `{cancelled_at}`: weniger als 2 Teilnehmer. Channel-Löschung in 15 Minuten."
            )
            await self.publish_schedule_to_channel()
            await self.publish_signup_to_channel()
            return

        pairings = create_pairings(participants, schedule_row)
        match_rows = build_match_rows(slot_id, schedule_row, pairings)

        append_matches(match_rows)
        update_schedule_status(slot_id, "paired")

        if slot_channel:
            await slot_channel.send(
                "**Anmeldung geschlossen.**\n"
                "Die Paarungen wurden geheim ausgelost.\n"
                "Ihr erhaltet die weiteren Informationen später per DM."
            )
            await slot_channel.send(build_slot_runner_message(schedule_row))

        await self.log_tfnl(f"Slot `{slot_id}` paired: {len(match_rows)} Match(es) erstellt.")

        await self.publish_schedule_to_channel()
        await self.publish_signup_to_channel()

    async def archive_slot_channel_now(self, schedule_row: dict) -> bool:
        slot_id = normalize_text(schedule_row.get("Slot ID"))
        channel_id = normalize_text(schedule_row.get("Slot Channel ID"))

        if not channel_id:
            update_schedule_status(slot_id, "archived")
            await self.publish_schedule_to_channel()
            await self.log_tfnl(f"Slot `{slot_id}` manuell archiviert. Kein Slot Channel ID vorhanden.")
            return True

        try:
            channel = self.bot.get_channel(int(channel_id))

            if channel is None:
                channel = await self.bot.fetch_channel(int(channel_id))

            await channel.delete(reason="TFNL Slot manuell archiviert")
        except Exception as e:
            await self.log_tfnl(f"Slot-Channel konnte manuell nicht gelöscht werden: `{slot_id}` — {repr(e)}")
            return False

        update_schedule_status(slot_id, "archived")
        await self.publish_schedule_to_channel()
        await self.log_tfnl(f"Slot `{slot_id}` manuell archiviert und Channel gelöscht.")
        return True

    async def check_finished_matches_from_sheet(self) -> int:
        """
        Prüft regelmäßig die Matches-Tabelle:
        Wenn alle Zeitspalten eines Matches gefüllt sind, wird das Match
        automatisch mit derselben Logik gewertet wie bei Finish/Forfeit-Buttons.
        """
        evaluated = 0

        async with self.auto_evaluate_matches_lock:
            # Die Routine läuft nur alle 3 Minuten.
            # Hier bewusst force_refresh=True, damit manuell im Sheet eingetragene
            # Zeiten/FFs zuverlässig erkannt werden und nicht im Cache hängen bleiben.
            rows = load_matches_rows(force_refresh=True)

            for match_row in rows:
                if not match_needs_auto_evaluation(match_row):
                    continue

                match_id = normalize_text(match_row.get("Match ID"))

                if not match_id:
                    continue

                await self.evaluate_match_if_complete(match_id)
                evaluated += 1

        if evaluated:
            await self.log_tfnl(
                f"Auto-Wertung: `{evaluated}` Match(es) mit vollständig gefüllten Zeitspalten gewertet."
            )

        return evaluated

    async def run_manual_process_step(self, step: str, slot_id: str) -> tuple[bool, str]:
        step = normalize_text(step).lower()
        slot_id = normalize_text(slot_id)

        _, schedule_row = find_schedule_row(slot_id)

        if not schedule_row:
            return False, f"Slot `{slot_id}` wurde im Schedule nicht gefunden."

        if step in ("open", "open_signup", "registration_open", "anmeldung"):
            update_schedule_status(slot_id, "registration_open")
            await self.publish_schedule_to_channel()
            await self.publish_signup_to_channel()
            return True, f"Anmeldung für Slot `{slot_id}` wurde manuell geöffnet."

        if step in ("pair", "pairing", "close_registration", "paaren"):
            await self.close_registration_and_pair(schedule_row)
            return True, f"Pairing/Anmeldeschluss für Slot `{slot_id}` wurde manuell angestoßen."

        if step in ("seed", "seed_dm", "seed_dms"):
            ok = await self.send_seed_dms(schedule_row)
            return ok, f"Seed-DMs für Slot `{slot_id}` wurden {'gesendet' if ok else 'nicht gesendet'}."

        if step in ("prestart", "prestart_dm", "one_minute_dm", "minute_dm"):
            ok = await self.send_prestart_dms(schedule_row)
            return ok, f"1-Minuten-DMs für Slot `{slot_id}` wurden {'gesendet' if ok else 'nicht gesendet'}."

        if step in ("countdown", "countdown_dm", "countdown_dms"):
            await self.send_countdown_dms(schedule_row)
            return True, f"Countdown-DMs für Slot `{slot_id}` wurden manuell vorbereitet."

        if step in ("start", "start_dm", "start_dms"):
            await self.send_start_dms(schedule_row)
            await self.publish_schedule_to_channel()
            return True, f"Start-DMs für Slot `{slot_id}` wurden manuell gesendet."

        if step in ("finalize", "ff", "slot_end", "ende"):
            await self.finalize_slot(schedule_row)
            return True, f"Slot-Ende/FF-Finalisierung für Slot `{slot_id}` wurde manuell angestoßen."

        if step in ("complete", "abschluss", "overview", "gesamt"):
            ok = await self.complete_slot_if_ready(slot_id, force=True, debug=True)
            return ok, f"Slotabschluss für Slot `{slot_id}` wurde {'durchgeführt' if ok else 'nicht durchgeführt'}."

        if step in ("archive", "archivieren", "delete_channel", "channel_delete"):
            ok = await self.archive_slot_channel_now(schedule_row)
            return ok, f"Archivierung für Slot `{slot_id}` wurde {'durchgeführt' if ok else 'nicht durchgeführt'}."

        if step in ("schedule", "publish_schedule"):
            await self.publish_schedule_to_channel()
            return True, "Spielplan wurde neu gepostet/aktualisiert."

        if step in ("signup", "publish_signup"):
            await self.publish_signup_to_channel()
            return True, "Anmeldung wurde neu gepostet/aktualisiert."

        if step in ("standings", "ranking", "rankings"):
            await self.publish_standings_to_channel()
            return True, "Gesamtranking wurde neu gepostet/aktualisiert."

        if step in ("final_standings", "season_final", "endwertung", "finalranking"):
            await self.publish_final_season_standings_to_channel(clear_existing=False)
            return True, "Saison-Endwertung mit FF-Abzug wurde gepostet."

        return False, (
            "Unbekannter Schritt. Erlaubt: `open_signup`, `pair`, `seed`, `countdown`, "
            "`start`, `finalize`, `complete`, `archive`, `schedule`, `signup`, `standings`, `final_standings`."
        )

    # =====================================================
    # TASKS
    # =====================================================

    @tasks.loop(minutes=5)
    async def update_schedule_channel(self):
        await self.publish_schedule_to_channel()

    @update_schedule_channel.before_loop
    async def before_update_schedule_channel(self):
        await self.bot.wait_until_ready()
        # Nach Deploy sind alle Sheet-Caches leer. Deshalb nicht gleichzeitig
        # mit Signup-Update und Slot-Prozess echte Reads feuern.
        await asyncio.sleep(TFNL_STARTUP_STAGGER_SECONDS)

    @tasks.loop(minutes=2)
    async def update_signup_channel(self):
        await self.publish_signup_to_channel()

    @update_signup_channel.before_loop
    async def before_update_signup_channel(self):
        await self.bot.wait_until_ready()
        # Signup-Ansicht startet bewusst versetzt nach Schedule.
        await asyncio.sleep(TFNL_STARTUP_STAGGER_SECONDS + 15)

    @tasks.loop(seconds=TFNL_LOOP_INTERVAL_SECONDS)
    async def process_ladder_slots(self):
        try:
            await self.process_schedule_states()
        except Exception as e:
            error_text = repr(e)

            if "Quota exceeded" in error_text or "[429]" in error_text:
                if should_log_quota_warning(60):
                    retry_seconds = seconds_until_quota_retry() or 60
                    await self.log_tfnl(
                        f"Google-Sheets-Quota erreicht. Nutze Cache und pausiert echte Sheet-Reads kurz. Neuer Versuch in ca. {retry_seconds} Sekunden."
                    )

                await asyncio.sleep(max(60, retry_seconds))
                return

            if is_transient_google_api_error(error_text):
                if should_log_transient_google_error("process_ladder_slots"):
                    await self.log_tfnl(
                        "Temporärer Google-Sheets/API-Fehler in `process_ladder_slots`. "
                        f"Wird automatisch erneut versucht. Details: {error_text}"
                    )

                await asyncio.sleep(max(5, TFNL_TRANSIENT_ERROR_BACKOFF_SECONDS))
                return

            await self.log_tfnl(f"Fehler in process_ladder_slots: {error_text}")

    @process_ladder_slots.before_loop
    async def before_process_ladder_slots(self):
        await self.bot.wait_until_ready()
        # Der Slot-Prozess ist der read-lastigste Task. Nach Deploy daher
        # erst starten, wenn Schedule-/Signup-Tasks zeitlich entzerrt wurden.
        await asyncio.sleep(TFNL_STARTUP_STAGGER_SECONDS + 30)

    @tasks.loop(minutes=TFNL_AUTO_EVALUATE_INTERVAL_MINUTES)
    async def auto_evaluate_finished_matches(self):
        try:
            await self.check_finished_matches_from_sheet()
        except Exception as e:
            error_text = repr(e)

            if "Quota exceeded" in error_text or "[429]" in error_text:
                if should_log_quota_warning(60):
                    retry_seconds = seconds_until_quota_retry() or 60
                    await self.log_tfnl(
                        f"Google-Sheets-Quota erreicht bei Auto-Wertung. Nutze Cache und pausiert echte Sheet-Reads kurz. Neuer Versuch in ca. {retry_seconds} Sekunden."
                    )

                await asyncio.sleep(max(60, retry_seconds))
                return

            if is_transient_google_api_error(error_text):
                if should_log_transient_google_error("auto_evaluate_finished_matches"):
                    await self.log_tfnl(
                        "Temporärer Google-Sheets/API-Fehler in `auto_evaluate_finished_matches`. "
                        f"Wird automatisch erneut versucht. Details: {error_text}"
                    )

                await asyncio.sleep(max(5, TFNL_TRANSIENT_ERROR_BACKOFF_SECONDS))
                return

            await self.log_tfnl(f"Fehler in auto_evaluate_finished_matches: {error_text}")

    @auto_evaluate_finished_matches.before_loop
    async def before_auto_evaluate_finished_matches(self):
        await self.bot.wait_until_ready()
        # Nach Deploy später starten als der normale Slot-Prozess.
        await asyncio.sleep(TFNL_STARTUP_STAGGER_SECONDS + 45)

    # =====================================================
    # COMMANDS
    # =====================================================

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def run_dm_flow_test(
        self,
        user: discord.User,
        countdown_seconds: int = 10,
        active: int = 10,
        total: int = 10,
        seedpause_seconds: int = 20,
        preppause_seconds: int = 20,
    ):
        """
        Persönlicher DM-Ablauftest ohne Sheet-Wertung:
        Seed-DM -> Countdown-DM -> Race gestartet -> Race-Control-DM.
        """
        countdown_seconds = max(3, min(int(countdown_seconds), 30))
        seedpause_seconds = max(0, min(int(seedpause_seconds), 300))
        preppause_seconds = max(0, min(int(preppause_seconds), 300))
        active = max(0, int(active))
        total = max(1, int(total))

        if active > total:
            active = total

        now = datetime.now(BERLIN_TZ)
        start_dt = now + timedelta(
            seconds=seedpause_seconds + preppause_seconds + countdown_seconds
        )
        start_unix = int(start_dt.timestamp())

        seed_url = "https://alttpr.com/h/TEST-DM-FLOW"

        await user.send(
            "**TFNL Seed für deinen Slot**\n\n"
            f"Datum: `{start_dt.strftime('%d.%m.%Y')}`\n"
            "Slot: `DM-Test`\n"
            "Modus: `Ambrosia`\n"
            f"Startzeit: `{start_dt.strftime('%H:%M')} Uhr`\n"
            f"Seed-Link: {seed_url}\n\n"
            "Die Paarungen bleiben geheim bis zum Ergebnis.\n"
            "Dies ist ein persönlicher Testlauf ohne Sheet-Wertung."
        )

        if seedpause_seconds > 0:
            await asyncio.sleep(seedpause_seconds)

        countdown_message = await user.send(
            build_countdown_dm_content(start_unix)
        )

        if preppause_seconds > 0:
            await asyncio.sleep(preppause_seconds)

        async def sleep_until_monotonic(target_mono: float):
            while True:
                remaining = target_mono - time.monotonic()

                if remaining <= 0:
                    return

                await asyncio.sleep(min(remaining, 0.25))

        start_deadline = time.monotonic() + countdown_seconds

        for value in range(countdown_seconds, 0, -1):
            target = start_deadline - value
            await sleep_until_monotonic(target)

            if time.monotonic() >= start_deadline - 0.10:
                break

            try:
                await countdown_message.edit(
                    content=build_countdown_dm_content(start_unix, value=value)
                )
            except Exception:
                countdown_message = await user.send(
                    build_countdown_dm_content(start_unix, value=value)
                )

        await sleep_until_monotonic(start_deadline)

        try:
            await countdown_message.edit(
                content=build_countdown_dm_content(start_unix, started=True)
            )
        except Exception:
            await user.send(
                build_countdown_dm_content(start_unix, started=True)
            )

        await user.send(
            "🔴 **TFNL RACE-CONTROL** 🔴\n\n"
            "Das Race ist gestartet.\n"
            f"Offizieller Start: <t:{start_unix}:T>\n"
            "Zeitmessung läuft exakt ab der geplanten Startzeit.\n\n"
            f"🔴 **AKTIVE RUNNER: `{active}/{total}`**\n\n"
            "Klicke `Finish`, sobald du fertig bist.\n"
            "Klicke `Forfeit`, wenn du aufgibst.\n\n"
            "_DM-Test: Die Buttons sind deaktiviert und schreiben nichts ins Sheet._",
            view=TfnlDmTestView(),
        )

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(
        name="tfnl_dmtest",
        description="Testet nur für dich den TFNL-DM-Ablauf Seed -> Countdown -> Race-Control.",
    )
    @app_commands.describe(
        user="Optional: User, der die Test-DM erhalten soll. Leer = du selbst.",
        seedpause="Pause zwischen Seed-DM und Countdown-Vorbereitung in Sekunden, Standard 20.",
        preppause="Pause zwischen Countdown-Vorbereitung und echtem Countdown in Sekunden, Standard 20.",
        countdown="Countdown-Länge in Sekunden, Standard 10.",
        active="Aktive Runner im Testcounter, Standard 10.",
        total="Gesamtzahl Runner im Testcounter, Standard 10.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def tfnl_dmtest(
        self,
        interaction: discord.Interaction,
        user: discord.Member = None,
        seedpause: int = 20,
        preppause: int = 20,
        countdown: int = 10,
        active: int = 10,
        total: int = 10,
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)

        target_user = user or interaction.user

        seedpause = max(0, min(int(seedpause), 300))
        preppause = max(0, min(int(preppause), 300))
        countdown = max(3, min(int(countdown), 30))

        async def run_background_dmtest():
            try:
                await self.run_dm_flow_test(
                    user=target_user,
                    countdown_seconds=countdown,
                    active=active,
                    total=total,
                    seedpause_seconds=seedpause,
                    preppause_seconds=preppause,
                )
            except Exception as e:
                try:
                    await self.log_tfnl(
                        f"DM-Test fehlgeschlagen für `{target_user.id}` — gestartet von `{interaction.user.id}` — {repr(e)}"
                    )
                except Exception:
                    pass

        self.bot.loop.create_task(run_background_dmtest())

        await interaction.followup.send(
            "DM-Test gestartet.\n"
            f"Empfänger: {target_user.mention}\n"
            f"Seed-DM kommt sofort.\n"
            f"Countdown-Vorbereitung kommt nach `{seedpause}` Sekunden.\n"
            f"Echter Countdown startet `{preppause}` Sekunden danach und läuft `{countdown}` Sekunden.\n"
            "Der Test verändert keine Sheets und keine Wertung.",
            ephemeral=True,
        )

    @app_commands.command(
        name="laddertable",
        description="Zeigt die neue TFNL-ELO-Tabelle.",
    )
    @app_commands.describe(
        wertung="Welche ELO-Wertung angezeigt werden soll.",
        modus="Nur bei Modus-Wertungen nötig, z. B. Open oder Casual Boots.",
    )
    @app_commands.choices(
        wertung=[
            app_commands.Choice(name="Saison Gesamt", value=SCOPE_SEASON_OVERALL),
            app_commands.Choice(name="Saison Modus", value=SCOPE_SEASON_MODE),
            app_commands.Choice(name="All-Time Gesamt", value=SCOPE_ALLTIME_OVERALL),
            app_commands.Choice(name="All-Time Modus", value=SCOPE_ALLTIME_MODE),
        ]
    )
    async def laddertable(
        self,
        interaction: discord.Interaction,
        wertung: app_commands.Choice[str],
        modus: str = "",
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)

        scope = wertung.value

        if scope in (SCOPE_SEASON_MODE, SCOPE_ALLTIME_MODE) and not normalize_text(modus):
            await interaction.followup.send(
                "Für Modus-Tabellen muss `modus` angegeben werden, z. B. `Open`.",
                ephemeral=True,
            )
            return

        try:
            season = get_active_season()
            message = build_elo_table_message(
                scope=scope,
                season=season,
                mode=modus,
                limit=None,
            )
        except Exception as e:
            await interaction.followup.send(
                f"ELO-Tabelle konnte nicht geladen werden:\n```{repr(e)}```",
                ephemeral=True,
            )
            return

        for chunk in split_discord_message(message):
            await interaction.followup.send(chunk, ephemeral=True)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(
        name="tfnl_elo_rebuild",
        description="Admin: Baut alle TFNL-ELO-Tabellen aus veröffentlichten Matches neu auf.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def tfnl_elo_rebuild(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            # Quellen genau einmal frisch laden und danach für Folgeausgaben im Cache halten.
            matches_rows = load_matches_rows_all_combined(force_refresh=True)
            schedule_rows = load_schedule_rows_all_combined(force_refresh=True)

            stats = rebuild_elo_from_matches(
                matches_rows=matches_rows,
                schedule_rows=schedule_rows,
            )
        except Exception as e:
            await interaction.followup.send(
                f"ELO-Rebuild fehlgeschlagen:\n```{repr(e)}```",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "TFNL-ELO-Rebuild abgeschlossen.\n"
            f"Verarbeitete Matches: `{stats.get('processed_matches', 0)}`\n"
            f"Rating-Events: `{stats.get('processed_events', 0)}`\n"
            f"Übersprungene Matches: `{stats.get('skipped_matches', 0)}`",
            ephemeral=True,
        )

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(
        name="tfnl_elo_rebuild_publish",
        description="Admin: Baut TFNL-ELO neu auf und postet danach die Tabellen quota-schonend.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def tfnl_elo_rebuild_publish(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            matches_rows = load_matches_rows_all_combined(force_refresh=True)
            schedule_rows = load_schedule_rows_all_combined(force_refresh=True)

            stats = rebuild_elo_from_matches(
                matches_rows=matches_rows,
                schedule_rows=schedule_rows,
            )

            # Direkt danach posten, ohne die Quellen erneut frisch aus Google zu ziehen.
            await self.publish_standings_to_channel()
        except Exception as e:
            await interaction.followup.send(
                f"ELO-Rebuild + Tabellenposting fehlgeschlagen:\n```{repr(e)}```",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "TFNL-ELO-Rebuild abgeschlossen und Tabellen neu gepostet.\n"
            f"Verarbeitete Matches: `{stats.get('processed_matches', 0)}`\n"
            f"Rating-Events: `{stats.get('processed_events', 0)}`\n"
            f"Übersprungene Matches: `{stats.get('skipped_matches', 0)}`",
            ephemeral=True,
        )

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(
        name="tfnl_elo_setup",
        description="Prüft und erstellt die benötigten TFNL-ELO-Sheets und Header.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def tfnl_elo_setup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            status = ensure_ladder_elo_sheets()
            self.elo_sheet_setup_status = status
        except Exception as e:
            await interaction.followup.send(
                f"TFNL-ELO-Sheet-Setup fehlgeschlagen:\n```{repr(e)}```",
                ephemeral=True,
            )
            return

        added = status.get("season_columns_added") or []
        added_text = ", ".join(added) if added else "keine"
        sheet_text = ", ".join(status.get("sheets") or [])

        await interaction.followup.send(
            "TFNL-ELO-Sheet-Setup erfolgreich.\n"
            f"Aktive Saison: `{status.get('active_season')}`\n"
            f"Geprüfte/angelegte Sheets: `{sheet_text}`\n"
            f"Neu ergänzte Season-Spalten: `{added_text}`\n"
            f"Zeitpunkt: `{status.get('checked_at')}`",
            ephemeral=True,
        )

    @tfnl_elo_setup.error
    async def tfnl_elo_setup_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        if isinstance(error, app_commands.MissingPermissions):
            if interaction.response.is_done():
                await interaction.followup.send(
                    "Dieser Command ist nur für Administratoren verfügbar.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "Dieser Command ist nur für Administratoren verfügbar.",
                    ephemeral=True,
                )
            return

        raise error


    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(
        name="ladder_plan",
        description="Zeigt den TFNL-Spielplan der nächsten 5 Tage.",
    )
    async def ladder_plan(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            embed = build_schedule_embed(days=5)
        except Exception as e:
            await interaction.followup.send(
                f"Fehler beim Lesen des TFNL-Sheets:\n```{repr(e)}```",
                ephemeral=True,
            )
            return

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(
        name="ladder_plan_update",
        description="Aktualisiert den TFNL-Spielplan im Plan-Channel manuell.",
    )
    async def ladder_plan_update(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            await self.publish_schedule_to_channel()
        except Exception as e:
            await interaction.followup.send(
                f"Fehler beim Aktualisieren des Plan-Channels:\n```{repr(e)}```",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "TFNL-Spielplan wurde aktualisiert.",
            ephemeral=True,
        )

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(
        name="ladder_signup_update",
        description="Aktualisiert die TFNL-Anmeldung im Signup-Channel manuell.",
    )
    async def ladder_signup_update(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            await self.publish_signup_to_channel()
        except Exception as e:
            await interaction.followup.send(
                f"Fehler beim Aktualisieren der Anmeldung:\n```{repr(e)}```",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "TFNL-Anmeldung wurde aktualisiert.",
            ephemeral=True,
        )

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(
        name="tfnl_archive_season",
        description="Archiviert eine TFNL-Season in Archive-Sheets.",
    )
    @app_commands.describe(
        season="Season-Wert, z. B. Test-01",
        sheet="Welche Tabelle archiviert werden soll: alle, schedule, signup, matches, players.",
        delete_from_live="Wenn True: Zeilen nach dem Kopieren aus Live-Sheets löschen. Standard: False.",
    )
    @app_commands.choices(
        sheet=[
            app_commands.Choice(name="alle", value="alle"),
            app_commands.Choice(name="schedule", value="schedule"),
            app_commands.Choice(name="signup", value="signup"),
            app_commands.Choice(name="matches", value="matches"),
            app_commands.Choice(name="players", value="players"),
        ]
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def tfnl_archive_season(
        self,
        interaction: discord.Interaction,
        season: str,
        sheet: app_commands.Choice[str],
        delete_from_live: bool = False,
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)

        selected_season = normalize_text(season)

        if not selected_season:
            await interaction.followup.send("Season fehlt.", ephemeral=True)
            return

        try:
            async with self.sheet_write_lock:
                stats = archive_season(
                    selected_season,
                    delete_from_live=delete_from_live,
                    sheet_name=sheet.value,
                )

        except Exception as e:
            await interaction.followup.send(
                f"Fehler beim Archivieren der Season `{selected_season}`:\n```{repr(e)}```",
                ephemeral=True,
            )
            return

        lines = [
            f"Season `{selected_season}` wurde archiviert.",
            f"Archiv-Auswahl: `{sheet.value}`",
            f"Aus Live-Sheets gelöscht: `{'Ja' if delete_from_live else 'Nein'}`",
            "",
        ]

        for sheet_name, sheet_stats in stats.items():
            lines.append(
                f"{sheet_name}: gefunden `{sheet_stats.get('matched', 0)}`, kopiert `{sheet_stats['copied']}`, übersprungen `{sheet_stats['skipped']}`, gelöscht `{sheet_stats['deleted']}`"
            )

        await interaction.followup.send("\n".join(lines), ephemeral=True)

    @tfnl_archive_season.error
    async def tfnl_archive_season_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        if isinstance(error, app_commands.MissingPermissions):
            if interaction.response.is_done():
                await interaction.followup.send(
                    "Dieser Command ist nur für Administratoren verfügbar.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "Dieser Command ist nur für Administratoren verfügbar.",
                    ephemeral=True,
                )
            return

        raise error


    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(
        name="tfnlrebuild",
        description="Baut die TFNL-Players-Tabelle vollständig aus veröffentlichten Matches neu auf.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def tfnlrebuild(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            async with self.sheet_write_lock:
                stats = rebuild_players_from_published_matches()

            await self.publish_standings_to_channel()

        except Exception as e:
            await interaction.followup.send(
                f"Fehler beim Rebuild der TFNL-Gesamttabelle:\n```{repr(e)}```",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"TFNL-Gesamttabelle wurde aus veröffentlichten Matches neu aufgebaut. Season: `{stats['season']}`\n"
            f"Matches verarbeitet: `{stats['matches']}`\n"
            f"Spieler-Ergebnisse verarbeitet: `{stats['player_results']}`\n"
            f"Spieler in Tabelle: `{stats['players']}`",
            ephemeral=True,
        )

    @tfnlrebuild.error
    async def tfnlrebuild_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        if isinstance(error, app_commands.MissingPermissions):
            if interaction.response.is_done():
                await interaction.followup.send(
                    "Dieser Command ist nur für Administratoren verfügbar.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "Dieser Command ist nur für Administratoren verfügbar.",
                    ephemeral=True,
                )
            return

        raise error


    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(
        name="ladder_standings_update",
        description="Postet die aktuelle TFNL-Gesamttabelle neu.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def ladder_standings_update(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            await self.publish_standings_to_channel()
        except Exception as e:
            await interaction.followup.send(
                f"Fehler beim Aktualisieren der Gesamttabelle:\n```{repr(e)}```",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "TFNL-Gesamttabelle wurde aktualisiert.",
            ephemeral=True,
        )

    @ladder_standings_update.error
    async def ladder_standings_update_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        if isinstance(error, app_commands.MissingPermissions):
            if interaction.response.is_done():
                await interaction.followup.send(
                    "Dieser Command ist nur für Administratoren verfügbar.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "Dieser Command ist nur für Administratoren verfügbar.",
                    ephemeral=True,
                )
            return

        raise error

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(
        name="tfnl_final_standings",
        description="Postet die TFNL-Saison-Endwertung mit FF-Abzug.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def tfnl_final_standings(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            await self.publish_final_season_standings_to_channel(clear_existing=False)
        except Exception as e:
            await interaction.followup.send(
                f"Fehler beim Posten der Saison-Endwertung:\n```{repr(e)}```",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "TFNL-Saison-Endwertung wurde gepostet. Live-ELO und Pairing bleiben unverändert.",
            ephemeral=True,
        )

    @tfnl_final_standings.error
    async def tfnl_final_standings_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        if isinstance(error, app_commands.MissingPermissions):
            if interaction.response.is_done():
                await interaction.followup.send(
                    "Dieser Command ist nur für Administratoren verfügbar.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "Dieser Command ist nur für Administratoren verfügbar.",
                    ephemeral=True,
                )

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(
        name="ladder_mode_standings",
        description="Postet die TFNL-Tabelle für einen bestimmten Modus.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(
        modus=[
            app_commands.Choice(name="Casual Boots", value="Casual Boots"),
            app_commands.Choice(name="Open", value="Open"),
            app_commands.Choice(name="Inverted", value="Inverted"),
            app_commands.Choice(name="Open AD Boots", value="Open AD Boots"),
            app_commands.Choice(name="Invrosia", value="Invrosia"),
            app_commands.Choice(name="Ambrosia", value="Ambrosia"),
            app_commands.Choice(name="Ludicrous Speed", value="Ludicrous Speed"),
            app_commands.Choice(name="Hard Standard", value="Hard Standard"),
            app_commands.Choice(name="Standard", value="Standard"),
            app_commands.Choice(name="TFL Hard Standard", value="TFL Hard Standard"),
            app_commands.Choice(name="Keysanity", value="Keysanity"),
            app_commands.Choice(name="AD Keysanity Mit Boots", value="AD Keysanity Mit Boots"),
            app_commands.Choice(name="AD Keys", value="AD Keys"),
            app_commands.Choice(name="MC Boss", value="MC Boss"),
            app_commands.Choice(name="Influkeys", value="Influkeys"),
            app_commands.Choice(name="Crosskeys", value="Crosskeys"),
        ]
    )
    async def ladder_mode_standings(
        self,
        interaction: discord.Interaction,
        modus: app_commands.Choice[str],
    ):
        await interaction.response.defer(ephemeral=False)

        try:
            messages = build_mode_standings_messages(modus.value)
        except Exception as e:
            await interaction.followup.send(
                f"Fehler beim Erstellen der Modus-Tabelle:\n```{repr(e)}```",
                ephemeral=False,
            )
            return

        for message in messages:
            for chunk in split_discord_message(message):
                await interaction.followup.send(chunk, ephemeral=False)

    @ladder_mode_standings.error
    async def ladder_mode_standings_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        if isinstance(error, app_commands.MissingPermissions):
            if interaction.response.is_done():
                await interaction.followup.send(
                    "Dieser Command ist nur für Administratoren verfügbar.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "Dieser Command ist nur für Administratoren verfügbar.",
                    ephemeral=True,
                )
            return

        raise error

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(
        name="ladder_seed_test",
        description="Testet die Seed-Erzeugung für einen bestimmten TFNL-Modus.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.choices(
        modus=[
            app_commands.Choice(name="Casual Boots", value="Casual Boots"),
            app_commands.Choice(name="Open", value="Open"),
            app_commands.Choice(name="Inverted", value="Inverted"),
            app_commands.Choice(name="Open AD Boots", value="Open AD Boots"),
            app_commands.Choice(name="Invrosia", value="Invrosia"),
            app_commands.Choice(name="Ambrosia", value="Ambrosia"),
            app_commands.Choice(name="Ludicrous Speed", value="Ludicrous Speed"),
            app_commands.Choice(name="Hard Standard", value="Hard Standard"),
            app_commands.Choice(name="Standard", value="Standard"),
            app_commands.Choice(name="TFL Hard Standard", value="TFL Hard Standard"),
            app_commands.Choice(name="Keysanity", value="Keysanity"),
            app_commands.Choice(name="AD Keysanity Mit Boots", value="AD Keysanity Mit Boots"),
            app_commands.Choice(name="AD Keys", value="AD Keys"),
            app_commands.Choice(name="MC Boss", value="MC Boss"),
            app_commands.Choice(name="Influkeys", value="Influkeys"),
            app_commands.Choice(name="Crosskeys", value="Crosskeys"),
        ]
    )
    async def ladder_seed_test(
        self,
        interaction: discord.Interaction,
        modus: app_commands.Choice[str],
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)

        mode_name = normalize_text(modus.value)
        preset_key = get_preset_key_for_mode(mode_name)

        if not preset_key:
            await interaction.followup.send(
                f"Kein Seed-Mapping für Modus `{mode_name}` gefunden.",
                ephemeral=True,
            )
            return

        try:
            seed_url, diagnostics = await generate_alttpr_seed_for_mode(mode_name)
        except Exception as e:
            await interaction.followup.send(
                "**Seed-Test fehlgeschlagen.**\n\n"
                f"Modus: `{mode_name}`\n"
                f"Preset: `{preset_key}`\n"
                f"YAML: `{build_sahasrahbot_preset_url(preset_key)}`\n\n"
                f"Fehler:\n```{repr(e)}```",
                ephemeral=True,
            )
            return

        eq_preview = diagnostics.get("eq") or []
        eq_text = ", ".join(eq_preview[:8]) if eq_preview else "-"

        await interaction.followup.send(
            "**Seed-Test erfolgreich.**\n\n"
            f"Modus: `{mode_name}`\n"
            f"Canonical: `{diagnostics['canonical_mode']}`\n"
            f"Preset: `{diagnostics['preset_key']}`\n"
            f"YAML: `{diagnostics['preset_url']}`\n"
            f"Customizer: `{diagnostics['customizer']}`\n"
            f"Mode-Setting: `{diagnostics['mode_setting']}`\n"
            f"Entrances: `{diagnostics['entrances']}`\n"
            f"Dungeon Items: `{diagnostics['dungeon_items']}`\n"
            f"PegasusBoots im Preset: `{diagnostics['has_pegasus_boots']}`\n"
            f"Start-Equipment: `{eq_text}`\n"
            f"Allow Quick Swap: `{diagnostics.get('allow_quickswap')}`\n"
            f"Quick-Swap-Flags: `gesetzt`\n"
            f"API: `{diagnostics.get('pyz3r_api')}`\n"
            f"Endpoint: `{diagnostics.get('endpoint')}`\n"
            f"Seed: {seed_url}\n\n"
            "Es wurde nichts ins Sheet geschrieben und keine DM verschickt.",
            ephemeral=True,
        )

    @ladder_seed_test.error
    async def ladder_seed_test_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        if isinstance(error, app_commands.MissingPermissions):
            if interaction.response.is_done():
                await interaction.followup.send(
                    "Dieser Command ist nur für Administratoren verfügbar.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "Dieser Command ist nur für Administratoren verfügbar.",
                    ephemeral=True,
                )
            return

        raise error


    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(
        name="ladder_force_complete",
        description="Erzwingt den Abschluss eines vollständigen TFNL-Slots.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def ladder_force_complete(
        self,
        interaction: discord.Interaction,
        slot_id: str,
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)

        normalized_slot_id = normalize_text(slot_id)

        if not normalized_slot_id:
            await interaction.followup.send(
                "Slot ID fehlt.",
                ephemeral=True,
            )
            return

        _, schedule_row = find_schedule_row(normalized_slot_id)

        if not schedule_row:
            await interaction.followup.send(
                f"Slot `{normalized_slot_id}` wurde im Schedule nicht gefunden.",
                ephemeral=True,
            )
            return

        blockers = get_slot_completion_blockers(normalized_slot_id)

        if blockers:
            preview = "\n".join(f"- {blocker}" for blocker in blockers[:15])

            if len(blockers) > 15:
                preview += f"\n- ... plus {len(blockers) - 15} weitere Blocker"

            await interaction.followup.send(
                f"Slot `{normalized_slot_id}` ist noch nicht vollständig:\n```{preview}```",
                ephemeral=True,
            )
            return

        completed = await self.complete_slot_if_ready(
            normalized_slot_id,
            force=True,
            debug=True,
        )

        if completed:
            await interaction.followup.send(
                f"Slot `{normalized_slot_id}` wurde abgeschlossen und die Gesamtübersicht wurde gepostet.",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"Slot `{normalized_slot_id}` konnte nicht abgeschlossen werden. Details stehen im TFNL-Log.",
                ephemeral=True,
            )

    @ladder_force_complete.error
    async def ladder_force_complete_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        if isinstance(error, app_commands.MissingPermissions):
            if interaction.response.is_done():
                await interaction.followup.send(
                    "Dieser Command ist nur für Administratoren verfügbar.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "Dieser Command ist nur für Administratoren verfügbar.",
                    ephemeral=True,
                )
            return

        raise error


    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(
        name="ladder_slotids_fix",
        description="Prüft und korrigiert doppelte/leere TFNL-Slot-IDs im Schedule.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def ladder_slotids_fix(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        changes = ensure_unique_schedule_slot_ids()

        if not changes:
            await interaction.followup.send(
                "Alle Slot IDs im Schedule sind eindeutig.",
                ephemeral=True,
            )
            return

        lines = []

        for change in changes:
            lines.append(
                f"Zeile {change['row_index']}: `{change['old_slot_id'] or '-'} ` → `{change['new_slot_id']}` "
                f"({change['datum']} {change['slot']} {change['startzeit']})"
            )

        await self.publish_schedule_to_channel()
        await self.publish_signup_to_channel()

        await interaction.followup.send(
            "Folgende Slot IDs wurden korrigiert:\n" + "\n".join(lines[:20]),
            ephemeral=True,
        )

    @ladder_slotids_fix.error
    async def ladder_slotids_fix_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        if isinstance(error, app_commands.MissingPermissions):
            if interaction.response.is_done():
                await interaction.followup.send(
                    "Dieser Command ist nur für Administratoren verfügbar.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "Dieser Command ist nur für Administratoren verfügbar.",
                    ephemeral=True,
                )
            return

        raise error

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(
        name="ladder_step",
        description="Stößt einen einzelnen TFNL-Prozessschritt für einen Slot manuell an.",
    )
    @app_commands.describe(
        slot_id="Exakte Slot ID aus dem Schedule",
        step="open_signup, pair, seed, prestart, countdown, start, finalize, complete, archive, schedule, signup, standings, final_standings",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def ladder_step(
        self,
        interaction: discord.Interaction,
        slot_id: str,
        step: str,
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)

        ok, message = await self.run_manual_process_step(step, slot_id)

        await interaction.followup.send(
            f"{'OK' if ok else 'NICHT OK'}: {message}",
            ephemeral=True,
        )

    @ladder_step.error
    async def ladder_step_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        if isinstance(error, app_commands.MissingPermissions):
            if interaction.response.is_done():
                await interaction.followup.send(
                    "Dieser Command ist nur für Administratoren verfügbar.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "Dieser Command ist nur für Administratoren verfügbar.",
                    ephemeral=True,
                )
            return

        raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(LadderCog(bot))
