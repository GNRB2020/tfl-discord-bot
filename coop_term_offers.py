"""Coop-Terminbörse nach dem Vorbild der Divisions-Terminbörse.

Ausschließlich Coop_A / Coop_B. Keine Änderungen an der Einzel-League.
Öffentliche Angebote enthalten bis zu drei freie Termine und keinen festen Gegner.
Beim Anklicken werden freie Begegnungen geprüft, danach wählt ein Runner des
Heimteams den Modus. Persistente Google-Sheets-Daten überstehen Bot-Neustarts.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta

import discord
import pytz
from gspread.exceptions import WorksheetNotFound

from sheet_guard import sheet_write_call
from sheets_connection import get_season_spreadsheet

LOG = logging.getLogger(__name__)
TZ = pytz.timezone("Europe/Berlin")
CHANNEL_ID = int(os.getenv("TFL_COOP_TERMINBOERSE_CHANNEL_ID", "1544986965202567188"))
STORE_SHEET = "CoopTerminboerseV3"
MODES = ("AD Boots", "Crosskeys", "Duality", "Logical Enemizer", "Influkeys", "Pilot Spoiler")
HEADERS = ["ID", "Gruppe", "Anbieterteam", "Anbieter ID", "Termin", "Status", "Kanal ID", "Nachricht ID", "Heimteam", "Gastteam", "Matchzeile", "Modus", "Annehmendes Team", "Modus-Deadline", "Event", "Aktualisiert"]
_LOCK = threading.RLock()
_STATUSES = {"offen", "moduswahl", "gebucht", "abgelaufen", "zurückgezogen"}


def _player():
    import player
    return player


def _norm(value):
    return _player().normalize_name(str(value or ""))


def _cell(row, index):
    return str(row[index]).strip() if index < len(row) else ""


def _now():
    return datetime.now(TZ)


def _parse(value):
    try:
        naive = datetime.strptime(value.strip(), "%d.%m.%Y %H:%M")
        result = TZ.localize(naive, is_dst=None)
    except (ValueError, pytz.exceptions.AmbiguousTimeError, pytz.exceptions.NonExistentTimeError):
        raise ValueError("Datum bitte als TT.MM.JJJJ HH:MM eingeben (gültige Berliner Ortszeit).")
    if result <= _now():
        raise ValueError("Der Termin liegt nicht in der Zukunft.")
    return result


def _ws():
    wb = get_season_spreadsheet()
    try:
        ws = wb.worksheet(STORE_SHEET)
    except WorksheetNotFound:
        ws = wb.add_worksheet(title=STORE_SHEET, rows=1000, cols=len(HEADERS))
    if ws.col_count < len(HEADERS):
        ws.add_cols(len(HEADERS) - ws.col_count)
    first = ws.row_values(1)
    if not any(first):
        ws.update("A1:P1", [HEADERS])
    elif first[:len(HEADERS)] != HEADERS:
        raise RuntimeError(f"{STORE_SHEET}: Spaltenüberschriften weichen ab. Keine Änderung vorgenommen.")
    return ws


def _all():
    return _ws().get("A:P")


def _load(identifier):
    rows = _all()
    for i, row in enumerate(rows[1:], 2):
        if _cell(row, 0) == identifier:
            return i, row
    raise ValueError("Dieses Coop-Terminangebot existiert nicht mehr.")


def _update(rowno, data):
    ws = _ws()
    ws.update(f"A{rowno}:P{rowno}", [data], value_input_option="RAW")


def _save(rowno, row):
    values = [_cell(row, i) for i in range(16)]
    values[15] = _now().strftime("%d.%m.%Y %H:%M:%S")
    _update(rowno, values)


def _matches(group, team):
    p = _player()
    rows = p._coop_group_rows(group, True)
    return [m for m in p._coop_group_matches(group, rows)
            if _norm(team) in {_norm(m["home"]), _norm(m["away"])}]


def _identity(member):
    p = _player()
    data = p._coop_team_identity(member)
    if data.get("group") not in ("Coop_A", "Coop_B") or not data.get("team_name"):
        raise PermissionError("Keinem Coop-Team zugeordnet.")
    return data["group"], data["team_name"]


def _team_members(group, team):
    p = _player()
    return p._coop_ids_for_team(group, team)


async def _notify(guild, group, teams, content):
    """Jeden Spieler höchstens einmal informieren; DM-Fehler sind nicht fatal."""
    if guild is None:
        return 0
    p = _player()
    seen = set()
    total = 0
