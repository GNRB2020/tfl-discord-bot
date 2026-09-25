from datetime import datetime as dt

import asyncio
import discord

from asyncplan import open_async_request_from_player
import matchcenter
from matchcenter import LeagueScheduleView, CupScheduleView


def menu_embed(title: str, description: str) -> discord.Embed:
    return discord.Embed(
        title=title,
        description=description,
        color=0x00FFCC,
    )


# =========================================================
# BASIS
# =========================================================
class PlanBaseView(discord.ui.View):
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


# =========================================================
# ZURÜCK-BUTTONS FÜR PLAYER-MENÜ
# =========================================================
class BackToPlanFromLeagueButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="◀ Zurück",
            style=discord.ButtonStyle.secondary,
            row=4,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=menu_embed("📅 Spiel planen", "Wähle einen Bereich."),
            view=PlanMenuView(owner_id=interaction.user.id),
            content=None,
        )


class BackToPlanFromCupButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="◀ Zurück",
            style=discord.ButtonStyle.secondary,
            row=3,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=menu_embed("📅 Spiel planen", "Wähle einen Bereich."),
            view=PlanMenuView(owner_id=interaction.user.id),
            content=None,
        )


# =========================================================
# MODUS-AUSWAHL FÜR LEAGUE
# =========================================================
class PlayerModeDivisionSelect(discord.ui.Select):
    def __init__(self, selected_division: int | None = None):
        options = [
            discord.SelectOption(
                label=f"{division}. Division",
                value=str(division),
                default=(selected_division == division),
            )
            for division in range(1, 7)
        ]
        super().__init__(
            placeholder="Division für den Spielmodus wählen",
            min_values=1,
            max_values=1,
            options=options,
            row=3,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, PlayerLeagueScheduleView):
            await interaction.response.defer()
            return

        view.mode_source_division = int(self.values[0])
        view.state.mode = None
        view.rebuild_mode_control()
        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view,
        )


class PlayerLeagueModeSelect(discord.ui.Select):
    def __init__(
        self,
        modes: list[str],
        source_division: int,
        match_division: int | None,
    ):
        is_own = match_division is not None and int(source_division) == int(match_division)
        description = (
            "Eigene Division"
            if is_own
            else "Fremdmodus · Zustimmung des Gegners nötig"
        )

        options = [
            discord.SelectOption(
                label=mode[:100],
                value=mode,
                description=description[:100],
            )
            for mode in modes[:25]
        ]

        if not options:
            options = [
                discord.SelectOption(
                    label="Keine Modi in dieser Division",
                    value="__none__",
                )
            ]
            disabled = True
        else:
            disabled = False

        super().__init__(
            placeholder=f"Modus aus Division {source_division} wählen",
            min_values=1,
            max_values=1,
            options=options,
            row=3,
            disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, PlayerLeagueScheduleView):
            await interaction.response.defer()
            return

        if self.values[0] == "__none__":
            await interaction.response.defer()
            return

        view.state.mode = self.values[0]
        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view,
        )


class PlayerModeDivisionButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Modus-Division",
            style=discord.ButtonStyle.secondary,
            row=4,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, PlayerLeagueScheduleView):
            await interaction.response.defer()
            return

        view.state.mode = None
        view.rebuild_mode_control(show_division_picker=True)
        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view,
        )


class PlayerLeagueSubmitButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Absenden",
            style=discord.ButtonStyle.success,
            row=4,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, PlayerLeagueScheduleView):
            await interaction.response.send_message(
                "Die Spielplanung konnte nicht verarbeitet werden.",
                ephemeral=True,
            )
            return

        await view.submit_schedule(interaction)


