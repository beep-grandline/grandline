import discord
from discord.ext import commands
import game
import os
import db
import map_render

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
# @bot.tree.command(name="map", description="Post the current map", guild=MY_GUILD)
# async def map_cmd(interaction: discord.Interaction):
#     if not os.path.exists("snapshot.png"):
#         await interaction.response.send_message(
#             "No snapshot yet.", ephemeral=True
#         )
#         return
#     await interaction.response.defer(ephemeral=True)
#     file = discord.File("snapshot.png", filename="map.png")
#     embed = discord.Embed(title="Grand Line: Paradise", color=0x1a3f6b)
#     embed.set_image(url="attachment://map.png")
#     await interaction.followup.send(file=file, embed=embed)

@bot.tree.command(name="register", description="Register your character", guild=MY_GUILD)
@discord.app_commands.describe(job="Your role (pirate, marine, etc)")
async def register(interaction: discord.Interaction, job: str):
    uid = str(interaction.user.id)
    name = interaction.user.name
    db.upsert_player(uid, name)
    await interaction.response.send_message(
        f"Welcome to the Grand Line, {name}!", ephemeral=True
    )

# @bot.tree.command(name="sail", description="Register your character", guild=MY_GUILD)
# @discord.app_commands.describe(job="Register your character")
# async def sail(interaction: discord.Interaction, job: str):
#     uid = str(interaction.user.id)
#     name = interaction.user.name

#     db.
    
#     if result["ok"]:
#         await interaction.response.send_message(result["message"])
#     else:
#         await interaction.response.send_message(result["error"], ephemeral=True)

@bot.tree.command(name="position", description="Check your position", guild=MY_GUILD)
async def position(interaction: discord.Interaction):
    await interaction.response.send_message("You are at Twin Capes.")








@bot.tree.command(name="crew", description="Create a new crew", guild=MY_GUILD)
@discord.app_commands.describe(
    name="Name of the crew",
    color="Hex color code (e.g. ff0000 for red)"
)
async def crew(interaction: discord.Interaction, name: str, color: str):
    await interaction.response.defer(ephemeral=True)

    color = color.strip().lstrip("#")

    if len(color) != 6:
        await interaction.followup.send("Invalid color — use a 6 digit hex like `ff0000`.", ephemeral=True)
        return
    try:
        color_int = int(color, 16)
    except ValueError:
        await interaction.followup.send("Invalid color — use a 6 digit hex like `ff0000`.", ephemeral=True)
        return

    if db.get_crew_by_name(name):
        await interaction.followup.send(f"A crew named **{name}** already exists.", ephemeral=True)
        return

    if discord.utils.get(interaction.guild.roles, name=name):
        await interaction.followup.send(f"A role named **{name}** already exists.", ephemeral=True)
        return

    role = await interaction.guild.create_role(
        name=name,
        color=discord.Color(color_int),
        mentionable=True
    )

    bot_top = interaction.guild.me.top_role
    positions = {role: bot_top.position - 1}
    await interaction.guild.edit_role_positions(positions)

    db.upsert_crew(str(role.id), name)

    await interaction.followup.send(f"Crew **{name}** created with color `#{color}`!", ephemeral=True)




# To send a picture of the map
@bot.tree.command(name="map", description="View your current area", guild=MY_GUILD)
async def map_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    uid = str(interaction.user.id)
    path = map_render.render_map(uid, radius=5)
    if not path:
        await interaction.followup.send("You are not registered yet.", ephemeral=True)
        return
    file = discord.File(path, filename="map.png")
    embed = discord.Embed(title="Your Position", color=0x1a3f6b)
    embed.set_image(url="attachment://map.png")
    await interaction.followup.send(file=file, embed=embed, ephemeral=True)





# MONEY COMMANDS
@bot.tree.command(name="purse", description="Check how much money you have", guild=MY_GUILD)
async def position(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    berry = db.get_berry(uid)
    if berry == 0:
        await interaction.response.send_message(f"You are broke.", ephemeral=True)
    else:
        await interaction.response.send_message(f"You have ฿**{berry}**.", ephemeral=True)

@bot.tree.command(name="setberry", description="Check how much money you have", guild=MY_GUILD)
async def position(interaction: discord.Interaction, amount: int):
    uid = str(interaction.user.id)
    berry = db.set_berry(uid, amount)
    await interaction.response.send_message(f"Successfully set berry.", ephemeral=True)




# ──── ROLE PICKER ────────────────────────────────────────────────────────────
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
    crew_roles = ["Pirate", "Marine", "Civilian", "Revolutionary"]
    
    # check if they already have one of the crew roles
    for rname in crew_roles:
        existing = discord.utils.get(interaction.guild.roles, name=rname)
        if existing and existing in interaction.user.roles:
            await interaction.response.send_message(
                f"You already have the {rname} role. You can't change it.", ephemeral=True
            )
            return

    role = discord.utils.get(interaction.guild.roles, name=role_name)
    if not role:
        await interaction.response.send_message(
            f"Role '{role_name}' doesn't exist on this server.", ephemeral=True
        )
        return
    await interaction.user.add_roles(role)
    await interaction.response.send_message(
        f"You are now a {role_name}!", ephemeral=True
    )

@bot.tree.command(name="rolepicker", description="Post the role picker message", guild=MY_GUILD)
async def rolepicker(interaction: discord.Interaction):
    role_names = [r.name for r in interaction.user.roles]
    if "Admin" not in role_names:
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    msg = "# Choose Your Allegiance!"
    await interaction.channel.send(msg, view=RolePicker())
    await interaction.followup.send("Posted!", ephemeral=True)
