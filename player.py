import os
import asyncio

import discord
import gspread
from discord import app_commands
from discord.ext import commands
from oauth2client.service_account import ServiceAccountCredentials

import signup
import asnyc
import restinfo

from plan import PlanMenuView
from asyncplan import open_async_request_from_player
from matchcenter import (
    LeagueResultViewStep1,
    LeagueResultViewStep2,
    CupResultView,
    get_runner_modes,
)

GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0"))

# =========================================================
# STREICHMODUS SETTINGS SHEET
# =========================================================
STREICHMODUS_SPREADSHEET_ID = "1pZxg1_DUtbO4dZvX95ZrIqEZnkMc1MjmE7z5SEsMHQU"
STREICHMODUS_WORKSHEET_GID = 2118667264
CREDS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]


# =========================================================
# UI HELFER
# =========================================================
def menu_embed(title: str, description: str) -> discord.Embed:
    return discord.Embed(
        title=title,
        description=description,
        color=0x00FFCC,
    )


def normalize_name(value: str) -> str:
    return (
        (value or "")
        .strip()
        .lower()
        .replace("_", "")
        .replace("-", "")
        .replace(" ", "")
    )


# =========================================================
# GOOGLE SHEETS FÜR STREICHMODI
# =========================================================
def get_gspread_client() -> gspread.Client:
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    return gspread.authorize(creds)


def get_streichmodus_worksheet():
    client = get_gspread_client()
    spreadsheet = client.open_by_key(STREICHMODUS_SPREADSHEET_ID)

    for ws in spreadsheet.worksheets():
        if ws.id == STREICHMODUS_WORKSHEET_GID:
            return ws

    raise RuntimeError(
        f"Worksheet mit gid/id {STREICHMODUS_WORKSHEET_GID} nicht gefunden."
    )


def find_streichmodus_row_for_name_candidates(name_candidates: list[str]) -> int | None:
    ws = get_streichmodus_worksheet()
    values = ws.col_values(12)  # L

    targets = {normalize_name(x) for x in name_candidates if x}

    for idx, cell_value in enumerate(values, start=1):
        if normalize_name(cell_value) in targets:
            return idx

    return None


def load_current_streichmodi_for_name_candidates(name_candidates: list[str]) -> tuple[str, str]:
    ws = get_streichmodus_worksheet()
    row_index = find_streichmodus_row_for_name_candidates(name_candidates)

    if row_index is None:
        return "", ""

    row = ws.row_values(row_index)
    mode_1 = row[12].strip() if len(row) > 12 else ""  # M
    mode_2 = row[13].strip() if len(row) > 13 else ""  # N
    return mode_1, mode_2


def write_streichmodi_for_name_candidates(
    name_candidates: list[str],
    mode_1: str,
    mode_2: str,
) -> int:
    ws = get_streichmodus_worksheet()
    row_index = find_streichmodus_row_for_name_candidates(name_candidates)

    if row_index is None:
        raise RuntimeError("Kein passender Name in Spalte L gefunden.")

    reqs = [
        {"range": f"M{row_index}:M{row_index}", "values": [[mode_1]]},
        {"range": f"N{row_index}:N{row_index}", "values": [[mode_2]]},
    ]
    ws.batch_update(reqs)
    return row_index


# =========================================================
# QUALI INFO
# =========================================================
async def build_quali_info_text(member: discord.Member, quali_number: int) -> str:
    runner_name = member.display_name.strip()
    ws = await asyncio.to_thread(asnyc.get_quali_worksheet)
    total_played, rank = await asyncio.to_thread(
        asnyc.get_quali_stats_for_runner,
        ws,
        runner_name,
        quali_number,
    )

    if rank is None:
        return (
            f"Bereits gespielt: **{total_played}**\n"
            f"Du hast Quali {quali_number} aktuell noch nicht abgeschlossen."
        )

    return (
        f"Bereits gespielt: **{total_played}**\n"
        f"Dein aktueller Platz: **{rank}/{total_played}**"
    )


