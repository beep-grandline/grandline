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

# Configuration scripts
from config import MY_GUILD, GUILD_ID, GAME_ADMIN, GAME_MOD
from fruits import FRUITS, get_fruit_by_id, fruit_autocomplete
from npcs import load_npcs

load_dotenv()

# Create bot instance
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Import commands
from kit_commands import kit_group
from battle_commands import battle_cmd, forfeit_cmd, cannons_cmd, engage_cmd
bot.tree.add_command(engage_cmd)
bot.tree.add_command(cannons_cmd)
bot.tree.add_command(kit_group)
bot.tree.add_command(battle_cmd)
bot.tree.add_command(forfeit_cmd)
from profile_commands import profile_group
bot.tree.add_command(profile_group)
from inventory_commands import inventory_cmd, eat_cmd
bot.tree.add_command(inventory_cmd)
bot.tree.add_command(eat_cmd)
from crew_commands import crew_group
bot.tree.add_command(crew_group)
from travel_commands import travel_group, setup_travel_task
bot.tree.add_command(travel_group)
from spyglass import spyglass_cmd, load_islands, prerender_all_flags
bot.tree.add_command(spyglass_cmd)

@bot.event
async def on_ready():
    setup_travel_task(bot)
    load_npcs()
    load_islands()
    asyncio.create_task(prerender_all_flags())
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
        ]
    },
    
    "Battle": {
        "title": "⚔ Battle",
        "description": "How to fight other players.",
        "fields": [
            ("/kit add",       "Build a move using keywords. Pick a power tier (CHIP → CRUSHER), then add modifiers like QUICK, HOMING, or FLURRY. You get 4 slots and 4 moves max."),
            ("/kit show",      "View your current moveset."),
            ("/kit remove",    "Remove a move from your kit."),
            ("/battle @user", "Challenge another player to a fight. They'll get Accept and Decline buttons. Both players need a kit before a battle can start."),
            ("/forfeit",       "Concede your current battle."),
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
            ("/search <name>", "Find an entry in the devil fruit encyclopedia."),
        ]
    },

}


