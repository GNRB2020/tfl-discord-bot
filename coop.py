import asyncio
import os
import re
import sys
import threading
from datetime import datetime as dt

import discord
import pytz
from gspread.exceptions import WorksheetNotFound
from sheets_connection import get_season_spreadsheet


BERLIN_TZ = pytz.timezone("Europe/Berlin")

# =========================================================
# COOP STORAGE
# =========================================================
# WICHTIG:
# Das bestehende Sheet "Coop" wird von diesem Modul NICHT mehr beschrieben.
# Anmeldung und Konfiguration liegen bewusst in separaten Bot-Sheets.

COOP_SIGNUP_SHEET = os.getenv("TFL_COOP_SIGNUP_SHEET", "CoopAnmeldungen").strip() or "CoopAnmeldungen"
COOP_CONFIG_SHEET = os.getenv("TFL_COOP_CONFIG_SHEET", "CoopConfig").strip() or "CoopConfig"
RUNNER_SHEET = "Runner"

# Kompatibilitaets-Alias fuer eventuelle externe Imports.
COOP_SHEET = COOP_SIGNUP_SHEET

_COOP_WS_CACHE = {}
_COOP_WRITE_LOCK = threading.RLock()

# CoopAnmeldungen:
# A Teamname
# B Spieler 1
# C Spieler 2
# D Twitch Spieler 1
# E Twitch Spieler 2
# F Status
# G Erstellt am
# H Bestaetigt am
# I Erstellt von
# J Discord-ID Spieler 1
# K Discord-ID Spieler 2

COOP_HEADERS = [
    "Teamname",
    "Spieler 1",
    "Spieler 2",
    "Twitch Spieler 1",
    "Twitch Spieler 2",
    "Status",
    "Erstellt am",
    "Bestätigt am",
    "Erstellt von",
    "Discord ID Spieler 1",
    "Discord ID Spieler 2",
]

CONFIG_HEADERS = ["Schlüssel", "Wert"]
CONFIG_KEY_SIGNUP = "Anmeldung"
CONFIG_KEY_LIMIT = "Max Teams"

ACTIVE_STATUSES = {"offen", "bestätigt"}
FINAL_STATUS = "bestätigt"


# =========================================================
# HELFER
# =========================================================

def normalize_name(value: str) -> str:
    value = (value or "").strip().lower()
    return re.sub(r"[^a-z0-9äöüß]", "", value)


def normalize_twitch(value: str) -> str:
    value = (value or "").strip().rstrip("/")
    if not value:
        return ""

    match = re.search(
        r"(?:https?://)?(?:www\.)?twitch\.tv/([^/?#]+)",
        value,
        re.IGNORECASE,
    )
    if match:
        value = match.group(1)

    return value.strip().lstrip("@")


def now_str() -> str:
    return dt.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M")


def get_main_bot_module():
    for module_name in ("__main__", "bot"):
        module = sys.modules.get(module_name)
        if module is not None and hasattr(module, "WB"):
            return module
    return None


def get_main_helper(name: str):
    module = get_main_bot_module()
    if module is None:
        raise RuntimeError("Hauptmodul des Bots wurde nicht gefunden.")

    helper = getattr(module, name, None)
    if helper is None:
        raise RuntimeError(f"Bot-Helfer '{name}' ist nicht verfügbar.")

    return helper


def get_player_module():
    module = sys.modules.get("player")
    if module is None:
        raise RuntimeError("player.py ist nicht geladen.")
    return module


def menu_embed(title: str, description: str, color: int = 0x00FFCC) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color)


def _cell(row, idx0: int) -> str:
    if not row or idx0 < 0 or idx0 >= len(row):
        return ""
    return str(row[idx0] or "").strip()


def get_shared_workbook():
    return get_season_spreadsheet()


