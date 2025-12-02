import discord
import pytz
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import os
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import asyncio
import re
from aiohttp import web
from datetime import datetime as dt, timezone, timedelta

# =========================================================
# .env laden / Konfiguration
# =========================================================
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))
EVENT_CHANNEL_ID = int(os.getenv("EVENT_CHANNEL_ID", os.getenv("DISCORD_EVENT_CHANNEL_ID", "0")))
RESTREAM_CHANNEL_ID = int(os.getenv("RESTREAM_CHANNEL_ID", "0"))
SHOWRESTREAMS_CHANNEL_ID = int(os.getenv("SHOWRESTREAMS_CHANNEL_ID", "1277949546650931241"))
CREDS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

# feste Role-IDs aus ENV (müssen gesetzt sein)
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", "0"))
TFL_ROLE_ID = int(os.getenv("TFL_ROLE_ID", "0"))

# Ergebnis-Channel
RESULTS_CHANNEL_ID = int(os.getenv("RESULTS_CHANNEL_ID", "1275077562984435853"))

# Zeitzone
BERLIN_TZ = pytz.timezone("Europe/Berlin")

# Standard-Link für ZSR-Stream (kann per ENV überschrieben werden)
ZSR_RESTREAM_URL = os.getenv("ZSR_RESTREAM_URL", "https://www.twitch.tv/zeldaspeedruns")

# Flags für tägliche Auto-Posts (Datum in Berlin-Zeit)
_last_restreamable_post_date = None  # 04:00 Uhr – #restreamable-spiele
_last_restreams_post_date = None     # 04:30 Uhr – #restreams

# =========================================================
# Web-API: Ergebnis-Parser (für evtl. spätere Nutzung)
# =========================================================

SCORE_RE = re.compile(
    r"""^\s*
        (?P<pl>.+?)                    # Spieler links
        \s+(?P<sl>\d+)\s*[:\-]\s*(?P<sr>\d+)\s+  # Score X:Y oder X-Y
        (?P<pr>.+?)                    # Spieler rechts
        (?:\s*\|\s*(?P<meta>.*))?      # optionale Meta "key: value | key: value"
        \s*$""",
    re.IGNORECASE | re.VERBOSE,
)


def parse_result_message(text: str):
    text = text.strip()
    text = re.sub(r"^\s*\d{1,2}\.\d{1,2}\.\d{2,4}\s*[-–]\s*", "", text)

    m = SCORE_RE.match(text)
    if not m:
        return None

    pl = m.group("pl").strip()
    pr = m.group("pr").strip()
    sl = m.group("sl").strip()
    sr = m.group("sr").strip()
    meta = (m.group("meta") or "").strip()

    out = {"pl": pl, "pr": pr, "sl": sl, "sr": sr, "mode": "", "venue": ""}

    if meta:
        for seg in [s.strip() for s in meta.split("|") if s.strip()]:
            if ":" in seg:
                key, val = seg.split(":", 1)
                key = key.strip().lower()
                val = val.strip()
                if key in ("modus", "mode"):
                    out["mode"] = val
                elif key in ("venue", "ort", "location"):
                    out["venue"] = val
            else:
                seg_clean = seg.strip("() ")
                if seg_clean and not out["mode"]:
                    out["mode"] = seg_clean

    return out


# =========================================================
# Discord-Client + Intents
# =========================================================
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
client = commands.Bot(command_prefix="/", intents=intents)
tree = client.tree

print(f"[INTENTS] members={intents.members}, message_content={intents.message_content}")

# --- API-Cache für /api/upcoming und /api/results ---
_API_CACHE = {
    "upcoming": {"ts": None, "data": []},
    "results": {"ts": None, "data": []},
}
API_CACHE_TTL = datetime.timedelta(minutes=10)

# =========================================================
# Minimaler Webserver für Joomla/Frontend
# =========================================================

_webserver_started = False
_webapp_runner: web.AppRunner | None = None


def _event_location(ev: discord.ScheduledEvent) -> str | None:
    try:
        if getattr(ev, "entity_metadata", None) and ev.entity_metadata:
            if getattr(ev.entity_metadata, "location", None):
                return ev.entity_metadata.location
        if getattr(ev, "location", None):
            return ev.location
        if getattr(ev, "channel", None) and ev.channel:
            return getattr(ev.channel, "name", None)
    except Exception:
        pass
    return None


