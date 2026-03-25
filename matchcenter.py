import os
import re
import traceback
from datetime import datetime, timedelta
from typing import Optional, List, Tuple, Dict

import discord
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from discord import app_commands
from discord.ext import commands


# =========================================================
# ENV / CONFIG
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))
EVENT_CHANNEL_ID = int(os.getenv("EVENT_CHANNEL_ID", os.getenv("DISCORD_EVENT_CHANNEL_ID", "0")))
RESTREAM_CHANNEL_ID = int(os.getenv("RESTREAM_CHANNEL_ID", "0"))
SHOWRESTREAMS_CHANNEL_ID = int(os.getenv("SHOWRESTREAMS_CHANNEL_ID", "1277949546650931241"))
CREDS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

print("DEBUG CREDS_FILE =", CREDS_FILE)

SPREADSHEET_ID = "1pZxg1_DUtbO4dZvX95ZrIqEZnkMc1MjmE7z5SEsMHQU"

DIVISION_SHEETS = {
    "Div 1": "1.DIV",
    "Div 2": "2.DIV",
    "Div 3": "3.DIV",
    "Div 4": "4.DIV",
    "Div 5": "5.DIV",
    "Div 6": "6.DIV",
}

CUP_SHEET = "TFL Cup"
RUNNER_SHEET = "Runner"

DIVISIONS = list(DIVISION_SHEETS.keys())

CUP_ROUNDS = [
    "Vorrunde",
    "Last 32",
    "Last 16",
    "Quarterfinals",
    "Semifinals",
    "Finals",
]

# Optional: Hier Stream-/Restream-Mapping pflegen
# Beispiel:
# "crackerito": "https://www.twitch.tv/crackerito"
PLAYER_STREAMS: Dict[str, str] = {}


# =========================================================
# GOOGLE SHEETS
# =========================================================

def get_gspread_client():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, scope)
    return gspread.authorize(creds)


def get_spreadsheet():
    gc = get_gspread_client()
    return gc.open_by_key(SPREADSHEET_ID)


def get_worksheet(name: str):
    return get_spreadsheet().worksheet(name)


def get_division_ws(division: str):
    sheet_name = DIVISION_SHEETS.get(division)
    if not sheet_name:
        raise ValueError(f"Unbekannte Division: {division}")
    return get_worksheet(sheet_name)


# =========================================================
# HELPER
# =========================================================

def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip())


def clean_text_lower(value: str) -> str:
    return clean_text(value).lower()


def parse_matchup(match_text: str) -> Tuple[str, str]:
    text = clean_text(match_text)
    text = text.replace(" vs ", " vs. ")
    parts = [p.strip() for p in text.split("vs.")]
    if len(parts) == 2:
        return parts[0], parts[1]
    return text, ""


def normalize_match_text(match_text: str) -> str:
    p1, p2 = parse_matchup(match_text)
    if p2:
        return f"{p1} vs. {p2}"
    return clean_text(match_text)


def parse_datetime(date_str: str, time_str: str) -> datetime:
    return datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")


def now_str() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M")


def result_league_from_winner(value: str) -> str:
    mapping = {
        "spieler1": "2:0",
        "spieler2": "0:2",
        "remis": "1:1",
    }
    return mapping[value]


def result_cup_from_value(round_name: str, value: str) -> str:
    if round_name in {"Semifinals", "Finals"}:
        mapping = {
            "p1_2_0": "2:0",
            "p1_2_1": "2:1",
            "p2_2_1": "1:2",
            "p2_2_0": "0:2",
        }
        return mapping[value]

    mapping = {
        "spieler1": "1:0",
        "spieler2": "0:1",
    }
    return mapping[value]


def is_nonempty(value: Optional[str]) -> bool:
    return bool(value and str(value).strip())


def truncate_label(text: str, max_len: int = 100) -> str:
    text = clean_text(text)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


# =========================================================
# DATEN AUS SHEETS
# =========================================================

