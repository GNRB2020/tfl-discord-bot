import os
import asyncio
import discord
import gspread
from discord import app_commands
from discord.ext import commands
from oauth2client.service_account import ServiceAccountCredentials

from signup import (
    get_signup_status_text_for_member,
    get_league_signup_text,
    get_cup_signup_text,
    get_worksheet,
    get_existing_signup_data,
    normalize_yes_no,
    find_name_row,
    find_free_row,
    write_row,
    open_signup_from_player,
)

from asnyc import (
    get_quali_worksheet,
    get_quali_stats_for_runner,
    get_overall_stats_for_runner,
    open_quali_from_player,
)

from restinfo import (
    list_rest_players,
    format_restprogramm_text,
    get_open_restprogramm_text_for_name_candidates,
)

from streichinfo import (
    format_streichungen_text,
    get_own_division_streich_text,
)

from plan import PlanMenuView
from matchcenter import get_runner_modes

GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))

SETTINGS_SPREADSHEET_ID = "1pZxg1_DUtbO4dZvX95ZrIqEZnkMc1MjmE7z5SEsMHQU"
SETTINGS_STREICH_GID = 2118667264
SETTINGS_CREDS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
SETTINGS_SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]


# =========================================================
# Hilfsfunktionen
# =========================================================
async def build_quali_info_text(member: discord.Member, quali_number: int) -> str:
    runner_name = member.display_name.strip()
    ws = await asyncio.to_thread(get_quali_worksheet)
    total_played, rank = await asyncio.to_thread(
        get_quali_stats_for_runner,
        ws,
        runner_name,
        quali_number
    )

    if rank is None:
        return (
            f"**Stand Quali {quali_number}**\n\n"
            f"Bereits gespielt: **{total_played}**\n"
            f"Du hast Quali {quali_number} aktuell noch nicht abgeschlossen."
        )

    return (
        f"**Stand Quali {quali_number}**\n\n"
        f"Bereits gespielt: **{total_played}**\n"
        f"Dein aktueller Platz: **{rank}/{total_played}**"
    )


async def build_quali_overall_text(member: discord.Member) -> str:
    runner_name = member.display_name.strip()
    ws = await asyncio.to_thread(get_quali_worksheet)
    total_completed, rank = await asyncio.to_thread(
        get_overall_stats_for_runner,
        ws,
        runner_name
    )

    if rank is None:
        return (
            f"**Gesamtstand**\n\n"
            f"Beide Qualis abgeschlossen: **{total_completed}**\n"
            f"Du bist aktuell noch nicht im Gesamtstand, weil dir mindestens eine Quali fehlt."
        )

    return (
        f"**Gesamtstand**\n\n"
        f"Beide Qualis abgeschlossen: **{total_completed}**\n"
        f"Dein aktueller Platz: **{rank}/{total_completed}**"
    )


def normalize_settings_name(value: str) -> str:
    return (
        (value or "")
        .strip()
        .lower()
        .replace("_", "")
        .replace("-", "")
        .replace(" ", "")
    )


def ensure_signup_row_for_member(member: discord.Member) -> int:
    ws = get_worksheet()
    name = member.display_name.strip()

    row = find_name_row(ws, name)
    if row is not None:
        return row

    existing = get_existing_signup_data(ws, name)
    row = find_free_row(ws)

    write_row(
        ws,
        row,
        name,
        existing.get("twitch", ""),
        existing.get("league", "Nein"),
        existing.get("cup", "Nein"),
        existing.get("restream", "Nein"),
        existing.get("commentary", "Nein"),
        existing.get("tracker", "Nein"),
    )
    return row


def update_member_twitch(member: discord.Member, twitch_value: str):
    ws = get_worksheet()
    row = ensure_signup_row_for_member(member)
    ws.update_cell(row, 2, twitch_value.strip())


def update_member_restream_settings(
    member: discord.Member,
    restream: str,
    commentary: str,
    tracker: str,
):
    ws = get_worksheet()
    row = ensure_signup_row_for_member(member)

    ws.update(
        f"E{row}:G{row}",
        [[
            normalize_yes_no(restream),
            normalize_yes_no(commentary),
            normalize_yes_no(tracker),
        ]]
    )


