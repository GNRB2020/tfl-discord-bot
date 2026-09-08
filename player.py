import os
import sys
import asyncio
import re
import unicodedata
import uuid
from datetime import datetime as dt, timedelta

import discord
import pytz
from discord import app_commands
from discord.ext import commands

from sheet_guard import (
    col_values_cached,
    row_values_cached,
    sheet_write_call,
)

import signup
import asnyc
import restinfo
import coop

from plan import PlanMenuView
from asyncplan import open_async_request_from_player
from matchcenter import (
    LeagueResultViewStep1,
    LeagueResultViewStep2,
    CupResultView,
    get_runner_modes,
)

GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0"))

# =========================================================
# STREICHMODUS CONFIG
# =========================================================

DIVISION_CHANNELS = {
    1: 1344118033920168047,
    2: 1344118383859204146,
    3: 1344118470102614036,
    4: 1344118574943572100,
    5: 1389541046874148924,
    6: 1438136009085817023,
}

# Spalte O in den Divisionstabellen 1.DIV bis 6.DIV
# leer = Änderung noch möglich
# "1" = einmalige Änderung bereits genutzt
STREICH_CHANGE_USED_COL = 15

# Config-Sheet:
# K = Division 1
# L = Division 2
# M = Division 3
# N = Division 4
# O = Division 5
# P = Division 6
STREICHMODUS_CONFIG_WORKSHEET_GID = 463142264
STREICHMODUS_MODE_COLUMNS = {
    1: 11,  # K
    2: 12,  # L
    3: 13,  # M
    4: 14,  # N
    5: 15,  # O
    6: 16,  # P
}

PLAYER_PERFORMANCE_VERSION = "player-performance-v4-exit-request"
print(f"[PLAYER] geladen: {PLAYER_PERFORMANCE_VERSION}")

PLAYER_SHEET_CACHE_TTL_SECONDS = int(os.getenv("PLAYER_SHEET_CACHE_TTL_SECONDS", "120"))
PLAYER_MODE_CACHE_TTL_SECONDS = int(os.getenv("PLAYER_MODE_CACHE_TTL_SECONDS", "300"))

BERLIN_TZ = pytz.timezone("Europe/Berlin")
EXIT_REQUEST_ADMIN_CHANNEL_ID = 1277927528706736162
EXIT_REQUEST_SHEET = "AustrittAnfragen"
EXIT_REQUEST_TIMEOUT_DAYS = 5
EXIT_REQUEST_CHECK_INTERVAL_SECONDS = 3600

_PLAYER_WORKSHEET_CACHE_BY_NAME = {}
_PLAYER_WORKSHEET_CACHE_BY_GID = {}


# =========================================================
# UI HELFER
# =========================================================

def menu_embed(title: str, description: str) -> discord.Embed:
    return discord.Embed(
        title=title,
        description=description,
        color=0x00FFCC,
    )


def normalize_name(value: str) -> str:
    """
    Normalisiert Discord-/Sheet-Namen robust.

    Beispiele:
    GNRB, .gnrb, G-N-R-B, G_N_R_B, G N R B -> gnrb
    """
    value = unicodedata.normalize("NFKC", value or "")
    value = value.lower().strip()
    return re.sub(r"[^a-z0-9äöüß]", "", value)


ADMIN_ROLE_NAME = "Admin"


def has_admin_role(member) -> bool:
    return (
        isinstance(member, discord.Member)
        and any(role.name == ADMIN_ROLE_NAME for role in member.roles)
    )


def get_main_bot_module():
    """
    bot.py läuft auf Render als __main__. Ein normales import bot würde den
    Bot ein zweites Mal initialisieren. Daher verwenden wir das bereits
    geladene Hauptmodul.
    """
    for module_name in ("__main__", "bot"):
        module = sys.modules.get(module_name)

        if module is not None and hasattr(module, "client"):
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


# =========================================================
# GOOGLE SHEETS FÜR STREICHMODI
# =========================================================

def get_name_candidates(member: discord.Member) -> list[str]:
    """
    Alle sinnvollen Discord-Namensvarianten für den Vergleich mit Spalte L.
    """
    return [
        member.display_name,
        getattr(member, "global_name", None),
        member.name,
        str(member),
    ]


def get_worksheet_by_gid(workbook, gid: int):
    gid = int(gid)

    if gid in _PLAYER_WORKSHEET_CACHE_BY_GID:
        return _PLAYER_WORKSHEET_CACHE_BY_GID[gid]

    for ws in workbook.worksheets():
        _PLAYER_WORKSHEET_CACHE_BY_GID[int(ws.id)] = ws
        _PLAYER_WORKSHEET_CACHE_BY_NAME[getattr(ws, "title", "")] = ws

    if gid in _PLAYER_WORKSHEET_CACHE_BY_GID:
        return _PLAYER_WORKSHEET_CACHE_BY_GID[gid]

    raise RuntimeError(f"Worksheet mit gid={gid} nicht gefunden.")


def get_player_division_worksheet(div_number: int):
    sheet_name = f"{int(div_number)}.DIV"

    if sheet_name in _PLAYER_WORKSHEET_CACHE_BY_NAME:
        return _PLAYER_WORKSHEET_CACHE_BY_NAME[sheet_name]

    ws = restinfo.WB.worksheet(sheet_name)
    _PLAYER_WORKSHEET_CACHE_BY_NAME[sheet_name] = ws
    return ws


def player_sheet_name(ws, fallback: str = "PlayerSheet") -> str:
    return getattr(ws, "title", fallback)


def player_invalidate_prefixes(ws, fallback: str = "PlayerSheet") -> list[str]:
    sheet_name = player_sheet_name(ws, fallback)
    return [
        f"records:{sheet_name}",
        f"values:{sheet_name}",
        f"row:{sheet_name}:",
        f"col:{sheet_name}:",
        f"cell:{sheet_name}:",
    ]


def get_division_worksheet_for_name_candidates(name_candidates: list[str]):
    """
    Sucht den Spieler in allen Division-Tabs 1.DIV bis 6.DIV in Spalte L.
    Gibt (worksheet, row_index, division_number) zurück.

    row_index ist die echte Google-Sheet-Zeile, also 1-basiert.
    """
    targets = {normalize_name(x) for x in name_candidates if x}
    targets.discard("")

    if not targets:
        return None, None, None

    for div_number in range(1, 7):
        ws = get_player_division_worksheet(div_number)
        values = col_values_cached(
            lambda: ws,
            sheet_name=player_sheet_name(ws, f"{div_number}.DIV"),
            col=12,  # Spalte L
            ttl_seconds=PLAYER_SHEET_CACHE_TTL_SECONDS,
        )

        for idx, cell_value in enumerate(values, start=1):
            if normalize_name(cell_value) in targets:
                return ws, idx, div_number

    return None, None, None


def load_current_streichmodi_for_name_candidates(name_candidates: list[str]) -> tuple[str, str]:
    ws, row_index, div_number = get_division_worksheet_for_name_candidates(name_candidates)

    if ws is None or row_index is None:
        return "", ""

    row = row_values_cached(
        lambda: ws,
        sheet_name=player_sheet_name(ws),
        row=row_index,
        ttl_seconds=PLAYER_SHEET_CACHE_TTL_SECONDS,
    )

    mode_1 = row[12].strip() if len(row) > 12 else ""  # M
    mode_2 = row[13].strip() if len(row) > 13 else ""  # N

    return mode_1, mode_2


def get_division_modes_for_streichmodus(div_number: int) -> list[str]:
    div_number = int(div_number)

    col_index = STREICHMODUS_MODE_COLUMNS.get(div_number)
    if not col_index:
        return []

    ws = get_worksheet_by_gid(
        restinfo.WB,
        STREICHMODUS_CONFIG_WORKSHEET_GID,
    )

    values = col_values_cached(
        lambda: ws,
        sheet_name=player_sheet_name(ws, "StreichmodusConfig"),
        col=col_index,
        ttl_seconds=PLAYER_MODE_CACHE_TTL_SECONDS,
    )

    modes = []
    seen = set()

    ignored_headers = {
        "1. division",
        "2. division",
        "3. division",
        "4. division",
        "5. division",
        "6. division",
        "division 1",
        "division 2",
        "division 3",
        "division 4",
        "division 5",
        "division 6",
        "1.division",
        "2.division",
        "3.division",
        "4.division",
        "5.division",
        "6.division",
        "modus",
        "modis",
        "modes",
    }

    for value in values:
        mode = (value or "").strip()
        if not mode:
            continue

        lowered = mode.lower()
        if lowered in ignored_headers:
            continue

        key = lowered
        if key in seen:
            continue

        seen.add(key)
        modes.append(mode)

    return modes[:25]


def load_streichmodus_state_for_name_candidates(name_candidates: list[str]) -> dict:
    ws, row_index, div_number = get_division_worksheet_for_name_candidates(name_candidates)

    if ws is None or row_index is None or div_number is None:
        return {
            "found": False,
            "ws": None,
            "row_index": None,
            "div_number": None,
            "mode_1": "",
            "mode_2": "",
            "change_used": False,
        }

    row = row_values_cached(
        lambda: ws,
        sheet_name=player_sheet_name(ws),
        row=row_index,
        ttl_seconds=PLAYER_SHEET_CACHE_TTL_SECONDS,
    )

    mode_1 = row[12].strip() if len(row) > 12 else ""  # M
    mode_2 = row[13].strip() if len(row) > 13 else ""  # N
    change_marker = row[14].strip() if len(row) > 14 else ""  # O

    return {
        "found": True,
        "ws": ws,
        "row_index": row_index,
        "div_number": int(div_number),
        "mode_1": mode_1,
        "mode_2": mode_2,
        "change_used": change_marker == "1",
    }


def write_streichmodi_for_name_candidates(
    name_candidates: list[str],
    mode_1: str,
    mode_2: str,
) -> tuple[int, int]:
    """
    Rückwärtskompatible Funktion.
    Schreibt ohne Änderungslogik.
    Wird im neuen Flow nicht mehr direkt verwendet.
    """
    ws, row_index, div_number = get_division_worksheet_for_name_candidates(name_candidates)

    if ws is None or row_index is None or div_number is None:
        normalized = sorted({normalize_name(x) for x in name_candidates if x})
        raise RuntimeError(
            "Kein passender Name in Spalte L der Divisionen 1.DIV bis 6.DIV gefunden. "
            f"Gesucht: {', '.join(normalized) or '-'}"
        )

    reqs = [
        {"range": f"M{row_index}:M{row_index}", "values": [[mode_1]]},
        {"range": f"N{row_index}:N{row_index}", "values": [[mode_2]]},
    ]

    sheet_write_call(
        lambda: ws.batch_update(reqs),
        invalidate_prefixes=player_invalidate_prefixes(ws),
    )

    return row_index, div_number