def get_runner_modes() -> List[str]:
    """
    Lädt Sheet 'Runner', Spalte N.
    Entfernt leere und doppelte Einträge.
    """
    ws = get_worksheet(RUNNER_SHEET)
    values = ws.col_values(14)  # Spalte N

    modes = []
    seen = set()

    for v in values:
        val = clean_text(v)
        if not val:
            continue
        low = val.lower()
        if low in {"modus", "mode", "modi", "spalte n"}:
            continue
        if val not in seen:
            seen.add(val)
            modes.append(val)

    return modes[:25]


def get_division_players(division: str) -> List[str]:
    """
    Spieler werden aus allen Matchups 'A vs. B' im jeweiligen Div-Sheet gesammelt.
    """
    ws = get_division_ws(division)
    values = ws.get_all_values()

    players = set()

    for row in values:
        for cell in row:
            txt = clean_text(cell)
            if "vs" not in txt.lower():
                continue
            p1, p2 = parse_matchup(txt)
            if p1:
                players.add(p1)
            if p2:
                players.add(p2)

    return sorted(players)[:25]


def get_league_home_matches(division: str, home_player: str) -> List[str]:
    """
    Sucht alle Matchups im Div-Sheet und filtert auf Heimrecht = Spieler1.
    """
    ws = get_division_ws(division)
    values = ws.get_all_values()

    matches = []
    seen = set()

    for row in values:
        for cell in row:
            txt = clean_text(cell)
            if "vs" not in txt.lower():
                continue

            p1, p2 = parse_matchup(txt)
            if clean_text_lower(p1) == clean_text_lower(home_player):
                match_text = f"{p1} vs. {p2}"
                if match_text not in seen:
                    seen.add(match_text)
                    matches.append(match_text)

    return matches[:25]


def get_cup_matches() -> List[str]:
    """
    Holt alle Spiele aus dem Cup-Sheet, in denen irgendwo im Sheet 'vs' vorkommt.
    So ist es robuster, falls die Spalte nicht immer gleich ist.
    """
    ws = get_worksheet(CUP_SHEET)
    values = ws.get_all_values()

    matches = []
    seen = set()

    for row in values:
        for cell in row:
            txt = clean_text(cell)
            if "vs" not in txt.lower():
                continue

            normalized = normalize_match_text(txt)
            if "vs." not in normalized:
                continue

            if normalized not in seen:
                seen.add(normalized)
                matches.append(normalized)

    return matches[:25]


def get_multistream_link(player1: str, player2: str) -> str:
    """
    Nutzt PLAYER_STREAMS. Wenn beide da sind, werden beide Links kombiniert.
    Falls nur einer existiert, wird der genommen.
    """
    p1 = PLAYER_STREAMS.get(player1)
    p2 = PLAYER_STREAMS.get(player2)

    if p1 and p2:
        return f"{p1} | {p2}"
    if p1:
        return p1
    if p2:
        return p2
    return "Kein Restream/Multistream-Link im Mapping gefunden"


# =========================================================
# SHEET-SCHREIBEN
# =========================================================

def find_row_by_match(ws, match_text: str) -> Optional[int]:
    """
    Sucht die Zeile, in der das Match vorkommt.
    Flexible Suche, damit kleine Schreibabweichungen nicht direkt alles zerstören.
    """
    target = clean_text_lower(normalize_match_text(match_text))
    all_values = ws.get_all_values()

    for row_idx, row in enumerate(all_values, start=1):
        for cell in row:
            cell_norm = clean_text_lower(normalize_match_text(cell))
            if cell_norm == target:
                return row_idx

    # Fallback: enthält den Text
    for row_idx, row in enumerate(all_values, start=1):
        row_joined = " | ".join(clean_text(c) for c in row)
        row_norm = clean_text_lower(normalize_match_text(row_joined))
        if target in row_norm:
            return row_idx

    return None


def write_league_result(
    division: str,
    match_text: str,
    mode: str,
    result: str,
    racetime_link: str,
    entered_by: str,
    timestamp: str,
) -> bool:
    """
    Schreibt in die Zeile des Spiels:
    B = Zeitstempel
    C = Modus
    E = Ergebnis
    G = Racetime
    H = Discordname
    """
    ws = get_division_ws(division)
    row_idx = find_row_by_match(ws, match_text)

    if row_idx is None:
        return False

    ws.update(f"B{row_idx}", [[timestamp]])
    ws.update(f"C{row_idx}", [[mode]])
    ws.update(f"E{row_idx}", [[result]])
    ws.update(f"G{row_idx}", [[racetime_link]])
    ws.update(f"H{row_idx}", [[entered_by]])
    return True


