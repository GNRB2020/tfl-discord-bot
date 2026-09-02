import os
print("BOT FILE PATH:", os.path.abspath(__file__))

import asyncio
import datetime
import sys
import traceback
from datetime import datetime as dt, timedelta

import aiohttp
import discord
import gspread
import pytz
from aiohttp import web
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials

from sheet_guard import (
    col_values_cached,
    get_all_values_cached,
    sheet_write_call,
)
from tfnl_ranking_api_sync import publish_tfnl_rankings_to_api

print("🔍 DEBUG: bot.py wurde geladen")

BOT_PERFORMANCE_VERSION = "bot-performance-v5-matchcenter-shared-sheets"
print(f"[BOT] geladen: {BOT_PERFORMANCE_VERSION}")


def _fatal(e: Exception):
    print("FATAL ERROR BEFORE on_ready():", e)
    traceback.print_exc()
    sys.exit(1)


# =========================================================
# .env laden / Konfiguration
# =========================================================
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0"))
EVENT_CHANNEL_ID = int(os.getenv("EVENT_CHANNEL_ID", os.getenv("DISCORD_EVENT_CHANNEL_ID", "0")))
RESTREAM_CHANNEL_ID = int(os.getenv("RESTREAM_CHANNEL_ID", "0"))
SHOWRESTREAMS_CHANNEL_ID = int(os.getenv("SHOWRESTREAMS_CHANNEL_ID", "1277949546650931241"))
CREDS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", "0"))
TFL_ROLE_ID = int(os.getenv("TFL_ROLE_ID", "0"))
RESULTS_CHANNEL_ID = int(os.getenv("RESULTS_CHANNEL_ID", "1275077562984435853"))
ZSR_RESTREAM_URL = os.getenv("ZSR_RESTREAM_URL", "https://www.twitch.tv/zeldaspeedruns")
SPREADSHEET_TITLE = os.getenv("SPREADSHEET_TITLE", "Season #4 - Spielbetrieb")
API_BASE = os.getenv("TFL_API_BASE", "https://tfl-discord-api.onrender.com")

print("DEBUG CREDS_FILE =", CREDS_FILE)

BERLIN_TZ = pytz.timezone("Europe/Berlin")
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

BOT_SHEET_CACHE_TTL_SECONDS = int(os.getenv("BOT_SHEET_CACHE_TTL_SECONDS", "90"))
BOT_PLAYER_CACHE_TTL_SECONDS = int(os.getenv("BOT_PLAYER_CACHE_TTL_SECONDS", "120"))
BOT_WEB_RESULTS_CACHE_TTL_SECONDS = int(os.getenv("BOT_WEB_RESULTS_CACHE_TTL_SECONDS", "60"))

# =========================================================
# Discord Client erstellen
# =========================================================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

print("DEBUG Intents:", intents)


DISABLED_MANUAL_COMMANDS = {
    "matchcenter",
    "showpicks",
    "result",
    "asyncplay",
    "cupresult",
    "cuptermin",
    "pick",
    "quali",
    "rest",
    "signup",
    "streich",
    "termin",
}


def remove_disabled_manual_commands(tree: app_commands.CommandTree, guild: discord.Object):
    """
    Entfernt nur die manuelle Slash-Command-Registrierung.
    Die Extensions bleiben geladen, damit Views/Buttons aus /player weiter funktionieren.
    """
    for cmd_name in DISABLED_MANUAL_COMMANDS:
        removed_global = tree.remove_command(cmd_name)
        removed_guild = tree.remove_command(cmd_name, guild=guild)

        if removed_global or removed_guild:
            print(f"🧹 Slash-Command deaktiviert: /{cmd_name}")


class TFLBot(commands.Bot):
    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)

        extensions = [
            "signup",
            "schedule",
            #"ladder",    #deaktiviert
            "matchcenter",
            "asnyc",
            "player",
            "restream_requests",
        ]

        for ext in extensions:
            try:
                await self.load_extension(ext)
                print(f"✅ {ext}.py geladen")
            except Exception:
                print(f"❌ FEHLER beim Laden von {ext}.py:")
                traceback.print_exc()

        print("TREE GLOBAL VOR COPY:", [cmd.name for cmd in self.tree.get_commands()])
        print("TREE GUILD VOR COPY:", [cmd.name for cmd in self.tree.get_commands(guild=guild)])

        self.tree.copy_global_to(guild=guild)

        print("TREE GUILD NACH COPY:", [cmd.name for cmd in self.tree.get_commands(guild=guild)])

        remove_disabled_manual_commands(self.tree, guild)

        print("TREE GUILD VOR SYNC:", [cmd.name for cmd in self.tree.get_commands(guild=guild)])

        synced = await self.tree.sync(guild=guild)

        print("✅ Slash Commands synchronisiert:")
        for cmd in synced:
            print(f" - /{cmd.name}")


