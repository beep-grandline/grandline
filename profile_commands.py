# ═══════════════════════════════════════════════════════════════════════════════
#  profile_commands.py  ·  /profile set and /profile show
#  Add to bot.py:
#      from profile_commands import profile_group
#      bot.tree.add_command(profile_group)
#
#  Add to db.py migrations list:
#      "ALTER TABLE players ADD COLUMN char_name     TEXT",
#      "ALTER TABLE players ADD COLUMN fighting_style TEXT",
#      "ALTER TABLE players ADD COLUMN summary        TEXT",
# ═══════════════════════════════════════════════════════════════════════════════

import discord
import db
from config import GUILD_ID


# ── Modal ─────────────────────────────────────────────────────────────────────

class ProfileModal(discord.ui.Modal, title="Set Your Profile"):

    char_name = discord.ui.TextInput(
        label="Character Name",
        placeholder="What's your character's name?",
        max_length=32,
        required=True,
    )

    epithet = discord.ui.TextInput(
        label="Epithet",
        placeholder='e.g. Pirate King, Hawk-Eye, Dark King...',
        max_length=48,
        required=False,
    )

    fighting_style = discord.ui.TextInput(
        label="Fighting Style",
        placeholder="e.g. Santoryu, Black Leg Style, Rokushiki...",
        max_length=64,
        required=False,
    )

    summary = discord.ui.TextInput(
        label="Summary",
        style=discord.TextStyle.paragraph,
        placeholder="A short description of your character...",
        max_length=150,
        required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        db.set_profile(
            uid,
            char_name     = str(self.char_name).strip(),
            epithet       = str(self.epithet).strip() or None,
            fighting_style= str(self.fighting_style).strip() or None,
            summary       = str(self.summary).strip() or None,
        )

        embed = _profile_embed(interaction.user, db.get_player(uid))
        await interaction.response.send_message(
            "Profile updated!", embed=embed, ephemeral=True
        )


# ── Display helper ────────────────────────────────────────────────────────────

def _profile_embed(member: discord.Member, player_row) -> discord.Embed:
    char_name     = player_row["char_name"]     or member.display_name
    epithet       = player_row["epithet"]        if player_row["epithet"] else None
    fighting_style= player_row["fighting_style"]
    summary       = player_row["summary"]
    bounty        = player_row["bounty"]        or 0
    hp            = player_row["hp"]            or 100

    title = f'{char_name}  —  "{epithet}"' if epithet else char_name

    embed = discord.Embed(
        title=title,
        description=summary or "*No summary set.*",
        color=0x1a3f6b,
    )
    embed.set_thumbnail(url=member.display_avatar.url)

    if fighting_style:
        embed.add_field(name="Fighting Style", value=fighting_style, inline=True)

    embed.add_field(name="HP",     value=str(hp),        inline=True)
    embed.add_field(name="Bounty", value=f"฿{bounty:,}", inline=True)
    embed.set_footer(text=f"Player: {member.display_name}")
    return embed


# ── Profile command group ─────────────────────────────────────────────────────

profile_group = discord.app_commands.Group(
    name="profile",
    description="View and edit your character profile",
    guild_ids=[GUILD_ID],
)


@profile_group.command(name="set", description="Set your character profile")
async def profile_set(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    if not db.get_player(uid):
        await interaction.response.send_message(
            "Register first with `/register`.", ephemeral=True
        )
        return

    player = db.get_player(uid)
    modal  = ProfileModal()

    # pre-fill with existing values so the user only edits what they want
    if player["char_name"]:
        modal.char_name.default = player["char_name"]
    if player["epithet"]:
        modal.epithet.default = player["epithet"]
    if player["fighting_style"]:
        modal.fighting_style.default = player["fighting_style"]
    if player["summary"]:
        modal.summary.default = player["summary"]

    await interaction.response.send_modal(modal)


@profile_group.command(name="show", description="View a player's profile")
@discord.app_commands.describe(target="Player to look up (leave empty for your own)")
async def profile_show(interaction: discord.Interaction, target: discord.Member = None):
    member = target or interaction.user
    uid    = str(member.id)
    player = db.get_player(uid)

    if not player:
        name = "You are" if not target else f"{member.display_name} is"
        await interaction.response.send_message(
            f"{name} not registered yet.", ephemeral=True
        )
        return

    embed = _profile_embed(member, player)
    await interaction.response.send_message(embed=embed, ephemeral=True)
