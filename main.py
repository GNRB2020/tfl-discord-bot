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

# ---------------------------
# RESTPROGRAMM / UTILS
# ---------------------------

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
    {
      "1": ["Komplett", "SpielerA", ...],
      ...
    }
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
    """
    ws_name = f"{div}.DIV"
    ws = WB.worksheet(ws_name)
    rows = ws.get_all_values()
    out = []
    q = player_query.strip().lower()

    D, E, F = 3, 4, 5   # 0-basierte Indizes für Spalten D/E/F

    for r_idx in range(1, len(rows)):  # ab Zeile 2
        row = rows[r_idx]
        p1 = _cell(row, D)
        marker = _cell(row, E).lower()
        p2 = _cell(row, F)

        if (p1 or p2) and marker == "vs":
            if not q or (q in p1.lower() or q in p2.lower()):
                out.append((r_idx + 1, "L", p1, p2))

    return out

async def _rp_show(interaction: discord.Interaction, division_value: str, player_filter: str):
    """
    Baut die Ausgabe und schickt sie ephemer.
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

# ---------------------------
# /termin Modal
# ---------------------------

def normalize_div(name):
    return name.lower().replace(" ", "").replace("-", "").replace(".", "")

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

# ---------------------------
# /result Workflow
# ---------------------------

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
        the_games = games
        self.games = the_games
        self.requester = requester

        options = []
        for idx, g in enumerate(the_games):
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
        # direkt deferren um 3s-Timeout zu vermeiden
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

            # Schreiben:
            # B (2): Timestamp
            # C (3): Modus
            # E (5): Ergebnis
            # G (7): Raceroom
            # H (8): Reporter
            ws.update_cell(self.row_index, 2, now_str)             # B
            ws.update_cell(self.row_index, 3, mode_val)            # C
            ws.update_cell(self.row_index, 5, ergebnis)            # E
            ws.update_cell(self.row_index, 7, raceroom_val)        # G
            ws.update_cell(self.row_index, 8, str(self.requester)) # H

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

# ---------------------------
# /playerexit Workflow
# ---------------------------

def list_div_players(div_number: str):
    """
    Liefert alle Spielernamen aus Spalte L des jeweiligen {div}.DIV Tabs.
    (das ist dieselbe Quelle wie get_players_for_div)
    """
    try:
        return get_players_for_div(div_number)
    except Exception:
        return []

def playerexit_apply(div_number: str, quitting_player: str, reporter: str):
    """
    Hard-Drop eines Spielers:
    - ALLE seine Spiele in der Division werden als Forfeit gegen ihn gewertet,
      auch bereits eingetragene Ergebnisse.
    - Links (Spalte D) => Ergebnis 0:2
    - Rechts (Spalte F) => Ergebnis 2:0
    Es wird überschrieben:
      B (2): Timestamp jetzt
      C (3): "FF"
      E (5): Ergebnis (0:2 / 2:0)
      G (7): "FF"
      H (8): Reporter
    Zusätzlich wird der Name des Spielers in D/F durchgestrichen.
    """
    ws = WB.worksheet(f"{div_number}.DIV")
    rows = ws.get_all_values()

    now = datetime.datetime.now(BERLIN_TZ)
    now_str = now.strftime("%d.%m.%Y %H:%M")

    strike_cells = []

    # durch alle Datenzeilen laufen (ab Zeile 2)
    for idx, row in enumerate(rows[1:], start=2):
        left_player  = _cell(row, 3)  # D
        right_player = _cell(row, 5)  # F

        lp_match = (left_player.lower() == quitting_player.lower()) if left_player else False
        rp_match = (right_player.lower() == quitting_player.lower()) if right_player else False

        if not (lp_match or rp_match):
            continue

        # Ergebnis festlegen
        if lp_match:
            result_val = "0:2"   # quitter links verliert
            strike_cells.append(f"D{idx}")
        else:
            result_val = "2:0"   # quitter rechts verliert
            strike_cells.append(f"F{idx}")

        # Sheet überschreiben
        ws.update_cell(idx, 2, now_str)     # B Timestamp
        ws.update_cell(idx, 3, "FF")        # C Modus "FF"
        ws.update_cell(idx, 5, result_val)  # E Ergebnis
        ws.update_cell(idx, 7, "FF")        # G Raceroom/FF
        ws.update_cell(idx, 8, reporter)    # H Reporter

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

        # wir defer'n sofort, weil jetzt viel Sheet-Kram kommt
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

