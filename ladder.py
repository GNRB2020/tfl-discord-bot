import os
import re
import random
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import aiohttp
import discord
import gspread
import pyz3r
try:
    from pyz3r.customizer import customizer as pyz3r_customizer
except Exception:
    pyz3r_customizer = None
import yaml
from discord import app_commands
from discord.ext import commands, tasks
from oauth2client.service_account import ServiceAccountCredentials


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

BERLIN_TZ = ZoneInfo("Europe/Berlin")

SCHEDULE_SHEET_NAME = "Schedule"
SIGNUP_SHEET_NAME = "Signup"
MATCHES_SHEET_NAME = "Matches"
PLAYERS_SHEET_NAME = "Players"

SCHEDULE_ANNOUNCEMENT_COL = "Signup Announcement Sent"
SCHEDULE_COMPLETED_AT_COL = "Completed At"

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
]

SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

HEADER_CACHE = {}


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
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    client = gspread.authorize(creds)
    return client.open_by_key(TFNL_SPREADSHEET_ID)


def ensure_header_column(sheet, sheet_name: str, column_name: str):
    headers = HEADER_CACHE.get(sheet_name)

    if headers is None:
        headers = sheet.row_values(1)
        HEADER_CACHE[sheet_name] = headers

    if column_name not in headers:
        next_col = len(headers) + 1
        sheet.update_cell(1, next_col, column_name)
        headers.append(column_name)
        HEADER_CACHE[sheet_name] = headers


def get_or_create_worksheet(
    spreadsheet,
    title: str,
    headers: list[str],
    rows: int = 1000,
    cols: int = 30,
):
    try:
        sheet = spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)

    existing_headers = sheet.row_values(1)

    if existing_headers != headers:
        sheet.update("A1", [headers])
        HEADER_CACHE[title] = headers
    else:
        HEADER_CACHE[title] = existing_headers

    return sheet


def get_header_index(sheet, sheet_name: str, column_name: str):
    if sheet_name not in HEADER_CACHE:
        HEADER_CACHE[sheet_name] = sheet.row_values(1)

    headers = HEADER_CACHE[sheet_name]

    try:
        return headers.index(column_name) + 1
    except ValueError:
        return None


def get_schedule_sheet():
    spreadsheet = get_tfnl_spreadsheet()
    sheet = spreadsheet.worksheet(SCHEDULE_SHEET_NAME)

    ensure_header_column(sheet, SCHEDULE_SHEET_NAME, SCHEDULE_ANNOUNCEMENT_COL)
    ensure_header_column(sheet, SCHEDULE_SHEET_NAME, SCHEDULE_COMPLETED_AT_COL)

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


def load_schedule_rows():
    return get_schedule_sheet().get_all_records()


def load_schedule_rows_with_index():
    rows = get_schedule_sheet().get_all_records()
    return [(index, row) for index, row in enumerate(rows, start=2)]


def load_signup_rows():
    return get_signup_sheet().get_all_records()


def load_matches_rows():
    return get_matches_sheet().get_all_records()


def load_matches_rows_with_index():
    rows = get_matches_sheet().get_all_records()
    return [(index, row) for index, row in enumerate(rows, start=2)]


def load_players_rows():
    return get_players_sheet().get_all_records()


def load_players_rows_with_index():
    rows = get_players_sheet().get_all_records()
    return [(index, row) for index, row in enumerate(rows, start=2)]


def append_signup(slot_id: str, user_id: int, display_name: str):
    now = datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M:%S")

    get_signup_sheet().append_row(
        [
            slot_id,
            str(user_id),
            display_name,
            now,
            "Ja",
            "signed_up",
        ],
        value_input_option="USER_ENTERED",
    )


def append_matches(match_rows: list[list]):
    if match_rows:
        get_matches_sheet().append_rows(match_rows, value_input_option="USER_ENTERED")


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

    sheet.update_cell(row_index, col_index, value)


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
        sheet.batch_update(requests, value_input_option="USER_ENTERED")


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
        sheet.batch_update(requests, value_input_option="USER_ENTERED")


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