def write_cup_result(
    round_name: str,
    match_text: str,
    result: str,
    racetime_link: str,
    entered_meta: str,
) -> bool:
    """
    Schreibt in die Zeile des Cup-Spiels:
    C = Ergebnis
    E = Racetime
    F = Eingebender + Zeitstempel

    Das Match wird flexibel im gesamten Cup-Sheet gesucht.
    """
    ws = get_worksheet(CUP_SHEET)
    row_idx = find_row_by_match(ws, match_text)

    if row_idx is None:
        return False

    ws.update(f"C{row_idx}", [[result]])
    ws.update(f"E{row_idx}", [[racetime_link]])
    ws.update(f"F{row_idx}", [[entered_meta]])
    return True


# =========================================================
# DISCORD EVENT / POSTS
# =========================================================

async def create_discord_scheduled_event(
    guild: discord.Guild,
    title: str,
    location: str,
    start_dt: datetime,
    end_dt: datetime,
    description: Optional[str] = None,
) -> Optional[discord.ScheduledEvent]:
    try:
        event = await guild.create_scheduled_event(
            name=title,
            description=description or "",
            start_time=start_dt,
            end_time=end_dt,
            entity_type=discord.EntityType.external,
            privacy_level=discord.PrivacyLevel.guild_only,
            location=location,
        )
        return event
    except Exception:
        traceback.print_exc()
        return None


async def send_channel_message(guild: discord.Guild, channel_id: int, text: str) -> bool:
    if not channel_id:
        return False

    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return False

    try:
        await channel.send(text)
        return True
    except Exception:
        traceback.print_exc()
        return False


# =========================================================
# STATE
# =========================================================

class MatchCenterState:
    def __init__(self):
        self.kind: Optional[str] = None

        self.division: Optional[str] = None
        self.home_player: Optional[str] = None
        self.match_text: Optional[str] = None
        self.mode: Optional[str] = None

        self.cup_round: Optional[str] = None

        self.winner: Optional[str] = None
        self.racetime_link: Optional[str] = None

        self.date_str: Optional[str] = None
        self.time_str: Optional[str] = None


# =========================================================
# MODALS
# =========================================================

class DateTimeModal(discord.ui.Modal, title="Datum und Uhrzeit"):
    date_input = discord.ui.TextInput(
        label="Datum",
        placeholder="26.03.2026",
        required=True,
        max_length=10,
    )

    time_input = discord.ui.TextInput(
        label="Uhrzeit",
        placeholder="20:30",
        required=True,
        max_length=5,
    )

    def __init__(self, parent_view: "BaseFlowView"):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        date_str = str(self.date_input).strip()
        time_str = str(self.time_input).strip()

        try:
            parse_datetime(date_str, time_str)
        except ValueError:
            await interaction.response.send_message(
                "Ungültiges Format. Bitte Datum als TT.MM.JJJJ und Uhrzeit als HH:MM eingeben.",
                ephemeral=True,
            )
            return

        self.parent_view.state.date_str = date_str
        self.parent_view.state.time_str = time_str

        await interaction.response.edit_message(
            content=self.parent_view.render_summary(),
            view=self.parent_view
        )


class RacetimeModal(discord.ui.Modal, title="Racetime-Link"):
    racetime_input = discord.ui.TextInput(
        label="Racetime-Link",
        placeholder="https://racetime.gg/...",
        required=True,
        max_length=300,
    )

    def __init__(self, parent_view: "BaseFlowView"):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        self.parent_view.state.racetime_link = str(self.racetime_input).strip()

        await interaction.response.edit_message(
            content=self.parent_view.render_summary(),
            view=self.parent_view
        )


# =========================================================
# BASE VIEW
# =========================================================

