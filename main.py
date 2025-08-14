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
RESTREAM_CHANNEL_ID = int(os.getenv("RESTREAM_CHANNEL_ID"))
# Zielkanal für die tägliche 04:30-Showrestreams-Liste
SHOWRESTREAMS_CHANNEL_ID = int(os.getenv("SHOWRESTREAMS_CHANNEL_ID", "1277949546650931241"))
CREDS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

# Discord-Client
intents = discord.Intents.default()
client = commands.Bot(command_prefix="/", intents=intents)
tree = client.tree

# Hilfsfunktionen
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
    # Sende entweder direkt (kurz) oder deferred + followups (lang)
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
    # Sheet nutzt H: "ZSR", "SGD1", "SGD2" – für Anzeige wollen wir "ZSR", "SG1", "SG2"
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
SHEET = gspread.authorize(CREDS).open("Season #3 - Spielbetrieb").worksheet("League & Cup Schedule")

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

# Slash Commands

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
            embed.add_field(name=f"{row[0]} – {row[2]}", value=f"**{row[3]} vs {row[4]}**\nModus: {row[5]}\n[Multistream]({row[6]})", inline=False)
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
            embed.add_field(name=f"{m[2]} – {m[0]} {m[1]}", value=f"**{m[3]} vs {m[4]}**\nModus: {m[5]}\n[Multistream]({m[6]})", inline=False)
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message(f"❌ Fehler: {e}", ephemeral=True)

# Divisions-Befehle
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
            await interaction.response.send_message("📭 Keine zukünftigen Spiele ohne Restream-Ziel gefunden.", ephemeral=True)
            return

        matches.sort(key=lambda x: datetime.datetime.strptime(x[1] + " " + x[2], "%d.%m.%Y %H:%M"))
        lines = [f"{row[1]} {row[2]} | {row[0]} | {row[3]} vs. {row[4]} | {row[5]}" for row in matches]
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
    await interaction.response.send_message(f"✅ `{name}` wurde mit Twitch `{twitch}` hinzugefügt.", ephemeral=True)

# ---------- /showrestreams ----------

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
            await interaction.response.send_message("📭 Keine geplanten Restreams ab heute gefunden.", ephemeral=True)
            return

        rows.sort(key=lambda r: datetime.datetime.strptime(r[1].strip() + " " + r[2].strip(), "%d.%m.%Y %H:%M"))

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
            lines.append(f"{datum} {uhr} | {kanal} | {s1} vs. {s2} | {modus} | {com} | {co} | {track}")

        msg = "🎥 **Geplante Restreams ab heute:**\n" + "\n".join(lines)
        await send_long_message_interaction(interaction, msg, ephemeral=False)

    except Exception as e:
        await interaction.response.send_message(f"❌ Fehler bei /showrestreams: {e}", ephemeral=True)

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
                return len(row) >= 8 and parse_date(row[1].strip()) >= today_d and row[7].strip() == ""
            except Exception:
                return False

        matches = [row for row in daten[1:] if valid_row(row)]
        if not matches:
            return

        matches.sort(key=lambda x: datetime.datetime.strptime(x[1] + " " + x[2], "%d.%m.%Y %H:%M"))
        lines = [f"{row[1]} {row[2]} | {row[0]} | {row[3]} vs. {row[4]} | {row[5]}" for row in matches]

        channel = client.get_channel(RESTREAM_CHANNEL_ID)
        if channel:
            msg = "📋 **Geplante Matches ab heute (ohne Restream-Ziel):**\n" + "\n".join(lines)
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

        rows.sort(key=lambda r: datetime.datetime.strptime(r[1].strip() + " " + r[2].strip(), "%d.%m.%Y %H:%M"))

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
            lines.append(f"{datum} {uhr} | {kanal} | {s1} vs. {s2} | {modus} | {com} | {co} | {track}")

        channel = client.get_channel(SHOWRESTREAMS_CHANNEL_ID)
        if channel:
            msg = "🎥 **Geplante Restreams ab heute:**\n" + "\n".join(lines)
            await send_long_message_channel(channel, msg)

    except Exception as e:
        print(f"❌ Fehler bei täglicher Restreams-Ausgabe (04:30): {e}")

