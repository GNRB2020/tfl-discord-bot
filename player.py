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
            content="**Spielermenü → Spiel planen**\nHier kommt später die Navigation rein.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                title="**Spielermenü → Spiel planen**",
                text="Hier kommt später die Navigation rein.",
                back_view=PlayerMenuView(owner_id=interaction.user.id),
                back_content="**Spielermenü**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Ergebnis melden", style=discord.ButtonStyle.success, row=0)
    async def result_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Ergebnis melden**\nHier kommt später die Navigation rein.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                title="**Spielermenü → Ergebnis melden**",
                text="Hier kommt später die Navigation rein.",
                back_view=PlayerMenuView(owner_id=interaction.user.id),
                back_content="**Spielermenü**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Qualifikation", style=discord.ButtonStyle.secondary, row=1)
    async def qualification_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Qualifikation**\nHier kommt später die Navigation rein.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                title="**Spielermenü → Qualifikation**",
                text="Hier kommt später die Navigation rein.",
                back_view=PlayerMenuView(owner_id=interaction.user.id),
                back_content="**Spielermenü**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Saisonmeldung", style=discord.ButtonStyle.secondary, row=1)
    async def season_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Saisonmeldung**\nHier kommt später die Navigation rein.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                title="**Spielermenü → Saisonmeldung**",
                text="Hier kommt später die Navigation rein.",
                back_view=PlayerMenuView(owner_id=interaction.user.id),
                back_content="**Spielermenü**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Einstellungen", style=discord.ButtonStyle.secondary, row=1)
    async def settings_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Einstellungen**\nHier kommt später die Navigation rein.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                title="**Spielermenü → Einstellungen**",
                text="Hier kommt später die Navigation rein.",
                back_view=PlayerMenuView(owner_id=interaction.user.id),
                back_content="**Spielermenü**\nWähle einen Bereich:"
            )
        )


# =========================================================
# Allgemeine Platzhalter-Detailansicht
# =========================================================
class PlaceholderView(PlayerBaseView):
    def __init__(self, owner_id: int, title: str, text: str, back_view: discord.ui.View, back_content: str):
        super().__init__(owner_id)
        self.title = title
        self.text = text
        self.back_view = back_view
        self.back_content = back_content

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=0)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content=self.back_content,
            view=self.back_view
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
            content="**Info → Ergebnisse/Tabelle**\nWähle einen Bereich:",
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
        await interaction.response.edit_message(
            content="**Info → Meldestatus → Meiner**\nHier kommt später der Inhalt rein.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                title="**Info → Meldestatus → Meiner**",
                text="Hier kommt später der Inhalt rein.",
                back_view=MeldestatusView(owner_id=interaction.user.id),
                back_content="**Info → Meldestatus**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="League", style=discord.ButtonStyle.primary, row=0)
    async def league_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Meldestatus → League**\nHier kommt später der Inhalt rein.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                title="**Info → Meldestatus → League**",
                text="Hier kommt später der Inhalt rein.",
                back_view=MeldestatusView(owner_id=interaction.user.id),
                back_content="**Info → Meldestatus**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Cup", style=discord.ButtonStyle.primary, row=0)
    async def cup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Meldestatus → Cup**\nHier kommt später der Inhalt rein.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                title="**Info → Meldestatus → Cup**",
                text="Hier kommt später der Inhalt rein.",
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
        await interaction.response.edit_message(
            content="**Info → Qualifikation → Quali 1**\nHier kommt später der Inhalt rein.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                title="**Info → Qualifikation → Quali 1**",
                text="Hier kommt später der Inhalt rein.",
                back_view=InfoQualifikationView(owner_id=interaction.user.id),
                back_content="**Info → Qualifikation**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Quali 2", style=discord.ButtonStyle.primary, row=0)
    async def quali2_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Qualifikation → Quali 2**\nHier kommt später der Inhalt rein.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                title="**Info → Qualifikation → Quali 2**",
                text="Hier kommt später der Inhalt rein.",
                back_view=InfoQualifikationView(owner_id=interaction.user.id),
                back_content="**Info → Qualifikation**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Gesamt", style=discord.ButtonStyle.primary, row=0)
    async def gesamt_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Qualifikation → Gesamt**\nHier kommt später der Inhalt rein.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                title="**Info → Qualifikation → Gesamt**",
                text="Hier kommt später der Inhalt rein.",
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
# Restprogramm
# =========================================================
class RestprogrammView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="Eigenes", style=discord.ButtonStyle.primary, row=0)
    async def eigenes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Restprogramm → Eigenes**\nHier kommt später der Inhalt rein.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                title="**Info → Restprogramm → Eigenes**",
                text="Hier kommt später der Inhalt rein.",
                back_view=RestprogrammView(owner_id=interaction.user.id),
                back_content="**Info → Restprogramm**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Andere", style=discord.ButtonStyle.primary, row=0)
    async def andere_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Restprogramm → Andere**\nHier kommt später der Inhalt rein.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                title="**Info → Restprogramm → Andere**",
                text="Hier kommt später der Inhalt rein.",
                back_view=RestprogrammView(owner_id=interaction.user.id),
                back_content="**Info → Restprogramm**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Info**\nWähle einen Bereich:",
            view=InfoMenuView(owner_id=interaction.user.id)
        )