async def _build_web_app(client: discord.Client) -> web.Application:
    routes = web.RouteTableDef()

    def add_cors(resp: web.StreamResponse) -> web.StreamResponse:
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "*"
        return resp

    @routes.get("/health")
    async def health(_request: web.Request):
        resp = web.json_response({"status": "ok"})
        return add_cors(resp)

    @routes.get("/api/upcoming")
    async def api_upcoming(request: web.Request):
        try:
            n = int(request.query.get("n", "5"))
        except Exception:
            n = 5
        n = max(1, min(20, n))

        now = datetime.datetime.now(datetime.timezone.utc)
        cache = _API_CACHE["upcoming"]

        print(f"[API] /api/upcoming called (n={n})")

        if cache["ts"] and (now - cache["ts"]) < API_CACHE_TTL and cache["data"]:
            print(f"[API] upcoming: cache HIT ({len(cache['data'])} cached items)")
            data = cache["data"][:n]
            resp = web.json_response({"items": data})
            return add_cors(resp)

        guild = client.get_guild(GUILD_ID)
        if guild is None:
            print(f"[API] upcoming: guild with ID {GUILD_ID} not found")
            resp = web.json_response({"items": []})
            return add_cors(resp)

        try:
            print("[API] upcoming: fetching scheduled events from Discord …")
            events = await asyncio.wait_for(
                guild.fetch_scheduled_events(),
                timeout=5.0,
            )
            print(f"[API] upcoming: fetched {len(events)} events from Discord")
        except asyncio.TimeoutError:
            print("[API] upcoming: TIMEOUT while fetching events")
            if cache["data"]:
                print("[API] upcoming: using OLD cache due to timeout")
                data = cache["data"][:n]
                resp = web.json_response({"items": data})
            else:
                print("[API] upcoming: no cache available, returning empty list")
                resp = web.json_response({"items": []})
            return add_cors(resp)
        except Exception as e:
            print(f"[API] upcoming: ERROR while fetching events: {e!r}")
            resp = web.json_response({"items": []})
            return add_cors(resp)

        data = []
        for ev in events:
            print(f"[API] upcoming: event {ev.id} status={ev.status}")
            if ev.status in (
                discord.EventStatus.scheduled,
                discord.EventStatus.active,
            ):
                data.append(
                    {
                        "id": ev.id,
                        "name": ev.name,
                        "start": ev.start_time.isoformat() if ev.start_time else None,
                        "end": ev.end_time.isoformat() if ev.end_time else None,
                        "location": _event_location(ev),
                        "url": f"https://discord.com/events/{GUILD_ID}/{ev.id}",
                    }
                )

        print(f"[API] upcoming: {len(data)} events nach Filter (scheduled/active)")

        data.sort(key=lambda x: (x["start"] is None, x["start"]))

        cache["ts"] = now
        cache["data"] = data

        resp = web.json_response({"items": data[:n]})
        return add_cors(resp)

    @routes.get("/api/results")
    async def api_results(request: web.Request):
        try:
            n = int(request.query.get("n", "5"))
        except Exception:
            n = 5
        n = max(1, min(20, n))

        now = datetime.datetime.now(datetime.timezone.utc)
        cache = _API_CACHE["results"]

        print(f"[API] /api/results called (n={n})")

        if cache["ts"] and (now - cache["ts"]) < API_CACHE_TTL and cache["data"]:
            print(f"[API] results: cache HIT ({len(cache['data'])} cached items)")
            data = cache["data"][:n]
            resp = web.json_response({"items": data})
            return add_cors(resp)

        ch = client.get_channel(RESULTS_CHANNEL_ID)
        if ch is None or not isinstance(
            ch, (discord.TextChannel, discord.Thread, discord.VoiceChannel),
        ):
            print(f"[API] results: channel {RESULTS_CHANNEL_ID} not found or wrong type")
            resp = web.json_response({"items": []})
            return add_cors(resp)

        items = []
        try:
            print("[API] results: fetching messages …")
            async for m in ch.history(limit=20):
                ts = m.created_at.astimezone(BERLIN_TZ).isoformat()
                items.append(
                    {
                        "id": m.id,
                        "author": str(m.author),
                        "time": ts,
                        "content": m.content,
                        "jump_url": m.jump_url,
                    }
                )
                if len(items) >= n:
                    break
            print(f"[API] results: collected {len(items)} messages")
        except Exception as e:
            print(f"[API] results: ERROR while fetching messages: {e!r}")
            resp = web.json_response({"items": []})
            return add_cors(resp)

        cache["ts"] = now
        cache["data"] = items

        resp = web.json_response({"items": items[:n]})
        return add_cors(resp)

    app = web.Application()
    app.add_routes(routes)
    return app