def write_streichmodi_with_change_limit(
    name_candidates: list[str],
    mode_1: str,
    mode_2: str,
) -> dict:
    state = load_streichmodus_state_for_name_candidates(name_candidates)

    if not state["found"]:
        normalized = sorted({normalize_name(x) for x in name_candidates if x})
        raise RuntimeError(
            "Kein passender Name in Spalte L der Divisionen 1.DIV bis 6.DIV gefunden. "
            f"Gesucht: {', '.join(normalized) or '-'}"
        )

    ws = state["ws"]
    row_index = state["row_index"]
    div_number = state["div_number"]

    old_mode_1 = state["mode_1"]
    old_mode_2 = state["mode_2"]
    change_used = state["change_used"]

    old_has_both = bool(old_mode_1 and old_mode_2)
    changed = (old_mode_1 != mode_1) or (old_mode_2 != mode_2)

    if old_has_both and changed and change_used:
        raise RuntimeError(
            "Du hast deine einmalige Änderung der Streichmodi für diese Saison bereits genutzt."
        )

    reqs = [
        {"range": f"M{row_index}:M{row_index}", "values": [[mode_1]]},
        {"range": f"N{row_index}:N{row_index}", "values": [[mode_2]]},
    ]

    notify_change = False

    if old_has_both and changed:
        reqs.append(
            {
                "range": f"O{row_index}:O{row_index}",
                "values": [["1"]],
            }
        )
        notify_change = True

    sheet_write_call(
        lambda: ws.batch_update(reqs),
        invalidate_prefixes=player_invalidate_prefixes(ws),
    )

    return {
        "row_index": row_index,
        "div_number": div_number,
        "old_mode_1": old_mode_1,
        "old_mode_2": old_mode_2,
        "new_mode_1": mode_1,
        "new_mode_2": mode_2,
        "changed": changed,
        "notify_change": notify_change,
    }


# =========================================================
# QUALI INFO
# =========================================================

async def build_quali_info_text(member: discord.Member, quali_number: int) -> str:
    runner_name = member.display_name.strip()

    ws = await asyncio.to_thread(asnyc.get_quali_worksheet)

    total_played, rank = await asyncio.to_thread(
        asnyc.get_quali_stats_for_runner,
        ws,
        runner_name,
        quali_number,
    )

    if rank is None:
        return (
            f"Bereits gespielt: **{total_played}**\n"
            f"Du hast Quali {quali_number} aktuell noch nicht abgeschlossen."
        )

    return (
        f"Bereits gespielt: **{total_played}**\n"
        f"Dein aktueller Platz: **{rank}/{total_played}**"
    )


async def build_quali_overall_text(member: discord.Member) -> str:
    runner_name = member.display_name.strip()

    ws = await asyncio.to_thread(asnyc.get_quali_worksheet)

    total_completed, rank = await asyncio.to_thread(
        asnyc.get_overall_stats_for_runner,
        ws,
        runner_name,
    )

    if rank is None:
        return (
            f"Beide Qualis abgeschlossen: **{total_completed}**\n"
            f"Du bist aktuell noch nicht im Gesamtstand, weil dir mindestens eine Quali fehlt."
        )

    return (
        f"Beide Qualis abgeschlossen: **{total_completed}**\n"
        f"Dein aktueller Platz: **{rank}/{total_completed}**"
    )


# =========================================================
# BASIS
# =========================================================

class PlayerBaseView(discord.ui.View):
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


class PlaceholderView(PlayerBaseView):
    def __init__(self, owner_id: int, back_view: discord.ui.View, back_embed: discord.Embed):
        super().__init__(owner_id)
        self.back_view = back_view
        self.back_embed = back_embed

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=0)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=self.back_embed,
            view=self.back_view,
            content=None,
        )


# =========================================================
# ERGEBNIS WRAPPER
# =========================================================

class BackToResultMenuFromLeagueStep1Button(discord.ui.Button):
    def __init__(self):
        super().__init__(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=4)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=menu_embed(" Ergebnis melden", "Wähle einen Bereich."),
            view=ResultMenuView(owner_id=interaction.user.id),
            content=None,
        )


class BackToResultMenuFromLeagueStep2Button(discord.ui.Button):
    def __init__(self):
        super().__init__(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=2)

    async def callback(self, interaction: discord.Interaction):
        view = PlayerLeagueResultViewStep1(author_id=interaction.user.id)
        view.state.kind = "Ergebnis League"

        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view,
            embed=None,
        )


class BackToResultMenuFromCupButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=3)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=menu_embed(" Ergebnis melden", "Wähle einen Bereich."),
            view=ResultMenuView(owner_id=interaction.user.id),
            content=None,
        )


class PlayerLeagueResultContinueButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Weiter", style=discord.ButtonStyle.primary, row=4)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, PlayerLeagueResultViewStep1):
            return

        s = view.state

        if not all([s.division, s.match_row_index, s.match_label, s.player1, s.player2]):
            await interaction.response.send_message(
                "Bitte zuerst Division, Heimrecht und Spiel auswählen.",
                ephemeral=True,
            )
            return

        next_view = PlayerLeagueResultViewStep2(
            author_id=interaction.user.id,
            state=s.clone(),
        )

        await interaction.response.edit_message(
            content=next_view.render_summary(),
            view=next_view,
            embed=None,
        )


class PlayerLeagueResultViewStep1(LeagueResultViewStep1):
    def __init__(self, author_id: int):
        super().__init__(cog=None, author_id=author_id)

        old_back = None
        old_continue = None

        for item in list(self.children):
            if isinstance(item, discord.ui.Button) and item.label == "Zurück":
                old_back = item
            elif isinstance(item, discord.ui.Button) and item.label == "Weiter":
                old_continue = item

        if old_back is not None:
            self.remove_item(old_back)

        if old_continue is not None:
            self.remove_item(old_continue)

        self.add_item(PlayerLeagueResultContinueButton())
        self.add_item(BackToResultMenuFromLeagueStep1Button())


class PlayerLeagueResultViewStep2(LeagueResultViewStep2):
    def __init__(self, author_id: int, state):
        super().__init__(cog=None, author_id=author_id, state=state)

        old_back = None

        for item in list(self.children):
            if isinstance(item, discord.ui.Button) and item.label == "Zurück":
                old_back = item
                break

        if old_back is not None:
            self.remove_item(old_back)

        self.add_item(BackToResultMenuFromLeagueStep2Button())


class PlayerCupResultView(CupResultView):
    def __init__(self, author_id: int):
        super().__init__(cog=None, author_id=author_id)

        old_back = None

        for item in list(self.children):
            if isinstance(item, discord.ui.Button) and item.label == "Zurück":
                old_back = item
                break

        if old_back is not None:
            self.remove_item(old_back)

        self.add_item(BackToResultMenuFromCupButton())


# =========================================================
# STREICHMODI SETZEN
# =========================================================

class StreichmodusSelect(discord.ui.Select):
    EMPTY_VALUE = "__none__"

    def __init__(self, slot: int, modes: list[str], selected_value: str | None = None):
        self.slot = slot

        options = []

        if not selected_value:
            options.append(
                discord.SelectOption(
                    label="Bitte wählen",
                    value=self.EMPTY_VALUE,
                    default=True,
                )
            )

        for mode in modes[:25]:
            clean_mode = (mode or "").strip()
            if not clean_mode:
                continue

            options.append(
                discord.SelectOption(
                    label=clean_mode[:100],
                    value=clean_mode[:100],
                    default=(clean_mode == selected_value),
                )
            )

        super().__init__(
            placeholder=f"Streichmodus {slot} wählen …",
            min_values=1,
            max_values=1,
            options=options,
            row=slot - 1,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view

        if not isinstance(view, StreichmodusSettingView):
            return

        selected = self.values[0]

        if selected == self.EMPTY_VALUE:
            selected = ""

        if self.slot == 1:
            view.mode_1 = selected
        else:
            view.mode_2 = selected

        new_view = StreichmodusSettingView(
            owner_id=view.owner_id,
            modes=view.modes,
            mode_1=view.mode_1,
            mode_2=view.mode_2,
            div_number=view.div_number,
            change_used=view.change_used,
        )

        await interaction.response.edit_message(
            embed=new_view.build_embed(),
            view=new_view,
            content=None,
        )


class StreichmodusSettingView(PlayerBaseView):
    def __init__(
        self,
        owner_id: int,
        modes: list[str],
        mode_1: str = "",
        mode_2: str = "",
        div_number: int | None = None,
        change_used: bool = False,
    ):
        super().__init__(owner_id)
        self.modes = modes
        self.mode_1 = mode_1
        self.mode_2 = mode_2
        self.div_number = div_number
        self.change_used = change_used

        self.add_item(StreichmodusSelect(1, self.modes, self.mode_1))
        self.add_item(StreichmodusSelect(2, self.modes, self.mode_2))

    def build_embed(self) -> discord.Embed:
        div_text = f"Division {self.div_number}" if self.div_number else "Division nicht erkannt"

        change_text = (
            "Einmalige Änderung bereits genutzt."
            if self.change_used
            else "Nach der Erstsetzung ist noch genau eine Änderung möglich."
        )

        text = (
            f"**{div_text}**\n\n"
            "Wähle zwei Streichmodi.\n\n"
            f"**Modus 1:** {self.mode_1 or '-'}\n"
            f"**Modus 2:** {self.mode_2 or '-'}\n\n"
            f"{change_text}"
        )

        return menu_embed("⚙️ Einstellungen → Streichmodis setzen", text)

    @discord.ui.button(label="Speichern", style=discord.ButtonStyle.success, row=2)
    async def save_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user

        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Nur auf dem Server verfügbar.", ephemeral=True)
            return

        if not self.mode_1 or not self.mode_2:
            await interaction.response.send_message(
                "Bitte beide Streichmodi auswählen.",
                ephemeral=True,
            )
            return

        if self.mode_1 == self.mode_2:
            await interaction.response.send_message(
                "Bitte zwei unterschiedliche Streichmodi auswählen.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            name_candidates = get_name_candidates(member)

            result = await asyncio.to_thread(
                write_streichmodi_with_change_limit,
                name_candidates,
                self.mode_1,
                self.mode_2,
            )

            div_number = result["div_number"]

            if result["notify_change"]:
                channel_id = DIVISION_CHANNELS.get(div_number)
                channel = interaction.client.get_channel(channel_id) if channel_id else None

                if channel is None and channel_id:
                    try:
                        channel = await interaction.client.fetch_channel(channel_id)
                    except Exception:
                        channel = None

                if channel:
                    await channel.send(
                        f"Spieler {member.display_name} hat seinen Streichmodus "
                        f"von {result['old_mode_1']} / {result['old_mode_2']} "
                        f"auf {result['new_mode_1']} / {result['new_mode_2']} geändert."
                    )

            await interaction.edit_original_response(
                embed=menu_embed(
                    "⚙️ Einstellungen → Streichmodis setzen",
                    (
                        "Streichmodi gespeichert.\n\n"
                        f"**Division:** {div_number}.DIV\n"
                        f"**Modus 1:** {self.mode_1}\n"
                        f"**Modus 2:** {self.mode_2}\n"
                        f"**Sheet-Zeile:** {result['row_index']}"
                    ),
                ),
                view=PlaceholderView(
                    owner_id=interaction.user.id,
                    back_view=SettingsMenuView(owner_id=interaction.user.id),
                    back_embed=menu_embed("⚙️ Einstellungen", "Wähle einen Bereich."),
                ),
                content=None,
            )

        except Exception as e:
            await interaction.edit_original_response(
                embed=menu_embed(
                    "⚙️ Einstellungen → Streichmodis setzen",
                    f"Fehler beim Speichern: {e}",
                ),
                view=self,
                content=None,
            )

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=2)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("⚙️ Einstellungen", "Wähle einen Bereich."),
            view=SettingsMenuView(owner_id=interaction.user.id),
            content=None,
        )