def _get_or_create_ws(sheet_name: str, rows: int, cols: int):
    if sheet_name in _COOP_WS_CACHE:
        return _COOP_WS_CACHE[sheet_name]

    wb = get_shared_workbook()
    try:
        ws = wb.worksheet(sheet_name)
    except WorksheetNotFound:
        ws = wb.add_worksheet(title=sheet_name, rows=rows, cols=cols)
        print(f"✅ [COOP] Sheet '{sheet_name}' wurde automatisch angelegt.")
    except Exception as exc:
        raise RuntimeError(
            f"Tabellenblatt '{sheet_name}' konnte nicht geöffnet werden: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    _COOP_WS_CACHE[sheet_name] = ws
    return ws


def get_cached_ws(sheet_name: str):
    """Kompatibilitaets-Helfer fuer bekannte bestehende Sheets."""
    if sheet_name in _COOP_WS_CACHE:
        return _COOP_WS_CACHE[sheet_name]

    wb = get_shared_workbook()
    try:
        ws = wb.worksheet(sheet_name)
    except Exception as exc:
        raise RuntimeError(
            f"Tabellenblatt '{sheet_name}' konnte nicht geöffnet werden: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    _COOP_WS_CACHE[sheet_name] = ws
    return ws


def get_coop_ws():
    """Anmelde-Sheet. Das alte Sheet 'Coop' wird nicht mehr verwendet."""
    return ensure_coop_sheet_structure()


def get_runner_ws_local():
    return get_cached_ws(RUNNER_SHEET)


def _read_signup_rows(ws):
    # Bewusst NUR A:K lesen. Inhalte rechts davon koennen die Anmeldelogik
    # dadurch weder beeinflussen noch verschieben.
    values = ws.get("A:K")
    return values or []


def ensure_coop_sheet_structure():
    ws = _get_or_create_ws(COOP_SIGNUP_SHEET, rows=1000, cols=11)
    first_row = ws.get("A1:K1")
    current = first_row[0] if first_row else []
    current = [_cell(current, i) for i in range(11)]

    if not any(current):
        ws.update("A1:K1", [COOP_HEADERS])
    elif current != COOP_HEADERS:
        raise RuntimeError(
            f"'{COOP_SIGNUP_SHEET}' hat nicht die erwartete Struktur in A1:K1. "
            "Der Bot schreibt aus Sicherheitsgründen nichts in dieses Sheet."
        )

    return ws


def ensure_config_sheet_structure():
    ws = _get_or_create_ws(COOP_CONFIG_SHEET, rows=20, cols=2)
    values = ws.get("A1:B3")

    row1 = values[0] if len(values) >= 1 else []
    a1 = _cell(row1, 0)
    b1 = _cell(row1, 1)

    if not a1 and not b1:
        ws.update(
            "A1:B3",
            [
                CONFIG_HEADERS,
                [CONFIG_KEY_SIGNUP, "open"],
                [CONFIG_KEY_LIMIT, ""],
            ],
        )
        return ws

    if [a1, b1] != CONFIG_HEADERS:
        raise RuntimeError(
            f"'{COOP_CONFIG_SHEET}' hat nicht die erwartete Struktur in A1:B1. "
            "Der Bot schreibt aus Sicherheitsgründen nichts in dieses Sheet."
        )

    # Fehlende Standardzeilen gezielt ergaenzen, ohne vorhandene Werte zu ueberschreiben.
    key_map = {}
    all_values = ws.get("A:B") or []
    occupied_rows = set()
    for index, row in enumerate(all_values[1:], start=2):
        if any(_cell(row, i) for i in range(2)):
            occupied_rows.add(index)
        key = _cell(row, 0)
        if key:
            key_map[key.lower()] = index

    def next_free_config_row():
        row_index = 2
        while row_index in occupied_rows:
            row_index += 1
        occupied_rows.add(row_index)
        return row_index

    updates = []
    if CONFIG_KEY_SIGNUP.lower() not in key_map:
        target_row = next_free_config_row()
        updates.append({"range": f"A{target_row}:B{target_row}", "values": [[CONFIG_KEY_SIGNUP, "open"]]})
    if CONFIG_KEY_LIMIT.lower() not in key_map:
        target_row = next_free_config_row()
        updates.append({"range": f"A{target_row}:B{target_row}", "values": [[CONFIG_KEY_LIMIT, ""]]})

    if updates:
        ws.batch_update(updates)

    return ws


def _config_row_for_key(ws, key: str):
    values = ws.get("A:B") or []
    target = key.strip().lower()
    for row_index, row in enumerate(values[1:], start=2):
        if _cell(row, 0).lower() == target:
            return row_index, _cell(row, 1)
    return None, ""


def get_coop_rows():
    ws = ensure_coop_sheet_structure()
    return ws, _read_signup_rows(ws)


def get_coop_config() -> dict:
    ws = ensure_config_sheet_structure()

    _, state_value = _config_row_for_key(ws, CONFIG_KEY_SIGNUP)
    _, limit_value = _config_row_for_key(ws, CONFIG_KEY_LIMIT)

    state = (state_value or "open").strip().lower()
    if state not in {"open", "closed"}:
        state = "closed"

    max_teams = None
    raw_limit = (limit_value or "").strip()
    if raw_limit:
        try:
            parsed = int(raw_limit)
            if parsed > 0:
                max_teams = parsed
        except ValueError:
            max_teams = None

    return {
        "open": state == "open",
        "state": state,
        "max_teams": max_teams,
    }


def set_coop_open_state(is_open: bool):
    with _COOP_WRITE_LOCK:
        ws = ensure_config_sheet_structure()
        row_index, _ = _config_row_for_key(ws, CONFIG_KEY_SIGNUP)
        if row_index is None:
            raise RuntimeError("Config-Eintrag 'Anmeldung' fehlt.")
        ws.update(f"B{row_index}", [["open" if is_open else "closed"]])


def set_coop_team_limit(limit: int | None):
    with _COOP_WRITE_LOCK:
        ws = ensure_config_sheet_structure()
        row_index, _ = _config_row_for_key(ws, CONFIG_KEY_LIMIT)
        if row_index is None:
            raise RuntimeError("Config-Eintrag 'Max Teams' fehlt.")
        ws.update(f"B{row_index}", [["" if limit is None or limit <= 0 else str(limit)]])


def coop_status_counts(rows=None) -> dict:
    if rows is None:
        _, rows = get_coop_rows()

    counts = {
        "offen": 0,
        "bestätigt": 0,
        "abgelehnt": 0,
        "zurückgezogen": 0,
        "entfernt": 0,
    }

    for row in rows[1:]:
        status = _cell(row, 5).lower()
        if status in counts:
            counts[status] += 1

    counts["reserviert"] = counts["offen"] + counts["bestätigt"]
    return counts


def _row_member_ids(row) -> set[int]:
    ids = set()
    for idx in (9, 10):
        raw = _cell(row, idx)
        if raw.isdigit():
            ids.add(int(raw))
    return ids


def _row_member_names(row) -> set[str]:
    return {
        normalize_name(_cell(row, 1)),
        normalize_name(_cell(row, 2)),
    } - {""}


def _row_matches_member(row, member_id: int, names: list[str] | None = None) -> bool:
    ids = _row_member_ids(row)
    if member_id > 0 and member_id in ids:
        return True

    # Wenn Discord-IDs vorhanden sind, sind diese verbindlich. Namensfallback
    # nur fuer alte/handgeschriebene Datensaetze ohne IDs.
    if ids:
        return False

    target_names = {normalize_name(v) for v in (names or []) if v}
    target_names.discard("")
    return bool(target_names and (_row_member_names(row) & target_names))


def find_active_team_for_member(member_id: int, names: list[str] | None = None):
    ws, rows = get_coop_rows()

    for row_index, row in enumerate(rows[1:], start=2):
        status = _cell(row, 5).lower()
        if status not in ACTIVE_STATUSES:
            continue
        if _row_matches_member(row, member_id, names):
            return ws, row_index, row

    return ws, None, None


def find_pending_invite_for_member(member_id: int, names: list[str] | None = None):
    ws, rows = get_coop_rows()
    target_names = {normalize_name(v) for v in (names or []) if v}
    target_names.discard("")

    for row_index, row in enumerate(rows[1:], start=2):
        if _cell(row, 5).lower() != "offen":
            continue

        player2_id = _cell(row, 10)
        if player2_id.isdigit():
            if int(player2_id) == member_id:
                return ws, row_index, row
            continue

        # Nur Legacy-Fallback, wenn K leer ist.
        if target_names and normalize_name(_cell(row, 2)) in target_names:
            return ws, row_index, row

    return ws, None, None


def get_runner_mapping() -> dict[str, str]:
    try:
        ws = get_runner_ws_local()
        rows = ws.get_all_values()

        mapping = {}
        for row in rows:
            player_name = _cell(row, 0)
            twitch_value = _cell(row, 1)
            if not player_name or not twitch_value:
                continue

            key = normalize_name(player_name)
            twitch = normalize_twitch(twitch_value)
            if key and twitch:
                mapping[key] = twitch

        return mapping
    except Exception as exc:
        print(f"[COOP] Runner-Twitchmapping konnte nicht geladen werden: {exc}")
        return {}


def get_runner_twitch_for_names(names: list[str]) -> str:
    mapping = get_runner_mapping()
    for name in names:
        value = mapping.get(normalize_name(name))
        if value:
            return value
    return ""


def ensure_runner_entry_if_missing(player_name: str, twitch: str):
    twitch = normalize_twitch(twitch)
    if not player_name or not twitch:
        return

    ws = get_runner_ws_local()
    rows = ws.get_all_values()
    target = normalize_name(player_name)

    for row_index, row in enumerate(rows, start=1):
        existing_name = _cell(row, 0)
        if normalize_name(existing_name) != target:
            continue

        if not _cell(row, 1):
            ws.update(f"B{row_index}", [[twitch]])
        return

    # Runner hat keine Mischkonfiguration rechts daneben; trotzdem gezielt A:B schreiben.
    new_row = max(len(rows) + 1, 2)
    ws.update(f"A{new_row}:B{new_row}", [[player_name, twitch]])


def validate_new_team(
    creator_id: int,
    creator_names: list[str],
    partner_id: int,
    partner_names: list[str],
):
    config = get_coop_config()
    _, rows = get_coop_rows()

    if not config["open"]:
        raise RuntimeError("Die Anmeldung zur Coop League ist aktuell geschlossen.")

    _, row1, _ = find_active_team_for_member(creator_id, creator_names)
    if row1 is not None:
        raise RuntimeError("Du bist bereits einem offenen oder bestätigten Coop-Team zugeordnet.")

    if partner_id > 0:
        _, row2, _ = find_active_team_for_member(partner_id, partner_names)
        if row2 is not None:
            raise RuntimeError("Dein ausgewählter Mitspieler ist bereits einem Coop-Team zugeordnet.")

    counts = coop_status_counts(rows)
    max_teams = config["max_teams"]
    if max_teams is not None and counts["reserviert"] >= max_teams:
        raise RuntimeError(
            f"Die Coop League ist voll. Aktuell sind {counts['reserviert']} "
            f"von {max_teams} Teamplätzen reserviert."
        )

    return {"config": config, "counts": counts}


def _next_free_signup_row(ws) -> int:
    rows = _read_signup_rows(ws)

    # Vorhandene echte Leerzeilen in A:K duerfen wiederverwendet werden.
    for row_index, row in enumerate(rows[1:], start=2):
        if not any(_cell(row, i) for i in range(11)):
            return row_index

    return max(len(rows) + 1, 2)


def create_pending_team(
    team_name: str,
    creator_name: str,
    partner_name: str,
    creator_twitch: str,
    partner_twitch: str,
    creator_id: int,
    partner_id: int,
):
    team_name = (team_name or "").strip()
    creator_name = (creator_name or "").strip()
    partner_name = (partner_name or "").strip()
    creator_twitch = normalize_twitch(creator_twitch)
    partner_twitch = normalize_twitch(partner_twitch)

    if not team_name:
        raise ValueError("Bitte einen Teamnamen angeben.")
    if not creator_name or not partner_name:
        raise ValueError("Beide Spielernamen müssen vorhanden sein.")
    if creator_id <= 0 or partner_id <= 0:
        raise ValueError("Die Discord-IDs beider Spieler konnten nicht ermittelt werden.")
    if creator_id == partner_id:
        raise ValueError("Du kannst dich nicht selbst als Coop-Partner auswählen.")
    if not creator_twitch:
        raise ValueError("Bitte deinen Twitchkanal angeben.")
    if not partner_twitch:
        raise ValueError("Bitte den Twitchkanal deines Mitspielers angeben.")

    # Validierung und Write muessen atomar gegen parallele Anmeldungen laufen.
    with _COOP_WRITE_LOCK:
        validate_new_team(
            creator_id,
            [creator_name],
            partner_id,
            [partner_name],
        )

        ws = ensure_coop_sheet_structure()
        created = now_str()
        row_index = _next_free_signup_row(ws)

        payload = [
            team_name,
            creator_name,
            partner_name,
            creator_twitch,
            partner_twitch,
            "offen",
            created,
            "",
            creator_name,
            str(creator_id),
            str(partner_id),
        ]

        # Kein append_row(): ausschliesslich die exakt vorgesehene Range A:K.
        ws.update(
            f"A{row_index}:K{row_index}",
            [payload],
            value_input_option="USER_ENTERED",
        )

        # Direkt zuruecklesen. Wenn das nicht exakt stimmt, nicht so tun als sei
        # eine Einladung erfolgreich angelegt worden.
        verify = ws.get(f"A{row_index}:K{row_index}")
        verify_row = verify[0] if verify else []
        if (
            _cell(verify_row, 0) != team_name
            or _cell(verify_row, 9) != str(creator_id)
            or _cell(verify_row, 10) != str(partner_id)
            or _cell(verify_row, 5).lower() != "offen"
        ):
            raise RuntimeError("Die Coop-Anmeldung konnte nach dem Schreiben nicht verifiziert werden.")

    return {
        "row": row_index,
        "team_name": team_name,
        "player1": creator_name,
        "player2": partner_name,
        "twitch1": creator_twitch,
        "twitch2": partner_twitch,
        "status": "offen",
        "created": created,
    }


def confirm_pending_team(member_id: int, names: list[str]):
    with _COOP_WRITE_LOCK:
        ws, row_index, row = find_pending_invite_for_member(member_id, names)
        if row_index is None:
            raise RuntimeError("Für dich liegt keine offene Coop-Einladung vor.")

        # Vor Write nochmal live lesen.
        live = ws.get(f"A{row_index}:K{row_index}")
        row = live[0] if live else []
        if _cell(row, 5).lower() != "offen":
            raise RuntimeError("Diese Coop-Einladung ist nicht mehr offen.")
        if _cell(row, 10) != str(member_id):
            raise RuntimeError("Diese Coop-Einladung gehört nicht zu deinem Discord-Konto.")

        team_name = _cell(row, 0)
        player1 = _cell(row, 1)
        player2 = _cell(row, 2)
        twitch1 = _cell(row, 3)
        twitch2 = _cell(row, 4)
        confirmed = now_str()

        ws.batch_update(
            [
                {"range": f"F{row_index}", "values": [["bestätigt"]]},
                {"range": f"H{row_index}", "values": [[confirmed]]},
            ]
        )

        check = ws.get(f"F{row_index}:H{row_index}")
        check_row = check[0] if check else []
        if _cell(check_row, 0).lower() != "bestätigt":
            raise RuntimeError("Die Bestätigung konnte nicht verifiziert werden.")

    ensure_runner_entry_if_missing(player1, twitch1)
    ensure_runner_entry_if_missing(player2, twitch2)

    return {
        "row": row_index,
        "team_name": team_name,
        "player1": player1,
        "player2": player2,
        "twitch1": twitch1,
        "twitch2": twitch2,
        "status": "bestätigt",
        "confirmed": confirmed,
        "player1_id": int(_cell(row, 9)) if _cell(row, 9).isdigit() else None,
    }


def decline_pending_team(member_id: int, names: list[str]):
    with _COOP_WRITE_LOCK:
        ws, row_index, row = find_pending_invite_for_member(member_id, names)
        if row_index is None:
            raise RuntimeError("Für dich liegt keine offene Coop-Einladung vor.")

        live = ws.get(f"A{row_index}:K{row_index}")
        row = live[0] if live else []
        if _cell(row, 5).lower() != "offen":
            raise RuntimeError("Diese Coop-Einladung ist nicht mehr offen.")
        if _cell(row, 10) != str(member_id):
            raise RuntimeError("Diese Coop-Einladung gehört nicht zu deinem Discord-Konto.")

        ws.update(f"F{row_index}", [["abgelehnt"]])

    return {
        "team_name": _cell(row, 0),
        "player1": _cell(row, 1),
        "player2": _cell(row, 2),
        "player1_id": int(_cell(row, 9)) if _cell(row, 9).isdigit() else None,
    }


def withdraw_team_for_member(member_id: int, names: list[str]):
    with _COOP_WRITE_LOCK:
        ws, row_index, row = find_active_team_for_member(member_id, names)
        if row_index is None:
            raise RuntimeError("Du hast aktuell keine offene oder bestätigte Coop-Anmeldung.")

        live = ws.get(f"A{row_index}:K{row_index}")
        row = live[0] if live else []
        if _cell(row, 5).lower() not in ACTIVE_STATUSES:
            raise RuntimeError("Diese Coop-Anmeldung ist nicht mehr aktiv.")
        if member_id not in _row_member_ids(row):
            raise RuntimeError("Diese Coop-Anmeldung gehört nicht zu deinem Discord-Konto.")

        ws.update(f"F{row_index}", [["zurückgezogen"]])

    ids = _row_member_ids(row)
    other_ids = [uid for uid in ids if uid != member_id]

    return {
        "team_name": _cell(row, 0),
        "player1": _cell(row, 1),
        "player2": _cell(row, 2),
        "other_ids": other_ids,
    }


def get_member_coop_status(member_id: int, names: list[str]) -> dict:
    _, active_row_index, active_row = find_active_team_for_member(member_id, names)
    _, invite_row_index, invite_row = find_pending_invite_for_member(member_id, names)

    return {
        "active_row_index": active_row_index,
        "active_row": active_row,
        "invite_row_index": invite_row_index,
        "invite_row": invite_row,
    }


def build_coop_status_text(member_id: int, names: list[str]) -> str:
    status = get_member_coop_status(member_id, names)
    row = status["active_row"]

    if row is None:
        return "Du hast aktuell keine Coop-Anmeldung."

    return (
        f"**Team:** {_cell(row, 0)}\n"
        f"**Spieler 1:** {_cell(row, 1)} ({_cell(row, 3) or '-'})\n"
        f"**Spieler 2:** {_cell(row, 2)} ({_cell(row, 4) or '-'})\n"
        f"**Status:** {_cell(row, 5)}\n"
    )


def get_admin_team_rows() -> list[dict]:
    _, rows = get_coop_rows()
    out = []

    for row_index, row in enumerate(rows[1:], start=2):
        status = _cell(row, 5).lower()
        if status not in ACTIVE_STATUSES:
            continue
        out.append(
            {
                "row": row_index,
                "team": _cell(row, 0),
                "p1": _cell(row, 1),
                "p2": _cell(row, 2),
                "status": status,
            }
        )

    return out[:25]


def admin_remove_team(row_index: int):
    with _COOP_WRITE_LOCK:
        ws = ensure_coop_sheet_structure()
        values = ws.get(f"A{row_index}:K{row_index}")
        row = values[0] if values else []
        if not row:
            raise RuntimeError("Teamzeile nicht gefunden.")

        ws.update(f"F{row_index}", [["entfernt"]])

    return {
        "team": _cell(row, 0),
        "p1": _cell(row, 1),
        "p2": _cell(row, 2),
    }


def get_member_names(member: discord.Member) -> list[str]:
    return [
        member.display_name,
        getattr(member, "global_name", None),
        member.name,
        str(member),
    ]


async def try_send_dm(user, text: str) -> bool:
    try:
        await user.send(text)
        return True
    except Exception:
        return False


# =========================================================
# DISCORD UI
# =========================================================

class OwnerView(discord.ui.View):
    def __init__(self, owner_id: int, timeout: float = 1800):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Dieses Menü gehört nicht dir.",
                ephemeral=True,
            )
            return False
        return True


def back_to_season_view(owner_id: int):
    player = get_player_module()
    return player.SeasonSignupMenuView(owner_id=owner_id)


def back_to_player_menu(owner_id: int, member):
    player = get_player_module()
    return player.PlayerMenuView(
        owner_id=owner_id,
        show_admin=player.has_admin_role(member),
    )


def back_to_admin_view(owner_id: int):
    player = get_player_module()
    return player.AdminMenuView(owner_id=owner_id)


class CoopTeamModal(discord.ui.Modal, title="Coop-Team anmelden"):
    team_name = discord.ui.TextInput(
        label="Teamname",
        placeholder="Name eures Coop-Teams",
        required=True,
        max_length=100,
    )

    twitch_self = discord.ui.TextInput(
        label="Dein Twitchkanal",
        placeholder="Username oder twitch.tv/...",
        required=True,
        max_length=200,
    )

    twitch_partner = discord.ui.TextInput(
        label="Twitchkanal Mitspieler",
        placeholder="Username oder twitch.tv/...",
        required=True,
        max_length=200,
    )

    def __init__(
        self,
        creator: discord.Member,
        partner: discord.Member,
        twitch_self_default: str = "",
        twitch_partner_default: str = "",
    ):
        super().__init__()
        self.creator = creator
        self.partner = partner

        if twitch_self_default:
            self.twitch_self.default = twitch_self_default
        if twitch_partner_default:
            self.twitch_partner.default = twitch_partner_default

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            result = await asyncio.to_thread(
                create_pending_team,
                str(self.team_name.value),
                self.creator.display_name.strip(),
                self.partner.display_name.strip(),
                str(self.twitch_self.value),
                str(self.twitch_partner.value),
                self.creator.id,
                self.partner.id,
            )

            dm_text = (
                "🤝 **Coop-League-Einladung**\n\n"
                f"**{result['player1']}** möchte mit dir als Team "
                f"**{result['team_name']}** an der Coop League teilnehmen.\n\n"
                "Die Anmeldung ist erst final, wenn du zustimmst.\n"
                "Öffne **/player → 👥 Coop → Coop-Menü → Einladung prüfen**."
            )

            dm_sent = await try_send_dm(self.partner, dm_text)
            extra = (
                "\n\n✅ Der Mitspieler wurde per DM informiert."
                if dm_sent
                else (
                    "\n\n⚠️ Die DM konnte nicht zugestellt werden. "
                    "Die Einladung liegt trotzdem sicher im Coop-Menü vor."
                )
            )

            await interaction.edit_original_response(
                content=(
                    "✅ Coop-Anmeldung angelegt.\n\n"
                    f"**Team:** {result['team_name']}\n"
                    f"**Spieler 1:** {result['player1']}\n"
                    f"**Spieler 2:** {result['player2']}\n"
                    f"**Status:** offen – Zustimmung von {result['player2']} fehlt."
                    f"{extra}"
                )
            )
        except Exception as exc:
            await interaction.edit_original_response(
                content=f"❌ Coop-Anmeldung konnte nicht angelegt werden: {exc}"
            )


class CoopPartnerSelect(discord.ui.UserSelect):
    def __init__(self, creator: discord.Member, runner_mapping: dict[str, str]):
        self.creator = creator
        self.runner_mapping = runner_mapping
        super().__init__(
            placeholder="Mitspieler auswählen …",
            min_values=1,
            max_values=1,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        partner = self.values[0]

        if partner.id == self.creator.id:
            await interaction.response.send_message(
                "Du kannst dich nicht selbst als Coop-Partner auswählen.",
                ephemeral=True,
            )
            return

        if getattr(partner, "bot", False):
            await interaction.response.send_message(
                "Bots können nicht an der Coop League teilnehmen.",
                ephemeral=True,
            )
            return

        own_twitch = self.runner_mapping.get(normalize_name(self.creator.display_name), "")
        partner_twitch = self.runner_mapping.get(normalize_name(partner.display_name), "")

        await interaction.response.send_modal(
            CoopTeamModal(
                creator=self.creator,
                partner=partner,
                twitch_self_default=own_twitch,
                twitch_partner_default=partner_twitch,
            )
        )


class CoopPartnerSelectView(OwnerView):
    def __init__(
        self,
        owner_id: int,
        creator: discord.Member,
        runner_mapping: dict[str, str],
    ):
        super().__init__(owner_id)
        self.add_item(CoopPartnerSelect(creator, runner_mapping))

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("🤝 Coop League", "Wähle einen Bereich."),
            view=CoopMenuView(owner_id=interaction.user.id),
            content=None,
        )


class CoopInviteDecisionView(OwnerView):
    @discord.ui.button(label="Bestätigen", style=discord.ButtonStyle.success, row=0)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Nur auf dem Server verfügbar.", ephemeral=True)
            return

        await interaction.response.defer()
        try:
            result = await asyncio.to_thread(
                confirm_pending_team,
                member.id,
                get_member_names(member),
            )

            if result.get("player1_id") and interaction.guild:
                creator = interaction.guild.get_member(result["player1_id"])
                if creator:
                    await try_send_dm(
                        creator,
                        (
                            "✅ **Coop-League-Anmeldung bestätigt**\n\n"
                            f"**{result['player2']}** hat eure Anmeldung bestätigt.\n"
                            f"**Team:** {result['team_name']}\n\n"
                            "Euer Team ist damit final angemeldet."
                        ),
                    )

            await interaction.edit_original_response(
                embed=menu_embed(
                    "🤝 Coop League",
                    (
                        "✅ **Anmeldung final bestätigt.**\n\n"
                        f"**Team:** {result['team_name']}\n"
                        f"**Spieler:** {result['player1']} & {result['player2']}"
                    ),
                ),
                view=CoopMenuView(owner_id=interaction.user.id),
                content=None,
            )
        except Exception as exc:
            await interaction.edit_original_response(
                embed=menu_embed("🤝 Coop League", f"Fehler: {exc}"),
                view=CoopMenuView(owner_id=interaction.user.id),
                content=None,
            )

    @discord.ui.button(label="Ablehnen", style=discord.ButtonStyle.danger, row=0)
    async def decline_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Nur auf dem Server verfügbar.", ephemeral=True)
            return

        await interaction.response.defer()
        try:
            result = await asyncio.to_thread(
                decline_pending_team,
                member.id,
                get_member_names(member),
            )

            if result.get("player1_id") and interaction.guild:
                creator = interaction.guild.get_member(result["player1_id"])
                if creator:
                    await try_send_dm(
                        creator,
                        (
                            "❌ **Coop-League-Einladung abgelehnt**\n\n"
                            f"**{result['player2']}** hat die Anmeldung für "
                            f"**{result['team_name']}** abgelehnt."
                        ),
                    )

            await interaction.edit_original_response(
                embed=menu_embed(
                    "🤝 Coop League",
                    f"Die Einladung für **{result['team_name']}** wurde abgelehnt.",
                ),
                view=CoopMenuView(owner_id=interaction.user.id),
                content=None,
            )
        except Exception as exc:
            await interaction.edit_original_response(
                embed=menu_embed("🤝 Coop League", f"Fehler: {exc}"),
                view=CoopMenuView(owner_id=interaction.user.id),
                content=None,
            )


class CoopWithdrawConfirmView(OwnerView):
    @discord.ui.button(label="Ja, zurückziehen", style=discord.ButtonStyle.danger, row=0)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Nur auf dem Server verfügbar.", ephemeral=True)
            return

        await interaction.response.defer()
        try:
            result = await asyncio.to_thread(
                withdraw_team_for_member,
                member.id,
                get_member_names(member),
            )

            if interaction.guild:
                for other_id in result.get("other_ids", []):
                    other = interaction.guild.get_member(other_id)
                    if other:
                        await try_send_dm(
                            other,
                            (
                                "⚠️ **Coop-Anmeldung zurückgezogen**\n\n"
                                f"Die Anmeldung des Teams **{result['team_name']}** "
                                "wurde von deinem Teampartner zurückgezogen."
                            ),
                        )

            await interaction.edit_original_response(
                embed=menu_embed(
                    "🤝 Coop League",
                    f"Die Anmeldung von **{result['team_name']}** wurde zurückgezogen.",
                ),
                view=CoopMenuView(owner_id=interaction.user.id),
                content=None,
            )
        except Exception as exc:
            await interaction.edit_original_response(
                embed=menu_embed("🤝 Coop League", f"Fehler: {exc}"),
                view=CoopMenuView(owner_id=interaction.user.id),
                content=None,
            )

    @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.secondary, row=0)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("🤝 Coop League", "Wähle einen Bereich."),
            view=CoopMenuView(owner_id=interaction.user.id),
            content=None,
        )


