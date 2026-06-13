# ═══════════════════════════════════════════════════════════════════════════════
#  marine_commands.py  ·  /marine arrest, release, prisoners
#  Add to bot.py:
#      from marine_commands import marine_group
#      bot.tree.add_command(marine_group)
# ═══════════════════════════════════════════════════════════════════════════════

import discord
import db
import game
from config import GUILD_ID

MARINE_ROLES = {"Fleet Admiral", "Admiral", "Vice Admiral"}
MARINE_COLOR  = 0x1a4b8c

IMPEL_DOWN_Q = game.IMPEL_DOWN_Q
IMPEL_DOWN_R = game.IMPEL_DOWN_R


def _is_marine_officer(member: discord.Member) -> bool:
    return any(r.name in MARINE_ROLES for r in getattr(member, "roles", []))


marine_group = discord.app_commands.Group(
    name="marine",
    description="Marine officer commands",
    guild_ids=[GUILD_ID],
)


@marine_group.command(name="sail", description="Commission your Marine battleship")
async def marine_sail(interaction: discord.Interaction):
    uid = str(interaction.user.id)

    if not _is_marine_officer(interaction.user):
        await interaction.response.send_message(
            "Only a **Fleet Admiral**, **Admiral**, or **Vice Admiral** can command a battleship.",
            ephemeral=True,
        )
        return

    if not db.get_player(uid):
        await interaction.response.send_message("Register first with `/register`.", ephemeral=True)
        return

    existing = db.get_battleship(uid)
    if existing:
        q = existing["q"] or 0
        r = existing["r"] or 0
        await interaction.response.send_message(
            f"You already command **{existing['name']}** — currently at `q={q}, r={r}`.\n"
            f"Use `/travel helm` to steer it.",
            ephemeral=True,
        )
        return

    # Build the ship name from their highest-ranked role
    rank = next(
        (r.name for r in interaction.user.roles if r.name in MARINE_ROLES),
        "Officer"
    )
    ship_name = f"{interaction.user.display_name}'s Battleship"

    crew_id = db.create_battleship(uid, ship_name)

    # Assign the officer to their battleship crew
    db.set_player_crew(uid, crew_id)
    db.set_following(uid, "ship")

    await interaction.response.send_message(
        f"⚓ **{ship_name}** is now commissioned, {rank} {interaction.user.mention}!\n"
        f"Use `/travel helm` to steer and `/travel disembark` to go ashore.\n"
        f"Your ship starts at `q=0, r=0`."
    )


@marine_group.command(name="arrest", description="Arrest a defeated player (0 HP required)")
@discord.app_commands.describe(target="The player to arrest")
async def marine_arrest(interaction: discord.Interaction, target: discord.Member):
    uid = str(interaction.user.id)
    tid = str(target.id)

    if not _is_marine_officer(interaction.user):
        await interaction.response.send_message(
            "Only a **Fleet Admiral**, **Admiral**, or **Vice Admiral** can make arrests.",
            ephemeral=True,
        )
        return

    if not db.get_player(uid):
        await interaction.response.send_message("Register first with `/register`.", ephemeral=True)
        return

    if target.id == interaction.user.id:
        await interaction.response.send_message("You can't arrest yourself.", ephemeral=True)
        return

    if target.bot:
        await interaction.response.send_message("You can't arrest a bot.", ephemeral=True)
        return

    target_row = db.get_player(tid)
    if not target_row:
        await interaction.response.send_message(
            f"{target.display_name} isn't registered.", ephemeral=True
        )
        return

    if target_row["captured_by"]:
        await interaction.response.send_message(
            f"{target.display_name} is already under arrest.", ephemeral=True
        )
        return

    hp = target_row["hp"] if target_row["hp"] is not None else 100
    if hp > 0:
        await interaction.response.send_message(
            f"{target.display_name} still has **{hp} HP** — you can only arrest a defeated fighter.",
            ephemeral=True,
        )
        return

    # Location check — officer and target must be on the same tile
    oq, orr = game.get_position(uid)
    tq, tr  = game.get_position(tid)
    if (oq, orr) != (tq, tr):
        await interaction.response.send_message(
            f"You must be in the same location as {target.display_name} to arrest them.",
            ephemeral=True,
        )
        return

    db.set_captured(tid, uid)
    await interaction.response.send_message(
        f"⛓️ {interaction.user.mention} arrests {target.mention}. "
        f"They are now in custody."
    )


