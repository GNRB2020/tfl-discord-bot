import os
import asyncio
import discord
from discord import app_commands
from discord.ext import commands

import signup
import asnyc
import restinfo

from plan import PlanMenuView
from asyncplan import open_async_request_from_player
from matchcenter import LeagueResultViewStep1, CupResultView

GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "0"))


# =========================================================
# Hilfsfunktionen
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
    ws = await asyncio.to_thread(asnyc.get_quali_worksheet)
    total_completed, rank = await asyncio.to_thread(
        asnyc.get_overall_stats_for_runner,
        ws,
        runner_name,
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


# =========================================================
# Basis-View
# =========================================================
class PlayerBaseView(discord.ui.View):
    def __init__(self, owner_id: int, timeout: float = 900):
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
            view=self.back_view,
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
            view=InfoMenuView(owner_id=interaction.user.id),
        )

    @discord.ui.button(label="Spiel planen", style=discord.ButtonStyle.primary, row=0)
    async def plan_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spiel planen**\nWähle einen Bereich:",
            view=PlanMenuView(owner_id=interaction.user.id),
        )

    @discord.ui.button(label="Ergebnis melden", style=discord.ButtonStyle.success, row=0)
    async def result_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Ergebnis melden**\nWähle einen Bereich:",
            view=ResultMenuView(owner_id=interaction.user.id),
        )

    @discord.ui.button(label="Qualifikation", style=discord.ButtonStyle.secondary, row=1)
    async def qualification_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await asnyc.open_quali_from_player(interaction)

    @discord.ui.button(label="Saisonmeldung", style=discord.ButtonStyle.secondary, row=1)
    async def season_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if hasattr(signup, "open_signup_from_player"):
            await signup.open_signup_from_player(interaction)
            return

        await interaction.response.edit_message(
            content="Saisonmeldung ist aktuell nicht verfügbar.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=PlayerMenuView(owner_id=interaction.user.id),
                back_content="**Spielermenü**\nWähle einen Bereich:",
            ),
        )

    @discord.ui.button(label="Einstellungen", style=discord.ButtonStyle.secondary, row=1)
    async def settings_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Einstellungen**\nWähle einen Bereich:",
            view=SettingsMenuView(owner_id=interaction.user.id),
        )

    @discord.ui.button(label="Async", style=discord.ButtonStyle.primary, row=2)
    async def async_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_async_request_from_player(interaction)


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
            view=MeldestatusView(owner_id=interaction.user.id),
        )

    @discord.ui.button(label="Qualifikation", style=discord.ButtonStyle.primary, row=0)
    async def qualifikation_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Qualifikation**\nWähle einen Bereich:",
            view=InfoQualifikationView(owner_id=interaction.user.id),
        )

    @discord.ui.button(label="Restprogramm", style=discord.ButtonStyle.primary, row=1)
    async def restprogramm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Restprogramm**\nWähle einen Bereich:",
            view=RestprogrammView(owner_id=interaction.user.id),
        )

    @discord.ui.button(label="Streichmodus", style=discord.ButtonStyle.primary, row=1)
    async def streichmodus_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Streichmodus**\nWähle einen Bereich:",
            view=StreichmodusView(owner_id=interaction.user.id),
        )

    @discord.ui.button(label="Ergebnisse/Tabelle", style=discord.ButtonStyle.primary, row=2)
    async def ergebnisse_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Ergebnisse/Tabelle**\nWähle eine Liga oder den Cup:",
            view=ErgebnisseTabelleView(owner_id=interaction.user.id),
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=3)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü**\nWähle einen Bereich:",
            view=PlayerMenuView(owner_id=interaction.user.id),
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
                text = signup.get_signup_status_text_for_member(member)
            except Exception as e:
                text = f"Fehler beim Abrufen deines Eintrags: {e}"

        await interaction.response.edit_message(
            content=f"**Info → Meldestatus → Meiner**\n{text}",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=MeldestatusView(owner_id=interaction.user.id),
                back_content="**Info → Meldestatus**\nWähle einen Bereich:",
            ),
        )

    @discord.ui.button(label="League", style=discord.ButtonStyle.primary, row=0)
    async def league_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            text = signup.get_league_signup_text()
        except Exception as e:
            text = f"Fehler beim Abrufen der League-Anmeldungen: {e}"

        await interaction.response.edit_message(
            content=f"**Info → Meldestatus → League**\n{text}",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=MeldestatusView(owner_id=interaction.user.id),
                back_content="**Info → Meldestatus**\nWähle einen Bereich:",
            ),
        )

    @discord.ui.button(label="Cup", style=discord.ButtonStyle.primary, row=0)
    async def cup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            text = signup.get_cup_signup_text()
        except Exception as e:
            text = f"Fehler beim Abrufen der Cup-Anmeldungen: {e}"

        await interaction.response.edit_message(
            content=f"**Info → Meldestatus → Cup**\n{text}",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=MeldestatusView(owner_id=interaction.user.id),
                back_content="**Info → Meldestatus**\nWähle einen Bereich:",
            ),
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Info**\nWähle einen Bereich:",
            view=InfoMenuView(owner_id=interaction.user.id),
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
        await interaction.response.defer()

        if not isinstance(member, discord.Member):
            text = "Nur auf dem Server verfügbar."
        else:
            try:
                text = await build_quali_info_text(member, 1)
            except Exception as e:
                text = f"Fehler bei Quali 1: {e}"

        await interaction.edit_original_response(
            content=f"**Info → Qualifikation → Quali 1**\n{text}",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=InfoQualifikationView(owner_id=interaction.user.id),
                back_content="**Info → Qualifikation**\nWähle einen Bereich:",
            ),
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
            content=f"**Info → Qualifikation → Quali 2**\n{text}",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=InfoQualifikationView(owner_id=interaction.user.id),
                back_content="**Info → Qualifikation**\nWähle einen Bereich:",
            ),
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
            content=f"**Info → Qualifikation → Gesamt**\n{text}",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=InfoQualifikationView(owner_id=interaction.user.id),
                back_content="**Info → Qualifikation**\nWähle einen Bereich:",
            ),
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Info**\nWähle einen Bereich:",
            view=InfoMenuView(owner_id=interaction.user.id),
        )


