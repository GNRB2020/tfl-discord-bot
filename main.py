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
EVENT_CHANNEL_ID = int(os.getenv("DISCORD_EVENT_CHANNEL_ID"))
RESTREAM_CHANNEL_ID = int(os.getenv("RESTREAM_CHANNEL_ID"))
CREDS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

# Discord-Client
intents = discord.Intents.default()
client = commands.Bot(command_prefix="/", intents=intents)
tree = client.tree

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
    division = discord.ui.TextInput(label="Division", placeholder="z. B. 2. Division", required=True)
    datetime_str = discord.ui.TextInput(label="Datum & Uhrzeit", placeholder="DD.MM.YYYY HH:MM", required=True)
    spieler1 = discord.ui.TextInput(label="Spieler 1", placeholder="Name wie in Liste", required=True)
    spieler2 = discord.ui.TextInput(label="Spieler 2", placeholder="Name wie in Liste", required=True)
    modus = discord.ui.TextInput(label="Modus", placeholder="z. B. Casual Boots", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            parts = self.datetime_str.value.strip().split()
            if len(parts) < 2:
                await interaction.response.send_message("❌ Formatfehler: Nutze `DD.MM.YYYY HH:MM`.", ephemeral=True)
                return

            datum_str, uhrzeit_str = parts[0], parts[1]
            local = pytz.timezone("Europe/Berlin")
            start_dt = local.localize(datetime.datetime.strptime(f"{datum_str} {uhrzeit_str}", "%d.%m.%Y %H:%M"))
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
        heute = datetime.datetime.now().strftime("%d.%m.%Y")
        matches = [row for row in daten[1:] if len(row) >= 7 and row[1].strip() == heute]

        if not matches:
            await interaction.response.send_message("📭 Heute sind keine Spiele geplant.", ephemeral=True)
            return

        matches.sort(key=lambda x: (x[2], x[0]))
        embed = discord.Embed(title=f"TFL-Matches am {heute}", color=0x00ffcc)
        for row in matches:
            embed.add_field(name=f"{row[0]} – {row[2]}", value=f"**{row[3]} vs {row[4]}**\nModus: {row[5]}\n[Multistream]({row[6]})", inline=False)
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message(f"❌ Fehler beim Abrufen: {e}", ephemeral=True)

async def zeige_geplante_spiele(interaction, filter_division=None):
    try:
        daten = SHEET.get_all_values()
        heute = datetime.datetime.now().strftime("%d.%m.%Y")
        matches = []
        for row in daten[1:]:
            if len(row) < 7:
                continue
            datum, uhrzeit, division = row[1].strip(), row[2].strip(), row[0].strip()
            try:
                if datetime.datetime.strptime(datum, "%d.%m.%Y") < datetime.datetime.strptime(heute, "%d.%m.%Y"):
                    continue
            except:
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
        heute = datetime.datetime.now(pytz.timezone("Europe/Berlin")).strftime("%d.%m.%Y")
        matches = [row for row in daten[1:] if len(row) >= 7 and row[1].strip() >= heute]

        if not matches:
            await interaction.response.send_message("📭 Keine zukünftigen Spiele gefunden.", ephemeral=True)
            return

        matches.sort(key=lambda x: datetime.datetime.strptime(x[1] + " " + x[2], "%d.%m.%Y %H:%M"))
        lines = [f"{row[1]} {row[2]} | {row[0]} | {row[3]} vs. {row[4]} | {row[5]}" for row in matches]
        await interaction.response.send_message("📋 **Geplante Matches ab heute:**\n" + "\n".join(lines), ephemeral=False)
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

@client.event
async def on_ready():
    print(f"✅ Eingeloggt als {client.user} (ID: {client.user.id})")
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    sende_restream_liste.start()
    print("✅ Slash-Befehle synchronisiert & täglicher Task aktiv")

@tasks.loop(minutes=1)
async def sende_restream_liste():
    try:
        now = datetime.datetime.now(pytz.timezone("Europe/Berlin"))
        if now.hour != 4 or now.minute != 0:
            return

        daten = SHEET.get_all_values()
        heute = now.strftime("%d.%m.%Y")
        matches = [row for row in daten[1:] if len(row) >= 7 and row[1].strip() >= heute]

        if not matches:
            return

        matches.sort(key=lambda x: datetime.datetime.strptime(x[1] + " " + x[2], "%d.%m.%Y %H:%M"))
        lines = [f"{row[1]} {row[2]} | {row[0]} | {row[3]} vs. {row[4]} | {row[5]}" for row in matches]

        channel = client.get_channel(RESTREAM_CHANNEL_ID)
        if channel:
            await channel.send("📋 **Geplante Matches ab heute:**\n" + "\n".join(lines))

    except Exception as e:
        print(f"❌ Fehler bei täglicher Ausgabe: {e}")

class RestreamModal(discord.ui.Modal, title="Restream-Optionen festlegen"):
    restream_input = discord.ui.TextInput(
        label="Restream Ziel (ZSR, SG1 oder SG2)",
        placeholder="z. B. ZSR",
        required=True,
        max_length=3
    )

    def __init__(self, selected_row):
        super().__init__()
        self.selected_row = selected_row  # [division, date, time, spieler1, spieler2, modus]

    async def on_submit(self, interaction: discord.Interaction):
        code = self.restream_input.value.strip().upper()
        allowed = {"ZSR", "SG1", "SG2"}

        if code not in allowed:
            await interaction.response.send_message("❌ Ungültiger Code. Erlaubt: ZSR, SG1, SG2", ephemeral=True)
            return

        title_prefix = {
            "ZSR": "RESTREAM ZSR |",
            "SG1": "RESTREAM SGD1 |",
            "SG2": "RESTREAM SGD2 |"
        }[code]

        location_url = {
            "ZSR": "https://www.twitch.tv/zeldaspeedrunsde",
            "SG1": "https://www.twitch.tv/speedgamingdeutsch",
            "SG2": "https://www.twitch.tv/speedgamingdeutsch2"
        }[code]

        # Eventtitel wie bei Termin-Erstellung zusammensetzen
        original_title = f"{self.selected_row[0]} | {self.selected_row[3]} vs. {self.selected_row[4]} | {self.selected_row[5]}"
        new_title = f"{title_prefix} {original_title}"

        # Event suchen (by title)
        event = discord.utils.get(interaction.guild.scheduled_events, name=original_title)
        if not event:
            await interaction.response.send_message("❌ Kein passendes Event gefunden.", ephemeral=True)
            return

        try:
            await event.edit(name=new_title, location=location_url)

            # Update Spalte H im Sheet (Spalte 8 → Index 7)
            daten = SHEET.get_all_values()
            for idx, row in enumerate(daten):
                if len(row) >= 6 and row[0] == self.selected_row[0] and row[1] == self.selected_row[1] and row[2] == self.selected_row[2]:
                    SHEET.update_cell(idx + 1, 8, code)  # +1 weil Sheets 1-indiziert sind
                    break

            await interaction.response.send_message(f"✅ Event und Sheet erfolgreich mit `{code}` aktualisiert.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Fehler beim Aktualisieren: {e}", ephemeral=True)


@tree.command(name="restreams", description="Setzt Restream-Ziel für ein geplantes Spiel")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def restreams(interaction: discord.Interaction):
    try:
        daten = SHEET.get_all_values()
        heute = datetime.datetime.now(pytz.timezone("Europe/Berlin")).strftime("%d.%m.%Y")
        matches = [row for row in daten[1:] if len(row) >= 6 and row[1].strip() >= heute]

        if not matches:
            await interaction.response.send_message("📭 Keine zukünftigen Spiele gefunden.", ephemeral=True)
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


client.run(TOKEN)
