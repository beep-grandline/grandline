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
    bot.add_view(RolePicker())
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


# define the view with buttons — custom_id is permanent, survives restarts
class RolePicker(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # timeout=None = never expires

    @discord.ui.button(label="🏴‍☠️ Pirate", style=discord.ButtonStyle.secondary, custom_id="role_pirate")
    async def pirate(self, interaction: discord.Interaction, button: discord.ui.Button):
        await assign_role(interaction, "Pirate")

    @discord.ui.button(label="⚓ Marine", style=discord.ButtonStyle.secondary, custom_id="role_marine")
    async def marine(self, interaction: discord.Interaction, button: discord.ui.Button):
        await assign_role(interaction, "Marine")

    @discord.ui.button(label="👨 Civilian", style=discord.ButtonStyle.secondary, custom_id="role_civ")
    async def civilian(self, interaction: discord.Interaction, button: discord.ui.Button):
        await assign_role(interaction, "Civilian")

    @discord.ui.button(label="🗡️ Revolutionary", style=discord.ButtonStyle.secondary, custom_id="role_revo")
    async def revolutionary(self, interaction: discord.Interaction, button: discord.ui.Button):
        await assign_role(interaction, "Revolutionary")


async def assign_role(interaction: discord.Interaction, role_name: str):
    role = discord.utils.get(interaction.guild.roles, name=role_name)
    if not role:
        await interaction.response.send_message(
            f"Role '{role_name}' doesn't exist on this server.", ephemeral=True
        )
        return
    await interaction.user.add_roles(role)
    await interaction.response.send_message(
        f"{role_name} role successfully added.", ephemeral=True
    )

@bot.tree.command(name="rolepicker", description="Post the role picker message", guild=MY_GUILD)
async def rolepicker(interaction: discord.Interaction):
    role_names = [r.name for r in interaction.user.roles]
    if "Admin" not in role_names:
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    embed = discord.Embed(
        title="Choose Your Crew",
        description="Pick a crew to join. You can change it later.",
        color=0x1a3f6b
    )
    await interaction.channel.send(embed=embed, view=RolePicker())
    await interaction.followup.send("Posted!", ephemeral=True)

# @bot.tree.command(name="sail", description="Register your character", guild=MY_GUILD)
# @discord.app_commands.describe(job="Island to sail to")
# async def sail(interaction: discord.Interaction, job: str):
#     uid = str(interaction.user.id)
#     name = interaction.user.name
#     result = game.sail(uid, name, destination)
#     if result["ok"]:
#         await interaction.response.send_message(result["message"])
#     else:
#         await interaction.response.send_message(result["error"], ephemeral=True)

@bot.tree.command(name="position", description="Check your position", guild=MY_GUILD)
async def position(interaction: discord.Interaction):
    await interaction.response.send_message("You are at Twin Capes.")