async def build_quali_overall_text(member: discord.Member) -> str:
    runner_name = member.display_name.strip()
    ws = await asyncio.to_thread(asnyc.get_quali_worksheet)
    total_completed, rank = await asyncio.to_thread(
        asnyc.get_overall_stats_for_runner,
        ws,
        runner_name,
    )

    if rank is None:
        return (
            f"Beide Qualis abgeschlossen: **{total_completed}**\n"
            f"Du bist aktuell noch nicht im Gesamtstand, weil dir mindestens eine Quali fehlt."
        )

    return (
        f"Beide Qualis abgeschlossen: **{total_completed}**\n"
        f"Dein aktueller Platz: **{rank}/{total_completed}**"
    )


# =========================================================
# BASIS
# =========================================================
class PlayerBaseView(discord.ui.View):
    def __init__(self, owner_id: int, timeout: float = 1800):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Dieses Menü gehört nicht dir.",
                ephemeral=True,
            )
            return False
        return True


class PlaceholderView(PlayerBaseView):
    def __init__(self, owner_id: int, back_view: discord.ui.View, back_embed: discord.Embed):
        super().__init__(owner_id)
        self.back_view = back_view
        self.back_embed = back_embed

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=0)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=self.back_embed,
            view=self.back_view,
            content=None,
        )


# =========================================================
# ERGEBNIS WRAPPER
# =========================================================
class BackToResultMenuFromLeagueStep1Button(discord.ui.Button):
    def __init__(self):
        super().__init__(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=4)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=menu_embed("🏁 Ergebnis melden", "Wähle einen Bereich."),
            view=ResultMenuView(owner_id=interaction.user.id),
            content=None,
        )


class BackToResultMenuFromLeagueStep2Button(discord.ui.Button):
    def __init__(self):
        super().__init__(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=2)

    async def callback(self, interaction: discord.Interaction):
        view = PlayerLeagueResultViewStep1(author_id=interaction.user.id)
        view.state.kind = "Ergebnis League"

        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view,
            embed=None,
        )


class BackToResultMenuFromCupButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=3)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=menu_embed("🏁 Ergebnis melden", "Wähle einen Bereich."),
            view=ResultMenuView(owner_id=interaction.user.id),
            content=None,
        )


class PlayerLeagueResultContinueButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Weiter", style=discord.ButtonStyle.primary, row=4)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, PlayerLeagueResultViewStep1):
            return

        s = view.state
        if not all([s.division, s.match_row_index, s.match_label, s.player1, s.player2]):
            await interaction.response.send_message(
                "Bitte zuerst Division, Heimrecht und Spiel auswählen.",
                ephemeral=True,
            )
            return

        next_view = PlayerLeagueResultViewStep2(
            author_id=interaction.user.id,
            state=s.clone(),
        )

        await interaction.response.edit_message(
            content=next_view.render_summary(),
            view=next_view,
            embed=None,
        )


class PlayerLeagueResultViewStep1(LeagueResultViewStep1):
    def __init__(self, author_id: int):
        super().__init__(cog=None, author_id=author_id)

        old_back = None
        old_continue = None

        for item in list(self.children):
            if isinstance(item, discord.ui.Button) and item.label == "Zurück":
                old_back = item
            elif isinstance(item, discord.ui.Button) and item.label == "Weiter":
                old_continue = item

        if old_back is not None:
            self.remove_item(old_back)
        if old_continue is not None:
            self.remove_item(old_continue)

        self.add_item(PlayerLeagueResultContinueButton())
        self.add_item(BackToResultMenuFromLeagueStep1Button())


class PlayerLeagueResultViewStep2(LeagueResultViewStep2):
    def __init__(self, author_id: int, state):
        super().__init__(cog=None, author_id=author_id, state=state)

        old_back = None
        for item in list(self.children):
            if isinstance(item, discord.ui.Button) and item.label == "Zurück":
                old_back = item
                break

        if old_back is not None:
            self.remove_item(old_back)

        self.add_item(BackToResultMenuFromLeagueStep2Button())


class PlayerCupResultView(CupResultView):
    def __init__(self, author_id: int):
        super().__init__(cog=None, author_id=author_id)

        old_back = None
        for item in list(self.children):
            if isinstance(item, discord.ui.Button) and item.label == "Zurück":
                old_back = item
                break

        if old_back is not None:
            self.remove_item(old_back)

        self.add_item(BackToResultMenuFromCupButton())


