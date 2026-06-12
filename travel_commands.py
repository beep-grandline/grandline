# ═══════════════════════════════════════════════════════════════════════════════
#  travel_commands.py  ·  /travel command group + roll regen background task
#  Add to bot.py:
#      from travel_commands import travel_group, setup_travel_task
#      bot.tree.add_command(travel_group)
#      # inside on_ready:
#      setup_travel_task(bot)
# ═══════════════════════════════════════════════════════════════════════════════

import asyncio
import discord
from discord.ext import tasks
import db
import game
import map_render
import islands as islands_mod
from config import GUILD_ID
from npcs import get_npcs_at

# ── Roll regen task ───────────────────────────────────────────────────────────

@tasks.loop(minutes=game.ROLL_REGEN_MINUTES)
async def _roll_regen():
    updated = game.replenish_rolls()
    if updated:
        print(f"[rolls] +{game.ROLL_REGEN_AMOUNT} roll to {updated} crew(s)")


def setup_travel_task(bot):
    """Call this inside on_ready to start the roll regen loop."""
    if not _roll_regen.is_running():
        _roll_regen.start()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tile_alert(q: int, r: int, uid: str) -> str:
    """Returns an alert string if there are NPCs or players on the tile."""
    from npcs import get_npcs_at, should_npc_initiate
    lines   = []
    player  = db.get_player(uid)
    npcs    = get_npcs_at(q, r)
    players = game.get_players_at(q, r, exclude_uid=uid)

    for npc in npcs:
        if player and should_npc_initiate(npc, player):
            lines.append(f"⚔️ **{npc['name']}** is hostile! Use `/battle` to fight.")
        else:
            lines.append(f"⚠️ **{npc['name']}** is here.")

    for p in players:
        name = p["char_name"] or str(p["id"])
        lines.append(f"⚠️ **{name}** is here.")

    return "\n".join(lines)



    return crew and str(crew["captain_id"]) == str(interaction.user.id)


def _roll_bar(current, max_rolls=game.ROLL_MAX, width=12):
    filled = round((current / max_rolls) * width)
    return "█" * filled + "░" * (width - filled)


def _status_embed(player, crew, q, r):
    fid   = player["following_id"]
    if fid == "ship":   mode = "Aboard ship"
    elif fid:           mode = "Following captain"
    else:               mode = "Solo"

    embed = discord.Embed(title="📍 Position", color=0x1a3f6b)
    embed.add_field(name="Coordinates", value=f"`q={q}, r={r}`",   inline=True)
    embed.add_field(name="Mode",        value=mode,                 inline=True)

    if crew:
        rolls = crew["roll"] or 0
        embed.add_field(
            name="Ship Rolls",
            value=f"`{_roll_bar(rolls)}` {rolls}/{game.ROLL_MAX}",
            inline=False,
        )
        log_pose = (crew["log_pose"] if crew["log_pose"] else game.DEFAULT_LOG_POSE)
        embed.add_field(name="Log Pose", value=log_pose.title(), inline=True)

    return embed


MOVE_FAILURE = {
    "no_rolls":          "The ship has no rolls left. Wait for them to recharge.",
    "impassable":        "Can't move there.",
    "ship_disabled":     "Your ship is disabled — it needs repairs before you can sail.",
    "invalid_direction": "Invalid direction.",
    "crew_not_found":    "Crew not found.",
    "island_not_found":  "Log pose island not found on the map.",
    "already_there":     "You're already at your log pose destination.",
    "no_path":           "No navigable path toward the log pose from here.",
    "not_found":         "Player not found.",
    "no_walking_on_sea": "You can't walk on open sea. Stay on land.",
}


def _is_captain(interaction: discord.Interaction, crew) -> bool:
    return crew and str(crew["captain_id"]) == str(interaction.user.id)

# ── Travel command group ──────────────────────────────────────────────────────

travel_group = discord.app_commands.Group(
    name="travel",
    description="Navigation and movement",
    guild_ids=[GUILD_ID],
)

_DIR_CHOICES = [
    discord.app_commands.Choice(name=label, value=key)
    for key, label in game.DIRECTION_LABELS.items()
]


@travel_group.command(name="status", description="Show your current position and ship rolls")
async def travel_status(interaction: discord.Interaction):
    uid    = str(interaction.user.id)
    player = db.get_player(uid)
    if not player:
        await interaction.response.send_message("Register first with `/register`.", ephemeral=True)
        return

    crew  = db.get_crew(player["crew_id"]) if player["crew_id"] else None
    q, r  = game.get_position(uid)
    embed = _status_embed(player, crew, q, r)
    await interaction.response.send_message(embed=embed, ephemeral=True)



