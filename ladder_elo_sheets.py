"""
Google-Sheets setup helpers for the TFNL Ladder ELO system.

Dieses Modul legt benötigte Sheets und fehlende Header automatisch an.
Bestehende Daten werden nicht überschrieben.
"""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
from oauth2client.service_account import ServiceAccountCredentials

BERLIN_TZ = ZoneInfo("Europe/Berlin")

TFNL_SPREADSHEET_ID = os.getenv(
    "TFNL_SPREADSHEET_ID",
    "1TamFbS5cRCcgSJFoQEohXdv03tVhk0VynvleeiVBQsM",
).strip()

CREDS_FILE = os.getenv(
    "GOOGLE_CREDENTIALS_FILE",
    os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials.json"),
).strip()

SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

SETTINGS_SHEET_NAME = "Settings"
SETTINGS_HEADERS = ["Key", "Value"]
ACTIVE_SEASON_KEY = "ACTIVE_SEASON"
DEFAULT_ACTIVE_SEASON = "TFNL-S1"

CORE_SHEETS_REQUIRING_SEASON = [
    "Schedule",
    "Signup",
    "Matches",
    "Players",
]

RATINGS_SHEET_NAME = "Ladder_Ratings"
RATING_HISTORY_SHEET_NAME = "Ladder_RatingHistory"
SEED_COMPARISON_SHEET_NAME = "Ladder_SeedComparison"

RATINGS_HEADERS = [
    "Player ID",
    "Player Name",
    "Season",
    "Mode",
    "Scope",
    "Elo",
    "Wins",
    "Draws",
    "Lose",
    "Games",
    "Winrate",
    "Updated At",
]

RATING_HISTORY_HEADERS = [
    "Rating Event ID",
    "Season",
    "Slot ID",
    "Date",
    "Mode",
    "Race Type",
    "Player ID",
    "Player Name",
    "Opponent Info",
    "Placement",
    "Score",
    "Elo Scope",
    "Elo Before",
    "Opponent Elo Used",
    "Elo After",
    "Elo Change",
    "Result Type",
    "Created At",
]

SEED_COMPARISON_HEADERS = [
    "Season",
    "Slot ID",
    "Date",
    "Mode",
    "Placement",
    "Player ID",
    "Player Name",
    "Time",
    "Status",
    "Winner Time",
    "Gap To Winner",
    "Created At",
]

_WORKSHEET_CACHE: dict[str, gspread.Worksheet] = {}


def normalize_text(value) -> str:
    return str(value or "").strip()


def now_text() -> str:
    return datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M:%S")


def get_spreadsheet():
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    client = gspread.authorize(creds)
    return client.open_by_key(TFNL_SPREADSHEET_ID)


def get_or_create_sheet(title: str, rows: int = 1000, cols: int = 30):
    cached = _WORKSHEET_CACHE.get(title)

    if cached is not None:
        return cached

    spreadsheet = get_spreadsheet()

    try:
        sheet = spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)

    _WORKSHEET_CACHE[title] = sheet
    return sheet


def ensure_headers(sheet, required_headers: list[str]) -> list[str]:
    existing_headers = sheet.row_values(1)

    if not existing_headers:
        sheet.update("A1", [required_headers])
        return required_headers[:]

    headers = existing_headers[:]
    missing_headers = [header for header in required_headers if header not in headers]

    if missing_headers:
        start_col = len(headers) + 1
        end_col = len(headers) + len(missing_headers)
        start_a1 = gspread.utils.rowcol_to_a1(1, start_col)
        end_a1 = gspread.utils.rowcol_to_a1(1, end_col)
        sheet.update(f"{start_a1}:{end_a1}", [missing_headers])
        headers.extend(missing_headers)

    return headers


def ensure_sheet_with_headers(
    title: str,
    required_headers: list[str],
    rows: int = 1000,
    cols: int | None = None,
):
    sheet = get_or_create_sheet(
        title=title,
        rows=rows,
        cols=cols or max(30, len(required_headers)),
    )
    headers = ensure_headers(sheet, required_headers)
    return sheet, headers


def ensure_settings_sheet() -> str:
    sheet, _ = ensure_sheet_with_headers(
        SETTINGS_SHEET_NAME,
        SETTINGS_HEADERS,
        rows=100,
        cols=len(SETTINGS_HEADERS),
    )

    records = sheet.get_all_records()

    for row_index, row in enumerate(records, start=2):
        if normalize_text(row.get("Key")) == ACTIVE_SEASON_KEY:
            value = normalize_text(row.get("Value"))

            if value:
                return value

            sheet.update_cell(row_index, 2, DEFAULT_ACTIVE_SEASON)
            return DEFAULT_ACTIVE_SEASON

    sheet.append_row([ACTIVE_SEASON_KEY, DEFAULT_ACTIVE_SEASON], value_input_option="USER_ENTERED")
    return DEFAULT_ACTIVE_SEASON


def get_active_season() -> str:
    return ensure_settings_sheet()


def ensure_core_season_columns() -> list[str]:
    touched = []

    for sheet_name in CORE_SHEETS_REQUIRING_SEASON:
        sheet = get_or_create_sheet(sheet_name)
        existing_headers = sheet.row_values(1)

        if not existing_headers:
            # Diese Sheets sollten im bestehenden Bot normalerweise bereits Header haben.
            # Leere Sheets werden hier nicht künstlich mit Teilheadern erzeugt.
            continue

        if "Season" not in existing_headers:
            next_col = len(existing_headers) + 1
            sheet.update_cell(1, next_col, "Season")
            touched.append(sheet_name)

    return touched


def ensure_ladder_elo_sheets() -> dict:
    active_season = ensure_settings_sheet()
    season_columns_added = ensure_core_season_columns()

    ensure_sheet_with_headers(
        RATINGS_SHEET_NAME,
        RATINGS_HEADERS,
        rows=1000,
        cols=len(RATINGS_HEADERS),
    )

    ensure_sheet_with_headers(
        RATING_HISTORY_SHEET_NAME,
        RATING_HISTORY_HEADERS,
        rows=5000,
        cols=len(RATING_HISTORY_HEADERS),
    )

    ensure_sheet_with_headers(
        SEED_COMPARISON_SHEET_NAME,
        SEED_COMPARISON_HEADERS,
        rows=5000,
        cols=len(SEED_COMPARISON_HEADERS),
    )

    return {
        "active_season": active_season,
        "season_columns_added": season_columns_added,
        "sheets": [
            SETTINGS_SHEET_NAME,
            RATINGS_SHEET_NAME,
            RATING_HISTORY_SHEET_NAME,
            SEED_COMPARISON_SHEET_NAME,
        ],
        "checked_at": now_text(),
    }