# =========================================================
# STREICHMODI SETZEN
# =========================================================
class StreichmodusSelect(discord.ui.Select):
    EMPTY_VALUE = "__none__"

    def __init__(self, slot: int, modes: list[str], selected_value: str | None = None):
        self.slot = slot

        options = []

        if not selected_value:
            options.append(
                discord.SelectOption(
                    label="Bitte wählen",
                    value=self.EMPTY_VALUE,
                    default=True,
                )
            )

        for mode in modes[:25]:
            clean_mode = (mode or "").strip()
            if not clean_mode:
                continue

            options.append(
                discord.SelectOption(
                    label=clean_mode[:100],
                    value=clean_mode[:100],
                    default=(clean_mode == selected_value),
                )
            )

        super().__init__(
            placeholder=f"Streichmodus {slot} wählen …",
            min_values=1,
            max_values=1,
            options=options,
            row=slot - 1,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, StreichmodusSettingView):
            return

        selected = self.values[0]
        if selected == self.EMPTY_VALUE:
            selected = ""

        if self.slot == 1:
            view.mode_1 = selected
        else:
            view.mode_2 = selected

        new_view = StreichmodusSettingView(
            owner_id=view.owner_id,
            modes=view.modes,
            mode_1=view.mode_1,
            mode_2=view.mode_2,
        )

        await interaction.response.edit_message(
            embed=new_view.build_embed(),
            view=new_view,
            content=None,
        )


class StreichmodusSettingView(PlayerBaseView):
    def __init__(
        self,
        owner_id: int,
        modes: list[str],
        mode_1: str = "",
        mode_2: str = "",
    ):
        super().__init__(owner_id)
        self.modes = modes
        self.mode_1 = mode_1
        self.mode_2 = mode_2

        self.add_item(StreichmodusSelect(1, self.modes, self.mode_1))
        self.add_item(StreichmodusSelect(2, self.modes, self.mode_2))

    def build_embed(self) -> discord.Embed:
        text = (
            "Wähle zwei Streichmodi.\n\n"
            f"**Modus 1:** {self.mode_1 or '-'}\n"
            f"**Modus 2:** {self.mode_2 or '-'}"
        )
        return menu_embed("⚙️ Einstellungen → Streichmodis setzen", text)

    @discord.ui.button(label="Speichern", style=discord.ButtonStyle.success, row=2)
    async def save_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Nur auf dem Server verfügbar.", ephemeral=True)
            return

        if not self.mode_1 or not self.mode_2:
            await interaction.response.send_message(
                "Bitte beide Streichmodi auswählen.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            name_candidates = [
                member.display_name,
                getattr(member, "global_name", None),
                member.name,
            ]
            row_index = await asyncio.to_thread(
                write_streichmodi_for_name_candidates,
                name_candidates,
                self.mode_1,
                self.mode_2,
            )

            await interaction.edit_original_response(
                embed=menu_embed(
                    "⚙️ Einstellungen → Streichmodis setzen",
                    (
                        "Streichmodi gespeichert.\n\n"
                        f"**Modus 1:** {self.mode_1}\n"
                        f"**Modus 2:** {self.mode_2}\n"
                        f"**Sheet-Zeile:** {row_index}"
                    ),
                ),
                view=PlaceholderView(
                    owner_id=interaction.user.id,
                    back_view=SettingsMenuView(owner_id=interaction.user.id),
                    back_embed=menu_embed("⚙️ Einstellungen", "Wähle einen Bereich."),
                ),
                content=None,
            )
        except Exception as e:
            await interaction.edit_original_response(
                embed=menu_embed(
                    "⚙️ Einstellungen → Streichmodis setzen",
                    f"Fehler beim Speichern: {e}",
                ),
                view=self,
                content=None,
            )

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=2)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("⚙️ Einstellungen", "Wähle einen Bereich."),
            view=SettingsMenuView(owner_id=interaction.user.id),
            content=None,
        )