# =========================================================
# Restprogramm
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
            content=text,
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=RestOtherDivisionView(owner_id=interaction.user.id),
                back_content="**Info → Restprogramm → Andere**\nWähle eine Division:",
            ),
        )


class RestOtherPlayerView(PlayerBaseView):
    def __init__(self, owner_id: int, division: str, players: list[str]):
        super().__init__(owner_id)
        self.add_item(RestOtherPlayerSelect(division, players, owner_id))

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Restprogramm → Andere**\nWähle eine Division:",
            view=RestOtherDivisionView(owner_id=interaction.user.id),
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
                content=f"❌ Fehler beim Laden der Spieler für Division {div_number}: {e}",
                view=RestOtherDivisionView(owner_id=interaction.user.id),
            )
            return

        if not players:
            await interaction.response.edit_message(
                content=f"Keine Spieler in Division {div_number} für das Restprogramm gefunden.",
                view=RestOtherDivisionView(owner_id=interaction.user.id),
            )
            return

        await interaction.response.edit_message(
            content=f"**Info → Restprogramm → Andere**\nDivision {div_number} gewählt. Bitte Spieler wählen:",
            view=RestOtherPlayerView(
                owner_id=interaction.user.id,
                division=div_number,
                players=players,
            ),
        )


class RestOtherDivisionView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)
        self.add_item(RestOtherDivisionSelect(owner_id))

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Restprogramm**\nWähle einen Bereich:",
            view=RestprogrammView(owner_id=interaction.user.id),
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
            content=f"**Info → Restprogramm → Eigenes**\n{text}",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=RestprogrammView(owner_id=interaction.user.id),
                back_content="**Info → Restprogramm**\nWähle einen Bereich:",
            ),
        )

    @discord.ui.button(label="Andere", style=discord.ButtonStyle.primary, row=0)
    async def andere_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Restprogramm → Andere**\nWähle eine Division:",
            view=RestOtherDivisionView(owner_id=interaction.user.id),
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Info**\nWähle einen Bereich:",
            view=InfoMenuView(owner_id=interaction.user.id),
        )


# =========================================================
# Streichmodus
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
            content=f"**Info → Streichmodus → Andere Divisionen**\n{text}",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=StreichOtherDivisionView(owner_id=interaction.user.id),
                back_content="**Info → Streichmodus → Andere Divisionen**\nWähle eine Division:",
            ),
        )


class StreichOtherDivisionView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)
        self.add_item(StreichOtherDivisionSelect(owner_id))

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Streichmodus**\nWähle einen Bereich:",
            view=StreichmodusView(owner_id=interaction.user.id),
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
            content=f"**Info → Streichmodus → Eigene Division**\n{text}",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=StreichmodusView(owner_id=interaction.user.id),
                back_content="**Info → Streichmodus**\nWähle einen Bereich:",
            ),
        )

    @discord.ui.button(label="Andere Divisionen", style=discord.ButtonStyle.primary, row=0)
    async def andere_divisionen_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Streichmodus → Andere Divisionen**\nWähle eine Division:",
            view=StreichOtherDivisionView(owner_id=interaction.user.id),
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Info**\nWähle einen Bereich:",
            view=InfoMenuView(owner_id=interaction.user.id),
        )


