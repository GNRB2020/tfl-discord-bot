import os
import re
import asyncio
import traceback
from datetime import datetime as dt, timedelta

import discord
import pytz
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv


# =========================================================
# ENV / CONFIG
# =========================================================
load_dotenv()

GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))
EVENT_CHANNEL_ID = int(os.getenv("EVENT_CHANNEL_ID", os.getenv("DISCORD_EVENT_CHANNEL_ID", "0")))
SHOWRESTREAMS_CHANNEL_ID = int(os.getenv("SHOWRESTREAMS_CHANNEL_ID", "1277949546650931241"))
RESULTS_CHANNEL_ID = int(os.getenv("RESULTS_CHANNEL_ID", "1275077562984435853"))
CREDS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
SPREADSHEET_TITLE = os.getenv("SPREADSHEET_TITLE", "Season #4 - Spielbetrieb")
TFL_ROLE_ID = int(os.getenv("TFL_ROLE_ID", "0"))

BERLIN_TZ = pytz.timezone("Europe/Berlin")

print("DEBUG matchcenter CREDS_FILE =", CREDS_FILE)

DIVISION_SHEETS = {
    "Div 1": "1.DIV",
    "Div 2": "2.DIV",
    "Div 3": "3.DIV",
    "Div 4": "4.DIV",
    "Div 5": "5.DIV",
    "Div 6": "6.DIV",
}

RUNNER_SHEET = "Runner"
CUP_SHEET = "TFL Cup"

CUP_ROUNDS = [
    "Vorrunde",
    "Last 32",
    "Last 16",
    "Quarterfinals",
    "Semifinals",
    "Finals",
]

DIV_COL_LEFT = 4      # D
DIV_COL_MARKER = 5    # E
DIV_COL_RIGHT = 6     # F

CUP_COL_ROUND = 1     # A
CUP_COL_P1 = 2        # B
CUP_COL_RESULT = 3    # C
CUP_COL_P2 = 4        # D
CUP_COL_RACETIME = 5  # E
CUP_COL_META = 6      # F


# =========================================================
# TWITCH MAP
# =========================================================
TWITCH_MAP = {
    "gnrb": "gnrb87",
    "steinchen89": "Steinchen89",
    "dirtbubble": "DirtBubblE",
    "speeka": "Speeka89",
    "link-q": "linkq87",
    "derdasch": "derdasch",
    "bumble": "bumblebee86x",
    "leisureking": "Leisureking",
    "tyrant242": "Tyrant242",
    "loadpille": "LoaDPille",
    "offiziell_alex2k6": "offiziell_alex2k6",
    "dafritza": "dafritza84",
    "teku361": "TeKu361",
    "holysmoke": "holysmoke",
    "wabnik": "Wabnik",
    "sydraves": "Sydraves",
    "roteralarm": "roteralarm",
    "kromb": "kromb4787",
    "ntapple": "NTapple",
    "kico_89": "Kico_89",
    "oeptown": "oeptown",
    "mr__navigator": "mr__navigator",
    "basdingo": "Basdingo",
    "phoenix": "phoenix_tyrol",
    "wolle": "wolle_91",
    "mc_thomas3": "mc_thomas3",
    "esto": "estaryo90",
    "dafatbrainbug": "dafatbrainbug",
    "funtreecake": "FunTreeCake",
    "darpex": "darpex3",
    "schieva96": "Schieva96",
    "crackerito": "crackerito88",
    "blackirave": "blackirave",
    "nezil": "Nezil7",
    "officermiaumiau": "officermiaumiautwitch",
    "papaschland": "Papaschland",
    "hideonbush": "hideonbush1909",
    "mahony": "mahony19888",
    "iconic": "iconic22",
    "krawalltofu": "krawalltofu",
    "osora": "osora90",
    "randonorris": "Rando_Norris",
    "neo-sanji": "neo_sanji",
    "cfate91": "CFate91",
    "kalamarino": "Kalamarino",
    "dekar112": "dekar_112",
    "drdiabetus": "dr_diabetus",
    "darknesslink81": "Darknesslink81",
    "littlevaia": "LittleVaia",
    "boothisman": "boothisman",
    "cptnsabo": "CptnSabo",
    "aleximwunderland": "alex_im_wunderland",
    "dominik0688": "Dominik0688",
    "quaschynock": "quaschynock",
    "marcii": "marciii86",
    "rennyur": "rennyur",
    "yasi89": "yasi89",
}


# =========================================================
# GOOGLE SHEETS
# =========================================================
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

SHEETS_ENABLED = True
GC = None
WB = None

