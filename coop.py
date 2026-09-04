import asyncio
import os
import re
import sys
from datetime import datetime as dt

import discord
import gspread
import pytz
from oauth2client.service_account import ServiceAccountCredentials


BERLIN_TZ = pytz.timezone("Europe/Berlin")

COOP_SHEET = "coop"
RUNNER_SHEET = "Runner"

CREDS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
SPREADSHEET_TITLE = os.getenv("SPREADSHEET_TITLE", "Season #4 - Spielbetrieb")
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

_COOP_GC = None
_COOP_WB = None
_COOP_WS_CACHE = {}

# Tabellenaufbau:
# A Teamname
# B Spieler 1
# C Spieler 2
# D Twitch Spieler 1
# E Twitch Spieler 2
# F Status
# G Erstellt am
# H Bestätigt am
# I Erstellt von
# J Discord-ID Spieler 1
# K Discord-ID Spieler 2
#
# M1 Anmeldung / M2 open|closed
# N1 Max Teams / N2 Zahl, leer oder 0 = unbegrenzt

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

ACTIVE_STATUSES = {"offen", "bestätigt"}
FINAL_STATUS = "bestätigt"


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
    return row[idx0].strip() if 0 <= idx0 < len(row) else ""


def get_shared_workbook():
    """
    Liefert eine funktionierende Workbook-Verbindung.

    Reihenfolge:
    1. aktive Verbindung aus bot.py
    2. selbstheilende Verbindung aus matchcenter.py
    3. eigene direkte Google-Anmeldung als Fallback

    Damit hängt die Coop League nicht an einem beim Botstart einmalig
    gesetzten SHEETS_ENABLED=False.
    """
    global _COOP_GC, _COOP_WB

    # 1) bot.py nur verwenden, wenn die Verbindung tatsächlich aktiv ist
    module = get_main_bot_module()
    if module is not None:
        wb = getattr(module, "WB", None)
        enabled = getattr(module, "SHEETS_ENABLED", False)
        if enabled and wb is not None:
            return wb

    # 2) MatchCenter besitzt bereits eine Retry-/Recovery-Initialisierung
    matchcenter = sys.modules.get("matchcenter")
    if matchcenter is not None:
        initializer = getattr(matchcenter, "initialize_matchcenter_sheets", None)
        if callable(initializer):
            try:
                initializer(force_retry=True)
            except Exception as e:
                print(f"[COOP] MatchCenter-Sheets-Retry fehlgeschlagen: {e}")

        wb = getattr(matchcenter, "WB", None)
        enabled = getattr(matchcenter, "SHEETS_ENABLED", False)
        if enabled and wb is not None:
            return wb

    # 3) Eigene Verbindung als letzter Fallback
    if _COOP_WB is not None:
        return _COOP_WB

    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
        gc = gspread.authorize(creds)
        wb = gc.open(SPREADSHEET_TITLE)

        _COOP_GC = gc
        _COOP_WB = wb
        print("✅ [COOP] Google Sheets direkt verbunden")
        return wb
    except Exception as e:
        raise RuntimeError(f"Google Sheets nicht verbunden: {e}") from e


def get_cached_ws(sheet_name: str):
    if sheet_name in _COOP_WS_CACHE:
        return _COOP_WS_CACHE[sheet_name]

    wb = get_shared_workbook()
    ws = wb.worksheet(sheet_name)
    _COOP_WS_CACHE[sheet_name] = ws
    return ws


def get_coop_ws():
    return get_cached_ws(COOP_SHEET)


def get_runner_ws_local():
    return get_cached_ws(RUNNER_SHEET)


def ensure_coop_sheet_structure():
    ws = get_coop_ws()
    values = ws.get_all_values()

    first_row = values[0] if values else []

    # Nur wenn A1:K1 komplett leer ist, legen wir unsere Header an.
    if not any(_cell(first_row, i) for i in range(11)):
        ws.update("A1:K1", [COOP_HEADERS])

    # Konfiguration nur in leere Zellen schreiben.
    m1 = ws.acell("M1").value or ""
    m2 = ws.acell("M2").value or ""
    n1 = ws.acell("N1").value or ""

    updates = []

    if not m1.strip():
        updates.append({"range": "M1", "values": [["Anmeldung"]]})

    if not m2.strip():
        updates.append({"range": "M2", "values": [["open"]]})

    if not n1.strip():
        updates.append({"range": "N1", "values": [["Max Teams"]]})

    if updates:
        ws.batch_update(updates)

    return ws


