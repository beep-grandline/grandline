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
from cook_commands import cook_group
bot.tree.add_command(cook_group)
from doctor_commands import doctor_group
bot.tree.add_command(doctor_group)
from marine_commands import marine_group
bot.tree.add_command(marine_group)

# Battles don't survive restarts (embed buttons die with the process),
# so clear any leftovers once per process start — not in on_ready, which
# re-fires on gateway reconnects and would wipe live battles.
_cleared = db.clear_all_battles()
if _cleared:
    print(f"[battles] cleared {_cleared} stale battle(s) from previous run")


# ── Global slash-command error handler ────────────────────────────────────────
ERROR_LOG_CHANNEL_ID = 1519738308756901928


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: discord.app_commands.AppCommandError,
):
    import traceback
    # full traceback to console
    traceback.print_exception(type(error), error, error.__traceback__)

    # concise message to the user who ran the command
    try:
        msg = "Something went wrong with that command. Try again, or let a GM know."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass  # interaction token may have expired — nothing we can do

    # concise summary to the log channel — no full paths or frame internals
    try:
        channel = bot.get_channel(ERROR_LOG_CHANNEL_ID)
        if channel:
            cmd  = interaction.command.qualified_name if interaction.command else "unknown"
            user = getattr(interaction.user, "display_name", "unknown")
            # unwrap CommandInvokeError to get the real exception
            exc  = getattr(error, "original", error)
            etype = type(exc).__name__
            emsg  = str(exc)[:200] or "(no message)"
            # last frame only, with the bare filename instead of the absolute path
            frames = traceback.extract_tb(exc.__traceback__)
            where  = ""
            if frames:
                f = frames[-1]
                where = f" at `{os.path.basename(f.filename)}:{f.lineno}` in `{f.name}()`"
            await channel.send(
                f"⚠ Error in `/{cmd}` (by {user}): `{etype}: {emsg}`{where}"
            )
    except Exception:
        pass

@bot.event
async def on_ready():
    setup_travel_task(bot)
    load_npcs()
    load_islands()
    game.ensure_whirlpools(force=True)   # fresh whirlpool field each bootup
    asyncio.create_task(prerender_all_flags())
    bot.add_view(RolePicker())
    bot.add_view(JobPicker())
    bot.add_view(WeaponPicker())
    bot.add_view(FruitPicker())
    bot.tree.clear_commands(guild=None)
    await bot.tree.sync()
    synced = await bot.tree.sync(guild=MY_GUILD)
    print(f"Synced {len(synced)} commands: {[c.name for c in synced]}")
    print(f"Logged in as {bot.user}")


_MUSIC_WORDS = {"crescendo", "diminuendo", "presto", "allegro", "yohohoho"}

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    words = set(message.content.lower().split())
    if words & _MUSIC_WORDS:
        await message.channel.send("🎵")
    await bot.process_commands(message)


# ── Permission helpers ────────────────────────────────────────────────────────

def is_admin(interaction: discord.Interaction) -> bool:
    return any(r.name == GAME_ADMIN for r in interaction.user.roles)

def is_gm(interaction: discord.Interaction) -> bool:
    return any(r.name in (GAME_ADMIN, GAME_MOD) for r in interaction.user.roles)


# ── Help ──────────────────────────────────────────────────────────────────────

