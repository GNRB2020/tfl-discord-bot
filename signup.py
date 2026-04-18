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


def normalize_yes_no(value: str) -> str:
    return "Ja" if (value or "").strip().lower() == "ja" else "Nein"


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


def get_existing_signup_data(ws, name: str) -> dict:
    row = find_name_row(ws, name)

    if row is None:
        return {
            "twitch": "",
            "league": "Nein",
            "cup": "Nein",
            "restream": "Nein",
            "commentary": "Nein",
            "tracker": "Nein",
        }

    values = get_row_values(ws, row)

    return {
        "twitch": values[1].strip(),
        "league": normalize_yes_no(values[2]),
        "cup": normalize_yes_no(values[3]),
        "restream": normalize_yes_no(values[4]),
        "commentary": normalize_yes_no(values[5]),
        "tracker": normalize_yes_no(values[6]),
    }


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


def has_admin_role(member: discord.Member) -> bool:
    return any(role.name in ADMIN_ROLE_NAMES for role in member.roles)


# =========================================================
# HELFER FÜR PLAYER.PY
# =========================================================
def get_signup_status_text_for_member(member: discord.Member) -> str:
    ws = get_worksheet()
    name = member.display_name.strip()
    row = find_name_row(ws, name)

    if row is None:
        return "Es wurde kein Eintrag mit deinem Namen gefunden."

    values = get_row_values(ws, row)
    return format_signup_row(values)


def get_league_signup_text() -> str:
    ws = get_worksheet()
    names = get_names_by_column_value(ws, 3, "Ja")

    if not names:
        return "Keine League-Anmeldungen."

    return "\n".join(names)


def get_cup_signup_text() -> str:
    ws = get_worksheet()
    names = get_names_by_column_value(ws, 4, "Ja")

    if not names:
        return "Keine Cup-Anmeldungen."

    return "\n".join(names)


