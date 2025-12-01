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
# Spieler-Helfer für DIV-Tabs (neu, ohne Spalte L)
# =========================================================
def _collect_players_from_div_ws(ws) -> list[str]:
    """
    Liest alle Spielernamen aus Spalte D (Heim) und F (Gast),
    entfernt Duplikate, behält Reihenfolge.
    """
    rows = ws.get_all_values()
    seen = set()
    players = []

    D_idx0 = DIV_COL_LEFT - 1
    F_idx0 = DIV_COL_RIGHT - 1

    for r_idx in range(1, len(rows)):  # ab Zeile 2
        row = rows[r_idx]
        p_left = _cell(row, D_idx0)
        p_right = _cell(row, F_idx0)

        for p in (p_left, p_right):
            if not p:
                continue
            low = p.lower()
            if low not in seen:
                seen.add(low)
                players.append(p)

    return players


def get_players_for_div(div: str) -> list[str]:
    """
    Öffnet {div}.DIV und liefert alle Spieler aus Spalte D/F.
    Falls dort nichts steht, versuchen wir zusätzlich den Racer-Block ab Spalte L.
    Fehler werden geloggt, aber nicht nach außen geworfen.
    """
    try:
        sheets_required()
        ws_name = f"{div}.DIV"
        print(f"[RESTPROGRAMM] get_players_for_div: versuche Worksheet '{ws_name}' zu öffnen")
        ws = WB.worksheet(ws_name)

        # 1) Standard: alle Spieler aus D/F (Spalten 4 und 6)
        players = _collect_players_from_div_ws(ws)
        if players:
            print(f"[RESTPROGRAMM] get_players_for_div({div}) -> {len(players)} Spieler (D/F): {players}")
            return players

        # 2) Fallback: Racer-Liste in Spalte L
        try:
            racer_col = ws.col_values(12)  # L = 12
            racer_players = []
            for name in racer_col[1:]:  # ab Zeile 2
                name = name.strip()
                if name:
                    racer_players.append(name)
            if racer_players:
                print(
                    f"[RESTPROGRAMM] get_players_for_div({div}) -> "
                    f"{len(racer_players)} Spieler (L): {racer_players}"
                )
                return racer_players
        except Exception as e:
            print(f"[RESTPROGRAMM] Fallback (Racer-Liste) fehlgeschlagen: {e}")

        print(f"[RESTPROGRAMM] get_players_for_div({div}) -> keine Spieler gefunden")
        return []

    except Exception as e:
        print(f"[RESTPROGRAMM] get_players_for_div({div}) Fehler: {e}")
        return []




def load_open_from_div_tab(div: str, player_query: str = ""):
    """
    Liest Tab '{div}.DIV' und gibt offene Paarungen zurück.
    D = Spieler 1
    E = Marker ("vs" = offen)
    F = Spieler 2
    """
    try:
        sheets_required()
        ws_name = f"{div}.DIV"
        ws = WB.worksheet(ws_name)
        rows = ws.get_all_values()
    except Exception as e:
        print(f"[RESTPROGRAMM] load_open_from_div_tab({div}) Fehler: {e}")
        return []

    out = []
    q = player_query.strip().lower()

    D_idx0 = DIV_COL_LEFT - 1
    E_idx0 = DIV_COL_MARKER - 1
    F_idx0 = DIV_COL_RIGHT - 1

    for r_idx in range(1, len(rows)):
        row = rows[r_idx]
        p1 = _cell(row, D_idx0)
        marker = _cell(row, E_idx0).lower()
        p2 = _cell(row, F_idx0)

        if (p1 or p2) and marker == "vs":
            if not q or (q in p1.lower() or q in p2.lower()):
                out.append((r_idx + 1, "L", p1, p2))

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
# Restream-Helfer
# =========================================================
def _format_event_line_for_post(ev: discord.ScheduledEvent) -> str:
    start = ev.start_time
    if start:
        start_local = start.astimezone(BERLIN_TZ)
        date_str = start_local.strftime("%d.%m.%Y")
        time_str = start_local.strftime("%H:%M")
        dt_str = f"{date_str} {time_str}"
    else:
        dt_str = "ohne Startzeit"

    loc = _event_location(ev) or "kein Link"
    if loc != "kein Link":
        loc_display = f"<{loc}>"
    else:
        loc_display = loc

    name = ev.name or "Unbenanntes Event"
    return f"• {name} – {dt_str} – {loc_display}"


