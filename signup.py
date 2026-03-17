import os
import discord
from discord import app_commands
from discord.ext import commands
import gspread
from google.oauth2.service_account import Credentials
from typing import Optional

GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0"))

# =========================================================
# GOOGLE CONFIG
# =========================================================

SPREADSHEET_ID = "1pZxg1_DUtbO4dZvX95ZrIqEZnkMc1MjmE7z5SEsMHQU"
WORKSHEET_GID = 463142264
GOOGLE_CREDENTIALS_FILE = "google_credentials.json"

ADMIN_ROLE_NAMES = {"Admin", "Orga", "TFL Admin"}

YES_NO_OPTIONS = [
    discord.SelectOption(label="Ja", value="Ja"),
    discord.SelectOption(label="Nein", value="Nein"),
]

# =========================================================
# GOOGLE SHEET
# =========================================================

def get_worksheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(
        GOOGLE_CREDENTIALS_FILE,
        scopes=scopes
    )
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID)
    return sheet.get_worksheet_by_id(WORKSHEET_GID)


def is_signup_open(ws) -> bool:
    value = ws.acell("A2").value or ""
    return value.strip().lower() == "open"


def normalize_name(value: str) -> str:
    return value.strip().lower()


def find_name_row(ws, name: str) -> Optional[int]:
    names = ws.col_values(1)
    target = normalize_name(name)

    for i, cell in enumerate(names, start=1):
        if normalize_name(cell) == target:
            return i
    return None


def find_free_row(ws) -> int:
    names = ws.col_values(1)
    for i, cell in enumerate(names, start=1):
        if not cell.strip():
            return i
    return len(names) + 1


def is_blocked(status: str) -> bool:
    return status.strip().lower() in {"banned", "timeout"}


def write_row(ws, row, name, twitch, league, cup, restream, commentary, tracker):
    ws.update(
        f"A{row}:G{row}",
        [[name, twitch, league, cup, restream, commentary, tracker]]
    )


def process_signup(name, twitch, league, cup, restream, commentary, tracker):
    ws = get_worksheet()
    row = find_name_row(ws, name)

    if row is not None:
        status = ws.acell(f"H{row}").value or ""
        if is_blocked(status):
            return "Du kannst dich aktuell nicht anmelden, da eine Sperre aktiv ist."

        write_row(ws, row, name, twitch, league, cup, restream, commentary, tracker)
        return "Deine Anmeldung wurde aktualisiert."

    row = find_free_row(ws)
    write_row(ws, row, name, twitch, league, cup, restream, commentary, tracker)
    return "Deine Anmeldung wurde eingetragen."


def get_row_values(ws, row: int):
    values = ws.row_values(row)
    while len(values) < 8:
        values.append("")
    return values[:8]


def format_signup_row(values: list[str]) -> str:
    return (
        f"**Name:** {values[0] or '-'}\n"
        f"**Twitch:** {values[1] or '-'}\n"
        f"**League:** {values[2] or '-'}\n"
        f"**Cup:** {values[3] or '-'}\n"
        f"**Restream:** {values[4] or '-'}\n"
        f"**Commentary:** {values[5] or '-'}\n"
        f"**Tracker:** {values[6] or '-'}\n"
        f"**Status:** {values[7] or '-'}"
    )


def get_names_by_column_value(ws, column_index: int, target_value: str):
    rows = ws.get_all_values()
    matches = []

    for row in rows:
        if len(row) < column_index:
            continue

        name = row[0].strip()
        value = row[column_index - 1].strip().lower()

        if name and value == target_value.lower():
            matches.append(name)

    return matches


def reset_signup_data(ws):
    rows = ws.get_all_values()
    count = 0

    for i, row in enumerate(rows, start=1):
        if not row or not row[0].strip():
            continue

        if i == 2 and row[0].lower() in ["open", "closed"]:
            continue

        ws.update(
            f"C{i}:H{i}",
            [["Nein", "Nein", "Nein", "Nein", "Nein", "nicht gemeldet"]]
        )
        count += 1

    return count


# =========================================================
# UI
# =========================================================