try:
    CREDS = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    GC = gspread.authorize(CREDS)
    WB = GC.open(SPREADSHEET_TITLE)
    print("✅ matchcenter Google Sheets verbunden")
except Exception as e:
    SHEETS_ENABLED = False
    WB = None
    print(f"⚠️ matchcenter Google Sheets deaktiviert: {e}")


def sheets_required():
    if not SHEETS_ENABLED or WB is None:
        raise RuntimeError("Google Sheets nicht verbunden.")


# =========================================================
# HELFER
# =========================================================
def has_tfl_role(member: discord.Member) -> bool:
    if not isinstance(member, discord.Member):
        return False
    if TFL_ROLE_ID == 0:
        return False
    return any(r.id == TFL_ROLE_ID for r in member.roles)


def _cell(row, idx0):
    return row[idx0].strip() if 0 <= idx0 < len(row) else ""


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip())


def now_berlin_str() -> str:
    return dt.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M")


def parse_berlin_datetime(date_str: str, time_str: str):
    naive = dt.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")
    return BERLIN_TZ.localize(naive)


def get_div_ws_from_label(division_label: str):
    sheets_required()
    ws_name = DIVISION_SHEETS.get(division_label)
    if not ws_name:
        raise ValueError(f"Unbekannte Division: {division_label}")
    return WB.worksheet(ws_name)


def get_runner_modes() -> list[str]:
    sheets_required()
    ws = WB.worksheet(RUNNER_SHEET)
    values = ws.col_values(14)

    out = []
    seen = set()

    for v in values:
        val = clean_text(v)
        if not val:
            continue
        if val.lower() in {"modus", "mode", "modi"}:
            continue
        if val not in seen:
            seen.add(val)
            out.append(val)

    return out[:25] if out else ["Standard"]


def build_multistream_url(player1: str, player2: str) -> str:
    p1 = TWITCH_MAP.get(player1.strip().lower())
    p2 = TWITCH_MAP.get(player2.strip().lower())

    if p1 and p2:
        return f"https://multistre.am/{p1}/{p2}/layout4"
    if p1:
        return f"https://www.twitch.tv/{p1}"
    if p2:
        return f"https://www.twitch.tv/{p2}"
    return "Kein Streamlink im Mapping gefunden"


def result_league_from_value(value: str) -> str:
    return {
        "spieler1": "2:0",
        "spieler2": "0:2",
        "remis": "1:1",
    }[value]


def result_cup_from_value(round_name: str, value: str) -> str:
    if round_name in {"Semifinals", "Finals"}:
        return value
    return {
        "spieler1": "1:0",
        "spieler2": "0:1",
    }[value]


def league_result_post_text(division_label: str, timestamp: str, p1: str, p2: str, result: str, mode: str, racetime: str) -> str:
    return (
        f"[{division_label.replace('Div', 'Division')}] {timestamp}\n"
        f"{p1} vs {p2} → {result}\n"
        f"Modus: {mode}\n"
        f"Raceroom: {racetime}"
    )


def cup_result_post_text(timestamp: str, round_label: str, p1: str, p2: str, result: str, racetime: str) -> str:
    return (
        f"[TFL Cup {round_label}] {timestamp}\n"
        f"{p1} vs {p2} → {result}\n"
        f"Modus: Cup\n"
        f"Raceroom: {racetime}"
    )


# =========================================================
# LEAGUE DATEN
# =========================================================
def collect_players_from_div_ws(ws) -> list[str]:
    rows = ws.get_all_values()
    seen = set()
    players = []

    d_idx = DIV_COL_LEFT - 1
    f_idx = DIV_COL_RIGHT - 1

    for row in rows[1:]:
        p1 = _cell(row, d_idx)
        p2 = _cell(row, f_idx)

        for p in (p1, p2):
            if not p:
                continue
            low = p.lower()
            if low not in seen:
                seen.add(low)
                players.append(p)

    return players[:25]


def get_division_players(division_label: str) -> list[str]:
    ws = get_div_ws_from_label(division_label)
    return collect_players_from_div_ws(ws)


def get_league_home_matches(division_label: str, home_player: str):
    ws = get_div_ws_from_label(division_label)
    rows = ws.get_all_values()

    out = []
    seen = set()

    for idx, row in enumerate(rows, start=1):
        if idx == 1:
            continue

        heim = _cell(row, DIV_COL_LEFT - 1)
        marker = _cell(row, DIV_COL_MARKER - 1)
        gast = _cell(row, DIV_COL_RIGHT - 1)

        if not heim or not gast:
            continue

        if heim.lower() == home_player.lower() and marker.lower() == "vs":
            label = f"{heim} vs. {gast}"
            if label not in seen:
                seen.add(label)
                out.append({
                    "label": label,
                    "value": str(idx),
                    "row_index": idx,
                    "heim": heim,
                    "gast": gast,
                })

    return out[:25]