def is_countdown_due(row: dict) -> bool:
    start = get_slot_start_dt(row)

    if not start:
        return False

    return datetime.now(BERLIN_TZ) >= start - timedelta(seconds=60)


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
    settings["quickswap"] = True
    settings["quick_swap"] = True
    settings["quickSwap"] = True


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
        if pyz3r_customizer is None:
            raise RuntimeError(
                "pyz3r.customizer konnte nicht importiert werden. "
                "Customizer-Presets wie Casual Boots können so nicht sicher erzeugt werden."
            )

        converted_settings = pyz3r_customizer.convert2settings(
            customizer_save=raw_settings,
            tournament=True,
        )

        if not isinstance(converted_settings, dict):
            raise RuntimeError("pyz3r.customizer.convert2settings hat keine gültigen Settings geliefert.")

        converted_settings["tournament"] = True
        converted_settings["spoilers"] = "off"
        force_quickswap_flags(converted_settings)

        # Wichtig:
        # Customizer-Seeds müssen über pyz3r.alttpr(customizer=True, ...)
        # erzeugt werden. ALTTPR.generate(...) kann Customizer-Startitems
        # je nach pyz3r-Version wie normale Randomizer-Settings behandeln.
        if not hasattr(pyz3r, "alttpr"):
            raise RuntimeError(
                "pyz3r.alttpr ist nicht verfügbar. "
                "Customizer-Seeds können mit dieser pyz3r-Version nicht sicher erzeugt werden."
            )

        seed = await pyz3r.alttpr(
            customizer=True,
            settings=converted_settings,
        )

    else:
        normal_settings = deepcopy(raw_settings)
        normal_settings["tournament"] = True
        normal_settings["spoilers"] = False
        force_quickswap_flags(normal_settings)

        seed = await pyz3r.ALTTPR.generate(settings=normal_settings)

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
        if pyz3r_customizer is None:
            raise RuntimeError(
                "pyz3r.customizer konnte nicht importiert werden. "
                "Customizer-Preset kann nicht sicher erzeugt werden."
            )

        converted_settings = pyz3r_customizer.convert2settings(
            customizer_save=settings,
            tournament=True,
        )
        force_quickswap_flags(converted_settings)

        if not hasattr(pyz3r, "alttpr"):
            raise RuntimeError(
                "pyz3r.alttpr ist nicht verfügbar. "
                "Customizer-Preset kann nicht sicher erzeugt werden."
            )

        seed = await pyz3r.alttpr(
            customizer=True,
            settings=converted_settings,
        )
    else:
        seed = await pyz3r.ALTTPR.generate(settings=settings)

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

    if not upcoming:
        description = f"Keine TFNL-Slots in den nächsten {days} Tagen gefunden."
    else:
        description = "\n".join(build_slot_line(row) for row in upcoming)

    now = datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M")

    embed = discord.Embed(
        title="TFNL-Spielplan",
        description=description,
        color=discord.Color.dark_teal(),
    )

    embed.set_footer(text=f"Try Force Nachteulen Ladder | Aktualisiert: {now} Uhr")
    return embed