# =========================================================
# LIGA-AUSTRITT
# =========================================================

LEAGUE_ROLE_NORMALIZED = "tryforceleague"
CUP_ROLE_NORMALIZED = "tryforcecup"


def clear_shared_results_db_cache():
    """
    Leert den Results-DB-Cache aus bot.py ohne einen normalen Import von bot.py.
    Ein normales `import bot` würde beim Extension-Setup zu einer doppelten
    Bot-Initialisierung führen können.
    """
    for module_name in ("__main__", "bot"):
        module = sys.modules.get(module_name)
        if module is None:
            continue

        clear_func = getattr(module, "clear_results_db_cache", None)
        if callable(clear_func):
            try:
                clear_func()
            except Exception as e:
                print(f"[PLAYER EXIT] Results-DB-Cache konnte nicht geleert werden: {e}")
            return


def division_role_matches(role_name: str, div_number: int) -> bool:
    """
    Unterstützt u. a.:
    - 1. Division
    - Division 1
    - 1 DIV
    - DIV 1
    """
    normalized = normalize_name(role_name)
    number = str(int(div_number))
    return normalized in {
        f"{number}division",
        f"division{number}",
        f"{number}div",
        f"div{number}",
    }


def get_exit_roles(member: discord.Member, div_number: int) -> list[discord.Role]:
    roles = []

    for role in member.roles:
        normalized = normalize_name(role.name)

        if normalized in {LEAGUE_ROLE_NORMALIZED, CUP_ROLE_NORMALIZED}:
            roles.append(role)
            continue

        if division_role_matches(role.name, div_number):
            roles.append(role)

    # Doppelte Rollen sicher ausschließen
    unique = []
    seen = set()
    for role in roles:
        if role.id in seen:
            continue
        seen.add(role.id)
        unique.append(role)

    return unique


def apply_player_exit_for_name_candidates(name_candidates: list[str]) -> dict:
    """
    Findet die Division über Spalte L und wertet ALLE Ligaspiele des Spielers
    als Niederlage gegen ihn.

    Heimspieler steigt aus  -> 0:2
    Gastspieler steigt aus  -> 2:0

    Der ursprüngliche Modus in Spalte C bleibt bewusst erhalten.
    Spalte G wird auf FF gesetzt und Spalte H mit dem Austritt markiert.
    """
    ws, roster_row_index, div_number = get_division_worksheet_for_name_candidates(name_candidates)

    if ws is None or roster_row_index is None or div_number is None:
        raise RuntimeError("Du wurdest in keiner Division gefunden.")

    roster_row = row_values_cached(
        lambda: ws,
        sheet_name=player_sheet_name(ws),
        row=roster_row_index,
        ttl_seconds=PLAYER_SHEET_CACHE_TTL_SECONDS,
    )

    canonical_name = roster_row[11].strip() if len(roster_row) > 11 else ""
    if not canonical_name:
        canonical_name = next((x.strip() for x in name_candidates if x and x.strip()), "")

    if not canonical_name:
        raise RuntimeError("Spielername konnte nicht eindeutig bestimmt werden.")

    target = normalize_name(canonical_name)
    rows = ws.get_all_values()
    requests = []
    affected_rows = []

    for row_index, row in enumerate(rows[1:], start=2):
        home = row[3].strip() if len(row) > 3 else ""  # D
        away = row[5].strip() if len(row) > 5 else ""  # F

        home_match = bool(home) and normalize_name(home) == target
        away_match = bool(away) and normalize_name(away) == target

        if not home_match and not away_match:
            continue

        result_value = "0:2" if home_match else "2:0"

        requests.extend(
            [
                {"range": f"E{row_index}:E{row_index}", "values": [[result_value]]},
                {"range": f"G{row_index}:G{row_index}", "values": [["FF"]]},
                {
                    "range": f"H{row_index}:H{row_index}",
                    "values": [[f"Austritt: {canonical_name}"]],
                },
            ]
        )
        affected_rows.append(row_index)

    if not affected_rows:
        raise RuntimeError(
            f"Für {canonical_name} wurden in Division {div_number} keine Ligaspiele gefunden."
        )

    sheet_write_call(
        lambda: ws.batch_update(requests),
        invalidate_prefixes=player_invalidate_prefixes(ws),
    )

    # Der Joomla/API-Results-Cache sitzt in bot.py und muss nach dem Batch-Write
    # ebenfalls verworfen werden.
    clear_shared_results_db_cache()

    return {
        "player_name": canonical_name,
        "division": int(div_number),
        "affected_games": len(affected_rows),
        "affected_rows": affected_rows,
    }


async def send_exit_admin_message(client: discord.Client, text: str):
    channel = client.get_channel(EXIT_REQUEST_ADMIN_CHANNEL_ID)

    if channel is None:
        try:
            channel = await client.fetch_channel(EXIT_REQUEST_ADMIN_CHANNEL_ID)
        except Exception as e:
            print(f"[EXIT REQUEST] Adminchannel konnte nicht geladen werden: {e}")
            return False

    try:
        await channel.send(text)
        return True
    except Exception as e:
        print(f"[EXIT REQUEST] Adminnachricht fehlgeschlagen: {e}")
        return False


async def execute_full_player_exit(
    client: discord.Client,
    guild: discord.Guild | None,
    member: discord.Member | None = None,
    fallback_name: str | None = None,
) -> dict:
    """
    Gemeinsame Austrittslogik für:
    - normalen Austrittsbutton des Spielers
    - Antwort "Austreten" auf eine Admin-Anfrage
    - automatischen Austritt nach 5 Tagen ohne Reaktion
    """
    if member is not None:
        name_candidates = get_name_candidates(member)
    elif fallback_name:
        name_candidates = [fallback_name]
    else:
        raise RuntimeError("Spieler konnte nicht bestimmt werden.")

    result = await asyncio.to_thread(
        apply_player_exit_for_name_candidates,
        name_candidates,
    )

    player_name = result["player_name"]
    div_number = result["division"]
    warnings = []

    # Divisionschat informieren
    channel_id = DIVISION_CHANNELS.get(div_number)
    division_channel = guild.get_channel(channel_id) if guild and channel_id else None

    if division_channel is None and channel_id:
        try:
            division_channel = await client.fetch_channel(channel_id)
        except Exception as e:
            warnings.append(f"Divisionschat konnte nicht geladen werden: {e}")
            division_channel = None

    if division_channel is not None:
        try:
            await division_channel.send(
                "🚨 **LIGA-AUSTRITT** 🚨\n\n"
                f"**{player_name} ist ausgestiegen. "
                "Alle seine Spiele werden mit 0:2 gegen ihn gewertet.**"
            )
        except Exception as e:
            warnings.append(f"Divisionsnachricht konnte nicht gesendet werden: {e}")

    # Rollen entfernen
    removed_role_names = []

    if member is not None:
        roles_to_remove = get_exit_roles(member, div_number)
        removed_role_names = [role.name for role in roles_to_remove]

        if roles_to_remove:
            try:
                await member.remove_roles(
                    *roles_to_remove,
                    reason=f"TFL Liga-Austritt von {player_name}",
                )
            except Exception as e:
                warnings.append(f"Rollen konnten nicht vollständig entfernt werden: {e}")
        else:
            warnings.append("Keine passenden TFL-/Cup-/Divisionsrollen gefunden.")
    else:
        warnings.append("Discord-Mitglied nicht gefunden; Rollen konnten nicht entfernt werden.")

    return {
        **result,
        "removed_role_names": removed_role_names,
        "warnings": warnings,
    }




