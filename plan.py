import discord

from asyncplan import open_async_request_from_player


class PlanBaseView(discord.ui.View):
    def __init__(self, owner_id: int, timeout: float = 180):
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


class PlanMenuView(PlanBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="League", style=discord.ButtonStyle.primary, row=0)
    async def league_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content=(
                "**Spiel planen → League**\n"
                "Der Async-Button ist wieder aktiv.\n"
                "Den League-Termin-Flow kannst du jetzt separat wieder anbinden, falls du ihn bereits in `plan.py` erweitert hast."
            ),
            view=PlanPlaceholderView(
                owner_id=interaction.user.id,
                back_content="**Spiel planen**\nWähle einen Bereich:",
            ),
        )

    @discord.ui.button(label="Cup", style=discord.ButtonStyle.primary, row=0)
    async def cup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content=(
                "**Spiel planen → Cup**\n"
                "Den Cup-Termin-Flow kannst du jetzt separat wieder anbinden, falls du ihn bereits in `plan.py` erweitert hast."
            ),
            view=PlanPlaceholderView(
                owner_id=interaction.user.id,
                back_content="**Spiel planen**\nWähle einen Bereich:",
            ),
        )

    @discord.ui.button(label="Async beantragen", style=discord.ButtonStyle.success, row=1)
    async def async_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_async_request_from_player(interaction)

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=2)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from player import PlayerMenuView

        await interaction.response.edit_message(
            content="**Spielermenü**\nWähle einen Bereich:",
            view=PlayerMenuView(owner_id=interaction.user.id),
        )


class PlanPlaceholderView(PlanBaseView):
    def __init__(self, owner_id: int, back_content: str):
        super().__init__(owner_id)
        self.back_content = back_content

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content=self.back_content,
            view=PlanMenuView(owner_id=interaction.user.id),
        )