def write_league_result(
    row_index: int,
    mode: str,
    result: str,
    racetime_link: str,
    entered_by: str,
    timestamp: str,
    division_label: str,
):
    ws = get_div_ws_from_label(division_label)

    reqs = [
        {"range": f"B{row_index}:C{row_index}", "values": [[timestamp, mode]]},
        {"range": f"E{row_index}:E{row_index}", "values": [[result]]},
        {"range": f"G{row_index}:G{row_index}", "values": [[racetime_link]]},
        {"range": f"H{row_index}:H{row_index}", "values": [[entered_by]]},
    ]
    ws.batch_update(reqs)


# =========================================================
# CUP DATEN
# =========================================================
def normalize_round_label(raw_round: str) -> str:
    raw = clean_text(raw_round).upper()

    if raw in {"VR", "VR.", "VORRUNDE"}:
        return "Vorrunde"
    if raw in {"L32", "LAST32", "LAST 32"}:
        return "Last 32"
    if raw in {"L16", "LAST16", "LAST 16"}:
        return "Last 16"
    if raw in {"QF", "QUARTERFINAL", "QUARTERFINALS"}:
        return "Quarterfinals"
    if raw in {"SF", "SEMIFINAL", "SEMIFINALS"}:
        return "Semifinals"
    if raw in {"FIN", "FINAL", "FINALS", "F"}:
        return "Finals"

    return clean_text(raw_round)


def is_cup_match_open(round_label: str, result_value: str) -> bool:
    result_clean = clean_text(result_value)

    if round_label in {"Semifinals", "Finals"}:
        return "2" not in result_clean

    return result_clean == ""


def get_open_cup_matches(selected_round: str | None = None):
    sheets_required()
    ws = WB.worksheet(CUP_SHEET)
    rows = ws.get_all_values()

    out = []
    seen = set()

    for idx, row in enumerate(rows, start=1):
        p1 = _cell(row, CUP_COL_P1 - 1)
        result_val = _cell(row, CUP_COL_RESULT - 1)
        p2 = _cell(row, CUP_COL_P2 - 1)
        round_code = _cell(row, CUP_COL_ROUND - 1)

        if not p1 or not p2:
            continue

        if p1.lower() in {"spieler 1", "spieler1"}:
            continue
        if p2.lower() in {"spieler 2", "spieler2", "racetime"}:
            continue

        round_label = normalize_round_label(round_code)
        if selected_round and round_label != selected_round:
            continue

        if not is_cup_match_open(round_label, result_val):
            continue

        label = f"{p1} vs. {p2}"
        key = f"{idx}|{label}".lower()
        if key in seen:
            continue
        seen.add(key)

        out.append({
            "label": label,
            "value": str(idx),
            "row_index": idx,
            "round_label": round_label,
            "player1": p1,
            "player2": p2,
            "current_result": result_val,
        })

    return out[:25]


def append_series_racetime(existing_text: str, score: str, link: str) -> str:
    existing = existing_text.strip() if existing_text else ""
    new_line = f"{score} | {link}".strip()
    return existing + "\n" + new_line if existing else new_line


def write_cup_result_standard(row_index: int, result: str, racetime_link: str, entered_meta: str):
    ws = WB.worksheet(CUP_SHEET)
    reqs = [
        {"range": f"C{row_index}:C{row_index}", "values": [[result]]},
        {"range": f"E{row_index}:E{row_index}", "values": [[racetime_link]]},
        {"range": f"F{row_index}:F{row_index}", "values": [[entered_meta]]},
    ]
    ws.batch_update(reqs)


def write_cup_result_series(row_index: int, series_score: str, racetime_link: str, entered_meta: str):
    ws = WB.worksheet(CUP_SHEET)
    existing_racetime = ws.acell(f"E{row_index}").value or ""
    combined_racetime = append_series_racetime(existing_racetime, series_score, racetime_link)

    reqs = [
        {"range": f"C{row_index}:C{row_index}", "values": [[series_score]]},
        {"range": f"E{row_index}:E{row_index}", "values": [[combined_racetime]]},
        {"range": f"F{row_index}:F{row_index}", "values": [[entered_meta]]},
    ]
    ws.batch_update(reqs)


