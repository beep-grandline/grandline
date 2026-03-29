import discord
from discord.ext import commands
import game
import os

MY_GUILD = discord.Object(id=1487526877185704107)

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    bot.tree.clear_commands(guild=None)        # clear global
    await bot.tree.sync()                       # push the empty list globally
    synced = await bot.tree.sync(guild=MY_GUILD)
    print(f"Synced {len(synced)} commands: {[c.name for c in synced]}")
    print(f"Logged in as {bot.user}")

# Listcommands
@bot.tree.command(name="help", description="Show available commands", guild=MY_GUILD)
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="LARP Piece Commands", color=0x1a3f6b)
    embed.add_field(name="/map", value="Send map", inline=False)
    embed.add_field(name="/sail", value="Sail to an island", inline=False)
    embed.add_field(name="/position", value="Check your current position", inline=False)
    embed.add_field(name="/help", value="Show this message", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# Base map img generator, to expand once we get a better sense of rendering
@bot.tree.command(name="map", description="Post the current map", guild=MY_GUILD)
async def map_cmd(interaction: discord.Interaction):
    if not os.path.exists("snapshot.png"):
        await interaction.response.send_message(
            "No snapshot yet.", ephemeral=True
        )
        return
    await interaction.response.defer()
    file = discord.File("snapshot.png", filename="map.png")
    embed = discord.Embed(title="Grand Line: Paradise", color=0x1a3f6b)
    embed.set_image(url="attachment://map.png")
    await interaction.followup.send(file=file, embed=embed, ephemeral=True)


@bot.tree.command(name="sail", description="Sail to an island", guild=MY_GUILD)
async def sail(interaction: discord.Interaction, destination: str):
    await interaction.response.send_message(f"Setting sail for {destination}!")

@bot.tree.command(name="position", description="Check your position", guild=MY_GUILD)
async def position(interaction: discord.Interaction):
    await interaction.response.send_message("You are at Twin Capes.")