class PlayerExitConfirmView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id=owner_id, timeout=300)
        self.processing = False

    @discord.ui.button(
        label="Ja, Liga verlassen",
        style=discord.ButtonStyle.danger,
        row=0,
    )
    async def confirm_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if self.processing:
            await interaction.response.send_message(
                "Der Austritt wird bereits verarbeitet.",
                ephemeral=True,
            )
            return

        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "Diese Funktion ist nur auf dem TFL-Server verfügbar.",
                ephemeral=True,
            )
            return

        self.processing = True

        # Discord sofort bestätigen, bevor Google Sheets und Rollen bearbeitet werden.
        await interaction.response.defer()

        try:
            result = await execute_full_player_exit(
                client=interaction.client,
                guild=interaction.guild,
                member=member,
            )

            player_name = result["player_name"]
            div_number = result["division"]
            affected_games = result["affected_games"]
            removed_role_names = result["removed_role_names"]
            warning_lines = [f"⚠️ {line}" for line in result["warnings"]]

            details = (
                f"**Division:** {div_number}\n"
                f"**Gewertete Spiele:** {affected_games}\n"
            )

            if removed_role_names:
                details += f"**Entfernte Rollen:** {', '.join(removed_role_names)}\n"

            if warning_lines:
                details += "\n" + "\n".join(warning_lines)

            await interaction.edit_original_response(
                embed=discord.Embed(
                    title="Liga-Austritt bestätigt",
                    description=(
                        f"**{player_name}**, dein Austritt aus der Try Force League ist endgültig.\n\n"
                        f"{details}"
                    ),
                    color=discord.Color.red(),
                ),
                view=None,
                content=None,
            )

        except Exception as e:
            self.processing = False
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title="Liga-Austritt fehlgeschlagen",
                    description=(
                        "Der Austritt wurde nicht vollständig durchgeführt. "
                        "Bitte wende dich an einen Admin.\n\n"
                        f"**Fehler:** {e}"
                    ),
                    color=discord.Color.red(),
                ),
                view=self,
                content=None,
            )

    @discord.ui.button(
        label="Abbrechen",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.edit_message(
            embed=menu_embed("Spielermenü", "Der Liga-Austritt wurde abgebrochen."),
            view=PlayerMenuView(owner_id=interaction.user.id, show_admin=has_admin_role(interaction.user)),
            content=None,
        )


# =========================================================
# ADMIN-AUSTRITTSANFRAGEN
# =========================================================

EXIT_REQUEST_HEADERS = [
    "Request ID",
    "Spieler",
    "Discord ID",
    "Division",
    "Gesendet am",
    "Frist",
    "Status",
    "Erledigt am",
    "DM Channel ID",
    "DM Message ID",
    "Angefordert von",
    "Fehler",
]


def get_exit_request_ws():
    if restinfo.WB is None:
        raise RuntimeError("Google Sheets nicht verbunden.")

    try:
        ws = restinfo.WB.worksheet(EXIT_REQUEST_SHEET)
    except Exception:
        ws = restinfo.WB.add_worksheet(
            title=EXIT_REQUEST_SHEET,
            rows=500,
            cols=12,
        )
        ws.update("A1:L1", [EXIT_REQUEST_HEADERS])

    try:
        first_row = ws.row_values(1)
        if not any((value or "").strip() for value in first_row[:12]):
            ws.update("A1:L1", [EXIT_REQUEST_HEADERS])
    except Exception:
        pass

    return ws


def parse_request_datetime(value: str):
    value = (value or "").strip()
    if not value:
        return None

    try:
        parsed = dt.fromisoformat(value)
        if parsed.tzinfo is None:
            return BERLIN_TZ.localize(parsed)
        return parsed.astimezone(BERLIN_TZ)
    except Exception:
        return None


def get_exit_request_rows():
    ws = get_exit_request_ws()
    return ws, ws.get_all_values()


def find_exit_request_row(request_id: str):
    ws, rows = get_exit_request_rows()

    for row_index, row in enumerate(rows[1:], start=2):
        current_id = row[0].strip() if len(row) > 0 else ""
        if current_id == request_id:
            return ws, row_index, row

    return ws, None, None


def find_pending_exit_request_for_player(discord_id: int):
    ws, rows = get_exit_request_rows()
    target = str(discord_id)

    for row_index, row in enumerate(rows[1:], start=2):
        player_id = row[2].strip() if len(row) > 2 else ""
        status = row[6].strip().lower() if len(row) > 6 else ""

        if player_id == target and status == "offen":
            return ws, row_index, row

    return ws, None, None


def write_exit_request(
    request_id: str,
    player_name: str,
    discord_id: int,
    division: int,
    sent_at,
    deadline,
    dm_channel_id: int,
    dm_message_id: int,
    requested_by: str,
):
    ws = get_exit_request_ws()

    ws.append_row(
        [
            request_id,
            player_name,
            str(discord_id),
            str(division),
            sent_at.isoformat(),
            deadline.isoformat(),
            "offen",
            "",
            str(dm_channel_id),
            str(dm_message_id),
            requested_by,
            "",
        ],
        value_input_option="USER_ENTERED",
    )


def update_exit_request_status(
    request_id: str,
    status: str,
    error_text: str = "",
):
    ws, row_index, row = find_exit_request_row(request_id)

    if row_index is None:
        raise RuntimeError("Austrittsanfrage wurde nicht gefunden.")

    ws.batch_update(
        [
            {"range": f"G{row_index}", "values": [[status]]},
            {"range": f"H{row_index}", "values": [[dt.now(BERLIN_TZ).isoformat()]]},
            {"range": f"L{row_index}", "values": [[error_text]]},
        ]
    )

    return row_index, row


def get_pending_exit_requests() -> list[dict]:
    _, rows = get_exit_request_rows()
    out = []

    for row_index, row in enumerate(rows[1:], start=2):
        status = row[6].strip().lower() if len(row) > 6 else ""
        if status != "offen":
            continue

        player_id = row[2].strip() if len(row) > 2 else ""
        division = row[3].strip() if len(row) > 3 else ""
        dm_channel_id = row[8].strip() if len(row) > 8 else ""
        dm_message_id = row[9].strip() if len(row) > 9 else ""

        if not player_id.isdigit():
            continue

        out.append(
            {
                "row": row_index,
                "request_id": row[0].strip() if len(row) > 0 else "",
                "player_name": row[1].strip() if len(row) > 1 else "",
                "discord_id": int(player_id),
                "division": int(division) if division.isdigit() else None,
                "deadline": parse_request_datetime(row[5] if len(row) > 5 else ""),
                "dm_channel_id": int(dm_channel_id) if dm_channel_id.isdigit() else None,
                "dm_message_id": int(dm_message_id) if dm_message_id.isdigit() else None,
            }
        )

    return out


def list_league_players_by_division(div_number: int) -> list[str]:
    ws = get_player_division_worksheet(div_number)

    values = col_values_cached(
        lambda: ws,
        sheet_name=player_sheet_name(ws, f"{div_number}.DIV"),
        col=12,
        ttl_seconds=PLAYER_SHEET_CACHE_TTL_SECONDS,
    )

    names = []
    seen = set()

    for raw in values[1:]:
        name = (raw or "").strip()
        if not name:
            continue

        key = normalize_name(name)
        if not key or key in seen:
            continue

        seen.add(key)
        names.append(name)

    return names[:25]


async def find_discord_member_for_league_player(
    guild: discord.Guild,
    player_name: str,
) -> discord.Member | None:
    target = normalize_name(player_name)

    for member in guild.members:
        if any(
            normalize_name(candidate or "") == target
            for candidate in get_name_candidates(member)
        ):
            return member

    return None


async def resolve_exit_request_continue(
    interaction: discord.Interaction,
    request_id: str,
    expected_player_id: int,
):
    if interaction.user.id != expected_player_id:
        await interaction.response.send_message(
            "Diese Anfrage ist nicht für dich bestimmt.",
            ephemeral=True,
        )
        return

    await interaction.response.defer()

    try:
        _, row_index, row = await asyncio.to_thread(
            find_exit_request_row,
            request_id,
        )

        if row_index is None:
            raise RuntimeError("Anfrage wurde nicht gefunden.")

        status = row[6].strip().lower() if len(row) > 6 else ""
        if status != "offen":
            await interaction.edit_original_response(
                content="Diese Anfrage wurde bereits bearbeitet.",
                view=None,
            )
            return

        player_name = row[1].strip() if len(row) > 1 else str(interaction.user)

        await asyncio.to_thread(
            update_exit_request_status,
            request_id,
            "weiterspielen",
            "",
        )

        await send_exit_admin_message(
            interaction.client,
            f"{player_name} hat reagiert und wird weiter am Spielbetrieb teilnehmen",
        )

        await interaction.edit_original_response(
            content=(
                "✅ Danke für deine Rückmeldung.\n\n"
                "Du hast bestätigt, dass du **weiter am Spielbetrieb teilnimmst**."
            ),
            view=None,
        )

    except Exception as e:
        await interaction.edit_original_response(
            content=f"❌ Deine Rückmeldung konnte nicht verarbeitet werden: {e}",
            view=None,
        )


async def resolve_exit_request_leave(
    interaction: discord.Interaction,
    request_id: str,
    expected_player_id: int,
):
    if interaction.user.id != expected_player_id:
        await interaction.response.send_message(
            "Diese Anfrage ist nicht für dich bestimmt.",
            ephemeral=True,
        )
        return

    await interaction.response.defer()

    try:
        _, row_index, row = await asyncio.to_thread(
            find_exit_request_row,
            request_id,
        )

        if row_index is None:
            raise RuntimeError("Anfrage wurde nicht gefunden.")

        status = row[6].strip().lower() if len(row) > 6 else ""
        if status != "offen":
            await interaction.edit_original_response(
                content="Diese Anfrage wurde bereits bearbeitet.",
                view=None,
            )
            return

        player_name = row[1].strip() if len(row) > 1 else str(interaction.user)

        guild = interaction.client.get_guild(GUILD_ID)
        member = guild.get_member(expected_player_id) if guild else None

        if member is None and guild is not None:
            try:
                member = await guild.fetch_member(expected_player_id)
            except Exception:
                member = None

        result = await execute_full_player_exit(
            client=interaction.client,
            guild=guild,
            member=member,
            fallback_name=player_name,
        )

        await asyncio.to_thread(
            update_exit_request_status,
            request_id,
            "ausgetreten",
            "\n".join(result["warnings"]),
        )

        await send_exit_admin_message(
            interaction.client,
            f"{result['player_name']} hat reagiert und wird aus dem Spielbetrieb austreten.",
        )

        await interaction.edit_original_response(
            content=(
                "✅ Deine Rückmeldung wurde verarbeitet.\n\n"
                "Du trittst aus dem Spielbetrieb aus. "
                "Deine Ligaspiele wurden entsprechend gewertet."
            ),
            view=None,
        )

    except Exception as e:
        try:
            await asyncio.to_thread(
                update_exit_request_status,
                request_id,
                "fehler",
                str(e),
            )
        except Exception:
            pass

        await interaction.edit_original_response(
            content=f"❌ Der Austritt konnte nicht vollständig verarbeitet werden: {e}",
            view=None,
        )


class ExitRequestDMView(discord.ui.View):
    def __init__(self, request_id: str, player_id: int):
        super().__init__(timeout=None)

        self.request_id = request_id
        self.player_id = player_id

        continue_button = discord.ui.Button(
            label="Weiterspielen",
            style=discord.ButtonStyle.success,
            custom_id=f"exitreq:continue:{request_id}",
        )
        leave_button = discord.ui.Button(
            label="Austreten",
            style=discord.ButtonStyle.danger,
            custom_id=f"exitreq:leave:{request_id}",
        )

        async def continue_callback(interaction: discord.Interaction):
            await resolve_exit_request_continue(
                interaction,
                self.request_id,
                self.player_id,
            )

        async def leave_callback(interaction: discord.Interaction):
            await resolve_exit_request_leave(
                interaction,
                self.request_id,
                self.player_id,
            )

        continue_button.callback = continue_callback
        leave_button.callback = leave_callback

        self.add_item(continue_button)
        self.add_item(leave_button)


class ExitRequestPlayerSelect(discord.ui.Select):
    def __init__(self, division: int, players: list[str]):
        self.division = division

        super().__init__(
            placeholder="Spieler auswählen …",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label=name[:100], value=name[:100])
                for name in players[:25]
            ],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_admin_role(interaction.user):
            await interaction.response.send_message("⛔ Keine Berechtigung.", ephemeral=True)
            return

        player_name = self.values[0]

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="📨 Austrittsanfrage senden",
                description=(
                    f"**Spieler:** {player_name}\n"
                    f"**Division:** {self.division}\n\n"
                    "Soll die 5-Tage-Anfrage jetzt per DM versendet werden?"
                ),
                color=discord.Color.orange(),
            ),
            view=ExitRequestSendConfirmView(
                owner_id=interaction.user.id,
                division=self.division,
                player_name=player_name,
            ),
            content=None,
        )