# =========================================================
# Ergebnisse / Tabelle
# =========================================================
class ErgebnisseTabelleView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

        self.add_item(discord.ui.Button(label="1. Div", style=discord.ButtonStyle.link, url="https://tryforceleague.de/index.php/1-division", row=0))
        self.add_item(discord.ui.Button(label="2. Div", style=discord.ButtonStyle.link, url="https://tryforceleague.de/index.php/1-division-2", row=0))
        self.add_item(discord.ui.Button(label="3. Div", style=discord.ButtonStyle.link, url="https://tryforceleague.de/index.php/3-division", row=0))
        self.add_item(discord.ui.Button(label="4. Div", style=discord.ButtonStyle.link, url="https://tryforceleague.de/index.php/3-division-2", row=1))
        self.add_item(discord.ui.Button(label="5. Div", style=discord.ButtonStyle.link, url="https://tryforceleague.de/index.php/3-division-3", row=1))
        self.add_item(discord.ui.Button(label="6. Div", style=discord.ButtonStyle.link, url="https://tryforceleague.de/index.php/3-division-4", row=1))
        self.add_item(discord.ui.Button(label="Cup", style=discord.ButtonStyle.link, url="https://tryforceleague.de/index.php/cup", row=2))

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=3)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Info**\nWähle einen Bereich:",
            view=InfoMenuView(owner_id=interaction.user.id),
        )


# =========================================================
# Ergebnis-Menü
# =========================================================
class ResultMenuView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="League", style=discord.ButtonStyle.success, row=0)
    async def league_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("MatchCenterCog")
        if cog is None:
            await interaction.response.edit_message(
                content="League-Ergebnismeldung ist aktuell nicht verfügbar.",
                view=PlaceholderView(
                    owner_id=interaction.user.id,
                    back_view=ResultMenuView(owner_id=interaction.user.id),
                    back_content="**Spielermenü → Ergebnis melden**\nWähle einen Bereich:",
                ),
            )
            return

        view = LeagueResultViewStep1(cog, interaction.user.id)
        view.state.kind = "Ergebnis League"
        await interaction.response.edit_message(content=view.render_summary(), view=view)

    @discord.ui.button(label="Cup", style=discord.ButtonStyle.success, row=0)
    async def cup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("MatchCenterCog")
        if cog is None:
            await interaction.response.edit_message(
                content="Cup-Ergebnismeldung ist aktuell nicht verfügbar.",
                view=PlaceholderView(
                    owner_id=interaction.user.id,
                    back_view=ResultMenuView(owner_id=interaction.user.id),
                    back_content="**Spielermenü → Ergebnis melden**\nWähle einen Bereich:",
                ),
            )
            return

        view = CupResultView(cog, interaction.user.id)
        view.state.kind = "Ergebnis Cup"
        await interaction.response.edit_message(content=view.render_summary(), view=view)

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü**\nWähle einen Bereich:",
            view=PlayerMenuView(owner_id=interaction.user.id),
        )


# =========================================================
# Einstellungen
# =========================================================
class SettingsMenuView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="Twitch setzen", style=discord.ButtonStyle.primary, row=0)
    async def twitch_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if hasattr(signup, "open_signup_from_player"):
            await signup.open_signup_from_player(interaction)
            return

        await interaction.response.edit_message(
            content="Twitch setzen ist aktuell nicht verfügbar.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=SettingsMenuView(owner_id=interaction.user.id),
                back_content="**Spielermenü → Einstellungen**\nWähle einen Bereich:",
            ),
        )

    @discord.ui.button(label="Restream", style=discord.ButtonStyle.primary, row=0)
    async def restream_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if hasattr(signup, "open_signup_from_player"):
            await signup.open_signup_from_player(interaction)
            return

        await interaction.response.edit_message(
            content="Restream/Commentary/Tracker ist aktuell nicht verfügbar.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=SettingsMenuView(owner_id=interaction.user.id),
                back_content="**Spielermenü → Einstellungen**\nWähle einen Bereich:",
            ),
        )

    @discord.ui.button(label="Streichmodis setzen", style=discord.ButtonStyle.primary, row=1)
    async def streich_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="Streichmodis setzen ist aktuell nicht in dieser Datei verdrahtet.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                back_view=SettingsMenuView(owner_id=interaction.user.id),
                back_content="**Spielermenü → Einstellungen**\nWähle einen Bereich:",
            ),
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=2)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü**\nWähle einen Bereich:",
            view=PlayerMenuView(owner_id=interaction.user.id),
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
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(PlayerCog(bot))
