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
GOOGLE_CREDENTIALS_FILE = "credentials.json"

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


class ToggleButton(discord.ui.Button):
    def __init__(self, field_name: str, label_name: str, row: int):
        super().__init__(
            label=f"{label_name}: Nein",
            style=discord.ButtonStyle.secondary,
            row=row
        )
        self.field_name = field_name
        self.label_name = label_name

    async def callback(self, interaction: discord.Interaction):
        view = self.view

        current_value = getattr(view, self.field_name)
        new_value = "Ja" if current_value == "Nein" else "Nein"
        setattr(view, self.field_name, new_value)

        self.label = f"{self.label_name}: {new_value}"
        self.style = (
            discord.ButtonStyle.success
            if new_value == "Ja"
            else discord.ButtonStyle.secondary
        )

        await interaction.response.edit_message(view=view)


class SignupView(discord.ui.View):
    def __init__(self, user_id, name):
        super().__init__(timeout=600)

        self.user_id = user_id
        self.name = name

        self.twitch = ""
        self.league = "Nein"
        self.cup = "Nein"
        self.restream = "Nein"
        self.commentary = "Nein"
        self.tracker = "Nein"

        self.add_item(ToggleButton("league", "League", 0))
        self.add_item(ToggleButton("cup", "Cup", 0))
        self.add_item(ToggleButton("restream", "Restream", 0))
        self.add_item(ToggleButton("commentary", "Commentary", 0))
        self.add_item(ToggleButton("tracker", "Tracker", 0))

    @discord.ui.button(label="Twitch setzen", style=discord.ButtonStyle.primary, row=1)
    async def twitch_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TwitchModal(self))

    @discord.ui.button(label="Absenden", style=discord.ButtonStyle.success, row=1)
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Nicht dein Formular.", ephemeral=True)
            return

        try:
            await interaction.response.defer(ephemeral=True)

            ws = get_worksheet()

            if not is_signup_open(ws):
                await interaction.followup.send(
                    "Die Anmeldephase ist vorbei.",
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

            await interaction.followup.send(result, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(
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

    @app_commands.command(
    name="signstat",
    description="Zeigt deinen Eintrag."
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def signstat(self, interaction: discord.Interaction):
        member = interaction.user

        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "Nur Server.",
                ephemeral=True
            )
        return

    await interaction.response.defer(ephemeral=True)

    try:
        ws = get_worksheet()
        name = member.display_name.strip()
        row = find_name_row(ws, name)

        if row is None:
            await interaction.followup.send(
                "Es wurde kein Eintrag mit deinem Namen gefunden.",
                ephemeral=True
            )
        return

        values = ws.row_values(row)

            await interaction.followup.send(
            f"Dein Eintrag wurde gefunden: Zeile {row}\n```{values}```",
            ephemeral=True
        )

    except Exception as e:
        await interaction.followup.send(
            f"Fehler beim Abrufen deines Eintrags: {e}",
            ephemeral=True
        )
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
