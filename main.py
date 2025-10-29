import discord
import pytz
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
import os
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import asyncio

# =========================================================
# .env laden / Konfiguration
# =========================================================
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))
EVENT_CHANNEL_ID = int(os.getenv("DISCORD_EVENT_CHANNEL_ID", "0"))
RESTREAM_CHANNEL_ID = int(os.getenv("RESTREAM_CHANNEL_ID", "0"))
SHOWRESTREAMS_CHANNEL_ID = int(os.getenv("SHOWRESTREAMS_CHANNEL_ID", "1277949546650931241"))
CREDS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

# optionale Role-IDs (string/int aus ENV), fallback auf Namen
ADMIN_ROLE_ID = os.getenv("ADMIN_ROLE_ID")
TFL_ROLE_ID = os.getenv("TFL_ROLE_ID")

# Discord-Client + Intents
intents = discord.Intents.default()
intents.members = True  # wir brauchen Rolleninfos stabil
client = commands.Bot(command_prefix="/", intents=intents)
tree = client.tree

# Zeitzone
BERLIN_TZ = pytz.timezone("Europe/Berlin")

def today_berlin_date() -> datetime.date:
    return datetime.datetime.now(BERLIN_TZ).date()

def parse_date(d: str) -> datetime.date:
    return datetime.datetime.strptime(d, "%d.%m.%Y").date()

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

async def send_long_message_interaction(interaction: discord.Interaction, content: str, ephemeral: bool = False):
    if len(content) <= 1900 and not interaction.response.is_done():
        await interaction.response.send_message(content, ephemeral=ephemeral)
    else:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=ephemeral)
        for part in chunk_text(content):
            await interaction.followup.send(part, ephemeral=ephemeral)

async def send_long_message_channel(channel: discord.abc.Messageable, content: str):
    if len(content) <= 2000:
        await channel.send(content)
    else:
        for part in chunk_text(content, limit=1990):
            await channel.send(part)

def map_sheet_channel_to_label(val: str) -> str:
    v = (val or "").strip().upper()
    if v == "SGD1":
        return "SG1"
    if v == "SGD2":
        return "SG2"
    return v  # ZSR oder leer/sonstiges

# =========================================================
# Twitch-Namen Mapping (Laufzeit erweiterbar via /add)
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
    "hideonbush": "hideonbush1909"
}

# =========================================================
# Google Sheets Verbindung
# =========================================================
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDS = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
GC = gspread.authorize(CREDS)

WB = GC.open("Season #3 - Spielbetrieb")
SHEET = WB.worksheet("League & Cup Schedule")

def _cell(row, idx0):
    return (row[idx0].strip() if 0 <= idx0 < len(row) else "")

# =========================================================
# Spaltenkonstanten (1-basiert fürs Sheet, 0-basiert für row[])
# Für "League & Cup Schedule"
# =========================================================
COL_DIVISION = 1        # A
COL_DATUM = 2           # B
COL_UHRZEIT = 3         # C
COL_SPIELER1 = 4        # D
COL_SPIELER2 = 5        # E
COL_MODUS = 6           # F
COL_MULTISTREAM = 7     # G
COL_RESTREAM = 8        # H
COL_COM = 9             # I
COL_CO = 10             # J
COL_TRACK = 11          # K
COL_EVENT_ID = 12       # L (neu: Discord Scheduled Event ID)

# Für "<div>.DIV"
DIV_COL_TIMESTAMP = 2   # Spalte B
DIV_COL_MODE = 3        # Spalte C
DIV_COL_RESULT = 5      # Spalte E
DIV_COL_LINK = 7        # Spalte G
DIV_COL_REPORTER = 8    # Spalte H
DIV_COL_LEFT = 4        # Spalte D (1-basiert)
DIV_COL_MARKER = 5      # Spalte E (1-basiert)
DIV_COL_RIGHT = 6       # Spalte F (1-basiert)
DIV_COL_PLAYERS = 12    # Spalte L (1-basiert)

# =========================================================
# Rollen-Checks
# =========================================================
def has_admin_role(member: discord.Member) -> bool:
    # erst ID prüfen, falls gesetzt
    if ADMIN_ROLE_ID:
        admin_id_int = int(ADMIN_ROLE_ID)
        return any(r.id == admin_id_int for r in member.roles)

    # fallback: Rollenname "Admin"
    return any(r.name == "Admin" for r in member.roles)

def has_tfl_role(member: discord.Member) -> bool:
    if TFL_ROLE_ID:
        tfl_id_int = int(TFL_ROLE_ID)
        return any(r.id == tfl_id_int for r in member.roles)

    # fallback: Rollenname "Try Force League"
    return any(r.name == "Try Force League" for r in member.roles)

# =========================================================
# Hilfsfunktionen Divisionstabellen / Restprogramm
# =========================================================
def get_players_for_div(div: str):
    """
    Liest aus dem Sheet '<div>.DIV' die Spielernamen aus Spalte L (ab Zeile 2).
    Gibt eindeutige Liste zurück.
    """
    ws_name = f"{div}.DIV"
    ws = WB.worksheet(ws_name)
    values = ws.col_values(DIV_COL_PLAYERS)  # Spalte L
    raw_players = [v.strip() for v in values[1:] if v and v.strip() != ""]
    seen = set()
    players_unique = []
    for p in raw_players:
        low = p.lower()
        if low not in seen:
            seen.add(low)
            players_unique.append(p)
    return players_unique

def get_players_by_divisions():
    """
    Struktur { "1": ["Komplett", "SpielerA", ...], ... }
    Division 6 ist drin, falls du sie brauchst.
    """
    result = {}
    for div in ["1", "2", "3", "4", "5", "6"]:
        try:
            players = get_players_for_div(div)
        except Exception:
            players = []
        result[div] = ["Komplett"] + players
    return result

def load_open_from_div_tab(div: str, player_query: str = ""):
    """
    Liest Tab '{div}.DIV' und gibt offene Paarungen zurück.
    D = Spieler 1
    E = Marker ("vs" = offen)
    F = Spieler 2
    Wir geben (row_nr, "L", p1, p2) zurück.
    """
    ws_name = f"{div}.DIV"
    ws = WB.worksheet(ws_name)
    rows = ws.get_all_values()

    out = []
    q = player_query.strip().lower()

    # 0-basierte Indizes im rows-Array:
    D_idx0 = DIV_COL_LEFT - 1    # D -> index 3
    E_idx0 = DIV_COL_MARKER - 1  # E -> index 4
    F_idx0 = DIV_COL_RIGHT - 1   # F -> index 5

    for r_idx in range(1, len(rows)):  # ab Zeile 2
        row = rows[r_idx]
        p1 = _cell(row, D_idx0)
        marker = _cell(row, E_idx0).lower()
        p2 = _cell(row, F_idx0)

        if (p1 or p2) and marker == "vs":
            if not q or (q in p1.lower() or q in p2.lower()):
                out.append((r_idx + 1, "L", p1, p2))

    return out

