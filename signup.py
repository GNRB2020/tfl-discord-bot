import discord
from discord import app_commands
from discord.ext import commands

import gspread
from google.oauth2.service_account import Credentials
from typing import Optional


# =========================================================
# GOOGLE CONFIG (DEIN SHEET)
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
    ws.update(f"A{row}:G{row}", [[
        name, twitch, league, cup, restream, commentary, tracker
    ]])


def process_signup(name, twitch, league, cup, restream, commentary, tracker):
    ws = get_worksheet()

    row = find_name_row(ws, name)

    if row:
        status = ws.acell(f"H{row}").value or ""
        if is_blocked(status):
            return "Du kannst dich aktuell nicht anmelden, da eine Sperre aktiv ist."

        write_row(ws, row, name, twitch, league, cup, restream, commentary, tracker)
        return "Deine Anmeldung wurde aktualisiert."

    row = find_free_row(ws)
    write_row(ws, row, name, twitch, league, cup, restream, commentary, tracker)
    return "Deine Anmeldung wurde eingetragen."


# =========================================================
# UI
# =========================================================

class TwitchModal(discord.ui.Modal, title="Twitchkanal"):
    twitch = discord.ui.TextInput(label="Twitchkanal", required=False)

    def __init__(self, view):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        self.view_ref.twitch = str(self.twitch.value)
        await interaction.response.send_message("Twitch gesetzt.", ephemeral=True)


class YesNoSelect(discord.ui.Select):
    def __init__(self, field):
        super().__init__(placeholder=field, options=YES_NO_OPTIONS)
        self.field = field

    async def callback(self, interaction: discord.Interaction):
        setattr(self.view, self.field, self.values[0])
        await interaction.response.send_message(f"{self.field}: {self.values[0]}", ephemeral=True)


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
    async def twitch_btn(self, interaction: discord.Interaction, button):
        await interaction.response.send_modal(TwitchModal(self))

    @discord.ui.button(label="Absenden", style=discord.ButtonStyle.success)
    async def submit(self, interaction: discord.Interaction, button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Nicht dein Formular.", ephemeral=True)

        ws = get_worksheet()

        if not is_signup_open(ws):
            return await interaction.response.send_message("Die Anmeldephase ist vorbei.", ephemeral=True)

        missing = [f for f in ["league", "cup", "restream", "commentary", "tracker"] if getattr(self, f) is None]
        if missing:
            return await interaction.response.send_message("Bitte alles ausfüllen.", ephemeral=True)

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


# =========================================================
# COG
# =========================================================

class SignupCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="switchsignup")
    async def switchsignup(self, interaction: discord.Interaction):
        member = interaction.user

        if not isinstance(member, discord.Member):
            return await interaction.response.send_message("Nur Server.", ephemeral=True)

        roles = [r.name for r in member.roles]
        if not (member.guild_permissions.administrator or any(r in ADMIN_ROLE_NAMES for r in roles)):
            return await interaction.response.send_message("Keine Rechte.", ephemeral=True)

        ws = get_worksheet()

        current = (ws.acell("A2").value or "").strip().lower()
        new = "Closed" if current == "open" else "Open"

        ws.update("A2", new)

        await interaction.response.send_message(f"Status: {new}", ephemeral=True)

    @app_commands.command(name="signup")
    async def signup(self, interaction: discord.Interaction):
        member = interaction.user

        if not isinstance(member, discord.Member):
            return await interaction.response.send_message("Nur Server.", ephemeral=True)

        ws = get_worksheet()

        if not is_signup_open(ws):
            return await interaction.response.send_message("Die Anmeldephase ist vorbei.", ephemeral=True)

        name = member.display_name

        view = SignupView(member.id, name)

        await interaction.response.send_message(
            f"Anmeldung für **{name}**",
            view=view,
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(SignupCog(bot))
