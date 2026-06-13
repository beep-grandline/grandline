# ═══════════════════════════════════════════════════════════════════════════════
#  doctor_commands.py  ·  /doctor bandage, heal — crew medical care
#  Add to bot.py:
#      from doctor_commands import doctor_group
#      bot.tree.add_command(doctor_group)
# ═══════════════════════════════════════════════════════════════════════════════

import discord
import db
from config import GUILD_ID

BANDAGE_FRACTION = 0.50   # +50% of max HP
DOCTOR_COLOR     = 0x4fb0c6


def _is_doctor(member: discord.Member) -> bool:
    return any(role.name.lower() == "doctor" for role in getattr(member, "roles", []))


doctor_group = discord.app_commands.Group(
    name="doctor",
    description="Treat your crewmates",
    guild_ids=[GUILD_ID],
)


async def _treat(interaction: discord.Interaction, target: discord.Member,
                 amount: int, verb: str):
    """Shared handler for bandage/heal. `amount` is HP to restore."""
    uid = str(interaction.user.id)
    if not db.get_player(uid):
        await interaction.response.send_message("Register first with `/register`.", ephemeral=True)
        return
    if not _is_doctor(interaction.user):
        await interaction.response.send_message("Only a **Doctor** can do that.", ephemeral=True)
        return

    tid = str(target.id)
    if not db.get_player(tid):
        await interaction.response.send_message(
            f"{target.display_name} isn't registered yet.", ephemeral=True
        )
        return

    hp, max_hp = db.get_player_hp(tid)
    if hp >= max_hp:
        await interaction.response.send_message(
            f"{target.display_name} is already at full HP.", ephemeral=True
        )
        return

    new_hp, max_hp, healed = db.heal_player(tid, amount)
    await interaction.response.send_message(
        f"{interaction.user.mention} {verb} {target.mention} ({new_hp}/{max_hp} HP)"
    )


@doctor_group.command(name="bandage", description="Patch a crewmate up for some HP")
@discord.app_commands.describe(target="Who to treat")
async def doctor_bandage(interaction: discord.Interaction, target: discord.Member):
    try:
        _, max_hp = db.get_player_hp(str(target.id))
        amount    = max(1, round(max_hp * BANDAGE_FRACTION))
        await _treat(interaction, target, amount, "bandages")
    except discord.NotFound:
        pass


@doctor_group.command(name="heal", description="Fully restore a crewmate's HP")
@discord.app_commands.describe(target="Who to treat")
async def doctor_heal(interaction: discord.Interaction, target: discord.Member):
    try:
        _, max_hp = db.get_player_hp(str(target.id))
        await _treat(interaction, target, max_hp, "fully heals")
    except discord.NotFound:
        pass