@bot.tree.command(name="help", description="Help topics", guild=MY_GUILD)
@discord.app_commands.describe(topic="What do you need help with?")
async def help_command(
    interaction: discord.Interaction,
    topic: Literal["Starting", "Travel", "Devil Fruits", "Battle"] = None
):
    if topic is None:
        embed = discord.Embed(
            title="📖 Guide to Bot Commands",
            description="Use `/help <topic>` to find bot commands for any of the listed topics. Want to know how the game works? Use the `/info` command!",
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


INFO_PAGES = {
    "Factions": {
        "title": "⚑ Factions",
        "description": "The three factions of the Grand Line.",
        "fields": [
            ("Pirate",         "Sail, fight, plunder, and find your way to the One Piece."),
            ("Marine",         "Represent justice."),
            ("Bounty Hunter",  "Collect bounties on wanted persons."),
        ]
    },
}


@bot.tree.command(name="info", description="Game information and references", guild=MY_GUILD)
@discord.app_commands.describe(topic="What do you want to know about?")
async def info_command(
    interaction: discord.Interaction,
    topic: Literal["Factions"] = None
):
    if topic is None:
        embed = discord.Embed(
            title="📖 Game Info",
            description="Use `/info <topic>` to learn about the world. More topics coming soon!",
            color=0x3a7ebf,
        )
        for key, page in INFO_PAGES.items():
            embed.add_field(name=page["title"], value=page["description"], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    page = INFO_PAGES[topic]
    embed = discord.Embed(title=page["title"], color=0x3a7ebf)
    for name, value in page["fields"]:
        embed.add_field(name=name, value=value, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ── Player commands ───────────────────────────────────────────────────────────

async def _crew_name_autocomplete(interaction: discord.Interaction, current: str):
    crews = db.get_all_crews()
    return [
        discord.app_commands.Choice(name=c["name"], value=c["id"])
        for c in crews
        if current.lower() in c["name"].lower()
    ][:25]


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
@discord.app_commands.autocomplete(crew=_crew_name_autocomplete)
async def join_cmd(interaction: discord.Interaction, crew:str):
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

    crew_row = db.get_crew(crew)
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

    CAT_MAP = {
    "1": "Paramecia",
    "2": "Zoan",
    "3": "Logia",
    "4": "Mythical Zoan",
    "5": "Ancient Zoan",
    "6": "Special Paramecia",
    }

    category = CAT_MAP.get(cat, "Unknown")
        
 
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

def is_gm(interaction: discord.Interaction) -> bool:
    return any(r.name in (GAME_ADMIN, GAME_MOD) for r in interaction.user.roles)

@gm_group.command(name="teleport", description="Teleport a player to a hex (solo at destination)")
@discord.app_commands.describe(
    target="The player to move",
    q="Hex q coordinate",
    r="Hex r coordinate",
)
async def gm_teleport(interaction: discord.Interaction, target: discord.Member, q: int, r: int):
    if not is_gm(interaction):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
 
    uid = str(target.id)
    if not db.get_player(uid):
        await interaction.response.send_message(
            f"**{target.display_name}** is not registered.", ephemeral=True
        )
        return
 
    db.update_player_position(uid, q, r)
    db.set_following(uid, None)   # detach from ship/captain at new location
    await interaction.response.send_message(
        f"Teleported **{target.display_name}** to `q={q}, r={r}`. "
        f"They are now moving independently."
    )

@gm_group.command(name="moveship", description="Teleport a crew's ship to a hex")
@discord.app_commands.describe(
    crew="Crew name",
    q="Hex q coordinate",
    r="Hex r coordinate",
)
@discord.app_commands.autocomplete(crew=_crew_name_autocomplete)
async def gm_moveship(interaction: discord.Interaction, crew: str, q: int, r: int):
    if not is_gm(interaction):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
 
    crew_row = db.get_crew(crew)
    if not crew_row:
        await interaction.response.send_message("Crew not found.", ephemeral=True)
        return
 
    db.move_crew(crew, q, r)
    await interaction.response.send_message(
        f"Moved **{crew_row['name']}**'s ship to `q={q}, r={r}`."
    )


# ── /gm addrolls — give extra rolls to a crew ─────────────────────────────────


@gm_group.command(name="addrolls", description="Add rolls to a crew (or all crews)")
@discord.app_commands.describe(
    amount="Number of rolls to add",
    crew="Specific crew (leave empty to add to all crews)",
    cap="Cap at max (12) — default True, set False to allow over max",
)
@discord.app_commands.autocomplete(crew=_crew_name_autocomplete)
async def gm_addrolls(
    interaction: discord.Interaction,
    amount: int,
    crew: str = None,
    cap: bool = True,
):
    if not is_gm(interaction):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
 
    if crew:
        crew_row = db.get_crew(crew)
        if not crew_row:
            await interaction.response.send_message("Crew not found.", ephemeral=True)
            return
        current  = crew_row["roll"] or 0
        new_roll = min(game.ROLL_MAX, current + amount) if cap else current + amount
        db.set_crew_roll(crew, new_roll)
        cap_note = f" (capped at {game.ROLL_MAX})" if cap and new_roll == game.ROLL_MAX else ""
        await interaction.response.send_message(
            f"Added **{amount}** rolls to **{crew_row['name']}** — "
            f"now at **{new_roll}**{cap_note}."
        )
    else:
        crews   = db.get_all_crews()
        updated = 0
        for c in crews:
            current  = c["roll"] or 0
            new_roll = min(game.ROLL_MAX, current + amount) if cap else current + amount
            db.set_crew_roll(c["id"], new_roll)
            updated += 1
        cap_note = f" (capped at {game.ROLL_MAX})" if cap else ""
        await interaction.response.send_message(
            f"Added **{amount}** rolls to all **{updated}** crews{cap_note}."
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
        
    # create the role normally first
    role = await interaction.guild.create_role(
        name=name, color=discord.Color(color_int), mentionable=True
    )
    
    # find an anchor role to position below
    # replace "Civilian" with whatever your lowest non-crew role is
    anchor = discord.utils.get(interaction.guild.roles, name="crewanchordontdelete")
    if anchor:
        try:
            await role.edit(position=anchor.position - 1)
        except discord.HTTPException:
            pass  # if it fails the role still works, just sits at bottom
            
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

# ── /gm repair — restore a crew's ship HP ─────────────────────────────────────
 
@gm_group.command(name="repair", description="Repair a crew's ship")
@discord.app_commands.describe(
    crew="Crew whose ship to repair",
    amount="HP to restore (leave empty for full repair)",
)
@discord.app_commands.autocomplete(crew=_crew_name_autocomplete)
async def gm_repair(
    interaction: discord.Interaction,
    crew: str,
    amount: int = None,
):
    if not is_gm(interaction):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
 
    crew_row = db.get_crew(crew)
    if not crew_row:
        await interaction.response.send_message("Crew not found.", ephemeral=True)
        return
 
    new_hp   = db.repair_ship(crew, amount)
    max_hp   = crew_row["ship_max_hp"] or 500
    note     = f"+{amount} HP" if amount else "fully repaired"
    await interaction.response.send_message(
        f"🔧 **{crew_row['name']}**'s ship {note}. "
        f"HP: **{new_hp}/{max_hp}**"
    )

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

# ── /gm givefruit ─────────────────────────────────────────────────────────────
 
@gm_group.command(name="givefruit", description="Give an uneaten Devil Fruit to a player")
@discord.app_commands.describe(target="The player", fruit="Devil fruit name")
@discord.app_commands.autocomplete(fruit=fruit_autocomplete)
async def gm_givefruit(interaction: discord.Interaction, target: discord.Member, fruit: str):
    if not is_gm(interaction):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
 
    uid = str(target.id)
    if not db.get_player(uid):
        await interaction.response.send_message(
            f"**{target.display_name}** is not registered.", ephemeral=True
        )
        return
 
    if db.get_held_fruit(uid):
        await interaction.response.send_message(
            f"**{target.display_name}** already has a fruit in their held slot. "
            "Use `/gm takefruit` first.", ephemeral=True
        )
        return
 
    row = get_fruit_by_id(fruit)
    if not row:
        await interaction.response.send_message(
            "Fruit not found — select from the autocomplete list.", ephemeral=True
        )
        return
 
    db.set_held_fruit(uid, fruit)
    jap = (row.get("jap") or "").strip()
    eng = (row.get("eng") or "").strip()
    await interaction.response.send_message(
        f"Gave **{target.display_name}** the **{jap}** ({eng}). "
        f"They can use `/eat` to eat it or hold onto it."
    )
 
 
# ── /gm giveitem ──────────────────────────────────────────────────────────────
 
@gm_group.command(name="giveitem", description="Add an item to a player's inventory")
@discord.app_commands.describe(
    target="The player",
    name="Item name",
    qty="Quantity (default 1)",
    keywords="Space-separated tags e.g. healing rare (optional)",
)
async def gm_giveitem(
    interaction: discord.Interaction,
    target: discord.Member,
    name: str,
    qty: int = 1,
    keywords: str = "",
):
    if not is_gm(interaction):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
 
    uid = str(target.id)
    if not db.get_player(uid):
        await interaction.response.send_message(
            f"**{target.display_name}** is not registered.", ephemeral=True
        )
        return
 
    if qty < 1:
        await interaction.response.send_message("Quantity must be at least 1.", ephemeral=True)
        return
 
    kw_list = [k.lower() for k in keywords.split() if k] if keywords else []
    db.add_inventory_item(uid, name, qty=qty, keywords=kw_list)
 
    kw_str = ", ".join(kw_list) if kw_list else "no tags"
    await interaction.response.send_message(
        f"Added **{name}** ×{qty} ({kw_str}) to **{target.display_name}**'s inventory."
    )
 
 
# ── /gm take ─────────────────────────────────────────────────────────────────
 
async def _take_autocomplete(interaction: discord.Interaction, current: str):
    target = interaction.namespace.target
    if not target:
        return []
    uid     = str(target.id)
    choices = []
    held    = db.get_held_fruit(uid)
    if held:
        row  = get_fruit_by_id(held)
        name = (row.get("jap") or held) if row else held
        choices.append(discord.app_commands.Choice(
            name=f"[Fruit] {name}", value="__held_fruit__"
        ))
    for item in db.get_inventory(uid):
        if current.lower() in item["name"].lower():
            choices.append(discord.app_commands.Choice(
                name=f"{item['name']} ×{item['qty']}", value=item["name"]
            ))
    return choices[:25]
 
 
@gm_group.command(name="take", description="Remove an item or fruit from a player")
@discord.app_commands.describe(
    target="The player",
    item="What to take",
    qty="Quantity to remove (items only, default 1)",
)
@discord.app_commands.autocomplete(item=_take_autocomplete)
async def gm_take(
    interaction: discord.Interaction,
    target: discord.Member,
    item: str,
    qty: int = 1,
):
    if not is_gm(interaction):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
 
    uid = str(target.id)
    if not db.get_player(uid):
        await interaction.response.send_message(
            f"**{target.display_name}** is not registered.", ephemeral=True
        )
        return
 
    if item == "__held_fruit__":
        held = db.get_held_fruit(uid)
        if not held:
            await interaction.response.send_message(
                f"**{target.display_name}** has no held fruit.", ephemeral=True
            )
            return
        row  = get_fruit_by_id(held)
        name = (row.get("jap") or held) if row else held
        db.clear_held_fruit(uid)
        await interaction.response.send_message(
            f"Took the **{name}** from **{target.display_name}**."
        )
    else:
        success, remaining = db.remove_inventory_item(uid, item, qty=qty)
        if not success:
            await interaction.response.send_message(
                f"**{target.display_name}** doesn't have **{item}**.", ephemeral=True
            )
            return
        leftover = f" ({remaining} remaining)" if remaining > 0 else ""
        await interaction.response.send_message(
            f"Took **{item}** ×{qty} from **{target.display_name}**{leftover}."
        )



@gm_group.command(name="help", description="List all GM commands")
async def gm_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="⚙️ Helper commands",
        color=0x2d6a9f,
    )
    commands_list = [
        ("/gm teleport",  "Teleport a player to a hex — they go solo at the destination (target, q, r)"),
        ("/gm moveship",  "Teleport a crew's entire ship to a hex (crew, q, r)"),
        ("/gm addrolls",  "Add rolls to a crew for events (crew, amount, optional cap)"),
        ("/gm crew",      "Create a new crew (name, captain, color)"),
        ("/gm disband",   "Disband a crew by name"),
        ("/gm remove",    "Remove a player from the game"),
        ("/gm setberry",  "Set a player's berry (target, amount)"),
        ("/gm setstats",  "Set a player's battle stats — ATK, DEF, SPD, block and dodge names"),
        ("/gm setfruit",  "Set a player's eaten fruit and apply its type (target, fruit)"),
        ("/gm givefruit", "Give an uneaten fruit to a player's held slot (target, fruit)"),
        ("/gm giveitem",  "Add an item to a player's inventory (target, name, qty, keywords)"),
        ("/gm take",      "Remove a held fruit or item from a player (target, item)"),
        ("/gm help",      "Show this message"),
    ]
    for name, desc in commands_list:
        embed.add_field(name=name, value=desc, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

class SetStatsModal(discord.ui.Modal, title="Set Fighter Stats"):

    atk = discord.ui.TextInput(
        label="ATK",
        placeholder="Attack power (integer)",
        max_length=4,
        required=False,
    )
    defense = discord.ui.TextInput(
        label="DEF",
        placeholder="Defence (integer)",
        max_length=4,
        required=False,
    )
    spd = discord.ui.TextInput(
        label="SPD",
        placeholder="Speed (integer)",
        max_length=4,
        required=False,
    )
    hp = discord.ui.TextInput(
        label="HP",
        placeholder="Hit points (integer)",
        max_length=6,
        required=False,
    )
    block_name = discord.ui.TextInput(
        label="Block technique name",
        placeholder="e.g. Iron Body  (leave blank to clear)",
        max_length=64,
        required=False,
    )

    def __init__(self, player_row, target: discord.Member):
        super().__init__()
        self.target = target
        if player_row["atk"]:
            self.atk.default      = str(player_row["atk"])
        if player_row["defense"]:
            self.defense.default  = str(player_row["defense"])
        if player_row["spd"]:
            self.spd.default      = str(player_row["spd"])
        if player_row["hp"]:
            self.hp.default       = str(player_row["hp"])
        if player_row["block_name"]:
            self.block_name.default = player_row["block_name"]

    async def on_submit(self, interaction: discord.Interaction):
        uid    = str(self.target.id)
        errors = []
        kwargs = {}

        for field, key in [(self.atk, "atk"), (self.defense, "defense"), (self.spd, "spd"), (self.hp, "hp")]:
            val = str(field).strip()
            if val:
                try:
                    kwargs[key] = int(val)
                except ValueError:
                    errors.append(f"{field.label} must be a whole number")

        if errors:
            await interaction.response.send_message(
                "Fix these errors:\n" + "\n".join(f"· {e}" for e in errors),
                ephemeral=True,
            )
            return

        block = str(self.block_name).strip() or None

        db.set_fighter_stats(
            uid,
            atk        = kwargs.get("atk"),
            defense    = kwargs.get("defense"),
            spd        = kwargs.get("spd"),
            hp         = kwargs.get("hp"),
            block_name = block,
        )

        lines = []
        if "atk"     in kwargs: lines.append(f"ATK → **{kwargs['atk']}**")
        if "defense" in kwargs: lines.append(f"DEF → **{kwargs['defense']}**")
        if "spd"     in kwargs: lines.append(f"SPD → **{kwargs['spd']}**")
        if "hp"      in kwargs: lines.append(f"HP → **{kwargs['hp']}**")
        if block is not None: lines.append(f"Block → **{block or 'cleared'}**")

        await interaction.response.send_message(
            f"Updated **{self.target.display_name}**:\n" + "\n".join(lines),
            ephemeral=False,
        )
 

@gm_group.command(name="setstats", description="Set a player's battle stats")
@discord.app_commands.describe(target="The player to update")
async def gm_setstats(interaction: discord.Interaction, target: discord.Member):
    if not is_gm(interaction):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    uid    = str(target.id)
    player = db.get_player(uid)
    if not player:
        await interaction.response.send_message(
            f"**{target.display_name}** is not registered.", ephemeral=True
        )
        return
    await interaction.response.send_modal(SetStatsModal(player, target))
 
 
@gm_group.command(name="setfruit", description="Assign a devil fruit to a player")
@discord.app_commands.describe(target="The player", fruit="Devil fruit name")
@discord.app_commands.autocomplete(fruit=fruit_autocomplete)
async def gm_setfruit(interaction: discord.Interaction, target: discord.Member, fruit: str):
    if not is_gm(interaction):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    uid    = str(target.id)
    player = db.get_player(uid)
    if not player:
        await interaction.response.send_message(
            f"**{target.display_name}** is not registered.", ephemeral=True
        )
        return
    row = get_fruit_by_id(fruit)
    if not row:
        await interaction.response.send_message(
            "Fruit not found — select from the autocomplete list.", ephemeral=True
        )
        return
    db.set_player_fruit(uid, fruit)
    jap = (row.get("jap") or "").strip()
    eng = (row.get("eng") or "").strip()
    t1  = row.get("type1") or "Normal"
    t2  = row.get("type2") or "none"
    await interaction.response.send_message(
        f"Gave **{target.display_name}** the **{jap}** ({eng}).\n"
        f"Type: `{t1}` / Defence modifier: `{t2}`",
        ephemeral=False,
    )


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




