import os
import re
import unicodedata

from sheet_guard import get_all_values_cached
from sheets_connection import get_season_spreadsheet, get_season_worksheet


DIV_COL_LEFT = 4
DIV_COL_MARKER = 5
DIV_COL_RIGHT = 6

RESTINFO_PERFORMANCE_VERSION = "restinfo-performance-v2-central-sheets"
print(f"[RESTINFO] geladen: {RESTINFO_PERFORMANCE_VERSION}")

RESTINFO_SHEET_CACHE_TTL_SECONDS = int(
    os.getenv("RESTINFO_SHEET_CACHE_TTL_SECONDS", "120")
)

SHEETS_ENABLED = True
WB = None
_WORKSHEET_CACHE = {}


def _ensure_workbook():
    global WB, SHEETS_ENABLED

    if WB is not None:
        return WB

    try:
        WB = get_season_spreadsheet()
        SHEETS_ENABLED = True
        return WB
    except Exception as e:
        SHEETS_ENABLED = False
        raise RuntimeError(
            f"Google Sheets nicht verbunden: {type(e).__name__}: {e}"
        ) from e


def sheets_required():
    _ensure_workbook()


def _cell(row, idx0):
    return row[idx0].strip() if 0 <= idx0 < len(row) else ""


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = value.strip().lower()
    return re.sub(r"[^a-z0-9äöüß]", "", value)


def _division_worksheet(div_number: str):
    sheet_name = f"{div_number}.DIV"

    if sheet_name in _WORKSHEET_CACHE:
        return _WORKSHEET_CACHE[sheet_name]

    ws = get_season_worksheet(sheet_name)
    _WORKSHEET_CACHE[sheet_name] = ws
    return ws


def _division_values(div_number: str):
    ws = _division_worksheet(div_number)

    return get_all_values_cached(
        lambda: ws,
        sheet_name=getattr(ws, "title", f"{div_number}.DIV"),
        ttl_seconds=RESTINFO_SHEET_CACHE_TTL_SECONDS,
    )


def _unique_players_from_column_l(rows):
    players = []
    seen = set()

    for row in rows[1:]:
        name = _cell(row, 11)

        if not name:
            continue

        key = normalize_name(name)
        if not key or key in seen:
            continue

        seen.add(key)
        players.append(name)

    return players


def list_rest_players(div_number: str):
    return _unique_players_from_column_l(_division_values(div_number))


def list_restprogramm(div_number: str, player_name: str):
    rows = _division_values(div_number)
    matches = []
    target = normalize_name(player_name)

    for idx, row in enumerate(rows[1:], start=2):
        heim = _cell(row, DIV_COL_LEFT - 1)
        marker = _cell(row, DIV_COL_MARKER - 1)
        gast = _cell(row, DIV_COL_RIGHT - 1)

        if marker.lower() != "vs":
            continue

        if normalize_name(heim) == target or normalize_name(gast) == target:
            matches.append(
                {
                    "row_index": idx,
                    "heim": heim,
                    "gast": gast,
                }
            )

    return matches


def format_restprogramm_text(div_number: str, player: str):
    matches = list_restprogramm(div_number, player)

    if not matches:
        return (
            f"Division {div_number} – Restprogramm für **{player}**:\n"
            "Es sind keine offenen Spiele mehr in der Tabelle (E != 'vs')."
        )

    lines = [f"Division {div_number} – Restprogramm für **{player}**:", ""]
    target = normalize_name(player)

    for match in matches:
        heim = match["heim"]
        gast = match["gast"]

        if normalize_name(heim) == target:
            lines.append(f"- **{heim} (H)** vs {gast}")
        elif normalize_name(gast) == target:
            lines.append(f"- {heim} vs **{gast} (A)**")
        else:
            lines.append(f"- {heim} vs {gast}")

    return "\n".join(lines)


def find_divisions_with_open_matches(player_name: str):
    found = []

    for div_number in ["1", "2", "3", "4", "5", "6"]:
        try:
            if list_restprogramm(div_number, player_name):
                found.append(div_number)
        except Exception:
            continue

    return found


def find_divisions_with_player(player_name: str):
    target = normalize_name(player_name)
    found = []

    for div_number in ["1", "2", "3", "4", "5", "6"]:
        try:
            players = list_rest_players(div_number)
        except Exception:
            continue

        if any(normalize_name(player) == target for player in players):
            found.append(div_number)

    return found


def get_open_restprogramm_text_for_name_candidates(name_candidates):
    clean_candidates = []
    seen = set()

    for name in name_candidates:
        if not name:
            continue

        norm = normalize_name(name)
        if norm and norm not in seen:
            seen.add(norm)
            clean_candidates.append(name.strip())

    for candidate in clean_candidates:
        divisions = find_divisions_with_open_matches(candidate)

        if len(divisions) == 1:
            return format_restprogramm_text(divisions[0], candidate)

        if len(divisions) > 1:
            parts = []
            for div in divisions:
                parts.append(format_restprogramm_text(div, candidate))
            return "\n\n".join(parts)

    tried = ", ".join(f"`{n}`" for n in clean_candidates) or "-"
    return (
        "Für dich konnte kein offenes Restprogramm gefunden werden.\n"
        f"Verwendete Namensvarianten: {tried}"
    )


def list_streichungen(div_number: str):
    rows = _division_values(div_number)
    entries = []

    for row in rows[1:10]:
        player = _cell(row, 11)
        mode_m = _cell(row, 12)
        mode_n = _cell(row, 13)

        if player:
            entries.append(
                {
                    "spieler": player,
                    "modus_m": mode_m,
                    "modus_n": mode_n,
                }
            )

    return entries


def get_streich_text_for_division(div_number: str):
    entries = list_streichungen(div_number)

    if not entries:
        return f"Keine Streichungen in Division {div_number} hinterlegt."

    lines = [f"📝 Streichungen in Division {div_number}:", ""]

    for entry in entries:
        modes = [x for x in (entry["modus_m"], entry["modus_n"]) if x]
        suffix = " | ".join(modes)
        lines.append(
            f"- **{entry['spieler']}**" + (f": {suffix}" if suffix else "")
        )

    return "\n".join(lines)


def get_own_division_streich_text(name_candidates):
    found = []

    for candidate in name_candidates:
        if not candidate:
            continue

        for div in find_divisions_with_player(candidate):
            if div not in found:
                found.append(div)

    if len(found) == 1:
        return get_streich_text_for_division(found[0])

    if len(found) > 1:
        return (
            "Du wurdest in mehreren Divisionen gefunden:\n"
            + "\n".join(f"- Division {div}" for div in found)
        )

    tried = ", ".join(f"`{n}`" for n in name_candidates if n) or "-"
    return (
        "Für dich konnte keine Division ermittelt werden.\n"
        f"Verwendete Namensvarianten: {tried}"
    )
