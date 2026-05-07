import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
import gspread
from discord import app_commands
from discord.ext import commands, tasks
from oauth2client.service_account import ServiceAccountCredentials


# =========================================================
# TFNL SETTINGS
# =========================================================

TFNL_SPREADSHEET_ID = os.getenv(
    "TFNL_SPREADSHEET_ID",
    "1TamFbS5cRCcgSJFoQEohXdv03tVhk0VynvleeiVBQsM",
)

CREDS_FILE = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_FILE",
    "credentials.json",
)

TFNL_SCHEDULE_CHANNEL_ID = int(
    os.getenv("TFNL_SCHEDULE_CHANNEL_ID", "1502031472574337204")
)

BERLIN_TZ = ZoneInfo("Europe/Berlin")

SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]


# =========================================================
# GOOGLE SHEETS
# =========================================================

def get_tfnl_spreadsheet():
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    client = gspread.authorize(creds)
    return client.open_by_key(TFNL_SPREADSHEET_ID)


def get_schedule_sheet():
    spreadsheet = get_tfnl_spreadsheet()
    return spreadsheet.worksheet("Schedule")


def load_schedule_rows():
    sheet = get_schedule_sheet()
    return sheet.get_all_records()


# =========================================================
# HELPERS
# =========================================================

def parse_german_date(value: str):
    """
    Erwartet Datum im Format DD.MM.YYYY
    """
    if not value:
        return None

    value = str(value).strip()

    try:
        return datetime.strptime(value, "%d.%m.%Y").date()
    except ValueError:
        return None


def normalize_text(value) -> str:
    return str(value or "").strip()


def build_slot_line(row: dict) -> str:
    datum = normalize_text(row.get("Datum"))
    slot = normalize_text(row.get("Slot"))
    startzeit = normalize_text(row.get("Startzeit"))
    modus = normalize_text(row.get("Modus"))
    status = normalize_text(row.get("Status"))

    if not status:
        status = "planned"

    return f"**{datum} | {slot} | {startzeit} Uhr** — {modus} `[{status}]`"


def get_upcoming_schedule(days: int = 5):
    rows = load_schedule_rows()

    today = datetime.now(BERLIN_TZ).date()
    end_date = today + timedelta(days=days)

    upcoming = []

    for row in rows:
        slot_date = parse_german_date(row.get("Datum"))

        if not slot_date:
            continue

        if today <= slot_date <= end_date:
            upcoming.append(row)

    upcoming.sort(
        key=lambda r: (
            parse_german_date(r.get("Datum")) or today,
            normalize_text(r.get("Startzeit")),
        )
    )

    return upcoming


def build_schedule_embed(days: int = 5) -> discord.Embed:
    upcoming = get_upcoming_schedule(days=days)

    if not upcoming:
        description = f"Keine TFNL-Slots in den nächsten {days} Tagen gefunden."
    else:
        description = "\n".join(build_slot_line(row) for row in upcoming)

    now = datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M")

    embed = discord.Embed(
        title="TFNL-Spielplan",
        description=description,
        color=discord.Color.dark_teal(),
    )

    embed.set_footer(
        text=f"Try Force Nachteulen Ladder | Aktualisiert: {now} Uhr"
    )

    return embed


# =========================================================
# COG
# =========================================================

class LadderCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.last_schedule_message_id = None
        self.update_schedule_channel.start()

    def cog_unload(self):
        self.update_schedule_channel.cancel()

    async def publish_schedule_to_channel(self):
        channel = self.bot.get_channel(TFNL_SCHEDULE_CHANNEL_ID)

        if channel is None:
            try:
                channel = await self.bot.fetch_channel(TFNL_SCHEDULE_CHANNEL_ID)
            except Exception as e:
                print(f"[TFNL] Konnte Schedule-Channel nicht laden: {e}")
                return

        embed = build_schedule_embed(days=5)

        # 1. Versuch: vorhandene Nachricht aktualisieren
        if self.last_schedule_message_id:
            try:
                old_message = await channel.fetch_message(self.last_schedule_message_id)
                await old_message.edit(embed=embed)
                return
            except Exception:
                self.last_schedule_message_id = None

        # 2. Alte Bot-Nachrichten im Channel entfernen
        try:
            async for message in channel.history(limit=25):
                if message.author == self.bot.user:
                    try:
                        await message.delete()
                    except Exception:
                        pass
        except Exception as e:
            print(f"[TFNL] Konnte alte Schedule-Nachrichten nicht löschen: {e}")

        # 3. Neue Plan-Nachricht senden
        try:
            new_message = await channel.send(embed=embed)
            self.last_schedule_message_id = new_message.id
        except Exception as e:
            print(f"[TFNL] Konnte Schedule nicht senden: {e}")

    @tasks.loop(minutes=5)
    async def update_schedule_channel(self):
        await self.publish_schedule_to_channel()

    @update_schedule_channel.before_loop
    async def before_update_schedule_channel(self):
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="ladder_plan",
        description="Zeigt den TFNL-Spielplan der nächsten 5 Tage."
    )
    async def ladder_plan(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            embed = build_schedule_embed(days=5)
        except Exception as e:
            await interaction.followup.send(
                f"Fehler beim Lesen des TFNL-Sheets:\n```{e}```",
                ephemeral=True,
            )
            return

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="ladder_plan_update",
        description="Aktualisiert den TFNL-Spielplan im Plan-Channel manuell."
    )
    async def ladder_plan_update(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            await self.publish_schedule_to_channel()
        except Exception as e:
            await interaction.followup.send(
                f"Fehler beim Aktualisieren des Plan-Channels:\n```{e}```",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "TFNL-Spielplan wurde aktualisiert.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(LadderCog(bot))
