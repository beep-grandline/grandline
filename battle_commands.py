# ═══════════════════════════════════════════════════════════════════════════════
#  battle_commands.py  ·  /challenge and /forfeit
#  Add to bot.py:
#      from battle_commands import challenge_cmd, forfeit_cmd
#      bot.tree.add_command(battle_cmd)
#      bot.tree.add_command(forfeit_cmd)
# ═══════════════════════════════════════════════════════════════════════════════

import discord
import db
import battle as battle_logic
from config import MY_GUILD
from fruits import get_fighter_types


# ── Embed builders ────────────────────────────────────────────────────────────

def _battle_embed(state, log=None):
    fa = state["fighters"]["a"]
    fb = state["fighters"]["b"]

    turn = state["turn"]
    embed = discord.Embed(
        title  = f"Turn {turn}" if turn > 0 else "Battle Start",
        color  = 0x1a3f6b,
    )
    embed.set_author(name=f"⚔  {fa['name']}  vs  {fb['name']}")

    # both HP bars in one field — no gap between them
    embed.add_field(
        name  = "\u200b",
        value = "\n".join(battle_logic.status_block(state)),
        inline= False,
    )

    if log:
        # strip the turn header line from the log since it's now the embed title
        lines   = [l for l in log if not l.startswith("**──")]
        log_str = "\n".join(lines)
        if len(log_str) > 1024:
            log_str = log_str[-1021:] + "..."
        if log_str.strip():
            embed.add_field(name="\u200b", value=log_str, inline=False)
    else:
        embed.description = "Battle started! Choose your action."

    embed.set_footer(text="Choose your action")
    return embed


def _finished_embed(state):
    fa = state["fighters"]["a"]
    fb = state["fighters"]["b"]

    winner = state.get("winner")
    if winner == "draw":
        title = "Draw!"
    elif winner in ("a", "b"):
        title = f"🏆  {state['fighters'][winner]['name']} wins!"
    else:
        title = "Battle Over"

    embed = discord.Embed(title=title, color=0x2d9e5f)
    embed.set_author(name=f"⚔  {fa['name']}  vs  {fb['name']}")

    embed.add_field(
        name  = "\u200b",
        value = "\n".join(battle_logic.status_block(state)),
        inline= False,
    )

    log = state.get("log", [])
    if log:
        lines   = [l for l in log if not l.startswith("**──")]
        log_str = "\n".join(lines)
        if len(log_str) > 1024:
            log_str = log_str[-1021:] + "..."
        if log_str.strip():
            embed.add_field(name="\u200b", value=log_str, inline=False)

    return embed


def _build_fighter_data(player_row, member: discord.Member):
    type1, type2 = get_fighter_types(player_row["fruit_id"] if player_row["fruit_id"] else None)
    return {
        "id":      str(member.id),
        "name":    member.display_name,
        "hp":      player_row["hp"]      or 100,
        "atk":     player_row["atk"]     or 10,
        "defense": player_row["defense"] or 10,
        "spd":     player_row["spd"]     or 10,
        "type1":   type1,
        "type2":   type2,
        "block":   player_row["block_name"],
        "dodge":   player_row["dodge_name"],
        "moves":   db.get_player_moves(str(member.id)),
    }


# ── Turn resolution ───────────────────────────────────────────────────────────

async def _resolve_and_update(interaction: discord.Interaction, channel_id: str):
    """
    Called when both players have pending actions.
    Resolves the turn, updates the battle message, cleans up if finished.
    """
    action_a, action_b = db.get_pending_actions(channel_id)
    if not action_a or not action_b:
        return  # already resolved by the other player's interaction

    state = db.get_battle_state(channel_id)
    if not state or state["status"] != "active":
        return

    state, log = battle_logic.resolve_turn(state, action_a, action_b)

    row     = db.get_battle(channel_id)
    channel = interaction.client.get_channel(int(channel_id))

    # delete the old message so the channel stays clean
    try:
        old_msg = await channel.fetch_message(int(row["message_id"]))
        await old_msg.delete()
    except Exception:
        pass

    fa = state["fighters"]["a"]
    fb = state["fighters"]["b"]

    if battle_logic.is_finished(state):
        embed = _finished_embed(state)
        await channel.send(
            content=f"<@{fa['id']}> <@{fb['id']}>",
            embed=embed,
        )
        db.delete_battle(channel_id)
    else:
        db.update_battle_state(channel_id, state)
        embed = _battle_embed(state, log)
        view  = BattleView(
            fighter_a_id=row["fighter_a_id"],
            fighter_b_id=row["fighter_b_id"],
            channel_id=channel_id,
        )
        new_msg = await channel.send(
            content=f"<@{fa['id']}> <@{fb['id']}>",
            embed=embed,
            view=view,
        )
        db.set_battle_message(channel_id, str(new_msg.id))