async def _rp_show(interaction: discord.Interaction, division_value: str, player_filter: str):
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=False)

        effective_filter = "" if (not player_filter or player_filter.lower() == "komplett") else player_filter
        matches = load_open_from_div_tab(division_value, player_query=effective_filter)

        if not matches:
            txt = f"📭 Keine offenen Spiele in **Division {division_value}**."
            if effective_filter:
                txt += f" (Filter: *{effective_filter}*)"
            await interaction.followup.send(txt, ephemeral=True)
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

        await interaction.followup.send("\n".join(lines), ephemeral=True)

    except Exception as e:
        try:
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ Fehler bei /restprogramm: {e}", ephemeral=True)
            else:
                await interaction.response.defer(ephemeral=True, thinking=False)
                await interaction.followup.send(f"❌ Fehler bei /restprogramm: {e}", ephemeral=True)
        except Exception as inner:
            print(f"Fehler in _rp_show: {e} / {inner}")

class RestprogrammView(discord.ui.View):
    def __init__(self, players_by_div: dict, start_div: str = "1"):
        super().__init__(timeout=180)

        self.players_by_div = players_by_div
        self.division_value = start_div
        self.player_value = "Komplett"

        self.add_item(self.DivSelect(self))
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
            super().__init__(
                placeholder="Division wählen …",
                min_values=1,
                max_values=1,
                options=options
            )

        async def callback(self, interaction: discord.Interaction):
            self.parent_view.division_value = self.values[0]

            new_view = RestprogrammView(
                players_by_div=self.parent_view.players_by_div,
                start_div=self.parent_view.division_value
            )

            await interaction.response.edit_message(
                content=f"📋 Restprogramm – Division {new_view.division_value} gewählt.\nSpieler auswählen oder direkt 'Anzeigen' drücken.",
                view=new_view
            )

    class PlayerSelect(discord.ui.Select):
        def __init__(self, parent_view: "RestprogrammView"):
            self.parent_view = parent_view

            current_div = parent_view.division_value
            players = parent_view.players_by_div.get(current_div, ["Komplett"])
            opts = [discord.SelectOption(label=p, value=p) for p in players]

            super().__init__(
                placeholder="Spieler filtern … (optional)",
                min_values=1,
                max_values=1,
                options=opts
            )

        async def callback(self, interaction: discord.Interaction):
            self.parent_view.player_value = self.values[0]
            await interaction.response.send_message(
                f"🎯 Spieler-Filter gesetzt: **{self.parent_view.player_value}**",
                ephemeral=True
            )

    @discord.ui.button(label="Anzeigen", style=discord.ButtonStyle.primary)
    async def show_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _rp_show(
            interaction,
            self.division_value,
            self.player_value
        )

# =========================================================
# Hilfs-Layer für League-&-Cup-Schedule
# =========================================================

def sheet_get_rows():
    """
    Holt alle Zeilen aus 'League & Cup Schedule' als Liste von Listen.
    NICHT jedes Mal neu aus der API holen, wenn schon vorhanden:
    -> hier einfach direkte Abfrage, Aufrufer puffern selber wenn sie mehrfach brauchen.
    """
    return SHEET.get_all_values()

def parse_future_matches(rows, today_date: datetime.date, require_restream=None):
    """
    rows: Output von sheet_get_rows()
    today_date: cutoff (nur >= heute)
    require_restream:
        True  -> nur Zeilen mit Restream (Spalte H nicht leer)
        False -> nur Zeilen ohne Restream (Spalte H leer)
        None  -> egal
    Rückgabe: Liste Tupel (datum, uhrzeit, division, s1, s2, modus, multistream, restream_code, com, co, track, row_index, event_id)
    row_index ist 1-basiert fürs Sheet.
    """
    out = []
    for i, row in enumerate(rows[1:], start=2):  # ab Zeile 2
        # Guard auf Länge
        if len(row) < COL_MULTISTREAM:
            continue

        datum = row[COL_DATUM - 1].strip() if len(row) >= COL_DATUM else ""
        uhrzeit = row[COL_UHRZEIT - 1].strip() if len(row) >= COL_UHRZEIT else ""
        division = row[COL_DIVISION - 1].strip() if len(row) >= COL_DIVISION else ""
        s1 = row[COL_SPIELER1 - 1].strip() if len(row) >= COL_SPIELER1 else ""
        s2 = row[COL_SPIELER2 - 1].strip() if len(row) >= COL_SPIELER2 else ""
        modus = row[COL_MODUS - 1].strip() if len(row) >= COL_MODUS else ""
        multistream = row[COL_MULTISTREAM - 1].strip() if len(row) >= COL_MULTISTREAM else ""
        restream_code = row[COL_RESTREAM - 1].strip() if len(row) >= COL_RESTREAM else ""
        com_val = row[COL_COM - 1].strip() if len(row) >= COL_COM else ""
        co_val = row[COL_CO - 1].strip() if len(row) >= COL_CO else ""
        track_val = row[COL_TRACK - 1].strip() if len(row) >= COL_TRACK else ""
        event_id = row[COL_EVENT_ID - 1].strip() if len(row) >= COL_EVENT_ID else ""

        # Datum prüfen
        try:
            match_date = parse_date(datum)
        except Exception:
            continue
        if match_date < today_date:
            continue

        # Restream-Filter
        if require_restream is True and restream_code == "":
            continue
        if require_restream is False and restream_code != "":
            continue

        out.append((
            datum, uhrzeit, division, s1, s2, modus, multistream,
            restream_code, com_val, co_val, track_val, i, event_id
        ))

    # Sort
    def sort_key(m):
        return datetime.datetime.strptime(m[0] + " " + m[1], "%d.%m.%Y %H:%M")
    out.sort(key=sort_key)
    return out

def normalize_div(name):
    return name.lower().replace(" ", "").replace("-", "").replace(".", "")

def filter_by_division(matches, div_query: str | None):
    if not div_query:
        return matches
    target_norm = normalize_div(div_query)
    return [
        m for m in matches
        if normalize_div(m[2]) == target_norm
    ]