# =========================================================
# HAUPTMENÜ
# =========================================================
class PlayerMenuView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="ℹ️ Info", style=discord.ButtonStyle.secondary, row=0)
    async def info_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Info", "Wähle einen Bereich."),
            view=InfoMenuView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(label="📅 Spiel planen", style=discord.ButtonStyle.primary, row=0)
    async def plan_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("📅 Spiel planen", "Wähle einen Bereich."),
            view=PlanMenuView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(label="🏁 Ergebnis melden", style=discord.ButtonStyle.success, row=0)
    async def result_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("🏁 Ergebnis melden", "Wähle einen Bereich."),
            view=ResultMenuView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(label="⚡ Async", style=discord.ButtonStyle.primary, row=1)
    async def async_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("⚡ Async", "Wähle einen Bereich."),
            view=AsyncMenuView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(label="🏆 Qualifikation", style=discord.ButtonStyle.primary, row=1)
    async def qualification_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if hasattr(asnyc, "open_quali_from_player"):
            await asnyc.open_quali_from_player(interaction)
            return

        await interaction.response.send_message(
            "Qualifikation ist aktuell nicht verfügbar.",
            ephemeral=True,
        )

    @discord.ui.button(label="📝 Saisonmeldung", style=discord.ButtonStyle.primary, row=1)
    async def season_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if hasattr(signup, "open_signup_from_player"):
            await signup.open_signup_from_player(interaction)
            return

        await interaction.response.send_message(
            "Saisonmeldung ist aktuell nicht verfügbar.",
            ephemeral=True,
        )

    @discord.ui.button(label="⚙️ Einstellungen", style=discord.ButtonStyle.secondary, row=2)
    async def settings_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("⚙️ Einstellungen", "Wähle einen Bereich."),
            view=SettingsMenuView(owner_id=interaction.user.id),
            content=None,
        )


# =========================================================
# ASYNC MENÜ
# =========================================================
class AsyncMenuView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="Beantragen", style=discord.ButtonStyle.primary, row=0)
    async def beantragen_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_async_request_from_player(interaction)

    @discord.ui.button(label="Spielen", style=discord.ButtonStyle.success, row=0)
    async def spielen_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if hasattr(asnyc, "open_async_play_from_player"):
            await asnyc.open_async_play_from_player(interaction)
            return

        await interaction.response.send_message(
            "Async spielen ist aktuell nicht verfügbar.",
            ephemeral=True,
        )

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("Spielermenü", "Wähle einen Bereich."),
            view=PlayerMenuView(owner_id=interaction.user.id),
            content=None,
        )


# =========================================================
# ERGEBNIS MENÜ
# =========================================================
class ResultMenuView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="League", style=discord.ButtonStyle.primary, row=0)
    async def league_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PlayerLeagueResultViewStep1(author_id=interaction.user.id)
        view.state.kind = "Ergebnis League"

        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view,
            embed=None,
        )

    @discord.ui.button(label="Cup", style=discord.ButtonStyle.primary, row=0)
    async def cup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PlayerCupResultView(author_id=interaction.user.id)
        view.state.kind = "Ergebnis Cup"

        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view,
            embed=None,
        )

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("Spielermenü", "Wähle einen Bereich."),
            view=PlayerMenuView(owner_id=interaction.user.id),
            content=None,
        )


# =========================================================
# INFO MENÜ
# =========================================================
class InfoMenuView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="Meldestatus", style=discord.ButtonStyle.primary, row=0)
    async def meldestatus_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Meldestatus", "Wähle einen Bereich."),
            view=MeldestatusView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(label="Qualifikation", style=discord.ButtonStyle.primary, row=0)
    async def qualifikation_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Qualifikation", "Wähle einen Bereich."),
            view=InfoQualifikationView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(label="Restprogramm", style=discord.ButtonStyle.primary, row=1)
    async def restprogramm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Restprogramm", "Wähle einen Bereich."),
            view=RestprogrammView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(label="Streichmodus", style=discord.ButtonStyle.primary, row=1)
    async def streichmodus_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Streichmodus", "Wähle einen Bereich."),
            view=StreichmodusView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(label="Ergebnisse/Tabelle", style=discord.ButtonStyle.primary, row=2)
    async def ergebnisse_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Ergebnisse/Tabelle", "Wähle eine Liga oder den Cup."),
            view=ErgebnisseTabelleView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=3)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("Spielermenü", "Wähle einen Bereich."),
            view=PlayerMenuView(owner_id=interaction.user.id),
            content=None,
        )