HELP_PAGES = {
    "Starting": {
        "title": "⛵ Starting Out",
        "description": "How to enter the game.",
        "fields": [
            ("Choose Your Allegiance", "Pick Pirate or Marine from the role picker to register. You'll be placed at a starting island and can begin playing immediately."),
            ("Crew Up", "Join a crew with `/join <crew>` or wait for a captain to invite you. Solo players can still sail and fight."),
            ("Build Your Kit", "Before you can fight, add at least one move with `/kit add`. Use `/kit help` for keyword details."),
        ]
    },

    "Travel": {
        "title": "🗺️ Travel",
        "description": "Navigating the Grand Line.",
        "fields": [
            ("/travel map",       "View your current area on the world map."),
            ("/travel disembark", "Step off the ship onto an adjacent island tile."),
            ("/travel reboard",   "Board the ship from an adjacent tile."),
            ("On Sea",            "/travel helm — Steer the ship (captain or helmsman).\n/travel auto — Auto-move one step toward your pose (captain only).\n/travel pose — Set your log or eternal pose destination (captain only).\n/spyglass — Scout nearby islands and ships."),
            ("On Land",           "/travel walk — Move on foot across island tiles.\n/travel solo — Break away from your crew and move independently.\n/travel rejoin — Teleport back to your captain's position."),
        ]
    },

    "Battle": {
        "title": "⚔️ Battle",
        "description": "Fighting other players and NPCs. Use `/kit help` for keyword details.",
        "fields": [
            ("/kit add",          "Build a move with a power tier (CHIP → CRUSHER) and optional modifiers. 4 slot budget, 4 moves max."),
            ("/kit show",         "View your current moveset and slot usage."),
            ("/kit remove",       "Remove a move from your kit."),
            ("/battle @player",   "Challenge a player to a duel. Both sides need a kit."),
            ("/engage <npc>",     "Fight an NPC on your current tile."),
            ("/cannons <target>", "Fire your ship's cannons at an enemy crew (captain only, must be in range)."),
            ("/forfeit",          "Concede your current battle."),
            ("/use",              "Use a consumable item (potion, etc.) outside of battle."),
        ]
    },

    "Flair": {
        "title": "🪪 Flair",
        "description": "Profile and crew customization.",
        "fields": [
            ("/profile show",     "View your own or another player's character profile."),
            ("/profile set",      "Set your character's name, backstory, image, and other details."),
            ("/crew show",        "View your crew's details and members."),
            ("/crew set",         "Set your crew's name, description, jolly roger, and other details (captain only)."),
        ]
    },

    "Inventory": {
        "title": "🎒 Inventory & Economy",
        "description": "Items, money, and consumables.",
        "fields": [
            ("/inventory",        "View everything in your inventory."),
            ("/eat",              "Eat your currently held Devil Fruit."),
            ("/use",              "Use a consumable item (heals HP)."),
            ("/purse",            "Check your current berry balance."),
            ("/zelle @player",    "Transfer berry to another player."),
            ("/join <crew>",      "Request to join a crew."),
            ("/leave",            "Leave your current crew."),
        ]
    },

    "Jobs": {
        "title": "💼 Jobs",
        "description": "Specialized roles with their own command sets. Use `/help <job>` for details on each.\n\n`Cook` · `Doctor` · `Marine`",
        "fields": [],
    },

    "Cook": {
        "title": "🍳 Cook",
        "description": "Cooks can prepare meals that buff or restore their crew.",
        "fields": [
            ("/cook serve <dish>",           "Serve a dish to everyone on the ship."),
            ("/cook feed @player",           "Serve a dish directly to one person."),
            ("/cook cookbook add",           "Add a new recipe to your cookbook."),
            ("/cook cookbook list",          "View all your saved recipes."),
            ("/cook cookbook modify <dish>", "Edit a recipe's description or image."),
            ("/cook cookbook delete <dish>", "Remove a recipe from your cookbook."),
        ]
    },

    "Doctor": {
        "title": "⚕️ Doctor",
        "description": "Doctors can patch up crewmates mid-adventure.",
        "fields": [
            ("/doctor bandage @player", "Patch a crewmate up for some HP."),
            ("/doctor heal @player",    "Fully restore a crewmate's HP."),
        ]
    },

    "Marine": {
        "title": "⚓ Marine",
        "description": "Marine officers have access to law-enforcement commands.",
        "fields": [
            ("/marine sail",              "Commission your Marine battleship."),
            ("/marine arrest @player",    "Arrest a defeated player (0 HP required)."),
            ("/marine release @player",   "Release your prisoner at your current location."),
            ("/marine prisoners",         "List your current prisoners."),
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

_HELP_TOPICS = Literal[
    "Starting", "Travel", "Battle", "Flair", "Inventory",
    "Jobs", "Cook", "Doctor", "Marine", "Devil Fruits"
]

@bot.tree.command(name="help", description="Help topics", guild=MY_GUILD)
@discord.app_commands.describe(topic="What do you need help with?")
async def help_command(
    interaction: discord.Interaction,
    topic: _HELP_TOPICS = None
):
    if topic is None:
        embed = discord.Embed(
            title="📖 Guide to Bot Commands",
            description="Use `/help <topic>` to find bot commands for any of the listed topics. Want to know how the game works? Use the `/info` command!",
            color=0x3a7ebf,
        )
        # Overview: skip individual job pages — they're grouped under Jobs
        _skip = {"Cook", "Doctor", "Marine"}
        for key, page in HELP_PAGES.items():
            if key in _skip:
                continue
            embed.add_field(name=page["title"], value=page["description"], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    page = HELP_PAGES[topic]
    embed = discord.Embed(title=page["title"], description=page.get("description"), color=0x3a7ebf)
    for name, value in page["fields"]:
        embed.add_field(name=name, value=value, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


INFO_PAGES = {
    "Kit": {
        "title": "How to build your kit",
        "blurb": "Spend 10 points across Power / Accuracy / Speed per move.",
        "description": (
            "Your kit is your moveset — build up to four moves that represent your character!\n\n"
            "Every stat starts at a base of **1** and can go up to **6**. You spend **up to 10 "
            "points** across the three (that's the cap — spend fewer if you like). "
            "Keywords are optional riders on top."
        ),
        "fields": [
            ("Power",    "Bigger hits. 1 = ×0.70 damage … 6 = ×1.20."),
            ("Accuracy", "Chance to land. 1 = 55% to hit … 6 = 95%."),
            ("Speed",    "Weave out of hits, cut a target's evasion, and strike first. "
                         "1 = 0% evade … 6 = 35% evade."),
            ("Keywords", "`RISKY` (20% recoil) · `SLASH` / `PIERCE` (attack type, needs a weapon)"),
        ],
    },
    "Defenses": {
        "title": "🛡️ Defenses — Devil Fruit Body Types",
        "blurb": "Devil fruit body types and how they resist each attack.",
        "description": (
            "Each fruit gives a **body type** that reacts differently to the "
            "three attack types: slash, blunt, pierce. Numbers are damage "
            "multipliers (`✕` = immune). Pick your moves to match your opponent."
        ),
        "fields": [
            ("Passive — always reduce incoming damage", (
                "```\n"
                "          Sla  Blu  Pie\n"
                "none        1    1    1\n"
                "sponge      2    ✕    1\n"
                "armor     0.7  0.6  1.5\n"
                "logia       ✕    ✕    ✕\n"
                "```\n"
                "`sponge` (Beri Beri) shrugs off blunt · `logia` (Gasu Gasu) "
                "is intangible until hit with Haki · `armor` (Buki Buki) hates pierce."
            )),
            ("On block — only when they block", (
                "```\n"
                "          Sla  Blu  Pie\n"
                "shell     0.6 0.45    2\n"
                "buffer    0.5  0.8  0.5\n"
                "```\n"
                "`shell` (Bari Bari) turtles up but shatters to pierce · "
                "`buffer` (Awa Awa) softens most blocked hits."
            )),
            ("Accuracy — harder to hit", (
                "```\n"
                "          Sla  Blu  Pie\n"
                "deflect   0.7  0.5  0.5\n"
                "big       0.8  0.5  0.9\n"
                "```\n"
                "`deflect` (Buku Buku) and `big` (Deka Deka) lower your attack's "
                "hit chance instead of reducing damage."
            )),
            ("Escape", (
                "`escape` (Bara Bara) fighters flee far more easily (1.8× escape "
                "chance). `big` types are slow to run (0.7×)."
            )),
            ("Elements", (
                "On top of body type, each fruit has an **element** (Fire, Ice, "
                "Electric, etc.) that follows the standard 18-type chart for super "
                "effective / not very effective hits."
            )),
        ],
    },
    "Factions": {
        "title": "⚑ Factions",
        "blurb": "The three factions of the Grand Line.",
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
    topic: Literal["Factions", "Kit", "Defenses"] = None
):
    if topic is None:
        embed = discord.Embed(
            title="📖 Game Info",
            description="Use `/info <topic>` to learn about the world. More topics coming soon!",
            color=0x3a7ebf,
        )
        for key, page in INFO_PAGES.items():
            embed.add_field(name=f"`{key}`", value=page.get("blurb", ""), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    page = INFO_PAGES[topic]
    embed = discord.Embed(title=page["title"], description=page.get("description"), color=0x3a7ebf)
    for name, value in page["fields"]:
        embed.add_field(name=name, value=value, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ── Player commands ───────────────────────────────────────────────────────────

async def _crew_name_autocomplete(interaction: discord.Interaction, current: str):
    try:
        crews = db.get_all_crews()
        return [
            discord.app_commands.Choice(name=c["name"], value=c["id"])
            for c in crews
            if current.lower() in c["name"].lower()
            and (c["ship_type"] if "ship_type" in c.keys() else None) != "battleship"
        ][:25]
    except (discord.NotFound, Exception):
        return []


async def _all_ships_autocomplete(interaction: discord.Interaction, current: str):
    """Like _crew_name_autocomplete but includes marine battleships."""
    try:
        crews = db.get_all_crews()
        return [
            discord.app_commands.Choice(name=c["name"], value=c["id"])
            for c in crews
            if current.lower() in c["name"].lower()
        ][:25]
    except (discord.NotFound, Exception):
        return []



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
        await interaction.followup.send("You need to register first — pick your allegiance from the role picker.")
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
    try:
        player = db.get_player(str(interaction.user.id))
        if not player or not player["crew_id"]:
            return [discord.app_commands.Choice(name="You are not in a crew.", value="no")]
        crew = db.get_crew(player["crew_id"])
        name = crew["name"] if crew else "your crew"
        return [discord.app_commands.Choice(
            name=f"⚠ This will remove you from {name} — select to confirm",
            value="yes",
        )]
    except (discord.NotFound, Exception):
        return []


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















 


# ── /use command ──────────────────────────────────────────────────────────────

async def _use_autocomplete(interaction: discord.Interaction, current: str):
    try:
        uid   = str(interaction.user.id)
        items = db.get_inventory(uid)
        cur   = current.lower()
        choices = []
        for item in items:
            kws = [k.lower() for k in item.get("keywords", [])]
            if "consumable" not in kws:
                continue
            name = item["name"]
            if cur in name.lower():
                choices.append(discord.app_commands.Choice(name=name, value=name))
        return choices[:25]
    except (discord.NotFound, Exception):
        return []


@bot.tree.command(name="use", description="Use a consumable item from your inventory", guild=MY_GUILD)
@discord.app_commands.describe(item="The item to use")
@discord.app_commands.autocomplete(item=_use_autocomplete)
async def use_cmd(interaction: discord.Interaction, item: str):
    from items import get_consumable_effect
    uid    = str(interaction.user.id)
    player = db.get_player(uid)
    if not player:
        await interaction.response.send_message(
            "Pick your allegiance from the role picker first.", ephemeral=True
        )
        return

    items    = db.get_inventory(uid)
    inv_item = next((i for i in items if i["name"].lower() == item.lower()), None)
    if not inv_item:
        await interaction.response.send_message(
            f"You don't have **{item}**.", ephemeral=True
        )
        return

    heal = get_consumable_effect(inv_item)
    if heal is None:
        await interaction.response.send_message(
            f"**{item}** can't be used directly.", ephemeral=True
        )
        return

    hp, max_hp = db.get_player_hp(uid)
    if hp >= max_hp:
        await interaction.response.send_message(
            f"You're already at full HP ({hp}/{max_hp}).", ephemeral=True
        )
        return

    new_hp, max_hp, healed = db.heal_player(uid, heal)
    db.remove_inventory_item(uid, inv_item["name"], qty=1)

    await interaction.response.send_message(
        f"🧪 You used **{inv_item['name']}** and restored **{healed} HP**. "
        f"({hp} → {new_hp}/{max_hp})",
        ephemeral=True,
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


@bot.tree.command(name="df", description="See what devil fruit you've eaten", guild=MY_GUILD)
async def df_cmd(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    if not db.get_player(uid):
        await interaction.response.send_message("You're not registered.", ephemeral=True)
        return
    fruit_id = db.get_player_fruit(uid)
    if not fruit_id:
        await interaction.response.send_message(
            "You haven't eaten a devil fruit.", ephemeral=True
        )
        return
    row = get_fruit_by_id(fruit_id)
    if not row:
        await interaction.response.send_message(
            f"You've eaten `{fruit_id}`, but that fruit has no data on record.", ephemeral=True
        )
        return

    jap = (row.get("jap") or "").strip()
    eng = (row.get("eng") or "").strip()
    t1  = row.get("type1") or "Normal"
    t2  = row.get("type2") or "none"
    await interaction.response.send_message(
        f"You've eaten the **{jap}** ({eng}).\n"
        f"Type: `{t1}` / Defense modifier: `{t2}`",
        ephemeral=True,
    )




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

    # Players can't be dropped in open water — destination must be land
    from map_render import _cache, _load_map
    _load_map()
    terrain = _cache["hex_lookup"].get((q, r), "sea")
    if terrain != "island":
        await interaction.response.send_message(
            "Can't teleport a player into open sea — destination must be an island tile.",
            ephemeral=True,
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
@discord.app_commands.autocomplete(crew=_all_ships_autocomplete)
async def gm_moveship(interaction: discord.Interaction, crew: str, q: int, r: int):
    if not is_gm(interaction):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
 
    crew_row = db.get_crew(crew)
    if not crew_row:
        await interaction.response.send_message("Crew not found.", ephemeral=True)
        return

    if not game.is_passable(q, r):
        await interaction.response.send_message(
            "Can't move a ship there — that tile is an island, Red Line, Calm Belt, or blocked.",
            ephemeral=True,
        )
        return

    db.move_crew(crew, q, r)
    fq, fr, swept = game.check_ship_whirlpool(crew, q, r)
    if swept:
        await interaction.response.send_message(
            f"Moved **{crew_row['name']}**'s ship to `q={q}, r={r}` — "
            f"🌀 a whirlpool there swept it to `q={fq}, r={fr}`!"
        )
    else:
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

@gm_group.command(name="register", description="Manually register a player (backup for the role picker)")
@discord.app_commands.describe(target="The player to register")
async def gm_register(interaction: discord.Interaction, target: discord.Member):
    if not is_gm(interaction):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    uid = str(target.id)
    if db.get_player(uid):
        await interaction.response.send_message(
            f"**{target.display_name}** is already registered.", ephemeral=True
        )
        return
    db.upsert_player(uid, target.name)
    await interaction.response.send_message(
        f"Registered **{target.display_name}** into the game."
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


@gm_group.command(name="position", description="Check a player's raw hex coordinates")
@discord.app_commands.describe(target="The player")
async def gm_position(interaction: discord.Interaction, target: discord.Member):
    if not is_gm(interaction):
        await interaction.response.send_message("You don't have permission to use this.", ephemeral=True)
        return
    uid = str(target.id)
    if not db.get_player(uid):
        await interaction.response.send_message(
            f"**{target.display_name}** is not registered.", ephemeral=True
        )
        return
    pos = db.get_player_position(uid)
    if not pos:
        await interaction.response.send_message(
            f"**{target.display_name}** has no position on record.", ephemeral=True
        )
        return
    q, r = pos
    await interaction.response.send_message(
        f"**{target.display_name}** is at **q={q}, r={r}**.", ephemeral=True
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

async def _giveitem_autocomplete(interaction: discord.Interaction, current: str):
    from items import NAMED_ITEMS
    try:
        cur = current.lower()
        return [
            discord.app_commands.Choice(name=n, value=n)
            for n in NAMED_ITEMS
            if cur in n.lower()
        ][:25]
    except (discord.NotFound, Exception):
        return []

@gm_group.command(name="giveitem", description="Add an item to a player's inventory")
@discord.app_commands.describe(
    target="The player",
    name="Item name (select from list or type a custom name)",
    qty="Quantity (default 1)",
    keywords="Space-separated tags — leave blank for named items (auto-filled)",
)
@discord.app_commands.autocomplete(name=_giveitem_autocomplete)
async def gm_giveitem(
    interaction: discord.Interaction,
    target: discord.Member,
    name: str,
    qty: int = 1,
    keywords: str = "",
):
    from items import NAMED_ITEMS
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

    # Auto-fill keywords from registry if this is a named item and none were provided
    definition = NAMED_ITEMS.get(name)
    if definition and not keywords:
        kw_list = definition.get("keywords", [])
    else:
        kw_list = [k for k in keywords.split() if k] if keywords else []

    db.add_inventory_item(uid, name, qty=qty, keywords=kw_list)

    kw_str = ", ".join(kw_list) if kw_list else "no tags"
    await interaction.response.send_message(
        f"Added **{name}** ×{qty} ({kw_str}) to **{target.display_name}**'s inventory."
    )
 
 
# ── /gm take ─────────────────────────────────────────────────────────────────
 
async def _take_autocomplete(interaction: discord.Interaction, current: str):
    try:
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
    except (discord.NotFound, Exception):
        return []
 
 
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



@gm_group.command(name="removefruit", description="Remove a player's eaten Devil Fruit")
@discord.app_commands.describe(target="The player whose eaten fruit to remove")
async def gm_removefruit(interaction: discord.Interaction, target: discord.Member):
    if not is_gm(interaction):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return

    uid = str(target.id)
    if not db.get_player(uid):
        await interaction.response.send_message(
            f"**{target.display_name}** is not registered.", ephemeral=True
        )
        return

    current = db.get_player_fruit(uid)
    if not current:
        await interaction.response.send_message(
            f"**{target.display_name}** has no eaten fruit.", ephemeral=True
        )
        return

    row  = get_fruit_by_id(current)
    name = (row.get("jap") or current) if row else current
    db.set_player_fruit(uid, None)
    await interaction.response.send_message(
        f"Removed **{name}** from **{target.display_name}**."
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
        ("/gm register",  "Manually register a player — backup if the role picker fails (target)"),
        ("/gm remove",    "Remove a player from the game"),
        ("/gm position",  "Check a player's raw hex coordinates (target)"),
        ("/gm setberry",  "Set a player's berry (target, amount)"),
        ("/gm setstats",  "Set a player's battle stats — ATK, DEF, SPD, block and dodge names"),
        ("/gm setfruit",  "Set a player's eaten fruit and apply its type (target, fruit)"),
        ("/gm givefruit", "Give an uneaten fruit to a player's held slot (target, fruit)"),
        ("/gm giveitem",  "Add an item to a player's inventory (target, name, qty, keywords)"),
        ("/gm take",         "Remove a held fruit or item from a player (target, item)"),
        ("/gm removefruit",  "Remove a player's eaten Devil Fruit (target)"),
        ("/gm help",         "Show this message"),
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
        placeholder="Defense (integer)",
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
        f"Type: `{t1}` / Defense modifier: `{t2}`",
        ephemeral=False,
    )


bot.tree.add_command(gm_group)


# ── /admin command group — Admin only ─────────────────────────────────────────

admin_group = discord.app_commands.Group(
    name="admin",
    description="Admin-only commands",
    guild_ids=[MY_GUILD.id],
)


@admin_group.command(name="rolepicker", description="Post the role/job/weapon pickers")
async def admin_rolepicker(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    await interaction.channel.send("# Choose Your Allegiance!", view=RolePicker())
    await interaction.channel.send("# Choose Your Job!", view=JobPicker())
    await interaction.channel.send("# Choose Your Weapon!", view=WeaponPicker())
    await interaction.channel.send("# Grab a Devil Fruit!", view=FruitPicker())
    await interaction.followup.send("Posted!", ephemeral=True)


@admin_group.command(name="translate", description="Render text in the Poneglyph script (test)")
@discord.app_commands.describe(text="Text to render")
async def admin_translate(interaction: discord.Interaction, text: str):
    if not is_admin(interaction):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return

    import io
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype("data/Poneglyph.ttf", 96)

    tmp  = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    bbox = tmp.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    pad = 20
    img  = Image.new("RGB", (tw + pad * 2, th + pad * 2), "black")
    draw = ImageDraw.Draw(img)
    draw.text((pad - bbox[0], pad - bbox[1]), text, font=font, fill="white")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    await interaction.response.send_message(
        file=discord.File(buf, filename="poneglyph.png")
    )


@admin_group.command(name="legacymoves", description="List moves that can't be recalculated (missing keyword metadata)")
async def admin_legacymoves(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)

    players = db.db.execute("SELECT id, name FROM players").fetchall()
    lines = []
    for row in players:
        pid  = row["id"]
        name = row["name"] or pid
        moves = db.get_player_moves(pid)
        for m in moves:
            if not m.get("_keywords"):
                lines.append(f"**{name}** (`{pid[:6]}…`) — `{m.get('name','?')}` power={m.get('power','?')}")

    if not lines:
        await interaction.followup.send("No legacy moves found.", ephemeral=True)
        return

    await interaction.followup.send(
        f"**{len(lines)} legacy move(s):**\n" + "\n".join(lines),
        ephemeral=True,
    )


@admin_group.command(name="recalcmoves", description="Recompute all player moves with the current keyword formula")
async def admin_recalcmoves(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)

    from kit_commands import legacy_to_pool, build_pool_move, to_battle_dict

    players = db.db.execute("SELECT id FROM players").fetchall()
    total_moves = 0
    total_players = 0
    skipped = 0

    for row in players:
        pid = row["id"]
        moves = db.get_player_moves(pid)
        if not moves:
            continue
        updated = []
        player_changed = False
        for m in moves:
            name = m.get("name", "Move")
            # best-effort remap of any old move (keyword build or stats) to the pool model
            p, a, s, kws, _ = legacy_to_pool(m)
            result = build_pool_move(name, p, a, s, kws)
            if result["errors"]:
                updated.append(m)
                skipped += 1
                continue
            updated.append(to_battle_dict(result))
            total_moves += 1
            player_changed = True
        if player_changed:
            db.set_player_moves(pid, updated)
            total_players += 1

    await interaction.followup.send(
        f"Recalculated **{total_moves}** moves across **{total_players}** players."
        + (f" Skipped {skipped} unconvertible moves." if skipped else ""),
        ephemeral=True,
    )


@admin_group.command(name="help", description="List all admin commands")
async def admin_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🔒 Admin Commands",
        color=0x8b0000,
    )
    commands_list = [
        ("/admin rolepicker",   "Used only to refresh the rolepicker."),
        ("/admin recalcmoves",  "Recompute all player moves with the current keyword formula."),
        ("/admin legacymoves",  "List moves that can't be recalculated (missing keyword metadata)."),
        ("/admin help",         "Show this message"),
    ]
    for name, desc in commands_list:
        embed.add_field(name=name, value=desc, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@admin_group.command(name="errortest", description="Throw a test error to verify the error handler")
async def admin_errortest(interaction: discord.Interaction):
    raise RuntimeError("This is a test error from /admin errortest.")


def _build_dummy_component():
    """
    A non-functional Components V2 layout that mimics the battle card, for
    previewing the look. Buttons are placeholders — clicking one just silently
    acknowledges and does nothing. Built lazily (not at import) so the bot still
    starts on discord.py < 2.6, where these classes don't exist.
    """
    ui = discord.ui

    class _DummyButton(ui.Button):
        async def callback(self, interaction: discord.Interaction):
            await interaction.response.defer()  # no-op placeholder

    view      = ui.LayoutView(timeout=None)
    container = ui.Container(accent_colour=0x1a3f6b)

    # ── Header ──
    container.add_item(ui.TextDisplay("## ⚔  Monkey D. Luffy  vs  Sir Crocodile"))
    container.add_item(ui.TextDisplay("-# Turn 4 · waiting on both fighters"))
    container.add_item(ui.Separator())

    # ── Fighters (dummy text) ──
    container.add_item(ui.TextDisplay(
        "**Monkey D. Luffy**  ⚡ charging\n`██████████░░░░░░`  120 / 200"
    ))
    container.add_item(ui.Separator())
    container.add_item(ui.TextDisplay(
        "**Sir Crocodile**  🛡 blocking\n`████████░░░░░░░░`   95 / 200"
    ))
    container.add_item(ui.Separator())

    # ── Dummy log ──
    container.add_item(ui.TextDisplay(
        "> Luffy used **Gum-Gum Red Hawk** — 42 dmg!\n"
        "> Crocodile blocked, softening the blow."
    ))

    # ── 2x2 button grid (two action rows of two) — all non-functional ──
    row1 = ui.ActionRow()
    row1.add_item(_DummyButton(label="Attack", style=discord.ButtonStyle.danger))
    row1.add_item(_DummyButton(label="Block",  style=discord.ButtonStyle.secondary))
    row2 = ui.ActionRow()
    row2.add_item(_DummyButton(label="Dodge",   style=discord.ButtonStyle.secondary))
    row2.add_item(_DummyButton(label="Special", style=discord.ButtonStyle.primary))
    container.add_item(row1)
    container.add_item(row2)

    view.add_item(container)
    return view


@admin_group.command(name="component", description="Preview a dummy Components V2 layout (no functions)")
async def admin_component(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    try:
        view = _build_dummy_component()
    except Exception as e:
        await interaction.response.send_message(
            f"Couldn't build the Components V2 layout — this needs discord.py >= 2.6 "
            f"(installed: {discord.__version__}). Error: `{e}`",
            ephemeral=True,
        )
        return
    await interaction.response.send_message(view=view, ephemeral=True)


def _build_maptest_component():
    """
    Vertical-spacing test: a static map image with a compact 3-row helm
    D-pad directly underneath, one divider between image and buttons.
    Buttons are dummy — they just defer, no movement logic. Mirrors the
    real HelmView's 6 hex directions (no N/S — hex grids don't have them).
    """
    ui = discord.ui

    class _DummyButton(ui.Button):
        async def callback(self, interaction: discord.Interaction):
            await interaction.response.defer()

    view      = ui.LayoutView(timeout=None)
    container = ui.Container(accent_colour=0x1a3f6b)

    container.add_item(ui.MediaGallery(discord.MediaGalleryItem(media="attachment://maptest.png")))
    container.add_item(ui.Separator(spacing=discord.SeparatorSpacing.small))

    row1 = ui.ActionRow()
    row1.add_item(_DummyButton(emoji="↖️", style=discord.ButtonStyle.secondary))
    row1.add_item(_DummyButton(emoji="↗️", style=discord.ButtonStyle.secondary))
    row2 = ui.ActionRow()
    row2.add_item(_DummyButton(emoji="⬅️", style=discord.ButtonStyle.secondary))
    row2.add_item(_DummyButton(emoji="➡️", style=discord.ButtonStyle.secondary))
    row3 = ui.ActionRow()
    row3.add_item(_DummyButton(emoji="↙️", style=discord.ButtonStyle.secondary))
    row3.add_item(_DummyButton(emoji="↘️", style=discord.ButtonStyle.secondary))

    container.add_item(row1)
    container.add_item(row2)
    container.add_item(row3)

    view.add_item(container)
    return view


@admin_group.command(name="maptest", description="Test: map image + compact helm buttons (no functions)")
async def admin_maptest(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("No permission.", ephemeral=True)
        return
    try:
        view = _build_maptest_component()
        file = discord.File("img/maptest.png", filename="maptest.png")
    except Exception as e:
        await interaction.response.send_message(
            f"Couldn't build the Components V2 layout — this needs discord.py >= 2.6 "
            f"(installed: {discord.__version__}). Error: `{e}`",
            ephemeral=True,
        )
        return
    await interaction.response.send_message(view=view, file=file, ephemeral=True)


bot.tree.add_command(admin_group)


# ── Role picker ───────────────────────────────────────────────────────────────

ALLEGIANCE_ROLES = ["Pirate", "Marine"]
JOB_ROLES        = ["Doctor", "Cook", "Navigator", "Helmsman", "Musician"]


class RolePicker(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🏴‍☠️ Pirate", style=discord.ButtonStyle.secondary, custom_id="role_pirate")
    async def pirate(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _assign_allegiance(interaction, "Pirate")

    @discord.ui.button(label="⚓ Marine", style=discord.ButtonStyle.secondary, custom_id="role_marine")
    async def marine(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _assign_allegiance(interaction, "Marine")


class JobPicker(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🩺 Doctor",    style=discord.ButtonStyle.secondary, custom_id="job_doctor")
    async def doctor(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _assign_job(interaction, "Doctor")

    @discord.ui.button(label="🍳 Cook",      style=discord.ButtonStyle.secondary, custom_id="job_cook")
    async def cook(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _assign_job(interaction, "Cook")

    @discord.ui.button(label="🧭 Navigator", style=discord.ButtonStyle.secondary, custom_id="job_navigator")
    async def navigator(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _assign_job(interaction, "Navigator")

    @discord.ui.button(label="🎡 Helmsman",  style=discord.ButtonStyle.secondary, custom_id="job_helmsman")
    async def helmsman(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _assign_job(interaction, "Helmsman")

    @discord.ui.button(label="🎵 Musician",  style=discord.ButtonStyle.secondary, custom_id="job_musician")
    async def musician(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _assign_job(interaction, "Musician")


class WeaponPicker(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🗡️ Sword", style=discord.ButtonStyle.secondary, custom_id="weapon_sword")
    async def sword(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        if not db.get_player(uid):
            await interaction.response.send_message(
                "Pick your allegiance from the role picker first.", ephemeral=True
            )
            return
        inv = db.get_inventory(uid)
        if any(item["name"].lower() == "sword" for item in inv):
            await interaction.response.send_message(
                "You already have a Sword.", ephemeral=True
            )
            return
        db.add_inventory_item(uid, "Sword", qty=1, keywords=[])
        await interaction.response.send_message(
            "You received a **Sword**!", ephemeral=True
        )


class FruitPicker(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🍎 Grab a Fruit",
                       style=discord.ButtonStyle.secondary, custom_id="fruit_grab")
    async def grab(self, interaction: discord.Interaction, button: discord.ui.Button):
        import random
        from fruits import FRUITS, get_fruit_by_id

        uid = str(interaction.user.id)
        if not db.get_player(uid):
            await interaction.response.send_message(
                "Pick your allegiance from the role picker first.", ephemeral=True
            )
            return

        # Once a fruit has been eaten, that's permanent — no more rolling.
        if db.get_player_fruit(uid):
            await interaction.response.send_message(
                "You have already eaten a fruit.", ephemeral=True
            )
            return

        # Otherwise allow one roll per hour.
        import time
        ROLL_COOLDOWN = 3600  # seconds
        elapsed = time.time() - (db.get_last_fruit_roll(uid) or 0)
        if elapsed < ROLL_COOLDOWN:
            remaining = int(ROLL_COOLDOWN - elapsed)
            mins, secs = divmod(remaining, 60)
            wait = f"{mins}m {secs}s" if mins else f"{secs}s"
            await interaction.response.send_message(
                f"You can roll again in {wait}.", ephemeral=True
            )
            return

        # roll a fruit that nobody else holds or has eaten
        taken     = db.get_taken_fruit_ids()
        available = [f for f in FRUITS if f.get("id") and f["id"] not in taken]
        if not available:
            await interaction.response.send_message(
                "There are no Devil Fruits left to grab.", ephemeral=True
            )
            return

        choice = random.choice(available)
        db.set_held_fruit(uid, choice["id"])
        db.set_last_fruit_roll(uid)   # start the 1-hour cooldown

        jap = (choice.get("jap") or "").strip()
        eng = (choice.get("eng") or "").strip()
        name = jap or eng or choice["id"]
        await interaction.response.send_message(
            f"You grabbed the **{name}** ({eng})! Use `/eat` to eat it.",
            ephemeral=True,
        )


async def _assign_allegiance(interaction: discord.Interaction, role_name: str):
    for rname in ALLEGIANCE_ROLES:
        existing = discord.utils.get(interaction.guild.roles, name=rname)
        if existing and existing in interaction.user.roles:
            await interaction.response.send_message(
                f"You already have the **{rname}** role.", ephemeral=True
            )
            return
    role = discord.utils.get(interaction.guild.roles, name=role_name)
    if not role:
        await interaction.response.send_message(
            f"Role '{role_name}' doesn't exist on this server.", ephemeral=True
        )
        return
    await interaction.user.add_roles(role)
    # registering an allegiance enters the player into the game
    db.upsert_player(str(interaction.user.id), interaction.user.name)
    await interaction.response.send_message(
        f"You are now a **{role_name}**! Welcome to the Grand Line.", ephemeral=True
    )


async def _assign_job(interaction: discord.Interaction, role_name: str):
    for rname in JOB_ROLES:
        existing = discord.utils.get(interaction.guild.roles, name=rname)
        if existing and existing in interaction.user.roles:
            await interaction.response.send_message(
                f"You already have the **{rname}** role.", ephemeral=True
            )
            return
    role = discord.utils.get(interaction.guild.roles, name=role_name)
    if not role:
        await interaction.response.send_message(
            f"Role '{role_name}' doesn't exist on this server.", ephemeral=True
        )
        return
    await interaction.user.add_roles(role)
    await interaction.response.send_message(f"You are now a **{role_name}**!", ephemeral=True)














if __name__ == "__main__":
    bot.run(os.getenv("DISCORD_TOKEN"))




