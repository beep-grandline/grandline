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
import csv

load_dotenv()

# Bot params
MY_GUILD   = discord.Object(id=1487526877185704107)
GAME_ADMIN = "Admin"
GAME_MOD   = "Mod"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    bot.add_view(RolePicker())
    bot.tree.clear_commands(guild=None)
    await bot.tree.sync()
    synced = await bot.tree.sync(guild=MY_GUILD)
    print(f"Synced {len(synced)} commands: {[c.name for c in synced]}")
    print(f"Logged in as {bot.user}")


# ── Permission helpers ────────────────────────────────────────────────────────

def is_admin(interaction: discord.Interaction) -> bool:
    return any(r.name == GAME_ADMIN for r in interaction.user.roles)

def is_gm(interaction: discord.Interaction) -> bool:
    return any(r.name in (GAME_ADMIN, GAME_MOD) for r in interaction.user.roles)


# ── Help ──────────────────────────────────────────────────────────────────────

HELP_PAGES = {
    "Starting": {
        "title": "⛵ Starting",
        "description": "How to start the game.",
        "fields": [
            ("/register <faction>", "Enter the game."),
            ("/crew", "Create a crew (admin)."),
            ("/disband", "Disband a crew (admin)."),
        ]
    },
    "Travel": {
        "title": "🗺️ Travel",
        "description": "Navigating the Grand Line.",
        "fields": [
            ("/map", "Shows your current viewport. Updates your position on the map."),
            ("/position", "Lists your current position."),
        ]
    },
    "Devil Fruits": {
        "title": "<:smile_fruit:1493852186663456918> Devil Fruits",
        "description": "Devil fruit commands.",
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
    topic: Literal["Starting", "Travel", "Devil Fruits"] = None
):
    if topic is None:
        embed = discord.Embed(
            title="📖 Help",
            description="Use `/help <topic>` to find bot commands for any of the listed topics.",
            color=0x3a7ebf,
        )
        for key, page in HELP_PAGES.items():
            embed.add_field(name=page["title"], value=page["description"], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    page = HELP_PAGES[topic]
    embed = discord.Embed(title=page["title"], color=0x3a7ebf)
    for name, value in page["fields"]:
        embed.add_field(name=name, value=value, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ── Player commands ───────────────────────────────────────────────────────────

@bot.tree.command(name="register", description="Register your character", guild=MY_GUILD)
@discord.app_commands.describe(job="Your role (pirate, marine, etc)")
async def register(interaction: discord.Interaction, job: str):
    uid  = str(interaction.user.id)
    name = interaction.user.name
    db.upsert_player(uid, name)
    await interaction.response.send_message(
        f"Welcome to the Grand Line, {name}!", ephemeral=True
    )

@bot.tree.command(name="position", description="Check your current position", guild=MY_GUILD)
async def position_cmd(interaction: discord.Interaction):
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

@bot.tree.command(name="purse", description="Check how much money you have", guild=MY_GUILD)
async def purse_cmd(interaction: discord.Interaction):
    uid   = str(interaction.user.id)
    berry = db.get_berry(uid)
    if not berry:
        await interaction.response.send_message("You are broke.", ephemeral=True)
    else:
        await interaction.response.send_message(f"You have ฿**{berry}**.", ephemeral=True)


# ── Map ───────────────────────────────────────────────────────────────────────

@bot.tree.command(name="map", description="View your current area", guild=MY_GUILD)
@discord.app_commands.describe(view="Map view")
@discord.app_commands.choices(view=[
    discord.app_commands.Choice(name="default", value="default"),
    discord.app_commands.Choice(name="roll",    value="roll"),
])
async def map_cmd(interaction: discord.Interaction, view: str = "default"):
    await interaction.response.defer(ephemeral=True)
    uid  = str(interaction.user.id)
    loop = asyncio.get_event_loop()
    buf  = await loop.run_in_executor(None, map_render.render_map, uid, 10, view)
    if not buf:
        await interaction.followup.send(
            "You are not registered yet. Use `/register` first.", ephemeral=True
        )
        return
    title = "Your Position" if view == "default" else "Your Position — Roll"
    file  = discord.File(buf, filename="map.png")
    embed = discord.Embed(title=title, color=0x1a3f6b)
    embed.set_image(url="attachment://map.png")
    await interaction.followup.send(file=file, embed=embed, ephemeral=True)


# ── Crew join / leave ─────────────────────────────────────────────────────────

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
                view=self, embed=None,
            )
        else:
            await interaction.response.edit_message(
                content=f"✗ {self.applicant.mention}'s request to join **{self.crew_name}** was denied.",
                view=self, embed=None,
            )

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="join_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._resolve(interaction, accepted=True)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, custom_id="join_deny")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._resolve(interaction, accepted=False)


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

    view  = JoinRequestView(applicant=interaction.user, crew_id=crew_id, crew_name=crew_name)
    embed = discord.Embed(
        title="Crew Join Request",
        description=f"{interaction.user.mention} wants to join **{crew_name}**.",
        color=0x1a3f6b,
    )
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    await interaction.followup.send(
        content=f"{captain.mention} — new join request!",
        embed=embed, view=view,
    )


async def leave_confirm_autocomplete(interaction: discord.Interaction, current: str):
    player = db.get_player(str(interaction.user.id))
    if not player or not player["crew_id"]:
        return [discord.app_commands.Choice(name="You are not in a crew.", value="no")]
    crew = db.get_crew(player["crew_id"])
    name = crew["name"] if crew else "your crew"
    return [discord.app_commands.Choice(
        name=f"⚠ This will remove you from {name} — select to confirm",
        value="yes",
    )]


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

    crew      = db.get_crew(player["crew_id"])
    crew_name = crew["name"] if crew else "your crew"
    role      = interaction.guild.get_role(int(player["crew_id"]))
    if role and role in interaction.user.roles:
        await interaction.user.remove_roles(role)
    db.set_player_crew(uid, None)
    await interaction.response.send_message(
        f"{interaction.user.mention} has left **{crew_name}**."
    )




@bot.tree.command(name="zelle", description="Transfer berry to another player", guild=MY_GUILD)
@discord.app_commands.describe(target="Who to send berry to", amount="How much to send")
async def zelle(interaction: discord.Interaction, target: discord.Member, amount: int):
    uid = str(interaction.user.id)
 
    if amount <= 0:
        await interaction.response.send_message("Amount must be greater than 0.", ephemeral=True)
        return
 
    if target.id == interaction.user.id:
        await interaction.response.send_message("You can't send berry to yourself.", ephemeral=True)
        return
 
    if not db.get_player(uid):
        await interaction.response.send_message("You are not registered yet.", ephemeral=True)
        return
 
    if not db.get_player(str(target.id)):
        await interaction.response.send_message(
            f"**{target.display_name}** is not registered.", ephemeral=True
        )
        return
 
    success = db.remove_berry(uid, amount)
    if not success:
        await interaction.response.send_message("You don't have enough berry.", ephemeral=True)
        return
 
    db.add_berry(str(target.id), amount)
    await interaction.response.send_message(
        f"{interaction.user.mention} sent ฿**{amount:,}** to {target.mention}."
    )

















FRUITS = []
 
def load_fruits():
    global FRUITS
    try:
        with open("data/fruits.csv", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            FRUITS = [row for row in reader if row.get("id")]
        print(f"Loaded {len(FRUITS)} devil fruits.")
    except FileNotFoundError:
        print("Warning: data/fruits.csv not found.")
 
load_fruits()
 
 
def get_fruit_by_id(fruit_id):
    return next((f for f in FRUITS if f["id"] == fruit_id), None)
 
 
# ── Autocomplete ──────────────────────────────────────────────────────────────
 
async def fruit_autocomplete(
    interaction: discord.Interaction,
    current: str,
):
    current = current.lower().strip()
    matches = []
    seen    = set()
 
    for f in FRUITS:
        eng = (f.get("eng") or "").strip()
        jap = (f.get("jap") or "").strip()
        fid = f.get("id", "")
 
        if fid in seen:
            continue
        if current in eng.lower() or current in jap.lower():
            seen.add(fid)
            label = jap
            # Discord Choice name max is 100 chars
            matches.append(discord.app_commands.Choice(
                name=label[:100],
                value=fid,
            ))
 
    return matches[:25]
 
 
# ── /search command ───────────────────────────────────────────────────────────
 
@bot.tree.command(name="search", description="Look up a devil fruit", guild=MY_GUILD)
@discord.app_commands.describe(fruit="Start typing a fruit name")
@discord.app_commands.autocomplete(fruit=fruit_autocomplete)
async def search_cmd(interaction: discord.Interaction, fruit: str):
    row = get_fruit_by_id(fruit)
 
    if not row:
        await interaction.response.send_message(
            "Fruit not found. Try selecting from the autocomplete list.",
            ephemeral=True,
        )
        return
 
    eng     = (row.get("eng") or "Unknown").strip()
    jap     = (row.get("jap") or "").strip()
    ability = (row.get("ability") or "No description available.").strip()
    url     = (row.get("url") or "").strip()
    cat     = (row.get("cat") or "").strip()

    match cat:
        case 1: category = "Paramecia"
        case 2: category = "Zoan"
        case 3: category = "Logia"
        case 4: category = "Mythical Zoan"
        case 5: category = "Ancient Zoan"
        case 6: category = "Special Paramecia"
 
    embed = discord.Embed(
        title=jap,
        description=f"*{eng}*" if jap else "",
        color=0x1a3f6b,
    )
    embed.add_field(name="Ability", value=ability, inline=True)
    embed.add_field(name="Category",value=category, inline=True)
    embed.set_thumbnail(url=url)
 
    await interaction.response.send_message(embed=embed, ephemeral=True)









# ── /gm command group — usable by Admin and Mod ───────────────────────────────

gm_group = discord.app_commands.Group(
    name="gm",
    description="Game master commands",
    guild_ids=[MY_GUILD.id],
)


@gm_group.command(name="teleport", description="Move a player to a specific hex")
@discord.app_commands.describe(target="The player to teleport", q="Hex q coordinate", r="Hex r coordinate")
async def gm_teleport(interaction: discord.Interaction, target: discord.Member, q: int, r: int):
    if not is_gm(interaction):
        await interaction.response.send_message("You don't have permission to use this.", ephemeral=True)
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


@gm_group.command(name="crew", description="Create a new crew")
@discord.app_commands.describe(name="Name of the crew", captain="The crew's captain", color="Hex color (e.g. ff0000)")
async def gm_crew(interaction: discord.Interaction, name: str, captain: discord.Member, color: str):
    if not is_gm(interaction):
        await interaction.response.send_message("You don't have permission to use this.", ephemeral=True)
        return
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
    if db.get_crew_by_name(name):
        await interaction.followup.send(f"A crew named **{name}** already exists.", ephemeral=True)
        return
    if discord.utils.find(lambda r: r.name.lower() == name.lower(), interaction.guild.roles):
        await interaction.followup.send(f"A role named **{name}** already exists.", ephemeral=True)
        return
    captain_player = db.get_player(str(captain.id))
    if captain_player and captain_player["crew_id"]:
        existing = db.get_crew(captain_player["crew_id"])
        existing_name = existing["name"] if existing else "a crew"
        await interaction.followup.send(
            f"**{captain.display_name}** is already in **{existing_name}**.", ephemeral=True
        )
        return
    role = await interaction.guild.create_role(
        name=name, color=discord.Color(color_int), mentionable=True
    )
    await interaction.guild.edit_role_positions({role: interaction.guild.me.top_role.position})
    db.upsert_crew(str(role.id), name, captain_id=str(captain.id))
    db.set_player_crew(str(captain.id), str(role.id))
    await captain.add_roles(role)
    await interaction.followup.send(
        f"Crew **{name}** created with color `#{color}`! Captain: {captain.mention}"
    )


@gm_group.command(name="disband", description="Disband a crew")
@discord.app_commands.describe(name="Name of the crew to disband")
async def gm_disband(interaction: discord.Interaction, name: str):
    if not is_gm(interaction):
        await interaction.response.send_message("You don't have permission to use this.", ephemeral=True)
        return
    await interaction.response.defer()
    crew = db.get_crew_by_name(name)
    if not crew:
        await interaction.followup.send(f"No crew named **{name}** found.", ephemeral=True)
        return
    role = interaction.guild.get_role(int(crew["id"]))
    if role:
        await role.delete()
    db.delete_crew(crew["id"])
    await interaction.followup.send(f"Crew **{crew['name']}** has been disbanded.")


@gm_group.command(name="remove", description="Remove a player from the player list")
@discord.app_commands.describe(target="The player to remove")
async def gm_remove(interaction: discord.Interaction, target: discord.Member):
    if not is_gm(interaction):
        await interaction.response.send_message("You don't have permission to use this.", ephemeral=True)
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


@gm_group.command(name="setberry", description="Set a player's berry amount")
@discord.app_commands.describe(target="The player", amount="Amount of berry to set")
async def gm_setberry(interaction: discord.Interaction, target: discord.Member, amount: int):
    if not is_gm(interaction):
        await interaction.response.send_message("You don't have permission to use this.", ephemeral=True)
        return
    uid = str(target.id)
    if not db.get_player(uid):
        await interaction.response.send_message(
            f"**{target.display_name}** is not registered.", ephemeral=True
        )
        return
    db.set_berry(uid, amount)
    await interaction.response.send_message(
        f"Set **{target.display_name}**'s berry to ฿{amount}."
    )



@gm_group.command(name="help", description="List all GM commands")
async def gm_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="⚙️ Helper commands",
        color=0x2d6a9f,
    )
    commands_list = [
        ("/gm teleport",  "Move a player to a specific hex (target, q, r)"),
        ("/gm crew",      "Create a new crew (name, captain, color)"),
        ("/gm disband",   "Disband a crew by name"),
        ("/gm remove",    "Remove a player from the game"),
        ("/gm setberry",  "Set a player's berry (target, amount)"),
        ("/gm help",      "Show this message"),
    ]
    for name, desc in commands_list:
        embed.add_field(name=name, value=desc, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


bot.tree.add_command(gm_group)


# ── /admin command group — Admin only ─────────────────────────────────────────

admin_group = discord.app_commands.Group(
    name="admin",
    description="Admin-only commands",
    guild_ids=[MY_GUILD.id],
)


@admin_group.command(name="rolepicker", description="Post the faction role picker")
async def admin_rolepicker(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    await interaction.channel.send("# Choose Your Allegiance!", view=RolePicker())
    await interaction.followup.send("Posted!", ephemeral=True)


@admin_group.command(name="help", description="List all admin commands")
async def admin_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🔒 Admin Commands",
        color=0x8b0000,
    )
    commands_list = [
        ("/admin rolepicker", "Used only to refresh the rolepicker."),
        ("/admin help",       "Show this message"),
    ]
    for name, desc in commands_list:
        embed.add_field(name=name, value=desc, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


bot.tree.add_command(admin_group)


# ── Role picker ───────────────────────────────────────────────────────────────

class RolePicker(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

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
    await interaction.response.send_message(f"You are now a {role_name}!", ephemeral=True)













if __name__ == "__main__":
    bot.run(os.getenv("DISCORD_TOKEN"))