class HelmView(discord.ui.View):
    def __init__(self, crew_id: str, captain_id: str):
        super().__init__(timeout=300)
        self.crew_id    = crew_id
        self.captain_id = captain_id

    async def _move(self, interaction: discord.Interaction, direction: str):
        if str(interaction.user.id) != self.captain_id:
            await interaction.response.send_message(
                "Only the captain can steer.", ephemeral=True
            )
            return
        new_q, new_r, ok, reason = game.move_ship(self.crew_id, direction)
        if not ok:
            await interaction.response.edit_message(
                content=MOVE_FAILURE.get(reason, reason)
            )
            return
        crew  = db.get_crew(self.crew_id)
        rolls = crew["roll"] or 0
        alert = _tile_alert(new_q, new_r, str(interaction.user.id))
        msg   = (
            f"⛵ `q={new_q}, r={new_r}`\n"
            f"`{_roll_bar(rolls)}` {rolls}/{game.ROLL_MAX} rolls"
        )
        if alert:
            msg += f"\n{alert}"
        await interaction.response.edit_message(content=msg)

    @discord.ui.button(emoji="↖️", style=discord.ButtonStyle.secondary, row=0)
    async def btn_bl(self, i, b): await self._move(i, "bl")

    @discord.ui.button(emoji="↗️", style=discord.ButtonStyle.secondary, row=0)
    async def btn_fl(self, i, b): await self._move(i, "fl")

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def btn_b(self, i, b):  await self._move(i, "b")

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.secondary, row=1)
    async def btn_f(self, i, b):  await self._move(i, "f")

    @discord.ui.button(emoji="↙️", style=discord.ButtonStyle.secondary, row=2)
    async def btn_br(self, i, b): await self._move(i, "br")

    @discord.ui.button(emoji="↘️", style=discord.ButtonStyle.secondary, row=2)
    async def btn_fr(self, i, b): await self._move(i, "fr")


@travel_group.command(name="helm", description="Take the helm and steer the ship (captain only)")
async def travel_helm(interaction: discord.Interaction):
    uid    = str(interaction.user.id)
    player = db.get_player(uid)
    if not player or not player["crew_id"]:
        await interaction.response.send_message("You need to be in a crew.", ephemeral=True)
        return

    crew = db.get_crew(player["crew_id"])
    if not _is_captain(interaction, crew):
        await interaction.response.send_message("Only the captain can take the helm.", ephemeral=True)
        return

    rolls = crew["roll"] or 0
    q     = crew["q"] or 0
    r     = crew["r"] or 0
    view  = HelmView(crew_id=player["crew_id"], captain_id=uid)
    await interaction.response.send_message(
        f"⛵ `q={q}, r={r}`\n"
        f"`{_roll_bar(rolls)}` {rolls}/{game.ROLL_MAX} rolls",
        view=view,
        ephemeral=True,
    )


@travel_group.command(name="auto", description="Move one step toward your log pose (captain only)")
async def travel_auto(interaction: discord.Interaction):
    uid    = str(interaction.user.id)
    player = db.get_player(uid)
    if not player or not player["crew_id"]:
        await interaction.response.send_message("You need to be in a crew.", ephemeral=True)
        return

    crew = db.get_crew(player["crew_id"])
    if not _is_captain(interaction, crew):
        await interaction.response.send_message("Only the captain can navigate.", ephemeral=True)
        return

    new_q, new_r, ok, reason = game.step_toward_log_pose(player["crew_id"])
    if not ok:
        await interaction.response.send_message(MOVE_FAILURE.get(reason, reason), ephemeral=True)
        return

    crew    = db.get_crew(player["crew_id"])
    rolls   = crew["roll"] or 0
    dir_lbl = game.DIRECTION_LABELS.get(reason, reason)
    log     = ((crew["log_pose"] if crew["log_pose"] else game.DEFAULT_LOG_POSE)).title()
    alert   = _tile_alert(new_q, new_r, uid)
    msg = (
        f"⛵ Heading toward **{log}** — moved **{dir_lbl}** → `q={new_q}, r={new_r}`\n"
        f"`{_roll_bar(rolls)}` {rolls}/{game.ROLL_MAX} rolls remaining."
    )
    if alert:
        msg += f"\n{alert}"
    await interaction.response.send_message(msg)