# =========================================================
# MELDESTATUS
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
                text = signup.get_signup_status_text_for_member(member)
            except Exception as e:
                text = f"Fehler beim Abrufen deines Eintrags: {e}"

        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Meldestatus → Meiner", text),
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=MeldestatusView(owner_id=interaction.user.id),
                back_embed=menu_embed("ℹ️ Meldestatus", "Wähle einen Bereich."),
            ),
            content=None,
        )

    @discord.ui.button(label="League", style=discord.ButtonStyle.primary, row=0)
    async def league_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            text = signup.get_league_signup_text()
        except Exception as e:
            text = f"Fehler beim Abrufen der League-Anmeldungen: {e}"

        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Meldestatus → League", text),
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=MeldestatusView(owner_id=interaction.user.id),
                back_embed=menu_embed("ℹ️ Meldestatus", "Wähle einen Bereich."),
            ),
            content=None,
        )

    @discord.ui.button(label="Cup", style=discord.ButtonStyle.primary, row=0)
    async def cup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            text = signup.get_cup_signup_text()
        except Exception as e:
            text = f"Fehler beim Abrufen der Cup-Anmeldungen: {e}"

        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Meldestatus → Cup", text),
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=MeldestatusView(owner_id=interaction.user.id),
                back_embed=menu_embed("ℹ️ Meldestatus", "Wähle einen Bereich."),
            ),
            content=None,
        )

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Info", "Wähle einen Bereich."),
            view=InfoMenuView(owner_id=interaction.user.id),
            content=None,
        )


# =========================================================
# INFO → QUALIFIKATION
# =========================================================
class InfoQualifikationView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="Quali 1", style=discord.ButtonStyle.primary, row=0)
    async def quali1_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        await interaction.response.defer()

        if not isinstance(member, discord.Member):
            text = "Nur auf dem Server verfügbar."
        else:
            try:
                text = await build_quali_info_text(member, 1)
            except Exception as e:
                text = f"Fehler bei Quali 1: {e}"

        await interaction.edit_original_response(
            embed=menu_embed("ℹ️ Qualifikation → Quali 1", text),
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=InfoQualifikationView(owner_id=interaction.user.id),
                back_embed=menu_embed("ℹ️ Qualifikation", "Wähle einen Bereich."),
            ),
            content=None,
        )

    @discord.ui.button(label="Quali 2", style=discord.ButtonStyle.primary, row=0)
    async def quali2_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        await interaction.response.defer()

        if not isinstance(member, discord.Member):
            text = "Nur auf dem Server verfügbar."
        else:
            try:
                text = await build_quali_info_text(member, 2)
            except Exception as e:
                text = f"Fehler bei Quali 2: {e}"

        await interaction.edit_original_response(
            embed=menu_embed("ℹ️ Qualifikation → Quali 2", text),
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=InfoQualifikationView(owner_id=interaction.user.id),
                back_embed=menu_embed("ℹ️ Qualifikation", "Wähle einen Bereich."),
            ),
            content=None,
        )

    @discord.ui.button(label="Gesamt", style=discord.ButtonStyle.primary, row=0)
    async def gesamt_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        await interaction.response.defer()

        if not isinstance(member, discord.Member):
            text = "Nur auf dem Server verfügbar."
        else:
            try:
                text = await build_quali_overall_text(member)
            except Exception as e:
                text = f"Fehler beim Gesamtstand: {e}"

        await interaction.edit_original_response(
            embed=menu_embed("ℹ️ Qualifikation → Gesamt", text),
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=InfoQualifikationView(owner_id=interaction.user.id),
                back_embed=menu_embed("ℹ️ Qualifikation", "Wähle einen Bereich."),
            ),
            content=None,
        )

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Info", "Wähle einen Bereich."),
            view=InfoMenuView(owner_id=interaction.user.id),
            content=None,
        )