class BaseFlowView(discord.ui.View):
    def __init__(self, cog: "MatchCenterCog", author_id: int, timeout: int = 900):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.author_id = author_id
        self.state = MatchCenterState()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Dieses Matchcenter-Fenster gehört nicht dir.",
                ephemeral=True
            )
            return False
        return True

    def render_summary(self) -> str:
        s = self.state
        lines = ["## TFL Matchcenter", ""]

        if s.kind:
            lines.append(f"**Bereich:** {s.kind}")

        if s.division:
            lines.append(f"**Division:** {s.division}")

        if s.cup_round:
            lines.append(f"**Runde:** {s.cup_round}")

        if s.home_player:
            lines.append(f"**Heimrecht:** {s.home_player}")

        if s.match_text:
            lines.append(f"**Spiel:** {s.match_text}")

        if s.mode:
            lines.append(f"**Modus:** {s.mode}")

        if s.winner:
            lines.append(f"**Auswahl Ergebnis/Gewinner:** {s.winner}")

        if s.date_str:
            lines.append(f"**Datum:** {s.date_str}")

        if s.time_str:
            lines.append(f"**Uhrzeit:** {s.time_str}")

        if s.racetime_link:
            lines.append(f"**Racetime:** {s.racetime_link}")

        return "\n".join(lines)


# =========================================================
# SELECTS
# =========================================================

class DivisionSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=d, value=d) for d in DIVISIONS]
        super().__init__(
            placeholder="Welche Division?",
            options=options,
            min_values=1,
            max_values=1,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, (LeagueScheduleView, LeagueResultView)):
            return

        view.state.division = self.values[0]
        view.state.home_player = None
        view.state.match_text = None
        view.rebuild_dynamic_items()

        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view
        )


class HomePlayerSelect(discord.ui.Select):
    def __init__(self, players: List[str]):
        options = [
            discord.SelectOption(label=truncate_label(p), value=p)
            for p in players[:25]
        ]
        super().__init__(
            placeholder="Wer hat Heimrecht?",
            options=options,
            min_values=1,
            max_values=1,
            row=1
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, (LeagueScheduleView, LeagueResultView)):
            return

        view.state.home_player = self.values[0]
        view.state.match_text = None
        view.rebuild_dynamic_items()

        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view
        )