client = TFLBot(command_prefix="!", intents=intents)
tree = client.tree


# =========================================================
# Google Sheets
# =========================================================
SHEETS_ENABLED = True
GC = None
WB = None
_WORKSHEET_CACHE_BY_NAME: dict[str, gspread.Worksheet] = {}

try:
    CREDS = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    GC = gspread.authorize(CREDS)
    WB = GC.open(SPREADSHEET_TITLE)
    print("✅ Google Sheets verbunden (ohne Master-Tab)")
except Exception as e:
    SHEETS_ENABLED = False
    WB = None
    print(f"⚠️ Google Sheets deaktiviert: {e}")


def sheets_required():
    if not SHEETS_ENABLED or WB is None:
        raise RuntimeError("Google Sheets nicht verbunden (SHEETS_ENABLED=False).")


def get_div_ws(div_number: str):
    sheets_required()
    sheet_name = f"{div_number}.DIV"

    if sheet_name in _WORKSHEET_CACHE_BY_NAME:
        return _WORKSHEET_CACHE_BY_NAME[sheet_name]

    ws = WB.worksheet(sheet_name)
    _WORKSHEET_CACHE_BY_NAME[sheet_name] = ws
    return ws


def sheet_name(ws, fallback: str = "Sheet") -> str:
    return getattr(ws, "title", fallback)


def invalidate_prefixes_for_ws(ws, fallback: str = "Sheet") -> list[str]:
    name = sheet_name(ws, fallback)
    return [
        f"records:{name}",
        f"values:{name}",
        f"row:{name}:",
        f"col:{name}:",
        f"cell:{name}:",
    ]


def get_div_values(div_number: str, force_refresh: bool = False):
    ws = get_div_ws(div_number)
    return get_all_values_cached(
        lambda: ws,
        sheet_name=sheet_name(ws, f"{div_number}.DIV"),
        ttl_seconds=BOT_SHEET_CACHE_TTL_SECONDS,
        force_refresh=force_refresh,
    )


def _cell(row, idx0):
    return row[idx0].strip() if 0 <= idx0 < len(row) else ""


DIV_COL_LEFT = 4      # D
DIV_COL_MARKER = 5    # E
DIV_COL_RIGHT = 6     # F


# =========================================================
# Twitch-Namen Mapping
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
    "malxantholos": "malxantholos",
    "robg": "robg92",
    "mrslexy": "mrslexy",
    "der_kai01": "der_Kai01",
    "satono92": "satono92",
    "dergoatbuster": "dergoatbuster",
    "snack": "snack",
    "hardy": "try_hardyy",
}


# =========================================================
# Rollen-Checks
# =========================================================
def has_admin_role(member: discord.Member) -> bool:
    if not isinstance(member, discord.Member):
        return False
    if ADMIN_ROLE_ID == 0:
        return False
    return any(r.id == ADMIN_ROLE_ID for r in member.roles)


def has_tfl_role(member: discord.Member) -> bool:
    if not isinstance(member, discord.Member):
        return False
    if TFL_ROLE_ID == 0:
        return False
    return any(r.id == TFL_ROLE_ID for r in member.roles)


# =========================================================
# Minimaler Webserver für Joomla/Frontend
# =========================================================
_webserver_started = False
_webapp_runner: web.AppRunner | None = None

_API_CACHE = {
    "upcoming": {"ts": None, "data": []},
    "results": {"ts": None, "data": []},
}

_RESULTS_DB_CACHE: dict[str, list[dict]] = {}


def clear_results_db_cache():
    _RESULTS_DB_CACHE.clear()


def _event_location(ev: discord.ScheduledEvent) -> str | None:
    try:
        if getattr(ev, "entity_metadata", None):
            loc = getattr(ev.entity_metadata, "location", None)
            if loc:
                return loc
        if getattr(ev, "location", None):
            return ev.location
        if getattr(ev, "channel", None) and ev.channel:
            return ev.channel.name
    except Exception:
        pass
    return None