class CoopMenuView(OwnerView):
    @discord.ui.button(label="Team anmelden", style=discord.ButtonStyle.success, row=0)
    async def signup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Nur auf dem Server verfügbar.", ephemeral=True)
            return

        await interaction.response.defer()
        try:
            # Nur eigenen Status + Anmeldung offen/Limit vorpruefen.
            await asyncio.to_thread(
                validate_new_team,
                member.id,
                get_member_names(member),
                -1,
                [],
            )
        except Exception as exc:
            await interaction.edit_original_response(
                embed=menu_embed("🤝 Coop League", str(exc)),
                view=CoopMenuView(owner_id=interaction.user.id),
                content=None,
            )
            return

        try:
            runner_mapping = await asyncio.to_thread(get_runner_mapping)
            await interaction.edit_original_response(
                embed=menu_embed(
                    "🤝 Coop League → Team anmelden",
                    (
                        "Wähle deinen Mitspieler aus.\n\n"
                        "Danach werden Teamname und Twitchkanäle abgefragt. "
                        "Vorhandene Twitchdaten aus dem Runner-Sheet werden automatisch vorbelegt."
                    ),
                ),
                view=CoopPartnerSelectView(
                    owner_id=interaction.user.id,
                    creator=member,
                    runner_mapping=runner_mapping,
                ),
                content=None,
            )
        except Exception as exc:
            await interaction.edit_original_response(
                embed=menu_embed("🤝 Coop League", f"Fehler beim Laden: {exc}"),
                view=CoopMenuView(owner_id=interaction.user.id),
                content=None,
            )

    @discord.ui.button(label="Meine Anmeldung", style=discord.ButtonStyle.primary, row=0)
    async def status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Nur auf dem Server verfügbar.", ephemeral=True)
            return

        await interaction.response.defer()
        try:
            status = await asyncio.to_thread(
                get_member_coop_status,
                member.id,
                get_member_names(member),
            )

            invite_row = status["invite_row"]
            active_row = status["active_row"]

            if invite_row is not None and _cell(invite_row, 10) == str(member.id):
                text = (
                    "Du hast eine offene Coop-Einladung:\n\n"
                    f"**Team:** {_cell(invite_row, 0)}\n"
                    f"**Von:** {_cell(invite_row, 1)}\n"
                    f"**Mitspieler:** {_cell(invite_row, 2)}\n\n"
                    "Bitte bestätige oder lehne die Einladung ab."
                )
                await interaction.edit_original_response(
                    embed=menu_embed("🤝 Coop League → Einladung", text),
                    view=CoopInviteDecisionView(owner_id=interaction.user.id),
                    content=None,
                )
                return

            if active_row is None:
                text = "Du hast aktuell keine Coop-Anmeldung."
            else:
                text = (
                    f"**Team:** {_cell(active_row, 0)}\n"
                    f"**Spieler 1:** {_cell(active_row, 1)} ({_cell(active_row, 3) or '-'})\n"
                    f"**Spieler 2:** {_cell(active_row, 2)} ({_cell(active_row, 4) or '-'})\n"
                    f"**Status:** {_cell(active_row, 5)}"
                )

            await interaction.edit_original_response(
                embed=menu_embed("🤝 Coop League → Meine Anmeldung", text),
                view=CoopMenuView(owner_id=interaction.user.id),
                content=None,
            )
        except Exception as exc:
            await interaction.edit_original_response(
                embed=menu_embed("🤝 Coop League", f"Fehler beim Laden: {exc}"),
                view=CoopMenuView(owner_id=interaction.user.id),
                content=None,
            )

    @discord.ui.button(label="Einladung prüfen", style=discord.ButtonStyle.primary, row=1)
    async def invite_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Nur auf dem Server verfügbar.", ephemeral=True)
            return

        await interaction.response.defer()
        try:
            _, row_index, row = await asyncio.to_thread(
                find_pending_invite_for_member,
                member.id,
                get_member_names(member),
            )

            if row_index is None:
                await interaction.edit_original_response(
                    embed=menu_embed(
                        "🤝 Coop League → Einladung",
                        "Für dich liegt aktuell keine offene Einladung vor.",
                    ),
                    view=CoopMenuView(owner_id=interaction.user.id),
                    content=None,
                )
                return

            await interaction.edit_original_response(
                embed=menu_embed(
                    "🤝 Coop League → Einladung",
                    (
                        f"**Team:** {_cell(row, 0)}\n"
                        f"**Spieler 1:** {_cell(row, 1)}\n"
                        f"**Spieler 2:** {_cell(row, 2)}\n\n"
                        "Möchtest du die Teilnahme bestätigen?"
                    ),
                ),
                view=CoopInviteDecisionView(owner_id=interaction.user.id),
                content=None,
            )
        except Exception as exc:
            await interaction.edit_original_response(
                embed=menu_embed("🤝 Coop League", f"Fehler beim Laden: {exc}"),
                view=CoopMenuView(owner_id=interaction.user.id),
                content=None,
            )

    @discord.ui.button(label="Anmeldung zurückziehen", style=discord.ButtonStyle.danger, row=1)
    async def withdraw_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Nur auf dem Server verfügbar.", ephemeral=True)
            return

        await interaction.response.defer()
        try:
            _, row_index, row = await asyncio.to_thread(
                find_active_team_for_member,
                member.id,
                get_member_names(member),
            )

            if row_index is None:
                await interaction.edit_original_response(
                    embed=menu_embed(
                        "🤝 Coop League",
                        "Du hast aktuell keine offene oder bestätigte Coop-Anmeldung.",
                    ),
                    view=CoopMenuView(owner_id=interaction.user.id),
                    content=None,
                )
                return

            await interaction.edit_original_response(
                embed=discord.Embed(
                    title="⚠️ Coop-Anmeldung zurückziehen?",
                    description=(
                        f"**Team:** {_cell(row, 0)}\n\n"
                        "Die Anmeldung des gesamten Teams wird zurückgezogen. Fortfahren?"
                    ),
                    color=discord.Color.red(),
                ),
                view=CoopWithdrawConfirmView(owner_id=interaction.user.id),
                content=None,
            )
        except Exception as exc:
            await interaction.edit_original_response(
                embed=menu_embed("🤝 Coop League", f"Fehler: {exc}"),
                view=CoopMenuView(owner_id=interaction.user.id),
                content=None,
            )

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=2)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("Saisonmeldung", "Wähle einen Bereich."),
            view=back_to_season_view(interaction.user.id),
            content=None,
        )