class MatchSelect(discord.ui.Select):
    def __init__(self, matches: List[str], placeholder: str = "Spiel auswählen", row: int = 2):
        options = [
            discord.SelectOption(label=truncate_label(m), value=m)
            for m in matches[:25]
        ]
        super().__init__(
            placeholder=placeholder,
            options=options,
            min_values=1,
            max_values=1,
            row=row
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if isinstance(view, BaseFlowView):
            view.state.match_text = self.values[0]
            await interaction.response.edit_message(
                content=view.render_summary(),
                view=view
            )


class ModeSelect(discord.ui.Select):
    def __init__(self, modes: List[str], row: int = 3):
        if not modes:
            modes = ["Kein Modus gefunden"]

        options = [
            discord.SelectOption(label=truncate_label(m), value=m)
            for m in modes[:25]
        ]
        super().__init__(
            placeholder="Welcher Modus?",
            options=options,
            min_values=1,
            max_values=1,
            row=row
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if isinstance(view, BaseFlowView):
            view.state.mode = self.values[0]
            await interaction.response.edit_message(
                content=view.render_summary(),
                view=view
            )


class CupRoundSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=r, value=r) for r in CUP_ROUNDS]
        super().__init__(
            placeholder="Welche Runde?",
            options=options,
            min_values=1,
            max_values=1,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if isinstance(view, (CupScheduleView, CupResultView)):
            view.state.cup_round = self.values[0]

            if isinstance(view, CupResultView):
                view.rebuild_dynamic_items()

            await interaction.response.edit_message(
                content=view.render_summary(),
                view=view
            )


class LeagueWinnerSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Spieler 1", value="spieler1"),
            discord.SelectOption(label="Spieler 2", value="spieler2"),
            discord.SelectOption(label="Remis", value="remis"),
        ]
        super().__init__(
            placeholder="Wer hat gewonnen?",
            options=options,
            min_values=1,
            max_values=1,
            row=4
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if isinstance(view, LeagueResultView):
            view.state.winner = self.values[0]
            await interaction.response.edit_message(
                content=view.render_summary(),
                view=view
            )


class CupWinnerStandardSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Spieler 1", value="spieler1"),
            discord.SelectOption(label="Spieler 2", value="spieler2"),
        ]
        super().__init__(
            placeholder="Wer hat gewonnen?",
            options=options,
            min_values=1,
            max_values=1,
            row=2
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if isinstance(view, CupResultView):
            view.state.winner = self.values[0]
            await interaction.response.edit_message(
                content=view.render_summary(),
                view=view
            )


class CupWinnerBestOf3Select(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Spieler 1 gewinnt 2:0", value="p1_2_0"),
            discord.SelectOption(label="Spieler 1 gewinnt 2:1", value="p1_2_1"),
            discord.SelectOption(label="Spieler 2 gewinnt 2:1", value="p2_2_1"),
            discord.SelectOption(label="Spieler 2 gewinnt 2:0", value="p2_2_0"),
        ]
        super().__init__(
            placeholder="Best of 3 Ergebnis",
            options=options,
            min_values=1,
            max_values=1,
            row=2
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if isinstance(view, CupResultView):
            view.state.winner = self.values[0]
            await interaction.response.edit_message(
                content=view.render_summary(),
                view=view
            )


# =========================================================
# START VIEW
# =========================================================

class MatchCenterStartView(BaseFlowView):
    def __init__(self, cog: "MatchCenterCog", author_id: int):
        super().__init__(cog, author_id)

    @discord.ui.button(label="Termin League", style=discord.ButtonStyle.primary, row=0)
    async def termin_league(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = LeagueScheduleView(self.cog, self.author_id)
        view.state.kind = "Termin League"
        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view
        )

    @discord.ui.button(label="Termin Cup", style=discord.ButtonStyle.primary, row=0)
    async def termin_cup(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = CupScheduleView(self.cog, self.author_id)
        view.state.kind = "Termin Cup"
        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view
        )

    @discord.ui.button(label="Ergebnis League", style=discord.ButtonStyle.success, row=1)
    async def ergebnis_league(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = LeagueResultView(self.cog, self.author_id)
        view.state.kind = "Ergebnis League"
        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view
        )

    @discord.ui.button(label="Ergebnis Cup", style=discord.ButtonStyle.success, row=1)
    async def ergebnis_cup(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = CupResultView(self.cog, self.author_id)
        view.state.kind = "Ergebnis Cup"
        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view
        )


# =========================================================
# LEAGUE SCHEDULE VIEW
# =========================================================

class LeagueScheduleView(BaseFlowView):
    def __init__(self, cog: "MatchCenterCog", author_id: int):
        super().__init__(cog, author_id)
        self.add_item(DivisionSelect())
        self.add_item(ModeSelect(get_runner_modes(), row=3))

    def rebuild_dynamic_items(self):
        for item in list(self.children):
            if isinstance(item, (HomePlayerSelect, MatchSelect)):
                self.remove_item(item)

        if self.state.division:
            players = get_division_players(self.state.division)
            if players:
                self.add_item(HomePlayerSelect(players))

        if self.state.division and self.state.home_player:
            matches = get_league_home_matches(self.state.division, self.state.home_player)
            if matches:
                self.add_item(MatchSelect(matches, row=2))

    @discord.ui.button(label="Datum/Uhrzeit", style=discord.ButtonStyle.secondary, row=4)
    async def date_time_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DateTimeModal(self))

    @discord.ui.button(label="Absenden", style=discord.ButtonStyle.success, row=4)
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        s = self.state

        if not all([s.division, s.home_player, s.match_text, s.mode, s.date_str, s.time_str]):
            await interaction.response.send_message("Es fehlen noch Angaben.", ephemeral=True)
            return

        try:
            start_dt = parse_datetime(s.date_str, s.time_str)
        except ValueError:
            await interaction.response.send_message("Datum/Uhrzeit ungültig.", ephemeral=True)
            return

        end_dt = start_dt + timedelta(hours=2)
        player1, player2 = parse_matchup(s.match_text)
        location = get_multistream_link(player1, player2)
        title = f"{s.division} | {player1} vs. {player2} | {s.mode}"

        event = await create_discord_scheduled_event(
            guild=interaction.guild,
            title=title,
            location=location,
            start_dt=start_dt,
            end_dt=end_dt,
            description="League-Match aus dem TFL Matchcenter"
        )

        if event:
            await interaction.response.send_message(
                f"Event erstellt:\n**{title}**",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "Event konnte nicht erstellt werden.",
                ephemeral=True
            )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.danger, row=4)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = MatchCenterStartView(self.cog, self.author_id)
        await interaction.response.edit_message(
            content="## TFL Matchcenter",
            view=view
        )


