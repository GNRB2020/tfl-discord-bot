import os
import re
import asyncio
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

GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0").strip())

TFNL_SPREADSHEET_ID = os.getenv(
    "TFNL_SPREADSHEET_ID",
    "1TamFbS5cRCcgSJFoQEohXdv03tVhk0VynvleeiVBQsM",
).strip()

CREDS_FILE = os.getenv(
    "GOOGLE_CREDENTIALS_FILE",
    os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials.json")
).strip()

TFNL_SCHEDULE_CHANNEL_ID = int(
    os.getenv("TFNL_SCHEDULE_CHANNEL_ID", "1502031472574337204").strip()
)

TFNL_SIGNUP_CHANNEL_ID = int(
    os.getenv("TFNL_SIGNUP_CHANNEL_ID", "1502062610227531877").strip()
)

TFNL_LADDER_ROLE_ID = int(
    os.getenv("TFNL_LADDER_ROLE_ID", "1502062912552833185").strip()
)

TFNL_CATEGORY_ID = int(
    os.getenv("TFNL_CATEGORY_ID", "1502014179803005009").strip()
)

BERLIN_TZ = ZoneInfo("Europe/Berlin")

SCHEDULE_SHEET_NAME = "Schedule"
SIGNUP_SHEET_NAME = "Signup"
SCHEDULE_ANNOUNCEMENT_COL = "Signup Announcement Sent"

SIGNUP_HEADERS = [
    "Slot ID",
    "Discord ID",
    "Discord Display Name",
    "Angemeldet um",
    "DM geprüft",
    "Status",
]

SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

print("DEBUG TFNL_SPREADSHEET_ID =", repr(TFNL_SPREADSHEET_ID))
print("DEBUG TFNL CREDS_FILE =", repr(CREDS_FILE))
print("DEBUG TFNL_SCHEDULE_CHANNEL_ID =", TFNL_SCHEDULE_CHANNEL_ID)
print("DEBUG TFNL_SIGNUP_CHANNEL_ID =", TFNL_SIGNUP_CHANNEL_ID)
print("DEBUG TFNL_LADDER_ROLE_ID =", TFNL_LADDER_ROLE_ID)
print("DEBUG TFNL_CATEGORY_ID =", TFNL_CATEGORY_ID)


# =========================================================
# GOOGLE SHEETS
# =========================================================

def get_tfnl_spreadsheet():
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    client = gspread.authorize(creds)
    return client.open_by_key(TFNL_SPREADSHEET_ID)


def get_or_create_worksheet(
    spreadsheet,
    title: str,
    headers: list[str],
    rows: int = 1000,
    cols: int = 20,
):
    try:
        sheet = spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)

    existing_headers = sheet.row_values(1)

    if existing_headers != headers:
        sheet.update("A1", [headers])

    return sheet


def get_schedule_sheet():
    spreadsheet = get_tfnl_spreadsheet()
    return spreadsheet.worksheet(SCHEDULE_SHEET_NAME)


def get_signup_sheet():
    spreadsheet = get_tfnl_spreadsheet()
    return get_or_create_worksheet(
        spreadsheet=spreadsheet,
        title=SIGNUP_SHEET_NAME,
        headers=SIGNUP_HEADERS,
        rows=1000,
        cols=len(SIGNUP_HEADERS),
    )


def load_schedule_rows():
    sheet = get_schedule_sheet()
    return sheet.get_all_records()


def load_schedule_rows_with_index():
    sheet = get_schedule_sheet()
    rows = sheet.get_all_records()

    result = []
    for index, row in enumerate(rows, start=2):
        result.append((index, row))

    return result


def load_signup_rows():
    sheet = get_signup_sheet()
    return sheet.get_all_records()


def append_signup(slot_id: str, user_id: int, display_name: str):
    sheet = get_signup_sheet()

    now = datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M:%S")

    sheet.append_row(
        [
            slot_id,
            str(user_id),
            display_name,
            now,
            "Ja",
            "signed_up",
        ],
        value_input_option="USER_ENTERED",
    )


def find_schedule_row(slot_id: str):
    for row_index, row in load_schedule_rows_with_index():
        if normalize_text(row.get("Slot ID")) == slot_id:
            return row_index, row

    return None, None