async def open_coop_menu_from_player(interaction: discord.Interaction):
    member = interaction.user
    if not isinstance(member, discord.Member):
        await interaction.response.send_message(
            "Diese Funktion ist nur auf dem TFL-Server verfügbar.",
            ephemeral=True,
        )
        return

    await interaction.response.defer()
    try:
        config = await asyncio.to_thread(get_coop_config)
        _, rows = await asyncio.to_thread(get_coop_rows)
        counts = coop_status_counts(rows)

        limit_text = str(config["max_teams"]) if config["max_teams"] is not None else "unbegrenzt"
        status = await asyncio.to_thread(
            get_member_coop_status,
            member.id,
            get_member_names(member),
        )

        own_status = "keine Anmeldung"
        if status.get("invite_row") is not None:
            own_status = f"Einladung für **{_cell(status['invite_row'], 0)}** wartet auf dich"
        elif status.get("active_row") is not None:
            own_status = (
                f"**{_cell(status['active_row'], 0)}** "
                f"({_cell(status['active_row'], 5)})"
            )

        text = (
            f"**Anmeldung:** {'offen' if config['open'] else 'geschlossen'}\n"
            f"**Bestätigte Teams:** {counts['bestätigt']}\n"
            f"**Offene Einladungen:** {counts['offen']}\n"
            f"**Reservierte Plätze:** {counts['reserviert']} / {limit_text}\n"
            f"**Dein Status:** {own_status}\n\n"
            "Ein Team ist erst final angemeldet, wenn **beide Spieler zugestimmt** haben."
        )

        await interaction.edit_original_response(
            embed=menu_embed("🤝 Coop League", text),
            view=CoopMenuView(owner_id=interaction.user.id),
            content=None,
        )
    except Exception as exc:
        await interaction.edit_original_response(
            embed=menu_embed("🤝 Coop League", f"Fehler beim Laden: {exc}"),
            view=back_to_season_view(interaction.user.id),
            content=None,
        )