@travel_group.command(name="disembark", description="Leave the ship onto an adjacent island tile")
async def travel_disembark(interaction: discord.Interaction):
    uid    = str(interaction.user.id)
    player = db.get_player(uid)
    if not player:
        await interaction.response.send_message("Register first with `/register`.", ephemeral=True)
        return

    if player["following_id"] != "ship":
        await interaction.response.send_message("You're not on the ship.", ephemeral=True)
        return

    crew = db.get_crew(player["crew_id"]) if player["crew_id"] else None
    if not crew:
        await interaction.response.send_message("Couldn't disembark — are you in a crew?", ephemeral=True)
        return

    sq, sr = crew["q"] or 0, crew["r"] or 0
    land_tile = game.adjacent_island_tile(sq, sr)
    if not land_tile:
        await interaction.response.send_message(
            "The ship isn't next to any island. Sail closer to shore first.", ephemeral=True
        )
        return

    lq, lr = land_tile
    db.update_player_position(uid, lq, lr)

    is_captain = str(crew["captain_id"]) == uid
    if is_captain:
        db.set_following(uid, None)
        await interaction.response.send_message(
            f"You stepped ashore at `q={lq}, r={lr}`. Crew members will follow you on land.",
            ephemeral=True,
        )
    else:
        db.set_following(uid, str(crew["captain_id"]))
        await interaction.response.send_message(
            f"You stepped ashore at `q={lq}, r={lr}` and are following the captain.\n"
            "Use `/travel solo` to move independently.",
            ephemeral=True,
        )


@travel_group.command(name="reboard", description="Board the ship — must be on an adjacent tile")
async def travel_reboard(interaction: discord.Interaction):
    uid    = str(interaction.user.id)
    player = db.get_player(uid)
    if not player:
        await interaction.response.send_message("Register first with `/register`.", ephemeral=True)
        return

    if player["following_id"] == "ship":
        await interaction.response.send_message("You're already on the ship.", ephemeral=True)
        return

    crew = db.get_crew(player["crew_id"]) if player["crew_id"] else None
    if not crew:
        await interaction.response.send_message("Couldn't reboard — are you in a crew?", ephemeral=True)
        return

    sq, sr = crew["q"] or 0, crew["r"] or 0
    pq, pr = game.get_position(uid)

    if not game.is_adjacent(pq, pr, sq, sr):
        await interaction.response.send_message(
            f"You're too far from the ship (`q={sq}, r={sr}`). Move to an adjacent tile first.",
            ephemeral=True,
        )
        return

    db.update_player_position(uid, sq, sr)
    db.set_following(uid, "ship")
    await interaction.response.send_message(
        f"You're back on the ship at `q={sq}, r={sr}`.", ephemeral=True
    )


@travel_group.command(name="rejoin", description="Teleport back to the captain's position")
async def travel_rejoin(interaction: discord.Interaction):
    uid    = str(interaction.user.id)
    player = db.get_player(uid)
    if not player:
        await interaction.response.send_message("Register first with `/register`.", ephemeral=True)
        return

    if player["following_id"] == "ship":
        await interaction.response.send_message("You're already on the ship.", ephemeral=True)
        return

    crew = db.get_crew(player["crew_id"]) if player["crew_id"] else None
    if not crew:
        await interaction.response.send_message("You're not in a crew.", ephemeral=True)
        return

    if str(crew["captain_id"]) == uid:
        await interaction.response.send_message("You're the captain — there's no one to rejoin.", ephemeral=True)
        return

    cq, cr = game.get_position(str(crew["captain_id"]))
    db.update_player_position(uid, cq, cr)
    db.set_following(uid, str(crew["captain_id"]))
    await interaction.response.send_message(
        f"You rejoined the captain at `q={cq}, r={cr}`.", ephemeral=True
    )


@travel_group.command(name="solo", description="Break away and move independently")
async def travel_solo(interaction: discord.Interaction):
    uid    = str(interaction.user.id)
    player = db.get_player(uid)
    if not player:
        await interaction.response.send_message("Register first with `/register`.", ephemeral=True)
        return

    if player["following_id"] is None:
        await interaction.response.send_message("You're already moving independently.", ephemeral=True)
        return

    game.go_solo(uid)
    q, r = game.get_position(uid)
    await interaction.response.send_message(
        f"You're now moving independently at `q={q}, r={r}`.\n"
        f"Use `/travel reboard` to return to the ship.", ephemeral=True
    )


