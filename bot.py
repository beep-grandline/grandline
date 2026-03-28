import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")

@bot.tree.command(name="sail", description="Sail to an island")
async def sail(interaction: discord.Interaction, destination: str):
    await interaction.response.send_message(f"Setting sail for {destination}!")

@bot.tree.command(name="position", description="Check your position")
async def position(interaction: discord.Interaction):
    await interaction.response.send_message("You are at Twin Capes.")
