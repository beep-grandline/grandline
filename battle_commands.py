# ═══════════════════════════════════════════════════════════════════════════════
#  battle_commands.py  ·  /challenge and /forfeit
#  Add to bot.py:
#      from battle_commands import challenge_cmd, forfeit_cmd
#      bot.tree.add_command(challenge_cmd)
#      bot.tree.add_command(forfeit_cmd)
# ═══════════════════════════════════════════════════════════════════════════════

import discord
import db
import battle as battle_logic
from config import MY_GUILD


def _build_fighter_data(player_row, member: discord.Member):
    """
    Assemble a fighter data dict from a DB player row.
    Uses DB stat columns (atk, defense, spd, type1, type2, block_name, dodge_name)
    with sane defaults for players whose stats haven't been set by a GM yet.
    """
    return {
        "id":      str(member.id),
        "name":    member.display_name,
        "hp":      player_row["hp"]      if player_row["hp"]      else 100,
        "atk":     player_row["atk"]     if player_row["atk"]     else 10,
        "defense": player_row["defense"] if player_row["defense"] else 10,
        "spd":     player_row["spd"]     if player_row["spd"]     else 10,
        "type1":   player_row["type1"]   if player_row["type1"]   else "Normal",
        "type2":   player_row["type2"]   if player_row["type2"]   else "none",
        "block":   player_row["block_name"],
        "dodge":   player_row["dodge_name"],
        "moves":   db.get_player_moves(str(member.id)),
    }


def _battle_embed(state, title="⚔  Battle", color=0x1a3f6b):
    """Build the main battle status embed from a state dict."""
    embed = discord.Embed(title=title, color=color)
    for line in battle_logic.status_block(state):
        embed.add_field(name="\u200b", value=line, inline=False)
    embed.set_footer(text=f"Turn {state['turn']}")
    return embed


# ── Challenge view ────────────────────────────────────────────────────────────

class ChallengeView(discord.ui.View):
    def __init__(self, challenger: discord.Member, target: discord.Member):
        super().__init__(timeout=120)
        self.challenger = challenger
        self.target     = target

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True

    async def _start_battle(self, interaction: discord.Interaction):
        """Validate both players and create the battle in DB."""
        cid = str(self.challenger.id)
        tid = str(self.target.id)

        p_a = db.get_player(cid)
        p_b = db.get_player(tid)

        if not p_a or not p_b:
            await interaction.response.edit_message(
                content="One or both players are not registered.", embed=None, view=None
            )
            return

        if not db.get_player_moves(cid):
            await interaction.response.edit_message(
                content=f"{self.challenger.mention} has no moves in their kit yet — use `/kit add` first.",
                embed=None, view=None,
            )
            return

        if not db.get_player_moves(tid):
            await interaction.response.edit_message(
                content=f"{self.target.mention} has no moves in their kit yet.",
                embed=None, view=None,
            )
            return

        if db.get_battle_by_player(cid):
            await interaction.response.edit_message(
                content=f"{self.challenger.mention} is already in a battle.",
                embed=None, view=None,
            )
            return

        if db.get_battle_by_player(tid):
            await interaction.response.edit_message(
                content=f"{self.target.mention} is already in a battle.",
                embed=None, view=None,
            )
            return

        a_data = _build_fighter_data(p_a, self.challenger)
        b_data = _build_fighter_data(p_b, self.target)
        state  = battle_logic.create_battle(a_data, b_data)

        channel_id = str(interaction.channel_id)
        db.create_battle(channel_id, cid, tid, state)

        embed = _battle_embed(state, title=f"⚔  {self.challenger.display_name}  vs  {self.target.display_name}")
        embed.description = "Battle started! Both players: choose your action for Turn 1."

        await interaction.response.edit_message(
            content=f"{self.challenger.mention}  {self.target.mention}",
            embed=embed,
            view=None,
        )
        # store the message ID so we can edit it each turn
        msg = await interaction.original_response()
        db.set_battle_message(channel_id, str(msg.id))

    @discord.ui.button(label="Accept ⚔", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message(
                "This challenge isn't for you.", ephemeral=True
            )
            return
        self.stop()
        for child in self.children:
            child.disabled = True
        await self._start_battle(interaction)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message(
                "This challenge isn't for you.", ephemeral=True
            )
            return
        self.stop()
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=f"{self.target.mention} declined the challenge.",
            embed=None,
            view=self,
        )


# ── /challenge ────────────────────────────────────────────────────────────────

@discord.app_commands.command(
    name="challenge",
    description="Challenge another player to a battle",
)
@discord.app_commands.describe(target="The player you want to fight")
@discord.app_commands.guilds(MY_GUILD)
async def challenge_cmd(interaction: discord.Interaction, target: discord.Member):
    uid = str(interaction.user.id)

    if target.id == interaction.user.id:
        await interaction.response.send_message("You can't challenge yourself.", ephemeral=True)
        return

    if target.bot:
        await interaction.response.send_message("You can't challenge a bot.", ephemeral=True)
        return

    if not db.get_player(uid):
        await interaction.response.send_message("Register first with `/register`.", ephemeral=True)
        return

    if not db.get_player(str(target.id)):
        await interaction.response.send_message(
            f"{target.display_name} isn't registered yet.", ephemeral=True
        )
        return

    if db.get_battle_by_player(uid):
        await interaction.response.send_message(
            "You're already in a battle. Use `/forfeit` to end it first.", ephemeral=True
        )
        return

    if db.get_battle_by_player(str(target.id)):
        await interaction.response.send_message(
            f"{target.display_name} is already in a battle.", ephemeral=True
        )
        return

    embed = discord.Embed(
        title="⚔  Challenge Issued",
        description=f"{interaction.user.mention} wants to fight {target.mention}!",
        color=0x1a3f6b,
    )
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.set_footer(text="This challenge expires in 2 minutes.")

    view = ChallengeView(challenger=interaction.user, target=target)
    await interaction.response.send_message(
        content=f"{target.mention} — you've been challenged!",
        embed=embed,
        view=view,
    )


# ── /forfeit ──────────────────────────────────────────────────────────────────

@discord.app_commands.command(
    name="forfeit",
    description="Forfeit your current battle",
)
@discord.app_commands.guilds(MY_GUILD)
async def forfeit_cmd(interaction: discord.Interaction):
    uid     = str(interaction.user.id)
    channel = str(interaction.channel_id)
    row     = db.get_battle_by_player(uid)

    if not row:
        await interaction.response.send_message(
            "You're not in a battle.", ephemeral=True
        )
        return

    state     = db.get_battle_state(row["channel_id"])
    fa        = state["fighters"]["a"]
    fb        = state["fighters"]["b"]
    forfeiter = fa if fa["id"] == uid else fb
    winner    = fb if fa["id"] == uid else fa

    db.delete_battle(row["channel_id"])

    await interaction.response.send_message(
        f"**{forfeiter['name']}** has forfeited. "
        f"🏆 **{winner['name']}** wins by forfeit!"
    )