async def apply_restream_to_event(
    ev: discord.ScheduledEvent,
    restream_type: str,
    private_url: str | None = None,
):
    new_name = ev.name or ""
    if "(Restream)" not in new_name:
        new_name = f"{new_name} (Restream)"

    desc = ev.description or ""
    line = ""
    if restream_type.upper() == "ZSR":
        line = f"Restream: ZSR – {ZSR_RESTREAM_URL}"
    else:
        if not private_url:
            raise ValueError("Privater Restream ohne URL.")
        line = f"Restream (Privat): {private_url}"

    if line and line not in desc:
        if desc.strip():
            desc = desc.rstrip() + "\n\n" + line
        else:
            desc = line

    await ev.edit(name=new_name, description=desc)


class PrivateRestreamModal(discord.ui.Modal, title="Privater Restream-Link"):
    def __init__(self, event: discord.ScheduledEvent):
        super().__init__(timeout=None)
        self.event = event

        self.url_input = discord.ui.TextInput(
            label="Link zum privaten Restream (Twitch o.Ä.)",
            style=discord.TextStyle.short,
            required=True,
            placeholder="https://www.twitch.tv/dein_kanal",
        )
        self.add_item(self.url_input)

    async def on_submit(self, interaction: discord.Interaction):
        url = self.url_input.value.strip()
        if not url.lower().startswith(("http://", "https://")):
            await interaction.response.send_message(
                "❌ Bitte eine vollständige URL mit http(s) angeben.",
                ephemeral=True,
            )
            return

        try:
            await apply_restream_to_event(self.event, "PRIVAT", private_url=url)
            await interaction.response.send_message(
                f"✅ Privater Restream für Event `{self.event.name}` gesetzt.",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Fehler beim Setzen des Restreams: {e}",
                ephemeral=True,
            )


class PickView(discord.ui.View):
    def __init__(self, events: list[discord.ScheduledEvent], requester: discord.Member):
        super().__init__(timeout=180)
        self.requester = requester
        self.events_by_id: dict[str, discord.ScheduledEvent] = {
            str(ev.id): ev for ev in events
        }
        self.selected_event_id: str | None = None

        self.add_item(self.EventSelect(self))
        self.add_item(self.SourceSelect(self))

    class EventSelect(discord.ui.Select):
        def __init__(self, parent_view: "PickView"):
            self.parent_view = parent_view
            options = []
            for ev_id, ev in parent_view.events_by_id.items():
                label = ev.name or "Unbenanntes Event"
                if len(label) > 90:
                    label = label[:87] + "..."
                options.append(discord.SelectOption(label=label, value=ev_id))
                if len(options) >= 25:
                    break

            super().__init__(
                placeholder="Event wählen …",
                min_values=1,
                max_values=1,
                options=options,
            )

        async def callback(self, interaction: discord.Interaction):
            self.parent_view.selected_event_id = self.values[0]
            selected_label = None
            for opt in self.options:
                if opt.value == self.values[0]:
                    selected_label = opt.label
                    break

            await interaction.response.send_message(
                f"🎯 Event gesetzt: `{selected_label}`",
                ephemeral=True,
            )

    class SourceSelect(discord.ui.Select):
        def __init__(self, parent_view: "PickView"):
            self.parent_view = parent_view
            options = [
                discord.SelectOption(label="ZSR", value="ZSR"),
                discord.SelectOption(label="Privat", value="PRIVAT"),
            ]
            super().__init__(
                placeholder="Restream-Quelle wählen …",
                min_values=1,
                max_values=1,
                options=options,
            )

        async def callback(self, interaction: discord.Interaction):
            if not self.parent_view.selected_event_id:
                await interaction.response.send_message(
                    "Bitte zuerst ein Event auswählen.",
                    ephemeral=True,
                )
                return

            ev = self.parent_view.events_by_id.get(self.parent_view.selected_event_id)
            if ev is None:
                await interaction.response.send_message(
                    "Event nicht mehr gefunden.",
                    ephemeral=True,
                )
                return

            choice = self.values[0]

            if choice == "ZSR":
                try:
                    await interaction.response.defer(ephemeral=True, thinking=False)
                except discord.InteractionResponded:
                    pass
                try:
                    await apply_restream_to_event(ev, "ZSR")
                    await interaction.followup.send(
                        f"✅ Restream über ZSR für Event `{ev.name}` gesetzt.",
                        ephemeral=True,
                    )
                except Exception as e:
                    await interaction.followup.send(
                        f"❌ Fehler beim Setzen des Restreams: {e}",
                        ephemeral=True,
                    )
            else:
                await interaction.response.send_modal(PrivateRestreamModal(ev))