# =========================================================
# DISCORD HELFER
# =========================================================
async def create_scheduled_event(
    guild: discord.Guild,
    title: str,
    location: str,
    start_dt,
    end_dt,
    description: str,
):
    return await guild.create_scheduled_event(
        name=title,
        description=description,
        start_time=start_dt,
        end_time=end_dt,
        entity_type=discord.EntityType.external,
        location=location,
        privacy_level=discord.PrivacyLevel.guild_only,
    )


async def send_result_post(guild: discord.Guild, text: str):
    channel = guild.get_channel(RESULTS_CHANNEL_ID)
    if channel is None:
        channel = guild.get_channel(SHOWRESTREAMS_CHANNEL_ID)

    if isinstance(channel, discord.TextChannel):
        await channel.send(text)


# =========================================================
# STATE
# =========================================================
class MatchCenterState:
    def __init__(self):
        self.kind: str | None = None
        self.division: str | None = None
        self.home_player: str | None = None
        self.match_label: str | None = None
        self.match_row_index: int | None = None
        self.player1: str | None = None
        self.player2: str | None = None
        self.mode: str | None = None
        self.cup_round: str | None = None
        self.winner_value: str | None = None
        self.racetime_link: str | None = None
        self.date_str: str | None = None
        self.time_str: str | None = None

    def clone(self):
        new = MatchCenterState()
        new.kind = self.kind
        new.division = self.division
        new.home_player = self.home_player
        new.match_label = self.match_label
        new.match_row_index = self.match_row_index
        new.player1 = self.player1
        new.player2 = self.player2
        new.mode = self.mode
        new.cup_round = self.cup_round
        new.winner_value = self.winner_value
        new.racetime_link = self.racetime_link
        new.date_str = self.date_str
        new.time_str = self.time_str
        return new


# =========================================================
# MODALS
# =========================================================
class DateTimeModal(discord.ui.Modal, title="Datum und Uhrzeit"):
    date_input = discord.ui.TextInput(label="Datum", placeholder="26.03.2026", required=True, max_length=10)
    time_input = discord.ui.TextInput(label="Uhrzeit", placeholder="20:30", required=True, max_length=5)

    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        date_str = str(self.date_input).strip()
        time_str = str(self.time_input).strip()

        try:
            parse_berlin_datetime(date_str, time_str)
        except ValueError:
            await interaction.response.send_message(
                "Ungültiges Format. Datum: TT.MM.JJJJ und Uhrzeit: HH:MM",
                ephemeral=True,
            )
            return

        self.parent_view.state.date_str = date_str
        self.parent_view.state.time_str = time_str

        await interaction.response.edit_message(
            content=self.parent_view.render_summary(),
            view=self.parent_view,
        )


class RacetimeModal(discord.ui.Modal, title="Racetime-Link"):
    racetime_input = discord.ui.TextInput(
        label="Raceroom-Link",
        placeholder="https://racetime.gg/...",
        required=True,
        max_length=300,
    )

    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        self.parent_view.state.racetime_link = str(self.racetime_input).strip()

        await interaction.response.edit_message(
            content=self.parent_view.render_summary(),
            view=self.parent_view,
        )


# =========================================================
# BASE VIEW
# =========================================================
class BaseFlowView(discord.ui.View):
    def __init__(self, cog, author_id: int, timeout: int = 900):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.author_id = author_id
        self.state = MatchCenterState()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Dieses Fenster gehört nicht dir.",
                ephemeral=True,
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
        if s.match_label:
            lines.append(f"**Spiel:** {s.match_label}")
        if s.mode:
            lines.append(f"**Modus:** {s.mode}")
        if s.winner_value:
            lines.append(f"**Ergebnis-Auswahl:** {s.winner_value}")
        if s.date_str:
            lines.append(f"**Datum:** {s.date_str}")
        if s.time_str:
            lines.append(f"**Uhrzeit:** {s.time_str}")
        if s.racetime_link:
            lines.append(f"**Raceroom:** {s.racetime_link}")

        return "\n".join(lines)


# =========================================================
# SELECTS
# =========================================================
class DivisionSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=f"Div {i}", value=f"Div {i}") for i in range(1, 7)]
        super().__init__(placeholder="Welche Division?", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, (LeagueScheduleView, LeagueResultViewStep1)):
            return

        view.state.division = self.values[0]
        view.state.home_player = None
        view.state.match_label = None
        view.state.match_row_index = None
        view.state.player1 = None
        view.state.player2 = None
        view.rebuild_dynamic_items()

        await interaction.response.edit_message(content=view.render_summary(), view=view)


