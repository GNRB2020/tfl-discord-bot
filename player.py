import os
import discord
from discord import app_commands
from discord.ext import commands

GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))


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


class PlayerMenuView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="Info", style=discord.ButtonStyle.secondary, row=0)
    async def info_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Info folgt.", ephemeral=True)

    @discord.ui.button(label="Spiel planen", style=discord.ButtonStyle.primary, row=0)
    async def plan_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Spiel planen folgt.", ephemeral=True)

    @discord.ui.button(label="Ergebnis melden", style=discord.ButtonStyle.success, row=0)
    async def result_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Ergebnis melden folgt.", ephemeral=True)

    @discord.ui.button(label="Qualifikation", style=discord.ButtonStyle.secondary, row=1)
    async def qualification_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Qualifikation folgt.", ephemeral=True)

    @discord.ui.button(label="Saisonmeldung", style=discord.ButtonStyle.secondary, row=1)
    async def season_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Saisonmeldung folgt.", ephemeral=True)

    @discord.ui.button(label="Einstellungen", style=discord.ButtonStyle.secondary, row=1)
    async def settings_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Einstellungen folgen.", ephemeral=True)


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