def get_settings_spreadsheet_client() -> gspread.Client:
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        SETTINGS_CREDS_FILE,
        SETTINGS_SCOPE
    )
    return gspread.authorize(creds)


def get_streich_settings_worksheet():
    client = get_settings_spreadsheet_client()
    spreadsheet = client.open_by_key(SETTINGS_SPREADSHEET_ID)

    for ws in spreadsheet.worksheets():
        if ws.id == SETTINGS_STREICH_GID:
            return ws

    raise RuntimeError(f"Worksheet mit gid/id {SETTINGS_STREICH_GID} nicht gefunden.")


def find_streich_row_for_member(ws, name_candidates: list[str]) -> int | None:
    targets = {normalize_settings_name(x) for x in name_candidates if x}
    rows = ws.get_all_values()

    for idx, row in enumerate(rows, start=1):
        name_in_l = row[11].strip() if len(row) > 11 else ""
        if normalize_settings_name(name_in_l) in targets:
            return idx

    return None


def set_member_streichmodi(name_candidates: list[str], mode_1: str, mode_2: str):
    ws = get_streich_settings_worksheet()
    row = find_streich_row_for_member(ws, name_candidates)

    if row is None:
        raise RuntimeError("Kein Eintrag für den Spieler in Spalte L gefunden.")

    ws.update(
        f"M{row}:N{row}",
        [[mode_1.strip(), mode_2.strip()]]
    )


# =========================================================
# Basis-View
# =========================================================
class PlayerBaseView(discord.ui.View):
    def __init__(self, owner_id: int, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Dieses Menü gehört nicht dir.",
                ephemeral=True
            )
            return False
        return True


# =========================================================
# Allgemeine Detailansicht mit Zurück
# =========================================================
class PlaceholderView(PlayerBaseView):
    def __init__(self, owner_id: int, back_view: discord.ui.View, back_content: str):
        super().__init__(owner_id)
        self.back_view = back_view
        self.back_content = back_content

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=0)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content=self.back_content,
            view=self.back_view
        )


# =========================================================
# Hauptmenü
# =========================================================
class PlayerMenuView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="Info", style=discord.ButtonStyle.secondary, row=0)
    async def info_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Info**\nWähle einen Bereich:",
            view=InfoMenuView(owner_id=interaction.user.id)
        )

    @discord.ui.button(label="Spiel planen", style=discord.ButtonStyle.primary, row=0)
    async def plan_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spiel planen**\nWähle einen Bereich:",
            view=PlanMenuView(owner_id=interaction.user.id)
        )

    @discord.ui.button(label="Ergebnis melden", style=discord.ButtonStyle.success, row=0)
    async def result_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Ergebnis melden**\nHier kommt später die Navigation rein.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=PlayerMenuView(owner_id=interaction.user.id),
                back_content="**Spielermenü**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Qualifikation", style=discord.ButtonStyle.secondary, row=1)
    async def qualification_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_quali_from_player(interaction)

    @discord.ui.button(label="Saisonmeldung", style=discord.ButtonStyle.secondary, row=1)
    async def season_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_signup_from_player(interaction)

    @discord.ui.button(label="Einstellungen", style=discord.ButtonStyle.secondary, row=1)
    async def settings_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Einstellungen**\nWähle einen Bereich:",
            view=SettingsMenuView(owner_id=interaction.user.id)
        )


# =========================================================
# Info-Menü
# =========================================================
class InfoMenuView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="Meldestatus", style=discord.ButtonStyle.primary, row=0)
    async def meldestatus_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Meldestatus**\nWähle einen Bereich:",
            view=MeldestatusView(owner_id=interaction.user.id)
        )

    @discord.ui.button(label="Qualifikation", style=discord.ButtonStyle.primary, row=0)
    async def qualifikation_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Qualifikation**\nWähle einen Bereich:",
            view=InfoQualifikationView(owner_id=interaction.user.id)
        )

    @discord.ui.button(label="Restprogramm", style=discord.ButtonStyle.primary, row=1)
    async def restprogramm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Restprogramm**\nWähle einen Bereich:",
            view=RestprogrammView(owner_id=interaction.user.id)
        )

    @discord.ui.button(label="Streichmodus", style=discord.ButtonStyle.primary, row=1)
    async def streichmodus_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Streichmodus**\nWähle einen Bereich:",
            view=StreichmodusView(owner_id=interaction.user.id)
        )

    @discord.ui.button(label="Ergebnisse/Tabelle", style=discord.ButtonStyle.primary, row=2)
    async def ergebnisse_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Ergebnisse/Tabelle**\nWähle eine Liga oder den Cup:",
            view=ErgebnisseTabelleView(owner_id=interaction.user.id)
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=3)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü**\nWähle einen Bereich:",
            view=PlayerMenuView(owner_id=interaction.user.id)
        )