# =========================================================
# Hintergrund-Refresher + Auto-Posts
# =========================================================
async def _maybe_post_restreamable(
    now_utc: datetime.datetime,
    now_berlin: datetime.datetime,
    events: list[discord.ScheduledEvent],
):
    global _last_restreamable_post_date

    if RESTREAM_CHANNEL_ID == 0:
        return

    today = now_berlin.date()
    header = "📺 Restreambare Spiele (heute & Zukunft)"

    if not (now_berlin.hour == 4 and now_berlin.minute < 30):
        return
    if _last_restreamable_post_date == today:
        return

    channel = client.get_channel(RESTREAM_CHANNEL_ID)
    if channel is None or not isinstance(channel, discord.TextChannel):
        return

    upcoming = []
    for ev in events:
        if ev.status not in (
            discord.EventStatus.scheduled,
            discord.EventStatus.active,
        ):
            continue
        if not ev.start_time:
            continue
        if ev.start_time <= now_utc:
            continue
        if "(restream)" in (ev.name or "").lower():
            continue
        upcoming.append(ev)

    if not upcoming:
        _last_restreamable_post_date = today
        print("[AUTO] 04:00 – keine restreambaren Events gefunden.")
        return

    upcoming.sort(key=lambda e: e.start_time or now_utc)

    lines = [header, ""]
    for ev in upcoming:
        lines.append(_format_event_line_for_post(ev))

    text = "\n".join(lines)

    try:
        async for m in channel.history(limit=5):
            if (
                m.author.id == client.user.id
                and m.created_at.astimezone(BERLIN_TZ).date() == today
                and m.content.startswith(header)
            ):
                print("[AUTO] 04:00 – bereits ein Post im Channel, breche ab.")
                _last_restreamable_post_date = today
                return
    except Exception as e:
        print(f"[AUTO] 04:00 – Fehler beim Prüfen auf Doppelpost: {e}")

    try:
        await channel.send(text)
        _last_restreamable_post_date = today
        print(f"[AUTO] 04:00 – {len(upcoming)} restreambare Events gepostet.")
    except Exception as e:
        print(f"[AUTO] Fehler beim Posten der restreambaren Events: {e}")


async def _maybe_post_restreams(
    now_utc: datetime.datetime,
    now_berlin: datetime.datetime,
    events: list[discord.ScheduledEvent],
):
    global _last_restreams_post_date

    if SHOWRESTREAMS_CHANNEL_ID == 0:
        return

    today = now_berlin.date()
    if not (now_berlin.hour == 4 and now_berlin.minute >= 30):
        return
    if _last_restreams_post_date == today:
        return

    channel = client.get_channel(SHOWRESTREAMS_CHANNEL_ID)
    if channel is None or not isinstance(channel, discord.TextChannel):
        return

    restream_events = []
    for ev in events:
        if ev.status not in (
            discord.EventStatus.scheduled,
            discord.EventStatus.active,
        ):
            continue
        if not ev.start_time or ev.start_time <= now_utc:
            continue
        if "(restream)" not in (ev.name or "").lower():
            continue
        restream_events.append(ev)

    if not restream_events:
        _last_restreams_post_date = today
        print("[AUTO] 04:30 – keine Restream-Events gefunden.")
        return

    restream_events.sort(key=lambda e: e.start_time or now_utc)

    lines = ["🔁 Geplante Restreams (heute & Zukunft)", ""]
    for ev in restream_events:
        lines.append(_format_event_line_for_post(ev))

    try:
        await channel.send("\n".join(lines))
        _last_restreams_post_date = today
        print(f"[AUTO] 04:30 – {len(restream_events)} Restream-Events gepostet.")
    except Exception as e:
        print(f"[AUTO] Fehler beim Posten der Restream-Events: {e}")