@marine_group.command(name="release", description="Release your prisoner at your current location")
@discord.app_commands.describe(target="Which prisoner to release (leave blank if you have only one)")
async def marine_release(interaction: discord.Interaction, target: discord.Member = None):
    uid = str(interaction.user.id)

    if not _is_marine_officer(interaction.user):
        await interaction.response.send_message(
            "Only a **Fleet Admiral**, **Admiral**, or **Vice Admiral** can release prisoners.",
            ephemeral=True,
        )
        return

    if not db.get_player(uid):
        await interaction.response.send_message("Register first with `/register`.", ephemeral=True)
        return

    prisoners = db.get_prisoners(uid)
    if not prisoners:
        await interaction.response.send_message("You have no prisoners.", ephemeral=True)
        return

    # Choose which prisoner to release
    if target is None:
        if len(prisoners) > 1:
            names = ", ".join(p["name"] for p in prisoners)
            await interaction.response.send_message(
                f"You have multiple prisoners: **{names}**. Specify who to release.",
                ephemeral=True,
            )
            return
        prisoner = prisoners[0]
    else:
        tid = str(target.id)
        prisoner = next((p for p in prisoners if str(p["id"]) == tid), None)
        if not prisoner:
            await interaction.response.send_message(
                f"{target.display_name} is not your prisoner.", ephemeral=True
            )
            return

    # Determine release location — must be island tile or Impel Down
    oq, orr = game.get_position(uid)
    at_impel_down = (oq, orr) == (IMPEL_DOWN_Q, IMPEL_DOWN_R)

    if not at_impel_down:
        try:
            from map_render import _cache, _load_map
            _load_map()
            terrain = _cache["hex_lookup"].get((oq, orr), "sea")
        except Exception:
            terrain = "sea"
        if terrain != "island":
            await interaction.response.send_message(
                "You can only release a prisoner on an island or at Impel Down.",
                ephemeral=True,
            )
            return

    prisoner_id   = str(prisoner["id"])
    prisoner_name = prisoner["name"]
    db.release_prisoner(prisoner_id, oq, orr)

    location_str = "Impel Down" if at_impel_down else f"q={oq}, r={orr}"
    await interaction.response.send_message(
        f"🔓 {interaction.user.mention} releases **{prisoner_name}** at {location_str}."
    )


@marine_group.command(name="prisoners", description="List your current prisoners")
async def marine_prisoners(interaction: discord.Interaction):
    uid = str(interaction.user.id)

    if not _is_marine_officer(interaction.user):
        await interaction.response.send_message(
            "Only a **Fleet Admiral**, **Admiral**, or **Vice Admiral** can use this.",
            ephemeral=True,
        )
        return

    if not db.get_player(uid):
        await interaction.response.send_message("Register first with `/register`.", ephemeral=True)
        return

    prisoners = db.get_prisoners(uid)
    if not prisoners:
        await interaction.response.send_message("You have no prisoners.", ephemeral=True)
        return

    oq, orr = game.get_position(uid)
    embed = discord.Embed(
        title=f"⛓️ Prisoners of {interaction.user.display_name}",
        color=MARINE_COLOR,
    )
    for p in prisoners:
        hp     = p["hp"] if p["hp"] is not None else 0
        max_hp = p["max_hp"] if p["max_hp"] is not None else 100
        embed.add_field(name=p["name"], value=f"HP: {hp}/{max_hp}", inline=False)

    embed.set_footer(text=f"Your position: q={oq}, r={orr}")
    await interaction.response.send_message(embed=embed, ephemeral=True)