def get_coop_rows():
    ws = ensure_coop_sheet_structure()
    return ws, ws.get_all_values()


def get_coop_config() -> dict:
    ws = ensure_coop_sheet_structure()

    state = (ws.acell("M2").value or "open").strip().lower()
    if state not in {"open", "closed"}:
        state = "closed"

    raw_limit = (ws.acell("N2").value or "").strip()

    max_teams = None
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
    ws = ensure_coop_sheet_structure()
    ws.update("M2", [["open" if is_open else "closed"]])


def set_coop_team_limit(limit: int | None):
    ws = ensure_coop_sheet_structure()

    if limit is None or limit <= 0:
        ws.update("N2", [[""]])
    else:
        ws.update("N2", [[str(limit)]])


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


def find_active_team_for_member(member_id: int, names: list[str] | None = None):
    ws, rows = get_coop_rows()
    target_names = {normalize_name(v) for v in (names or []) if v}
    target_names.discard("")

    for row_index, row in enumerate(rows[1:], start=2):
        status = _cell(row, 5).lower()
        if status not in ACTIVE_STATUSES:
            continue

        if member_id in _row_member_ids(row):
            return ws, row_index, row

        if target_names and (_row_member_names(row) & target_names):
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
        if player2_id.isdigit() and int(player2_id) == member_id:
            return ws, row_index, row

        if not player2_id and normalize_name(_cell(row, 2)) in target_names:
            return ws, row_index, row

    return ws, None, None


def get_runner_mapping() -> dict[str, str]:
    """
    Liest Runner!A:B direkt über dieselbe robuste Workbook-Verbindung.
    """
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
    except Exception as e:
        print(f"[COOP] Runner-Twitchmapping konnte nicht geladen werden: {e}")
        return {}


def get_runner_twitch_for_names(names: list[str]) -> str:
    mapping = get_runner_mapping()
    for name in names:
        value = mapping.get(normalize_name(name))
        if value:
            return value
    return ""


def ensure_runner_entry_if_missing(player_name: str, twitch: str):
    """
    Ergänzt Runner nur, wenn der Spieler fehlt oder sein Twitchfeld leer ist.
    Bestehende Twitchdaten werden bewusst NICHT überschrieben.
    """
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

        existing_twitch = _cell(row, 1)
        if not existing_twitch:
            ws.update(f"B{row_index}", [[twitch]])
        return

    new_row = max(len(rows) + 1, 2)
    ws.update(f"A{new_row}:B{new_row}", [[player_name, twitch]])


def validate_new_team(
    creator_id: int,
    creator_names: list[str],
    partner_id: int,
    partner_names: list[str],
):
    config = get_coop_config()
    ws, rows = get_coop_rows()

    if not config["open"]:
        raise RuntimeError("Die Anmeldung zur Coop League ist aktuell geschlossen.")

    _, row1, _ = find_active_team_for_member(creator_id, creator_names)
    if row1 is not None:
        raise RuntimeError("Du bist bereits einem offenen oder bestätigten Coop-Team zugeordnet.")

    _, row2, _ = find_active_team_for_member(partner_id, partner_names)
    if row2 is not None:
        raise RuntimeError("Dein ausgewählter Mitspieler ist bereits einem Coop-Team zugeordnet.")

    counts = coop_status_counts(rows)
    max_teams = config["max_teams"]

    if max_teams is not None and counts["reserviert"] >= max_teams:
        raise RuntimeError(
            f"Die Coop League ist voll. "
            f"Aktuell sind {counts['reserviert']} von {max_teams} Teamplätzen reserviert."
        )

    return {
        "config": config,
        "counts": counts,
    }


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
    creator_twitch = normalize_twitch(creator_twitch)
    partner_twitch = normalize_twitch(partner_twitch)

    if not team_name:
        raise ValueError("Bitte einen Teamnamen angeben.")
    if not creator_twitch:
        raise ValueError("Bitte deinen Twitchkanal angeben.")
    if not partner_twitch:
        raise ValueError("Bitte den Twitchkanal deines Mitspielers angeben.")

    validate_new_team(
        creator_id,
        [creator_name],
        partner_id,
        [partner_name],
    )

    ws = ensure_coop_sheet_structure()
    created = now_str()

    ws.append_row(
        [
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
        ],
        value_input_option="USER_ENTERED",
    )

    return {
        "team_name": team_name,
        "player1": creator_name,
        "player2": partner_name,
        "twitch1": creator_twitch,
        "twitch2": partner_twitch,
        "status": "offen",
        "created": created,
    }