# ---------- Restream-Workflow mit optionalen Feldern ----------

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
        # Sofort deferren, damit der Token nicht abläuft
        await interaction.response.defer(ephemeral=True)

        code = self.restream_input.value.strip().upper()
        allowed = {"ZSR", "SG1", "SG2"}
        if code not in allowed:
            await interaction.followup.send("❌ Ungültiger Code. Erlaubt: ZSR, SG1, SG2", ephemeral=True)
            return

        title_prefix = {"ZSR": "RESTREAM ZSR |", "SG1": "RESTREAM SGD1 |", "SG2": "RESTREAM SGD2 |"}[code]
        location_url = {
            "ZSR": "https://www.twitch.tv/zeldaspeedrunsde",
            "SG1": "https://www.twitch.tv/speedgamingdeutsch",
            "SG2": "https://www.twitch.tv/speedgamingdeutsch2",
        }[code]

        # Optionale Felder (können leer sein)
        com_val = (self.com_input.value or "").strip()
        co_val = (self.co_input.value or "").strip()
        track_val = (self.track_input.value or "").strip()

        # Eventtitel wie bei Termin-Erstellung zusammensetzen
        original_title = f"{self.selected_row[0]} | {self.selected_row[3]} vs. {self.selected_row[4]} | {self.selected_row[5]}"
        new_title = f"{title_prefix} {original_title}"

        # Event sicher fetchen (nicht nur Cache)
        try:
            events = await interaction.guild.fetch_scheduled_events()
        except Exception as e:
            await interaction.followup.send(f"❌ Konnte Events nicht abrufen: {e}", ephemeral=True)
            return

        # Exakt nach Titel suchen
        event = discord.utils.get(events, name=original_title)

        # Fallback: nach Startzeit & Spielern suchen (±90min)
        if not event:
            try:
                dt = datetime.datetime.strptime(self.selected_row[1].strip() + " " + self.selected_row[2].strip(), "%d.%m.%Y %H:%M")
                start_target = BERLIN_TZ.localize(dt)

                def plausible(ev: discord.ScheduledEvent) -> bool:
                    try:
                        ev_start = ev.start_time.astimezone(BERLIN_TZ)
                        within = abs((ev_start - start_target).total_seconds()) <= 90 * 60
                        s1 = self.selected_row[3].strip()
                        s2 = self.selected_row[4].strip()
                        names_ok = (s1.lower() in ev.name.lower()) and (s2.lower() in ev.name.lower())
                        return within and names_ok
                    except Exception:
                        return False

                candidates = [ev for ev in events if plausible(ev)]
                if candidates:
                    event = min(
                        candidates,
                        key=lambda ev: abs((ev.start_time.astimezone(BERLIN_TZ) - start_target).total_seconds())
                    )
            except Exception:
                pass

        if not event:
            await interaction.followup.send("❌ Kein passendes Event gefunden.", ephemeral=True)
            return

        try:
            # Event editieren
            await event.edit(name=new_title, location=location_url)

            # Update Spalten H (Restream-Ziel), I (Com), J (Co), K (Track)
            daten = SHEET.get_all_values()
            sheet_value = {"ZSR": "ZSR", "SG1": "SGD1", "SG2": "SGD2"}[code]
            for idx, row in enumerate(daten):
                if (len(row) >= 6 and
                    row[0].strip() == self.selected_row[0] and
                    row[1].strip() == self.selected_row[1] and
                    row[2].strip() == self.selected_row[2] and
                    row[3].strip() == self.selected_row[3] and
                    row[4].strip() == self.selected_row[4] and
                    row[5].strip() == self.selected_row[5]):
                    # H=8, I=9, J=10, K=11
                    SHEET.update_cell(idx + 1, 8, sheet_value)
                    SHEET.update_cell(idx + 1, 9, com_val)
                    SHEET.update_cell(idx + 1, 10, co_val)
                    SHEET.update_cell(idx + 1, 11, track_val)
                    break

            extra = []
            if com_val: extra.append(f"Com: `{com_val}`")
            if co_val: extra.append(f"Co: `{co_val}`")
            if track_val: extra.append(f"Track: `{track_val}`")
            suffix = (", " + ", ".join(extra)) if extra else ""
            await interaction.followup.send(f"✅ Event & Sheet aktualisiert: `{sheet_value}` gesetzt{suffix}.", ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ Fehler beim Aktualisieren: {e}", ephemeral=True)

@tree.command(name="restreams", description="Setzt Restream-Ziel + optional Com/Co/Track für ein Spiel")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def restreams(interaction: discord.Interaction):
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
            await interaction.response.send_message("📭 Keine zukünftigen Spiele ohne Restream-Ziel gefunden.", ephemeral=True)
            return

        # Baue Auswahlmenü
        class SpielAuswahl(discord.ui.View):
            def __init__(self, spiele):
                super().__init__(timeout=60)
                options = [
                    discord.SelectOption(
                        label=f"{r[1]} {r[2]} | {r[0]} | {r[3]} vs {r[4]}",
                        value=str(i)
                    ) for i, r in enumerate(spiele[:25])
                ]
                self.add_item(self.SpielSelect(options, spiele))

            class SpielSelect(discord.ui.Select):
                def __init__(self, options, spiele):
                    super().__init__(placeholder="Wähle ein Spiel", min_values=1, max_values=1, options=options)
                    self.spiele = spiele

                async def callback(self, interaction2: discord.Interaction):
                    auswahl = int(self.values[0])
                    selected = self.spiele[auswahl]
                    await interaction2.response.send_modal(RestreamModal(selected))

        await interaction.response.send_message("🎮 Bitte wähle ein Spiel zur Bearbeitung:", view=SpielAuswahl(matches), ephemeral=True)

    except Exception as e:
        await interaction.response.send_message(f"❌ Fehler bei /restreams: {e}", ephemeral=True)

@tree.command(name="help", description="Zeigt eine Übersicht aller verfügbaren Befehle")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📖 TFL Bot Hilfe",
        description="Alle verfügbaren Befehle mit kurzer Erklärung:",
        color=0x00ffcc
    )

    embed.add_field(name="/termin", value="➤ Neues Match eintragen, Event erstellen und ins Sheet schreiben", inline=False)
    embed.add_field(name="/today", value="➤ Zeigt alle heutigen Spiele (Embed mit Link & Modus)", inline=False)
    embed.add_field(name="/div1 – /div5", value="➤ Zeigt alle geplanten Spiele einer bestimmten Division", inline=False)
    embed.add_field(name="/cup", value="➤ Zeigt alle geplanten Cup-Spiele", inline=False)
    embed.add_field(name="/alle", value="➤ Zeigt alle geplanten Spiele ab heute (alle Divisionen & Cup)", inline=False)
    embed.add_field(name="/viewall", value="➤ Zeigt alle Spiele **ohne gesetztes Restream-Ziel** im Listenformat", inline=False)
    embed.add_field(name="/restreams", value="➤ Wähle ein Spiel, setze Restream-Ziel (ZSR, SG1, SG2) + optional Com/Co/Track. Aktualisiert Event & Sheet.", inline=False)
    embed.add_field(name="/showrestreams", value="➤ Zeigt alle geplanten Restreams ab heute (Kanal, Com, Co, Track).", inline=False)
    embed.add_field(name="/add", value="➤ Fügt zur Laufzeit einen neuen Spieler zur TWITCH_MAP hinzu (nicht persistent)", inline=False)
    embed.add_field(name="🔁 Auto-Posts", value="➤ 04:00: restreambare Spiele • 04:30: geplante Restreams", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

@client.event
async def on_ready():
    print(f"✅ Eingeloggt als {client.user} (ID: {client.user.id})")
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    if not sende_restream_liste.is_running():
        sende_restream_liste.start()
    if not sende_showrestreams_liste.is_running():
        sende_showrestreams_liste.start()
    print("✅ Slash-Befehle synchronisiert & tägliche Tasks aktiv")

client.run(TOKEN)