class HomePlayerSelect(discord.ui.Select):
    def __init__(self, players: list[str]):
        options = [discord.SelectOption(label=p[:100], value=p) for p in players[:25]]
        super().__init__(placeholder="Wer hat Heimrecht?", min_values=1, max_values=1, options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, (LeagueScheduleView, LeagueResultViewStep1)):
            return

        view.state.home_player = self.values[0]
        view.state.match_label = None
        view.state.match_row_index = None
        view.state.player1 = None
        view.state.player2 = None
        view.rebuild_dynamic_items()

        await interaction.response.edit_message(content=view.render_summary(), view=view)


class LeagueMatchSelect(discord.ui.Select):
    def __init__(self, matches: list[dict]):
        options = [
            discord.SelectOption(
                label=m["label"][:100],
                value=f'{m["row_index"]}|{m["heim"]}|{m["gast"]}|{m["label"]}',
            )
            for m in matches[:25]
        ]
        super().__init__(placeholder="Spiel auswählen", min_values=1, max_values=1, options=options, row=2)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, (LeagueScheduleView, LeagueResultViewStep1)):
            return

        row_index, p1, p2, label = self.values[0].split("|", 3)
        view.state.match_row_index = int(row_index)
        view.state.player1 = p1
        view.state.player2 = p2
        view.state.match_label = label

        await interaction.response.edit_message(content=view.render_summary(), view=view)


class CupMatchSelect(discord.ui.Select):
    def __init__(self, matches: list[dict]):
        if not matches:
            options = [discord.SelectOption(label="Keine offenen Cup-Spiele gefunden", value="0|Keine offenen Cup-Spiele gefunden| | ")]
            disabled = True
        else:
            options = [
                discord.SelectOption(
                    label=m["label"][:100],
                    value=f'{m["row_index"]}|{m["label"]}|{m["player1"]}|{m["player2"]}',
                )
                for m in matches[:25]
            ]
            disabled = False

        super().__init__(placeholder="Spiel auswählen", min_values=1, max_values=1, options=options, row=1, disabled=disabled)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, (CupScheduleView, CupResultView)):
            return

        row_index, label, p1, p2 = self.values[0].split("|", 3)
        if row_index == "0":
            await interaction.response.send_message("Es wurden keine offenen Cup-Spiele gefunden.", ephemeral=True)
            return

        view.state.match_row_index = int(row_index)
        view.state.match_label = label
        view.state.player1 = p1
        view.state.player2 = p2

        await interaction.response.edit_message(content=view.render_summary(), view=view)


class ModeSelect(discord.ui.Select):
    def __init__(self, modes: list[str], row: int):
        options = [discord.SelectOption(label=m[:100], value=m) for m in modes[:25]]
        super().__init__(placeholder="Welcher Modus?", min_values=1, max_values=1, options=options, row=row)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if isinstance(view, BaseFlowView):
            view.state.mode = self.values[0]
            await interaction.response.edit_message(content=view.render_summary(), view=view)


class CupRoundSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=r, value=r) for r in CUP_ROUNDS]
        super().__init__(placeholder="Welche Runde?", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, (CupScheduleView, CupResultView)):
            return

        view.state.cup_round = self.values[0]
        view.state.match_label = None
        view.state.match_row_index = None
        view.state.player1 = None
        view.state.player2 = None
        view.state.winner_value = None

        if isinstance(view, CupScheduleView):
            view.rebuild_match_select()
        if isinstance(view, CupResultView):
            view.rebuild_match_select()
            view.rebuild_winner_select()

        await interaction.response.edit_message(content=view.render_summary(), view=view)


class LeagueWinnerSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Spieler 1", value="spieler1"),
            discord.SelectOption(label="Spieler 2", value="spieler2"),
            discord.SelectOption(label="Remis", value="remis"),
        ]
        super().__init__(placeholder="Wer hat gewonnen?", min_values=1, max_values=1, options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if isinstance(view, LeagueResultViewStep2):
            view.state.winner_value = self.values[0]
            await interaction.response.edit_message(content=view.render_summary(), view=view)


class CupWinnerNormalSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Spieler 1", value="spieler1"),
            discord.SelectOption(label="Spieler 2", value="spieler2"),
        ]
        super().__init__(placeholder="Wer hat gewonnen?", min_values=1, max_values=1, options=options, row=2)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if isinstance(view, CupResultView):
            view.state.winner_value = self.values[0]
            await interaction.response.edit_message(content=view.render_summary(), view=view)


class CupWinnerSeriesSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="1:0", value="1:0"),
            discord.SelectOption(label="0:1", value="0:1"),
            discord.SelectOption(label="1:1", value="1:1"),
            discord.SelectOption(label="2:0", value="2:0"),
            discord.SelectOption(label="0:2", value="0:2"),
            discord.SelectOption(label="2:1", value="2:1"),
            discord.SelectOption(label="1:2", value="1:2"),
        ]
        super().__init__(placeholder="Aktueller Serienstand", min_values=1, max_values=1, options=options, row=2)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if isinstance(view, CupResultView):
            view.state.winner_value = self.values[0]
            await interaction.response.edit_message(content=view.render_summary(), view=view)