class ExitRequestPlayerSelectView(AdminOnlyView):
    def __init__(self, owner_id: int, division: int, players: list[str]):
        super().__init__(owner_id)
        self.add_item(ExitRequestPlayerSelect(division, players))

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed(
                "🟨 Administration → Austrittsanfrage",
                "Wähle eine Division.",
            ),
            view=ExitRequestDivisionSelectView(owner_id=interaction.user.id),
            content=None,
        )


class ExitRequestDivisionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Division auswählen …",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label=f"Division {i}", value=str(i))
                for i in range(1, 7)
            ],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_admin_role(interaction.user):
            await interaction.response.send_message("⛔ Keine Berechtigung.", ephemeral=True)
            return

        division = int(self.values[0])
        await interaction.response.defer()

        try:
            players = await asyncio.to_thread(
                list_league_players_by_division,
                division,
            )

            if not players:
                raise RuntimeError(f"In Division {division} wurden keine Spieler gefunden.")

            await interaction.edit_original_response(
                embed=menu_embed(
                    "🟨 Administration → Austrittsanfrage",
                    f"Division {division}: Wähle den Spieler aus.",
                ),
                view=ExitRequestPlayerSelectView(
                    owner_id=interaction.user.id,
                    division=division,
                    players=players,
                ),
                content=None,
            )

        except Exception as e:
            await interaction.edit_original_response(
                embed=menu_embed(
                    "🟨 Administration → Austrittsanfrage",
                    f"Fehler beim Laden der Spieler: {e}",
                ),
                view=ExitRequestDivisionSelectView(owner_id=interaction.user.id),
                content=None,
            )


class ExitRequestDivisionSelectView(AdminOnlyView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)
        self.add_item(ExitRequestDivisionSelect())

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("🟨 Administration", "Wähle eine Adminfunktion."),
            view=AdminMenuView(owner_id=interaction.user.id),
            content=None,
        )


class ExitRequestSendConfirmView(AdminOnlyView):
    def __init__(self, owner_id: int, division: int, player_name: str):
        super().__init__(owner_id)
        self.division = division
        self.player_name = player_name
        self.processing = False

    @discord.ui.button(label="Anfrage senden", style=discord.ButtonStyle.success, row=0)
    async def send_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.processing:
            await interaction.response.send_message(
                "Die Anfrage wird bereits versendet.",
                ephemeral=True,
            )
            return

        self.processing = True
        await interaction.response.defer()

        try:
            if interaction.guild is None:
                raise RuntimeError("Server konnte nicht bestimmt werden.")

            member = await find_discord_member_for_league_player(
                interaction.guild,
                self.player_name,
            )

            if member is None:
                raise RuntimeError(
                    f"Discord-Mitglied für '{self.player_name}' wurde nicht gefunden."
                )

            _, existing_row, _ = await asyncio.to_thread(
                find_pending_exit_request_for_player,
                member.id,
            )

            if existing_row is not None:
                raise RuntimeError(
                    "Für diesen Spieler existiert bereits eine offene Austrittsanfrage."
                )

            request_id = uuid.uuid4().hex
            sent_at = dt.now(BERLIN_TZ)
            deadline = sent_at + timedelta(days=EXIT_REQUEST_TIMEOUT_DAYS)

            dm_channel = member.dm_channel or await member.create_dm()
            message = await dm_channel.send(
                (
                    "Bitte teile uns mit, ob du weiterhin am Spielbetrieb teilnimmst. "
                    "Mit Erhalt dieser Nachricht hast du **5 Tage Zeit**.\n\n"
                    "Bitte wähle eine der beiden Optionen:"
                ),
                view=ExitRequestDMView(
                    request_id=request_id,
                    player_id=member.id,
                ),
            )

            await asyncio.to_thread(
                write_exit_request,
                request_id,
                self.player_name,
                member.id,
                self.division,
                sent_at,
                deadline,
                dm_channel.id,
                message.id,
                interaction.user.display_name,
            )

            interaction.client.add_view(
                ExitRequestDMView(
                    request_id=request_id,
                    player_id=member.id,
                ),
                message_id=message.id,
            )

            await interaction.edit_original_response(
                embed=menu_embed(
                    "🟨 Administration → Austrittsanfrage",
                    (
                        f"✅ Anfrage an **{self.player_name}** wurde versendet.\n\n"
                        f"**Frist:** {deadline.strftime('%d.%m.%Y %H:%M')}\n"
                        "Ohne Reaktion wird der Austritt nach 5 Tagen automatisch durchgeführt."
                    ),
                ),
                view=AdminMenuView(owner_id=interaction.user.id),
                content=None,
            )

        except Exception as e:
            self.processing = False
            await interaction.edit_original_response(
                embed=menu_embed(
                    "🟨 Administration → Austrittsanfrage",
                    f"❌ Anfrage konnte nicht versendet werden: {e}",
                ),
                view=self,
                content=None,
            )

    @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.secondary, row=0)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("🟨 Administration", "Wähle eine Adminfunktion."),
            view=AdminMenuView(owner_id=interaction.user.id),
            content=None,
        )


async def disable_exit_request_dm(bot: commands.Bot, request: dict, content: str):
    channel_id = request.get("dm_channel_id")
    message_id = request.get("dm_message_id")

    if not channel_id or not message_id:
        return

    try:
        channel = bot.get_channel(channel_id)
        if channel is None:
            channel = await bot.fetch_channel(channel_id)

        message = await channel.fetch_message(message_id)
        await message.edit(content=content, view=None)
    except Exception as e:
        print(f"[EXIT REQUEST] DM nach Fristablauf nicht aktualisiert: {e}")


async def process_expired_exit_request(bot: commands.Bot, request: dict):
    request_id = request["request_id"]
    player_name = request["player_name"]
    player_id = request["discord_id"]

    _, row_index, row = await asyncio.to_thread(
        find_exit_request_row,
        request_id,
    )

    if row_index is None:
        return

    status = row[6].strip().lower() if len(row) > 6 else ""
    if status != "offen":
        return

    guild = bot.get_guild(GUILD_ID)
    member = guild.get_member(player_id) if guild else None

    if member is None and guild is not None:
        try:
            member = await guild.fetch_member(player_id)
        except Exception:
            member = None

    try:
        result = await execute_full_player_exit(
            client=bot,
            guild=guild,
            member=member,
            fallback_name=player_name,
        )

        await asyncio.to_thread(
            update_exit_request_status,
            request_id,
            "frist_abgelaufen_austritt",
            "\n".join(result["warnings"]),
        )

        await send_exit_admin_message(
            bot,
            (
                f"{result['player_name']} hat innerhalb von 5 Tagen nicht reagiert "
                "und wird aus dem Spielbetrieb austreten."
            ),
        )

        await disable_exit_request_dm(
            bot,
            request,
            (
                "Die 5-Tage-Frist ist abgelaufen.\n\n"
                "Da keine Rückmeldung eingegangen ist, wurde dein Austritt "
                "aus dem Spielbetrieb automatisch durchgeführt."
            ),
        )

    except Exception as e:
        try:
            await asyncio.to_thread(
                update_exit_request_status,
                request_id,
                "fehler",
                str(e),
            )
        except Exception:
            pass

        await send_exit_admin_message(
            bot,
            (
                f"⚠️ Automatischer Austritt für {player_name} nach Ablauf "
                f"der 5-Tage-Frist ist fehlgeschlagen: {e}"
            ),
        )


async def exit_request_monitor_loop(bot: commands.Bot):
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            pending = await asyncio.to_thread(get_pending_exit_requests)
            now = dt.now(BERLIN_TZ)

            for request in pending:
                deadline = request.get("deadline")
                if deadline is not None and deadline <= now:
                    await process_expired_exit_request(bot, request)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[EXIT REQUEST] Monitorfehler: {e}")

        await asyncio.sleep(EXIT_REQUEST_CHECK_INTERVAL_SECONDS)


async def restore_exit_request_views(bot: commands.Bot):
    try:
        pending = await asyncio.to_thread(get_pending_exit_requests)
        restored = 0

        for request in pending:
            if not request["request_id"] or not request["dm_message_id"]:
                continue

            bot.add_view(
                ExitRequestDMView(
                    request_id=request["request_id"],
                    player_id=request["discord_id"],
                ),
                message_id=request["dm_message_id"],
            )
            restored += 1

        print(f"[EXIT REQUEST] {restored} offene DM-Views wiederhergestellt.")

    except Exception as e:
        print(f"[EXIT REQUEST] Wiederherstellung fehlgeschlagen: {e}")




# =========================================================
# ADMINISTRATION
# =========================================================

class AdminOnlyView(PlayerBaseView):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not await super().interaction_check(interaction):
            return False

        if not has_admin_role(interaction.user):
            await interaction.response.send_message(
                "⛔ Diese Funktion ist nur für Admins verfügbar.",
                ephemeral=True,
            )
            return False

        return True