# =========================================================
# Meldestatus
# =========================================================
class MeldestatusView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="Meiner", style=discord.ButtonStyle.primary, row=0)
    async def meiner_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member):
            text = "Nur auf dem Server verfügbar."
        else:
            try:
                text = get_signup_status_text_for_member(member)
            except Exception as e:
                text = f"Fehler beim Abrufen deines Eintrags: {e}"

        await interaction.response.edit_message(
            content=f"**Info → Meldestatus → Meiner**\n{text}",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=MeldestatusView(owner_id=interaction.user.id),
                back_content="**Info → Meldestatus**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="League", style=discord.ButtonStyle.primary, row=0)
    async def league_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            text = get_league_signup_text()
        except Exception as e:
            text = f"Fehler beim Abrufen der League-Anmeldungen: {e}"

        await interaction.response.edit_message(
            content=f"**Info → Meldestatus → League**\n{text}",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=MeldestatusView(owner_id=interaction.user.id),
                back_content="**Info → Meldestatus**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Cup", style=discord.ButtonStyle.primary, row=0)
    async def cup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            text = get_cup_signup_text()
        except Exception as e:
            text = f"Fehler beim Abrufen der Cup-Anmeldungen: {e}"

        await interaction.response.edit_message(
            content=f"**Info → Meldestatus → Cup**\n{text}",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=MeldestatusView(owner_id=interaction.user.id),
                back_content="**Info → Meldestatus**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Info**\nWähle einen Bereich:",
            view=InfoMenuView(owner_id=interaction.user.id)
        )


# =========================================================
# Info -> Qualifikation
# =========================================================
class InfoQualifikationView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="Quali 1", style=discord.ButtonStyle.primary, row=0)
    async def quali1_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member):
            text = "Nur auf dem Server verfügbar."
        else:
            try:
                await interaction.response.defer()
                text = await build_quali_info_text(member, 1)
                await interaction.edit_original_response(
                    content=f"**Info → Qualifikation → Quali 1**\n{text}",
                    view=PlaceholderView(
                        owner_id=interaction.user.id,
                        back_view=InfoQualifikationView(owner_id=interaction.user.id),
                        back_content="**Info → Qualifikation**\nWähle einen Bereich:"
                    )
                )
                return
            except Exception as e:
                text = f"Fehler bei Quali 1: {e}"

        await interaction.response.edit_message(
            content=f"**Info → Qualifikation → Quali 1**\n{text}",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=InfoQualifikationView(owner_id=interaction.user.id),
                back_content="**Info → Qualifikation**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Quali 2", style=discord.ButtonStyle.primary, row=0)
    async def quali2_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member):
            text = "Nur auf dem Server verfügbar."
        else:
            try:
                await interaction.response.defer()
                text = await build_quali_info_text(member, 2)
                await interaction.edit_original_response(
                    content=f"**Info → Qualifikation → Quali 2**\n{text}",
                    view=PlaceholderView(
                        owner_id=interaction.user.id,
                        back_view=InfoQualifikationView(owner_id=interaction.user.id),
                        back_content="**Info → Qualifikation**\nWähle einen Bereich:"
                    )
                )
                return
            except Exception as e:
                text = f"Fehler bei Quali 2: {e}"

        await interaction.response.edit_message(
            content=f"**Info → Qualifikation → Quali 2**\n{text}",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=InfoQualifikationView(owner_id=interaction.user.id),
                back_content="**Info → Qualifikation**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Gesamt", style=discord.ButtonStyle.primary, row=0)
    async def gesamt_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member):
            text = "Nur auf dem Server verfügbar."
        else:
            try:
                await interaction.response.defer()
                text = await build_quali_overall_text(member)
                await interaction.edit_original_response(
                    content=f"**Info → Qualifikation → Gesamt**\n{text}",
                    view=PlaceholderView(
                        owner_id=interaction.user.id,
                        back_view=InfoQualifikationView(owner_id=interaction.user.id),
                        back_content="**Info → Qualifikation**\nWähle einen Bereich:"
                    )
                )
                return
            except Exception as e:
                text = f"Fehler beim Gesamtstand: {e}"

        await interaction.response.edit_message(
            content=f"**Info → Qualifikation → Gesamt**\n{text}",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=InfoQualifikationView(owner_id=interaction.user.id),
                back_content="**Info → Qualifikation**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Info**\nWähle einen Bereich:",
            view=InfoMenuView(owner_id=interaction.user.id)
        )