def parse_div_result_date(date_text: str):
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.datetime.strptime(date_text, fmt)
        except Exception:
            pass
    return datetime.datetime.min


def get_results_db_items(division: str) -> list[dict]:
    if division in _RESULTS_DB_CACHE:
        return _RESULTS_DB_CACHE[division]

    rows = get_div_values(division)
    items = []

    for row in rows[1:]:
        date = _cell(row, 1)
        mode = _cell(row, 2)
        p1 = _cell(row, 3)
        score = _cell(row, 4)
        p2 = _cell(row, 5)
        link = _cell(row, 6)
        reporter = _cell(row, 7)

        if score.lower() == "vs" or "vs" in score.lower():
            continue

        if not date or not p1 or not p2:
            continue

        items.append({
            "date": date,
            "player1": p1,
            "score": score,
            "player2": p2,
            "mode": mode,
            "link": link,
            "reporter": reporter,
        })

    items.sort(key=lambda x: parse_div_result_date(x["date"]), reverse=True)
    _RESULTS_DB_CACHE[division] = items
    return items


async def _build_web_app(_client: discord.Client) -> web.Application:
    routes = web.RouteTableDef()

    def add_cors(resp: web.StreamResponse) -> web.StreamResponse:
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "*"
        return resp

    @routes.get("/health")
    async def health(_request: web.Request):
        return add_cors(web.json_response({"status": "ok"}))

    @routes.get("/api/upcoming")
    async def api_upcoming(request: web.Request):
        try:
            n = int(request.query.get("n", "5"))
        except Exception:
            n = 5
        n = max(1, min(20, n))

        cache = _API_CACHE["upcoming"]

        if not cache["data"]:
            return add_cors(web.json_response({"items": [], "loading": True}))

        data = sorted(cache["data"], key=lambda x: (x["start"] is None, x["start"]))
        return add_cors(web.json_response({"items": data[:n]}))

    @routes.get("/api/results")
    async def api_results(request: web.Request):
        try:
            n = int(request.query.get("n", "5"))
        except Exception:
            n = 5
        n = max(1, min(20, n))

        cache = _API_CACHE["results"]

        if not cache["data"]:
            return add_cors(web.json_response({"items": [], "loading": True}))

        return add_cors(web.json_response({"items": cache["data"][:n]}))

    @routes.get("/api/results-db")
    async def api_results_db(request: web.Request):
        division = request.query.get("division")

        try:
            limit = int(request.query.get("limit", "336"))
        except Exception:
            limit = 336

        limit = max(1, min(336, limit))

        if division not in ["1", "2", "3", "4", "5", "6"]:
            return add_cors(web.json_response({"items": []}))

        try:
            items = get_results_db_items(division)
            return add_cors(web.json_response({"items": items[:limit]}))
        except Exception as e:
            print(f"[API] results-db ERROR: {e}")
            return add_cors(web.json_response({"items": []}))

    app = web.Application()
    app.add_routes(routes)
    return app