class AdminSignupResetConfirmView(AdminOnlyView):
    @discord.ui.button(
        label="Ja, Anmeldungen zurücksetzen",
        style=discord.ButtonStyle.danger,
        row=0,
    )
    async def confirm_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.defer()

        try:
            ws = await asyncio.to_thread(signup.get_worksheet)
            count = await asyncio.to_thread(signup.reset_signup_data, ws)

            await interaction.edit_original_response(
                embed=menu_embed(
                    "🟨 Administration → Anmeldung zurücksetzen",
                    f"**{count} Einträge wurden zurückgesetzt.**",
                ),
                view=AdminMenuView(owner_id=interaction.user.id),
                content=None,
            )
        except Exception as e:
            await interaction.edit_original_response(
                embed=menu_embed(
                    "🟨 Administration → Anmeldung zurücksetzen",
                    f"Fehler beim Zurücksetzen: {e}",
                ),
                view=AdminMenuView(owner_id=interaction.user.id),
                content=None,
            )

    @discord.ui.button(
        label="Abbrechen",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.edit_message(
            embed=menu_embed("🟨 Administration", "Wähle eine Adminfunktion."),
            view=AdminMenuView(owner_id=interaction.user.id),
            content=None,
        )


class AdminQualiResetSelect(discord.ui.Select):
    def __init__(self, active_runs: dict):
        options = []

        for user_id, state in active_runs.items():
            runner_name = getattr(state, "runner_name", str(user_id))
            quali_number = getattr(state, "quali_number", "?")

            options.append(
                discord.SelectOption(
                    label=f"{runner_name} – Quali {quali_number}"[:100],
                    value=str(user_id),
                )
            )

        super().__init__(
            placeholder="Laufende Qualifikation auswählen …",
            min_values=1,
            max_values=1,
            options=options[:25],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_admin_role(interaction.user):
            await interaction.response.send_message(
                "⛔ Keine Berechtigung.",
                ephemeral=True,
            )
            return

        cog = interaction.client.get_cog("QualiCog")

        if cog is None:
            await interaction.response.send_message(
                "Qualifikation ist aktuell nicht verfügbar.",
                ephemeral=True,
            )
            return

        target_user_id = int(self.values[0])
        active = cog.active_runs.pop(target_user_id, None)

        if active is None:
            await interaction.response.send_message(
                "Diese Qualifikation läuft nicht mehr.",
                ephemeral=True,
            )
            return

        active.cancelled = True
        cog.stop_state_tasks(active)

        await interaction.response.edit_message(
            embed=menu_embed(
                "🟨 Administration → Qualifikation zurücksetzen",
                f"Die laufende Qualifikation von **{active.runner_name}** wurde zurückgesetzt.",
            ),
            view=AdminMenuView(owner_id=interaction.user.id),
            content=None,
        )


class AdminQualiResetView(AdminOnlyView):
    def __init__(self, owner_id: int, active_runs: dict):
        super().__init__(owner_id)

        if active_runs:
            self.add_item(AdminQualiResetSelect(active_runs))

    @discord.ui.button(
        label="◀ Zurück",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def back_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.edit_message(
            embed=menu_embed("🟨 Administration", "Wähle eine Adminfunktion."),
            view=AdminMenuView(owner_id=interaction.user.id),
            content=None,
        )


class AdminSpielplanDivisionSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Division wählen …",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label=f"Division {i}", value=str(i))
                for i in range(1, 7)
            ],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_admin_role(interaction.user):
            await interaction.response.send_message(
                "⛔ Keine Berechtigung.",
                ephemeral=True,
            )
            return

        div_number = self.values[0]
        await interaction.response.defer()

        try:
            spielplan_read_players = get_main_helper("spielplan_read_players")
            spielplan_build_matches = get_main_helper("spielplan_build_matches")
            spielplan_write = get_main_helper("spielplan_write")
            get_div_ws = get_main_helper("get_div_ws")

            players = await asyncio.to_thread(
                spielplan_read_players,
                div_number,
            )
            rounds = spielplan_build_matches(players)
            ws = get_div_ws(div_number)

            written = await asyncio.to_thread(
                spielplan_write,
                ws,
                rounds,
            )

            await interaction.edit_original_response(
                embed=menu_embed(
                    "🟨 Administration → Spielplan erstellen",
                    (
                        f"**Division {div_number}**\n"
                        f"Spieler: **{len(players)}**\n"
                        f"Geschriebene Spiele: **{written}**"
                    ),
                ),
                view=AdminMenuView(owner_id=interaction.user.id),
                content=None,
            )
        except Exception as e:
            await interaction.edit_original_response(
                embed=menu_embed(
                    "🟨 Administration → Spielplan erstellen",
                    f"Fehler beim Erstellen: {e}",
                ),
                view=AdminMenuView(owner_id=interaction.user.id),
                content=None,
            )


class AdminSpielplanView(AdminOnlyView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)
        self.add_item(AdminSpielplanDivisionSelect())

    @discord.ui.button(
        label="◀ Zurück",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def back_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.edit_message(
            embed=menu_embed("🟨 Administration", "Wähle eine Adminfunktion."),
            view=AdminMenuView(owner_id=interaction.user.id),
            content=None,
        )


class AdminTwitchModal(discord.ui.Modal, title="Twitchmapping setzen"):
    player_name = discord.ui.TextInput(
        label="Spielername",
        placeholder="Name wie im Runner-Sheet",
        required=True,
        max_length=100,
    )

    twitch = discord.ui.TextInput(
        label="Twitchkanal",
        placeholder="Username oder https://twitch.tv/...",
        required=True,
        max_length=200,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not has_admin_role(interaction.user):
            await interaction.response.send_message(
                "⛔ Keine Berechtigung.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            set_runner_twitch = get_main_helper("set_runner_twitch")
            result = await asyncio.to_thread(
                set_runner_twitch,
                str(self.player_name.value),
                str(self.twitch.value),
            )

            action_text = (
                "aktualisiert"
                if result["action"] == "updated"
                else "neu angelegt"
            )

            await interaction.edit_original_response(
                content=(
                    f"✅ Twitchmapping {action_text}.\n"
                    f"**Spieler:** {result['player_name']}\n"
                    f"**Twitch:** {result['twitch']}\n"
                    f"**Runner-Zeile:** {result['row']}"
                )
            )
        except Exception as e:
            await interaction.edit_original_response(
                content=f"❌ Fehler beim Twitchmapping: {e}"
            )


class PlayerTwitchModal(discord.ui.Modal, title="Twitchkanal setzen"):
    twitch = discord.ui.TextInput(
        label="Twitchkanal",
        placeholder="Username oder https://twitch.tv/...",
        required=True,
        max_length=200,
    )

    async def on_submit(self, interaction: discord.Interaction):
        member = interaction.user

        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "Nur auf dem Server verfügbar.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            set_runner_twitch = get_main_helper("set_runner_twitch")
            result = await asyncio.to_thread(
                set_runner_twitch,
                member.display_name.strip(),
                str(self.twitch.value),
            )

            await interaction.edit_original_response(
                content=(
                    "✅ Twitchkanal gespeichert.\n"
                    f"**Spieler:** {result['player_name']}\n"
                    f"**Twitch:** {result['twitch']}\n\n"
                    "Multistreamlinks verwenden ab jetzt diesen Eintrag aus **Runner!B**."
                )
            )
        except Exception as e:
            await interaction.edit_original_response(
                content=f"❌ Twitchkanal konnte nicht gespeichert werden: {e}"
            )


class AdminMenuView(AdminOnlyView):
    @discord.ui.button(
        label="Anmeldung zurücksetzen",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def signup_reset_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="⚠️ Anmeldungen zurücksetzen?",
                description=(
                    "Damit wird die bestehende **/resetsign**-Funktion ausgeführt.\n\n"
                    "Alle Saisonmeldungen werden zurückgesetzt. Fortfahren?"
                ),
                color=discord.Color.orange(),
            ),
            view=AdminSignupResetConfirmView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(
        label="Qualifikation zurücksetzen",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def quali_reset_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        cog = interaction.client.get_cog("QualiCog")
        active_runs = getattr(cog, "active_runs", {}) if cog else {}

        if not active_runs:
            await interaction.response.edit_message(
                embed=menu_embed(
                    "🟨 Administration → Qualifikation zurücksetzen",
                    "Aktuell läuft keine Qualifikation.",
                ),
                view=AdminMenuView(owner_id=interaction.user.id),
                content=None,
            )
            return

        await interaction.response.edit_message(
            embed=menu_embed(
                "🟨 Administration → Qualifikation zurücksetzen",
                "Wähle die laufende Qualifikation aus.",
            ),
            view=AdminQualiResetView(
                owner_id=interaction.user.id,
                active_runs=dict(active_runs),
            ),
            content=None,
        )

    @discord.ui.button(
        label="Spieler Austritt",
        style=discord.ButtonStyle.danger,
        row=1,
    )
    async def player_exit_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        try:
            player_exit_view = get_main_helper("PlayerExitDivisionSelectView")

            await interaction.response.edit_message(
                content="📤 Spieler-Exit starten:\nBitte Division auswählen.",
                embed=None,
                view=player_exit_view(requester=interaction.user),
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Spieler-Austritt konnte nicht geöffnet werden: {e}",
                ephemeral=True,
            )

    @discord.ui.button(
        label="Spielplan erstellen",
        style=discord.ButtonStyle.primary,
        row=1,
    )
    async def spielplan_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.edit_message(
            embed=menu_embed(
                "🟨 Administration → Spielplan erstellen",
                "Wähle eine Division.",
            ),
            view=AdminSpielplanView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(
        label="Twitchmapping",
        style=discord.ButtonStyle.primary,
        row=2,
    )
    async def twitch_mapping_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.send_modal(AdminTwitchModal())

    @discord.ui.button(
        label="Coop League",
        style=discord.ButtonStyle.success,
        row=2,
    )
    async def coop_admin_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await coop.open_coop_admin_from_player(interaction)

    @discord.ui.button(
        label="Austritt Anfrage senden",
        style=discord.ButtonStyle.secondary,
        row=3,
    )
    async def exit_request_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.edit_message(
            embed=menu_embed(
                "🟨 Administration → Austrittsanfrage",
                "Wähle zuerst die Division des Spielers.",
            ),
            view=ExitRequestDivisionSelectView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(
        label="◀ Zurück",
        style=discord.ButtonStyle.secondary,
        row=4,
    )
    async def back_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.edit_message(
            embed=menu_embed("Spielermenü", "Wähle einen Bereich."),
            view=PlayerMenuView(
                owner_id=interaction.user.id,
                show_admin=True,
            ),
            content=None,
        )


class AdminMenuButton(discord.ui.Button):
    def __init__(self):
        # Discord bietet keine frei wählbare gelbe Buttonfarbe.
        # Deshalb gelbes Symbol + neutraler Button.
        super().__init__(
            label="🟨 Administration",
            style=discord.ButtonStyle.secondary,
            row=3,
        )

    async def callback(self, interaction: discord.Interaction):
        if not has_admin_role(interaction.user):
            await interaction.response.send_message(
                "⛔ Diese Funktion ist nur für Admins verfügbar.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            embed=menu_embed(
                "🟨 Administration",
                "Wähle eine Adminfunktion.",
            ),
            view=AdminMenuView(owner_id=interaction.user.id),
            content=None,
        )


# =========================================================
# SAISONMELDUNG
# =========================================================

class SeasonSignupMenuView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="TFL Saison", style=discord.ButtonStyle.primary, row=0)
    async def tfl_signup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if hasattr(signup, "open_signup_from_player"):
            await signup.open_signup_from_player(interaction)
            return

        await interaction.response.send_message(
            "Saisonmeldung ist aktuell nicht verfügbar.",
            ephemeral=True,
        )

    @discord.ui.button(label="Coop League", style=discord.ButtonStyle.success, row=0)
    async def coop_signup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await coop.open_coop_menu_from_player(interaction)

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("Spielermenü", "Wähle einen Bereich."),
            view=PlayerMenuView(
                owner_id=interaction.user.id,
                show_admin=has_admin_role(interaction.user),
            ),
            content=None,
        )


# =========================================================
# HAUPTMENÜ
# =========================================================

class PlayerMenuView(PlayerBaseView):
    def __init__(self, owner_id: int, show_admin: bool = False):
        super().__init__(owner_id)

        if show_admin:
            self.add_item(AdminMenuButton())

    @discord.ui.button(label="ℹ️ Info", style=discord.ButtonStyle.secondary, row=0)
    async def info_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Info", "Wähle einen Bereich."),
            view=InfoMenuView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(label=" Spiel planen", style=discord.ButtonStyle.primary, row=0)
    async def plan_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed(" Spiel planen", "Wähle einen Bereich."),
            view=PlanMenuView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(label=" Ergebnis melden", style=discord.ButtonStyle.success, row=0)
    async def result_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed(" Ergebnis melden", "Wähle einen Bereich."),
            view=ResultMenuView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(label="⚡ Async", style=discord.ButtonStyle.primary, row=1)
    async def async_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("⚡ Async", "Wähle einen Bereich."),
            view=AsyncMenuView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(label=" Qualifikation", style=discord.ButtonStyle.primary, row=1)
    async def qualification_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if hasattr(asnyc, "open_quali_from_player"):
            await asnyc.open_quali_from_player(interaction)
            return

        await interaction.response.send_message(
            "Qualifikation ist aktuell nicht verfügbar.",
            ephemeral=True,
        )

    @discord.ui.button(label=" Saisonmeldung", style=discord.ButtonStyle.primary, row=1)
    async def season_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("Saisonmeldung", "Wähle einen Bereich."),
            view=SeasonSignupMenuView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(label="⚙️ Einstellungen", style=discord.ButtonStyle.secondary, row=2)
    async def settings_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("⚙️ Einstellungen", "Wähle einen Bereich."),
            view=SettingsMenuView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(label="Austritt", style=discord.ButtonStyle.danger, row=2)
    async def exit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user

        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "Diese Funktion ist nur auf dem TFL-Server verfügbar.",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="⚠️ Liga verlassen?",
                description=(
                    "Bist du dir absolut sicher, dass du die Liga verlassen möchtest? "
                    "Wenn du nun bestätigst, ist die Entscheidung final. "
                    "Zudem ist eine Teilnahme an der kommenden Saison damit ausgeschlossen."
                ),
                color=discord.Color.red(),
            ),
            view=PlayerExitConfirmView(owner_id=interaction.user.id),
            content=None,
        )


# =========================================================
# ASYNC MENÜ
# =========================================================

class AsyncMenuView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="Beantragen", style=discord.ButtonStyle.primary, row=0)
    async def beantragen_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_async_request_from_player(interaction)

    @discord.ui.button(label="Spielen", style=discord.ButtonStyle.success, row=0)
    async def spielen_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Discord erwartet innerhalb weniger Sekunden eine Bestätigung der
        # Component-Interaction. Deshalb wird der Klick hier sofort bestätigt,
        # bevor im Async-Modul Google-Sheets-Daten geladen werden.
        await interaction.response.defer()

        if hasattr(asnyc, "open_async_play_from_player"):
            await asnyc.open_async_play_from_player(
                interaction,
                already_deferred=True,
            )
            return

        await interaction.edit_original_response(
            content="Async spielen ist aktuell nicht verfügbar.",
            embed=None,
            view=None,
        )

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("Spielermenü", "Wähle einen Bereich."),
            view=PlayerMenuView(owner_id=interaction.user.id, show_admin=has_admin_role(interaction.user)),
            content=None,
        )


# =========================================================
# ERGEBNIS MENÜ
# =========================================================

class ResultMenuView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="League", style=discord.ButtonStyle.primary, row=0)
    async def league_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PlayerLeagueResultViewStep1(author_id=interaction.user.id)
        view.state.kind = "Ergebnis League"

        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view,
            embed=None,
        )

    @discord.ui.button(label="Cup", style=discord.ButtonStyle.primary, row=0)
    async def cup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PlayerCupResultView(author_id=interaction.user.id)
        view.state.kind = "Ergebnis Cup"

        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view,
            embed=None,
        )

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("Spielermenü", "Wähle einen Bereich."),
            view=PlayerMenuView(owner_id=interaction.user.id, show_admin=has_admin_role(interaction.user)),
            content=None,
        )