def confirm_pending_team(member_id: int, names: list[str]):
    ws, row_index, row = find_pending_invite_for_member(member_id, names)

    if row_index is None:
        raise RuntimeError("Für dich liegt keine offene Coop-Einladung vor.")

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

    # Erst bei finaler Bestätigung fehlende Runner-Einträge ergänzen.
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
    ws, row_index, row = find_pending_invite_for_member(member_id, names)

    if row_index is None:
        raise RuntimeError("Für dich liegt keine offene Coop-Einladung vor.")

    ws.update(f"F{row_index}", [["abgelehnt"]])

    return {
        "team_name": _cell(row, 0),
        "player1": _cell(row, 1),
        "player2": _cell(row, 2),
        "player1_id": int(_cell(row, 9)) if _cell(row, 9).isdigit() else None,
    }


def withdraw_team_for_member(member_id: int, names: list[str]):
    ws, row_index, row = find_active_team_for_member(member_id, names)

    if row_index is None:
        raise RuntimeError("Du hast aktuell keine offene oder bestätigte Coop-Anmeldung.")

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
    ws, active_row_index, active_row = find_active_team_for_member(member_id, names)
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

    team_name = _cell(row, 0)
    player1 = _cell(row, 1)
    player2 = _cell(row, 2)
    twitch1 = _cell(row, 3)
    twitch2 = _cell(row, 4)
    state = _cell(row, 5)

    return (
        f"**Team:** {team_name}\n"
        f"**Spieler 1:** {player1} ({twitch1 or '-'})\n"
        f"**Spieler 2:** {player2} ({twitch2 or '-'})\n"
        f"**Status:** {state}\n"
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
    ws = ensure_coop_sheet_structure()
    row = ws.row_values(row_index)

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
                "Bitte öffne auf dem TFL-Server **/player → Saisonmeldung → Coop League** "
                "und bestätige dort die Einladung."
            )

            dm_sent = await try_send_dm(self.partner, dm_text)

            extra = (
                "\n\nDer Mitspieler wurde per DM informiert."
                if dm_sent
                else (
                    "\n\n⚠️ Ich konnte dem Mitspieler keine DM schicken. "
                    "Bitte informiere ihn selbst, dass er die Einladung über "
                    "**/player → Saisonmeldung → Coop League** bestätigen muss."
                )
            )

            await interaction.edit_original_response(
                content=(
                    f"✅ Coop-Anmeldung angelegt.\n\n"
                    f"**Team:** {result['team_name']}\n"
                    f"**Spieler 1:** {result['player1']}\n"
                    f"**Spieler 2:** {result['player2']}\n"
                    f"**Status:** offen – Zustimmung von {result['player2']} fehlt."
                    f"{extra}"
                )
            )

        except Exception as e:
            await interaction.edit_original_response(
                content=f"❌ Coop-Anmeldung konnte nicht angelegt werden: {e}"
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

            if result.get("player1_id"):
                try:
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
                except Exception:
                    pass

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

        except Exception as e:
            await interaction.edit_original_response(
                embed=menu_embed("🤝 Coop League", f"Fehler: {e}"),
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

            if result.get("player1_id"):
                try:
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
                except Exception:
                    pass

            await interaction.edit_original_response(
                embed=menu_embed(
                    "🤝 Coop League",
                    f"Die Einladung für **{result['team_name']}** wurde abgelehnt.",
                ),
                view=CoopMenuView(owner_id=interaction.user.id),
                content=None,
            )

        except Exception as e:
            await interaction.edit_original_response(
                embed=menu_embed("🤝 Coop League", f"Fehler: {e}"),
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

        except Exception as e:
            await interaction.edit_original_response(
                embed=menu_embed("🤝 Coop League", f"Fehler: {e}"),
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
            await asyncio.to_thread(
                validate_new_team,
                member.id,
                get_member_names(member),
                -1,
                [],
            )
        except RuntimeError as e:
            # Bei der Vorprüfung ist Partner -1 absichtlich noch nicht vorhanden.
            # Nur Fehler für Anmeldung/Teamlimit/eigenes Team weitergeben.
            text = str(e)
            if "Mitspieler" not in text:
                await interaction.edit_original_response(
                    embed=menu_embed("🤝 Coop League", text),
                    view=CoopMenuView(owner_id=interaction.user.id),
                    content=None,
                )
                return
        except Exception as e:
            await interaction.edit_original_response(
                embed=menu_embed("🤝 Coop League", f"Fehler beim Laden: {e}"),
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

        except Exception as e:
            await interaction.edit_original_response(
                embed=menu_embed("🤝 Coop League", f"Fehler beim Laden: {e}"),
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

        except Exception as e:
            await interaction.edit_original_response(
                embed=menu_embed("🤝 Coop League", f"Fehler beim Laden: {e}"),
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

        except Exception as e:
            await interaction.edit_original_response(
                embed=menu_embed("🤝 Coop League", f"Fehler beim Laden: {e}"),
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

        except Exception as e:
            await interaction.edit_original_response(
                embed=menu_embed("🤝 Coop League", f"Fehler: {e}"),
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

        limit_text = (
            str(config["max_teams"])
            if config["max_teams"] is not None
            else "unbegrenzt"
        )

        text = (
            f"**Anmeldung:** {'offen' if config['open'] else 'geschlossen'}\n"
            f"**Bestätigte Teams:** {counts['bestätigt']}\n"
            f"**Offene Einladungen:** {counts['offen']}\n"
            f"**Reservierte Plätze:** {counts['reserviert']} / {limit_text}\n\n"
            "Ein Team ist erst final angemeldet, wenn **beide Spieler zugestimmt** haben."
        )

        await interaction.edit_original_response(
            embed=menu_embed("🤝 Coop League", text),
            view=CoopMenuView(owner_id=interaction.user.id),
            content=None,
        )

    except Exception as e:
        await interaction.edit_original_response(
            embed=menu_embed("🤝 Coop League", f"Fehler beim Laden: {e}"),
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
            await asyncio.to_thread(
                set_coop_team_limit,
                None if value == 0 else value,
            )

            text = "unbegrenzt" if value == 0 else str(value)
            await interaction.edit_original_response(
                content=f"✅ Coop-Teamlimit auf **{text}** gesetzt."
            )

        except Exception as e:
            await interaction.edit_original_response(
                content=f"❌ Teamlimit konnte nicht gesetzt werden: {e}"
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

        except Exception as e:
            await interaction.edit_original_response(
                embed=menu_embed(
                    "🟨 Administration → Coop League",
                    f"Fehler: {e}",
                ),
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
        except Exception as e:
            await interaction.edit_original_response(
                embed=menu_embed("🟨 Administration → Coop League", f"Fehler: {e}"),
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
        except Exception as e:
            await interaction.edit_original_response(
                embed=menu_embed("🟨 Administration → Coop League", f"Fehler: {e}"),
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

            limit_text = (
                str(config["max_teams"])
                if config["max_teams"] is not None
                else "unbegrenzt"
            )

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

        except Exception as e:
            await interaction.edit_original_response(
                embed=menu_embed("🟨 Administration → Coop League", f"Fehler: {e}"),
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

        except Exception as e:
            await interaction.edit_original_response(
                embed=menu_embed("🟨 Administration → Coop League", f"Fehler: {e}"),
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

        limit_text = (
            str(config["max_teams"])
            if config["max_teams"] is not None
            else "unbegrenzt"
        )

        await interaction.edit_original_response(
            embed=menu_embed(
                "🟨 Administration → Coop League",
                (
                    f"**Anmeldung:** {'offen' if config['open'] else 'geschlossen'}\n"
                    f"**Teamlimit:** {limit_text}\n"
                    f"**Bestätigte Teams:** {counts['bestätigt']}\n"
                    f"**Offene Einladungen:** {counts['offen']}\n"
                    f"**Reservierte Plätze:** {counts['reserviert']}"
                ),
            ),
            view=CoopAdminMenuView(owner_id=interaction.user.id),
            content=None,
        )

    except Exception as e:
        await interaction.edit_original_response(
            embed=menu_embed(
                "🟨 Administration → Coop League",
                f"Fehler beim Laden: {e}",
            ),
            view=back_to_admin_view(interaction.user.id),
            content=None,
        )
