import discord
from discord.ext import commands
import os

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    await bot.tree.sync(guild=1487526877185704107)
    print(f"Logged in as {bot.user}")


@bot.tree.command(name="map", description="Post the current map")
async def map_cmd(interaction: discord.Interaction):
    if not os.path.exists("snapshot.png"):
        await interaction.response.send_message(
            "No snapshot yet.", ephemeral=True
        )
        return
    await interaction.response.defer()
    file = discord.File("snapshot.png", filename="map.png")
    embed = discord.Embed(title="Grand Line — Current State", color=0x1a3f6b)
    embed.set_image(url="attachment://map.png")
    await interaction.followup.send(file=file, embed=embed)

@bot.tree.command(name="sail", description="Sail to an island")
async def sail(interaction: discord.Interaction, destination: str):
    await interaction.response.send_message(f"Setting sail for {destination}!")

@bot.tree.command(name="position", description="Check your position")
async def position(interaction: discord.Interaction):
    await interaction.response.send_message("You are at Twin Capes.")

