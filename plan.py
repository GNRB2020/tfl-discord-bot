
import discord

from asyncplan import open_async_request_from_player
from matchcenter import LeagueScheduleView, CupScheduleView


class PlanBaseView(discord.ui.View):
    def __init__(self, owner_id: int, timeout: float = 1800):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Dieses Menü gehört nicht dir.", ephemeral=True)
            return False
        return True


class PlanMenuView(PlanBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="League", style=discord.ButtonStyle.primary, row=0)
    async def league_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = LeagueScheduleView(None, interaction.user.id)
        view.state.kind = "Termin League"
        await interaction.response.edit_message(content=view.render_summary(), view=view)

    @discord.ui.button(label="Cup", style=discord.ButtonStyle.primary, row=0)
    async def cup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = CupScheduleView(None, interaction.user.id)
        view.state.kind = "Termin Cup"
        await interaction.response.edit_message(content=view.render_summary(), view=view)

    @discord.ui.button(label="Async beantragen", style=discord.ButtonStyle.success, row=1)
    async def async_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_async_request_from_player(interaction, back_target="plan")

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=2)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from player import PlayerMenuView
        await interaction.response.edit_message(content="**Spielermenü**\nWähle einen Bereich:", view=PlayerMenuView(owner_id=interaction.user.id))