# =========================================================
# CUP SCHEDULE VIEW
# =========================================================

class CupScheduleView(BaseFlowView):
    def __init__(self, cog: "MatchCenterCog", author_id: int):
        super().__init__(cog, author_id)
        self.add_item(CupRoundSelect())
        self.add_item(MatchSelect(get_cup_matches(), row=1))
        self.add_item(ModeSelect(get_runner_modes(), row=2))

    @discord.ui.button(label="Datum/Uhrzeit", style=discord.ButtonStyle.secondary, row=3)
    async def date_time_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DateTimeModal(self))

    @discord.ui.button(label="Absenden", style=discord.ButtonStyle.success, row=3)
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        s = self.state

        if not all([s.cup_round, s.match_text, s.mode, s.date_str, s.time_str]):
            await interaction.response.send_message("Es fehlen noch Angaben.", ephemeral=True)
            return

        try:
            start_dt = parse_datetime(s.date_str, s.time_str)
        except ValueError:
            await interaction.response.send_message("Datum/Uhrzeit ungültig.", ephemeral=True)
            return

        end_dt = start_dt + timedelta(hours=2)
        player1, player2 = parse_matchup(s.match_text)
        location = get_multistream_link(player1, player2)
        title = f"TFL Cup {s.cup_round} | {player1} vs. {player2} | {s.mode}"

        event = await create_discord_scheduled_event(
            guild=interaction.guild,
            title=title,
            location=location,
            start_dt=start_dt,
            end_dt=end_dt,
            description="Cup-Match aus dem TFL Matchcenter"
        )

        if event:
            await interaction.response.send_message(
                f"Event erstellt:\n**{title}**",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "Event konnte nicht erstellt werden.",
                ephemeral=True
            )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.danger, row=3)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = MatchCenterStartView(self.cog, self.author_id)
        await interaction.response.edit_message(
            content="## TFL Matchcenter",
            view=view
        )


# =========================================================
# LEAGUE RESULT VIEW
# =========================================================

class LeagueResultView(BaseFlowView):
    def __init__(self, cog: "MatchCenterCog", author_id: int):
        super().__init__(cog, author_id)
        self.add_item(DivisionSelect())
        self.add_item(ModeSelect(get_runner_modes(), row=3))
        self.add_item(LeagueWinnerSelect())

    def rebuild_dynamic_items(self):
        for item in list(self.children):
            if isinstance(item, (HomePlayerSelect, MatchSelect)):
                self.remove_item(item)

        if self.state.division:
            players = get_division_players(self.state.division)
            if players:
                self.add_item(HomePlayerSelect(players))

        if self.state.division and self.state.home_player:
            matches = get_league_home_matches(self.state.division, self.state.home_player)
            if matches:
                self.add_item(MatchSelect(matches, row=2))

    @discord.ui.button(label="Racetime-Link", style=discord.ButtonStyle.secondary, row=5)
    async def racetime_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RacetimeModal(self))

    @discord.ui.button(label="Absenden", style=discord.ButtonStyle.success, row=5)
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        s = self.state

        if not all([s.division, s.home_player, s.match_text, s.mode, s.winner, s.racetime_link]):
            await interaction.response.send_message("Es fehlen noch Angaben.", ephemeral=True)
            return

        result = result_league_from_winner(s.winner)
        timestamp = now_str()
        entered_by = interaction.user.display_name

        ok = write_league_result(
            division=s.division,
            match_text=s.match_text,
            mode=s.mode,
            result=result,
            racetime_link=s.racetime_link,
            entered_by=entered_by,
            timestamp=timestamp,
        )

        if not ok:
            await interaction.response.send_message(
                "League-Ergebnis konnte nicht ins Sheet geschrieben werden. Wahrscheinlich wurde die Spiel-Zeile nicht gefunden.",
                ephemeral=True
            )
            return

        player1, player2 = parse_matchup(s.match_text)
        msg = (
            f"[TFL League] {timestamp}\n"
            f"{s.division}\n"
            f"{player1} vs. {player2} -> {result}\n"
            f"Modus: {s.mode}\n"
            f"Racetime: {s.racetime_link}\n"
            f"Eingetragen von: {entered_by}"
        )

        await send_channel_message(interaction.guild, SHOWRESTREAMS_CHANNEL_ID, msg)

        await interaction.response.send_message(
            "League-Ergebnis wurde eingetragen.",
            ephemeral=True
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.danger, row=5)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = MatchCenterStartView(self.cog, self.author_id)
        await interaction.response.edit_message(
            content="## TFL Matchcenter",
            view=view
        )


