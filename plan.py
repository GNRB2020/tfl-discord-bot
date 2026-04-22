import discord

from asyncplan import open_async_request_from_player
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
# WRAPPER-VIEWS FÜR MATCHCENTER
# =========================================================
class PlayerLeagueScheduleView(LeagueScheduleView):
    def __init__(self, author_id: int):
        super().__init__(cog=None, author_id=author_id)

        old_back = None
        for item in list(self.children):
            if isinstance(item, discord.ui.Button) and item.label == "Zurück":
                old_back = item
                break

        if old_back is not None:
            self.remove_item(old_back)

        self.add_item(BackToPlanFromLeagueButton())


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