# ---------------------------
# /spielplan Workflow (ADMIN ONLY)
# ---------------------------

def _get_div_ws(div_number: str):
    """
    Holt das Worksheet-Objekt für z.B. "1" -> "1.DIV".
    """
    ws_name = f"{div_number}.DIV"
    return WB.worksheet(ws_name)

def spielplan_read_players(div_number: str):
    """
    Liest die Spielernamen aus Spalte L (12) ab Zeile 2 des Tabs {div}.DIV.
    Entfernt Leerzeilen und Duplikate. Reihenfolge bleibt wie im Sheet.
    """
    ws = _get_div_ws(div_number)
    values = ws.col_values(12)  # Spalte L
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
    Round-Robin (Circle Method).
    Gibt eine Liste von Spieltagen zurück.
    Jeder Spieltag ist Liste von (home, away).
    Jede Person taucht pro Spieltag nur einmal auf.
    """
    work = list(players)
    if len(work) % 2 == 1:
        work.append("BYE")  # BYE = spielfrei, wird nicht eingetragen

    n = len(work)
    half = n // 2
    rotation = work[:]  # wir rotieren alle außer das erste Element

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
            day_pairs.append((p1, p2))  # p1 Heim, p2 Gast

        rounds.append(day_pairs)

        # Rotation (klassische Circle-Methode):
        fixed = rotation[0]
        tail = rotation[1:]
        tail = [tail[-1]] + tail[:-1]
        rotation = [fixed] + tail

    return rounds

def spielplan_build_matches(players: list[str]) -> list[list[tuple[str, str]]]:
    """
    Liefert Spieltage mit Hin- und Rückrunde.
    Rückrunde = Heim/Auswärts getauscht.
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
    Nimmt die erste Zeile ab 2, wo D leer ist.
    Wenn nix leer ist, hängt unten dran.
    """
    col_d = ws.col_values(4)  # Spalte D
    for idx_1based, val in enumerate(col_d, start=1):
        if idx_1based == 1:
            continue  # Header überspringen
        if val.strip() == "":
            return idx_1based
    # col_values() endet an der letzten nicht-leeren Stelle.
    # -> nächste freie Zeile ist len(col_d)+1
    return len(col_d) + 1

def spielplan_get_last_number(ws):
    """
    Alte Logik (wird nicht mehr verwendet für Nummerierung).
    Ich lasse sie drin, falls du sie woanders brauchst.
    """
    col_a = ws.col_values(1)  # Spalte A
    last_num = 0
    for v in col_a[1:]:
        v2 = v.strip()
        if v2.isdigit():
            num = int(v2)
            if num > last_num:
                last_num = num
    return last_num

def spielplan_write(ws, rounds: list[list[tuple[str, str]]]):
    """
    Schreibt ALLE Spieltage (Hin+Rück) direkt untereinander.
    KEINE Leerzeilen zwischen Spieltagen.
    Spalte A wird pro Block neu ab 1 gezählt.

    Spalten:
      A = Laufende Nummer (1,2,3,... innerhalb dieses Blocks)
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
            row_data[0] = str(laufende_nummer)  # Nummer
            row_data[3] = home                  # Heim in D
            row_data[4] = "vs"                  # "vs" in E
            row_data[5] = away                  # Gast in F
            rows_to_write.append(row_data)
            laufende_nummer += 1

    if not rows_to_write:
        return 0

    end_row = start_row + len(rows_to_write) - 1
    cell_range = f"A{start_row}:I{end_row}"
    ws.update(cell_range, rows_to_write)
    return len(rows_to_write)