def update_schedule_cell(slot_id: str, column_name: str, value: str):
    sheet = get_schedule_sheet()
    row_index, row = find_schedule_row(slot_id)

    if not row_index:
        return

    headers = sheet.row_values(1)

    try:
        col_index = headers.index(column_name) + 1
    except ValueError:
        return

    sheet.update_cell(row_index, col_index, value)


def update_schedule_channel_id(slot_id: str, channel_id: int):
    update_schedule_cell(slot_id, "Slot Channel ID", str(channel_id))


def update_schedule_announcement_sent(slot_id: str):
    update_schedule_cell(slot_id, SCHEDULE_ANNOUNCEMENT_COL, "Ja")


# =========================================================
# HELPERS
# =========================================================

def normalize_text(value) -> str:
    return str(value or "").strip()


def parse_german_date(value):
    if not value:
        return None

    value = normalize_text(value)

    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass

    return None


def parse_time(value):
    if not value:
        return None

    value = normalize_text(value)

    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            pass

    return None


def build_datetime(date_value, time_value):
    parsed_date = parse_german_date(date_value)
    parsed_time = parse_time(time_value)

    if not parsed_date or not parsed_time:
        return None

    return datetime.combine(parsed_date, parsed_time, tzinfo=BERLIN_TZ)


def is_registration_open(row: dict) -> bool:
    now = datetime.now(BERLIN_TZ)

    start = build_datetime(row.get("Datum"), row.get("Anmeldebeginn"))
    end = build_datetime(row.get("Datum"), row.get("Anmeldeschluss"))

    if not start or not end:
        return False

    return start <= now < end


def signup_announcement_already_sent(row: dict) -> bool:
    value = normalize_text(row.get(SCHEDULE_ANNOUNCEMENT_COL)).lower()
    return value in ("ja", "yes", "true", "1")


def sanitize_channel_name(value: str) -> str:
    value = value.lower()
    value = value.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    value = re.sub(r"[^a-z0-9\-]+", "-", value)
    value = re.sub(r"-+", "-", value)
    return value.strip("-")[:90]


def build_slot_channel_name(row: dict) -> str:
    datum = normalize_text(row.get("Datum")).replace(".", "-")
    slot = normalize_text(row.get("Slot")).lower()
    modus = normalize_text(row.get("Modus")).lower()

    raw = f"tfnl-{datum}-{slot}-{modus}"
    return sanitize_channel_name(raw)


def build_slot_line(row: dict) -> str:
    datum = normalize_text(row.get("Datum"))
    slot = normalize_text(row.get("Slot"))
    startzeit = normalize_text(row.get("Startzeit"))
    modus = normalize_text(row.get("Modus"))
    status = normalize_text(row.get("Status"))

    if not status:
        status = "planned"

    return f"**{datum} | {slot} | {startzeit} Uhr** — {modus} `[{status}]`"


def build_signup_line(row: dict) -> str:
    datum = normalize_text(row.get("Datum"))
    slot = normalize_text(row.get("Slot"))
    startzeit = normalize_text(row.get("Startzeit"))
    anmeldeschluss = normalize_text(row.get("Anmeldeschluss"))
    modus = normalize_text(row.get("Modus"))

    return (
        f"**{datum} | {slot} | {startzeit} Uhr** — {modus}\n"
        f"Anmeldeschluss: `{anmeldeschluss} Uhr`"
    )


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


def get_open_signup_slots():
    rows = load_schedule_rows()

    open_slots = []

    for row in rows:
        if is_registration_open(row):
            open_slots.append(row)

    open_slots.sort(
        key=lambda r: (
            parse_german_date(r.get("Datum")) or datetime.now(BERLIN_TZ).date(),
            normalize_text(r.get("Startzeit")),
        )
    )

    return open_slots


def user_already_signed_up(slot_id: str, user_id: int) -> bool:
    rows = load_signup_rows()

    for row in rows:
        if (
            normalize_text(row.get("Slot ID")) == slot_id
            and normalize_text(row.get("Discord ID")) == str(user_id)
            and normalize_text(row.get("Status")).lower() == "signed_up"
        ):
            return True

    return False


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