# =========================================================
# Restprogramm - Andere
# =========================================================
class RestOtherPlayerSelect(discord.ui.Select):
    def __init__(self, division: str, players: list[str], owner_id: int):
        self.division = division
        self.owner_id = owner_id

        options = [discord.SelectOption(label=p, value=p) for p in players[:25]]

        super().__init__(
            placeholder="Spieler wählen …",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        player = self.values[0]

        await interaction.response.defer()

        try:
            text = await asyncio.to_thread(format_restprogramm_text, self.division, player)
        except Exception as e:
            text = f"Fehler beim Ermitteln des Restprogramms: {e}"

        await interaction.edit_original_response(
            content=text,
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=RestOtherDivisionView(owner_id=interaction.user.id),
                back_content="**Info → Restprogramm → Andere**\nWähle eine Division:"
            )
        )


class RestOtherPlayerView(PlayerBaseView):
    def __init__(self, owner_id: int, division: str, players: list[str]):
        super().__init__(owner_id)
        self.add_item(RestOtherPlayerSelect(division, players, owner_id))

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Restprogramm → Andere**\nWähle eine Division:",
            view=RestOtherDivisionView(owner_id=interaction.user.id)
        )


class RestOtherDivisionSelect(discord.ui.Select):
    def __init__(self, owner_id: int):
        self.owner_id = owner_id
        options = [
            discord.SelectOption(label="Division 1", value="1"),
            discord.SelectOption(label="Division 2", value="2"),
            discord.SelectOption(label="Division 3", value="3"),
            discord.SelectOption(label="Division 4", value="4"),
            discord.SelectOption(label="Division 5", value="5"),
            discord.SelectOption(label="Division 6", value="6"),
        ]
        super().__init__(
            placeholder="Division wählen …",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        div_number = self.values[0]

        await interaction.response.defer()

        try:
            players = await asyncio.to_thread(list_rest_players, div_number)
        except Exception as e:
            await interaction.edit_original_response(
                content=f"❌ Fehler beim Laden der Spieler für Division {div_number}: {e}",
                view=RestOtherDivisionView(owner_id=interaction.user.id)
            )
            return

        if not players:
            await interaction.edit_originalResponse(
                content=f"Keine Spieler in Division {div_number} für das Restprogramm gefunden.",
                view=RestOtherDivisionView(owner_id=interaction.user.id)
            )
            return

        await interaction.edit_original_response(
            content=f"**Info → Restprogramm → Andere**\nDivision {div_number} gewählt. Bitte Spieler wählen:",
            view=RestOtherPlayerView(
                owner_id=interaction.user.id,
                division=div_number,
                players=players
            )
        )


class RestOtherDivisionView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)
        self.add_item(RestOtherDivisionSelect(owner_id))

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Restprogramm**\nWähle einen Bereich:",
            view=RestprogrammView(owner_id=interaction.user.id)
        )