async def open_signup_from_player(interaction: discord.Interaction):
    member = interaction.user

    if not isinstance(member, discord.Member):
        await interaction.response.send_message("Nur Server.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    try:
        ws = get_worksheet()

        if not is_signup_open(ws):
            await interaction.edit_original_response(
                content="Die Anmeldephase ist vorbei.",
                view=None,
            )
            return

        existing_data = get_existing_signup_data(ws, member.display_name.strip())

        view = SignupView(
            member.id,
            member.display_name.strip(),
            initial_data=existing_data
        )

        await interaction.edit_original_response(
            content=f"Anmeldung für **{member.display_name}**",
            view=view,
        )

    except Exception as e:
        await interaction.edit_original_response(
            content=f"Fehler beim Laden der Anmeldung: {e}",
            view=None,
        )


# =========================================================
# UI
# =========================================================
class TwitchModal(discord.ui.Modal, title="Twitchkanal"):
    twitch = discord.ui.TextInput(label="Twitchkanal", required=False)

    def __init__(self, view):
        super().__init__()
        self.view_ref = view
        self.twitch.default = view.twitch

    async def on_submit(self, interaction: discord.Interaction):
        self.view_ref.twitch = str(self.twitch.value).strip()
        await interaction.response.send_message("Twitch gesetzt.", ephemeral=True)


class ToggleButton(discord.ui.Button):
    def __init__(self, field_name: str, label_name: str, row: int):
        super().__init__(
            label=label_name,
            style=discord.ButtonStyle.secondary,
            row=row
        )
        self.field_name = field_name
        self.label_name = label_name

    def sync_state(self, view):
        current_value = getattr(view, self.field_name, "Nein")
        self.label = f"{self.label_name}: {current_value}"
        self.style = (
            discord.ButtonStyle.success
            if current_value == "Ja"
            else discord.ButtonStyle.secondary
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view

        if not isinstance(view, SignupView):
            await interaction.response.send_message("Fehler: Ungültige View.", ephemeral=True)
            return

        if interaction.user.id != view.user_id:
            await interaction.response.send_message("Nicht dein Formular.", ephemeral=True)
            return

        current_value = getattr(view, self.field_name)
        new_value = "Ja" if current_value == "Nein" else "Nein"
        setattr(view, self.field_name, new_value)

        self.sync_state(view)
        await interaction.response.edit_message(view=view)


class SignupView(discord.ui.View):
    def __init__(self, user_id, name, initial_data: Optional[dict] = None):
        super().__init__(timeout=600)

        self.user_id = user_id
        self.name = name

        initial_data = initial_data or {}

        self.twitch = initial_data.get("twitch", "")
        self.league = normalize_yes_no(initial_data.get("league", "Nein"))
        self.cup = normalize_yes_no(initial_data.get("cup", "Nein"))
        self.restream = normalize_yes_no(initial_data.get("restream", "Nein"))
        self.commentary = normalize_yes_no(initial_data.get("commentary", "Nein"))
        self.tracker = normalize_yes_no(initial_data.get("tracker", "Nein"))

        league_btn = ToggleButton("league", "League", 0)
        cup_btn = ToggleButton("cup", "Cup", 0)
        restream_btn = ToggleButton("restream", "Restream", 0)
        commentary_btn = ToggleButton("commentary", "Commentary", 0)
        tracker_btn = ToggleButton("tracker", "Tracker", 0)

        for btn in [league_btn, cup_btn, restream_btn, commentary_btn, tracker_btn]:
            btn.sync_state(self)
            self.add_item(btn)

    @discord.ui.button(label="Twitch setzen", style=discord.ButtonStyle.primary, row=1)
    async def twitch_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Nicht dein Formular.", ephemeral=True)
            return

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

        await interaction.response.defer(ephemeral=True)

        try:
            ws = get_worksheet()

            if not is_signup_open(ws):
                await interaction.followup.send(
                    "Die Anmeldephase ist vorbei.",
                    ephemeral=True
                )
                return

            existing_data = get_existing_signup_data(ws, member.display_name.strip())

            view = SignupView(
                member.id,
                member.display_name.strip(),
                initial_data=existing_data
            )

            await interaction.followup.send(
                f"Anmeldung für **{member.display_name}**",
                view=view,
                ephemeral=True
            )

        except Exception as e:
            await interaction.followup.send(
                f"Fehler beim Laden der Anmeldung: {e}",
                ephemeral=True
            )

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

            values = get_row_values(ws, row)

            await interaction.followup.send(
                format_signup_row(values),
                ephemeral=True
            )

        except Exception as e:
            await interaction.followup.send(
                f"Fehler beim Abrufen deines Eintrags: {e}",
                ephemeral=True
            )

    @app_commands.command(name="leaguesign", description="Zeigt alle League-Anmeldungen")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def leaguesign(self, interaction: discord.Interaction):
        ws = get_worksheet()
        names = get_names_by_column_value(ws, 3, "Ja")

        if not names:
            await interaction.response.send_message("Keine League-Anmeldungen.", ephemeral=True)
            return

        await interaction.response.send_message("\n".join(names), ephemeral=True)

    @app_commands.command(name="cupsign", description="Zeigt alle Cup-Anmeldungen")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def cupsign(self, interaction: discord.Interaction):
        ws = get_worksheet()
        names = get_names_by_column_value(ws, 4, "Ja")

        if not names:
            await interaction.response.send_message("Keine Cup-Anmeldungen.", ephemeral=True)
            return

        await interaction.response.send_message("\n".join(names), ephemeral=True)

    @app_commands.command(name="resetsign", description="Setzt alle Signups zurück")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def resetsign(self, interaction: discord.Interaction):
        member = interaction.user

        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Nur Server.", ephemeral=True)
            return

        if not has_admin_role(member):
            await interaction.response.send_message(
                "Dafür fehlen dir die Rechte.",
                ephemeral=True
            )
            return

        ws = get_worksheet()
        count = reset_signup_data(ws)
        await interaction.response.send_message(
            f"{count} Einträge zurückgesetzt.",
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(SignupCog(bot), guild=discord.Object(id=GUILD_ID))
