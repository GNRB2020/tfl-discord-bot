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

# .env laden
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))
EVENT_CHANNEL_ID = int(os.getenv("DISCORD_EVENT_CHANNEL_ID")) if os.getenv("DISCORD_EVENT_CHANNEL_ID") else 0
RESTREAM_CHANNEL_ID = int(os.getenv("RESTREAM_CHANNEL_ID"))
SHOWRESTREAMS_CHANNEL_ID = int(os.getenv("SHOWRESTREAMS_CHANNEL_ID", "1277949546650931241"))
CREDS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

# Discord-Client
intents = discord.Intents.default()
client = commands.Bot(command_prefix="/", intents=intents)
tree = client.tree

# Hilfsfunktionen / Konstanten
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

# Twitch-Namen Mapping
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

# Google Sheets Verbindung
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDS = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
GC = gspread.authorize(CREDS)

# Haupt-Workbook
WB = GC.open("Season #3 - Spielbetrieb")
SHEET = WB.worksheet("League & Cup Schedule")

def _cell(row, idx0):
    return (row[idx0].strip() if 0 <= idx0 < len(row) else "")

# --- RESTPROGRAMM / VIEWALL / etc. bestehende Logik ---

def get_players_for_div(div: str):
    """
    Liest aus dem Sheet '<div>.DIV' die Spielernamen aus Spalte L (ab Zeile 2).
    Gibt eine eindeutige Liste zurück.
    """
    ws_name = f"{div}.DIV"
    ws = WB.worksheet(ws_name)
    values = ws.col_values(12)  # Spalte L = 12 (1-basiert)
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
    Ergebnis:
    {
      "1": ["Komplett", "SpielerA", "SpielerB", ...],
      "2": [...],
      ...
    }
    Falls ein Tab mal fehlt oder leer ist, gibt's nur ["Komplett"].
    """
    result = {}
    for div in ["1", "2", "3", "4", "5"]:
        try:
            players = get_players_for_div(div)
        except Exception:
            players = []
        result[div] = ["Komplett"] + players
    return result

def load_open_from_div_tab(div: str, player_query: str = ""):
    """
    Liest Tab '{div}.DIV' (z. B. '1.DIV') und gibt offene Paarungen zurück.

    Tabellenlayout laut deiner letzten Version:
    D = Spieler 1
    E = Marker  ("vs" = offen, alles andere = gespielt)
    F = Spieler 2

    Optionaler Spielerfilter (Substring in P1 oder P2, case-insensitive).

    Rückgabe: Liste[Tuple[int, str, str, str]] = (zeile, block, p1, p2)
              block ist immer 'L' (für Ausgabe "links/rechts")
    """
    ws_name = f"{div}.DIV"
    ws = WB.worksheet(ws_name)
    rows = ws.get_all_values()
    out = []
    q = player_query.strip().lower()

    D, E, F = 3, 4, 5   # 0-basierte Indizes für Spalten D/E/F

    # ab Zeile 2 (Index 1), weil Zeile 1 Header ist
    for r_idx in range(1, len(rows)):
        row = rows[r_idx]
        p1 = _cell(row, D)
        marker = _cell(row, E).lower()
        p2 = _cell(row, F)

        # Offen: Marker exakt "vs"
        if (p1 or p2) and marker == "vs":
            if not q or (q in p1.lower() or q in p2.lower()):
                out.append((r_idx + 1, "L", p1, p2))

    return out

async def _rp_show(interaction: discord.Interaction, division_value: str, player_filter: str):
    """
    Baut die Ausgabe und schickt sie ephemer.

    player_filter == "" oder "Komplett" => alle offenen Spiele der Division
    sonst nur Spiele, an denen der Spieler beteiligt ist.
    """

    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=False)

        effective_filter = "" if (not player_filter or player_filter.lower() == "komplett") else player_filter
        matches = load_open_from_div_tab(division_value, player_query=effective_filter)

        if not matches:
            txt = f"📭 Keine offenen Spiele in **Division {division_value}**."
            if effective_filter:
                txt += f" (Filter: *{effective_filter}*)"

            await interaction.followup.send(
                txt,
                ephemeral=True
            )
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

        await interaction.followup.send(
            "\n".join(lines),
            ephemeral=True
        )

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

        # Zustand
        self.players_by_div = players_by_div       # {"1": [...], "2": [...], ...}
        self.division_value = start_div            # aktuell ausgewählte Division
        self.player_value = "Komplett"             # aktuell ausgewählter Spieler / Filter

        # Dropdowns hinzufügen
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

# Division-Normalisierung für Vergleich
def normalize_div(name):
    return name.lower().replace(" ", "").replace("-", "").replace(".", "")

# Modal für Termin-Eingabe
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

            s1 = self.spieler1.value.strip().lower()
            s2 = self.spieler2.value.strip().lower()

            if s1 not in TWITCH_MAP or s2 not in TWITCH_MAP:
                msg = "❌ Fehlerhafte Spielernamen:"
                if s1 not in TWITCH_MAP:
                    msg += f"\nSpieler 1: `{self.spieler1.value}` nicht erkannt"
                if s2 not in TWITCH_MAP:
                    msg += f"\nSpieler 2: `{self.spieler2.value}` nicht erkannt"
                await interaction.response.send_message(msg, ephemeral=True)
                return

            twitch1 = TWITCH_MAP[s1]
            twitch2 = TWITCH_MAP[s2]
            multistream_url = f"https://multistre.am/{twitch1}/{twitch2}/layout4"

            await interaction.guild.create_scheduled_event(
                name=f"{self.division.value} | {self.spieler1.value} vs. {self.spieler2.value} | {self.modus.value}",
                description=f"Match in der {self.division.value} zwischen {self.spieler1.value} und {self.spieler2.value}.",
                start_time=start_dt,
                end_time=end_dt,
                entity_type=discord.EntityType.external,
                location=multistream_url,
                privacy_level=discord.PrivacyLevel.guild_only
            )

            row = [
                self.division.value.strip(),
                datum_str,
                uhrzeit_str,
                self.spieler1.value.strip(),
                self.spieler2.value.strip(),
                self.modus.value.strip(),
                multistream_url
            ]
            SHEET.append_row(row)
            await interaction.response.send_message("✅ Match wurde eingetragen und Event erstellt!", ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(f"❌ Fehler beim Eintragen: {e}", ephemeral=True)

# --- /result Hilfsfunktionen & UI (überarbeitet) ---

def get_division_ws(div_number: str):
    """
    Holt das Worksheet für eine Division.
    Annahme: Tabs heißen '1.DIV', '2.DIV', ... '6.DIV'.
    """
    ws_name = f"{div_number}.DIV"
    return WB.worksheet(ws_name)

def load_open_games_for_result(div_number: str):
    """
    Liest offene Spiele aus {div}.DIV nach deiner echten Logik:
    - Spalte D (index 3): Heimspieler
    - Spalte E (index 4): Marker "vs" wenn offen
    - Spalte F (index 5): Auswärtsspieler

    Rückgabe: Liste Dicts:
    {
        "row_index": <int>,  # 1-basiert
        "heim": <str>,
        "auswaerts": <str>
    }
    """
    ws = get_division_ws(div_number)
    rows = ws.get_all_values()

    out = []
    for idx, row in enumerate(rows, start=1):
        if idx == 1:
            continue  # Header

        heim = _cell(row, 3)      # D
        marker = _cell(row, 4)    # E
        gast = _cell(row, 5)      # F

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
        spiele_dieses_heims = [g for g in alle_spiele if g["heim"] == heim]

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
    Hinweis für winner_input:
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

        self.winner_input = discord.ui.TextInput(
            label=f"Wer hat gewonnen? 1={heim}, 2={auswaerts}, X=Unentschieden",
            style=discord.TextStyle.short,
            required=True,
            max_length=1,
            placeholder="1 / 2 / X"
        )
        self.mode_input = discord.ui.TextInput(
            label="Welcher Modus wurde gespielt?",
            style=discord.TextStyle.short,
            required=True,
            placeholder="z. B. League, Cup, Bo3...",
            max_length=50
        )
        self.raceroom_input = discord.ui.TextInput(
            label="Bitte Raceroom-Link angeben",
            style=discord.TextStyle.short,
            required=True,
            placeholder="https://raceroom.xyz/..."
        )

        self.add_item(self.winner_input)
        self.add_item(self.mode_input)
        self.add_item(self.raceroom_input)

    async def on_submit(self, interaction: discord.Interaction):
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
            await interaction.response.send_message(
                content="❌ Ungültiger Gewinner-Wert. Bitte nur 1 / 2 / X.",
                ephemeral=True
            )
            return

        try:
            ws = get_division_ws(self.division)

            now = datetime.datetime.now(BERLIN_TZ)
            now_str = now.strftime("%d.%m.%Y %H:%M")

            # Schreiben in dieselbe Zeile der Divisionstabelle.
            # Spalten laut deiner Vorgabe:
            # B (2) = Timestamp
            # C (3) = Modus
            # E (5) = Ergebnis
            # G (7) = Raceroom
            # H (8) = Reporter
            ws.update_cell(self.row_index, 2, now_str)              # B
            ws.update_cell(self.row_index, 3, mode_val)             # C
            ws.update_cell(self.row_index, 5, ergebnis)             # E
            ws.update_cell(self.row_index, 7, raceroom_val)         # G
            ws.update_cell(self.row_index, 8, str(self.requester))  # H

            msg = (
                f"✅ Ergebnis gespeichert für Division {self.division}:\n"
                f"{self.heim} vs {self.auswaerts} => {ergebnis}\n"
                f"Modus: {mode_val}\n"
                f"Raceroom: {raceroom_val}"
            )
            await interaction.response.send_message(content=msg, ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(
                content=f"❌ Konnte nicht ins Sheet schreiben: {e}",
                ephemeral=True
            )

# ----------------------
# Slash Commands
# ----------------------

@tree.command(name="termin", description="Erstelle einen neuen Termin + Event + Sheet-Eintrag")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def termin(interaction: discord.Interaction):
    await interaction.response.send_modal(TerminModal())

@tree.command(name="today", description="Zeigt alle heutigen Matches")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def today(interaction: discord.Interaction):
    try:
        daten = SHEET.get_all_values()
        heute_str = datetime.datetime.now().strftime("%d.%m.%Y")
        matches = [row for row in daten[1:] if len(row) >= 7 and row[1].strip() == heute_str]

        if not matches:
            await interaction.response.send_message("📭 Heute sind keine Spiele geplant.", ephemeral=True)
            return

        matches.sort(key=lambda x: (x[2], x[0]))
        embed = discord.Embed(title=f"TFL-Matches am {heute_str}", color=0x00ffcc)
        for row in matches:
            embed.add_field(
                name=f"{row[0]} – {row[2]}",
                value=f"**{row[3]} vs {row[4]}**\nModus: {row[5]}\n[Multistream]({row[6]})",
                inline=False
            )
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message(f"❌ Fehler beim Abrufen: {e}", ephemeral=True)

async def zeige_geplante_spiele(interaction, filter_division=None):
    try:
        daten = SHEET.get_all_values()
        today_d = today_berlin_date()
        matches = []
        for row in daten[1:]:
            if len(row) < 7:
                continue
            datum, uhrzeit, division = row[1].strip(), row[2].strip(), row[0].strip()
            try:
                if parse_date(datum) < today_d:
                    continue
            except Exception:
                continue
            if filter_division and normalize_div(division) != normalize_div(filter_division):
                continue
            matches.append((datum, uhrzeit, division, row[3], row[4], row[5], row[6]))

        if not matches:
            await interaction.response.send_message("📭
