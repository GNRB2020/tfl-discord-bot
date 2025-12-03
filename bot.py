import discord
import asyncio
from discord.ext import commands
from discord import app_commands
from shared import TOKEN, GUILD_ID, WB, sheets_required

# alle deine bestehenden Bot-Klassen, Views, Befehle usw.
# (Result, Streich, Rest, Playerexit, Spielplan usw.)
# können hier unverändert rein – ich kürze das hier.

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

client = commands.Bot(command_prefix="/", intents=intents)
tree = client.tree


@client.event
async def on_ready():
    print("Bot ist online!")
    await tree.sync(guild=discord.Object(id=GUILD_ID))
    print("Slash-Commands synchronisiert")


# ALLE deine bisherigen /commands bleiben hier


client.run(TOKEN)