async def start_webserver(client: discord.Client):
    global _webserver_started, _webapp_runner
    if _webserver_started:
        return
    _webserver_started = True

    app = await _build_web_app(client)
    runner = web.AppRunner(app)
    await runner.setup()
    _webapp_runner = runner
    port = int(os.getenv("PORT", "10000"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(
        f"[WEB] running on 0.0.0.0:{port}   endpoints: /health, /api/upcoming, /api/results",
    )


def today_berlin_date() -> datetime.date:
    return dt.now(BERLIN_TZ).date()


def parse_date(d: str) -> datetime.date:
    return dt.strptime(d, "%d.%m.%Y").date()


def chunk_text(text: str, limit: int = 1900):
    buf, out, count = [], [], 0
    for line in text.splitlines(True):
        if count + len(line) > limit:
            out.append("".join(buf))
            buf, count = [line], len(line)
        else:
            buf.append(line)
            count += len(line)
    if buf:
        out.append("".join(buf))
    return out


async def send_long_message_channel(channel: discord.abc.Messageable, content: str):
    if len(content) <= 2000:
        await channel.send(content)
    else:
        for part in chunk_text(content, limit=1990):
            await channel.send(content=part)


def map_sheet_channel_to_label(val: str) -> str:
    v = (val or "").strip().upper()
    if v == "SGD1":
        return "SG1"
    if v == "SGD2":
        return "SG2"
    return v


# =========================================================
# Twitch-Namen Mapping
# =========================================================
TWITCH_MAP = {
    "gnrb": "gamenrockbuddys",
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
}

# =========================================================
# Google Sheets
# =========================================================
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
SPREADSHEET_TITLE = os.getenv("SPREADSHEET_TITLE", "Season #4 - Spielbetrieb")

SHEETS_ENABLED = True
GC = WB = None

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


def _cell(row, idx0):
    return row[idx0].strip() if 0 <= idx0 < len(row) else ""


# Spaltenkonstanten
DIV_COL_TIMESTAMP = 2  # B
DIV_COL_MODE = 3       # C
DIV_COL_RESULT = 5     # E
DIV_COL_LINK = 7       # G
DIV_COL_REPORTER = 8   # H
DIV_COL_LEFT = 4       # D
DIV_COL_MARKER = 5     # E
DIV_COL_RIGHT = 6      # F

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
# Spieler-Helfer für DIV-Tabs – Spieler IMMER aus L2–L9
# =========================================================
def _collect_players_from_div_ws(ws) -> list[str]:
    """
    Liest alle Spielernamen aus Spalte L2–L9.
    L = Spalte 12.
    Reihenfolge: wie im Sheet, Duplikate entfernt.
    """
    try:
        col_L = ws.col_values(12)  # L
    except Exception as e:
        print(f"[RESTPROGRAMM] Fehler beim Lesen von Spalte L: {e}")
        return []

    seen = set()
    players = []
    # col_L[0] = L1 (Header / leer), daher ab Index 1
    for name in col_L[1:9]:  # L2 bis L9
        if not name:
            continue
        n = name.strip()
        low = n.lower()
        if n and low not in seen:
            seen.add(low)
            players.append(n)

    print(f"[RESTPROGRAMM] _collect_players_from_div_ws -> {players}")
    return players


def get_players_for_div(div: str) -> list[str]:
    """
    Öffnet {div}.DIV und liefert alle Spieler aus L2–L9.
    """
    try:
        sheets_required()
        ws_name = f"{div}.DIV"
        print(f"[RESTPROGRAMM] get_players_for_div: öffne Worksheet '{ws_name}'")
        ws = WB.worksheet(ws_name)
        players = _collect_players_from_div_ws(ws)
        print(f"[RESTPROGRAMM] get_players_for_div({div}) -> {len(players)} Spieler")
        return players
    except Exception as e:
        print(f"[RESTPROGRAMM] get_players_for_div({div}) Fehler: {e}")
        return []


def load_open_from_div_tab(div: str, player_query: str = ""):
    """
    Liest Tab '{div}.DIV' und gibt offene Paarungen zurück.
    D = Spieler 1
    E = Marker ("vs" = offen)
    F = Spieler 2

    Rückgabe: Liste von Tupeln:
      (tab_zeile, "L", spieler_links, spieler_rechts)
    """
    try:
        sheets_required()
        ws_name = f"{div}.DIV"
        print(f"[RESTPROGRAMM] load_open_from_div_tab: öffne Worksheet '{ws_name}'")
        ws = WB.worksheet(ws_name)
        rows = ws.get_all_values()
    except Exception as e:
        print(f"[RESTPROGRAMM] load_open_from_div_tab({div}) Fehler: {e}")
        return []

    out = []
    q = player_query.strip().lower()

    D_idx0 = DIV_COL_LEFT - 1   # 3 -> Spalte D
    E_idx0 = DIV_COL_MARKER - 1 # 4 -> Spalte E
    F_idx0 = DIV_COL_RIGHT - 1  # 5 -> Spalte F

    for r_idx in range(1, len(rows)):  # ab Zeile 2 (Index 1)
        row = rows[r_idx]

        p1 = _cell(row, D_idx0)
        marker = _cell(row, E_idx0)
        p2 = _cell(row, F_idx0)

        if not (p1 or p2):
            continue

        marker_clean = (marker or "").strip().lower()
        # robust gegen "vs", "VS", "vs ", etc.
        if not marker_clean.startswith("vs"):
            continue

        if q:
            if q not in p1.lower() and q not in p2.lower():
                continue

        # r_idx ist 0-basiert auf get_all_values => Zeile = r_idx + 1
        tab_row = r_idx + 1
        out.append((tab_row, "L", p1, p2))

    print(
        f"[RESTPROGRAMM] load_open_from_div_tab({div}, player_query='{player_query}') "
        f"-> {len(out)} offene Spiele",
    )
    return out


async def _rp_show(
    interaction: discord.Interaction,
    division_value: str,
    player_filter: str,
):
    """
    Ersetzt die ursprüngliche /restprogramm-Nachricht durch die Ergebnisliste.
    """
    effective_filter = (
        "" if (not player_filter or player_filter.lower() == "komplett") else player_filter
    )
    try:
        matches = load_open_from_div_tab(division_value, player_query=effective_filter)

        if not matches:
            txt = f"📭 Keine offenen Spiele in **Division {division_value}**."
            if effective_filter:
                txt += f" (Filter: *{effective_filter}*)"
            await interaction.response.edit_message(content=txt, view=None)
            return

        lines = [f"**Division {division_value} – offene Spiele ({len(matches)})**"]
        if effective_filter:
            lines.append(f"_Filter: {effective_filter}_")
        else:
            lines.append("_Filter: Komplett_")

        for (row_nr, block, p1, p2) in matches[:80]:
            side = "links" if block == "L" else "rechts"
            lines.append(f"• Zeile {row_nr} ({side}): **{p1}** vs **{p2}**")

        if len(matches) > 80:
            lines.append(f"… und {len(matches) - 80} weitere.")

        await interaction.response.edit_message(content="\n".join(lines), view=None)

    except Exception as e:
        print(f"[RESTPROGRAMM] Fehler in _rp_show: {e}")
        try:
            await interaction.response.edit_message(
                content="❌ Konnte das Restprogramm gerade nicht laden. Bitte später erneut probieren.",
                view=None,
            )
        except Exception:
            pass


# =========================================================
# /termin Modal
# =========================================================
class TerminModal(discord.ui.Modal, title="Neues TFL-Match eintragen"):
    division = discord.ui.TextInput(
        label="Division",
        placeholder="z. B. 2. Division",
        required=True,
    )
    datetime_str = discord.ui.TextInput(
        label="Datum & Uhrzeit",
        placeholder="DD.MM.YYYY HH:MM",
        required=True,
    )
    spieler1 = discord.ui.TextInput(
        label="Spieler 1",
        placeholder="Name wie in Liste",
        required=True,
    )
    spieler2 = discord.ui.TextInput(
        label="Spieler 2",
        placeholder="Name wie in Liste",
        required=True,
    )
    modus = discord.ui.TextInput(
        label="Modus",
        placeholder="z. B. Casual Boots",
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            parts = self.datetime_str.value.strip().split()
            if len(parts) < 2:
                await interaction.response.send_message(
                    "❌ Formatfehler: Nutze `DD.MM.YYYY HH:MM`.",
                    ephemeral=True,
                )
                return

            datum_str, uhrzeit_str = parts[0], parts[1]
            start_dt = BERLIN_TZ.localize(
                dt.strptime(f"{datum_str} {uhrzeit_str}", "%d.%m.%Y %H:%M"),
            )
            end_dt = start_dt + timedelta(hours=1)

            s1_key = self.spieler1.value.strip().lower()
            s2_key = self.spieler2.value.strip().lower()

            if s1_key not in TWITCH_MAP or s2_key not in TWITCH_MAP:
                msg = "❌ Fehlerhafte Spielernamen:"
                if s1_key not in TWITCH_MAP:
                    msg += f"\nSpieler 1: `{self.spieler1.value}` nicht erkannt"
                if s2_key not in TWITCH_MAP:
                    msg += f"\nSpieler 2: `{self.spieler2.value}` nicht erkannt"
                await interaction.response.send_message(msg, ephemeral=True)
                return

            twitch1 = TWITCH_MAP[s1_key]
            twitch2 = TWITCH_MAP[s2_key]
            multistream_url = f"https://multistre.am/{twitch1}/{twitch2}/layout4"

            await interaction.guild.create_scheduled_event(
                name=(
                    f"{self.division.value} | {self.spieler1.value} vs. "
                    f"{self.spieler2.value} | {self.modus.value}"
                ),
                description=(
                    f"Match in der {self.division.value} zwischen "
                    f"{self.spieler1.value} und {self.spieler2.value}."
                ),
                start_time=start_dt,
                end_time=end_dt,
                entity_type=discord.EntityType.external,
                location=multistream_url,
                privacy_level=discord.PrivacyLevel.guild_only,
            )

            await interaction.response.send_message(
                "✅ Event wurde erstellt (kein Sheet-Eintrag).",
                ephemeral=True,
            )

        except Exception as e:
            await interaction.response.send_message(
                f"❌ Fehler beim Erstellen des Events: {e}",
                ephemeral=True,
            )


# =========================================================
# /result Workflow
# =========================================================
def load_open_games_for_result(div_number: str):
    sheets_required()
    ws = WB.worksheet(f"{div_number}.DIV")
    rows = ws.get_all_values()

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


def get_unique_heimspieler(div_number: str):
    games = load_open_games_for_result(div_number)
    heim_set = {g["heim"] for g in games if g["heim"]}
    return sorted(list(heim_set))


def batch_update_result(
    ws,
    row_index,
    now_str,
    mode_val,
    ergebnis,
    raceroom_val,
    reporter_name,
):
    reqs = [
        {"range": f"B{row_index}:C{row_index}", "values": [[now_str, mode_val]]},
        {"range": f"E{row_index}:E{row_index}", "values": [[ergebnis]]},
        {"range": f"G{row_index}:G{row_index}", "values": [[raceroom_val]]},
        {"range": f"H{row_index}:H{row_index}", "values": [[reporter_name]]},
    ]
    ws.batch_update(reqs)


class ResultDivisionSelect(discord.ui.Select):
    def __init__(self, requester: discord.Member):
        self.requester = requester
        options = [
            discord.SelectOption(label="Division 1", value="1"),
            discord.SelectOption(label="Division 2", value="2"),
            discord.SelectOption(label="Division 3", value="3"),
            discord.SelectOption(label="Division 4", value="4"),
            discord.SelectOption(label="Division 5", value="5"),
            discord.SelectOption(label="Division 6", value="6"),
        ]
        super().__init__(
            placeholder="Welche Division?",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        division = self.values[0]

        try:
            heimspieler_liste = get_unique_heimspieler(division)
        except Exception as e:
            print(f"[RESULT] Fehler beim Laden der Division {division}: {e}")
            await interaction.response.send_message(
                "❌ Fehler beim Laden der Division.",
                ephemeral=True,
            )
            return

        if not heimspieler_liste:
            await interaction.response.edit_message(
                content=f"Keine offenen Spiele in Division {division}.",
                view=None,
            )
            return

        view = ResultHomeSelectView(
            division=division,
            heimspieler_list=heimspieler_liste,
            requester=self.requester,
        )

        await interaction.response.edit_message(
            content=f"Division {division} ausgewählt.\nWer hat Heimrecht?",
            view=view,
        )


class ResultDivisionSelectView(discord.ui.View):
    def __init__(self, requester: discord.Member, timeout=180):
        super().__init__(timeout=timeout)
        self.add_item(ResultDivisionSelect(requester))


class ResultHomeSelect(discord.ui.Select):
    def __init__(self, division: str, heimspieler_list, requester: discord.Member):
        self.division = division
        self.requester = requester
        options = [
            discord.SelectOption(label=spieler, value=spieler)
            for spieler in heimspieler_list
        ]
        super().__init__(
            placeholder="Wer hat Heimrecht?",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        heim = self.values[0]

        try:
            alle_spiele = load_open_games_for_result(self.division)
        except Exception as e:
            print(f"[RESULT] Fehler beim Laden offener Spiele (Div {self.division}): {e}")
            await interaction.response.send_message(
                "❌ Fehler beim Laden der offenen Spiele.",
                ephemeral=True,
            )
            return

        spiele_dieses_heims = [g for g in alle_spiele if g["heim"] == heim]

        if not spiele_dieses_heims:
            await interaction.response.edit_message(
                content=f"Keine offenen Spiele gefunden, in denen {heim} Heim ist.",
                view=None,
            )
            return

        view = ResultGameSelectView(
            division=self.division,
            heim=heim,
            games=spiele_dieses_heims,
            requester=self.requester,
        )

        await interaction.response.edit_message(
            content=f"Heimrecht: {heim}\nBitte Spiel auswählen:",
            view=view,
        )


class ResultHomeSelectView(discord.ui.View):
    def __init__(
        self,
        division: str,
        heimspieler_list,
        requester: discord.Member,
        timeout=180,
    ):
        super().__init__(timeout=timeout)
        self.add_item(ResultHomeSelect(division, heimspieler_list, requester))


class ResultGameSelect(discord.ui.Select):
    def __init__(self, division: str, heim: str, games, requester: discord.Member):
        self.division = division
        self.heim = heim
        self.games = games
        self.requester = requester

        options = []
        for idx, g in enumerate(games):
            label = f"{g['heim']} vs {g['auswaerts']} | Zeile {g['row_index']}"
            options.append(discord.SelectOption(label=label[:100], value=str(idx)))

        super().__init__(
            placeholder="Bitte Spiel auswählen",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        sel_idx = int(self.values[0])
        game_info = self.games[sel_idx]

        modal = ResultEntryModal(
            division=self.division,
            row_index=game_info["row_index"],
            heim=game_info["heim"],
            auswaerts=game_info["auswaerts"],
            requester=self.requester,
        )
        await interaction.response.send_modal(modal)


class ResultGameSelectView(discord.ui.View):
    def __init__(
        self,
        division: str,
        heim: str,
        games,
        requester: discord.Member,
        timeout=180,
    ):
        super().__init__(timeout=timeout)
        self.add_item(ResultGameSelect(division, heim, games, requester))


class ResultEntryModal(discord.ui.Modal, title="Ergebnis eintragen"):
    def __init__(
        self,
        division: str,
        row_index: int,
        heim: str,
        auswaerts: str,
        requester: discord.Member,
    ):
        super().__init__(timeout=None)
        self.division = division
        self.row_index = row_index
        self.heim = heim
        self.auswaerts = auswaerts
        self.requester = requester

        short_heim = (heim[:12] + "…") if len(heim) > 12 else heim
        short_aus = (auswaerts[:12] + "…") if len(auswaerts) > 12 else auswaerts

        self.winner_input = discord.ui.TextInput(
            label="Wer hat gewonnen?",
            style=discord.TextStyle.short,
            required=True,
            max_length=1,
            placeholder=f"1 = {short_heim}, 2 = {short_aus}, X = Unentschieden",
        )
        self.mode_input = discord.ui.TextInput(
            label="Modus",
            style=discord.TextStyle.short,
            required=True,
            placeholder="Ambrosia, Crosskeys o.Ä.",
            max_length=50,
        )
        self.raceroom_input = discord.ui.TextInput(
            label="Raceroom-Link",
            style=discord.TextStyle.short,
            required=True,
            placeholder="https://raceroom.xyz/...",
        )

        self.add_item(self.winner_input)
        self.add_item(self.mode_input)
        self.add_item(self.raceroom_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=False)

        winner_val = self.winner_input.value.strip().upper()
        mode_val = self.mode_input.value.strip()
        raceroom_val = self.raceroom_input.value.strip()

        if winner_val == "1":
            ergebnis = "2:0"
        elif winner_val == "2":
            ergebnis = "0:2"
        elif winner_val == "X":
            ergebnis = "1:1"
        else:
            await interaction.followup.send(
                content="❌ Ungültiger Gewinner-Wert. Bitte nur 1 / 2 / X.",
                ephemeral=True,
            )
            return

        try:
            sheets_required()
            ws = WB.worksheet(f"{self.division}.DIV")

            now = dt.now(BERLIN_TZ)
            now_str = now.strftime("%d.%m.%Y %H:%M")

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                batch_update_result,
                ws,
                self.row_index,
                now_str,
                mode_val,
                ergebnis,
                raceroom_val,
                str(self.requester),
            )

            channel = client.get_channel(RESULTS_CHANNEL_ID)
            if channel is not None:
                out_lines = [
                    f"**[Division {self.division}]** {now_str}",
                    f"**{self.heim}** vs **{self.auswaerts}** → **{ergebnis}**",
                    f"Modus: {mode_val}",
                    f"Raceroom: {raceroom_val}",
                ]
                try:
                    await channel.send("\n".join(out_lines))
                except Exception as send_err:
                    await interaction.followup.send(
                        content=(
                            "⚠️ Ergebnis gespeichert, aber Channel-Post "
                            f"fehlgeschlagen: {send_err}"
                        ),
                        ephemeral=True,
                    )
                    return
            else:
                await interaction.followup.send(
                    content=(
                        "⚠️ Ergebnis gespeichert, aber Ergebnischannel nicht gefunden."
                    ),
                    ephemeral=True,
                )
                return

            msg = (
                f"✅ Ergebnis gespeichert & gepostet:\n"
                f"{self.heim} vs {self.auswaerts} => {ergebnis}\n"
                f"Modus: {mode_val}\n"
                f"Raceroom: {raceroom_val}"
            )
            await interaction.followup.send(content=msg, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(
                content=f"❌ Konnte Ergebnis nicht verarbeiten: {e}",
                ephemeral=True,
            )


@tree.command(
    name="result",
    description="Ergebnis melden (nur Orga / Try Force League Rolle)",
)
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def result(interaction: discord.Interaction):
    member = interaction.user
    if not isinstance(member, discord.Member):
        await interaction.response.send_message(
            "❌ Konnte Mitgliedsdaten nicht lesen.",
            ephemeral=True,
        )
        return

    if not has_tfl_role(member):
        await interaction.response.send_message(
            "⛔ Du hast keine Berechtigung diesen Befehl zu nutzen.",
            ephemeral=True,
        )
        return

    view = ResultDivisionSelectView(requester=member)

    await interaction.response.send_message(
        "Bitte Division auswählen:",
        view=view,
        ephemeral=True,
    )


# =========================================================
# /playerexit Workflow
# =========================================================
def list_div_players(div_number: str):
    try:
        sheets_required()
        ws = WB.worksheet(f"{div_number}.DIV")
        return _collect_players_from_div_ws(ws)
    except Exception:
        return []


def playerexit_apply(div_number: str, quitting_player: str, reporter: str):
    sheets_required()
    ws = WB.worksheet(f"{div_number}.DIV")
    rows = ws.get_all_values()

    now_str = dt.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M")
    batch_reqs = []
    strike_cells = []

    for idx, row in enumerate(rows[1:], start=2):
        left_player = _cell(row, DIV_COL_LEFT - 1)
        right_player = _cell(row, DIV_COL_RIGHT - 1)

        lp_match = (
            left_player.lower() == quitting_player.lower()
            if left_player
            else False
        )
        rp_match = (
            right_player.lower() == quitting_player.lower()
            if right_player
            else False
        )

        if not (lp_match or rp_match):
            continue

        if lp_match:
            result_val = "0:2"
            strike_cells.append(f"D{idx}")
        else:
            result_val = "2:0"
            strike_cells.append(f"F{idx}")

        batch_reqs.append(
            {"range": f"B{idx}:C{idx}", "values": [[now_str, "FF"]]},
        )
        batch_reqs.append(
            {"range": f"E{idx}:E{idx}", "values": [[result_val]]},
        )
        batch_reqs.append({"range": f"G{idx}:G{idx}", "values": [["FF"]]})
        batch_reqs.append({"range": f"H{idx}:H{idx}", "values": [[reporter]]})

    if batch_reqs:
        ws.batch_update(batch_reqs)

    if strike_cells:
        style = {"textFormat": {"strikethrough": True}}
        for rng in strike_cells:
            try:
                ws.format(rng, style)
            except Exception:
                pass


class PlayerExitDivisionSelect(discord.ui.Select):
    def __init__(self, requester: discord.Member):
        self.requester = requester
        options = [
            discord.SelectOption(label="Division 1", value="1"),
            discord.SelectOption(label="Division 2", value="2"),
            discord.SelectOption(label="Division 3", value="3"),
            discord.SelectOption(label="Division 4", value="4"),
            discord.SelectOption(label="Division 5", value="5"),
            discord.SelectOption(label="Division 6", value="6"),
        ]
        super().__init__(
            placeholder="Welche Division?",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        div_number = self.values[0]

        try:
            await interaction.response.defer(ephemeral=True, thinking=False)
        except discord.InteractionResponded:
            pass

        try:
            players = list_div_players(div_number)
        except Exception as e:
            await interaction.followup.send(
                f"❌ Konnte Spieler nicht laden.",
                ephemeral=True,
            )
            return

        if not players:
            await interaction.edit_original_response(
                content=f"Keine Spieler in Division {div_number} gefunden.",
                view=None,
            )
            return

        view = PlayerExitPlayerSelectView(
            division=div_number,
            players=players,
            requester=self.requester,
        )

        await interaction.edit_original_response(
            content=f"Division {div_number} gewählt.\nWelcher Spieler steigt aus?",
            view=view,
        )


class PlayerExitDivisionSelectView(discord.ui.View):
    def __init__(self, requester: discord.Member, timeout=180):
        super().__init__(timeout=timeout)
        self.add_item(PlayerExitDivisionSelect(requester))


class PlayerExitPlayerSelect(discord.ui.Select):
    def __init__(self, division: str, players, requester: discord.Member):
        self.division = division
        self.players = players
        self.requester = requester

        options = [discord.SelectOption(label=p, value=p) for p in players]

        super().__init__(
            placeholder="Spieler wählen (steigt aus)",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        quitting_player = self.values[0]

        try:
            await interaction.response.defer(ephemeral=True, thinking=False)
        except discord.InteractionResponded:
            pass

        try:
            playerexit_apply(
                div_number=self.division,
                quitting_player=quitting_player,
                reporter=str(self.requester),
            )

            await interaction.followup.send(
                content=(
                    f"✅ `{quitting_player}` in Division {self.division} ausgetragen.\n"
                    "Alle Spiele (auch bereits gespielte) wurden als FF gegen ihn gewertet "
                    "und der Name wurde durchgestrichen."
                ),
                ephemeral=True,
            )

        except Exception as e:
            await interaction.followup.send(
                content=f"❌ Fehler beim Austragen.",
                ephemeral=True,
            )


class PlayerExitPlayerSelectView(discord.ui.View):
    def __init__(
        self,
        division: str,
        players,
        requester: discord.Member,
        timeout=180,
    ):
        super().__init__(timeout=timeout)
        self.add_item(PlayerExitPlayerSelect(division, players, requester))


# =========================================================
# Spielplan / Round Robin
# =========================================================
def _get_div_ws(div_number: str):
    sheets_required()
    ws_name = f"{div_number}.DIV"
    return WB.worksheet(ws_name)


def spielplan_read_players(div_number: str):
    ws = _get_div_ws(div_number)
    return _collect_players_from_div_ws(ws)


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
    col_d = ws.col_values(4)
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
            row_data = [""] * 9  # A..I
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
    ws.update(cell_range, rows_to_write)
    return len(rows_to_write)

# =========================================================
# RESTREAM-SYSTEM
# =========================================================
# Spalte H = Restream-Label (leer → ungeplant)
# Werte: ZSR, SGD1, SGD2


def load_upcoming_games():
    """
    Lädt alle kommenden Spiele aus ALLEN Div-Tabs.
    Ein Spiel gilt als 'kommend', wenn E == 'vs'.
    """
    sheets_required()
    all_games = []

    for div in ("1", "2", "3", "4", "5", "6"):
        ws = WB.worksheet(f"{div}.DIV")
        rows = ws.get_all_values()
        for idx, row in enumerate(rows, start=1):
            if idx == 1:
                continue

            p1 = _cell(row, DIV_COL_LEFT - 1)
            p2 = _cell(row, DIV_COL_RIGHT - 1)
            marker = _cell(row, DIV_COL_MARKER - 1).lower()

            if marker == "vs":
                all_games.append(
                    {
                        "div": div,
                        "row": idx,
                        "p1": p1,
                        "p2": p2,
                        "row_data": row,
                    }
                )
    return all_games


def load_restream_column():
    sheets_required()
    data = {}
    for div in ("1", "2", "3", "4", "5", "6"):
        ws = WB.worksheet(f"{div}.DIV")
        colH = ws.col_values(8)
        data[div] = colH
    return data


def write_restream_label(div, row, label):
    sheets_required()
    ws = WB.worksheet(f"{div}.DIV")
    ws.update(f"H{row}", label)


# =========================================================
# /restreams — Checkbox-UI
# =========================================================

class RestreamCheckbox(discord.ui.Checkbox):
    def __init__(self, div, row, p1, p2):
        self.div = div
        self.row = row
        super().__init__(
            label=f"Div {div}: {p1} vs {p2} (Zeile {row})",
            required=False,
        )


class RestreamsView(discord.ui.View):
    def __init__(self, games):
        super().__init__(timeout=300)
        self.checks = []
        for g in games:
            cb = RestreamCheckbox(g["div"], g["row"], g["p1"], g["p2"])
            self.checks.append(cb)
            self.add_item(cb)

        self.zsr = discord.ui.Button(
            label="RESTREAM: ZSR", style=discord.ButtonStyle.primary
        )
        self.sgd1 = discord.ui.Button(
            label="RESTREAM: SGDE1", style=discord.ButtonStyle.primary
        )
        self.sgd2 = discord.ui.Button(
            label="RESTREAM: SGDE2", style=discord.ButtonStyle.primary
        )

        self.zsr.callback = self._zsr_pressed
        self.sgd1.callback = self._sgd1_pressed
        self.sgd2.callback = self._sgd2_pressed

        self.add_item(self.zsr)
        self.add_item(self.sgd1)
        self.add_item(self.sgd2)

    async def _update(self, interaction, label):
        updated = []
        for cb in self.checks:
            if cb.value:
                write_restream_label(cb.div, cb.row, label)
                updated.append(f"Div {cb.div} | Zeile {cb.row}")

        if not updated:
            await interaction.response.send_message(
                "❌ Kein Spiel ausgewählt.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "✅ Aktualisiert:\n" + "\n".join(updated),
            ephemeral=True,
        )

    async def _zsr_pressed(self, interaction):
        await self._update(interaction, "ZSR")

    async def _sgd1_pressed(self, interaction):
        await self._update(interaction, "SGD1")

    async def _sgd2_pressed(self, interaction):
        await self._update(interaction, "SGD2")


@tree.command(name="restreams", description="Offene Spiele für Restreams auswählen")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def restreams(interaction: discord.Interaction):
    member = interaction.user
    if not has_tfl_role(member):
        await interaction.response.send_message(
            "⛔ Keine Berechtigung.",
            ephemeral=True,
        )
        return

    all_games = load_upcoming_games()

    # Filter: Spalte H NICHT gesetzt
    restream_col = load_restream_column()
    unassigned = []

    for g in all_games:
        div = g["div"]
        row = g["row"]
        colH = restream_col[div]
        val = ""
        if row - 1 < len(colH):
            val = (colH[row - 1] or "").strip()
        if val == "":
            unassigned.append(g)

    if not unassigned:
        await interaction.response.send_message(
            "🎉 Kein Spiel mehr offen für Restreams – alles zugeordnet.",
            ephemeral=True,
        )
        return

    view = RestreamsView(unassigned)
    await interaction.response.send_message(
        f"**{len(unassigned)} offene Spiele** für Restream-Auswahl:",
        view=view,
        ephemeral=True,
    )


# =========================================================
# /pick & /showpicks – internes Pick-System
# =========================================================
PICKS = []


@tree.command(name="pick", description="Einen Tipp / Pick setzen.")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def pick(interaction: discord.Interaction, text: str):
    PICKS.append((interaction.user.name, text))
    await interaction.response.send_message(
        f"Pick gespeichert: **{text}**",
        ephemeral=True,
    )


@tree.command(name="showpicks", description="Alle bisherigen Picks anzeigen.")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def showpicks(interaction: discord.Interaction):
    if not PICKS:
        await interaction.response.send_message(
            "Keine Picks gesetzt.",
            ephemeral=True,
        )
        return

    out = ["**Alle Picks:**"]
    for user, text in PICKS:
        out.append(f"- **{user}**: {text}")

    await interaction.response.send_message("\n".join(out), ephemeral=True)


# =========================================================
# /today – Spiele heute in jeder Division
# =========================================================
def load_schedule_sheet():
    sheets_required()
    try:
        return WB.worksheet("League & Cup Schedule")
    except:
        return None


def parse_date_field(row_val):
    try:
        return dt.strptime(row_val, "%d.%m.%Y").date()
    except:
        return None


@tree.command(name="today", description="Zeigt alle Spiele, die heute stattfinden.")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def today(interaction: discord.Interaction):
    ws = load_schedule_sheet()
    if ws is None:
        await interaction.response.send_message(
            "❌ Schedule-Sheet fehlt.",
            ephemeral=True,
        )
        return

    rows = ws.get_all_values()
    today = today_berlin_date()

    out = ["**Spiele heute:**"]
    found = False

    for row in rows[1:]:
        div = _cell(row, 0)
        dat = parse_date_field(_cell(row, 1))
        time = _cell(row, 2)
        p1 = _cell(row, 3)
        p2 = _cell(row, 4)
        mode = _cell(row, 5)

        if dat == today:
            found = True
            out.append(f"Div {div}: **{p1} vs {p2}** – {time} – {mode}")

    if not found:
        out = ["Heute keine Spiele."]

    await interaction.response.send_message("\n".join(out), ephemeral=True)


# =========================================================
# /div1 … /div6 /cup /alle – Kommende Spiele
# =========================================================

async def _filtered_games(interaction, selector):
    ws = load_schedule_sheet()
    if ws is None:
        await interaction.response.send_message(
            "❌ Konnte Schedule nicht laden.",
            ephemeral=True,
        )
        return

    rows = ws.get_all_values()
    today = today_berlin_date()

    out = []
    for r in rows[1:]:
        div = _cell(r, 0)
        dat = parse_date_field(_cell(r, 1))
        time = _cell(r, 2)
        p1 = _cell(r, 3)
        p2 = _cell(r, 4)
        mode = _cell(r, 5)

        if dat is None:
            continue
        if dat < today:
            continue

        if selector == "ALL" or selector == "CUP":
            if selector == "CUP" and div == "Cup":
                out.append(f"Cup: **{p1} vs {p2}** – {dat} {time} – {mode}")
            elif selector == "ALL":
                out.append(f"Div {div}: **{p1} vs {p2}** – {dat} {time} – {mode}")
        else:
            if div == selector:
                out.append(
                    f"Div {div}: **{p1} vs {p2}** – {dat} {time} – {mode}"
                )

    if not out:
        await interaction.response.send_message("Keine Spiele.", ephemeral=True)
        return

    await interaction.response.send_message("\n".join(out), ephemeral=True)


for i in range(1, 7):
    @tree.command(name=f"div{i}", description=f"Kommende Spiele der Division {i}")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def _(interaction: discord.Interaction, i=i):
        await _filtered_games(interaction, str(i))


@tree.command(name="cup", description="Kommende Cup-Spiele")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def cup_cmd(interaction: discord.Interaction):
    await _filtered_games(interaction, "CUP")


@tree.command(name="alle", description="Alle kommenden Spiele")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def alle_cmd(interaction: discord.Interaction):
    await _filtered_games(interaction, "ALL")


# =========================================================
# /add – Twitch-Map dynamisch erweitern
# =========================================================
@tree.command(name="add", description="Neuen Spieler + Twitch hinzufügen")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def add(interaction: discord.Interaction, name: str, twitch: str):
    TWITCH_MAP[name.lower()] = twitch
    await interaction.response.send_message(
        f"✅ `{name}` → `{twitch}` hinzugefügt.",
        ephemeral=True,
    )


# =========================================================
# /restprogramm (FIXED)
# =========================================================

class RPSelectDivision(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=f"Division {i}", value=str(i))
            for i in range(1, 7)
        ]
        super().__init__(
            placeholder="Division auswählen",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        div = self.values[0]

        players = get_players_for_div(div)
        if not players:
            await interaction.response.edit_message(
                content=f"Keine Spieler in Div {div}.",
                view=None,
            )
            return

        view = RPSelectPlayer(division_value=div, players=players)
        await interaction.response.edit_message(
            content=f"Division {div} – Spieler auswählen:",
            view=view,
        )


class RPSelectPlayer(discord.ui.View):
    def __init__(self, division_value: str, players):
        super().__init__(timeout=300)
        self.division_value = division_value
        self.player_value = "Komplett"

        opts = [discord.SelectOption(label="Komplett", value="Komplett")] + [
            discord.SelectOption(label=p, value=p) for p in players
        ]

        self.player_select = discord.ui.Select(
            placeholder="Spieler auswählen",
            min_values=1,
            max_values=1,
            options=opts,
        )
        self.player_select.callback = self._player_changed

        self.add_item(self.player_select)

        self.show_btn = discord.ui.Button(label="Anzeigen", style=discord.ButtonStyle.primary)
        self.show_btn.callback = self._show
        self.add_item(self.show_btn)

    async def _player_changed(self, interaction):
        self.player_value = self.player_select.values[0]
        try:
            await interaction.response.edit_message(
                content=f"Division {self.division_value} | Spieler: {self.player_value}",
                view=self,
            )
        except discord.InteractionResponded:
            await interaction.edit_original_response(
                content=f"Division {self.division_value} | Spieler: {self.player_value}",
                view=self,
            )

    async def _show(self, interaction):
        await _rp_show(
            interaction,
            self.division_value,
            self.player_value,
        )


@tree.command(name="restprogramm", description="Offene Spiele pro Division anzeigen.")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def restprogramm(interaction: discord.Interaction):
    view = discord.ui.View(timeout=300)
    view.add_item(RPSelectDivision())
    await interaction.response.send_message(
        "Division auswählen:",
        view=view,
        ephemeral=True,
    )


# =========================================================
# Auto-Posts um 04:00 & 04:30
# =========================================================

async def autopost_loop():
    await client.wait_until_ready()

    global _last_restreamable_post_date
    global _last_restreams_post_date

    while not client.is_closed():
        now = dt.now(BERLIN_TZ)
        today = now.date()
        hhmm = now.strftime("%H:%M")

        if hhmm == "04:00":
            if _last_restreamable_post_date != today:
                _last_restreamable_post_date = today
                await autopost_restreamable()
        elif hhmm == "04:30":
            if _last_restreams_post_date != today:
                _last_restreams_post_date = today
                await autopost_restreams()

        await asyncio.sleep(30)


async def autopost_restreamable():
    ch = client.get_channel(SHOWRESTREAMS_CHANNEL_ID)
    if not ch:
        return

    all_games = load_upcoming_games()
    restream_col = load_restream_column()

    unassigned = []
    for g in all_games:
        div = g["div"]
        row = g["row"]
        colH = restream_col[div]
        val = ""
        if row - 1 < len(colH):
            val = colH[row - 1] or ""
        if val.strip() == "":
            unassigned.append(g)

    if not unassigned:
        await ch.send("🎉 Keine Spiele warten auf Restream-Zuweisung.")
        return

    lines = ["**Offene Restream-Spiele:**"]
    for g in unassigned:
        lines.append(f"- Div {g['div']}: **{g['p1']} vs {g['p2']}** (Zeile {g['row']})")
    await ch.send("\n".join(lines))


async def autopost_restreams():
    ch = client.get_channel(SHOWRESTREAMS_CHANNEL_ID)
    if not ch:
        return

    restream_col = load_restream_column()
    all_games = load_upcoming_games()

    lines = ["**Geplante Restreams:**"]
    found = False

    for g in all_games:
        div = g["div"]
        row = g["row"]
        p1 = g["p1"]
        p2 = g["p2"]

        val = ""
        colH = restream_col[div]
        if row - 1 < len(colH):
            val = colH[row - 1] or ""

        if val != "":
            found = True
            lines.append(f"- Div {div}: **{p1} vs {p2}** – {val}")

    if not found:
        await ch.send("Keine geplanten Restreams.")
    else:
        await ch.send("\n".join(lines))


# =========================================================
# /sync
# =========================================================
@tree.command(name="sync", description="Re-sync aller Slash Commands")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def sync_cmd(interaction: discord.Interaction):
    if not has_admin_role(interaction.user):
        await interaction.response.send_message(
            "⛔ Keine Berechtigung.",
            ephemeral=True,
        )
        return

    await tree.sync(guild=discord.Object(id=GUILD_ID))
    await interaction.response.send_message("🔄 Slash Commands synchronisiert!", ephemeral=True)


# =========================================================
# on_ready
# =========================================================
@client.event
async def on_ready():
    print(f"[READY] Eingeloggt als {client.user}")

    try:
        await tree.sync(guild=discord.Object(id=GUILD_ID))
        print("[SYNC] Slash Commands synchronisiert.")
    except Exception as e:
        print(f"[SYNC] Fehler: {e}")

    try:
        asyncio.create_task(start_webserver(client))
    except Exception as e:
        print(f"[WEB] Fehler: {e}")

    try:
        asyncio.create_task(autopost_loop())
    except Exception as e:
        print(f"[AUTOPOST] Fehler: {e}")


# =========================================================
# BOT STARTEN
# =========================================================
client.run(TOKEN)