# =========================================================
# INFO MENÜ
# =========================================================

class InfoMenuView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="Meldestatus", style=discord.ButtonStyle.primary, row=0)
    async def meldestatus_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Meldestatus", "Wähle einen Bereich."),
            view=MeldestatusView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(label="Qualifikation", style=discord.ButtonStyle.primary, row=0)
    async def qualifikation_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Qualifikation", "Wähle einen Bereich."),
            view=InfoQualifikationView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(label="Restprogramm", style=discord.ButtonStyle.primary, row=1)
    async def restprogramm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Restprogramm", "Wähle einen Bereich."),
            view=RestprogrammView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(label="Streichmodus", style=discord.ButtonStyle.primary, row=1)
    async def streichmodus_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Streichmodus", "Wähle einen Bereich."),
            view=StreichmodusView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(label="Ergebnisse/Tabelle", style=discord.ButtonStyle.primary, row=2)
    async def ergebnisse_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Ergebnisse/Tabelle", "Wähle eine Liga oder den Cup."),
            view=ErgebnisseTabelleView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=3)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("Spielermenü", "Wähle einen Bereich."),
            view=PlayerMenuView(owner_id=interaction.user.id, show_admin=has_admin_role(interaction.user)),
            content=None,
        )


# =========================================================
# MELDESTATUS
# =========================================================

class MeldestatusView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="Meiner", style=discord.ButtonStyle.primary, row=0)
    async def meiner_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user

        if not isinstance(member, discord.Member):
            text = "Nur auf dem Server verfügbar."
        else:
            try:
                text = signup.get_signup_status_text_for_member(member)
            except Exception as e:
                text = f"Fehler beim Abrufen deines Eintrags: {e}"

        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Meldestatus → Meiner", text),
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=MeldestatusView(owner_id=interaction.user.id),
                back_embed=menu_embed("ℹ️ Meldestatus", "Wähle einen Bereich."),
            ),
            content=None,
        )

    @discord.ui.button(label="League", style=discord.ButtonStyle.primary, row=0)
    async def league_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            text = signup.get_league_signup_text()
        except Exception as e:
            text = f"Fehler beim Abrufen der League-Anmeldungen: {e}"

        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Meldestatus → League", text),
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=MeldestatusView(owner_id=interaction.user.id),
                back_embed=menu_embed("ℹ️ Meldestatus", "Wähle einen Bereich."),
            ),
            content=None,
        )

    @discord.ui.button(label="Cup", style=discord.ButtonStyle.primary, row=0)
    async def cup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            text = signup.get_cup_signup_text()
        except Exception as e:
            text = f"Fehler beim Abrufen der Cup-Anmeldungen: {e}"

        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Meldestatus → Cup", text),
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=MeldestatusView(owner_id=interaction.user.id),
                back_embed=menu_embed("ℹ️ Meldestatus", "Wähle einen Bereich."),
            ),
            content=None,
        )

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Info", "Wähle einen Bereich."),
            view=InfoMenuView(owner_id=interaction.user.id),
            content=None,
        )


# =========================================================
# INFO → QUALIFIKATION
# =========================================================

class InfoQualifikationView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="Quali 1", style=discord.ButtonStyle.primary, row=0)
    async def quali1_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user

        await interaction.response.defer()

        if not isinstance(member, discord.Member):
            text = "Nur auf dem Server verfügbar."
        else:
            try:
                text = await build_quali_info_text(member, 1)
            except Exception as e:
                text = f"Fehler bei Quali 1: {e}"

        await interaction.edit_original_response(
            embed=menu_embed("ℹ️ Qualifikation → Quali 1", text),
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=InfoQualifikationView(owner_id=interaction.user.id),
                back_embed=menu_embed("ℹ️ Qualifikation", "Wähle einen Bereich."),
            ),
            content=None,
        )

    @discord.ui.button(label="Quali 2", style=discord.ButtonStyle.primary, row=0)
    async def quali2_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user

        await interaction.response.defer()

        if not isinstance(member, discord.Member):
            text = "Nur auf dem Server verfügbar."
        else:
            try:
                text = await build_quali_info_text(member, 2)
            except Exception as e:
                text = f"Fehler bei Quali 2: {e}"

        await interaction.edit_original_response(
            embed=menu_embed("ℹ️ Qualifikation → Quali 2", text),
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=InfoQualifikationView(owner_id=interaction.user.id),
                back_embed=menu_embed("ℹ️ Qualifikation", "Wähle einen Bereich."),
            ),
            content=None,
        )

    @discord.ui.button(label="Gesamt", style=discord.ButtonStyle.primary, row=0)
    async def gesamt_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user

        await interaction.response.defer()

        if not isinstance(member, discord.Member):
            text = "Nur auf dem Server verfügbar."
        else:
            try:
                text = await build_quali_overall_text(member)
            except Exception as e:
                text = f"Fehler beim Gesamtstand: {e}"

        await interaction.edit_original_response(
            embed=menu_embed("ℹ️ Qualifikation → Gesamt", text),
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=InfoQualifikationView(owner_id=interaction.user.id),
                back_embed=menu_embed("ℹ️ Qualifikation", "Wähle einen Bereich."),
            ),
            content=None,
        )

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Info", "Wähle einen Bereich."),
            view=InfoMenuView(owner_id=interaction.user.id),
            content=None,
        )


# =========================================================
# RESTPROGRAMM
# =========================================================