# =========================================================
# CUP RESULT VIEW
# =========================================================

class CupResultView(BaseFlowView):
    def __init__(self, cog: "MatchCenterCog", author_id: int):
        super().__init__(cog, author_id)
        self.add_item(CupRoundSelect())
        self.add_item(MatchSelect(get_cup_matches(), row=1))
        self.rebuild_dynamic_items()

    def rebuild_dynamic_items(self):
        for item in list(self.children):
            if isinstance(item, (CupWinnerStandardSelect, CupWinnerBestOf3Select)):
                self.remove_item(item)

        if self.state.cup_round in {"Semifinals", "Finals"}:
            self.add_item(CupWinnerBestOf3Select())
        else:
            self.add_item(CupWinnerStandardSelect())

    @discord.ui.button(label="Racetime-Link", style=discord.ButtonStyle.secondary, row=3)
    async def racetime_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RacetimeModal(self))

    @discord.ui.button(label="Absenden", style=discord.ButtonStyle.success, row=3)
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        s = self.state

        if not all([s.cup_round, s.match_text, s.winner, s.racetime_link]):
            await interaction.response.send_message("Es fehlen noch Angaben.", ephemeral=True)
            return

        result = result_cup_from_value(s.cup_round, s.winner)
        timestamp = now_str()
        entered_meta = f"{interaction.user.display_name} | {timestamp}"

        ok = write_cup_result(
            round_name=s.cup_round,
            match_text=s.match_text,
            result=result,
            racetime_link=s.racetime_link,
            entered_meta=entered_meta,
        )

        if not ok:
            await interaction.response.send_message(
                "Cup-Ergebnis konnte nicht ins Sheet geschrieben werden. Wahrscheinlich wurde die Spiel-Zeile nicht gefunden.",
                ephemeral=True
            )
            return

        player1, player2 = parse_matchup(s.match_text)
        msg = (
            f"[TFL Cup] {timestamp}\n"
            f"Runde: {s.cup_round}\n"
            f"{player1} vs. {player2} -> {result}\n"
            f"Racetime: {s.racetime_link}\n"
            f"Eingetragen von: {interaction.user.display_name}"
        )

        await send_channel_message(interaction.guild, SHOWRESTREAMS_CHANNEL_ID, msg)

        await interaction.response.send_message(
            "Cup-Ergebnis wurde eingetragen.",
            ephemeral=True
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.danger, row=3)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = MatchCenterStartView(self.cog, self.author_id)
        await interaction.response.edit_message(
            content="## TFL Matchcenter",
            view=view
        )


# =========================================================
# COG
# =========================================================

class MatchCenterCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="matchcenter", description="Öffnet das TFL Matchcenter.")
    async def matchcenter(self, interaction: discord.Interaction):
        try:
            view = MatchCenterStartView(self, interaction.user.id)
            await interaction.response.send_message(
                "## TFL Matchcenter",
                view=view,
                ephemeral=True
            )
        except Exception:
            traceback.print_exc()
            if interaction.response.is_done():
                await interaction.followup.send(
                    "Fehler beim Öffnen des Matchcenters.",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "Fehler beim Öffnen des Matchcenters.",
                    ephemeral=True
                )


async def setup(bot: commands.Bot):
    await bot.add_cog(MatchCenterCog(bot))