# =========================================================
# Restprogramm
# =========================================================
class RestprogrammView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="Eigenes", style=discord.ButtonStyle.primary, row=0)
    async def eigenes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user

        await interaction.response.defer()

        if not isinstance(member, discord.Member):
            text = "Nur auf dem Server verfügbar."
        else:
            try:
                name_candidates = [
                    member.display_name,
                    getattr(member, "global_name", None),
                    member.name,
                ]
                text = await asyncio.to_thread(
                    get_open_restprogramm_text_for_name_candidates,
                    name_candidates
                )
            except Exception as e:
                text = f"Fehler beim Abrufen deines Restprogramms: {e}"

        await interaction.edit_original_response(
            content=f"**Info → Restprogramm → Eigenes**\n{text}",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=RestprogrammView(owner_id=interaction.user.id),
                back_content="**Info → Restprogramm**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Andere", style=discord.ButtonStyle.primary, row=0)
    async def andere_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Restprogramm → Andere**\nWähle eine Division:",
            view=RestOtherDivisionView(owner_id=interaction.user.id)
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Info**\nWähle einen Bereich:",
            view=InfoMenuView(owner_id=interaction.user.id)
        )


# =========================================================
# Streichmodus - Andere Divisionen
# =========================================================
class StreichOtherDivisionSelect(discord.ui.Select):
    def __init__(self, owner_id: int):
        self.owner_id = owner_id
        options = [
            discord.SelectOption(label="Division 1", value="1"),
            discord.SelectOption(label="Division 2", value="2"),
            discord.SelectOption(label="Division 3", value="3"),
            discord.SelectOption(label="Division 4", value="4"),
            discord.SelectOption(label="Division 5", value="5"),
            discord.SelectOption(label="Division 6", value="6"),
        ]
        super().__init__(
            placeholder="Division wählen …",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        div_number = self.values[0]

        await interaction.response.defer()

        try:
            text = await asyncio.to_thread(format_streichungen_text, div_number)
        except Exception as e:
            text = f"❌ Fehler beim Lesen der Streichungen aus Division {div_number}: {e}"

        await interaction.edit_original_response(
            content=text,
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=StreichOtherDivisionView(owner_id=interaction.user.id),
                back_content="**Info → Streichmodus → Andere Divisionen**\nWähle eine Division:"
            )
        )


class StreichOtherDivisionView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)
        self.add_item(StreichOtherDivisionSelect(owner_id))

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Streichmodus**\nWähle einen Bereich:",
            view=StreichmodusView(owner_id=interaction.user.id)
        )


# =========================================================
# Streichmodus
# =========================================================
class StreichmodusView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="Eigene Division", style=discord.ButtonStyle.primary, row=0)
    async def eigene_division_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user

        await interaction.response.defer()

        if not isinstance(member, discord.Member):
            text = "Nur auf dem Server verfügbar."
        else:
            try:
                name_candidates = [
                    member.display_name,
                    getattr(member, "global_name", None),
                    member.name,
                ]
                text = await asyncio.to_thread(
                    get_own_division_streich_text,
                    name_candidates
                )
            except Exception as e:
                text = f"Fehler beim Abrufen des Streichmodus: {e}"

        await interaction.edit_original_response(
            content=f"**Info → Streichmodus → Eigene Division**\n{text}",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=StreichmodusView(owner_id=interaction.user.id),
                back_content="**Info → Streichmodus**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Andere Divisionen", style=discord.ButtonStyle.primary, row=0)
    async def andere_divisionen_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Streichmodus → Andere Divisionen**\nWähle eine Division:",
            view=StreichOtherDivisionView(owner_id=interaction.user.id)
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Info**\nWähle einen Bereich:",
            view=InfoMenuView(owner_id=interaction.user.id)
        )


# =========================================================
# Ergebnisse / Tabelle mit Browser-Links
# =========================================================
class ErgebnisseTabelleView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

        self.add_item(discord.ui.Button(
            label="1. Div",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/1-division",
            row=0
        ))
        self.add_item(discord.ui.Button(
            label="2. Div",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/1-division-2",
            row=0
        ))
        self.add_item(discord.ui.Button(
            label="3. Div",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/3-division",
            row=0
        ))
        self.add_item(discord.ui.Button(
            label="4. Div",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/3-division-2",
            row=1
        ))
        self.add_item(discord.ui.Button(
            label="5. Div",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/3-division-3",
            row=1
        ))
        self.add_item(discord.ui.Button(
            label="6. Div",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/3-division-4",
            row=1
        ))
        self.add_item(discord.ui.Button(
            label="Cup",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/cup",
            row=2
        ))

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=3)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Info**\nWähle einen Bereich:",
            view=InfoMenuView(owner_id=interaction.user.id)
        )