class RestOtherPlayerSelect(discord.ui.Select):
    def __init__(self, division: str, players: list[str], owner_id: int):
        self.division = division
        self.owner_id = owner_id

        options = [discord.SelectOption(label=p, value=p) for p in players[:25]]

        super().__init__(
            placeholder="Spieler wählen …",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        player = self.values[0]

        try:
            text = restinfo.format_restprogramm_text(self.division, player)
        except Exception as e:
            text = f"Fehler beim Ermitteln des Restprogramms: {e}"

        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Restprogramm → Andere", text),
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=RestOtherDivisionView(owner_id=interaction.user.id),
                back_embed=menu_embed("ℹ️ Restprogramm → Andere", "Wähle eine Division."),
            ),
            content=None,
        )


class RestOtherPlayerView(PlayerBaseView):
    def __init__(self, owner_id: int, division: str, players: list[str]):
        super().__init__(owner_id)
        self.add_item(RestOtherPlayerSelect(division, players, owner_id))

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Restprogramm → Andere", "Wähle eine Division."),
            view=RestOtherDivisionView(owner_id=interaction.user.id),
            content=None,
        )


class RestOtherDivisionSelect(discord.ui.Select):
    def __init__(self, owner_id: int):
        self.owner_id = owner_id

        options = [
            discord.SelectOption(label="Division 1", value="1"),
            discord.SelectOption(label="Division 2", value="2"),
            discord.SelectOption(label="Division 3", value="3"),
            discord.SelectOption(label="Division 4", value="4"),
            discord.SelectOption(label="Division 5", value="5"),
            discord.SelectOption(label="Division 6", value="6"),
        ]

        super().__init__(
            placeholder="Division wählen …",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        div_number = self.values[0]

        try:
            players = restinfo.list_rest_players(div_number)
        except Exception as e:
            await interaction.response.edit_message(
                embed=menu_embed(
                    "ℹ️ Restprogramm → Andere",
                    f"Fehler beim Laden der Spieler für Division {div_number}: {e}",
                ),
                view=RestOtherDivisionView(owner_id=interaction.user.id),
                content=None,
            )
            return

        if not players:
            await interaction.response.edit_message(
                embed=menu_embed(
                    "ℹ️ Restprogramm → Andere",
                    f"Keine Spieler in Division {div_number} für das Restprogramm gefunden.",
                ),
                view=RestOtherDivisionView(owner_id=interaction.user.id),
                content=None,
            )
            return

        await interaction.response.edit_message(
            embed=menu_embed(
                "ℹ️ Restprogramm → Andere",
                f"**Division {div_number}**\nWähle einen Spieler.",
            ),
            view=RestOtherPlayerView(
                owner_id=interaction.user.id,
                division=div_number,
                players=players,
            ),
            content=None,
        )


class RestOtherDivisionView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)
        self.add_item(RestOtherDivisionSelect(owner_id))

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Restprogramm", "Wähle einen Bereich."),
            view=RestprogrammView(owner_id=interaction.user.id),
            content=None,
        )


class RestprogrammView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="Eigenes", style=discord.ButtonStyle.primary, row=0)
    async def eigenes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user

        await interaction.response.defer()

        if not isinstance(member, discord.Member):
            text = "Nur auf dem Server verfügbar."
        else:
            try:
                name_candidates = get_name_candidates(member)
                text = await asyncio.to_thread(
                    restinfo.get_open_restprogramm_text_for_name_candidates,
                    name_candidates,
                )
            except Exception as e:
                text = f"Fehler beim Abrufen deines Restprogramms: {e}"

        await interaction.edit_original_response(
            embed=menu_embed("ℹ️ Restprogramm → Eigenes", text),
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=RestprogrammView(owner_id=interaction.user.id),
                back_embed=menu_embed("ℹ️ Restprogramm", "Wähle einen Bereich."),
            ),
            content=None,
        )

    @discord.ui.button(label="Andere", style=discord.ButtonStyle.primary, row=0)
    async def andere_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Restprogramm → Andere", "Wähle eine Division."),
            view=RestOtherDivisionView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Info", "Wähle einen Bereich."),
            view=InfoMenuView(owner_id=interaction.user.id),
            content=None,
        )


# =========================================================
# STREICHMODUS INFO
# =========================================================

class StreichOtherDivisionSelect(discord.ui.Select):
    def __init__(self, owner_id: int):
        self.owner_id = owner_id

        options = [
            discord.SelectOption(label="Division 1", value="1"),
            discord.SelectOption(label="Division 2", value="2"),
            discord.SelectOption(label="Division 3", value="3"),
            discord.SelectOption(label="Division 4", value="4"),
            discord.SelectOption(label="Division 5", value="5"),
            discord.SelectOption(label="Division 6", value="6"),
        ]

        super().__init__(
            placeholder="Division wählen …",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        div_number = self.values[0]

        try:
            text = restinfo.get_streich_text_for_division(div_number)
        except Exception as e:
            text = f"Fehler beim Abrufen des Streichmodus: {e}"

        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Streichmodus → Andere Divisionen", text),
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=StreichOtherDivisionView(owner_id=interaction.user.id),
                back_embed=menu_embed("ℹ️ Streichmodus → Andere Divisionen", "Wähle eine Division."),
            ),
            content=None,
        )


class StreichOtherDivisionView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)
        self.add_item(StreichOtherDivisionSelect(owner_id))

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Streichmodus", "Wähle einen Bereich."),
            view=StreichmodusView(owner_id=interaction.user.id),
            content=None,
        )


class StreichmodusView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="Eigene Division", style=discord.ButtonStyle.primary, row=0)
    async def eigene_division_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user

        await interaction.response.defer()

        if not isinstance(member, discord.Member):
            text = "Nur auf dem Server verfügbar."
        else:
            try:
                name_candidates = get_name_candidates(member)
                text = await asyncio.to_thread(
                    restinfo.get_own_division_streich_text,
                    name_candidates,
                )
            except Exception as e:
                text = f"Fehler beim Abrufen des Streichmodus: {e}"

        await interaction.edit_original_response(
            embed=menu_embed("ℹ️ Streichmodus → Eigene Division", text),
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=StreichmodusView(owner_id=interaction.user.id),
                back_embed=menu_embed("ℹ️ Streichmodus", "Wähle einen Bereich."),
            ),
            content=None,
        )

    @discord.ui.button(label="Andere Divisionen", style=discord.ButtonStyle.primary, row=0)
    async def andere_divisionen_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Streichmodus → Andere Divisionen", "Wähle eine Division."),
            view=StreichOtherDivisionView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Info", "Wähle einen Bereich."),
            view=InfoMenuView(owner_id=interaction.user.id),
            content=None,
        )


# =========================================================
# ERGEBNISSE / TABELLE
# =========================================================

class ErgebnisseTabelleView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

        self.add_item(discord.ui.Button(
            label="1. Div",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/1-division",
            row=0,
        ))

        self.add_item(discord.ui.Button(
            label="2. Div",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/1-division-2",
            row=0,
        ))

        self.add_item(discord.ui.Button(
            label="3. Div",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/3-division",
            row=0,
        ))

        self.add_item(discord.ui.Button(
            label="4. Div",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/3-division-2",
            row=1,
        ))

        self.add_item(discord.ui.Button(
            label="5. Div",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/3-division-3",
            row=1,
        ))

        self.add_item(discord.ui.Button(
            label="6. Div",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/3-division-4",
            row=1,
        ))

        self.add_item(discord.ui.Button(
            label="Cup",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/cup",
            row=2,
        ))

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=3)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Info", "Wähle einen Bereich."),
            view=InfoMenuView(owner_id=interaction.user.id),
            content=None,
        )


# =========================================================
# EINSTELLUNGEN
# =========================================================

class SettingsMenuView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="Twitch setzen", style=discord.ButtonStyle.primary, row=0)
    async def twitch_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PlayerTwitchModal())

    @discord.ui.button(label="Restream/Commentary/Tracker", style=discord.ButtonStyle.primary, row=0)
    async def restream_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if hasattr(signup, "open_signup_from_player"):
            await signup.open_signup_from_player(interaction)
            return

        await interaction.response.send_message(
            "Restream/Commentary/Tracker ist aktuell nicht verfügbar.",
            ephemeral=True,
        )

    @discord.ui.button(label="Streichmodis setzen", style=discord.ButtonStyle.success, row=1)
    async def streich_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user

        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Nur auf dem Server verfügbar.", ephemeral=True)
            return

        await interaction.response.defer()

        try:
            name_candidates = get_name_candidates(member)

            state = await asyncio.to_thread(
                load_streichmodus_state_for_name_candidates,
                name_candidates,
            )

            if not state["found"]:
                raise RuntimeError("Du wurdest in keiner Division in Spalte L gefunden.")

            div_number = state["div_number"]

            modes = await asyncio.to_thread(
                get_division_modes_for_streichmodus,
                div_number,
            )

            if not modes:
                raise RuntimeError(
                    f"Für Division {div_number} wurden keine erlaubten Streichmodi im Sheet gefunden."
                )

            view = StreichmodusSettingView(
                owner_id=interaction.user.id,
                modes=modes,
                mode_1=state["mode_1"],
                mode_2=state["mode_2"],
                div_number=div_number,
                change_used=state["change_used"],
            )

            await interaction.edit_original_response(
                embed=view.build_embed(),
                view=view,
                content=None,
            )

        except Exception as e:
            await interaction.edit_original_response(
                embed=menu_embed(
                    "⚙️ Einstellungen → Streichmodis setzen",
                    f"Fehler beim Laden: {e}",
                ),
                view=PlaceholderView(
                    owner_id=interaction.user.id,
                    back_view=SettingsMenuView(owner_id=interaction.user.id),
                    back_embed=menu_embed("⚙️ Einstellungen", "Wähle einen Bereich."),
                ),
                content=None,
            )

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=2)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("Spielermenü", "Wähle einen Bereich."),
            view=PlayerMenuView(owner_id=interaction.user.id, show_admin=has_admin_role(interaction.user)),
            content=None,
        )


# =========================================================
# COG
# =========================================================

class PlayerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="player", description="Öffnet das Spielermenü")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def player(self, interaction: discord.Interaction):
        view = PlayerMenuView(owner_id=interaction.user.id, show_admin=has_admin_role(interaction.user))

        await interaction.response.send_message(
            embed=menu_embed("Spielermenü", "Wähle einen Bereich."),
            view=view,
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(PlayerCog(bot))

    # Persistente Buttons offener Anfragen nach Neustart wieder registrieren.
    await restore_exit_request_views(bot)

    # Fristen liegen im Google Sheet und überstehen dadurch Bot-Neustarts.
    if not hasattr(bot, "_exit_request_monitor_task"):
        bot._exit_request_monitor_task = asyncio.create_task(
            exit_request_monitor_loop(bot)
        )
