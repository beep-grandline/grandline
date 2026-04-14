#!/usr/bin/python3

import discord
from discord.ext import commands
from dotenv import load_dotenv
import game
import os
import db
import map_render
import asyncio
from typing import Literal

load_dotenv()

# Bot params 
MY_GUILD = discord.Object(id=1487526877185704107) # Currently targets our server
GAME_ADMIN = "Admin" # Set admin role here, change if we give special name

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# 
@bot.event
async def on_ready():
    synced = await bot.tree.sync(guild=MY_GUILD)
    print(f"Synced {len(synced)} commands")
    print(f"Logged in as {bot.user}")

@bot.event
async def on_ready():
    bot.add_view(RolePicker())
    bot.tree.clear_commands(guild=None)        # clear global
    await bot.tree.sync()                       # push the empty list globally
    synced = await bot.tree.sync(guild=MY_GUILD)
    print(f"Synced {len(synced)} commands: {[c.name for c in synced]}")
    print(f"Logged in as {bot.user}")









# HELP LIST, NEED TO UPDATE
HELP_PAGES = {
    "map": {
        "title": "🗺️ Map & Navigation",
        "fields": [
            ("/map", "Shows your current viewport. Updates your position on the map."),
            ("/map roll", "Shows reachable hexes this turn. White dots = standard, red dots = wind-boosted."),
        ]
    },
    "travel": {
        "title": "⛵ Travel",
        "fields": [
            ("/sail <directions>", "Move your ship. e.g. `/sail n ne ne se`\nDirections: `n s ne sw se nw`"),
            ("/sail to <island>", "Pathfind to a destination. Bot will preview cost and ask to confirm."),
            ("/sail stop", "Cancel your queued route."),
        ]
    },
    "rolls": {
        "title": "🎲 Rolls",
        "fields": [
            ("/rolls", "Check your current roll bank and time until next roll."),
            ("Roll cap", "Max 12 rolls banked. One roll earned every 2 hours."),
            ("Wind bonus", "Sailing with the wind costs fewer rolls. Check `/map roll` to see wind direction."),
        ]
    },
    "devil fruits": {
        "title": "<:mera:1493493605267017808> Devil Fruits",
        "fields": [
            ("/df <name>", "Look up a devil fruit. Autocompletes as you type."),
            ("/df list <type>", "List all fruits of a given type: Paramecia, Zoan, Logia."),
        ]
    },
}