async def start_webserver(_client: discord.Client):
    global _webserver_started, _webapp_runner

    if _webserver_started:
        return

    _webserver_started = True
    app = await _build_web_app(_client)

    runner = web.AppRunner(app)
    await runner.setup()
    _webapp_runner = runner

    port = int(os.getenv("PORT", "10000"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    print(f"[WEB] running on 0.0.0.0:{port} endpoints: /health /api/upcoming /api/results /api/results-db")


# =========================================================
# Ergebnis-/DIV-Helfer
# =========================================================
def load_open_games_for_result(div_number: str):
    rows = get_div_values(div_number)

    out = []
    for idx, row in enumerate(rows, start=1):
        if idx == 1:
            continue

        heim = _cell(row, DIV_COL_LEFT - 1)
        marker = _cell(row, DIV_COL_MARKER - 1)
        gast = _cell(row, DIV_COL_RIGHT - 1)

        if (heim or gast) and marker.lower() == "vs":
            out.append({"row_index": idx, "heim": heim, "auswaerts": gast})

    return out


def _collect_players_from_rows(rows) -> list[str]:
    seen = set()
    players = []
    d_idx0 = DIV_COL_LEFT - 1
    f_idx0 = DIV_COL_RIGHT - 1

    for row in rows[1:]:
        p_left = _cell(row, d_idx0)
        p_right = _cell(row, f_idx0)

        for p in (p_left, p_right):
            if not p:
                continue
            low = p.lower()
            if low not in seen:
                seen.add(low)
                players.append(p)

    return players


def list_div_players(div_number: str):
    try:
        rows = get_div_values(div_number)
        return _collect_players_from_rows(rows)
    except Exception:
        return []


def list_streichungen(div_number: str):
    rows = get_div_values(div_number)

    eintraege = []
    max_row_index = min(9, len(rows))

    for idx in range(1, max_row_index):
        row = rows[idx]
        spieler = _cell(row, 11)
        modus_m = _cell(row, 12)
        modus_n = _cell(row, 13)

        if spieler:
            eintraege.append({"spieler": spieler, "modus_m": modus_m, "modus_n": modus_n})

    return eintraege


def list_rest_players(div_number: str) -> list[str]:
    rows = get_div_values(div_number)

    players = []
    seen = set()
    max_row_index = min(9, len(rows))

    for idx in range(1, max_row_index):
        row = rows[idx]
        name = _cell(row, 11)
        if not name:
            continue
        low = name.lower()
        if low not in seen:
            seen.add(low)
            players.append(name)

    return players


def list_restprogramm(div_number: str, player_name: str):
    rows = get_div_values(div_number)
    matches = []
    target = player_name.lower()

    for idx, row in enumerate(rows[1:], start=2):
        heim = _cell(row, DIV_COL_LEFT - 1)
        marker = _cell(row, DIV_COL_MARKER - 1)
        gast = _cell(row, DIV_COL_RIGHT - 1)

        if marker.lower() != "vs":
            continue

        if heim.lower() == target or gast.lower() == target:
            matches.append({"row_index": idx, "heim": heim, "gast": gast})

    return matches


def batch_update_result(ws, row_index, now_str, mode_val, ergebnis, raceroom_val, reporter_name):
    reqs = [
        {"range": f"B{row_index}:C{row_index}", "values": [[now_str, mode_val]]},
        {"range": f"E{row_index}:E{row_index}", "values": [[ergebnis]]},
        {"range": f"G{row_index}:G{row_index}", "values": [[raceroom_val]]},
        {"range": f"H{row_index}:H{row_index}", "values": [[reporter_name]]},
    ]
    sheet_write_call(lambda: ws.batch_update(reqs), invalidate_prefixes=invalidate_prefixes_for_ws(ws))
    clear_results_db_cache()


# =========================================================
# /playerexit Workflow
# =========================================================
def playerexit_apply(div_number: str, quitting_player: str, reporter: str):
    ws = get_div_ws(div_number)
    rows = get_div_values(div_number)

    now_str = dt.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M")
    batch_reqs = []
    strike_cells = []

    for idx, row in enumerate(rows[1:], start=2):
        left_player = _cell(row, DIV_COL_LEFT - 1)
        right_player = _cell(row, DIV_COL_RIGHT - 1)

        lp_match = left_player.lower() == quitting_player.lower() if left_player else False
        rp_match = right_player.lower() == quitting_player.lower() if right_player else False

        if not (lp_match or rp_match):
            continue

        if lp_match:
            result_val = "0:2"
            strike_cells.append(f"D{idx}")
        else:
            result_val = "2:0"
            strike_cells.append(f"F{idx}")

        batch_reqs.append({"range": f"B{idx}:C{idx}", "values": [[now_str, "FF"]]})
        batch_reqs.append({"range": f"E{idx}:E{idx}", "values": [[result_val]]})
        batch_reqs.append({"range": f"G{idx}:G{idx}", "values": [["FF"]]})
        batch_reqs.append({"range": f"H{idx}:H{idx}", "values": [[reporter]]})

    if batch_reqs:
        sheet_write_call(lambda: ws.batch_update(batch_reqs), invalidate_prefixes=invalidate_prefixes_for_ws(ws))
        clear_results_db_cache()

    if strike_cells:
        style = {"textFormat": {"strikethrough": True}}
        for rng in strike_cells:
            try:
                sheet_write_call(lambda rng=rng: ws.format(rng, style), invalidate_prefixes=invalidate_prefixes_for_ws(ws))
            except Exception:
                pass


class PlayerExitDivisionSelect(discord.ui.Select):
    def __init__(self, requester: discord.Member):
        self.requester = requester
        options = [discord.SelectOption(label=f"Division {i}", value=str(i)) for i in range(1, 7)]
        super().__init__(placeholder="Welche Division?", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        div_number = self.values[0]

        try:
            await interaction.response.defer(ephemeral=True, thinking=False)
        except discord.InteractionResponded:
            pass

        players = list_div_players(div_number)

        if not players:
            await interaction.edit_original_response(content=f"Keine Spieler in Division {div_number} gefunden.", view=None)
            return

        view = PlayerExitPlayerSelectView(division=div_number, players=players, requester=self.requester)
        await interaction.edit_original_response(content=f"Division {div_number} gewählt.\nWelcher Spieler steigt aus?", view=view)


class PlayerExitDivisionSelectView(discord.ui.View):
    def __init__(self, requester: discord.Member, timeout=180):
        super().__init__(timeout=timeout)
        self.add_item(PlayerExitDivisionSelect(requester))


class PlayerExitPlayerSelect(discord.ui.Select):
    def __init__(self, division: str, players, requester: discord.Member):
        self.division = division
        self.players = players
        self.requester = requester
        options = [discord.SelectOption(label=p[:100], value=p[:100]) for p in players[:25]]
        super().__init__(placeholder="Spieler wählen (steigt aus)", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        quitting_player = self.values[0]

        try:
            await interaction.response.defer(ephemeral=True, thinking=False)
        except discord.InteractionResponded:
            pass

        try:
            playerexit_apply(self.division, quitting_player, str(self.requester))
            await interaction.followup.send(
                content=(
                    f"✅ `{quitting_player}` in Division {self.division} ausgetragen.\n"
                    "Alle Spiele (auch bereits gespielte) wurden als FF gegen ihn gewertet "
                    "und der Name wurde durchgestrichen."
                ),
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(content=f"❌ Fehler beim Austragen: {e}", ephemeral=True)


class PlayerExitPlayerSelectView(discord.ui.View):
    def __init__(self, division: str, players, requester: discord.Member, timeout=180):
        super().__init__(timeout=timeout)
        self.add_item(PlayerExitPlayerSelect(division, players, requester))


# =========================================================
# Spielplan / Round Robin
# =========================================================
def spielplan_read_players(div_number: str) -> list[str]:
    ws = get_div_ws(div_number)
    values = get_all_values_cached(
        lambda: ws,
        sheet_name=sheet_name(ws, f"{div_number}.DIV"),
        ttl_seconds=BOT_PLAYER_CACHE_TTL_SECONDS,
    )

    players = []
    seen = set()

    for row in values[1:10]:
        name = _cell(row, 11)
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        players.append(name)

    if len(players) not in (8, 9):
        raise RuntimeError(
            f"Für Division {div_number} müssen genau 8 oder 9 Spieler in Spalte L stehen "
            f"(8er: L2:L9, 9er: L2:L10). Gefunden: {len(players)}."
        )

    return players


def spielplan_build_rounds(players: list[str]) -> list[list[tuple[str, str]]]:
    work = list(players)
    if len(work) % 2 == 1:
        work.append("BYE")

    n = len(work)
    half = n // 2
    rotation = work[:]
    rounds = []

    for _r in range(n - 1):
        left_half = rotation[:half]
        right_half = rotation[half:]
        right_rev = right_half[::-1]
        day_pairs = []

        for i in range(half):
            p1 = left_half[i]
            p2 = right_rev[i]
            if p1 == "BYE" or p2 == "BYE":
                continue
            day_pairs.append((p1, p2))

        rounds.append(day_pairs)
        fixed = rotation[0]
        tail = rotation[1:]
        tail = [tail[-1]] + tail[:-1]
        rotation = [fixed] + tail

    return rounds


def spielplan_build_matches(players: list[str]) -> list[list[tuple[str, str]]]:
    hinrunde = spielplan_build_rounds(players)
    rueckrunde = []
    for day in hinrunde:
        rueckrunde.append([(away, home) for (home, away) in day])
    return hinrunde + rueckrunde


def spielplan_find_next_free_row(ws):
    col_d = col_values_cached(
        lambda: ws,
        sheet_name=sheet_name(ws),
        col=4,
        ttl_seconds=BOT_SHEET_CACHE_TTL_SECONDS,
    )

    for idx_1based, val in enumerate(col_d, start=1):
        if idx_1based == 1:
            continue
        if val.strip() == "":
            return idx_1based

    return len(col_d) + 1


def spielplan_write(ws, rounds: list[list[tuple[str, str]]]):
    start_row = spielplan_find_next_free_row(ws)
    laufende_nummer = 1
    rows_to_write = []

    for matches_in_round in rounds:
        for (home, away) in matches_in_round:
            row_data = [""] * 9
            row_data[0] = str(laufende_nummer)
            row_data[3] = home
            row_data[4] = "vs"
            row_data[5] = away
            rows_to_write.append(row_data)
            laufende_nummer += 1

    if not rows_to_write:
        return 0

    end_row = start_row + len(rows_to_write) - 1
    cell_range = f"A{start_row}:I{end_row}"
    sheet_write_call(lambda: ws.update(cell_range, rows_to_write), invalidate_prefixes=invalidate_prefixes_for_ws(ws))
    return len(rows_to_write)


# =========================================================
# Restream-Helfer
# =========================================================
_WEEKDAY_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def _format_start_dt(ev: discord.ScheduledEvent, include_weekday: bool = False) -> str:
    start = ev.start_time
    if not start:
        return "ohne Startzeit"

    start_local = start.astimezone(BERLIN_TZ)
    date_str = start_local.strftime("%d.%m.%Y")
    time_str = start_local.strftime("%H:%M")

    if include_weekday:
        wd = _WEEKDAY_DE[start_local.weekday()]
        return f"{wd}, {date_str} {time_str}"

    return f"{date_str} {time_str}"


def _format_event_line_for_post(ev: discord.ScheduledEvent, include_weekday: bool = False) -> str:
    dt_str = _format_start_dt(ev, include_weekday=include_weekday)
    loc = _event_location(ev) or "kein Link"
    loc_display = f"<{loc}>" if loc != "kein Link" else loc
    name = ev.name or "Unbenanntes Event"
    return f"• {name} – {dt_str} – {loc_display}"


def _filter_future_events(events: list[discord.ScheduledEvent], now_utc: datetime.datetime):
    return [
        ev for ev in events
        if ev.status in (discord.EventStatus.scheduled, discord.EventStatus.active)
        and ev.start_time
        and ev.start_time > now_utc
    ]


def _is_restream(ev: discord.ScheduledEvent) -> bool:
    name = (ev.name or "").lower()
    return "(restream)" in name or name.startswith("restream ")


def _format_event_list(title: str, events: list[discord.ScheduledEvent], now_utc: datetime.datetime, include_weekday: bool = False) -> str:
    events_sorted = sorted(events, key=lambda e: e.start_time or now_utc)
    lines = [title, ""]
    lines.extend(_format_event_line_for_post(ev, include_weekday=include_weekday) for ev in events_sorted)
    return "\n".join(lines)


# =========================================================
# Hintergrund-Refresher + API Sync
# =========================================================
async def refresh_api_cache(_client):
    await _client.wait_until_ready()
    await asyncio.sleep(20)
    print("[CACHE] Hintergrund-Refresher gestartet (stabiler 5-Minuten-Modus)")

    while not _client.is_closed():
        now = datetime.datetime.now(datetime.timezone.utc)

        try:
            guild = _client.get_guild(GUILD_ID) or await _client.fetch_guild(GUILD_ID)
            events = await guild.fetch_scheduled_events()

            upcoming = []
            for ev in events:
                if ev.status in (discord.EventStatus.scheduled, discord.EventStatus.active):
                    upcoming.append({
                        "id": ev.id,
                        "name": ev.name,
                        "start": ev.start_time.isoformat() if ev.start_time else None,
                        "end": ev.end_time.isoformat() if ev.end_time else None,
                        "location": _event_location(ev),
                        "url": f"https://discord.com/events/{GUILD_ID}/{ev.id}",
                    })

            _API_CACHE["upcoming"]["ts"] = now
            _API_CACHE["upcoming"]["data"] = upcoming
            print(f"[CACHE] Upcoming aktualisiert ({len(upcoming)} Events)")

        except Exception as e:
            print(f"[CACHE] Fehler UPCOMING: {e}")

        try:
            ch = _client.get_channel(RESULTS_CHANNEL_ID)

            if isinstance(ch, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
                new_results = []

                async for m in ch.history(limit=400):
                    new_results.append({
                        "id": m.id,
                        "author": str(m.author),
                        "time": m.created_at.astimezone(BERLIN_TZ).isoformat(),
                        "content": m.content,
                        "jump_url": m.jump_url,
                    })

                if new_results:
                    _API_CACHE["results"]["ts"] = now
                    _API_CACHE["results"]["data"] = new_results
                    print(f"[CACHE] Results aktualisiert ({len(new_results)} Einträge)")
                else:
                    print("[CACHE] Results NICHT aktualisiert (0 Einträge)")
            else:
                print("[CACHE] Ergebnischannel nicht gefunden oder falscher Typ")

        except Exception as e:
            print(f"[CACHE] Fehler RESULTS: {e}")

        try:
            await push_updates_to_api()
            print("[SYNC] API-Sync durchgeführt")
        except Exception as e:
            print("[SYNC] Fehler beim API-Sync:", e)

        await asyncio.sleep(300)


async def push_updates_to_api():
    async with aiohttp.ClientSession() as session:
        try:
            payload_upcoming = {"items": _API_CACHE["upcoming"]["data"]}
            async with session.post(
                f"{API_BASE}/api/update/upcoming",
                json=payload_upcoming,
                timeout=5,
            ) as r:
                print("[PUSH] upcoming ->", r.status)

        except Exception as e:
            print("[PUSH] Fehler upcoming:", e)

        try:
            payload_results = {"items": _API_CACHE["results"]["data"]}
            async with session.post(
                f"{API_BASE}/api/update/results",
                json=payload_results,
                timeout=5,
            ) as r:
                print("[PUSH] results ->", r.status)

        except Exception as e:
            print("[PUSH] Fehler results:", e)

    try:
        ranking_result = await publish_tfnl_rankings_to_api(api_base=API_BASE)

        print(
            "[PUSH] tfnl frontend -> "
            f"season={ranking_result.get('season_status')} "
            f"overall={ranking_result.get('overall_status')} "
            f"results={ranking_result.get('results_status')} "
            f"season_count={ranking_result.get('season_count')} "
            f"overall_count={ranking_result.get('overall_count')} "
            f"results_count={ranking_result.get('results_count')}"
        )

    except Exception as e:
        print("[PUSH] Fehler tfnl frontend:", e)

    print("[SYNC] push_updates_to_api abgeschlossen")
    print("Upcoming Count:", len(_API_CACHE["upcoming"]["data"]))
    print("Results Count:", len(_API_CACHE["results"]["data"]))


# =========================================================
# Slash Commands
# =========================================================
@tree.command(name="add", description="Fügt einen neuen Spieler zur Liste hinzu")
@app_commands.describe(name="Name", twitch="Twitch-Username")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def add(interaction: discord.Interaction, name: str, twitch: str):
    key = name.strip().lower()
    TWITCH_MAP[key] = twitch.strip()
    await interaction.response.send_message(f"✅ `{key}` wurde mit Twitch `{twitch.strip()}` hinzugefügt.", ephemeral=True)


@tree.command(name="playerexit", description="Spieler aus Division austragen und alle Spiele als FF gegen ihn werten (nur Admin)")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def playerexit(interaction: discord.Interaction):
    member = interaction.user
    if not isinstance(member, discord.Member):
        await interaction.response.send_message("❌ Konnte Mitgliedsdaten nicht lesen.", ephemeral=True)
        return

    if not has_admin_role(member):
        await interaction.response.send_message("⛔ Du hast keine Berechtigung diesen Befehl zu nutzen.", ephemeral=True)
        return

    view = PlayerExitDivisionSelectView(requester=member)
    await interaction.response.send_message("📤 Spieler-Exit starten:\nBitte Division auswählen.", view=view, ephemeral=True)


@tree.command(name="help", description="Zeigt eine Übersicht aller verfügbaren Befehle")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 TFL Bot Hilfe", description="Aktive Befehle:", color=0x00FFCC)
    embed.add_field(name="/player", value="Zentrales Spielermenü für Planung, Ergebnisse, Qualifikation, Saisonmeldung und weitere Funktionen.", inline=False)
    embed.add_field(name="/playerexit", value="Admin: Spieler austragen (alle Spiele FF gegen ihn, Name durchgestrichen).", inline=False)
    embed.add_field(name="/spielplan", value="Admin: Hin- & Rückrunde erzeugen und ins DIV-Sheet schreiben.", inline=False)
    embed.add_field(name="/restreams", value="Zeigt alle zukünftigen Restream-Events.", inline=False)
    embed.add_field(name="/add", value="Spieler → TWITCH_MAP hinzufügen (nicht persistent).", inline=False)
    embed.add_field(name="/sync", value="Admin: Slash-Commands synchronisieren.", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="spielplan", description="(Admin) Erstellt Hin-/Rückrunde (jeder gg. jeden) und schreibt alles ins Sheet")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(division="Welche Division?")
@app_commands.choices(division=[app_commands.Choice(name=f"Division {i}", value=str(i)) for i in range(1, 7)])
async def spielplan(interaction: discord.Interaction, division: app_commands.Choice[str]):
    member = interaction.user
    if not isinstance(member, discord.Member):
        await interaction.response.send_message("❌ Konnte Mitgliedsdaten nicht lesen.", ephemeral=True)
        return

    if not has_admin_role(member):
        await interaction.response.send_message("⛔ Du hast keine Berechtigung diesen Befehl zu nutzen.", ephemeral=True)
        return

    try:
        players = spielplan_read_players(division.value)
        if len(players) < 2:
            await interaction.response.send_message(f"❌ Zu wenig Spieler in Division {division.value} gefunden.", ephemeral=True)
            return

        rounds = spielplan_build_matches(players)
        ws = get_div_ws(division.value)
        written = spielplan_write(ws, rounds)

        preview_round = rounds[0] if rounds else []
        preview_lines = [f"{h} vs {a}" for (h, a) in preview_round[:6]]
        preview_txt = "\n".join(preview_lines) if preview_lines else "(leer)"

        msg = (
            f"✅ Spielplan für Division {division.value} erstellt.\n"
            f"{written} Zeilen ins Tab `{division.value}.DIV` geschrieben.\n\n"
            f"Erster Spieltag (Beispiel):\n```{preview_txt}\n...```"
        )
        await interaction.response.send_message(msg, ephemeral=True)

    except Exception as e:
        await interaction.response.send_message(f"❌ Fehler bei /spielplan: {e}", ephemeral=True)


@tree.command(name="sync", description="(Admin) Slash-Commands für diese Guild synchronisieren")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def sync_cmd(interaction: discord.Interaction):
    member = interaction.user
    if not isinstance(member, discord.Member) or not has_admin_role(member):
        await interaction.response.send_message("⛔ Keine Berechtigung.", ephemeral=True)
        return

    try:
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = discord.Object(id=GUILD_ID)
        remove_disabled_manual_commands(tree, guild)
        synced = await tree.sync(guild=guild)
        names = ", ".join(sorted(c.name for c in synced))
        await interaction.followup.send(f"✅ Synced {len(synced)} Commands: {names}", ephemeral=True)
    except Exception as e:
        print(f"[SYNC] Fehler: {e}")
        try:
            await interaction.followup.send("❌ Sync ist fehlgeschlagen. Bitte Logs prüfen.", ephemeral=True)
        except Exception:
            pass


@tree.command(name="restreams", description="Zeigt alle zukünftigen Restream-Events")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def restreams(interaction: discord.Interaction):
    try:
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("❌ Konnte Guild nicht ermitteln.", ephemeral=True)
            return

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        events = await guild.fetch_scheduled_events()
        future_events = _filter_future_events(events, now_utc)
        restream_events = [ev for ev in future_events if _is_restream(ev)]

        if not restream_events:
            await interaction.followup.send("📭 Aktuell sind keine zukünftigen Restream-Events eingetragen.", ephemeral=True)
            return

        text = _format_event_list("🔁 Geplante Restreams (nur Events in der Zukunft)", restream_events, now_utc)
        await interaction.followup.send(text, ephemeral=True)

    except Exception as e:
        await interaction.followup.send(f"❌ Fehler bei /restreams: {e}", ephemeral=True)


# =========================================================
# on_ready
# =========================================================
_client_synced_once = False
_cache_task_started = False


@client.event
async def on_ready():
    print("🔍 DEBUG: on_ready() wurde aufgerufen")
    print("Bot ist online")
    global _client_synced_once, _cache_task_started
    print(f"✅ Eingeloggt als {client.user} (ID: {client.user.id})")

    if not _client_synced_once:
        guild = discord.Object(id=GUILD_ID)
        remove_disabled_manual_commands(tree, guild)
        synced = await tree.sync(guild=guild)
        print("✅ Slash-Befehle synchronisiert:", [cmd.name for cmd in synced])
        _client_synced_once = True

    try:
        asyncio.create_task(start_webserver(client))
        print("🌐 Webserver gestartet (/health, /api/results, /api/upcoming, /api/results-db)")
    except Exception as e:
        print(f"⚠️ Webserver-Start fehlgeschlagen: {e}")

    if not _cache_task_started:
        asyncio.create_task(refresh_api_cache(client))
        _cache_task_started = True
        print("♻️ Background cache refresher gestartet")

    print("🤖 Bot bereit")


if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN fehlt.")

client.run(TOKEN)
