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
# EVENT_CHANNEL_ID ist aktuell ungenutzt – ggf. später verwenden oder entfernen
EVENT_CHANNEL_ID = int(os.getenv("DISCORD_EVENT_CHANNEL_ID")) if os.getenv("DISCORD_EVENT_CHANNEL_ID") else 0
RESTREAM_CHANNEL_ID = int(os.getenv("RESTREAM_CHANNEL_ID"))  # Kanal für 04:00-Post (ohne Restream-Ziel)
SHOWRESTREAMS_CHANNEL_ID = int(os.getenv("SHOWRESTREAMS_CHANNEL_ID", "1277949546650931241"))  # Kanal für 04:30-Post
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

# Gesamte Arbeitsmappe öffnen (wir brauchen zusätzlich die DIV-Tabs)
WB = GC.open("Season #3 - Spielbetrieb")

# Bestehend: das Schedule-Blatt weiter benutzen wie gehabt
SHEET = WB.worksheet("League & Cup Schedule")

def _cell(row, idx0):
    return (row[idx0].strip() if 0 <= idx0 < len(row) else "")

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

async def _rp_show(interaction: discord.Interaction, division_value: str, player_filter: str):
    """
    Baut die Ausgabe und schickt sie ephemer.

    player_filter == "" oder "Komplett" => alle offenen Spiele der Division
    sonst nur Spiele, an denen der Spieler beteiligt ist.
    """

    try:
        # zuerst Interaction sichern, damit der Button-Callback nicht abläuft
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
        # Fallback bei Fehlern
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
            # Division merken
            self.parent_view.division_value = self.values[0]

            # Neue View mit aktualisierter Spielerliste erstellen
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
        # finale Ausgabe erzeugen
        await _rp_show(
            interaction,
            self.division_value,
            self.player_value
        )

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
        # Sofort deferren, damit kein Unknown Interaction entsteht
        await interaction.response.defer(ephemeral=True)

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

        # Events vom Server holen (nicht nur Cache)
        try:
            events = await interaction.guild.fetch_scheduled_events()
        except Exception as e:
            await interaction.followup.send(
                f"❌ Konnte Events nicht abrufen: {e}",
                ephemeral=True
            )
            return

        # Exakt nach Titel suchen
        event = discord.utils.get(events, name=original_title)

        # Fallback: anhand Startzeit (±90 Min) + Spielernamen
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

            # Sheet updaten: H (Restream), I (Com), J (Co), K (Track)
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
                    # H=8, I=9, J=10, K=11
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
        name="/div1 – /div5",
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
        # Sofort defer, weil sync() bei Rate Limit dauern kann
        await interaction.response.defer(ephemeral=True, thinking=True)

        synced = await tree.sync(guild=discord.Object(id=GUILD_ID))
        names = ", ".join(sorted(c.name for c in synced))

        await interaction.followup.send(
            f"✅ Synced {len(synced)} Commands: {names}",
            ephemeral=True
        )

    except Exception as e:
        # Falls sync knallt, versuch trotzdem per followup zu antworten
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
        # GANZ WICHTIG: sofort deferren, noch bevor wir Sheets anfassen
        await interaction.response.defer(ephemeral=True, thinking=True)

        # Spielernamen je Division holen (Google Sheets, kann langsam sein)
        players_by_div = get_players_by_divisions()

        # View erzeugen mit Default Division "1"
        view = RestprogrammView(players_by_div=players_by_div, start_div="1")

        # Followup senden (erste sichtbare Nachricht für den User)
        await interaction.followup.send(
            "📋 Restprogramm – Division wählen, optional Spieler auswählen, dann 'Anzeigen' drücken.",
            view=view,
            ephemeral=True
        )

    except Exception as e:
        # Falls irgendwas crasht: versuch über followup zu antworten
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