class TwitchModal(discord.ui.Modal, title="Twitchkanal"):
    twitch = discord.ui.TextInput(label="Twitchkanal", required=False)

    def __init__(self, view):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        self.view_ref.twitch = str(self.twitch.value).strip()
        await interaction.response.send_message("Twitch gesetzt.", ephemeral=True)


class YesNoSelect(discord.ui.Select):
    def __init__(self, field):
        super().__init__(placeholder=field, options=YES_NO_OPTIONS)
        self.field = field

    async def callback(self, interaction: discord.Interaction):
        setattr(self.view, self.field, self.values[0])
        await interaction.response.send_message(
            f"{self.field}: {self.values[0]}",
            ephemeral=True
        )


class SignupView(discord.ui.View):
    def __init__(self, user_id, name):
        super().__init__(timeout=600)

        self.user_id = user_id
        self.name = name

        self.twitch = ""
        self.league = None
        self.cup = None
        self.restream = None
        self.commentary = None
        self.tracker = None

        self.add_item(YesNoSelect("league"))
        self.add_item(YesNoSelect("cup"))
        self.add_item(YesNoSelect("restream"))
        self.add_item(YesNoSelect("commentary"))
        self.add_item(YesNoSelect("tracker"))

    @discord.ui.button(label="Twitch setzen", style=discord.ButtonStyle.secondary)
    async def twitch_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TwitchModal(self))

    @discord.ui.button(label="Absenden", style=discord.ButtonStyle.success)
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Nicht dein Formular.", ephemeral=True)
            return

        try:
            ws = get_worksheet()

            if not is_signup_open(ws):
                await interaction.response.send_message(
                    "Die Anmeldephase ist vorbei.",
                    ephemeral=True
                )
                return

            missing = [
                f for f in ["league", "cup", "restream", "commentary", "tracker"]
                if getattr(self, f) is None
            ]
            if missing:
                await interaction.response.send_message(
                    "Bitte alles ausfüllen.",
                    ephemeral=True
                )
                return

            result = process_signup(
                self.name,
                self.twitch,
                self.league,
                self.cup,
                self.restream,
                self.commentary,
                self.tracker
            )

            await interaction.response.edit_message(content=result, view=None)

        except Exception as e:
            await interaction.response.send_message(
                f"Fehler beim Absenden: {e}",
                ephemeral=True
            )


# =========================================================
# COG
# =========================================================

class SignupCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="signup", description="Anmelden")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def signup(self, interaction: discord.Interaction):
        member = interaction.user

        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Nur Server.", ephemeral=True)
            return

        ws = get_worksheet()
        if not is_signup_open(ws):
            await interaction.response.send_message("Die Anmeldephase ist vorbei.", ephemeral=True)
            return

        view = SignupView(member.id, member.display_name.strip())
        await interaction.response.send_message(f"Anmeldung für **{member.display_name}**", view=view, ephemeral=True)

    @app_commands.command(name="signstat")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def signstat(self, interaction: discord.Interaction):
        ws = get_worksheet()
        row = find_name_row(ws, interaction.user.display_name)

        if not row:
            await interaction.response.send_message("Kein Eintrag gefunden.", ephemeral=True)
            return

        values = get_row_values(ws, row)
        await interaction.response.send_message(format_signup_row(values), ephemeral=True)

    @app_commands.command(name="leaguesign")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def leaguesign(self, interaction: discord.Interaction):
        ws = get_worksheet()
        names = get_names_by_column_value(ws, 3, "Ja")

        if not names:
            await interaction.response.send_message("Keine League-Anmeldungen.", ephemeral=True)
            return

        await interaction.response.send_message("\n".join(names), ephemeral=True)

    @app_commands.command(name="cupsign")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def cupsign(self, interaction: discord.Interaction):
        ws = get_worksheet()
        names = get_names_by_column_value(ws, 4, "Ja")

        if not names:
            await interaction.response.send_message("Keine Cup-Anmeldungen.", ephemeral=True)
            return

        await interaction.response.send_message("\n".join(names), ephemeral=True)

    @app_commands.command(name="resetsign")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def resetsign(self, interaction: discord.Interaction):
        ws = get_worksheet()
        count = reset_signup_data(ws)
        await interaction.response.send_message(f"{count} Einträge zurückgesetzt.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(SignupCog(bot), guild=discord.Object(id=GUILD_ID))