# =========================================================
# START VIEW
# =========================================================
class MatchCenterStartView(BaseFlowView):
    def __init__(self, cog, author_id: int):
        super().__init__(cog, author_id)

    @discord.ui.button(label="Termin League", style=discord.ButtonStyle.primary, row=0)
    async def termin_league(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            view = LeagueScheduleView(self.cog, self.author_id)
            view.state.kind = "Termin League"
            await interaction.response.edit_message(content=view.render_summary(), view=view)
        except Exception as e:
            traceback.print_exc()
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ Fehler bei Termin League: {e}", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ Fehler bei Termin League: {e}", ephemeral=True)

    @discord.ui.button(label="Termin Cup", style=discord.ButtonStyle.primary, row=0)
    async def termin_cup(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            view = CupScheduleView(self.cog, self.author_id)
            view.state.kind = "Termin Cup"
            await interaction.response.edit_message(content=view.render_summary(), view=view)
        except Exception as e:
            traceback.print_exc()
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ Fehler bei Termin Cup: {e}", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ Fehler bei Termin Cup: {e}", ephemeral=True)

    @discord.ui.button(label="Ergebnis League", style=discord.ButtonStyle.success, row=1)
    async def ergebnis_league(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            view = LeagueResultViewStep1(self.cog, self.author_id)
            view.state.kind = "Ergebnis League"
            await interaction.response.edit_message(content=view.render_summary(), view=view)
        except Exception as e:
            traceback.print_exc()
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ Fehler bei Ergebnis League: {e}", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ Fehler bei Ergebnis League: {e}", ephemeral=True)

    @discord.ui.button(label="Ergebnis Cup", style=discord.ButtonStyle.success, row=1)
    async def ergebnis_cup(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            view = CupResultView(self.cog, self.author_id)
            view.state.kind = "Ergebnis Cup"
            await interaction.response.edit_message(content=view.render_summary(), view=view)
        except Exception as e:
            traceback.print_exc()
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ Fehler bei Ergebnis Cup: {e}", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ Fehler bei Ergebnis Cup: {e}", ephemeral=True)


# =========================================================
# LEAGUE SCHEDULE
# =========================================================
class LeagueScheduleView(BaseFlowView):
    def __init__(self, cog, author_id: int):
        super().__init__(cog, author_id)
        self.add_item(DivisionSelect())
        self.add_item(ModeSelect(get_runner_modes(), row=3))

    def rebuild_dynamic_items(self):
        for item in list(self.children):
            if isinstance(item, (HomePlayerSelect, LeagueMatchSelect)):
                self.remove_item(item)

        if self.state.division:
            players = get_division_players(self.state.division)
            if players:
                self.add_item(HomePlayerSelect(players))

        if self.state.division and self.state.home_player:
            matches = get_league_home_matches(self.state.division, self.state.home_player)
            if matches:
                self.add_item(LeagueMatchSelect(matches))

    @discord.ui.button(label="Datum/Uhrzeit", style=discord.ButtonStyle.secondary, row=4)
    async def datetime_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DateTimeModal(self))

    @discord.ui.button(label="Absenden", style=discord.ButtonStyle.success, row=4)
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        s = self.state
        if not all([s.division, s.match_label, s.player1, s.player2, s.mode, s.date_str, s.time_str]):
            await interaction.response.send_message("Es fehlen noch Angaben.", ephemeral=True)
            return

        try:
            start_dt = parse_berlin_datetime(s.date_str, s.time_str)
            end_dt = start_dt + timedelta(hours=2)
            location = build_multistream_url(s.player1, s.player2)
            title = f"{s.division} | {s.player1} vs. {s.player2} | {s.mode}"

            await create_scheduled_event(
                interaction.guild,
                title,
                location,
                start_dt,
                end_dt,
                f"League-Match in {s.division} zwischen {s.player1} und {s.player2}.",
            )

            await interaction.response.send_message(f"✅ Event erstellt:\n**{title}**", ephemeral=True)
        except Exception as e:
            traceback.print_exc()
            await interaction.response.send_message(f"❌ Event konnte nicht erstellt werden: {e}", ephemeral=True)

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.danger, row=4)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = MatchCenterStartView(self.cog, self.author_id)
        await interaction.response.edit_message(content="## TFL Matchcenter", view=view)