async def refresh_api_cache(client: discord.Client):
    await client.wait_until_ready()
    await asyncio.sleep(5)

    print("[CACHE] Hintergrund-Refresher gestartet")
    while not client.is_closed():
        now = datetime.datetime.now(datetime.timezone.utc)
        now_berlin = now.astimezone(BERLIN_TZ)

        try:
            guild = client.get_guild(GUILD_ID) or await client.fetch_guild(GUILD_ID)
            events = await guild.fetch_scheduled_events()

            data = []
            for ev in events:
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

            data.sort(key=lambda x: (x["start"] is None, x["start"]))

            _API_CACHE["upcoming"]["ts"] = now
            _API_CACHE["upcoming"]["data"] = data

            print(f"[CACHE] Upcoming aktualisiert ({len(data)} Events)")

            await _maybe_post_restreamable(now, now_berlin, list(events))
            await _maybe_post_restreams(now, now_berlin, list(events))

        except Exception as e:
            print(f"[CACHE] Fehler beim Aktualisieren der Upcoming-Events: {e}")

        try:
            ch = client.get_channel(RESULTS_CHANNEL_ID)
            if ch is None or not isinstance(
                ch,
                (discord.TextChannel, discord.Thread, discord.VoiceChannel),
            ):
                raise RuntimeError("Ergebnis-Channel nicht gefunden oder falscher Typ")

            items = []
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

            _API_CACHE["results"]["ts"] = now
            _API_CACHE["results"]["data"] = items

            print(f"[CACHE] Results aktualisiert ({len(items)} Einträge)")
        except Exception as e:
            print(f"[CACHE] Fehler beim Aktualisieren der Results: {e}")

        await asyncio.sleep(300)


# =========================================================
# Slash Commands
# =========================================================
@tree.command(
    name="termin",
    description="Erstelle einen neuen Termin (nur Event, kein Sheet)",
)
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def termin(interaction: discord.Interaction):
    await interaction.response.send_modal(TerminModal())


@tree.command(name="add", description="Fügt einen neuen Spieler zur Liste hinzu")
@app_commands.describe(name="Name", twitch="Twitch-Username")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def add(interaction: discord.Interaction, name: str, twitch: str):
    key = name.strip().lower()
    TWITCH_MAP[key] = twitch.strip()
    await interaction.response.send_message(
        f"✅ `{key}` wurde mit Twitch `{twitch.strip()}` hinzugefügt.",
        ephemeral=True,
    )


@tree.command(
    name="playerexit",
    description=(
        "Spieler aus Division austragen und alle Spiele als FF gegen ihn "
        "werten (nur Admin)"
    ),
)
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def playerexit(interaction: discord.Interaction):
    member = interaction.user
    if not isinstance(member, discord.Member):
        await interaction.response.send_message(
            "❌ Konnte Mitgliedsdaten nicht lesen.",
            ephemeral=True,
        )
        return

    if not has_admin_role(member):
        await interaction.response.send_message(
            "⛔ Du hast keine Berechtigung diesen Befehl zu nutzen.",
            ephemeral=True,
        )
        return

    view = PlayerExitDivisionSelectView(requester=member)
    await interaction.response.send_message(
        "📤 Spieler-Exit starten:\nBitte Division auswählen.",
        view=view,
        ephemeral=True,
    )