def build_signup_embed(open_slots: list[dict]) -> discord.Embed:
    now = datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M")

    if not open_slots:
        description = (
            "Aktuell ist keine Anmeldung geöffnet.\n\n"
            "Early öffnet um `18:15 Uhr`.\n"
            "Late öffnet um `20:15 Uhr`."
        )
        title = "TFNL-Anmeldung"
    else:
        description = "\n\n".join(build_signup_line(row) for row in open_slots)
        title = "TFNL-Anmeldung geöffnet"

    embed = discord.Embed(
        title=title,
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


def user_already_signed_up(slot_id: str, user_id: int) -> bool:
    rows = load_signup_rows()

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
    rows = sheet.get_all_records()

    status_col = get_header_index(sheet, SIGNUP_SHEET_NAME, "Status")

    if not status_col:
        return False

    for row_index, row in enumerate(rows, start=2):
        if (
            normalize_text(row.get("Slot ID")) == slot_id
            and normalize_text(row.get("Discord ID")) == str(user_id)
            and normalize_text(row.get("Status")).lower() == "signed_up"
        ):
            sheet.update_cell(row_index, status_col, "cancelled")
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


def get_last_opponents() -> dict[str, set[str]]:
    rows = load_matches_rows()
    last_opponents: dict[str, set[str]] = {}

    for row in rows:
        players = [
            normalize_text(row.get("Spieler 1 Discord ID")),
            normalize_text(row.get("Spieler 2 Discord ID")),
            normalize_text(row.get("Spieler 3 Discord ID")),
        ]
        players = [p for p in players if p]

        for player_id in players:
            opponents = set(p for p in players if p != player_id)

            if opponents:
                last_opponents[player_id] = opponents

    return last_opponents


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


def create_pairings(participants: list[dict]) -> list[list[dict]]:
    count = len(participants)

    if count < 2:
        return []

    if count == 3:
        return [participants]

    last_opponents = get_last_opponents()
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
            ]
        )

    return rows


def is_slot_complete(slot_id: str) -> bool:
    matches = get_matches_for_slot(slot_id)

    if not matches:
        return False

    for match in matches:
        if normalize_text(match.get("Veröffentlicht")).lower() != "ja":
            return False

        for player in get_match_players(match):
            if not normalize_text(match.get(player["time_col"])):
                return False

    return True


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


def build_result_message(match_row: dict) -> str:
    match_id = normalize_text(match_row.get("Match ID"))
    matchtyp = normalize_text(match_row.get("Matchtyp"))
    players = get_match_players(match_row)

    lines = [
        "**TFNL-Ergebnis veröffentlicht**",
        f"`{match_id}` — `{matchtyp}`",
        "",
    ]

    for player in players:
        name = player["name"]
        time_value = normalize_text(match_row.get(player["time_col"]))
        result = normalize_text(match_row.get(player["result_col"]))
        points = normalize_text(match_row.get(player["points_col"]))

        lines.append(f"**{name}** — `{time_value}` — {result} ({points} Punkte)")

    return "\n".join(lines)


def apply_result_to_match(match_id: str, result: dict[int, tuple[str, int]]):
    values = {}

    for player_no, (result_text, points) in result.items():
        values[f"Ergebnis Spieler {player_no}"] = result_text
        values[f"Punkte Spieler {player_no}"] = str(points)

    values["Status"] = "finished"
    values["Veröffentlicht"] = "Ja"

    update_match_cells(match_id, values)


def collect_slot_results(slot_id: str) -> list[dict]:
    results = []

    for match in get_matches_for_slot(slot_id):
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
                    "is_ff": time_value.upper() == "FF",
                }
            )

    results.sort(
        key=lambda r: (
            r["is_ff"],
            r["seconds"] if r["seconds"] is not None else 9999999,
            r["name"].lower(),
        )
    )

    return results


def build_slot_overview_message(schedule_row: dict) -> str:
    slot_id = normalize_text(schedule_row.get("Slot ID"))
    datum = normalize_text(schedule_row.get("Datum"))
    slot = normalize_text(schedule_row.get("Slot"))
    modus = normalize_text(schedule_row.get("Modus"))
    seed_url = get_seed_url(schedule_row)
    results = collect_slot_results(slot_id)

    lines = [
        "**TFNL-Slot abgeschlossen**",
        "",
        f"Datum: `{datum}`",
        f"Slot: `{slot}`",
        f"Modus: `{modus}`",
        f"Seed: {seed_url if seed_url else '`nicht eingetragen`'}",
        "",
        "**Gesamtübersicht:**",
    ]

    if not results:
        lines.append("Keine Ergebnisse gefunden.")
    else:
        for index, result in enumerate(results, start=1):
            lines.append(
                f"{index}. **{result['name']}** — `{result['time']}` — "
                f"{result['result']} ({result['points']} Punkte)"
            )

    lines.extend(
        [
            "",
            "Der Channel wird 60 Minuten nach Abschluss gelöscht.",
        ]
    )

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
            ]

            players_sheet.update(f"A{row_index}:J{row_index}", [values])

        else:
            players_sheet.append_row(
                [
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
                ],
                value_input_option="USER_ENTERED",
            )

    sort_players_sheet()