def build_signup_embed(open_slots: list[dict]) -> discord.Embed:
    now = datetime.now(BERLIN_TZ).strftime("%d.%m.%Y %H:%M")

    if not open_slots:
        description = (
            "Aktuell ist keine Anmeldung geöffnet.\n\n"
            "Early öffnet um `18:15 Uhr`.\n"
            "Late öffnet um `20:15 Uhr`."
        )

        title = "TFNL-Anmeldung"
    else:
        description = "\n\n".join(build_signup_line(row) for row in open_slots)
        title = "TFNL-Anmeldung geöffnet"

    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.dark_teal(),
    )

    embed.set_footer(text=f"Aktualisiert: {now} Uhr")

    return embed


# =========================================================
# DISCORD VIEW
# =========================================================

class SignupSlotButton(discord.ui.Button):
    def __init__(self, slot_id: str, label: str):
        super().__init__(
            label=label,
            style=discord.ButtonStyle.success,
            custom_id=f"tfnl_signup:{slot_id}",
        )
        self.slot_id = slot_id

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("LadderCog")

        if cog is None:
            await interaction.response.send_message(
                "TFNL-Modul ist nicht geladen.",
                ephemeral=True,
            )
            return

        await cog.handle_signup(interaction, self.slot_id)


class SignupView(discord.ui.View):
    def __init__(self, open_slots: list[dict]):
        super().__init__(timeout=None)

        for row in open_slots[:25]:
            slot_id = normalize_text(row.get("Slot ID"))
            slot = normalize_text(row.get("Slot"))
            startzeit = normalize_text(row.get("Startzeit"))
            modus = normalize_text(row.get("Modus"))

            if not slot_id:
                continue

            label = f"{slot} {startzeit} | {modus}"
            self.add_item(SignupSlotButton(slot_id=slot_id, label=label))


# =========================================================
# COG
# =========================================================

class LadderCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.last_schedule_message_id = None
        self.last_signup_message_id = None

        if not self.update_schedule_channel.is_running():
            self.update_schedule_channel.start()

        if not self.update_signup_channel.is_running():
            self.update_signup_channel.start()

    def cog_unload(self):
        self.update_schedule_channel.cancel()
        self.update_signup_channel.cancel()

    # =====================================================
    # CHANNEL HELPERS
    # =====================================================

    async def get_text_channel(self, channel_id: int):
        channel = self.bot.get_channel(channel_id)

        if channel is None:
            channel = await self.bot.fetch_channel(channel_id)

        return channel

    async def publish_schedule_to_channel(self):
        try:
            channel = await self.get_text_channel(TFNL_SCHEDULE_CHANNEL_ID)
        except Exception as e:
            print(f"[TFNL] Konnte Schedule-Channel nicht laden: {repr(e)}")
            return

        try:
            embed = build_schedule_embed(days=5)
        except Exception as e:
            print(f"[TFNL] Konnte Schedule-Embed nicht bauen: {repr(e)}")
            return

        if self.last_schedule_message_id:
            try:
                old_message = await channel.fetch_message(self.last_schedule_message_id)
                await old_message.edit(embed=embed)
                return
            except Exception as e:
                print(f"[TFNL] Alte Schedule-Nachricht konnte nicht editiert werden: {repr(e)}")
                self.last_schedule_message_id = None

        try:
            async for message in channel.history(limit=25):
                if self.bot.user and message.author.id == self.bot.user.id:
                    try:
                        await message.delete()
                    except Exception as e:
                        print(f"[TFNL] Alte Schedule-Bot-Nachricht konnte nicht gelöscht werden: {repr(e)}")
        except Exception as e:
            print(f"[TFNL] Konnte Schedule-Channel-History nicht lesen: {repr(e)}")

        try:
            new_message = await channel.send(embed=embed)
            self.last_schedule_message_id = new_message.id
            print("[TFNL] Spielplan im Channel aktualisiert.")
        except Exception as e:
            print(f"[TFNL] Konnte Schedule nicht senden: {repr(e)}")

    async def send_signup_announcements(self, open_slots: list[dict], signup_channel: discord.TextChannel):
        for row in open_slots:
            slot_id = normalize_text(row.get("Slot ID"))

            if not slot_id:
                continue

            if signup_announcement_already_sent(row):
                continue

            datum = normalize_text(row.get("Datum"))
            slot = normalize_text(row.get("Slot"))
            startzeit = normalize_text(row.get("Startzeit"))
            anmeldeschluss = normalize_text(row.get("Anmeldeschluss"))
            modus = normalize_text(row.get("Modus"))

            role_mention = f"<@&{TFNL_LADDER_ROLE_ID}>"

            try:
                ping_message = await signup_channel.send(
                    f"{role_mention} **TFNL-Anmeldung geöffnet**\n"
                    f"**{datum} | {slot} | {startzeit} Uhr** — {modus}\n"
                    f"Anmeldeschluss: `{anmeldeschluss} Uhr`"
                )

                update_schedule_announcement_sent(slot_id)

                async def delete_later(message: discord.Message):
                    await asyncio.sleep(60)
                    try:
                        await message.delete()
                    except Exception as e:
                        print(f"[TFNL] Signup-Ping konnte nicht gelöscht werden: {repr(e)}")

                self.bot.loop.create_task(delete_later(ping_message))

            except Exception as e:
                print(f"[TFNL] Signup-Announcement konnte nicht gesendet werden: {repr(e)}")

    async def publish_signup_to_channel(self):
        try:
            channel = await self.get_text_channel(TFNL_SIGNUP_CHANNEL_ID)
        except Exception as e:
            print(f"[TFNL] Konnte Signup-Channel nicht laden: {repr(e)}")
            return

        try:
            open_slots = get_open_signup_slots()
            embed = build_signup_embed(open_slots)
            view = SignupView(open_slots) if open_slots else None
        except Exception as e:
            print(f"[TFNL] Konnte Signup-Embed nicht bauen: {repr(e)}")
            return

        await self.send_signup_announcements(open_slots, channel)

        if self.last_signup_message_id:
            try:
                old_message = await channel.fetch_message(self.last_signup_message_id)
                await old_message.edit(embed=embed, view=view)
                return
            except Exception as e:
                print(f"[TFNL] Alte Signup-Nachricht konnte nicht editiert werden: {repr(e)}")
                self.last_signup_message_id = None

        try:
            async for message in channel.history(limit=25):
                if self.bot.user and message.author.id == self.bot.user.id:
                    try:
                        await message.delete()
                    except Exception as e:
                        print(f"[TFNL] Alte Signup-Bot-Nachricht konnte nicht gelöscht werden: {repr(e)}")
        except Exception as e:
            print(f"[TFNL] Konnte Signup-Channel-History nicht lesen: {repr(e)}")

        try:
            new_message = await channel.send(embed=embed, view=view)
            self.last_signup_message_id = new_message.id
            print("[TFNL] Anmeldung im Channel aktualisiert.")
        except Exception as e:
            print(f"[TFNL] Konnte Signup nicht senden: {repr(e)}")

    # =====================================================
    # SIGNUP LOGIC
    # =====================================================

    async def handle_signup(self, interaction: discord.Interaction, slot_id: str):
        await interaction.response.defer(ephemeral=True)

        member = interaction.user

        if not isinstance(member, discord.Member):
            await interaction.followup.send(
                "Anmeldung fehlgeschlagen: Mitglied konnte nicht erkannt werden.",
                ephemeral=True,
            )
            return

        role = member.guild.get_role(TFNL_LADDER_ROLE_ID)

        if role is None:
            await interaction.followup.send(
                "Anmeldung fehlgeschlagen: Ladder-Rolle wurde nicht gefunden.",
                ephemeral=True,
            )
            return

        if role not in member.roles:
            await interaction.followup.send(
                "Du hast keine Berechtigung für die TFNL-Ladder.",
                ephemeral=True,
            )
            return

        row_index, schedule_row = find_schedule_row(slot_id)

        if not schedule_row:
            await interaction.followup.send(
                "Anmeldung fehlgeschlagen: Slot wurde im Schedule nicht gefunden.",
                ephemeral=True,
            )
            return

        if not is_registration_open(schedule_row):
            await interaction.followup.send(
                "Die Anmeldung für diesen Slot ist aktuell nicht geöffnet.",
                ephemeral=True,
            )
            return

        if user_already_signed_up(slot_id, member.id):
            await interaction.followup.send(
                "Du bist für diesen Slot bereits angemeldet.",
                ephemeral=True,
            )
            return

        try:
            await member.send(
                f"TFNL-DM-Test erfolgreich.\n"
                f"Du meldest dich für folgenden Slot an:\n"
                f"**{normalize_text(schedule_row.get('Datum'))} | "
                f"{normalize_text(schedule_row.get('Slot'))} | "
                f"{normalize_text(schedule_row.get('Startzeit'))} Uhr | "
                f"{normalize_text(schedule_row.get('Modus'))}**"
            )
        except Exception:
            await interaction.followup.send(
                "Anmeldung abgelehnt: Ich kann dir keine DM senden. "
                "Bitte öffne deine DMs für diesen Server und versuche es erneut.",
                ephemeral=True,
            )
            return

        try:
            append_signup(
                slot_id=slot_id,
                user_id=member.id,
                display_name=member.display_name,
            )
        except Exception as e:
            await interaction.followup.send(
                f"Anmeldung fehlgeschlagen: Sheet konnte nicht beschrieben werden.\n```{repr(e)}```",
                ephemeral=True,
            )
            return

        try:
            slot_channel = await self.get_or_create_slot_channel(schedule_row)

            await slot_channel.set_permissions(
                member,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )

            await slot_channel.send(
                f"{member.mention} ist für diesen TFNL-Slot angemeldet."
            )
        except Exception as e:
            await interaction.followup.send(
                f"Anmeldung wurde gespeichert, aber der Slot-Channel konnte nicht aktualisiert werden.\n```{repr(e)}```",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "Anmeldung erfolgreich. Du wurdest dem privaten Slot-Channel hinzugefügt.",
            ephemeral=True,
        )

        await self.publish_signup_to_channel()

    async def get_or_create_slot_channel(self, schedule_row: dict):
        guild = self.bot.get_guild(GUILD_ID)

        if guild is None:
            guild = await self.bot.fetch_guild(GUILD_ID)

        existing_channel_id = normalize_text(schedule_row.get("Slot Channel ID"))

        if existing_channel_id:
            try:
                channel = self.bot.get_channel(int(existing_channel_id))
                if channel is None:
                    channel = await self.bot.fetch_channel(int(existing_channel_id))
                return channel
            except Exception:
                pass

        category = guild.get_channel(TFNL_CATEGORY_ID)

        if category is None:
            category = await self.bot.fetch_channel(TFNL_CATEGORY_ID)

        channel_name = build_slot_channel_name(schedule_row)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                manage_permissions=True,
            ),
        }

        channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            reason="TFNL Slot-Channel erstellt",
        )

        slot_id = normalize_text(schedule_row.get("Slot ID"))
        update_schedule_channel_id(slot_id, channel.id)

        await channel.send(
            "**TFNL Slot-Channel erstellt.**\n"
            "Die Paarungen bleiben geheim, bis Ergebnisse vorliegen."
        )

        return channel

    # =====================================================
    # TASKS
    # =====================================================

    @tasks.loop(minutes=5)
    async def update_schedule_channel(self):
        await self.publish_schedule_to_channel()

    @update_schedule_channel.before_loop
    async def before_update_schedule_channel(self):
        await self.bot.wait_until_ready()
        await self.publish_schedule_to_channel()

    @tasks.loop(minutes=1)
    async def update_signup_channel(self):
        await self.publish_signup_to_channel()

    @update_signup_channel.before_loop
    async def before_update_signup_channel(self):
        await self.bot.wait_until_ready()
        await self.publish_signup_to_channel()

    # =====================================================
    # COMMANDS
    # =====================================================

    @app_commands.guilds(discord.Object(id=GUILD_ID))
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
                f"Fehler beim Lesen des TFNL-Sheets:\n```{repr(e)}```",
                ephemeral=True,
            )
            return

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
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
                f"Fehler beim Aktualisieren des Plan-Channels:\n```{repr(e)}```",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "TFNL-Spielplan wurde aktualisiert.",
            ephemeral=True,
        )

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(
        name="ladder_signup_update",
        description="Aktualisiert die TFNL-Anmeldung im Signup-Channel manuell."
    )
    async def ladder_signup_update(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            await self.publish_signup_to_channel()
        except Exception as e:
            await interaction.followup.send(
                f"Fehler beim Aktualisieren der Anmeldung:\n```{repr(e)}```",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "TFNL-Anmeldung wurde aktualisiert.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(LadderCog(bot))