@tree.command(
    name="spielplan",
    description="(Admin) Erstellt Hin-/Rückrunde (jeder gg. jeden, Spieltage) und schreibt alles ins Sheet"
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

    is_admin = any(r.name == "Admin" for r in member.roles)
    if not is_admin:
        await interaction.response.send_message(
            "⛔ Du hast keine Berechtigung diesen Befehl zu nutzen.",
            ephemeral=True
        )
        return

    try:
        # Spieler holen aus Spalte L
        players = spielplan_read_players(division.value)
        if len(players) < 2:
            await interaction.response.send_message(
                f"❌ Zu wenig Spieler in Division {division.value} gefunden (Spalte L leer oder nur eine Person).",
                ephemeral=True
            )
            return

        # Spieltage (Hin+Rück)
        rounds = spielplan_build_matches(players)

        # Schreiben
        ws = _get_div_ws(division.value)
        written = spielplan_write(ws, rounds)

        # Preview für den ersten Spieltag
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

async def zeige_geplante_spiele(interaction: discord.Interaction, filter_division=None):
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
            await interaction.response.send_message("📭 Keine Spiele gefunden.", ephemeral=True)
            return

        matches.sort(key=lambda x: datetime.datetime.strptime(x[0] + " " + x[1], "%d.%m.%Y %H:%M"))
        embed = discord.Embed(title=f"{filter_division or 'Alle'} – Geplante Matches", color=0x00ffcc)
        for m in matches:
            embed.add_field(
                name=f"{m[2]} – {m[0]} {m[1]}",
                value=f"**{m[3]} vs {m[4]}**\nModus: {m[5]}\n[Multistream]({m[6]})",
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

DIV_CHOICES = [
    app_commands.Choice(name="Division 1", value="1"),
    app_commands.Choice(name="Division 2", value="2"),
    app_commands.Choice(name="Division 3", value="3"),
    app_commands.Choice(name="Division 4", value="4"),
    app_commands.Choice(name="Division 5", value="5"),
]

@tree.command(name="viewall", description="Zeigt alle kommenden Matches im Listenformat")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def viewall(interaction: discord.Interaction):
    try:
        daten = SHEET.get_all_values()
        today_d = today_berlin_date()

        def valid_row(row):
            try:
                return len(row) >= 8 and parse_date(row[1].strip()) >= today_d and row[7].strip() == ""
            except Exception:
                return False

        matches = [row for row in daten[1:] if valid_row(row)]

        if not matches:
            await interaction.response.send_message(
                "📭 Keine zukünftigen Spiele ohne Restream-Ziel gefunden.",
                ephemeral=True
            )
            return

        matches.sort(key=lambda x: datetime.datetime.strptime(x[1] + " " + x[2], "%d.%m.%Y %H:%M"))
        lines = [
            f"{row[1]} {row[2]} | {row[0]} | {row[3]} vs. {row[4]} | {row[5]}"
            for row in matches
        ]
        msg = "📋 **Geplante Matches ab heute (ohne Restream-Ziel):**\n" + "\n".join(lines)
        await send_long_message_interaction(interaction, msg, ephemeral=False)

    except Exception as e:
        await interaction.response.send_message(f"❌ Fehler bei /viewall: {e}", ephemeral=True)

@tree.command(name="add", description="Fügt einen neuen Spieler zur Liste hinzu")
@app_commands.describe(name="Name", twitch="Twitch-Username")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def add(interaction: discord.Interaction, name: str, twitch: str):
    name = name.strip().lower()
    twitch = twitch.strip()
    TWITCH_MAP[name] = twitch
    await interaction.response.send_message(
        f"✅ `{name}` wurde mit Twitch `{twitch}` hinzugefügt.",
        ephemeral=True
    )

@tree.command(name="showrestreams", description="Zeigt alle geplanten Restreams ab heute (mit Com/Co/Track)")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def showrestreams(interaction: discord.Interaction):
    try:
        daten = SHEET.get_all_values()
        today_d = today_berlin_date()

        def valid_row(row):
            try:
                has_date = len(row) >= 2 and parse_date(row[1].strip()) >= today_d
                has_restream = len(row) >= 8 and row[7].strip() != ""
                return has_date and has_restream
            except Exception:
                return False

        rows = [row for row in daten[1:] if valid_row(row)]
        if not rows:
            await interaction.response.send_message(
                "📭 Keine geplanten Restreams ab heute gefunden.",
                ephemeral=True
            )
            return

        rows.sort(
            key=lambda r: datetime.datetime.strptime(
                r[1].strip() + " " + r[2].strip(),
                "%d.%m.%Y %H:%M"
            )
        )

        lines = []
        for r in rows:
            datum = r[1].strip()
            uhr = r[2].strip()
            kanal = map_sheet_channel_to_label(r[7].strip() if len(r) >= 8 else "")
            s1 = r[3].strip() if len(r) >= 4 else ""
            s2 = r[4].strip() if len(r) >= 5 else ""
            modus = r[5].strip() if len(r) >= 6 else ""
            com = r[8].strip() if len(r) >= 9 else ""
            co = r[9].strip() if len(r) >= 10 else ""
            track = r[10].strip() if len(r) >= 11 else ""
            lines.append(
                f"{datum} {uhr} | {kanal} | {s1} vs. {s2} | {modus} | "
                f"Com: {com or '—'} | Co: {co or '—'} | Track: {track or '—'}"
            )

        msg = "🎥 **Geplante Restreams ab heute:**\n" + "\n".join(lines)
        await send_long_message_interaction(interaction, msg, ephemeral=False)

    except Exception as e:
        await interaction.response.send_message(f"❌ Fehler bei /showrestreams: {e}", ephemeral=True)

# ---------- Restream-Workflow (/pick + Modal) ----------

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
        self.selected_row = selected_row  # [division, date, time, spieler1, spieler2, modus]

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

        com_val = (self.com_input.value or "").strip()
        co_val = (self.co_input.value or "").strip()
        track_val = (self.track_input.value or "").strip()

        original_title = (
            f"{self.selected_row[0]} | "
            f"{self.selected_row[3]} vs. {self.selected_row[4]} | "
            f"{self.selected_row[5]}"
        )
        new_title = f"{title_prefix} {original_title}"

        # Events holen
        try:
            events = await interaction.guild.fetch_scheduled_events()
        except Exception as e:
            await interaction.followup.send(
                f"❌ Konnte Events nicht abrufen: {e}",
                ephemeral=True
            )
            return

        event = discord.utils.get(events, name=original_title)

        if not event:
            try:
                dt = datetime.datetime.strptime(
                    self.selected_row[1].strip() + " " + self.selected_row[2].strip(),
                    "%d.%m.%Y %H:%M"
                )
                start_target = BERLIN_TZ.localize(dt)

                def plausible(ev: discord.ScheduledEvent) -> bool:
                    try:
                        ev_start = ev.start_time.astimezone(BERLIN_TZ)
                        within = abs(
                            (ev_start - start_target).total_seconds()
                        ) <= 90 * 60
                        s1 = self.selected_row[3].strip().lower()
                        s2 = self.selected_row[4].strip().lower()
                        name_l = ev.name.lower()
                        names_ok = (s1 in name_l) and (s2 in name_l)
                        return within and names_ok
                    except Exception:
                        return False

                candidates = [ev for ev in events if plausible(ev)]
                if candidates:
                    event = min(
                        candidates,
                        key=lambda ev: abs(
                            (
                                ev.start_time.astimezone(BERLIN_TZ)
                                - start_target
                            ).total_seconds()
                        )
                    )
            except Exception:
                pass

        if not event:
            await interaction.followup.send(
                "❌ Kein passendes Event gefunden.",
                ephemeral=True
            )
            return

        try:
            # Event updaten
            await event.edit(name=new_title, location=location_url)

            # Sheet updaten
            daten = SHEET.get_all_values()
            sheet_value = {"ZSR": "ZSR", "SG1": "SGD1", "SG2": "SGD2"}[code]
            for idx, row in enumerate(daten):
                if (
                    len(row) >= 6 and
                    row[0].strip() == self.selected_row[0] and
                    row[1].strip() == self.selected_row[1] and
                    row[2].strip() == self.selected_row[2] and
                    row[3].strip() == self.selected_row[3] and
                    row[4].strip() == self.selected_row[4] and
                    row[5].strip() == self.selected_row[5]
                ):
                    # H (8), I (9), J (10), K (11)
                    SHEET.update_cell(idx + 1, 8, sheet_value)
                    SHEET.update_cell(idx + 1, 9, com_val)
                    SHEET.update_cell(idx + 1, 10, co_val)
                    SHEET.update_cell(idx + 1, 11, track_val)
                    break

            extra = []
            if com_val:
                extra.append(f"Com: `{com_val}`")
            if co_val:
                extra.append(f"Co: `{co_val}`")
            if track_val:
                extra.append(f"Track: `{track_val}`")
            suffix = (", " + ", ".join(extra)) if extra else ""

            await interaction.followup.send(
                f"✅ Event & Sheet aktualisiert: `{sheet_value}` gesetzt{suffix}.",
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
        daten = SHEET.get_all_values()
        today_d = today_berlin_date()

        def valid_row(row):
            try:
                return (
                    len(row) >= 8 and
                    parse_date(row[1].strip()) >= today_d and
                    row[7].strip() == ""
                )
            except Exception:
                return False

        matches = [row for row in daten[1:] if valid_row(row)]

        if not matches:
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
                        label=f"{r[1]} {r[2]} | {r[0]} | {r[3]} vs {r[4]}",
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
            view=SpielAuswahl(matches),
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

    has_role = any(r.name == "Try Force League" for r in member.roles)
    if not has_role:
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

    is_admin = any(r.name == "Admin" for r in member.roles)
    if not is_admin:
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
        value="➤ Admin: Baut Hin- & Rückrunde (Round Robin, Spieltage). Schreibt alles untereinander ins DIV-Sheet. Spalte A startet bei 1.",
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

@tree.command(name="sync", description="(Admin) Slash-Commands für diese Guild synchronisieren")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def sync_cmd(interaction: discord.Interaction):
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

# ---------- Auto-Posts ----------

@client.event
async def on_ready():
    print(f"✅ Eingeloggt als {client.user} (ID: {client.user.id})")
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    if not sende_restream_liste.is_running():
        sende_restream_liste.start()
    if not sende_showrestreams_liste.is_running():
        sende_showrestreams_liste.start()
    print("✅ Slash-Befehle synchronisiert & tägliche Tasks aktiv")

# 04:00 – restreambare Spiele (H leer)
@tasks.loop(minutes=1)
async def sende_restream_liste():
    try:
        now = datetime.datetime.now(BERLIN_TZ)
        if now.hour != 4 or now.minute != 0:
            return

        daten = SHEET.get_all_values()
        today_d = now.date()

        def valid_row(row):
            try:
                return (
                    len(row) >= 8 and
                    parse_date(row[1].strip()) >= today_d and
                    row[7].strip() == ""
                )
            except Exception:
                return False

        matches = [row for row in daten[1:] if valid_row(row)]
        if not matches:
            return

        matches.sort(
            key=lambda x: datetime.datetime.strptime(
                x[1] + " " + x[2],
                "%d.%m.%Y %H:%M"
            )
        )
        lines = [
            f"{row[1]} {row[2]} | {row[0]} | {row[3]} vs. {row[4]} | {row[5]}"
            for row in matches
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

# 04:30 – geplante Restreams (H befüllt)
@tasks.loop(minutes=1)
async def sende_showrestreams_liste():
    try:
        now = datetime.datetime.now(BERLIN_TZ)
        if now.hour != 4 or now.minute != 30:
            return

        daten = SHEET.get_all_values()
        today_d = now.date()

        def valid_row(row):
            try:
                has_date = len(row) >= 2 and parse_date(row[1].strip()) >= today_d
                has_restream = len(row) >= 8 and row[7].strip() != ""
                return has_date and has_restream
            except Exception:
                return False

        rows = [row for row in daten[1:] if valid_row(row)]
        if not rows:
            return

        rows.sort(
            key=lambda r: datetime.datetime.strptime(
                r[1].strip() + " " + r[2].strip(),
                "%d.%m.%Y %H:%M"
            )
        )

        lines = []
        for r in rows:
            datum = r[1].strip()
            uhr = r[2].strip()
            kanal = map_sheet_channel_to_label(r[7].strip() if len(r) >= 8 else "")
            s1 = r[3].strip() if len(r) >= 4 else ""
            s2 = r[4].strip() if len(r) >= 5 else ""
            modus = r[5].strip() if len(r) >= 6 else ""
            com = r[8].strip() if len(r) >= 9 else ""
            co = r[9].strip() if len(r) >= 10 else ""
            track = r[10].strip() if len(r) >= 11 else ""
            lines.append(
                f"{datum} {uhr} | {kanal} | {s1} vs. {s2} | {modus} | "
                f"Com: {com or '—'} | Co: {co or '—'} | Track: {track or '—'}"
            )

        channel = client.get_channel(SHOWRESTREAMS_CHANNEL_ID)
        if channel:
            msg = "🎥 **Geplante Restreams ab heute:**\n" + "\n".join(lines)
            await send_long_message_channel(channel, msg)

    except Exception as e:
        print(f"❌ Fehler bei täglicher Restreams-Ausgabe (04:30): {e}")

client.run(TOKEN)