def sort_players_sheet():
    sheet = get_players_sheet()
    rows = sheet.get_all_records()

    if not rows:
        return

    rows.sort(
        key=lambda r: (
            -int_value(r.get("Punkte")),
            -int_value(r.get("Siege")),
            -int_value(r.get("Remis")),
            int_value(r.get("Forfeits")),
            normalize_text(r.get("Discord Display Name")).lower(),
        )
    )

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
            ]
        )

    sheet.resize(rows=max(1000, len(values) + 1), cols=len(PLAYERS_HEADERS))
    sheet.update("A2:J", values)


def build_standings_messages() -> list[str]:
    rows = load_players_rows()

    rows.sort(
        key=lambda r: (
            -int_value(r.get("Punkte")),
            -int_value(r.get("Siege")),
            -int_value(r.get("Remis")),
            int_value(r.get("Forfeits")),
            normalize_text(r.get("Discord Display Name")).lower(),
        )
    )

    timestamp = datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M")

    header = [
        "**TFNL Gesamttabelle**",
        f"Stand: `{timestamp} Uhr`",
        "",
    ]

    if not rows:
        return ["\n".join(header + ["Noch keine Einträge."])]

    lines = header[:]

    for index, row in enumerate(rows, start=1):
        name = normalize_text(row.get("Discord Display Name"))
        points = int_value(row.get("Punkte"))
        starts = int_value(row.get("Starts"))
        wins = int_value(row.get("Siege"))
        draws = int_value(row.get("Remis"))
        losses = int_value(row.get("Niederlagen"))
        forfeits = int_value(row.get("Forfeits"))

        lines.append(
            f"{index}. **{name}** — {points} Pkt | {starts} Starts | "
            f"{wins}S / {draws}R / {losses}N | FF: {forfeits}"
        )

    messages = []
    current = ""

    for line in lines:
        candidate = f"{current}\n{line}" if current else line

        if len(candidate) > 1900:
            messages.append(current)
            current = line
        else:
            current = candidate

    if current:
        messages.append(current)

    return messages


# =========================================================
# MODE STANDINGS
# =========================================================

def get_schedule_mode_map() -> dict[str, str]:
    rows = load_schedule_rows()

    return {
        normalize_text(row.get("Slot ID")): normalize_text(row.get("Modus"))
        for row in rows
        if normalize_text(row.get("Slot ID"))
    }


def build_mode_standings(mode_name: str) -> list[dict]:
    requested_mode = get_canonical_mode_name(mode_name)
    schedule_modes = get_schedule_mode_map()
    matches = load_matches_rows()

    standings = {}

    for match in matches:
        slot_id = normalize_text(match.get("Slot ID"))
        match_mode = schedule_modes.get(slot_id, "")

        if get_canonical_mode_name(match_mode) != requested_mode:
            continue

        if normalize_text(match.get("Veröffentlicht")).lower() != "ja":
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
    rows = build_mode_standings(mode_name)
    timestamp = datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M")

    header = [
        f"**TFNL Modus-Tabelle: {mode_name}**",
        f"Stand: `{timestamp} Uhr`",
        "",
    ]

    if not rows:
        return [
            "\n".join(
                header + [
                    "Keine abgeschlossenen Ergebnisse für diesen Modus gefunden."
                ]
            )
        ]

    lines = header[:]

    for index, row in enumerate(rows, start=1):
        best = seconds_to_timecode(row["best_seconds"]) if row["best_seconds"] is not None else "-"
        avg = seconds_to_timecode(row["avg_seconds"]) if row["avg_seconds"] is not None else "-"

        lines.append(
            f"{index}. **{row['name']}** — {row['points']} Pkt | "
            f"{row['starts']} Starts | "
            f"{row['wins']}S / {row['draws']}R / {row['losses']}N | "
            f"FF: {row['forfeits']} | "
            f"Best: `{best}` | Ø: `{avg}`"
        )

    messages = []
    current = ""

    for line in lines:
        candidate = f"{current}\n{line}" if current else line

        if len(candidate) > 1900:
            messages.append(current)
            current = line
        else:
            current = candidate

    if current:
        messages.append(current)

    return messages


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