# =========================================================
# LEAGUE RESULT STEP 1
# =========================================================
class LeagueResultViewStep1(BaseFlowView):
    def __init__(self, cog, author_id: int):
        super().__init__(cog, author_id)
        self.add_item(DivisionSelect())

    def rebuild_dynamic_items(self):
        for item in list(self.children):
            if isinstance(item, (HomePlayerSelect, LeagueMatchSelect)):
                self.remove_item(item)

        if self.state.division:
            players = get_division_players(self.state.division)
            if players:
                self.add_item(HomePlayerSelect(players))

        if self.state.division and self.state.home_player:
            matches = get_league_home_matches(self.state.division, self.state.home_player)
            if matches:
                self.add_item(LeagueMatchSelect(matches))

    @discord.ui.button(label="Weiter", style=discord.ButtonStyle.primary, row=4)
    async def continue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        s = self.state
        if not all([s.division, s.match_row_index, s.match_label, s.player1, s.player2]):
            await interaction.response.send_message("Bitte zuerst Division, Heimrecht und Spiel auswählen.", ephemeral=True)
            return

        view = LeagueResultViewStep2(self.cog, self.author_id, s.clone())
        await interaction.response.edit_message(content=view.render_summary(), view=view)

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.danger, row=4)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = MatchCenterStartView(self.cog, self.author_id)
        await interaction.response.edit_message(content="## TFL Matchcenter", view=view)


# =========================================================
# LEAGUE RESULT STEP 2
# =========================================================
class LeagueResultViewStep2(BaseFlowView):
    def __init__(self, cog, author_id: int, state: MatchCenterState):
        super().__init__(cog, author_id)
        self.state = state
        self.add_item(ModeSelect(get_runner_modes(), row=0))
        self.add_item(LeagueWinnerSelect())

    @discord.ui.button(label="Raceroom-Link", style=discord.ButtonStyle.secondary, row=2)
    async def racetime_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RacetimeModal(self))

    @discord.ui.button(label="Absenden", style=discord.ButtonStyle.success, row=2)
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        s = self.state
        if not all([s.division, s.match_row_index, s.match_label, s.player1, s.player2, s.mode, s.winner_value, s.racetime_link]):
            await interaction.response.send_message("Es fehlen noch Angaben.", ephemeral=True)
            return

        try:
            result = result_league_from_value(s.winner_value)
            timestamp = now_berlin_str()
            entered_by = str(interaction.user)

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                write_league_result,
                s.match_row_index,
                s.mode,
                result,
                s.racetime_link,
                entered_by,
                timestamp,
                s.division,
            )

            post_text = league_result_post_text(
                s.division,
                timestamp,
                s.player1,
                s.player2,
                result,
                s.mode,
                s.racetime_link,
            )
            await send_result_post(interaction.guild, post_text)

            await interaction.response.send_message("✅ League-Ergebnis gespeichert und gepostet.", ephemeral=True)
        except Exception as e:
            traceback.print_exc()
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ Fehler beim Speichern des League-Ergebnisses: {e}", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ Fehler beim Speichern des League-Ergebnisses: {e}", ephemeral=True)

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.danger, row=2)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        prev = LeagueResultViewStep1(self.cog, self.author_id)
        prev.state = self.state.clone()
        prev.rebuild_dynamic_items()
        await interaction.response.edit_message(content=prev.render_summary(), view=prev)


# =========================================================
# CUP SCHEDULE
# =========================================================
class CupScheduleView(BaseFlowView):
    def __init__(self, cog, author_id: int):
        super().__init__(cog, author_id)
        self.add_item(CupRoundSelect())
        self.add_item(ModeSelect(get_runner_modes(), row=2))
        self.rebuild_match_select()

    def rebuild_match_select(self):
        for item in list(self.children):
            if isinstance(item, CupMatchSelect):
                self.remove_item(item)
        self.add_item(CupMatchSelect(get_open_cup_matches(self.state.cup_round)))

    @discord.ui.button(label="Datum/Uhrzeit", style=discord.ButtonStyle.secondary, row=3)
    async def datetime_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DateTimeModal(self))

    @discord.ui.button(label="Absenden", style=discord.ButtonStyle.success, row=3)
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        s = self.state
        if not all([s.cup_round, s.match_label, s.player1, s.player2, s.mode, s.date_str, s.time_str]):
            await interaction.response.send_message("Es fehlen noch Angaben.", ephemeral=True)
            return

        if s.match_row_index == 0:
            await interaction.response.send_message("Es wurde kein gültiges offenes Cup-Spiel gefunden.", ephemeral=True)
            return

        try:
            start_dt = parse_berlin_datetime(s.date_str, s.time_str)
            end_dt = start_dt + timedelta(hours=2)
            location = build_multistream_url(s.player1, s.player2)
            title = f"TFL Cup {s.cup_round} | {s.player1} vs. {s.player2} | {s.mode}"

            await create_scheduled_event(
                interaction.guild,
                title,
                location,
                start_dt,
                end_dt,
                f"TFL Cup {s.cup_round} zwischen {s.player1} und {s.player2}.",
            )

            await interaction.response.send_message(f"✅ Event erstellt:\n**{title}**", ephemeral=True)
        except Exception as e:
            traceback.print_exc()
            await interaction.response.send_message(f"❌ Event konnte nicht erstellt werden: {e}", ephemeral=True)

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.danger, row=3)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = MatchCenterStartView(self.cog, self.author_id)
        await interaction.response.edit_message(content="## TFL Matchcenter", view=view)


