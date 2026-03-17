import os
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
import gspread
from discord import app_commands
from discord.ext import commands
from google.oauth2.service_account import Credentials

# =========================
# ANPASSEN
# =========================
GUILD_ID = 123456789012345678  # <-- deine Server-ID
CUP_SPREADSHEET_NAME = "TFL Cup"
CUP_WORKSHEET_NAME = "TFL Cup"  # Falls der Tabellen-Tab anders heißt, hier ändern
TIMEZONE = ZoneInfo("Europe/Berlin")

# Falls du lieber ein anderes Datumsformat in Spalte E willst:
DATETIME_FORMAT = "%d.%m.%Y %H:%M"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


# =========================
# GOOGLE SHEETS
# =========================
def get_gspread_client() -> gspread.Client:
    """
    Unterstützt entweder:
    - Env-Variable GOOGLE_CREDENTIALS_JSON
    - oder lokale Datei credentials.json
    """
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")

    if creds_json:
        info = json.loads(creds_json)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)

    return gspread.authorize(creds)


def get_cup_worksheet():
    client = get_gspread_client()
    spreadsheet = client.open(CUP_SPREADSHEET_NAME)

    try:
        return spreadsheet.worksheet(CUP_WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        return spreadsheet.sheet1


# =========================
# HILFSFUNKTIONEN
# =========================
def normalize_text(value: str) -> str:
    return (value or "").strip()


def get_round_label(raw_round: str) -> str:
    round_text = normalize_text(raw_round)
    return round_text if round_text else "Unbekannte Runde"


def get_mode_from_round(raw_round: str) -> str:
    """
    Empfehlung:
    In Spalte A steht die Runde, z. B.
    Achtelfinale, Viertelfinale, Halbfinale, Finale
    """
    round_text = normalize_text(raw_round).lower()

    if "halbfinale" in round_text or "finale" in round_text:
        return "Best of 3"

    return "Best of 1"


def is_finished_result(result_text: str, mode: str) -> bool:
    result = normalize_text(result_text).replace(" ", "")

    if mode == "Best of 1":
        return result in {"1-0", "0-1"}

    if mode == "Best of 3":
        return result in {"2-0", "2-1", "1-2", "0-2"}

    return False


def validate_result_for_mode(result_text: str, mode: str) -> bool:
    result = normalize_text(result_text).replace(" ", "")

    if mode == "Best of 1":
        return result in {"1-0", "0-1"}

    if mode == "Best of 3":
        return result in {"2-0", "2-1", "1-2", "0-2"}

    return False


def parse_datetime(date_text: str, time_text: str) -> datetime:
    """
    Erlaubt:
    Datum: 17.03.2026
    Uhrzeit: 20:00
    """
    combined = f"{date_text.strip()} {time_text.strip()}"
    dt = datetime.strptime(combined, "%d.%m.%Y %H:%M")
    return dt.replace(tzinfo=TIMEZONE)


def truncate(text: str, max_len: int) -> str:
    text = text or ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def load_open_matches():
    """
    Erwartete Spalten:
    A = Runde
    B = Spieler 1
    C = Ergebnis
    D = Spieler 2
    E = Datum/Uhrzeit
    """
    ws = get_cup_worksheet()
    values = ws.get_all_values()

    matches = []

    # Zeile 1 = Header
    for row_index, row in enumerate(values[1:], start=2):
        round_text = row[0] if len(row) > 0 else ""
        player1 = row[1] if len(row) > 1 else ""
        result = row[2] if len(row) > 2 else ""
        player2 = row[3] if len(row) > 3 else ""
        date_value = row[4] if len(row) > 4 else ""

        player1 = normalize_text(player1)
        player2 = normalize_text(player2)
        result = normalize_text(result)
        round_label = get_round_label(round_text)
        mode = get_mode_from_round(round_text)

        if not player1 or not player2:
            continue

        if is_finished_result(result, mode):
            continue

        matches.append(
            {
                "row": row_index,
                "round": round_label,
                "mode": mode,
                "player1": player1,
                "player2": player2,
                "result": result,
                "date_value": date_value,
            }
        )

    return matches


# =========================
# MODALS
# =========================
class CupTerminModal(discord.ui.Modal, title="Cuptermin eintragen"):
    datum = discord.ui.TextInput(
        label="Datum",
        placeholder="z. B. 17.03.2026",
        required=True,
        max_length=10,
    )

    uhrzeit = discord.ui.TextInput(
        label="Uhrzeit",
        placeholder="z. B. 20:00",
        required=True,
        max_length=5,
    )

    def __init__(self, match_data: dict):
        super().__init__()
        self.match_data = match_data

    async def on_submit(self, interaction: discord.Interaction):
        try:
            start_dt = parse_datetime(str(self.datum), str(self.uhrzeit))
        except ValueError:
            await interaction.response.send_message(
                "Ungültiges Format. Datum: TT.MM.JJJJ | Uhrzeit: HH:MM",
                ephemeral=True,
            )
            return

        if interaction.guild is None:
            await interaction.response.send_message(
                "Der Befehl funktioniert nur auf dem Server.",
                ephemeral=True,
            )
            return

        event_name = (
            f"TFL Cup | {self.match_data['player1']} vs. {self.match_data['player2']} | "
            f"{self.match_data['round']} | {self.match_data['mode']}"
        )
        event_name = truncate(event_name, 100)

        description = (
            f"Begegnung: {self.match_data['player1']} vs. {self.match_data['player2']}\n"
            f"Runde: {self.match_data['round']}\n"
            f"Modus: {self.match_data['mode']}"
        )

        # Für externe Events ist eine Endzeit Pflicht.
        end_dt = start_dt + timedelta(hours=2)

        try:
            event = await interaction.guild.create_scheduled_event(
                name=event_name,
                description=description,
                start_time=start_dt,
                end_time=end_dt,
                entity_type=discord.EntityType.external,
                privacy_level=discord.PrivacyLevel.guild_only,
                location="Discord-Server",
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "Ich darf kein Server-Event erstellen. Rechte prüfen: Events verwalten.",
                ephemeral=True,
            )
            return
        except Exception as e:
            await interaction.response.send_message(
                f"Event konnte nicht erstellt werden: {e}",
                ephemeral=True,
            )
            return

        try:
            ws = get_cup_worksheet()
            ws.update_cell(self.match_data["row"], 5, start_dt.strftime(DATETIME_FORMAT))
        except Exception as e:
            await interaction.response.send_message(
                f"Event wurde erstellt, aber Spalte E konnte nicht geschrieben werden: {e}",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Termin gespeichert und Event erstellt:\n{event.name}\n{start_dt.strftime(DATETIME_FORMAT)}",
            ephemeral=True,
        )


class CupResultModal(discord.ui.Modal, title="Cupresult eintragen"):
    ergebnis = discord.ui.TextInput(
        label="Ergebnis",
        placeholder="BO1: 1-0 oder 0-1 | BO3: 2-0, 2-1, 1-2, 0-2",
        required=True,
        max_length=5,
    )

    def __init__(self, match_data: dict):
        super().__init__()
        self.match_data = match_data

    async def on_submit(self, interaction: discord.Interaction):
        result_text = normalize_text(str(self.ergebnis)).replace(" ", "")

        if not validate_result_for_mode(result_text, self.match_data["mode"]):
            await interaction.response.send_message(
                f"Ungültiges Ergebnis für {self.match_data['mode']}.",
                ephemeral=True,
            )
            return

        try:
            ws = get_cup_worksheet()
            ws.update_cell(self.match_data["row"], 3, result_text)
        except Exception as e:
            await interaction.response.send_message(
                f"Ergebnis konnte nicht gespeichert werden: {e}",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            (
                f"Ergebnis gespeichert:\n"
                f"{self.match_data['player1']} vs. {self.match_data['player2']} → {result_text}"
            ),
            ephemeral=True,
        )


# =========================
# SELECTS / VIEWS
# =========================
class CupTerminSelect(discord.ui.Select):
    def __init__(self, matches: list[dict]):
        self.matches_by_row = {str(m["row"]): m for m in matches}

        options = []
        for match in matches[:25]:
            label = truncate(f"{match['player1']} vs. {match['player2']}", 100)
            description = truncate(f"{match['round']} | {match['mode']}", 100)

            options.append(
                discord.SelectOption(
                    label=label,
                    description=description,
                    value=str(match["row"]),
                )
            )

        super().__init__(
            placeholder="Spiel auswählen...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        selected_row = self.values[0]
        match_data = self.matches_by_row[selected_row]
        await interaction.response.send_modal(CupTerminModal(match_data))


class CupTerminView(discord.ui.View):
    def __init__(self, matches: list[dict]):
        super().__init__(timeout=120)
        self.add_item(CupTerminSelect(matches))


class CupResultSelect(discord.ui.Select):
    def __init__(self, matches: list[dict]):
        self.matches_by_row = {str(m["row"]): m for m in matches}

        options = []
        for match in matches[:25]:
            label = truncate(f"{match['player1']} vs. {match['player2']}", 100)
            description = truncate(f"{match['round']} | {match['mode']}", 100)

            options.append(
                discord.SelectOption(
                    label=label,
                    description=description,
                    value=str(match["row"]),
                )
            )

        super().__init__(
            placeholder="Spiel auswählen...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        selected_row = self.values[0]
        match_data = self.matches_by_row[selected_row]
        await interaction.response.send_modal(CupResultModal(match_data))


class CupResultView(discord.ui.View):
    def __init__(self, matches: list[dict]):
        super().__init__(timeout=120)
        self.add_item(CupResultSelect(matches))


# =========================
# COG
# =========================
class Schedule(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="cuptermin",
        description="Termin für ein offenes TFL-Cup-Spiel setzen"
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def cuptermin(self, interaction: discord.Interaction):
        try:
            matches = load_open_matches()
        except Exception as e:
            await interaction.response.send_message(
                f"Tabelle konnte nicht geladen werden: {e}",
                ephemeral=True,
            )
            return

        if not matches:
            await interaction.response.send_message(
                "Keine offenen Cup-Spiele gefunden.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "Wähle das Spiel aus:",
            view=CupTerminView(matches),
            ephemeral=True,
        )

    @app_commands.command(
        name="cupresult",
        description="Ergebnis für ein offenes TFL-Cup-Spiel eintragen"
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def cupresult(self, interaction: discord.Interaction):
        try:
            matches = load_open_matches()
        except Exception as e:
            await interaction.response.send_message(
                f"Tabelle konnte nicht geladen werden: {e}",
                ephemeral=True,
            )
            return

        if not matches:
            await interaction.response.send_message(
                "Keine offenen Cup-Spiele gefunden.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "Wähle das Spiel aus:",
            view=CupResultView(matches),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Schedule(bot))