# ── Move select ───────────────────────────────────────────────────────────────

class MoveSelect(discord.ui.Select):
    def __init__(self, moves: list, channel_id: str, side: str):
        options = [
            discord.SelectOption(
                label=m["name"],
                description=m["attack_type"],
                value=m["name"],
            )
            for m in moves
        ]
        super().__init__(placeholder="Choose a move...", min_values=1, max_values=1, options=options)
        self.channel_id = channel_id
        self.side       = side

    async def callback(self, interaction: discord.Interaction):
        move_name   = self.values[0]
        both_ready  = db.set_pending_action(self.channel_id, self.side, ["attack", move_name])

        for item in self.view.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"You chose **{move_name}**. Waiting for your opponent...",
            view=self.view,
        )

        if both_ready:
            await _resolve_and_update(interaction, self.channel_id)


class MoveSelectView(discord.ui.View):
    def __init__(self, moves: list, channel_id: str, side: str):
        super().__init__(timeout=120)
        self.add_item(MoveSelect(moves, channel_id, side))


# ── Battle view ───────────────────────────────────────────────────────────────

class BattleView(discord.ui.View):
    def __init__(self, fighter_a_id: str, fighter_b_id: str, channel_id: str):
        super().__init__(timeout=None)
        self.fighter_a_id = fighter_a_id
        self.fighter_b_id = fighter_b_id
        self.channel_id   = channel_id

    def _side(self, uid: str):
        if uid == self.fighter_a_id: return "a"
        if uid == self.fighter_b_id: return "b"
        return None

    async def _guard(self, interaction: discord.Interaction):
        """Returns side string or sends an error and returns None."""
        side = self._side(str(interaction.user.id))
        if not side:
            await interaction.response.send_message(
                "You're not in this battle.", ephemeral=True
            )
        return side

    @discord.ui.button(label="Attack", style=discord.ButtonStyle.danger, row=0)
    async def attack(self, interaction: discord.Interaction, button: discord.ui.Button):
        side = await self._guard(interaction)
        if not side:
            return
        state = db.get_battle_state(self.channel_id)
        if not state:
            await interaction.response.send_message("Battle not found.", ephemeral=True)
            return
        moves = state["fighters"][side]["moves"]
        if not moves:
            await interaction.response.send_message("You have no moves!", ephemeral=True)
            return
        view = MoveSelectView(moves, self.channel_id, side)
        await interaction.response.send_message(
            "Choose your move:", view=view, ephemeral=True
        )

    @discord.ui.button(label="Block", style=discord.ButtonStyle.secondary, row=0)
    async def block(self, interaction: discord.Interaction, button: discord.ui.Button):
        side = await self._guard(interaction)
        if not side:
            return
        both_ready = db.set_pending_action(self.channel_id, side, ["block", None])
        await interaction.response.send_message(
            "Blocking this turn. Waiting for your opponent...", ephemeral=True
        )
        if both_ready:
            await _resolve_and_update(interaction, self.channel_id)

    @discord.ui.button(label="Dodge", style=discord.ButtonStyle.secondary, row=0)
    async def dodge(self, interaction: discord.Interaction, button: discord.ui.Button):
        side = await self._guard(interaction)
        if not side:
            return
        both_ready = db.set_pending_action(self.channel_id, side, ["dodge", None])
        await interaction.response.send_message(
            "Dodging this turn. Waiting for your opponent...", ephemeral=True
        )
        if both_ready:
            await _resolve_and_update(interaction, self.channel_id)

    @discord.ui.button(label="Escape", style=discord.ButtonStyle.secondary, row=0)
    async def escape(self, interaction: discord.Interaction, button: discord.ui.Button):
        side = await self._guard(interaction)
        if not side:
            return
        both_ready = db.set_pending_action(self.channel_id, side, ["escape", None])
        await interaction.response.send_message(
            "Attempting to escape. Waiting for your opponent...", ephemeral=True
        )
        if both_ready:
            await _resolve_and_update(interaction, self.channel_id)

    @discord.ui.button(label="Charge ⚡", style=discord.ButtonStyle.primary, row=1)
    async def charge(self, interaction: discord.Interaction, button: discord.ui.Button):
        side = await self._guard(interaction)
        if not side:
            return
        state = db.get_battle_state(self.channel_id)
        if state and state["fighters"][side].get("charging"):
            await interaction.response.send_message(
                "You're already charging! Attack this turn to release it.", ephemeral=True
            )
            return
        both_ready = db.set_pending_action(self.channel_id, side, ["charge", None])
        await interaction.response.send_message(
            "Charging up — your next attack will hit twice as hard!", ephemeral=True
        )
        if both_ready:
            await _resolve_and_update(interaction, self.channel_id)


