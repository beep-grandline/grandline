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
    updated = game.hourly_regen()
    if updated:
        print(f"[rolls] +{game.ROLL_REGEN_AMOUNT} roll to {updated} crew(s); walk rolls and HP regenerated")


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


# ── Tile dialogue ──────────────────────────────────────────────────────────────

class DialogueView(discord.ui.View):
    """
    Minimal click-through dialogue. Shows one box at a time in a bare embed
    (just the text) with left/right buttons to page between boxes.
    """
    def __init__(self, uid: str, boxes: list):
        super().__init__(timeout=300)
        self.uid   = str(uid)
        self.boxes = boxes
        self.idx   = 0
        self._sync()

    def embed(self) -> discord.Embed:
        return discord.Embed(description=self.boxes[self.idx], color=0x2b2d31)

    def _sync(self):
        self.prev_btn.disabled = self.idx <= 0
        self.next_btn.disabled = self.idx >= len(self.boxes) - 1

    async def _guard(self, interaction) -> bool:
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("This isn't your dialogue.", ephemeral=True)
            return False
        return True

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        if self.idx > 0:
            self.idx -= 1
        self._sync()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        if self.idx < len(self.boxes) - 1:
            self.idx += 1
        self._sync()
        await interaction.response.edit_message(embed=self.embed(), view=self)


# Max hex render distance for /travel map — the compact component crops
# vertically, not sideways, so this is the same hex count shown before.
MAP_RADIUS = 7


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
    "no_walk_rolls":     "You're out of stamina. Rest a while — or get the cook to make a stamina meal.",
    "captured":          "You are under arrest and cannot move.",
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




# HelmView/travel_helm and WalkView/travel_walk (previously here) have been
# merged into the single /travel map Components V2 view below — see MapView.


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

    new_q, new_r, swept = game.check_ship_whirlpool(player["crew_id"], new_q, new_r)
    crew    = db.get_crew(player["crew_id"])
    rolls   = crew["roll"] or 0
    dir_lbl = game.DIRECTION_LABELS.get(reason, reason)
    log     = ((crew["log_pose"] if crew["log_pose"] else game.DEFAULT_LOG_POSE)).title()
    alert   = _tile_alert(new_q, new_r, uid)
    if swept:
        msg = (
            f"🌀 Heading toward **{log}**, a whirlpool swallows the ship and "
            f"spits it out at `q={new_q}, r={new_r}`!\n"
            f"`{_roll_bar(rolls)}` {rolls}/{game.ROLL_MAX} rolls remaining."
        )
    else:
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
        await interaction.response.send_message("Register first — pick your allegiance from the role picker.", ephemeral=True)
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
        await interaction.response.send_message("Register first — pick your allegiance from the role picker.", ephemeral=True)
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
        await interaction.response.send_message("Register first — pick your allegiance from the role picker.", ephemeral=True)
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
        await interaction.response.send_message("Register first — pick your allegiance from the role picker.", ephemeral=True)
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


MARINE_ALLEGIANCE    = "Marine"
MARINE_OFFICER_ROLES = {"Fleet Admiral", "Admiral", "Vice Admiral"}


def _is_marine(member) -> bool:
    names = {r.name for r in getattr(member, "roles", [])}
    return MARINE_ALLEGIANCE in names or bool(names & MARINE_OFFICER_ROLES)


async def _pose_autocomplete(interaction: discord.Interaction, current: str):
    try:
        choices = []
        cur     = current.lower()

        # Always offer Log Pose first
        if "log pose".startswith(cur) or not current:
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
            if cur in label.lower():
                choices.append(discord.app_commands.Choice(name=label, value=value))

        # Marines may navigate directly to any island or facility on the map
        if _is_marine(interaction.user):
            seen = {c.value for c in choices}
            for name in sorted(islands_mod.get_all().keys()):
                value = f"eternal:{name}"
                if value in seen:
                    continue
                if not cur or cur in name.lower():
                    choices.append(discord.app_commands.Choice(name=name, value=value))

        return choices[:25]
    except (discord.NotFound, Exception):
        return []


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
            "🧭 You are now following the log pose.", ephemeral=True
        )

    elif destination.startswith("eternal:"):
        island = destination[8:]
        if not islands_mod.get_island(island):
            await interaction.response.send_message(
                f"**{island}** isn't a known island. Select a destination from the list.",
                ephemeral=True,
            )
            return
        db.set_log_pose(crew["id"], island, pose_type="eternal")
        await interaction.response.send_message(
            f"🧭 Eternal Pose activated — destination locked to **{island}**.", ephemeral=True
        )

    else:
        await interaction.response.send_message(
            "Select an option from the list.", ephemeral=True
        )