# =========================================================
# CUP RESULT
# =========================================================
class CupResultView(BaseFlowView):
    def __init__(self, cog, author_id: int):
        super().__init__(cog, author_id)
        self.add_item(CupRoundSelect())
        self.rebuild_match_select()
        self.rebuild_winner_select()

    def rebuild_match_select(self):
        for item in list(self.children):
            if isinstance(item, CupMatchSelect):
                self.remove_item(item)
        self.add_item(CupMatchSelect(get_open_cup_matches(self.state.cup_round)))

    def rebuild_winner_select(self):
        for item in list(self.children):
            if isinstance(item, (CupWinnerNormalSelect, CupWinnerSeriesSelect)):
                self.remove_item(item)

        if self.state.cup_round in {"Semifinals", "Finals"}:
            self.add_item(CupWinnerSeriesSelect())
        else:
            self.add_item(CupWinnerNormalSelect())

    @discord.ui.button(label="Raceroom-Link", style=discord.ButtonStyle.secondary, row=3)
    async def racetime_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RacetimeModal(self))

    @discord.ui.button(label="Absenden", style=discord.ButtonStyle.success, row=3)
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        s = self.state
        if not all([s.cup_round, s.match_row_index, s.match_label, s.player1, s.player2, s.winner_value, s.racetime_link]):
            await interaction.response.send_message("Es fehlen noch Angaben.", ephemeral=True)
            return

        if s.match_row_index == 0:
            await interaction.response.send_message("Es wurde kein gültiges offenes Cup-Spiel gefunden.", ephemeral=True)
            return

        try:
            result = result_cup_from_value(s.cup_round, s.winner_value)
            timestamp = now_berlin_str()
            entered_meta = f"{interaction.user} | {timestamp}"

            loop = asyncio.get_event_loop()
            if s.cup_round in {"Semifinals", "Finals"}:
                await loop.run_in_executor(
                    None,
                    write_cup_result_series,
                    s.match_row_index,
                    result,
                    s.racetime_link,
                    entered_meta,
                )
            else:
                await loop.run_in_executor(
                    None,
                    write_cup_result_standard,
                    s.match_row_index,
                    result,
                    s.racetime_link,
                    entered_meta,
                )

            post_text = cup_result_post_text(
                timestamp,
                s.cup_round,
                s.player1,
                s.player2,
                result,
                s.racetime_link,
            )
            await send_result_post(interaction.guild, post_text)

            await interaction.response.send_message("✅ Cup-Ergebnis gespeichert und gepostet.", ephemeral=True)
        except Exception as e:
            traceback.print_exc()
            await interaction.response.send_message(f"❌ Fehler beim Speichern des Cup-Ergebnisses: {e}", ephemeral=True)

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.danger, row=3)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = MatchCenterStartView(self.cog, self.author_id)
        await interaction.response.edit_message(content="## TFL Matchcenter", view=view)


# =========================================================
# COG
# =========================================================
class MatchCenterCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="matchcenter", description="Öffnet das TFL Matchcenter.")
    async def matchcenter(self, interaction: discord.Interaction):
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("❌ Konnte Mitgliedsdaten nicht lesen.", ephemeral=True)
            return

        if not has_tfl_role(member):
            await interaction.response.send_message("⛔ Du hast keine Berechtigung diesen Befehl zu nutzen.", ephemeral=True)
            return

        try:
            view = MatchCenterStartView(self, interaction.user.id)
            await interaction.response.send_message("## TFL Matchcenter", view=view, ephemeral=True)
        except Exception:
            traceback.print_exc()
            if interaction.response.is_done():
                await interaction.followup.send("❌ Fehler beim Öffnen des Matchcenters.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Fehler beim Öffnen des Matchcenters.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(MatchCenterCog(bot))