class WalkView(discord.ui.View):
    def __init__(self, uid: str):
        super().__init__(timeout=300)
        self.uid = uid

    async def _walk(self, interaction: discord.Interaction, direction: str):
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("This isn't your movement panel.", ephemeral=True)
            return
        new_q, new_r, ok, reason = game.move_player(self.uid, direction)
        if not ok:
            await interaction.response.edit_message(
                content=MOVE_FAILURE.get(reason, reason)
            )
            return
        alert = _tile_alert(new_q, new_r, self.uid)
        msg   = f"🚶 `q={new_q}, r={new_r}`"
        if alert:
            msg += f"\n{alert}"
        await interaction.response.edit_message(content=msg)

    @discord.ui.button(emoji="↖️", style=discord.ButtonStyle.secondary, row=0)
    async def btn_bl(self, i, b): await self._walk(i, "bl")

    @discord.ui.button(emoji="↗️", style=discord.ButtonStyle.secondary, row=0)
    async def btn_fl(self, i, b): await self._walk(i, "fl")

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def btn_b(self, i, b):  await self._walk(i, "b")

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.secondary, row=1)
    async def btn_f(self, i, b):  await self._walk(i, "f")

    @discord.ui.button(emoji="↙️", style=discord.ButtonStyle.secondary, row=2)
    async def btn_br(self, i, b): await self._walk(i, "br")

    @discord.ui.button(emoji="↘️", style=discord.ButtonStyle.secondary, row=2)
    async def btn_fr(self, i, b): await self._walk(i, "fr")


@travel_group.command(name="walk", description="Move on foot — island tiles only")
async def travel_walk(interaction: discord.Interaction):
    uid    = str(interaction.user.id)
    player = db.get_player(uid)
    if not player:
        await interaction.response.send_message("Register first with `/register`.", ephemeral=True)
        return

    if player["following_id"] == "ship":
        await interaction.response.send_message(
            "You're on the ship. Use `/travel disembark` first.", ephemeral=True
        )
        return

    if player["following_id"] and player["following_id"] != uid:
        await interaction.response.send_message(
            "You're following the captain. Use `/travel solo` to move independently.", ephemeral=True
        )
        return

    q, r  = game.get_position(uid)
    view  = WalkView(uid=uid)
    await interaction.response.send_message(
        f"🚶 `q={q}, r={r}`",
        view=view,
        ephemeral=True,
    )


async def _pose_autocomplete(interaction: discord.Interaction, current: str):
    choices = []

    # Always offer Log Pose first
    if "log pose".startswith(current.lower()) or not current:
        choices.append(discord.app_commands.Choice(name="Log Pose", value="log"))

    # Eternal Poses from inventory
    uid   = str(interaction.user.id)
    items = db.get_inventory(uid)
    for item in items:
        kws = item.get("keywords", [])
        if "Eternal Pose" not in item.get("name", "") and not any(k.lower() == "eternal" for k in kws):
            continue
        # destination island: first keyword that isn't "eternal"
        dest = next((k for k in kws if k.lower() != "eternal"), None)
        if not dest:
            continue
        label = f"Eternal Pose → {dest}"
        value = f"eternal:{dest}"
        if current.lower() in label.lower():
            choices.append(discord.app_commands.Choice(name=label, value=value))

    return choices[:25]


@travel_group.command(name="pose", description="Set your navigation destination (captain only)")
@discord.app_commands.describe(destination="Log Pose or an Eternal Pose from your inventory")
@discord.app_commands.autocomplete(destination=_pose_autocomplete)
async def travel_pose(interaction: discord.Interaction, destination: str):
    uid    = str(interaction.user.id)
    player = db.get_player(uid)
    if not player or not player["crew_id"]:
        await interaction.response.send_message("You need to be in a crew.", ephemeral=True)
        return

    crew = db.get_crew(player["crew_id"])
    if not _is_captain(interaction, crew):
        await interaction.response.send_message("Only the captain can set the pose.", ephemeral=True)
        return

    if destination == "log":
        current_island = crew["log_pose"] or game.DEFAULT_LOG_POSE
        island_data    = islands_mod.get_island(current_island)
        next_island    = (island_data or {}).get("next") or current_island
        db.set_log_pose(crew["id"], next_island, pose_type="log")
        await interaction.response.send_message(
            f"🧭 Log Pose set — navigating toward **{next_island}**.", ephemeral=True
        )

    elif destination.startswith("eternal:"):
        island = destination[8:]
        db.set_log_pose(crew["id"], island, pose_type="eternal")
        await interaction.response.send_message(
            f"🧭 Eternal Pose activated — destination locked to **{island}**.", ephemeral=True
        )

    else:
        await interaction.response.send_message(
            "Select an option from the list.", ephemeral=True
        )


@travel_group.command(name="map", description="View your current area")
@discord.app_commands.describe(view="Map view")
@discord.app_commands.choices(view=[
    discord.app_commands.Choice(name="default", value="default"),
    discord.app_commands.Choice(name="roll",    value="roll"),
])
async def travel_map(interaction: discord.Interaction, view: str = "default"):
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