@bot.tree.command(name="help", description="Help topics", guild=MY_GUILD)
@discord.app_commands.describe(topic="What do you need help with?")
async def help_command(
    interaction: discord.Interaction,
    topic: Literal["map", "travel", "rolls", "devil fruits"] = None
):
    if topic is None:
        embed = discord.Embed(
            title="📖 Help",
            description="Use `/help <topic>` for details on a specific topic.",
            color=0x3a7ebf,
        )
        for key, page in HELP_PAGES.items():
            embed.add_field(
                name=page["title"],
                value=" • ".join(f"`{f[0]}`" for f in page["fields"]),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    page = HELP_PAGES[topic]
    embed = discord.Embed(title=page["title"], color=0x3a7ebf)
    for name, value in page["fields"]:
        embed.add_field(name=name, value=value, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)











# PLAYER 
@bot.tree.command(name="register", description="Register your character", guild=MY_GUILD)
@discord.app_commands.describe(job="Your role (pirate, marine, etc)")
async def register(interaction: discord.Interaction, job: str):
    uid = str(interaction.user.id)
    name = interaction.user.name
    db.upsert_player(uid, name)
    await interaction.response.send_message(
        f"Welcome to the Grand Line, {name}!", ephemeral=True
    )

# MAP 
@bot.tree.command(name="position", description="Check your current position", guild=MY_GUILD)
async def position(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    pos = db.get_player_position(uid)
    if not pos:
        await interaction.response.send_message(
            "You are not registered yet. Use `/register` first.", ephemeral=True
        )
        return
    q, r = pos
    await interaction.response.send_message(
        f"Your current position is **q={q}, r={r}**.", ephemeral=True
    )



# Teleport, for admin use
@bot.tree.command(name="teleport", description="Drop a player to a specific position (admin only)", guild=MY_GUILD)
@discord.app_commands.describe(
    target="The user to teleport",
    q="Hex q coordinate",
    r="Hex r coordinate",
)
async def teleport(interaction: discord.Interaction, target: discord.Member, q: int, r: int):
    role_names = [role.name for role in interaction.user.roles]
    if GAME_ADMIN not in role_names:
        await interaction.response.send_message(
            f"Only **{GAME_ADMIN}s** can teleport players.", ephemeral=True
        )
        return
 
    uid = str(target.id)
 
    if not db.get_player(uid):
        await interaction.response.send_message(
            f"**{target.display_name}** is not registered yet.", ephemeral=True
        )
        return
 
    db.update_player_position(uid, q, r)
    await interaction.response.send_message(
        f"Teleported **{target.display_name}** to q={q}, r={r}."
    )

@bot.tree.command(name="crew", description="Create a new crew", guild=MY_GUILD)
@discord.app_commands.describe(
    name="Name of the crew",
    captain="The crew's captain",
    color="Hex color code (e.g. ff0000 for red)"
)
async def crew(interaction: discord.Interaction, name: str, captain: discord.Member, color: str):
    await interaction.response.defer()

    color = color.strip().lstrip("#")
    if len(color) != 6:
        await interaction.followup.send("Invalid color — use a 6 digit hex like `ff0000`.", ephemeral=True)
        return
    try:
        color_int = int(color, 16)
    except ValueError:
        await interaction.followup.send("Invalid color — use a 6 digit hex like `ff0000`.", ephemeral=True)
        return

    # Case-insensitive crew name check (db is the reference for proper casing)
    if db.get_crew_by_name(name):
        await interaction.followup.send(f"A crew named **{name}** already exists.", ephemeral=True)
        return

    existing_role = discord.utils.find(
        lambda r: r.name.lower() == name.lower(),
        interaction.guild.roles
    )
    if existing_role:
        await interaction.followup.send(f"A role named **{name}** already exists.", ephemeral=True)
        return

    # Check captain isn't already in a crew
    captain_player = db.get_player(str(captain.id))
    if captain_player and captain_player["crew_id"]:
        existing_crew = db.get_crew(captain_player["crew_id"])
        existing_name = existing_crew["name"] if existing_crew else "a crew"
        await interaction.followup.send(
            f"**{captain.display_name}** is the captain of **{existing_name}**.",
            ephemeral=True
        )
        return

    role = await interaction.guild.create_role(
        name=name,
        color=discord.Color(color_int),
        mentionable=True
    )
    bot_top = interaction.guild.me.top_role
    await interaction.guild.edit_role_positions({role: bot_top.position})

    db.upsert_crew(str(role.id), name, captain_id=str(captain.id))
    db.set_player_crew(str(captain.id), str(role.id))

    await captain.add_roles(role)
    await interaction.followup.send(
        f"Crew **{name}** created with color `#{color}`! Captain: {captain.mention}"
    )


@bot.tree.command(name="disband", description="Disband a crew", guild=MY_GUILD)
@discord.app_commands.describe(name="Name of the crew to disband")
async def disband(interaction: discord.Interaction, name: str):
    await interaction.response.defer()

    role_names = [r.name for r in interaction.user.roles]
    if GAME_ADMIN not in role_names:
        await interaction.followup.send(f"Only **{GAME_ADMIN}s** can disband crews.", ephemeral=True)
        return

    # get_crew_by_name uses LOWER() — case-insensitive match
    # crew["name"] is used for display so proper casing always comes from db
    crew = db.get_crew_by_name(name)
    if not crew:
        await interaction.followup.send(f"No crew named **{name}** found.", ephemeral=True)
        return

    role = interaction.guild.get_role(int(crew["id"]))
    if role:
        await role.delete()

    db.delete_crew(crew["id"])

    await interaction.followup.send(f"Crew **{crew['name']}** has been disbanded.")


























class JoinRequestView(discord.ui.View):
    def __init__(self, applicant: discord.Member, crew_id: str, crew_name: str):
        super().__init__(timeout=300)
        self.applicant = applicant
        self.crew_id   = crew_id
        self.crew_name = crew_name
 
    async def _resolve(self, interaction: discord.Interaction, accepted: bool):
        crew = db.get_crew(self.crew_id)
        if not crew or str(interaction.user.id) != crew["captain_id"]:
            await interaction.response.send_message(
                "Only the captain can respond to this.", ephemeral=True
            )
            return
 
        self.stop()
        for child in self.children:
            child.disabled = True
 
        if accepted:
            db.set_player_crew(str(self.applicant.id), self.crew_id)
            role = interaction.guild.get_role(int(self.crew_id))
            if role:
                await self.applicant.add_roles(role)
            await interaction.response.edit_message(
                content=f"✓ {self.applicant.mention} has joined **{self.crew_name}**!",
                view=self,
                embed=None,
            )
        else:
            await interaction.response.edit_message(
                content=f"✗ {self.applicant.mention}'s request to join **{self.crew_name}** was denied.",
                view=self,
                embed=None,
            )
 
    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="join_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._resolve(interaction, accepted=True)
 
    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, custom_id="join_deny")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._resolve(interaction, accepted=False)
 
 
# ── /join ─────────────────────────────────────────────────────────────────────
 
@bot.tree.command(name="join", description="Request to join a crew", guild=MY_GUILD)
@discord.app_commands.describe(crew="Name of the crew you want to join")
async def join_cmd(interaction: discord.Interaction, crew: str):
    await interaction.response.defer()
    uid = str(interaction.user.id)
 
    if not db.get_player(uid):
        await interaction.followup.send("You need to register first with `/register`.")
        return
 
    player = db.get_player(uid)
    if player["crew_id"]:
        current = db.get_crew(player["crew_id"])
        name = current["name"] if current else "a crew"
        await interaction.followup.send(f"You are already in **{name}**. Use `/leave` first.")
        return
 
    crew_row = db.get_crew_by_name(crew)
    if not crew_row:
        await interaction.followup.send(f"No crew named **{crew}** found.")
        return
 
    crew_id    = crew_row["id"]
    crew_name  = crew_row["name"]
    captain_id = crew_row["captain_id"]
 
    if not captain_id:
        await interaction.followup.send(
            f"**{crew_name}** has no captain set — ask an admin to fix this."
        )
        return
 
    try:
        captain = await interaction.guild.fetch_member(int(captain_id))
    except discord.NotFound:
        await interaction.followup.send("Could not find the captain in this server.")
        return
 
    view = JoinRequestView(
        applicant=interaction.user,
        crew_id=crew_id,
        crew_name=crew_name,
    )
 
    embed = discord.Embed(
        title="Crew Join Request",
        description=f"{interaction.user.mention} wants to join **{crew_name}**.",
        color=0x1a3f6b,
    )
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
 
    # Posted in the channel where the command was used, pings the captain
    await interaction.followup.send(
        content=f"{captain.mention} — new join request!",
        embed=embed,
        view=view,
    )
 
 
# ── /leave ────────────────────────────────────────────────────────────────────

async def leave_confirm_autocomplete(
    interaction: discord.Interaction,
    current: str,
):
    player = db.get_player(str(interaction.user.id))
    if not player or not player["crew_id"]:
        return [discord.app_commands.Choice(name="You are not in a crew.", value="no")]
    crew = db.get_crew(player["crew_id"])
    name = crew["name"] if crew else "your crew"
    return [
        discord.app_commands.Choice(
            name=f"⚠ This will remove you from {name} — select to confirm",
            value="yes",
        )
    ]
 
 
@bot.tree.command(name="leave", description="Leave your current crew", guild=MY_GUILD)
@discord.app_commands.describe(confirm="Confirm you want to leave")
@discord.app_commands.autocomplete(confirm=leave_confirm_autocomplete)
async def leave_cmd(interaction: discord.Interaction, confirm: str):
    if confirm != "yes":
        await interaction.response.send_message("Cancelled.", ephemeral=True)
        return
 
    uid    = str(interaction.user.id)
    player = db.get_player(uid)
 
    if not player:
        await interaction.response.send_message("You are not registered yet.")
        return
 
    if not player["crew_id"]:
        await interaction.response.send_message("You are not in a crew.")
        return
 
    crew = db.get_crew(player["crew_id"])
    crew_name = crew["name"] if crew else "your crew"
 
    role = interaction.guild.get_role(int(player["crew_id"]))
    if role and role in interaction.user.roles:
        await interaction.user.remove_roles(role)
 
    db.set_player_crew(uid, None)
 
    await interaction.response.send_message(
        f"{interaction.user.mention} has left **{crew_name}**."
    )
 

# ── /remove ───────────────────────────────────────────────────────────────────
 
@bot.tree.command(name="remove", description="Remove a player from the player list", guild=MY_GUILD)
@discord.app_commands.describe(target="The player to remove")
async def remove_cmd(interaction: discord.Interaction, target: discord.Member):
    role_names = [r.name for r in interaction.user.roles]
    if GAME_ADMIN not in role_names:
        await interaction.response.send_message(
            f"Only **{GAME_ADMIN}s** can remove players.", ephemeral=True
        )
        return
 
    uid = str(target.id)
    if not db.get_player(uid):
        await interaction.response.send_message(
            f"**{target.display_name}** is not registered.", ephemeral=True
        )
        return
 
    db.delete_player(uid)
    await interaction.response.send_message(
        f"**{target.display_name}** has been removed from the player list."
    )









# To send a picture of the map
@bot.tree.command(name="map", description="View your current area", guild=MY_GUILD)
@discord.app_commands.describe(view="Map view")
@discord.app_commands.choices(view=[
    discord.app_commands.Choice(name="default", value="default"),
    discord.app_commands.Choice(name="roll",    value="roll"),
])
async def map_cmd(interaction: discord.Interaction, view: str = "default"):
    await interaction.response.defer(ephemeral=True)
    uid = str(interaction.user.id)
 
    loop = asyncio.get_event_loop()
    buf  = await loop.run_in_executor(None, map_render.render_map, uid, 10, view)
 
    if not buf:
        await interaction.followup.send("You are not registered yet. Use `/register` first.", ephemeral=True)
        return
 
    title = "Your Position" if view == "default" else "Your Position — Roll"
    file  = discord.File(buf, filename="map.png")
    embed = discord.Embed(title=title, color=0x1a3f6b)
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
    if GAME_ADMIN not in role_names:
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    msg = "# Choose Your Allegiance!"
    await interaction.channel.send(msg, view=RolePicker())
    await interaction.followup.send("Posted!", ephemeral=True)



if __name__ == "__main__":
    bot.run(os.getenv("DISCORD_TOKEN"))