@tree.command(name="help", description="Zeigt eine Übersicht aller verfügbaren Befehle")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📖 TFL Bot Hilfe",
        description="Aktive Befehle:",
        color=0x00FFCC,
    )

    embed.add_field(
        name="/termin",
        value="Neues Match eintragen, Event erstellen (kein Sheet)",
        inline=False,
    )
    embed.add_field(
        name="/restprogramm",
        value="Offene Spiele je Division, optional Spieler-Filter.",
        inline=False,
    )
    embed.add_field(
        name="/result",
        value=(
            "Ergebnis melden (schreibt ins DIV-Sheet & postet in den "
            "Ergebnischannel)."
        ),
        inline=False,
    )
    embed.add_field(
        name="/playerexit",
        value=(
            "Admin: Spieler austragen (alle Spiele FF gegen ihn, Name "
            "durchgestrichen)."
        ),
        inline=False,
    )
    embed.add_field(
        name="/spielplan",
        value=(
            "Admin: Hin- & Rückrunde erzeugen und ins DIV-Sheet "
            "schreiben."
        ),
        inline=False,
    )
    embed.add_field(
        name="/pick",
        value=(
            "Restream für ein Event setzen (ZSR oder privater Link). "
            "Erweitert den Eventtitel um '(Restream)'."
        ),
        inline=False,
    )
    embed.add_field(
        name="/showpicks",
        value="Zeigt alle zukünftigen Events ohne Restream (Basis für /pick).",
        inline=False,
    )
    embed.add_field(
        name="/restreams",
        value="Zeigt alle zukünftigen Events mit '(Restream)' im Titel.",
        inline=False,
    )
    embed.add_field(
        name="/add",
        value="Spieler → TWITCH_MAP hinzufügen (nicht persistent).",
        inline=False,
    )
    embed.add_field(
        name="/sync",
        value="Admin: Slash-Commands synchronisieren.",
        inline=False,
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(
    name="spielplan",
    description="(Admin) Erstellt Hin-/Rückrunde (jeder gg. jeden) und schreibt alles ins Sheet",
)
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(division="Welche Division?")
@app_commands.choices(
    division=[
        app_commands.Choice(name="Division 1", value="1"),
        app_commands.Choice(name="Division 2", value="2"),
        app_commands.Choice(name="Division 3", value="3"),
        app_commands.Choice(name="Division 4", value="4"),
        app_commands.Choice(name="Division 5", value="5"),
        app_commands.Choice(name="Division 6", value="6"),
    ],
)
async def spielplan(
    interaction: discord.Interaction,
    division: app_commands.Choice[str],
):
    member = interaction.user
    if not isinstance(member, discord.Member):
        await interaction.response.send_message(
            "❌ Konnte Mitgliedsdaten nicht lesen.",
            ephemeral=True,
        )
        return

    if not has_admin_role(member):
        await interaction.response.send_message(
            "⛔ Du hast keine Berechtigung diesen Befehl zu nutzen.",
            ephemeral=True,
        )
        return

    try:
        players = spielplan_read_players(division.value)
        if len(players) < 2:
            await interaction.response.send_message(
                (
                    f"❌ Zu wenig Spieler in Division {division.value} gefunden "
                    "(zu wenige Namen in D/F)."
                ),
                ephemeral=True,
            )
            return

        rounds = spielplan_build_matches(players)
        ws = _get_div_ws(division.value)
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
        await interaction.response.send_message(
            f"❌ Fehler bei /spielplan: {e}",
            ephemeral=True,
        )


@tree.command(
    name="sync",
    description="(Admin) Slash-Commands für diese Guild synchronisieren",
)
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def sync_cmd(interaction: discord.Interaction):
    member = interaction.user
    if not isinstance(member, discord.Member) or not has_admin_role(member):
        await interaction.response.send_message(
            "⛔ Keine Berechtigung.",
            ephemeral=True,
        )
        return

    try:
        await interaction.response.defer(ephemeral=True, thinking=True)
        synced = await tree.sync(guild=discord.Object(id=GUILD_ID))
        names = ", ".join(sorted(c.name for c in synced))

        await interaction.followup.send(
            f"✅ Synced {len(synced)} Commands: {names}",
            ephemeral=True,
        )

    except Exception as e:
        print(f"[SYNC] Fehler: {e}")
        try:
            await interaction.followup.send(
                "❌ Sync ist fehlgeschlagen. Bitte Logs prüfen.",
                ephemeral=True,
            )
        except Exception:
            pass


# =========================================================
# /restprogramm View
# =========================================================
class RestprogrammView(discord.ui.View):
    def __init__(self, start_div: str = "1"):
        super().__init__(timeout=180)
        self.division_value = start_div
        self.player_value = "Komplett"

        # View-Bestandteile hinzufügen
        self.add_item(self.DivSelect(self))
        self.add_item(self.PlayerSelect(self))

    # Text für die Steuerungs-Nachricht
    def header_text(self) -> str:
        if self.player_value and self.player_value != "Komplett":
            filter_part = f"Aktueller Spieler-Filter: **{self.player_value}**"
        else:
            filter_part = "Aktueller Spieler-Filter: **Komplett**"

        return (
            f"📋 Restprogramm – Division {self.division_value} gewählt.\n"
            f"{filter_part}\n"
            "Spieler auswählen oder direkt 'Anzeigen' drücken."
        )

    def set_division(self, new_div: str):
        """
        Division wechseln, Spieler-Filter zurücksetzen und PlayerSelect neu aufbauen.
        """
        self.division_value = new_div
        self.player_value = "Komplett"

        # vorhandenes PlayerSelect entfernen
        for child in list(self.children):
            if isinstance(child, RestprogrammView.PlayerSelect):
                self.remove_item(child)

        # neuen PlayerSelect für die neue Division hinzufügen
        self.add_item(self.PlayerSelect(self))

    class DivSelect(discord.ui.Select):
        def __init__(self, parent_view: "RestprogrammView"):
            self.parent_view = parent_view
            options = [
                discord.SelectOption(label="Division 1", value="1"),
                discord.SelectOption(label="Division 2", value="2"),
                discord.SelectOption(label="Division 3", value="3"),
                discord.SelectOption(label="Division 4", value="4"),
                discord.SelectOption(label="Division 5", value="5"),
                discord.SelectOption(label="Division 6", value="6"),
            ]

            # aktuell gewählte Division im Dropdown markieren
            for opt in options:
                opt.default = (opt.value == parent_view.division_value)

            super().__init__(
                placeholder="Division wählen …",
                min_values=1,
                max_values=1,
                options=options,
            )

        async def callback(self, interaction: discord.Interaction):
            # Neue Division setzen und PlayerSelect neu bauen
            new_div = self.values[0]
            self.parent_view.set_division(new_div)

            # eigene Optionen (Defaults) updaten, damit die Auswahl sichtbar bleibt
            for opt in self.options:
                opt.default = (opt.value == new_div)

            await interaction.response.edit_message(
                content=self.parent_view.header_text(),
                view=self.parent_view,
            )

    class PlayerSelect(discord.ui.Select):
        def __init__(self, parent_view: "RestprogrammView"):
            self.parent_view = parent_view

            # Spieler laden – Fehler abfangen, damit das View nicht crasht
            try:
                players = get_players_for_div(parent_view.division_value)
            except Exception as e:
                print(f"[RESTPROGRAMM] PlayerSelect init Fehler: {e}")
                players = []

            opts = [discord.SelectOption(label="Komplett", value="Komplett")]
            for p in players:
                opts.append(discord.SelectOption(label=p, value=p))

            # aktuellen Filter als default markieren
            for opt in opts:
                opt.default = (opt.value == parent_view.player_value)

            super().__init__(
                placeholder="Spieler filtern … (optional)",
                min_values=1,
                max_values=1,
                options=opts,
            )

        async def callback(self, interaction: discord.Interaction):
            # Auswahl merken
            self.parent_view.player_value = self.values[0]

            # Dropdown-Auswahl sichtbar halten
            for opt in self.options:
                opt.default = (opt.value == self.parent_view.player_value)

            await interaction.response.edit_message(
                content=self.parent_view.header_text(),
                view=self.parent_view,
            )

    @discord.ui.button(label="Anzeigen", style=discord.ButtonStyle.primary)
    async def show_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Ergebnisliste in derselben Nachricht anzeigen
        await _rp_show(interaction, self.division_value, self.player_value)


@tree.command(
    name="restprogramm",
    description="Zeigt offene Spiele: Division wählen, Spieler wählen, anzeigen.",
)
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def restprogramm(interaction: discord.Interaction):
    try:
        view = RestprogrammView(start_div="1")
        await interaction.response.send_message(
            view=view,
            content=view.header_text(),
            ephemeral=True,
        )

    except Exception as e:
        print(f"[RESTPROGRAMM] Fehler im Command: {e}")
        try:
            await interaction.response.send_message(
                "❌ Konnte das Restprogramm nicht starten.",
                ephemeral=True,
            )
        except Exception:
            pass


@tree.command(
    name="pick",
    description="Restream für ein Event auswählen (ZSR oder privater Link)",
)
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def pick(interaction: discord.Interaction):
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

    try:
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send(
                "❌ Konnte Guild nicht ermitteln.",
                ephemeral=True,
            )
            return

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        events = await guild.fetch_scheduled_events()

        selectable = []
        for ev in events:
            if ev.status not in (
                discord.EventStatus.scheduled,
                discord.EventStatus.active,
            ):
                continue
            if not ev.start_time or ev.start_time <= now_utc:
                continue
            if "(restream)" in (ev.name or "").lower():
                continue
            selectable.append(ev)

        if not selectable:
            await interaction.followup.send(
                "📭 Es gibt aktuell keine zukünftigen Events ohne Restream.",
                ephemeral=True,
            )
            return

        view = PickView(selectable, requester=member)
        await interaction.followup.send(
            "Bitte Event wählen und anschließend die Restream-Quelle auswählen.",
            view=view,
            ephemeral=True,
        )

    except Exception as e:
        await interaction.followup.send(
            f"❌ Fehler bei /pick: {e}",
            ephemeral=True,
        )


@tree.command(
    name="showpicks",
    description="Zeigt alle zukünftigen Events ohne Restream (für /pick)",
)
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def showpicks(interaction: discord.Interaction):
    try:
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send(
                "❌ Konnte Guild nicht ermitteln.",
                ephemeral=True,
            )
            return

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        events = await guild.fetch_scheduled_events()

        selectable = []
        for ev in events:
            if ev.status not in (
                discord.EventStatus.scheduled,
                discord.EventStatus.active,
            ):
                continue
            if not ev.start_time or ev.start_time <= now_utc:
                continue
            if "(restream)" in (ev.name or "").lower():
                continue
            selectable.append(ev)

        if not selectable:
            await interaction.followup.send(
                "📭 Es gibt aktuell keine zukünftigen Events ohne Restream.",
                ephemeral=True,
            )
            return

        selectable.sort(key=lambda e: e.start_time or now_utc)
        lines = ["🎯 Events, die für /pick zur Verfügung stehen:", ""]
        for ev in selectable:
            lines.append(_format_event_line_for_post(ev))

        await interaction.followup.send("\n".join(lines), ephemeral=True)

    except Exception as e:
        await interaction.followup.send(
            f"❌ Fehler bei /showpicks: {e}",
            ephemeral=True,
        )


@tree.command(
    name="restreams",
    description="Zeigt alle zukünftigen Events mit '(Restream)' im Titel",
)
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def restreams(interaction: discord.Interaction):
    try:
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send(
                "❌ Konnte Guild nicht ermitteln.",
                ephemeral=True,
            )
            return

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        events = await guild.fetch_scheduled_events()

        restream_events = []
        for ev in events:
            if ev.status not in (
                discord.EventStatus.scheduled,
                discord.EventStatus.active,
            ):
                continue
            if not ev.start_time or ev.start_time <= now_utc:
                continue
            if "(restream)" not in (ev.name or "").lower():
                continue
            restream_events.append(ev)

        if not restream_events:
            await interaction.followup.send(
                "📭 Aktuell sind keine zukünftigen Restream-Events eingetragen.",
                ephemeral=True,
            )
            return

        restream_events.sort(key=lambda e: e.start_time or now_utc)
        lines = ["🔁 Geplante Restreams (nur Events in der Zukunft)", ""]
        for ev in restream_events:
            lines.append(_format_event_line_for_post(ev))

        await interaction.followup.send("\n".join(lines), ephemeral=True)

    except Exception as e:
        await interaction.followup.send(
            f"❌ Fehler bei /restreams: {e}",
            ephemeral=True,
        )


# =========================================================
# on_ready
# =========================================================
_client_synced_once = False
_cache_task_started = False


@client.event
async def on_ready():
    print("Bot ist online")
    global _client_synced_once, _cache_task_started
    print(f"✅ Eingeloggt als {client.user} (ID: {client.user.id})")

    if not _client_synced_once:
        await tree.sync(guild=discord.Object(id=GUILD_ID))
        _client_synced_once = True
        print("✅ Slash-Befehle synchronisiert")

    try:
        asyncio.create_task(start_webserver(client))
        print("🌐 Webserver gestartet (/health, /api/results, /api/upcoming)")
    except Exception as e:
        print(f"⚠️ Webserver-Start fehlgeschlagen: {e}")

    if not _cache_task_started:
        asyncio.create_task(refresh_api_cache(client))
        _cache_task_started = True
        print("♻️ Cache-Refresher gestartet (alle 5 Minuten)")

    print("🤖 Bot bereit")


# =========================================================
# RUN
# =========================================================
client.run(TOKEN)