# =========================================================
# RESTPROGRAMM
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
        try:
            text = restinfo.format_restprogramm_text(self.division, player)
        except Exception as e:
            text = f"Fehler beim Ermitteln des Restprogramms: {e}"

        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Restprogramm → Andere", text),
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=RestOtherDivisionView(owner_id=interaction.user.id),
                back_embed=menu_embed("ℹ️ Restprogramm → Andere", "Wähle eine Division."),
            ),
            content=None,
        )


class RestOtherPlayerView(PlayerBaseView):
    def __init__(self, owner_id: int, division: str, players: list[str]):
        super().__init__(owner_id)
        self.add_item(RestOtherPlayerSelect(division, players, owner_id))

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Restprogramm → Andere", "Wähle eine Division."),
            view=RestOtherDivisionView(owner_id=interaction.user.id),
            content=None,
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

        try:
            players = restinfo.list_rest_players(div_number)
        except Exception as e:
            await interaction.response.edit_message(
                embed=menu_embed(
                    "ℹ️ Restprogramm → Andere",
                    f"Fehler beim Laden der Spieler für Division {div_number}: {e}",
                ),
                view=RestOtherDivisionView(owner_id=interaction.user.id),
                content=None,
            )
            return

        if not players:
            await interaction.response.edit_message(
                embed=menu_embed(
                    "ℹ️ Restprogramm → Andere",
                    f"Keine Spieler in Division {div_number} für das Restprogramm gefunden.",
                ),
                view=RestOtherDivisionView(owner_id=interaction.user.id),
                content=None,
            )
            return

        await interaction.response.edit_message(
            embed=menu_embed(
                "ℹ️ Restprogramm → Andere",
                f"**Division {div_number}**\nWähle einen Spieler.",
            ),
            view=RestOtherPlayerView(
                owner_id=interaction.user.id,
                division=div_number,
                players=players,
            ),
            content=None,
        )


class RestOtherDivisionView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)
        self.add_item(RestOtherDivisionSelect(owner_id))

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Restprogramm", "Wähle einen Bereich."),
            view=RestprogrammView(owner_id=interaction.user.id),
            content=None,
        )


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
                    restinfo.get_open_restprogramm_text_for_name_candidates,
                    name_candidates,
                )
            except Exception as e:
                text = f"Fehler beim Abrufen deines Restprogramms: {e}"

        await interaction.edit_original_response(
            embed=menu_embed("ℹ️ Restprogramm → Eigenes", text),
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=RestprogrammView(owner_id=interaction.user.id),
                back_embed=menu_embed("ℹ️ Restprogramm", "Wähle einen Bereich."),
            ),
            content=None,
        )

    @discord.ui.button(label="Andere", style=discord.ButtonStyle.primary, row=0)
    async def andere_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Restprogramm → Andere", "Wähle eine Division."),
            view=RestOtherDivisionView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Info", "Wähle einen Bereich."),
            view=InfoMenuView(owner_id=interaction.user.id),
            content=None,
        )


# =========================================================
# STREICHMODUS INFO
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
        try:
            text = restinfo.get_streich_text_for_division(div_number)
        except Exception as e:
            text = f"Fehler beim Abrufen des Streichmodus: {e}"

        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Streichmodus → Andere Divisionen", text),
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=StreichOtherDivisionView(owner_id=interaction.user.id),
                back_embed=menu_embed("ℹ️ Streichmodus → Andere Divisionen", "Wähle eine Division."),
            ),
            content=None,
        )


class StreichOtherDivisionView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)
        self.add_item(StreichOtherDivisionSelect(owner_id))

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Streichmodus", "Wähle einen Bereich."),
            view=StreichmodusView(owner_id=interaction.user.id),
            content=None,
        )


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
                    restinfo.get_own_division_streich_text,
                    name_candidates,
                )
            except Exception as e:
                text = f"Fehler beim Abrufen des Streichmodus: {e}"

        await interaction.edit_original_response(
            embed=menu_embed("ℹ️ Streichmodus → Eigene Division", text),
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=StreichmodusView(owner_id=interaction.user.id),
                back_embed=menu_embed("ℹ️ Streichmodus", "Wähle einen Bereich."),
            ),
            content=None,
        )

    @discord.ui.button(label="Andere Divisionen", style=discord.ButtonStyle.primary, row=0)
    async def andere_divisionen_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Streichmodus → Andere Divisionen", "Wähle eine Division."),
            view=StreichOtherDivisionView(owner_id=interaction.user.id),
            content=None,
        )

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Info", "Wähle einen Bereich."),
            view=InfoMenuView(owner_id=interaction.user.id),
            content=None,
        )