# =========================================================
# ADMINISTRATION
# =========================================================

def player_is_admin(member) -> bool:
    try:
        player = get_player_module()
        return player.has_admin_role(member)
    except Exception:
        return False


class AdminOwnerView(OwnerView):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False

        if not player_is_admin(interaction.user):
            await interaction.response.send_message(
                "⛔ Diese Funktion ist nur für Admins verfügbar.",
                ephemeral=True,
            )
            return False
        return True


class CoopLimitModal(discord.ui.Modal, title="Coop-Teamlimit setzen"):
    limit = discord.ui.TextInput(
        label="Maximale Teams",
        placeholder="z. B. 8 | 0 = unbegrenzt",
        required=True,
        max_length=4,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not player_is_admin(interaction.user):
            await interaction.response.send_message("⛔ Keine Berechtigung.", ephemeral=True)
            return

        raw = str(self.limit.value).strip()
        try:
            value = int(raw)
            if value < 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "Bitte eine ganze Zahl ab 0 eingeben.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            await asyncio.to_thread(set_coop_team_limit, None if value == 0 else value)
            text = "unbegrenzt" if value == 0 else str(value)
            await interaction.edit_original_response(
                content=f"✅ Coop-Teamlimit auf **{text}** gesetzt."
            )
        except Exception as exc:
            await interaction.edit_original_response(
                content=f"❌ Teamlimit konnte nicht gesetzt werden: {exc}"
            )


class CoopAdminRemoveSelect(discord.ui.Select):
    def __init__(self, teams: list[dict]):
        options = [
            discord.SelectOption(
                label=f"{item['team']} ({item['status']})"[:100],
                description=f"{item['p1']} & {item['p2']}"[:100],
                value=str(item["row"]),
            )
            for item in teams[:25]
        ]
        super().__init__(
            placeholder="Team auswählen …",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        if not player_is_admin(interaction.user):
            await interaction.response.send_message("⛔ Keine Berechtigung.", ephemeral=True)
            return

        row_index = int(self.values[0])
        await interaction.response.defer()
        try:
            result = await asyncio.to_thread(admin_remove_team, row_index)
            await interaction.edit_original_response(
                embed=menu_embed(
                    "🟨 Administration → Coop League",
                    (
                        f"Team **{result['team']}** wurde entfernt.\n"
                        f"{result['p1']} & {result['p2']}"
                    ),
                ),
                view=CoopAdminMenuView(owner_id=interaction.user.id),
                content=None,
            )
        except Exception as exc:
            await interaction.edit_original_response(
                embed=menu_embed("🟨 Administration → Coop League", f"Fehler: {exc}"),
                view=CoopAdminMenuView(owner_id=interaction.user.id),
                content=None,
            )


class CoopAdminRemoveView(AdminOwnerView):
    def __init__(self, owner_id: int, teams: list[dict]):
        super().__init__(owner_id)
        if teams:
            self.add_item(CoopAdminRemoveSelect(teams))

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("🟨 Administration → Coop League", "Wähle eine Funktion."),
            view=CoopAdminMenuView(owner_id=interaction.user.id),
            content=None,
        )


class CoopAdminMenuView(AdminOwnerView):
    @discord.ui.button(label="Anmeldung öffnen", style=discord.ButtonStyle.success, row=0)
    async def open_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            await asyncio.to_thread(set_coop_open_state, True)
            await interaction.edit_original_response(
                embed=menu_embed(
                    "🟨 Administration → Coop League",
                    "✅ Die Coop-Anmeldung ist jetzt **offen**.",
                ),
                view=CoopAdminMenuView(owner_id=interaction.user.id),
                content=None,
            )
        except Exception as exc:
            await interaction.edit_original_response(
                embed=menu_embed("🟨 Administration → Coop League", f"Fehler: {exc}"),
                view=CoopAdminMenuView(owner_id=interaction.user.id),
                content=None,
            )

    @discord.ui.button(label="Anmeldung schließen", style=discord.ButtonStyle.danger, row=0)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            await asyncio.to_thread(set_coop_open_state, False)
            await interaction.edit_original_response(
                embed=menu_embed(
                    "🟨 Administration → Coop League",
                    (
                        "🔒 Die Coop-Anmeldung ist jetzt **geschlossen**.\n\n"
                        "Bereits offene Einladungen können weiterhin bestätigt werden."
                    ),
                ),
                view=CoopAdminMenuView(owner_id=interaction.user.id),
                content=None,
            )
        except Exception as exc:
            await interaction.edit_original_response(
                embed=menu_embed("🟨 Administration → Coop League", f"Fehler: {exc}"),
                view=CoopAdminMenuView(owner_id=interaction.user.id),
                content=None,
            )

    @discord.ui.button(label="Teamlimit setzen", style=discord.ButtonStyle.primary, row=1)
    async def limit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CoopLimitModal())

    @discord.ui.button(label="Status / Anmeldungen", style=discord.ButtonStyle.primary, row=1)
    async def status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            config = await asyncio.to_thread(get_coop_config)
            _, rows = await asyncio.to_thread(get_coop_rows)
            counts = coop_status_counts(rows)

            active = []
            for row in rows[1:]:
                status = _cell(row, 5).lower()
                if status in ACTIVE_STATUSES:
                    active.append(
                        f"• **{_cell(row, 0)}** – {_cell(row, 1)} & {_cell(row, 2)} ({status})"
                    )

            limit_text = str(config["max_teams"]) if config["max_teams"] is not None else "unbegrenzt"
            text = (
                f"**Anmeldung:** {'offen' if config['open'] else 'geschlossen'}\n"
                f"**Teamlimit:** {limit_text}\n"
                f"**Bestätigt:** {counts['bestätigt']}\n"
                f"**Offen:** {counts['offen']}\n"
                f"**Reserviert:** {counts['reserviert']}\n\n"
                + ("\n".join(active[:20]) if active else "Keine aktiven Anmeldungen.")
            )

            await interaction.edit_original_response(
                embed=menu_embed("🟨 Administration → Coop League", text),
                view=CoopAdminMenuView(owner_id=interaction.user.id),
                content=None,
            )
        except Exception as exc:
            await interaction.edit_original_response(
                embed=menu_embed("🟨 Administration → Coop League", f"Fehler: {exc}"),
                view=CoopAdminMenuView(owner_id=interaction.user.id),
                content=None,
            )

    @discord.ui.button(label="Team entfernen", style=discord.ButtonStyle.danger, row=2)
    async def remove_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            teams = await asyncio.to_thread(get_admin_team_rows)
            if not teams:
                await interaction.edit_original_response(
                    embed=menu_embed(
                        "🟨 Administration → Coop League",
                        "Keine offenen oder bestätigten Teams vorhanden.",
                    ),
                    view=CoopAdminMenuView(owner_id=interaction.user.id),
                    content=None,
                )
                return

            await interaction.edit_original_response(
                embed=menu_embed(
                    "🟨 Administration → Coop League → Team entfernen",
                    "Wähle das Team aus, das entfernt werden soll.",
                ),
                view=CoopAdminRemoveView(
                    owner_id=interaction.user.id,
                    teams=teams,
                ),
                content=None,
            )
        except Exception as exc:
            await interaction.edit_original_response(
                embed=menu_embed("🟨 Administration → Coop League", f"Fehler: {exc}"),
                view=CoopAdminMenuView(owner_id=interaction.user.id),
                content=None,
            )

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=3)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("🟨 Administration", "Wähle eine Adminfunktion."),
            view=back_to_admin_view(interaction.user.id),
            content=None,
        )


