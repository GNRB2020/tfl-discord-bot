from __future__ import annotations

import os
from threading import RLock

import gspread
from google.oauth2.service_account import Credentials


SEASON_SPREADSHEET_ID = os.getenv(
    "SEASON_SPREADSHEET_ID",
    "1pZxg1_DUtbO4dZvX95ZrIqEZnkMc1MjmE7z5SEsMHQU",
).strip()

ASYNC_SPREADSHEET_ID = os.getenv(
    "ASYNC_SPREADSHEET_ID",
    "1TnKRQM8x2mLHfiaNC_dtlnjazJ5Ph5hz2edixM0Jhw8",
).strip()

GOOGLE_CREDENTIALS_FILE = os.getenv(
    "GOOGLE_CREDENTIALS_FILE",
    os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials.json"),
).strip()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_LOCK = RLock()
_CLIENT = None
_SPREADSHEETS = {}
_WORKSHEETS_BY_TITLE = {}
_WORKSHEETS_BY_GID = {}


def get_client() -> gspread.Client:
    global _CLIENT

    with _LOCK:
        if _CLIENT is not None:
            return _CLIENT

        creds = Credentials.from_service_account_file(
            GOOGLE_CREDENTIALS_FILE,
            scopes=SCOPES,
        )
        _CLIENT = gspread.authorize(creds)
        print(f"✅ [SHEETS] Google-Client verbunden über {GOOGLE_CREDENTIALS_FILE}")
        return _CLIENT


def get_spreadsheet(spreadsheet_id: str):
    spreadsheet_id = str(spreadsheet_id or "").strip()
    if not spreadsheet_id:
        raise RuntimeError("Spreadsheet-ID fehlt.")

    with _LOCK:
        cached = _SPREADSHEETS.get(spreadsheet_id)
        if cached is not None:
            return cached

        spreadsheet = get_client().open_by_key(spreadsheet_id)
        _SPREADSHEETS[spreadsheet_id] = spreadsheet
        print(f"✅ [SHEETS] Spreadsheet geöffnet: {spreadsheet_id}")
        return spreadsheet


def get_season_spreadsheet():
    return get_spreadsheet(SEASON_SPREADSHEET_ID)


def get_async_spreadsheet():
    return get_spreadsheet(ASYNC_SPREADSHEET_ID)


def get_worksheet_by_title(spreadsheet_id: str, title: str):
    key = (spreadsheet_id, title)

    with _LOCK:
        cached = _WORKSHEETS_BY_TITLE.get(key)
        if cached is not None:
            return cached

        ws = get_spreadsheet(spreadsheet_id).worksheet(title)
        _WORKSHEETS_BY_TITLE[key] = ws
        return ws


def get_season_worksheet(title: str):
    return get_worksheet_by_title(SEASON_SPREADSHEET_ID, title)


def get_worksheet_by_gid(spreadsheet_id: str, gid: int):
    gid = int(gid)
    key = (spreadsheet_id, gid)

    with _LOCK:
        cached = _WORKSHEETS_BY_GID.get(key)
        if cached is not None:
            return cached

        spreadsheet = get_spreadsheet(spreadsheet_id)

        try:
            ws = spreadsheet.get_worksheet_by_id(gid)
        except Exception:
            ws = None

        if ws is None:
            for candidate in spreadsheet.worksheets():
                if int(getattr(candidate, "id", -1)) == gid:
                    ws = candidate
                    break

        if ws is None:
            raise RuntimeError(
                f"Worksheet mit GID {gid} in Spreadsheet {spreadsheet_id} nicht gefunden."
            )

        _WORKSHEETS_BY_GID[key] = ws
        _WORKSHEETS_BY_TITLE[(spreadsheet_id, getattr(ws, "title", ""))] = ws
        return ws


def get_season_worksheet_by_gid(gid: int):
    return get_worksheet_by_gid(SEASON_SPREADSHEET_ID, gid)


def clear_connection_cache():
    global _CLIENT
    with _LOCK:
        _CLIENT = None
        _SPREADSHEETS.clear()
        _WORKSHEETS_BY_TITLE.clear()
        _WORKSHEETS_BY_GID.clear()