# =========================================================
# WRAPPER-VIEWS FÜR MATCHCENTER
# =========================================================
class PlayerLeagueScheduleView(LeagueScheduleView):
    """League-Planung aus /player mit gemeinsamer Fremdmodus-Regel."""

    def __init__(self, author_id: int):
        super().__init__(cog=None, author_id=author_id)

        self.mode_source_division: int | None = None
        self._last_match_division: int | None = None

        # Basis-Moduswahl und Basis-Buttons werden für /player ersetzt.
        for item in list(self.children):
            if isinstance(item, matchcenter.ModeSelect):
                self.remove_item(item)
                continue
            if isinstance(item, discord.ui.Button) and item.label in {"Absenden", "Zurück"}:
                self.remove_item(item)

        self.rebuild_mode_control(show_division_picker=True)
        self.add_item(PlayerModeDivisionButton())
        self.add_item(PlayerLeagueSubmitButton())
        self.add_item(BackToPlanFromLeagueButton())

    def _division_number(self) -> int | None:
        value = str(self.state.division or "").strip()
        try:
            return int(value.split()[-1])
        except Exception:
            return None

    def rebuild_mode_control(self, show_division_picker: bool = False) -> None:
        import term_offers

        for item in list(self.children):
            if isinstance(item, (PlayerModeDivisionSelect, PlayerLeagueModeSelect)):
                self.remove_item(item)

        match_division = self._division_number()
        if show_division_picker or self.mode_source_division is None:
            self.add_item(
                PlayerModeDivisionSelect(
                    self.mode_source_division or match_division,
                )
            )
            return

        modes = term_offers.get_division_modes(self.mode_source_division)
        self.add_item(
            PlayerLeagueModeSelect(
                modes,
                source_division=self.mode_source_division,
                match_division=match_division,
            )
        )

    def rebuild_dynamic_items(self):
        # Heimspieler-/Match-Auswahl aus dem Matchcenter beibehalten.
        super().rebuild_dynamic_items()

        # Bei Wechsel der Liga-Division automatisch wieder deren eigene Modi
        # anzeigen. Für Fremdmodi gibt es den Button "Modus-Division".
        current_division = self._division_number()
        if current_division != self._last_match_division:
            self._last_match_division = current_division
            self.mode_source_division = current_division
            self.state.mode = None
            self.rebuild_mode_control(
                show_division_picker=(current_division is None),
            )

    def render_summary(self) -> str:
        text = super().render_summary()
        division = self._division_number()
        mode = str(self.state.mode or "").strip()

        if self.mode_source_division:
            source_note = f"{self.mode_source_division}. Division"
            if division and self.mode_source_division != division:
                source_note += " · Fremdmodus"
            text += f"\n**Modusbereich:** {source_note}"

        if not division or not mode:
            return text

        try:
            import term_offers

            if not term_offers.is_mode_native_to_division(division, mode):
                origin = term_offers.mode_origin_label(mode, division)
                text += (
                    f"\n\n🤝 **Fremdmodus ({origin}):** Beim Absenden wird zuerst "
                    "die Zustimmung des Gegners eingeholt."
                )
        except Exception:
            pass

        return text

    async def submit_schedule(self, interaction: discord.Interaction) -> None:
        import term_offers

        s = self.state
        if not all(
            [
                s.division,
                s.match_label,
                s.player1,
                s.player2,
                s.mode,
                s.date_str,
                s.time_str,
            ]
        ):
            await interaction.response.send_message(
                "Es fehlen noch Angaben.",
                ephemeral=True,
            )
            return

        division = self._division_number()
        if division is None:
            await interaction.response.send_message(
                "Die Division konnte nicht gelesen werden.",
                ephemeral=True,
            )
            return

        try:
            when = matchcenter.parse_berlin_datetime(s.date_str, s.time_str)
        except Exception:
            await interaction.response.send_message(
                "Ungültiger Termin. Bitte Datum und Uhrzeit erneut auswählen.",
                ephemeral=True,
            )
            return

        if when <= dt.now(term_offers.BERLIN_TZ):
            await interaction.response.send_message(
                "Der Spieltermin muss in der Zukunft liegen.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        slot = term_offers.OfferSlot(index=0, when=when)

        try:
            is_native = await asyncio.to_thread(
                term_offers.is_mode_native_to_division,
                division,
                s.mode,
            )

            if not is_native:
                await term_offers.request_foreign_mode_approval_for_direct_schedule(
                    interaction=interaction,
                    division=division,
                    row_index=int(s.match_row_index),
                    home=s.player1,
                    away=s.player2,
                    mode=s.mode,
                    slot=slot,
                )
                return

            guild = interaction.guild or interaction.client.get_guild(matchcenter.GUILD_ID)
            if guild is None:
                guild = await interaction.client.fetch_guild(matchcenter.GUILD_ID)

            result = await term_offers.finalize_match_schedule(
                guild=guild,
                actor=interaction.user,
                division=division,
                row_index=int(s.match_row_index),
                home=s.player1,
                away=s.player2,
                mode=s.mode,
                slot=slot,
                source_label="Spielplanung",
            )

            await interaction.edit_original_response(
                content=(
                    "✅ **Spieltermin eingetragen**\n\n"
                    f"**{result['home']} vs. {result['away']}**\n"
                    f"📅 {slot.long_label}\n"
                    f"🎮 {result['mode']}\n"
                    f"🔗 {result['event_url'] or result['multistream_url']}"
                ),
                view=None,
            )
        except Exception as exc:
            await interaction.edit_original_response(
                content=f"❌ Fehler beim Erstellen: {exc}",
                view=None,
            )


class PlayerCupScheduleView(CupScheduleView):
    def __init__(self, author_id: int):
        super().__init__(cog=None, author_id=author_id)

        old_back = None
        for item in list(self.children):
            if isinstance(item, discord.ui.Button) and item.label == "Zurück":
                old_back = item
                break

        if old_back is not None:
            self.remove_item(old_back)

        self.add_item(BackToPlanFromCupButton())


# =========================================================
# MENÜ
# =========================================================
class PlanMenuView(PlanBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="League", style=discord.ButtonStyle.primary, row=0)
    async def league_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PlayerLeagueScheduleView(author_id=interaction.user.id)
        view.state.kind = "Termin League"

        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view,
            embed=None,
        )

    @discord.ui.button(label="Cup", style=discord.ButtonStyle.primary, row=0)
    async def cup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PlayerCupScheduleView(author_id=interaction.user.id)
        view.state.kind = "Termin Cup"

        await interaction.response.edit_message(
            content=view.render_summary(),
            view=view,
            embed=None,
        )

    @discord.ui.button(label="Async beantragen", style=discord.ButtonStyle.success, row=1)
    async def async_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_async_request_from_player(interaction)

    @discord.ui.button(label="◀ Zurück", style=discord.ButtonStyle.secondary, row=2)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from player import PlayerMenuView

        await interaction.response.edit_message(
            embed=menu_embed("Spielermenü", "Wähle einen Bereich."),
            view=PlayerMenuView(owner_id=interaction.user.id),
            content=None,
        )