# ── Challenge view ────────────────────────────────────────────────────────────

class ChallengeView(discord.ui.View):
    def __init__(self, challenger: discord.Member, target: discord.Member):
        super().__init__(timeout=120)
        self.challenger = challenger
        self.target     = target
        self.message    = None   # set after sending so on_timeout can edit it

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(
                    content=f"~~{self.target.mention}, {self.challenger.display_name} has challenged you to a fight ⚔️~~\n*Challenge expired.*",
                    view=self,
                )
            except Exception:
                pass

    async def _start_battle(self, interaction: discord.Interaction):
        cid = str(self.challenger.id)
        tid = str(self.target.id)

        p_a = db.get_player(cid)
        p_b = db.get_player(tid)

        if not p_a or not p_b:
            await interaction.response.edit_message(
                content="One or both players are not registered.", embed=None, view=None
            )
            return

        for pid, mention in [(cid, self.challenger.mention), (tid, self.target.mention)]:
            if not db.get_player_moves(pid):
                await interaction.response.edit_message(
                    content=f"{mention} has no moves in their kit yet — use `/kit add` first.",
                    embed=None, view=None,
                )
                return

        for pid, mention in [(cid, self.challenger.mention), (tid, self.target.mention)]:
            if db.get_battle_by_player(pid):
                await interaction.response.edit_message(
                    content=f"{mention} is already in a battle.",
                    embed=None, view=None,
                )
                return

        a_data    = _build_fighter_data(p_a, self.challenger)
        b_data    = _build_fighter_data(p_b, self.target)
        state     = battle_logic.create_battle(a_data, b_data)
        channel_id = str(interaction.channel_id)

        db.create_battle(channel_id, cid, tid, state)

        embed = _battle_embed(state)
        view  = BattleView(fighter_a_id=cid, fighter_b_id=tid, channel_id=channel_id)

        await interaction.response.edit_message(
            content=f"{self.challenger.mention}  {self.target.mention}",
            embed=embed,
            view=view,
        )
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
            embed=None, view=self,
        )

    @discord.ui.button(label="Withdraw", style=discord.ButtonStyle.secondary)
    async def withdraw(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.challenger.id:
            await interaction.response.send_message(
                "Only the challenger can withdraw.", ephemeral=True
            )
            return
        self.stop()
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=f"{self.challenger.mention} withdrew the challenge.",
            embed=None, view=self,
        )


# ── /challenge ────────────────────────────────────────────────────────────────

@discord.app_commands.command(
    name="battle",
    description="Challenge another player to a battle",
)
@discord.app_commands.describe(target="The player you want to fight")
@discord.app_commands.guilds(MY_GUILD)
async def battle_cmd(interaction: discord.Interaction, target: discord.Member):
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

    view = ChallengeView(challenger=interaction.user, target=target)
    await interaction.response.send_message(
        content=f"{target.mention}, {interaction.user.display_name} has challenged you to a fight ⚔️",
        view=view,
    )
    view.message = await interaction.original_response()


# ── /forfeit ──────────────────────────────────────────────────────────────────

@discord.app_commands.command(
    name="forfeit",
    description="Forfeit your current battle",
)
@discord.app_commands.guilds(MY_GUILD)
async def forfeit_cmd(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    row = db.get_battle_by_player(uid)

    if not row:
        await interaction.response.send_message("You're not in a battle.", ephemeral=True)
        return

    state     = db.get_battle_state(row["channel_id"])
    fa        = state["fighters"]["a"]
    fb        = state["fighters"]["b"]
    forfeiter = fa if fa["id"] == uid else fb
    winner    = fb if fa["id"] == uid else fa

    try:
        channel = interaction.client.get_channel(int(row["channel_id"]))
        old_msg = await channel.fetch_message(int(row["message_id"]))
        await old_msg.delete()
        state["status"] = "finished"
        state["winner"] = "b" if fa["id"] == uid else "a"
        embed = _finished_embed(state)
        await channel.send(embed=embed)
    except Exception:
        pass

    db.delete_battle(row["channel_id"])
    await interaction.response.send_message(
        f"**{forfeiter['name']}** forfeited. 🏆 **{winner['name']}** wins!"
    )