# =========================================================
# Einstellungen -> Twitch setzen
# =========================================================
class TwitchSettingsModal(discord.ui.Modal, title="Twitch setzen"):
    twitch = discord.ui.TextInput(
        label="Twitchkanal",
        required=False,
        max_length=100,
    )

    def __init__(self, owner_id: int, default_value: str = ""):
        super().__init__()
        self.owner_id = owner_id
        self.twitch.default = default_value

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Dieses Menü gehört nicht dir.", ephemeral=True)
            return

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Nur auf dem Server verfügbar.", ephemeral=True)
            return

        try:
            await asyncio.to_thread(
                update_member_twitch,
                interaction.user,
                str(self.twitch.value).strip(),
            )

            await interaction.response.send_message(
                "✅ Twitch wurde gespeichert.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Fehler beim Speichern des Twitchkanals: {e}",
                ephemeral=True
            )


# =========================================================
# Einstellungen -> Restream / Commentary / Tracker
# =========================================================
class SettingsToggleButton(discord.ui.Button):
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
        if not isinstance(view, RestreamSettingsView):
            await interaction.response.send_message("Fehler: Ungültige View.", ephemeral=True)
            return

        current_value = getattr(view, self.field_name)
        new_value = "Ja" if current_value == "Nein" else "Nein"
        setattr(view, self.field_name, new_value)

        self.sync_state(view)
        await interaction.response.edit_message(
            content=view.render_text(),
            view=view
        )


class RestreamSettingsView(PlayerBaseView):
    def __init__(self, owner_id: int, restream: str, commentary: str, tracker: str):
        super().__init__(owner_id, timeout=600)

        self.restream = normalize_yes_no(restream)
        self.commentary = normalize_yes_no(commentary)
        self.tracker = normalize_yes_no(tracker)

        restream_btn = SettingsToggleButton("restream", "Restream", 0)
        commentary_btn = SettingsToggleButton("commentary", "Commentary", 0)
        tracker_btn = SettingsToggleButton("tracker", "Tracker", 0)

        for btn in [restream_btn, commentary_btn, tracker_btn]:
            btn.sync_state(self)
            self.add_item(btn)

    def render_text(self) -> str:
        return (
            "**Einstellungen → Restream**\n"
            f"Restream: **{self.restream}**\n"
            f"Commentary: **{self.commentary}**\n"
            f"Tracker: **{self.tracker}**"
        )

    @discord.ui.button(label="Absenden", style=discord.ButtonStyle.success, row=1)
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Nur auf dem Server verfügbar.", ephemeral=True)
            return

        try:
            await asyncio.to_thread(
                update_member_restream_settings,
                interaction.user,
                self.restream,
                self.commentary,
                self.tracker,
            )

            await interaction.response.edit_message(
                content="**Einstellungen → Restream**\n✅ Einstellungen gespeichert.",
                view=PlaceholderView(
                    owner_id=interaction.user.id,
                    back_view=SettingsMenuView(owner_id=interaction.user.id),
                    back_content="**Spielermenü → Einstellungen**\nWähle einen Bereich:"
                )
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Fehler beim Speichern der Einstellungen: {e}",
                ephemeral=True
            )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Einstellungen**\nWähle einen Bereich:",
            view=SettingsMenuView(owner_id=interaction.user.id)
        )


# =========================================================
# Einstellungen -> Streichmodi setzen
# =========================================================
class StreichModeSelect(discord.ui.Select):
    def __init__(self, field_name: str, modes: list[str], placeholder: str, row: int):
        self.field_name = field_name
        options = [discord.SelectOption(label=m[:100], value=m) for m in modes[:25]]

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            row=row,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, StreichSettingsView):
            return

        setattr(view, self.field_name, self.values[0])
        await interaction.response.edit_message(
            content=view.render_text(),
            view=view,
        )