# =========================================================
# Streichmodus
# =========================================================
class StreichmodusView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="Eigene Division", style=discord.ButtonStyle.primary, row=0)
    async def eigene_division_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Streichmodus → Eigene Division**\nHier kommt später der Inhalt rein.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                title="**Info → Streichmodus → Eigene Division**",
                text="Hier kommt später der Inhalt rein.",
                back_view=StreichmodusView(owner_id=interaction.user.id),
                back_content="**Info → Streichmodus**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Andere Divisionen", style=discord.ButtonStyle.primary, row=0)
    async def andere_divisionen_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Streichmodus → Andere Divisionen**\nHier kommt später der Inhalt rein.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                title="**Info → Streichmodus → Andere Divisionen**",
                text="Hier kommt später der Inhalt rein.",
                back_view=StreichmodusView(owner_id=interaction.user.id),
                back_content="**Info → Streichmodus**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Info**\nWähle einen Bereich:",
            view=InfoMenuView(owner_id=interaction.user.id)
        )


# =========================================================
# Ergebnisse / Tabelle
# =========================================================
class ErgebnisseTabelleView(PlayerBaseView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)

    @discord.ui.button(label="1. Div", style=discord.ButtonStyle.primary, row=0)
    async def div1_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Ergebnisse/Tabelle → 1. Div**\nHier kommt später der Inhalt rein.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                title="**Info → Ergebnisse/Tabelle → 1. Div**",
                text="Hier kommt später der Inhalt rein.",
                back_view=ErgebnisseTabelleView(owner_id=interaction.user.id),
                back_content="**Info → Ergebnisse/Tabelle**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="2. Div", style=discord.ButtonStyle.primary, row=0)
    async def div2_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Ergebnisse/Tabelle → 2. Div**\nHier kommt später der Inhalt rein.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                title="**Info → Ergebnisse/Tabelle → 2. Div**",
                text="Hier kommt später der Inhalt rein.",
                back_view=ErgebnisseTabelleView(owner_id=interaction.user.id),
                back_content="**Info → Ergebnisse/Tabelle**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="3. Div", style=discord.ButtonStyle.primary, row=0)
    async def div3_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Ergebnisse/Tabelle → 3. Div**\nHier kommt später der Inhalt rein.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                title="**Info → Ergebnisse/Tabelle → 3. Div**",
                text="Hier kommt später der Inhalt rein.",
                back_view=ErgebnisseTabelleView(owner_id=interaction.user.id),
                back_content="**Info → Ergebnisse/Tabelle**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="4. Div", style=discord.ButtonStyle.primary, row=1)
    async def div4_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Ergebnisse/Tabelle → 4. Div**\nHier kommt später der Inhalt rein.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                title="**Info → Ergebnisse/Tabelle → 4. Div**",
                text="Hier kommt später der Inhalt rein.",
                back_view=ErgebnisseTabelleView(owner_id=interaction.user.id),
                back_content="**Info → Ergebnisse/Tabelle**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="5. Div", style=discord.ButtonStyle.primary, row=1)
    async def div5_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Ergebnisse/Tabelle → 5. Div**\nHier kommt später der Inhalt rein.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                title="**Info → Ergebnisse/Tabelle → 5. Div**",
                text="Hier kommt später der Inhalt rein.",
                back_view=ErgebnisseTabelleView(owner_id=interaction.user.id),
                back_content="**Info → Ergebnisse/Tabelle**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="6. Div", style=discord.ButtonStyle.primary, row=1)
    async def div6_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Ergebnisse/Tabelle → 6. Div**\nHier kommt später der Inhalt rein.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                title="**Info → Ergebnisse/Tabelle → 6. Div**",
                text="Hier kommt später der Inhalt rein.",
                back_view=ErgebnisseTabelleView(owner_id=interaction.user.id),
                back_content="**Info → Ergebnisse/Tabelle**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Cup", style=discord.ButtonStyle.primary, row=2)
    async def cup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Info → Ergebnisse/Tabelle → Cup**\nHier kommt später der Inhalt rein.",
            view=PlaceholderView(
                owner_id=interaction.user.id,
                title="**Info → Ergebnisse/Tabelle → Cup**",
                text="Hier kommt später der Inhalt rein.",
                back_view=ErgebnisseTabelleView(owner_id=interaction.user.id),
                back_content="**Info → Ergebnisse/Tabelle**\nWähle einen Bereich:"
            )
        )

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.secondary, row=3)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="**Spielermenü → Info**\nWähle einen Bereich:",
            view=InfoMenuView(owner_id=interaction.user.id)
        )


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