def matches_today(rows, today_str: str):
    """
    Für /today
    rows: SHEET.get_all_values()
    today_str: "dd.mm.yyyy"
    Rückgabe: list[row]
    """
    result = []
    for row in rows[1:]:
        if len(row) >= COL_MULTISTREAM:
            if row[COL_DATUM - 1].strip() == today_str:
                result.append(row)
    # Sort nach Uhrzeit, dann Division
    result.sort(key=lambda x: (x[COL_UHRZEIT - 1], x[COL_DIVISION - 1]))
    return result

# =========================================================
# /termin Modal
# =========================================================

class TerminModal(discord.ui.Modal, title="Neues TFL-Match eintragen"):
    division = discord.ui.TextInput(label="Division", placeholder="z. B. 2. Division", required=True)
    datetime_str = discord.ui.TextInput(label="Datum & Uhrzeit", placeholder="DD.MM.YYYY HH:MM", required=True)
    spieler1 = discord.ui.TextInput(label="Spieler 1", placeholder="Name wie in Liste", required=True)
    spieler2 = discord.ui.TextInput(label="Spieler 2", placeholder="Name wie in Liste", required=True)
    modus = discord.ui.TextInput(label="Modus", placeholder="z. B. Casual Boots", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            parts = self.datetime_str.value.strip().split()
            if len(parts) < 2:
                await interaction.response.send_message("❌ Formatfehler: Nutze `DD.MM.YYYY HH:MM`.", ephemeral=True)
                return

            datum_str, uhrzeit_str = parts[0], parts[1]
            start_dt = BERLIN_TZ.localize(datetime.datetime.strptime(f"{datum_str} {uhrzeit_str}", "%d.%m.%Y %H:%M"))
            end_dt = start_dt + datetime.timedelta(hours=1)

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

            # Event erstellen
            event = await interaction.guild.create_scheduled_event(
                name=f"{self.division.value} | {self.spieler1.value} vs. {self.spieler2.value} | {self.modus.value}",
                description=f"Match in der {self.division.value} zwischen {self.spieler1.value} und {self.spieler2.value}.",
                start_time=start_dt,
                end_time=end_dt,
                entity_type=discord.EntityType.external,
                location=multistream_url,
                privacy_level=discord.PrivacyLevel.guild_only
            )

            # Sheet schreiben (inkl. Event-ID in Spalte L)
            row = [
                self.division.value.strip(),  # A
                datum_str,                    # B
                uhrzeit_str,                  # C
                self.spieler1.value.strip(),  # D
                self.spieler2.value.strip(),  # E
                self.modus.value.strip(),     # F
                multistream_url,              # G
                "",                           # H (Restream-Kanal noch leer)
                "",                           # I Com
                "",                           # J Co
                "",                           # K Track
                event.id                      # L Event-ID
            ]
            SHEET.append_row(row)

            await interaction.response.send_message("✅ Match wurde eingetragen und Event erstellt!", ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(f"❌ Fehler beim Eintragen: {e}", ephemeral=True)

# =========================================================
# /result Workflow
# =========================================================

def load_open_games_for_result(div_number: str):
    """
    Lädt offene Spiele aus {div}.DIV:
    D: Heim
    E: Marker ("vs" = offen)
    F: Auswärts
    """
    ws = WB.worksheet(f"{div_number}.DIV")
    rows = ws.get_all_values()

    out = []
    for idx, row in enumerate(rows, start=1):
        if idx == 1:
            continue  # Header

        heim = _cell(row, DIV_COL_LEFT - 1)   # D
        marker = _cell(row, DIV_COL_MARKER - 1)  # E
        gast = _cell(row, DIV_COL_RIGHT - 1)  # F

        if (heim or gast) and marker.lower() == "vs":
            out.append({
                "row_index": idx,
                "heim": heim,
                "auswaerts": gast
            })

    return out

def get_unique_heimspieler(div_number: str):
    games = load_open_games_for_result(div_number)
    heim_set = {g["heim"] for g in games if g["heim"]}
    return sorted(list(heim_set))

async def batch_update_result(ws, row_index, now_str, mode_val, ergebnis, raceroom_val, reporter_name):
    """
    Statt 5x update_cell einzeln wird hier ein Range-Update gemacht.
    B..H = Timestamp, Mode, [leer für D/E-abhängig], Ergebnis, Link, Reporter
    Wir schreiben die Zellen B, C, E, G, H (und lassen D/F unverändert).
    Das Range B..H hat 6 Felder: B,C,D,E,F,G,H -> wir füllen passend.
    Spalte-Index (1-basiert):
      B = 2 Timestamp
      C = 3 Modus
      D = 4 (lassen wir leer, damit alter Wert bleiben soll? Achtung: Range-Update überschreibt ALLES!)
    
    Wir müssen also gezielt einzelne Zellen updaten, um nicht Heim/Gast zu killen.
    Kompromiss: 2 Batch Updates statt 5 Einzelupdates,
    via worksheet.batch_update().
    """
    reqs = [
        {
            "range": f"B{row_index}:C{row_index}",
            "values": [[now_str, mode_val]]
        },
        {
            "range": f"E{row_index}:H{row_index}",
            "values": [[ergebnis, "", raceroom_val, reporter_name]]
        }
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
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        division = self.values[0]
        heimspieler_liste = get_unique_heimspieler(division)

        if not heimspieler_liste:
            await interaction.response.edit_message(
                content=f"Keine offenen Spiele in Division {division}.",
                view=None
            )
            return

        view = ResultHomeSelectView(
            division=division,
            heimspieler_list=heimspieler_liste,
            requester=self.requester
        )

        await interaction.response.edit_message(
            content=f"Division {division} ausgewählt.\nWer hat Heimrecht?",
            view=view
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
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        heim = self.values[0]
        alle_spiele = load_open_games_for_result(self.division)
        spiele_dieses_heims = [
            g for g in alle_spiele if g["heim"] == heim
        ]

        if not spiele_dieses_heims:
            await interaction.response.edit_message(
                content=f"Keine offenen Spiele gefunden, in denen {heim} Heim ist.",
                view=None
            )
            return

        view = ResultGameSelectView(
            division=self.division,
            heim=heim,
            games=spiele_dieses_heims,
            requester=self.requester
        )

        await interaction.response.edit_message(
            content=f"Heimrecht: {heim}\nBitte Spiel auswählen:",
            view=view
        )

class ResultHomeSelectView(discord.ui.View):
    def __init__(self, division: str, heimspieler_list, requester: discord.Member, timeout=180):
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
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=str(idx)
                )
            )

        super().__init__(
            placeholder="Bitte Spiel auswählen",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        sel_idx = int(self.values[0])
        game_info = self.games[sel_idx]

        modal = ResultEntryModal(
            division=self.division,
            row_index=game_info["row_index"],
            heim=game_info["heim"],
            auswaerts=game_info["auswaerts"],
            requester=self.requester
        )
        await interaction.response.send_modal(modal)

class ResultGameSelectView(discord.ui.View):
    def __init__(self, division: str, heim: str, games, requester: discord.Member, timeout=180):
        super().__init__(timeout=timeout)
        self.add_item(ResultGameSelect(division, heim, games, requester))

class ResultEntryModal(discord.ui.Modal, title="Ergebnis eintragen"):
    """
    Gewinner-Codierung:
    1 = Heim gewinnt -> 2:0
    2 = Auswärts gewinnt -> 0:2
    X = Unentschieden -> 1:1
    """
    def __init__(self, division: str, row_index: int, heim: str, auswaerts: str, requester: discord.Member):
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
            placeholder=f"1 = {short_heim}, 2 = {short_aus}, X = Unentschieden"
        )
        self.mode_input = discord.ui.TextInput(
            label="Modus",
            style=discord.TextStyle.short,
            required=True,
            placeholder="Ambrosia, Crosskeys o.Ä.",
            max_length=50
        )
        self.raceroom_input = discord.ui.TextInput(
            label="Raceroom-Link",
            style=discord.TextStyle.short,
            required=True,
            placeholder="https://raceroom.xyz/..."
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
                ephemeral=True
            )
            return

        try:
            ws = WB.worksheet(f"{self.division}.DIV")

            now = datetime.datetime.now(BERLIN_TZ)
            now_str = now.strftime("%d.%m.%Y %H:%M")

            # Batch-Update (Timestamp, Modus, Ergebnis, Raceroom, Reporter)
            await asyncio.get_event_loop().run_in_executor(
                None,
                batch_update_result,
                ws,
                self.row_index,
                now_str,
                mode_val,
                ergebnis,
                raceroom_val,
                str(self.requester)
            )

            msg = (
                f"✅ Ergebnis gespeichert für Division {self.division}:\n"
                f"{self.heim} vs {self.auswaerts} => {ergebnis}\n"
                f"Modus: {mode_val}\n"
                f"Raceroom: {raceroom_val}"
            )
            await interaction.followup.send(content=msg, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(
                content=f"❌ Konnte nicht ins Sheet schreiben: {e}",
                ephemeral=True
            )

# =========================================================
# /playerexit Workflow (Admin)
# =========================================================

def list_div_players(div_number: str):
    try:
        return get_players_for_div(div_number)
    except Exception:
        return []

def playerexit_apply(div_number: str, quitting_player: str, reporter: str):
    """
    Hard-Drop eines Spielers:
    - ALLE seine Spiele in der Division werden als Forfeit gegen ihn gewertet.
    - Links (Spalte D) => Ergebnis 0:2
    - Rechts (Spalte F) => Ergebnis 2:0
    Wir nutzen batch_update() um Requests zu verringern.
    Namen werden durchgestrichen.
    """
    ws = WB.worksheet(f"{div_number}.DIV")
    rows = ws.get_all_values()

    now = datetime.datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M")
    updates = []
    strike_cells = []

    for idx, row in enumerate(rows[1:], start=2):  # ab Zeile 2
        left_player = _cell(row, DIV_COL_LEFT - 1)
        right_player = _cell(row, DIV_COL_RIGHT - 1)

        lp_match = (left_player.lower() == quitting_player.lower()) if left_player else False
        rp_match = (right_player.lower() == quitting_player.lower()) if right_player else False

        if not (lp_match or rp_match):
            continue

        if lp_match:
            result_val = "0:2"   # quitter links verliert
            strike_cells.append(f"D{idx}")
        else:
            result_val = "2:0"   # quitter rechts verliert
            strike_cells.append(f"F{idx}")

        # Batch Range Updates:
        # B (Timestamp), C ("FF"), E (Ergebnis), G ("FF"), H (Reporter)
        updates.append({
            "range": f"B{idx}:H{idx}",
            "values": [[now, "FF", "", result_val, "FF", reporter]]
        })

    if updates:
        ws.batch_update(updates)

    # Namen durchstreichen
    if strike_cells:
        style = {
            "textFormat": {
                "strikethrough": True
            }
        }
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
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        div_number = self.values[0]

        try:
            players = list_div_players(div_number)
        except Exception as e:
            await interaction.response.edit_message(
                content=f"❌ Konnte Spieler nicht laden ({e}).",
                view=None
            )
            return

        if not players:
            await interaction.response.edit_message(
                content=f"Keine Spieler in Division {div_number} gefunden.",
                view=None
            )
            return

        view = PlayerExitPlayerSelectView(
            division=div_number,
            players=players,
            requester=self.requester
        )

        await interaction.response.edit_message(
            content=f"Division {div_number} gewählt.\nWelcher Spieler steigt aus?",
            view=view
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

        options = [
            discord.SelectOption(label=p, value=p)
            for p in players
        ]

        super().__init__(
            placeholder="Spieler wählen (steigt aus)",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        quitting_player = self.values[0]

        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=False)

        try:
            playerexit_apply(
                div_number=self.division,
                quitting_player=quitting_player,
                reporter=str(self.requester)
            )

            await interaction.followup.send(
                content=(
                    f"✅ `{quitting_player}` in Division {self.division} ausgetragen.\n"
                    f"Alle Spiele (auch bereits gespielte) wurden als FF gegen ihn gewertet "
                    f"und der Name wurde durchgestrichen."
                ),
                ephemeral=True
            )

        except Exception as e:
            await interaction.followup.send(
                content=f"❌ Fehler beim Austragen: {e}",
                ephemeral=True
            )

class PlayerExitPlayerSelectView(discord.ui.View):
    def __init__(self, division: str, players, requester: discord.Member, timeout=180):
        super().__init__(timeout=timeout)
        self.add_item(PlayerExitPlayerSelect(division, players, requester))

# =========================================================
# Spielplan / Round Robin
# =========================================================

def _get_div_ws(div_number: str):
    ws_name = f"{div_number}.DIV"
    return WB.worksheet(ws_name)

def spielplan_read_players(div_number: str):
    """
    Liest Spielernamen aus Spalte L (ab Zeile 2) des Tabs {div}.DIV.
    Entfernt Duplikate, Reihenfolge wie im Sheet.
    """
    ws = _get_div_ws(div_number)
    values = ws.col_values(DIV_COL_PLAYERS)
    raw_players = [v.strip() for v in values[1:] if v and v.strip() != ""]
    seen = set()
    result = []
    for p in raw_players:
        low = p.lower()
        if low not in seen:
            seen.add(low)
            result.append(p)
    return result

def spielplan_build_rounds(players: list[str]) -> list[list[tuple[str, str]]]:
    """
    Classic Circle Method.
    Jeder Spieltag ist Liste von (home, away).
    Jeder Spieler max 1x pro Spieltag.
    """
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
    """
    Hin- und Rückrunde erzeugen.
    Rückrunde = Heim/Auswärts gedreht.
    """
    hinrunde = spielplan_build_rounds(players)

    rueckrunde = []
    for day in hinrunde:
        rueckrunde.append([(away, home) for (home, away) in day])

    return hinrunde + rueckrunde

def spielplan_find_next_free_row(ws):
    """
    Findet die erste freie Zeile anhand Spalte D (Heimspieler).
    Zeile 1 = Header.
    """
    col_d = ws.col_values(4)  # Spalte D
    for idx_1based, val in enumerate(col_d, start=1):
        if idx_1based == 1:
            continue
        if val.strip() == "":
            return idx_1based

    return len(col_d) + 1

def spielplan_write(ws, rounds: list[list[tuple[str, str]]]):
    """
    Schreibt ALLE Begegnungen (Hin+Rück) untereinander ohne Leerzeilen.
    Spalte A beginnt bei 1 und zählt einfach hoch, durchgängig.
    (Wir resetten NICHT pro "Spieltag", das entspricht deinem aktuellen tatsächlichen Verhalten.)

    Spalten A..I:
      A = Laufende Nummer (1,2,3,... fortlaufend)
      B = Datum (leer)
      C = Modus (leer)
      D = Heim
      E = "vs"
      F = Gast
      G = Link (leer)
      H = Boteingabe (leer)
      I = Checkbox (leer)
    """
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
# Slash Commands
# =========================================================

@tree.command(name="termin", description="Erstelle einen neuen Termin + Event + Sheet-Eintrag")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def termin(interaction: discord.Interaction):
    await interaction.response.send_modal(TerminModal())

@tree.command(name="today", description="Zeigt alle heutigen Matches")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def today(interaction: discord.Interaction):
    try:
        rows = sheet_get_rows()
        heute_str = datetime.datetime.now().strftime("%d.%m.%Y")
        matches = matches_today(rows, heute_str)

        if not matches:
            await interaction.response.send_message("📭 Heute sind keine Spiele geplant.", ephemeral=True)
            return

        embed = discord.Embed(title=f"TFL-Matches am {heute_str}", color=0x00ffcc)
        for row in matches:
            division = row[COL_DIVISION - 1]
            uhrzeit = row[COL_UHRZEIT - 1]
            s1 = row[COL_SPIELER1 - 1]
            s2 = row[COL_SPIELER2 - 1]
            modus = row[COL_MODUS - 1]
            link = row[COL_MULTISTREAM - 1]

            embed.add_field(
                name=f"{division} – {uhrzeit}",
                value=f"**{s1} vs {s2}**\nModus: {modus}\n[Multistream]({link})",
                inline=False
            )
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message(f"❌ Fehler beim Abrufen: {e}", ephemeral=True)

async def zeige_geplante_spiele(interaction: discord.Interaction, filter_division=None):
    try:
        rows = sheet_get_rows()
        future_all = parse_future_matches(rows, today_berlin_date(), require_restream=None)
        matches = filter_by_division(future_all, filter_division)

        if not matches:
            await interaction.response.send_message("📭 Keine Spiele gefunden.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"{filter_division or 'Alle'} – Geplante Matches",
            color=0x00ffcc
        )
        for m in matches:
            datum, uhrzeit, division, s1, s2, modus, multistream, *_rest = m
            embed.add_field(
                name=f"{division} – {datum} {uhrzeit}",
                value=f"**{s1} vs {s2}**\nModus: {modus}\n[Multistream]({multistream})",
                inline=False
            )
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message(f"❌ Fehler: {e}", ephemeral=True)

@tree.command(name="div1", description="Alle kommenden Spiele der 1. Division")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def div1(interaction: discord.Interaction):
    await zeige_geplante_spiele(interaction, "1. Division")

@tree.command(name="div2", description="Alle kommenden Spiele der 2. Division")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def div2(interaction: discord.Interaction):
    await zeige_geplante_spiele(interaction, "2. Division")

@tree.command(name="div3", description="Alle kommenden Spiele der 3. Division")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def div3(interaction: discord.Interaction):
    await zeige_geplante_spiele(interaction, "3. Division")

@tree.command(name="div4", description="Alle kommenden Spiele der 4. Division")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def div4(interaction: discord.Interaction):
    await zeige_geplante_spiele(interaction, "4. Division")

@tree.command(name="div5", description="Alle kommenden Spiele der 5. Division")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def div5(interaction: discord.Interaction):
    await zeige_geplante_spiele(interaction, "5. Division")

@tree.command(name="div6", description="Alle kommenden Spiele der 6. Division")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def div6(interaction: discord.Interaction):
    await zeige_geplante_spiele(interaction, "6. Division")

@tree.command(name="cup", description="Alle kommenden Cup-Spiele")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def cup(interaction: discord.Interaction):
    await zeige_geplante_spiele(interaction, "TFL Cup")

@tree.command(name="alle", description="Alle Spiele ab heute")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def alle(interaction: discord.Interaction):
    await zeige_geplante_spiele(interaction)

# viewall: nur Spiele ohne Restream-Ziel
@tree.command(name="viewall", description="Zeigt alle kommenden Matches im Listenformat")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def viewall(interaction: discord.Interaction):
    try:
        rows = sheet_get_rows()
        matches = parse_future_matches(
            rows,
            today_berlin_date(),
            require_restream=False  # H leer
        )

        if not matches:
            await interaction.response.send_message(
                "📭 Keine zukünftigen Spiele ohne Restream-Ziel gefunden.",
                ephemeral=True
            )
            return

        lines = [
            f"{m[0]} {m[1]} | {m[2]} | {m[3]} vs. {m[4]} | {m[5]}"
            for m in matches
        ]
        msg = "📋 **Geplante Matches ab heute (ohne Restream-Ziel):**\n" + "\n".join(lines)
        await send_long_message_interaction(interaction, msg, ephemeral=False)

    except Exception as e:
        await interaction.response.send_message(f"❌ Fehler bei /viewall: {e}", ephemeral=True)

# add: erweitert TWITCH_MAP zur Laufzeit
@tree.command(name="add", description="Fügt einen neuen Spieler zur Liste hinzu")
@app_commands.describe(name="Name", twitch="Twitch-Username")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def add(interaction: discord.Interaction, name: str, twitch: str):
    key = name.strip().lower()
    TWITCH_MAP[key] = twitch.strip()
    await interaction.response.send_message(
        f"✅ `{key}` wurde mit Twitch `{twitch.strip()}` hinzugefügt.",
        ephemeral=True
    )

# showrestreams: nur Spiele MIT Restream-Ziel
@tree.command(name="showrestreams", description="Zeigt alle geplanten Restreams ab heute (mit Com/Co/Track)")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def showrestreams(interaction: discord.Interaction):
    try:
        rows = sheet_get_rows()
        rows_w_restream = parse_future_matches(
            rows,
            today_berlin_date(),
            require_restream=True  # H NICHT leer
        )

        if not rows_w_restream:
            await interaction.response.send_message(
                "📭 Keine geplanten Restreams ab heute gefunden.",
                ephemeral=True
            )
            return

        lines = []
        for r in rows_w_restream:
            datum, uhr, _div, s1, s2, modus, _ms, restream_code, com_val, co_val, track_val, _row_idx, _eid = r
            kanal = map_sheet_channel_to_label(restream_code)
            lines.append(
                f"{datum} {uhr} | {kanal} | {s1} vs. {s2} | {modus} | "
                f"Com: {com_val or '—'} | Co: {co_val or '—'} | Track: {track_val or '—'}"
            )

        msg = "🎥 **Geplante Restreams ab heute:**\n" + "\n".join(lines)
        await send_long_message_interaction(interaction, msg, ephemeral=False)

    except Exception as e:
        await interaction.response.send_message(f"❌ Fehler bei /showrestreams: {e}", ephemeral=True)

# ---------- Restream-Workflow (/pick + Modal) ----------

async def update_sheet_and_event_for_restream(interaction: discord.Interaction, selected_row, code, com_val, co_val, track_val):
    """
    selected_row: (wie wir sie aus parse_future_matches bekommen)
        (datum, uhrzeit, division, s1, s2, modus, multistream, restream_code, com, co, track, row_index, event_id)

    code: "ZSR", "SG1", "SG2"
    """
    title_prefix = {
        "ZSR": "RESTREAM ZSR |",
        "SG1": "RESTREAM SGD1 |",
        "SG2": "RESTREAM SGD2 |"
    }[code]
    location_url = {
        "ZSR": "https://www.twitch.tv/zeldaspeedrunsde",
        "SG1": "https://www.twitch.tv/speedgamingdeutsch",
        "SG2": "https://www.twitch.tv/speedgamingdeutsch2",
    }[code]

    (datum, uhrzeit, division, s1, s2, modus, multistream, _oldrest, _oc, _oco, _ot, row_index, event_id) = selected_row

    original_title = f"{division} | {s1} vs. {s2} | {modus}"
    new_title = f"{title_prefix} {original_title}"

    # Event finden:
    event = None
    events = await interaction.guild.fetch_scheduled_events()

    # 1) Versuche direkt per event_id (neu)
    if event_id:
        try:
            event_id_int = int(event_id)
            for ev in events:
                if ev.id == event_id_int:
                    event = ev
                    break
        except Exception:
            event = None

    # 2) Fallback auf "alten" Matching-Ansatz, falls kein event gefunden
    if not event:
        # exakter Titel?
        event = discord.utils.get(events, name=original_title)

    # 3) fuzzy fallback: zeitnah + beide Spielernamen im Titel
    if not event:
        try:
            dt = datetime.datetime.strptime(datum + " " + uhrzeit, "%d.%m.%Y %H:%M")
            start_target = BERLIN_TZ.localize(dt)

            def plausible(ev: discord.ScheduledEvent) -> bool:
                try:
                    ev_start = ev.start_time.astimezone(BERLIN_TZ)
                    within = abs((ev_start - start_target).total_seconds()) <= 90 * 60
                    s1_l = s1.lower()
                    s2_l = s2.lower()
                    name_l = ev.name.lower()
                    names_ok = (s1_l in name_l) and (s2_l in name_l)
                    return within and names_ok
                except Exception:
                    return False

            candidates = [ev for ev in events if plausible(ev)]
            if candidates:
                event = min(
                    candidates,
                    key=lambda ev: abs(
                        (ev.start_time.astimezone(BERLIN_TZ) - start_target).total_seconds()
                    )
                )
        except Exception:
            pass

    if not event:
        raise RuntimeError("Kein passendes Event gefunden.")

    # Event updaten
    await event.edit(name=new_title, location=location_url)

    # Sheet updaten: Spalten H..K (Restream, Com, Co, Track)
    # sheet_update_range = f"H{row_index}:K{row_index}"
    # Werte: H=sheet_value, I=com_val, J=co_val, K=track_val
    sheet_value = {"ZSR": "ZSR", "SG1": "SGD1", "SG2": "SGD2"}[code]
    SHEET.update(
        f"H{row_index}:K{row_index}",
        [[sheet_value, com_val, co_val, track_val]]
    )

    return sheet_value

class RestreamModal(discord.ui.Modal, title="Restream-Optionen festlegen"):
    restream_input = discord.ui.TextInput(
        label="Restream Ziel (ZSR, SG1 oder SG2)",
        placeholder="z. B. ZSR",
        required=True,
        max_length=3
    )
    com_input = discord.ui.TextInput(
        label="Com",
        placeholder="Kommentator/in (optional)",
        required=False,
        max_length=64
    )
    co_input = discord.ui.TextInput(
        label="Co",
        placeholder="Co-Kommentator/in (optional)",
        required=False,
        max_length=64
    )
    track_input = discord.ui.TextInput(
        label="Track",
        placeholder="z. B. German, EN, DE2 (optional)",
        required=False,
        max_length=64
    )

    def __init__(self, selected_row):
        super().__init__()
        self.selected_row = selected_row  # kompletter Datensatz inkl. row_index & event_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=False)

        code = self.restream_input.value.strip().upper()
        allowed = {"ZSR", "SG1", "SG2"}
        if code not in allowed:
            await interaction.followup.send(
                "❌ Ungültiger Code. Erlaubt: ZSR, SG1, SG2",
                ephemeral=True
            )
            return

        com_val = (self.com_input.value or "").strip()
        co_val = (self.co_input.value or "").strip()
        track_val = (self.track_input.value or "").strip()

        try:
            sheet_code = await update_sheet_and_event_for_restream(
                interaction, self.selected_row, code, com_val, co_val, track_val
            )

            extra = []
            if com_val:
                extra.append(f"Com: `{com_val}`")
            if co_val:
                extra.append(f"Co: `{co_val}`")
            if track_val:
                extra.append(f"Track: `{track_val}`")
            suffix = (", " + ", ".join(extra)) if extra else ""

            await interaction.followup.send(
                f"✅ Event & Sheet aktualisiert: `{sheet_code}` gesetzt{suffix}.",
                ephemeral=True
            )

        except Exception as e:
            await interaction.followup.send(
                f"❌ Fehler beim Aktualisieren: {e}",
                ephemeral=True
            )

@tree.command(name="pick", description="Wähle ein Spiel und setze Restream-Ziel + optional Com/Co/Track")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def pick(interaction: discord.Interaction):
    try:
        rows = sheet_get_rows()
        # nur Spiele ohne Restream-Ziel, ab heute
        candidates = parse_future_matches(
            rows,
            today_berlin_date(),
            require_restream=False
        )

        if not candidates:
            await interaction.response.send_message(
                "📭 Keine zukünftigen Spiele ohne Restream-Ziel gefunden.",
                ephemeral=True
            )
            return

        class SpielAuswahl(discord.ui.View):
            def __init__(self, spiele):
                super().__init__(timeout=60)
                options = [
                    discord.SelectOption(
                        label=f"{r[0]} {r[1]} | {r[2]} | {r[3]} vs {r[4]}",
                        value=str(i)
                    )
                    for i, r in enumerate(spiele[:25])
                ]
                self.add_item(self.SpielSelect(options, spiele))

            class SpielSelect(discord.ui.Select):
                def __init__(self, options, spiele):
                    super().__init__(
                        placeholder="Wähle ein Spiel",
                        min_values=1,
                        max_values=1,
                        options=options
                    )
                    self.spiele = spiele

                async def callback(self, interaction2: discord.Interaction):
                    auswahl = int(self.values[0])
                    selected = self.spiele[auswahl]
                    await interaction2.response.send_modal(RestreamModal(selected))

        await interaction.response.send_message(
            "🎮 Bitte wähle ein Spiel zur Bearbeitung:",
            view=SpielAuswahl(candidates),
            ephemeral=True
        )

    except Exception as e:
        await interaction.response.send_message(
            f"❌ Fehler bei /pick: {e}",
            ephemeral=True
        )

@tree.command(name="restreams", description="Alias zu /pick (Restream-Ziel setzen)")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def restreams_alias(interaction: discord.Interaction):
    await pick.callback(interaction)

@tree.command(name="showrestreams_syncinfo", description="(Admin) Info: Auto-Posts 04:00 & 04:30 laufen")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def showrestreams_syncinfo(interaction: discord.Interaction):
    await interaction.response.send_message(
        "⏱️ Auto-Posts aktiv: 04:00 (ohne Restream) & 04:30 (mit Restream).",
        ephemeral=True
    )

# --- /result Command (mit Rollen-Check) ---
@tree.command(name="result", description="Ergebnis melden (nur Orga / Try Force League Rolle)")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def result(interaction: discord.Interaction):
    member = interaction.user
    if not isinstance(member, discord.Member):
        await interaction.response.send_message(
            "❌ Konnte Mitgliedsdaten nicht lesen.",
            ephemeral=True
        )
        return

    if not has_tfl_role(member):
        await interaction.response.send_message(
            "⛔ Du hast keine Berechtigung diesen Befehl zu nutzen.",
            ephemeral=True
        )
        return

    view = ResultDivisionSelectView(requester=member)
    await interaction.response.send_message(
        "Bitte Division auswählen:",
        view=view,
        ephemeral=True
    )

# --- /playerexit Command (nur Admin) ---
@tree.command(name="playerexit", description="Spieler aus Division austragen und alle Spiele als FF gegen ihn werten (nur Admin)")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def playerexit(interaction: discord.Interaction):
    member = interaction.user
    if not isinstance(member, discord.Member):
        await interaction.response.send_message(
            "❌ Konnte Mitgliedsdaten nicht lesen.",
            ephemeral=True
        )
        return

    if not has_admin_role(member):
        await interaction.response.send_message(
            "⛔ Du hast keine Berechtigung diesen Befehl zu nutzen.",
            ephemeral=True
        )
        return

    view = PlayerExitDivisionSelectView(requester=member)
    await interaction.response.send_message(
        "📤 Spieler-Exit starten:\nBitte Division auswählen.",
        view=view,
        ephemeral=True
    )

@tree.command(name="help", description="Zeigt eine Übersicht aller verfügbaren Befehle")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📖 TFL Bot Hilfe",
        description="Alle verfügbaren Befehle mit kurzer Erklärung:",
        color=0x00ffcc
    )

    embed.add_field(
        name="/termin",
        value="➤ Neues Match eintragen, Event erstellen und ins Sheet schreiben",
        inline=False
    )
    embed.add_field(
        name="/today",
        value="➤ Zeigt alle heutigen Spiele (Embed mit Link & Modus)",
        inline=False
    )
    embed.add_field(
        name="/div1 – /div6",
        value="➤ Zeigt alle geplanten Spiele einer bestimmten Division",
        inline=False
    )
    embed.add_field(
        name="/cup",
        value="➤ Zeigt alle geplanten Cup-Spiele",
        inline=False
    )
    embed.add_field(
        name="/alle",
        value="➤ Zeigt alle geplanten Spiele ab heute (alle Divisionen & Cup)",
        inline=False
    )
    embed.add_field(
        name="/viewall",
        value="➤ Zeigt alle Spiele ohne gesetztes Restream-Ziel im Listenformat",
        inline=False
    )
    embed.add_field(
        name="/pick /restreams",
        value="➤ Wähle ein Spiel, setze Restream-Ziel (ZSR, SG1, SG2) + optional Com/Co/Track. Aktualisiert Event & Sheet.",
        inline=False
    )
    embed.add_field(
        name="/showrestreams",
        value="➤ Zeigt alle geplanten Restreams ab heute (Kanal, Com, Co, Track).",
        inline=False
    )
    embed.add_field(
        name="/restprogramm",
        value="➤ Zeigt alle noch offenen Spiele in einer Division. Dropdown: Division wählen, dann optional Spieler filtern, dann 'Anzeigen'. Ausgabe ephemer nur für dich.",
        inline=False
    )
    embed.add_field(
        name="/result",
        value="➤ Ergebnis melden: Division → Heim → Match. Dann Gewinner (1/2/X), Modus, Raceroom eingeben. Bot schreibt Timestamp, Modus, Ergebnis (2:0 / 0:2 / 1:1), Raceroom und deinen Namen in die passende Divisionstabelle.",
        inline=False
    )
    embed.add_field(
        name="/playerexit",
        value="➤ Admin: Spieler aus einer Division entfernen. Alle seine Matches (auch schon gespielte) werden als FF gegen ihn gewertet, Timestamp/Reporter gesetzt und der Name wird durchgestrichen.",
        inline=False
    )
    embed.add_field(
        name="/spielplan",
        value="➤ Admin: Baut Hin- & Rückrunde (Round Robin). Schreibt alles untereinander ins DIV-Sheet. Spalte A startet bei 1.",
        inline=False
    )
    embed.add_field(
        name="/add",
        value="➤ Fügt zur Laufzeit einen neuen Spieler zur TWITCH_MAP hinzu (nicht persistent)",
        inline=False
    )
    embed.add_field(
        name="🔁 Auto-Posts",
        value="➤ 04:00: restreambare Spiele • 04:30: geplante Restreams",
        inline=False
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)

# /spielplan (Admin only)
@tree.command(
    name="spielplan",
    description="(Admin) Erstellt Hin-/Rückrunde (jeder gg. jeden) und schreibt alles ins Sheet"
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
    ]
)
async def spielplan(interaction: discord.Interaction, division: app_commands.Choice[str]):
    # Admin-Check
    member = interaction.user
    if not isinstance(member, discord.Member):
        await interaction.response.send_message(
            "❌ Konnte Mitgliedsdaten nicht lesen.",
            ephemeral=True
        )
        return

    if not has_admin_role(member):
        await interaction.response.send_message(
            "⛔ Du hast keine Berechtigung diesen Befehl zu nutzen.",
            ephemeral=True
        )
        return

    try:
        players = spielplan_read_players(division.value)
        if len(players) < 2:
            await interaction.response.send_message(
                f"❌ Zu wenig Spieler in Division {division.value} gefunden (Spalte L leer oder nur eine Person).",
                ephemeral=True
            )
            return

        rounds = spielplan_build_matches(players)
        ws = _get_div_ws(division.value)
        written = spielplan_write(ws, rounds)

        # Preview erster Spieltag (erster Round-Eintrag aus rounds)
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
            ephemeral=True
        )

# /sync (Admin)
@tree.command(name="sync", description="(Admin) Slash-Commands für diese Guild synchronisieren")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def sync_cmd(interaction: discord.Interaction):
    member = interaction.user
    if not isinstance(member, discord.Member) or not has_admin_role(member):
        await interaction.response.send_message(
            "⛔ Keine Berechtigung.",
            ephemeral=True
        )
        return

    try:
        await interaction.response.defer(ephemeral=True, thinking=True)
        synced = await tree.sync(guild=discord.Object(id=GUILD_ID))
        names = ", ".join(sorted(c.name for c in synced))

        await interaction.followup.send(
            f"✅ Synced {len(synced)} Commands: {names}",
            ephemeral=True
        )

    except Exception as e:
        try:
            await interaction.followup.send(
                f"❌ Sync-Fehler: {e}",
                ephemeral=True
            )
        except Exception as inner:
            print(f"Fehler in /sync: {e} / {inner}")

@tree.command(name="restprogramm", description="Zeigt offene Spiele: Division wählen, Spieler wählen, anzeigen.")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def restprogramm(interaction: discord.Interaction):
    try:
        await interaction.response.defer(ephemeral=True, thinking=True)
        players_by_div = get_players_by_divisions()
        view = RestprogrammView(players_by_div=players_by_div, start_div="1")
        await interaction.followup.send(
            "📋 Restprogramm – Division wählen, optional Spieler auswählen, dann 'Anzeigen' drücken.",
            view=view,
            ephemeral=True
        )

    except Exception as e:
        try:
            await interaction.followup.send(f"❌ Fehler bei /restprogramm: {e}", ephemeral=True)
        except Exception:
            print(f"Fehler in /restprogramm: {e}")

# =========================================================
# Auto-Posts (04:00 / 04:30) – jetzt zeitgesteuert statt minütlich pollend
# =========================================================

@tasks.loop(time=datetime.time(hour=4, minute=0, tzinfo=BERLIN_TZ))
async def sende_restream_liste():
    """
    04:00 – restreambare Spiele (H leer / require_restream=False)
    """
    try:
        rows = sheet_get_rows()
        matches = parse_future_matches(
            rows,
            today_berlin_date(),
            require_restream=False
        )

        if not matches:
            return

        lines = [
            f"{m[0]} {m[1]} | {m[2]} | {m[3]} vs. {m[4]} | {m[5]}"
            for m in matches
        ]
        channel = client.get_channel(RESTREAM_CHANNEL_ID)
        if channel:
            msg = (
                "📋 **Geplante Matches ab heute (ohne Restream-Ziel):**\n"
                + "\n".join(lines)
            )
            await send_long_message_channel(channel, msg)

    except Exception as e:
        print(f"❌ Fehler bei täglicher Ausgabe (04:00): {e}")

@tasks.loop(time=datetime.time(hour=4, minute=30, tzinfo=BERLIN_TZ))
async def sende_showrestreams_liste():
    """
    04:30 – geplante Restreams (H befüllt / require_restream=True)
    """
    try:
        rows = sheet_get_rows()
        rows_w_restream = parse_future_matches(
            rows,
            today_berlin_date(),
            require_restream=True
        )

        if not rows_w_restream:
            return

        lines = []
        for r in rows_w_restream:
            datum, uhr, _div, s1, s2, modus, _multistream, restream_code, com_val, co_val, track_val, _row_idx, _eid = r
            kanal = map_sheet_channel_to_label(restream_code)
            lines.append(
                f"{datum} {uhr} | {kanal} | {s1} vs. {s2} | {modus} | "
                f"Com: {com_val or '—'} | Co: {co_val or '—'} | Track: {track_val or '—'}"
            )

        channel = client.get_channel(SHOWRESTREAMS_CHANNEL_ID)
        if channel:
            msg = "🎥 **Geplante Restreams ab heute:**\n" + "\n".join(lines)
            await send_long_message_channel(channel, msg)

    except Exception as e:
        print(f"❌ Fehler bei täglicher Restreams-Ausgabe (04:30): {e}")

# =========================================================
# on_ready
# =========================================================
_client_synced_once = False

@client.event
async def on_ready():
    global _client_synced_once
    print(f"✅ Eingeloggt als {client.user} (ID: {client.user.id})")

    if not _client_synced_once:
        await tree.sync(guild=discord.Object(id=GUILD_ID))
        _client_synced_once = True
        print("✅ Slash-Befehle synchronisiert")

    if not sende_restream_liste.is_running():
        sende_restream_liste.start()
    if not sende_showrestreams_liste.is_running():
        sende_showrestreams_liste.start()

    print("✅ tägliche Tasks aktiv")

# =========================================================
# RUN
# =========================================================
client.run(TOKEN)