async def open_coop_admin_from_player(interaction: discord.Interaction):
    if not player_is_admin(interaction.user):
        await interaction.response.send_message(
            "⛔ Diese Funktion ist nur für Admins verfügbar.",
            ephemeral=True,
        )
        return

    await interaction.response.defer()
    try:
        config = await asyncio.to_thread(get_coop_config)
        _, rows = await asyncio.to_thread(get_coop_rows)
        counts = coop_status_counts(rows)

        limit_text = str(config["max_teams"]) if config["max_teams"] is not None else "unbegrenzt"
        await interaction.edit_original_response(
            embed=menu_embed(
                "🟨 Administration → Coop League",
                (
                    f"**Anmeldung:** {'offen' if config['open'] else 'geschlossen'}\n"
                    f"**Teamlimit:** {limit_text}\n"
                    f"**Bestätigte Teams:** {counts['bestätigt']}\n"
                    f"**Offene Einladungen:** {counts['offen']}\n"
                    f"**Reservierte Plätze:** {counts['reserviert']}\n\n"
                    f"**Anmeldedaten:** `{COOP_SIGNUP_SHEET}`\n"
                    f"**Konfiguration:** `{COOP_CONFIG_SHEET}`"
                ),
            ),
            view=CoopAdminMenuView(owner_id=interaction.user.id),
            content=None,
        )
    except Exception as exc:
        await interaction.edit_original_response(
            embed=menu_embed(
                "🟨 Administration → Coop League",
                f"Fehler beim Laden: {exc}",
            ),
            view=back_to_admin_view(interaction.user.id),
            content=None,
        )