# =========================================================
# ERGEBNISSE / TABELLE
# =========================================================
class ErgebnisseTabelleView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

        self.add_item(discord.ui.Button(
            label="1. Div",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/1-division",
            row=0,
        ))
        self.add_item(discord.ui.Button(
            label="2. Div",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/1-division-2",
            row=0,
        ))
        self.add_item(discord.ui.Button(
            label="3. Div",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/3-division",
            row=0,
        ))
        self.add_item(discord.ui.Button(
            label="4. Div",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/3-division-2",
            row=1,
        ))
        self.add_item(discord.ui.Button(
            label="5. Div",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/3-division-3",
            row=1,
        ))
        self.add_item(discord.ui.Button(
            label="6. Div",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/3-division-4",
            row=1,
        ))
        self.add_item(discord.ui.Button(
            label="Cup",
            style=discord.ButtonStyle.link,
            url="https://tryforceleague.de/index.php/cup",
            row=2,
        ))

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=3)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("ℹ️ Info", "Wähle einen Bereich."),
            view=InfoMenuView(owner_id=interaction.user.id),
            content=None,
        )


# =========================================================
# EINSTELLUNGEN
# =========================================================
class SettingsMenuView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="Twitch setzen", style=discord.ButtonStyle.primary, row=0)
    async def twitch_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if hasattr(signup, "open_signup_from_player"):
            await signup.open_signup_from_player(interaction)
            return

        await interaction.response.send_message(
            "Twitch setzen ist aktuell nicht verfügbar.",
            ephemeral=True,
        )

    @discord.ui.button(label="Restream/Commentary/Tracker", style=discord.ButtonStyle.primary, row=0)
    async def restream_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if hasattr(signup, "open_signup_from_player"):
            await signup.open_signup_from_player(interaction)
            return

        await interaction.response.send_message(
            "Restream/Commentary/Tracker ist aktuell nicht verfügbar.",
            ephemeral=True,
        )

    @discord.ui.button(label="Streichmodis setzen", style=discord.ButtonStyle.success, row=1)
    async def streich_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Nur auf dem Server verfügbar.", ephemeral=True)
            return

        await interaction.response.defer()

        try:
            modes = await asyncio.to_thread(get_runner_modes)
            if not modes:
                modes = ["Standard"]

            name_candidates = [
                member.display_name,
                getattr(member, "global_name", None),
                member.name,
            ]
            current_mode_1, current_mode_2 = await asyncio.to_thread(
                load_current_streichmodi_for_name_candidates,
                name_candidates,
            )

            view = StreichmodusSettingView(
                owner_id=interaction.user.id,
                modes=modes,
                mode_1=current_mode_1,
                mode_2=current_mode_2,
            )

            await interaction.edit_original_response(
                embed=view.build_embed(),
                view=view,
                content=None,
            )

        except Exception as e:
            await interaction.edit_original_response(
                embed=menu_embed(
                    "⚙️ Einstellungen → Streichmodis setzen",
                    f"Fehler beim Laden: {e}",
                ),
                view=PlaceholderView(
                    owner_id=interaction.user.id,
                    back_view=SettingsMenuView(owner_id=interaction.user.id),
                    back_embed=menu_embed("⚙️ Einstellungen", "Wähle einen Bereich."),
                ),
                content=None,
            )

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=2)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=menu_embed("Spielermenü", "Wähle einen Bereich."),
            view=PlayerMenuView(owner_id=interaction.user.id),
            content=None,
        )


# =========================================================
# COG
# =========================================================
class PlayerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="player", description="Öffnet das Spielermenü")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def player(self, interaction: discord.Interaction):
        view = PlayerMenuView(owner_id=interaction.user.id)
        await interaction.response.send_message(
            embed=menu_embed("Spielermenü", "Wähle einen Bereich."),
            view=view,
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(PlayerCog(bot))