class UndoFinishView(discord.ui.View):
    def __init__(self, match_id: str, player_no: int):
        super().__init__(timeout=None)

        self.add_item(
            discord.ui.Button(
                label="Undo Finish",
                style=discord.ButtonStyle.secondary,
                custom_id=f"tfnl_undo_finish:{match_id}:{player_no}",
            )
        )


# =========================================================
# COG
# =========================================================

class LadderCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.last_schedule_message_id = None
        self.last_signup_message_id = None

        if not self.update_schedule_channel.is_running():
            self.update_schedule_channel.start()

        if not self.update_signup_channel.is_running():
            self.update_signup_channel.start()

        if not self.process_ladder_slots.is_running():
            self.process_ladder_slots.start()

    def cog_unload(self):
        self.update_schedule_channel.cancel()
        self.update_signup_channel.cancel()
        self.process_ladder_slots.cancel()

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
            view = SignupView(open_slots) if open_slots else None
        except Exception as e:
            print(f"[TFNL] Konnte Signup-Embed nicht bauen: {repr(e)}")
            return

        await self.send_signup_announcements(open_slots, channel)

        if self.last_signup_message_id:
            try:
                old_message = await channel.fetch_message(self.last_signup_message_id)
                await old_message.edit(embed=embed, view=view)
                return
            except Exception:
                self.last_signup_message_id = None

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
            print("[TFNL] Anmeldung im Channel aktualisiert.")
        except Exception as e:
            print(f"[TFNL] Konnte Signup nicht senden: {repr(e)}")

    async def publish_standings_to_channel(self):
        try:
            channel = await self.get_text_channel(TFNL_STANDINGS_CHANNEL_ID)
        except Exception as e:
            await self.log_tfnl(f"Konnte Standings-Channel nicht laden: {repr(e)}")
            return

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
            messages = build_standings_messages()

            for message in messages:
                await channel.send(message)

        except Exception as e:
            await self.log_tfnl(f"Gesamttabelle konnte nicht gepostet werden: {repr(e)}")

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
                await channel.send(message)

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

        role = member.guild.get_role(TFNL_LADDER_ROLE_ID)

        if role is None:
            await interaction.followup.send(
                "Anmeldung fehlgeschlagen: Ladder-Rolle wurde nicht gefunden.",
                ephemeral=True,
            )
            return

        if role not in member.roles:
            await interaction.followup.send(
                "Du hast keine Berechtigung für die TFNL-Ladder.",
                ephemeral=True,
            )
            return

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

        if user_already_signed_up(slot_id, member.id):
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
                        "Die Paarungen bleiben geheim bis zum Ergebnis."
                    )
                except Exception as e:
                    await self.log_tfnl(
                        f"Seed-DM konnte nicht gesendet werden: Slot `{slot_id}`, Spieler `{player['discord_id']}` — {repr(e)}"
                    )

        update_schedule_status(slot_id, "seed_sent")
        await self.publish_schedule_to_channel()

        return True

    async def send_countdown_dms(self, schedule_row: dict):
        slot_id = normalize_text(schedule_row.get("Slot ID"))
        matches = get_matches_for_slot(slot_id)
        sent_to = set()

        async def countdown(user: discord.User):
            try:
                message = await user.send("TFNL-Race startet in `60` Sekunden.")

                countdown_steps = [
                    (30, 30),
                    (10, 20),
                    (5, 5),
                    (4, 1),
                    (3, 1),
                    (2, 1),
                    (1, 1),
                ]

                for remaining, wait_seconds in countdown_steps:
                    await asyncio.sleep(wait_seconds)

                    try:
                        await message.edit(
                            content=f"TFNL-Race startet in `{remaining}` Sekunden."
                        )
                    except Exception:
                        pass

            except Exception as e:
                await self.log_tfnl(f"Countdown-DM fehlgeschlagen: {repr(e)}")

        for match in matches:
            for player in get_match_players(match):
                if player["discord_id"] in sent_to:
                    continue

                sent_to.add(player["discord_id"])

                try:
                    user = await self.bot.fetch_user(int(player["discord_id"]))
                    self.bot.loop.create_task(countdown(user))
                except Exception as e:
                    await self.log_tfnl(
                        f"Countdown-DM konnte nicht vorbereitet werden: Spieler `{player['discord_id']}` — {repr(e)}"
                    )

        update_schedule_status(slot_id, "countdown_sent")

    async def send_start_dms(self, schedule_row: dict):
        slot_id = normalize_text(schedule_row.get("Slot ID"))
        matches = get_matches_for_slot(slot_id)

        for match in matches:
            match_id = normalize_text(match.get("Match ID"))

            update_match_cell(match_id, "Status", "running")

            for player in get_match_players(match):
                try:
                    user = await self.bot.fetch_user(int(player["discord_id"]))
                    await user.send(
                        "**TFNL-Race gestartet.**\n\n"
                        "Zeitmessung läuft ab der geplanten Startzeit.\n"
                        "Klicke `Finish`, sobald du fertig bist.\n"
                        "Klicke `Forfeit`, wenn du aufgibst.",
                        view=RaceControlView(match_id, player["no"]),
                    )
                except Exception as e:
                    await self.log_tfnl(
                        f"Start-DM konnte nicht gesendet werden: Match `{match_id}`, Spieler `{player['discord_id']}` — {repr(e)}"
                    )

        update_schedule_status(slot_id, "running")

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

            await interaction.followup.send(
                "Finish wurde zurückgenommen. Die Zeitmessung läuft weiter.\n"
                "Du kannst erneut finishen oder forfeiten.",
                view=RaceControlView(match_id, player_no),
                ephemeral=True,
            )

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

            update_match_cells(
                match_id,
                {
                    f"Zeit Spieler {player_no}": "FF",
                    "Status": "partial_result",
                },
            )

            await interaction.followup.send("Forfeit wurde eingetragen: `FF`.", ephemeral=True)

            await self.evaluate_match_if_complete(match_id)

        except Exception as e:
            await interaction.followup.send(
                f"Fehler beim Forfeit:\n```{repr(e)}```",
                ephemeral=True,
            )

    async def evaluate_match_if_complete(self, match_id: str):
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

        update_players_from_match(updated_match)

        slot_id = normalize_text(updated_match.get("Slot ID"))
        _, schedule_row = find_schedule_row(slot_id)

        if schedule_row:
            try:
                slot_channel = await self.get_or_create_slot_channel(schedule_row)
                await slot_channel.send(build_result_message(updated_match))
            except Exception as e:
                await self.log_tfnl(f"Ergebnispost fehlgeschlagen für `{match_id}` — {repr(e)}")

            await self.complete_slot_if_ready(slot_id)

    async def complete_slot_if_ready(self, slot_id: str):
        _, schedule_row = find_schedule_row(slot_id)

        if not schedule_row:
            return

        status = normalize_text(schedule_row.get("Status")).lower()

        if status in ("completed", "archived", "cancelled"):
            return

        completed_at_existing = normalize_text(schedule_row.get(SCHEDULE_COMPLETED_AT_COL))

        if completed_at_existing:
            return

        if not is_slot_complete(slot_id):
            return

        completed_at = set_schedule_completed(slot_id)

        _, updated_schedule_row = find_schedule_row(slot_id)

        if not updated_schedule_row:
            updated_schedule_row = schedule_row

        try:
            slot_channel = await self.get_or_create_slot_channel(updated_schedule_row)
            await slot_channel.send(build_slot_overview_message(updated_schedule_row))
        except Exception as e:
            await self.log_tfnl(f"Slot-Gesamtübersicht konnte nicht gepostet werden: `{slot_id}` — {repr(e)}")

        await self.publish_standings_to_channel()

        slot_mode = normalize_text(updated_schedule_row.get("Modus"))
        await self.publish_mode_standings_to_channel(slot_mode, clear_existing=False)

        await self.publish_schedule_to_channel()
        await self.publish_signup_to_channel()

        await self.log_tfnl(
            f"Slot `{slot_id}` completed um `{completed_at}`. Channel-Löschung in 60 Minuten."
        )

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
        channel_id = normalize_text(schedule_row.get("Slot Channel ID"))

        if not is_completed_channel_delete_due(schedule_row):
            return

        if not channel_id:
            update_schedule_status(slot_id, "archived")
            return

        try:
            channel = self.bot.get_channel(int(channel_id))

            if channel is None:
                channel = await self.bot.fetch_channel(int(channel_id))

            await channel.delete(reason="TFNL Slot 60 Minuten nach Abschluss gelöscht")
        except Exception as e:
            await self.log_tfnl(f"Slot-Channel konnte nicht gelöscht werden: `{slot_id}` — {repr(e)}")

        update_schedule_status(slot_id, "archived")
        await self.publish_schedule_to_channel()

    # =====================================================
    # PAIRING LOGIC
    # =====================================================

    async def process_schedule_states(self):
        rows_with_index = load_schedule_rows_with_index()

        for _, row in rows_with_index:
            slot_id = normalize_text(row.get("Slot ID"))
            status = normalize_text(row.get("Status")).lower()

            if not slot_id:
                continue

            if status in ("archived", "cancelled"):
                continue

            if status == "completed":
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
                continue

            if status == "seed_sent" and is_countdown_due(row):
                await self.send_countdown_dms(row)
                continue

            if status == "countdown_sent" and is_start_due(row):
                await self.send_start_dms(row)
                continue

            if status == "running" and is_slot_end_due(row):
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
            update_schedule_status(slot_id, "cancelled")

            if slot_channel:
                await slot_channel.send(
                    "**Anmeldung geschlossen.**\n"
                    "Der Slot wurde abgesagt, da weniger als 2 Spieler angemeldet sind."
                )

            await self.log_tfnl(f"Slot `{slot_id}` cancelled: weniger als 2 Teilnehmer.")
            await self.publish_schedule_to_channel()
            await self.publish_signup_to_channel()
            return

        pairings = create_pairings(participants)
        match_rows = build_match_rows(slot_id, schedule_row, pairings)

        append_matches(match_rows)
        update_schedule_status(slot_id, "paired")

        if slot_channel:
            await slot_channel.send(
                "**Anmeldung geschlossen.**\n"
                "Die Paarungen wurden geheim ausgelost.\n"
                "Ihr erhaltet die weiteren Informationen später per DM."
            )

        await self.log_tfnl(f"Slot `{slot_id}` paired: {len(match_rows)} Match(es) erstellt.")

        await self.publish_schedule_to_channel()
        await self.publish_signup_to_channel()

    # =====================================================
    # TASKS
    # =====================================================

    @tasks.loop(minutes=5)
    async def update_schedule_channel(self):
        await self.publish_schedule_to_channel()

    @update_schedule_channel.before_loop
    async def before_update_schedule_channel(self):
        await self.bot.wait_until_ready()
        await self.publish_schedule_to_channel()

    @tasks.loop(minutes=2)
    async def update_signup_channel(self):
        await self.publish_signup_to_channel()

    @update_signup_channel.before_loop
    async def before_update_signup_channel(self):
        await self.bot.wait_until_ready()
        await self.publish_signup_to_channel()

    @tasks.loop(minutes=1)
    async def process_ladder_slots(self):
        try:
            await self.process_schedule_states()
        except Exception as e:
            await self.log_tfnl(f"Fehler in process_ladder_slots: {repr(e)}")

    @process_ladder_slots.before_loop
    async def before_process_ladder_slots(self):
        await self.bot.wait_until_ready()

    # =====================================================
    # COMMANDS
    # =====================================================

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
            await interaction.followup.send(message, ephemeral=False)

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
            f"Quick-Swap-Flags: `gesetzt`\n"
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


async def setup(bot: commands.Bot):
    await bot.add_cog(LadderCog(bot))
