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
from config import GUILD_ID

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

def _is_captain(interaction: discord.Interaction, crew):
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
    "impassable":        "That way leads into the Calm Belt — impossible to pass.",
    "invalid_direction": "Invalid direction.",
    "crew_not_found":    "Crew not found.",
    "island_not_found":  "Log pose island not found on the map.",
    "already_there":     "You're already at your log pose destination.",
    "no_path":           "No navigable path toward the log pose from here.",
    "not_found":         "Player not found.",
}

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
        await interaction.response.edit_message(
            content=(
                f"⛵ `q={new_q}, r={new_r}`\n"
                f"`{_roll_bar(rolls)}` {rolls}/{game.ROLL_MAX} rolls"
            )
        )

    @discord.ui.button(emoji="↖️", style=discord.ButtonStyle.secondary, row=0)
    async def btn_lb(self, i, b): await self._move(i, "lb")

    @discord.ui.button(emoji="↗️", style=discord.ButtonStyle.secondary, row=0)
    async def btn_lf(self, i, b): await self._move(i, "lf")

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
    async def btn_bw(self, i, b): await self._move(i, "bw")

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.secondary, row=1)
    async def btn_fw(self, i, b): await self._move(i, "fw")

    @discord.ui.button(emoji="↙️", style=discord.ButtonStyle.secondary, row=2)
    async def btn_rb(self, i, b): await self._move(i, "rb")

    @discord.ui.button(emoji="↘️", style=discord.ButtonStyle.secondary, row=2)
    async def btn_rf(self, i, b): await self._move(i, "rf")


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
    await interaction.response.send_message(
        f"⛵ Heading toward **{log}** — moved **{dir_lbl}** → `q={new_q}, r={new_r}`\n"
        f"`{_roll_bar(rolls)}` {rolls}/{game.ROLL_MAX} rolls remaining."
    )


@travel_group.command(name="disembark", description="Leave the ship and move on foot")
async def travel_disembark(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    if not db.get_player(uid):
        await interaction.response.send_message("Register first with `/register`.", ephemeral=True)
        return

    player = db.get_player(uid)
    if player["following_id"] != "ship":
        await interaction.response.send_message("You're not on the ship.", ephemeral=True)
        return

    ok = game.disembark(uid)
    if not ok:
        await interaction.response.send_message("Couldn't disembark — are you in a crew?", ephemeral=True)
        return

    player = db.get_player(uid)
    fid    = player["following_id"]
    if fid:
        await interaction.response.send_message(
            "You disembarked. You're now following the captain on land.\n"
            "Use `/travel solo` to move independently.", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "You disembarked as captain. Crew members will follow you.", ephemeral=True
        )


@travel_group.command(name="reboard", description="Return to the ship")
async def travel_reboard(interaction: discord.Interaction):
    uid    = str(interaction.user.id)
    player = db.get_player(uid)
    if not player:
        await interaction.response.send_message("Register first with `/register`.", ephemeral=True)
        return

    if player["following_id"] == "ship":
        await interaction.response.send_message("You're already on the ship.", ephemeral=True)
        return

    ok = game.reboard(uid)
    if not ok:
        await interaction.response.send_message("Couldn't reboard — are you in a crew?", ephemeral=True)
        return

    crew  = db.get_crew(player["crew_id"])
    q, r  = crew["q"] or 0, crew["r"] or 0
    await interaction.response.send_message(
        f"You reboarded the ship at `q={q}, r={r}`.", ephemeral=True
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


@travel_group.command(name="walkto", description="Move yourself one hex while on land (solo or captain)")
@discord.app_commands.describe(direction="Direction to walk")
@discord.app_commands.choices(direction=_DIR_CHOICES)
async def travel_walkto(interaction: discord.Interaction, direction: str):
    uid    = str(interaction.user.id)
    player = db.get_player(uid)
    if not player:
        await interaction.response.send_message("Register first with `/register`.", ephemeral=True)
        return

    if player["following_id"] == "ship":
        await interaction.response.send_message(
            "You're on the ship. Use `/travel move` to move the ship, "
            "or `/travel disembark` to go on foot.", ephemeral=True
        )
        return

    if player["following_id"] and player["following_id"] != str(interaction.user.id):
        await interaction.response.send_message(
            "You're following the captain. Use `/travel solo` to move independently.", ephemeral=True
        )
        return

    new_q, new_r, ok, reason = game.move_player(uid, direction)
    if not ok:
        await interaction.response.send_message(MOVE_FAILURE.get(reason, reason), ephemeral=True)
        return

    dir_lbl = game.DIRECTION_LABELS[direction]
    await interaction.response.send_message(
        f"🚶 Moved **{dir_lbl}** → `q={new_q}, r={new_r}`", ephemeral=True
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