def _map_roles(interaction: discord.Interaction, crew):
    """Which overlay layers this viewer's roles unlock. Perks are additive,
    not a single exclusive "view" anymore — a Navigator who's also Helmsman
    sees topography AND roll in the same image."""
    member       = interaction.user
    uid          = str(member.id)
    is_navigator = any(r.name == "Navigator" for r in getattr(member, "roles", []))
    is_helmsman  = any(r.name == "Helmsman"  for r in getattr(member, "roles", []))
    is_captain   = bool(crew) and str(crew["captain_id"]) == uid
    return is_navigator, is_helmsman, is_captain


def _map_status_text(player, crew) -> str:
    # No coordinates here — players are meant to be blind to their exact
    # position, just their icon + rolls/stamina remaining.
    if player["following_id"] == "ship" and crew:
        rolls = crew["roll"] or 0
        return f"⛵ `{_roll_bar(rolls)}` {rolls}/{game.ROLL_MAX} rolls"
    rolls = player["walk_roll"] if player["walk_roll"] is not None else game.WALK_ROLL_MAX
    return f"🚶 `{_roll_bar(rolls, max_rolls=game.WALK_ROLL_MAX)}` {rolls}/{game.WALK_ROLL_MAX} walk moves"


class MapView(discord.ui.LayoutView):
    """
    Unified /travel map component — replaces the old separate /travel walk
    and /travel helm button panels. Movement mode (steer the ship vs. walk
    on foot) is resolved fresh from the player's current following_id on
    every button press rather than fixed at open time, since it can change
    out from under a long-lived ephemeral message (disembark, reboard,
    solo, etc. are all separate commands the player can run in between).

    Overlay layers (topography / roll) are fixed per-viewer at open time —
    they're role perks, not movement state, so they don't need re-checking
    every press.
    """

    def __init__(self, uid: str, show_topography: bool, show_roll: bool):
        super().__init__(timeout=300)
        self.uid             = uid
        self.show_topography = show_topography
        self.show_roll       = show_roll

        self.gallery = discord.ui.MediaGallery(discord.MediaGalleryItem(media="attachment://map.png"))
        self.status  = discord.ui.TextDisplay("​")   # placeholder, set via set_status()

        container = discord.ui.Container(accent_colour=0x1a3f6b)
        container.add_item(self.gallery)
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
        container.add_item(self.status)
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))

        # 4-over-2 D-pad: top row ⬅️ ↖️ ↗️ ➡️, bottom row ↙️ ↘️ centered
        # under the middle two (↖️/↗️) columns via blank disabled spacers —
        # ActionRow has no real column alignment, so this fakes it.
        row1 = discord.ui.ActionRow()
        row1.add_item(self._nav_button("⬅️", "b"))
        row1.add_item(self._nav_button("↖️", "bl"))
        row1.add_item(self._nav_button("↗️", "fl"))
        row1.add_item(self._nav_button("➡️", "f"))
        row2 = discord.ui.ActionRow()
        row2.add_item(discord.ui.Button(label="​", style=discord.ButtonStyle.secondary, disabled=True))
        row2.add_item(self._nav_button("↙️", "br"))
        row2.add_item(self._nav_button("↘️", "fr"))
        row2.add_item(discord.ui.Button(label="​", style=discord.ButtonStyle.secondary, disabled=True))

        container.add_item(row1)
        container.add_item(row2)
        self.add_item(container)

    def _nav_button(self, emoji: str, direction: str) -> discord.ui.Button:
        button = discord.ui.Button(emoji=emoji, style=discord.ButtonStyle.secondary)

        async def _callback(interaction: discord.Interaction, direction=direction):
            await self._move(interaction, direction)

        button.callback = _callback
        return button

    def set_status(self, text: str):
        self.status.content = text

    async def _rerender(self, interaction: discord.Interaction):
        """Re-render the map image at the player's new position and edit
        it into the same component in place — this is the only thing that
        ever edits onto the component; every alert below goes ephemeral."""
        loop = asyncio.get_event_loop()
        buf  = await loop.run_in_executor(
            None, map_render.render_map, self.uid, MAP_RADIUS,
            self.show_topography, self.show_roll, self.show_topography,
        )
        file = discord.File(buf, filename="map.png")
        await interaction.response.edit_message(attachments=[file], view=self)

    async def _move(self, interaction: discord.Interaction, direction: str):
        uid    = self.uid
        player = db.get_player(uid)
        if not player:
            await interaction.response.send_message("Register first.", ephemeral=True)
            return

        swept       = False
        moved_q     = moved_r = None
        was_on_ship = player["following_id"] == "ship"

        if was_on_ship:
            crew = db.get_crew(player["crew_id"]) if player["crew_id"] else None
            if not crew:
                await interaction.response.send_message("Crew not found.", ephemeral=True)
                return
            if str(crew["captain_id"]) != uid:
                await interaction.response.send_message("Only the captain can steer.", ephemeral=True)
                return
            new_q, new_r, ok, reason = game.move_ship(player["crew_id"], direction)
            if not ok:
                await interaction.response.send_message(MOVE_FAILURE.get(reason, reason), ephemeral=True)
                return
            new_q, new_r, swept = game.check_ship_whirlpool(player["crew_id"], new_q, new_r)
            crew  = db.get_crew(player["crew_id"])
            rolls = crew["roll"] or 0
            self.set_status(f"⛵ `{_roll_bar(rolls)}` {rolls}/{game.ROLL_MAX} rolls")
            moved_q, moved_r = new_q, new_r

        elif player["following_id"] and player["following_id"] != uid:
            await interaction.response.send_message(
                "You're following the captain. Use `/travel solo` to move independently.", ephemeral=True
            )
            return

        else:
            new_q, new_r, ok, reason = game.move_player(uid, direction)
            if not ok:
                await interaction.response.send_message(MOVE_FAILURE.get(reason, reason), ephemeral=True)
                return
            p     = db.get_player(uid)
            rolls = p["walk_roll"] if p and p["walk_roll"] is not None else 0
            self.set_status(f"🚶 `{_roll_bar(rolls, max_rolls=game.WALK_ROLL_MAX)}` {rolls}/{game.WALK_ROLL_MAX} walk moves")
            moved_q, moved_r = new_q, new_r

        await self._rerender(interaction)

        # Extra alerts — ephemeral only, never edited onto the component.
        if swept:
            await interaction.followup.send(
                f"🌀 A whirlpool swallows you and spits you out at `q={moved_q}, r={moved_r}`!",
                ephemeral=True,
            )
        alert = _tile_alert(moved_q, moved_r, uid)
        if alert:
            await interaction.followup.send(alert, ephemeral=True)

        if not was_on_ship:
            boxes = map_render.get_dialogue(moved_q, moved_r)
            if boxes:
                dview = DialogueView(uid, boxes)
                await interaction.followup.send(embed=dview.embed(), view=dview, ephemeral=True)


@travel_group.command(name="map", description="View your current area and move")
async def travel_map(interaction: discord.Interaction):
    uid    = str(interaction.user.id)
    player = db.get_player(uid)
    if not player:
        await interaction.response.send_message(
            "Register first — pick your allegiance from the role picker.", ephemeral=True
        )
        return

    crew = db.get_crew(player["crew_id"]) if player["crew_id"] else None
    is_navigator, is_helmsman, is_captain = _map_roles(interaction, crew)
    show_topography = is_navigator
    show_roll       = is_captain or is_helmsman

    await interaction.response.defer(ephemeral=True)
    loop = asyncio.get_event_loop()
    buf  = await loop.run_in_executor(
        None, map_render.render_map, uid, MAP_RADIUS, show_topography, show_roll, show_topography
    )
    if not buf:
        await interaction.followup.send(
            "You are not registered yet. Use `/register` first.", ephemeral=True
        )
        return

    view = MapView(uid=uid, show_topography=show_topography, show_roll=show_roll)
    view.set_status(_map_status_text(player, crew))
    file = discord.File(buf, filename="map.png")
    await interaction.followup.send(file=file, view=view, ephemeral=True)