class StreichSettingsView(PlayerBaseView):
    def __init__(self, owner_id: int, modes: list[str]):
        super().__init__(owner_id, timeout=600)
        self.mode_1: str | None = None
        self.mode_2: str | None = None

        self.add_item(StreichModeSelect("mode_1", modes, "Streichmodus 1 wählen …", 0))
        self.add_item(StreichModeSelect("mode_2", modes, "Streichmodus 2 wählen …", 1))

    def render_text(self) -> str:
        return (
            "**Einstellungen → Streichmodis setzen**\n"
            f"Modus 1: **{self.mode_1 or '-'}**\n"
            f"Modus 2: **{self.mode_2 or '-'}**"
        )

    @discord.ui.button(label="Absenden", style=discord.ButtonStyle.success, row=2)
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Nur auf dem Server verfügbar.", ephemeral=True)
            return

        if not self.mode_1 or not self.mode_2:
            await interaction.response.send_message(
                "Bitte beide Streichmodi auswählen.",
                ephemeral=True
            )
            return

        name_candidates = [
            interaction.user.display_name,
            getattr(interaction.user, "global_name", None),
            interaction.user.name,
        ]

        try:
            await asyncio.to_thread(
                set_member_streichmodi,
                name_candidates,
                self.mode_1,
                self.mode_2,
            )

            await interaction.response.edit_message(
                content=(
                    "**Einstellungen → Streichmodis setzen**\n"
                    "✅ Streichmodi gespeichert."
                ),
                view=PlaceholderView(
                    owner_id=interaction.user.id,
                    back_view=SettingsMenuView(owner_id=interaction.user.id),
                    back_content="**Spielermenü → Einstellungen**\nWähle einen Bereich:"
                )
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Fehler beim Speichern der Streichmodi: {e}",
                ephemeral=True
            )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=2)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Einstellungen**\nWähle einen Bereich:",
            view=SettingsMenuView(owner_id=interaction.user.id)
        )


# =========================================================
# Einstellungen-Menü
# =========================================================
class SettingsMenuView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="Twitch setzen", style=discord.ButtonStyle.primary, row=0)
    async def twitch_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Nur auf dem Server verfügbar.", ephemeral=True)
            return

        try:
            ws = await asyncio.to_thread(get_worksheet)
            existing = await asyncio.to_thread(
                get_existing_signup_data,
                ws,
                interaction.user.display_name.strip()
            )
            twitch_default = existing.get("twitch", "")
        except Exception:
            twitch_default = ""

        await interaction.response.send_modal(
            TwitchSettingsModal(
                owner_id=interaction.user.id,
                default_value=twitch_default
            )
        )

    @discord.ui.button(label="Restream", style=discord.ButtonStyle.primary, row=0)
    async def restream_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Nur auf dem Server verfügbar.", ephemeral=True)
            return

        try:
            ws = await asyncio.to_thread(get_worksheet)
            existing = await asyncio.to_thread(
                get_existing_signup_data,
                ws,
                interaction.user.display_name.strip()
            )
        except Exception:
            existing = {
                "restream": "Nein",
                "commentary": "Nein",
                "tracker": "Nein",
            }

        view = RestreamSettingsView(
            owner_id=interaction.user.id,
            restream=existing.get("restream", "Nein"),
            commentary=existing.get("commentary", "Nein"),
            tracker=existing.get("tracker", "Nein"),
        )

        await interaction.response.edit_message(
            content=view.render_text(),
            view=view,
        )

    @discord.ui.button(label="Streichmodis setzen", style=discord.ButtonStyle.primary, row=1)
    async def streich_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            modes = await asyncio.to_thread(get_runner_modes)
        except Exception as e:
            await interaction.response.send_message(
                f"Fehler beim Laden der Spielmodi: {e}",
                ephemeral=True
            )
            return

        view = StreichSettingsView(owner_id=interaction.user.id, modes=modes)
        await interaction.response.edit_message(
            content=view.render_text(),
            view=view,
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=2)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü**\nWähle einen Bereich:",
            view=PlayerMenuView(owner_id=interaction.user.id)
        )


# =========================================================
# Cog
# =========================================================
class PlayerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="player", description="Öffnet das Spielermenü")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def player(self, interaction: discord.Interaction):
        view = PlayerMenuView(owner_id=interaction.user.id)
        await interaction.response.send_message(
            "**Spielermenü**\nWähle einen Bereich:",
            view=view,
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(PlayerCog(bot))
