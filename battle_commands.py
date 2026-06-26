# ═══════════════════════════════════════════════════════════════════════════════
#  battle_commands.py  ·  /challenge and /forfeit
#  Add to bot.py:
#      from battle_commands import challenge_cmd, forfeit_cmd
#      bot.tree.add_command(battle_cmd)
#      bot.tree.add_command(forfeit_cmd)
# ═══════════════════════════════════════════════════════════════════════════════

import uuid
import discord
import db
import game
import battle as battle_logic
from config import MY_GUILD
from fruits import get_fighter_types, get_fruit_by_id
from npcs import get_npc_by_id, get_npcs_at, build_npc_fighter, npc_pick_action


# Fruit categories that can transform (cat column in fruits.csv)
ZOAN_CATS = {"2", "4", "5"}  # 2 = Zoan, 4 = Mythical Zoan, 5 = Ancient Zoan


def _is_zoan(fruit_id: str) -> bool:
    if not fruit_id:
        return False
    row = get_fruit_by_id(fruit_id)
    if not row:
        return False
    return str(row.get("cat", "")).strip() in ZOAN_CATS


def _extract_animal(fruit_id: str) -> str:
    """Pull the animal name from a fruit's English name.

    If the name has a colon, take the text after it ("Dog-Dog Fruit Model:
    Jackal" -> "jackal"); otherwise take the text before the first dash
    ("Otter-Otter Fruit" -> "otter")."""
    if not fruit_id:
        return ""
    row = get_fruit_by_id(fruit_id)
    eng = (row.get("eng") or "") if row else ""
    if ":" in eng:
        animal = eng.split(":", 1)[1].strip()
    else:
        animal = eng.split("-")[0].strip()
    return animal.lower()


# Transformation states, in order. Label shown to players for each.
_TRANSFORM_LABELS = {
    "base":   "Base",
    "hybrid": "Hybrid Zoan",
    "full":   "Full Zoan",
}



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

    # build the whole body in the description so there are no blank
    # field-name gaps between the HP bars and the log
    parts = ["\n".join(battle_logic.status_block(state))]
    if log:
        lines   = [l for l in log if not l.startswith("**──")]
        log_str = "\n".join(lines).strip()
        if log_str:
            parts.append(log_str)
    else:
        parts.append("Battle started! Choose your action.")
    desc = "\n".join(parts)
    if len(desc) > 4096:
        desc = desc[:4093] + "..."
    embed.description = desc

    embed.set_footer(text="Choose your action")
    return embed


def _finished_embed(state):
    fa = state["fighters"]["a"]
    fb = state["fighters"]["b"]

    end_reason = state.get("end_reason", "hp")
    winner     = state.get("winner")

    if end_reason == "teleport":
        target_name = state.get("teleport_target", "Someone")
        island      = state.get("teleport_island", "somewhere far away")
        title       = f"Battle Over"
        desc        = f"*{target_name} was sent flying to {island}...*"
    elif end_reason == "escape":
        title = "Battle Over"
        desc  = "*One fighter fled the scene.*"
    elif winner == "draw":
        title = "Draw!"
        desc  = None
    elif winner in ("a", "b"):
        title = f"🏆  {state['fighters'][winner]['name']} wins!"
        desc  = None
    else:
        title = "Battle Over"
        desc  = None

    embed = discord.Embed(title=title, color=0x2d9e5f)
    embed.set_author(name=f"⚔  {fa['name']}  vs  {fb['name']}")

    # build the whole body in the description so there are no blank
    # field-name gaps between the HP bars and the log
    parts = []
    if desc:
        parts.append(desc)
    parts.append("\n".join(battle_logic.status_block(state)))
    log = state.get("log", [])
    if log:
        # the win is shown in the title — never let a stray "wins!" line in the
        # log repeat it, and drop the turn header
        lines   = [l for l in log
                   if not l.startswith("**──") and "wins!" not in l]
        log_str = "\n".join(lines).strip()
        if log_str:
            parts.append(log_str)

    body = "\n".join(parts)
    if len(body) > 4096:
        body = body[-4093:] + "..."
    embed.description = body
    return embed


def _build_fighter_data(player_row, member: discord.Member):
    type1, type2 = get_fighter_types(player_row["fruit_id"] if player_row["fruit_id"] else None)
    moves = db.get_player_moves(str(member.id))

    # inject special moves granted by fruit
    fruit_id = (player_row["fruit_id"] or "").strip().lower()
    for special_key in battle_logic.FRUIT_SPECIALS.get(fruit_id, []):
        special_move = battle_logic.SPECIAL_MOVES.get(special_key)
        if special_move and not any(m["name"] == special_move["name"] for m in moves):
            moves = list(moves) + [special_move]

    current_hp = player_row["hp"] if player_row["hp"] is not None else 100
    max_hp     = player_row["max_hp"] if player_row["max_hp"] is not None else current_hp

    atk = player_row["atk"]     or 10
    dfn = player_row["defense"] or 10
    spd = player_row["spd"]     or 10

    # hearty meal — +10% stats for one battle, consumed on use
    if player_row["hearty_buff"]:
        atk = round(atk * game.HEARTY_BUFF_MULT)
        dfn = round(dfn * game.HEARTY_BUFF_MULT)
        spd = round(spd * game.HEARTY_BUFF_MULT)
        db.set_hearty_buff(str(member.id), 0)

    haki = any(r.name.lower() == "haki" for r in getattr(member, "roles", []))

    return {
        "id":      str(member.id),
        "name":    member.display_name,
        "hp":      current_hp,
        "max_hp":  max_hp,
        "atk":     atk,
        "defense": dfn,
        "spd":     spd,
        "type1":   type1,
        "type2":   type2,
        "block":   player_row["block_name"],
        "dodge":   player_row["dodge_name"],
        "moves":   moves,
        "haki":    haki,
        "fruit_id": fruit_id,
        "animal":   _extract_animal(fruit_id),
        "is_zoan":  _is_zoan(fruit_id),
    }


# ── Turn resolution ───────────────────────────────────────────────────────────

async def _resolve_and_update(interaction: discord.Interaction, battle_id: str):
    """
    Called when both players have pending actions.
    Resolves the turn, updates the battle message, cleans up if finished.
    """
    action_a, action_b = db.get_pending_actions(battle_id)
    if not action_a or not action_b:
        return  # already resolved by the other player's interaction

    state = db.get_battle_state(battle_id)
    if not state or state["status"] != "active":
        return

    state, log = battle_logic.resolve_turn(state, action_a, action_b)

    # apply any post-turn position effects (e.g. paw teleport)
    for side_key in ("a", "b"):
        f   = state["fighters"][side_key]
        dst = f.pop("teleport_to", None)
        if dst and not str(f["id"]).startswith("npc:"):
            db.update_player_position(str(f["id"]), dst["q"], dst["r"])
            db.set_following(str(f["id"]), None)
            # teleport ends the battle
            state["status"]          = "finished"
            state["winner"]          = "draw"
            state["end_reason"]      = "teleport"
            state["teleport_target"] = f["name"]
            state["teleport_target_id"] = str(f["id"])
            state["teleport_island"] = dst.get("island", "somewhere far away")
            state["teleport_by"]     = str(dst.get("by", ""))

    row     = db.get_battle(battle_id)
    channel = interaction.client.get_channel(int(row["channel_id"]))

    # delete the old message so the channel stays clean
    try:
        old_msg = await channel.fetch_message(int(row["message_id"]))
        await old_msg.delete()
    except Exception:
        pass

    fa = state["fighters"]["a"]
    fb = state["fighters"]["b"]

    # only mention real players
    def _mention(fid):
        return f"<@{fid}>" if not str(fid).startswith("npc:") else ""

    pings = " ".join(filter(None, [_mention(fa["id"]), _mention(fb["id"])]))

    # persist HP for real players after EVERY turn, so an interrupted battle
    # (restart, stale cleanup, dropped turn) still reflects damage taken
    for side_key in ("a", "b"):
        f = state["fighters"][side_key]
        fid = str(f["id"])
        if not fid.startswith("npc:"):
            db.update_player_hp(fid, max(0, f["hp"]))

    if battle_logic.is_finished(state):
        # If a marine officer lost, release all their prisoners to the winner's position
        winner_key = state.get("winner")
        if winner_key in ("a", "b"):
            loser_key  = "b" if winner_key == "a" else "a"
            loser_id   = str(state["fighters"][loser_key]["id"])
            winner_id  = str(state["fighters"][winner_key]["id"])
            if not loser_id.startswith("npc:") and db.get_prisoners(loser_id):
                wq, wr = game.get_position(winner_id) if not winner_id.startswith("npc:") else (0, 0)
                db.release_all_prisoners_of(loser_id, wq, wr)

        # send the result message, but never let a send failure (e.g. channel
        # not in cache) keep the finished battle row alive in the DB
        try:
            if (state.get("end_reason") == "teleport"
                    and state.get("teleport_by", "").lower() == "npc:kuma"):
                from urls import KUMA_TELEPORT_IMAGE
                victim_id = str(state.get("teleport_target_id", ""))
                mention   = f"<@{victim_id}>" if victim_id and not victim_id.startswith("npc:") else state.get("teleport_target", "Someone")
                embed = discord.Embed(
                    description=f"{mention} was sent flying far away...",
                    color=0x1a2744,
                )
                embed.set_image(url=KUMA_TELEPORT_IMAGE)
                await channel.send(embed=embed)
            else:
                embed = _finished_embed(state)
                await channel.send(content=pings or None, embed=embed)
        finally:
            db.delete_battle(battle_id)
    else:
        db.update_battle_state(battle_id, state)

        # kuma paw warning — replace normal battle embed with vacation prompt + buttons
        kuma_warn = next(
            (state["fighters"][s] for s in ("a", "b")
             if state["fighters"][s].get("paw_incoming")
             and state["fighters"][s].get("paw_warning_by", "").lower() == "npc:kuma"),
            None
        )

        view = BattleView(
            fighter_a_id=row["fighter_a_id"],
            fighter_b_id=row["fighter_b_id"],
            battle_id=battle_id,
            channel_id=row["channel_id"],
        )

        if kuma_warn:
            from urls import KUMA_TELEPORT_WARN
            victim_id = str(kuma_warn["id"])
            mention   = f"<@{victim_id}>" if not victim_id.startswith("npc:") else kuma_warn["name"]
            warn_embed = discord.Embed(
                description='*"If you could take a vacation, where would you go?"*',
                color=0x1a2744,
            )
            warn_embed.set_image(url=KUMA_TELEPORT_WARN)
            new_msg = await channel.send(content=mention, embed=warn_embed, view=view)
        else:
            embed   = _battle_embed(state, log)
            new_msg = await channel.send(content=pings or None, embed=embed, view=view)

        db.set_battle_message(battle_id, str(new_msg.id))


# ── Move select ───────────────────────────────────────────────────────────────

class MoveSelect(discord.ui.Select):
    def __init__(self, moves: list, battle_id: str, channel_id: str,
                 side: str, fighter_a_id: str, fighter_b_id: str):
        options = [
            discord.SelectOption(
                label=m["name"],
                description=m["attack_type"],
                value=m["name"],
            )
            for m in moves
        ]
        super().__init__(placeholder="Choose a move...", min_values=1, max_values=1, options=options)
        self.battle_id     = battle_id
        self.channel_id    = channel_id
        self.side          = side
        self.fighter_a_id  = fighter_a_id
        self.fighter_b_id  = fighter_b_id

    async def callback(self, interaction: discord.Interaction):
        move_name = self.values[0]
        for item in self.view.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"You chose **{move_name}**." + (
                "" if self.fighter_b_id.startswith("npc:") else " Waiting for your opponent..."
            ),
            view=self.view,
        )

        # reuse BattleView._submit_action logic inline
        both_ready = db.set_pending_action(self.battle_id, self.side, ["attack", move_name])
        if not both_ready:
            opp_id = self.fighter_b_id if self.side == "a" else self.fighter_a_id
            if str(opp_id).startswith("npc:"):
                npc_id     = str(opp_id)[4:]
                state      = db.get_battle_state(self.battle_id)
                npc_side   = "b" if self.side == "a" else "a"
                npc_action = npc_pick_action(state["fighters"][npc_side])
                both_ready = db.set_pending_action(self.battle_id, npc_side, npc_action)

        if both_ready:
            await _resolve_and_update(interaction, self.battle_id)


class MoveSelectView(discord.ui.View):
    def __init__(self, moves: list, battle_id: str, channel_id: str,
                 side: str, fighter_a_id: str = "", fighter_b_id: str = ""):
        super().__init__(timeout=120)
        self.add_item(MoveSelect(moves, battle_id, channel_id, side, fighter_a_id, fighter_b_id))


# ── Transform select (Zoan special) ───────────────────────────────────────────

class TransformSelect(discord.ui.Select):
    def __init__(self, battle_view, side: str, current: str):
        # show every transformation state except the one we're already in
        options = [
            discord.SelectOption(label=f"Transform: {label}", value=key)
            for key, label in _TRANSFORM_LABELS.items()
            if key != current
        ]
        super().__init__(placeholder="Choose a form...", min_values=1, max_values=1, options=options)
        self.battle_view = battle_view
        self.side        = side

    async def callback(self, interaction: discord.Interaction):
        target = self.values[0]
        for item in self.view.children:
            item.disabled = True
        bv = self.battle_view
        waiting = "" if bv.fighter_b_id.startswith("npc:") else " Waiting for your opponent..."
        await interaction.response.edit_message(
            content=f"Transforming into **{_TRANSFORM_LABELS[target]}**." + waiting,
            view=self.view,
        )
        # transforming costs a turn — submit it like any other action
        await bv._submit_action(interaction, self.side, ["transform", target])


class TransformSelectView(discord.ui.View):
    def __init__(self, battle_view, side: str, current: str):
        super().__init__(timeout=120)
        self.add_item(TransformSelect(battle_view, side, current))


# ── Battle view ───────────────────────────────────────────────────────────────

class BattleView(discord.ui.View):
    def __init__(self, fighter_a_id: str, fighter_b_id: str,
                 battle_id: str, channel_id: str):
        super().__init__(timeout=300)
        self.fighter_a_id = fighter_a_id
        self.fighter_b_id = fighter_b_id
        self.battle_id    = battle_id
        self.channel_id   = channel_id

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            state = db.get_battle_state(self.battle_id)
            if state:
                fa = state["fighters"]["a"]
                fb = state["fighters"]["b"]
                embed = discord.Embed(title="⏱ Battle timed out", color=0x888888)
                embed.set_author(name=f"⚔  {fa['name']}  vs  {fb['name']}")
                # restore both players' HP to what it was at timeout
                for side_key in ("a", "b"):
                    f = state["fighters"][side_key]
                    if not str(f["id"]).startswith("npc:"):
                        db.update_player_hp(str(f["id"]), max(0, f["hp"]))
            else:
                embed = discord.Embed(title="⏱ Battle timed out", color=0x888888)

            battle_row = db.get_battle(self.battle_id)
            msg_id     = battle_row["message_id"] if battle_row else None
            db.delete_battle(self.battle_id)

            channel = bot.get_channel(int(self.channel_id))
            if channel:
                if msg_id:
                    try:
                        msg = await channel.fetch_message(int(msg_id))
                        await msg.edit(embed=embed, view=self)
                        return
                    except Exception:
                        pass
                await channel.send(embed=embed)
        except Exception:
            pass

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

    async def _submit_action(self, interaction: discord.Interaction, side: str, action: list):
        """
        Stores action for this side. If opponent is an NPC, auto-generates
        their action immediately and resolves the turn.
        """
        both_ready = db.set_pending_action(self.battle_id, side, action)

        if not both_ready:
            opp_id = self.fighter_b_id if side == "a" else self.fighter_a_id
            if str(opp_id).startswith("npc:"):
                npc_id     = str(opp_id)[4:]
                npc_row    = get_npc_by_id(npc_id)
                state      = db.get_battle_state(self.battle_id)
                npc_side   = "b" if side == "a" else "a"
                npc_action = npc_pick_action(state["fighters"][npc_side])
                both_ready = db.set_pending_action(self.battle_id, npc_side, npc_action)

        if both_ready:
            await _resolve_and_update(interaction, self.battle_id)

    @discord.ui.button(label="Attack", style=discord.ButtonStyle.danger, row=0)
    async def attack(self, interaction: discord.Interaction, button: discord.ui.Button):
        side = await self._guard(interaction)
        if not side:
            return
        state = db.get_battle_state(self.battle_id)
        if not state:
            await interaction.response.send_message("Battle not found.", ephemeral=True)
            return
        moves = state["fighters"][side]["moves"]
        if not moves:
            await interaction.response.send_message("You have no moves!", ephemeral=True)
            return
        view = MoveSelectView(moves, self.battle_id, self.channel_id, side, self.fighter_a_id, self.fighter_b_id)
        await interaction.response.send_message(
            "Choose your move:", view=view, ephemeral=True
        )

    @discord.ui.button(label="Block", style=discord.ButtonStyle.secondary, row=0)
    async def block(self, interaction: discord.Interaction, button: discord.ui.Button):
        side = await self._guard(interaction)
        if not side:
            return
        await interaction.response.send_message(
            "Blocking this turn." + ("" if self.fighter_b_id.startswith("npc:") else " Waiting for your opponent..."),
            ephemeral=True
        )
        await self._submit_action(interaction, side, ["block", None])

    @discord.ui.button(label="Dodge", style=discord.ButtonStyle.secondary, row=0)
    async def dodge(self, interaction: discord.Interaction, button: discord.ui.Button):
        side = await self._guard(interaction)
        if not side:
            return
        await interaction.response.send_message(
            "Dodging this turn." + ("" if self.fighter_b_id.startswith("npc:") else " Waiting for your opponent..."),
            ephemeral=True
        )
        await self._submit_action(interaction, side, ["dodge", None])

    @discord.ui.button(label="Escape", style=discord.ButtonStyle.secondary, row=0)
    async def escape(self, interaction: discord.Interaction, button: discord.ui.Button):
        side = await self._guard(interaction)
        if not side:
            return
        await interaction.response.send_message(
            "Attempting to escape." + ("" if self.fighter_b_id.startswith("npc:") else " Waiting for your opponent..."),
            ephemeral=True
        )
        await self._submit_action(interaction, side, ["escape", None])

    @discord.ui.button(label="Charge ⚡", style=discord.ButtonStyle.primary, row=1)
    async def charge(self, interaction: discord.Interaction, button: discord.ui.Button):
        side = await self._guard(interaction)
        if not side:
            return
        state = db.get_battle_state(self.battle_id)
        if state and state["fighters"][side].get("charging"):
            await interaction.response.send_message(
                "You're already charging! Attack this turn to release it.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "Charging up — your next attack will hit twice as hard!", ephemeral=True
        )
        await self._submit_action(interaction, side, ["charge", None])

    @discord.ui.button(label="Special", style=discord.ButtonStyle.primary, row=1)
    async def special(self, interaction: discord.Interaction, button: discord.ui.Button):
        side = await self._guard(interaction)
        if not side:
            return
        state = db.get_battle_state(self.battle_id)
        if not state:
            await interaction.response.send_message("Battle not found.", ephemeral=True)
            return
        fighter = state["fighters"][side]
        if not _is_zoan(fighter.get("fruit_id")):
            await interaction.response.send_message(
                "You have no special abilities.", ephemeral=True
            )
            return
        current = fighter.get("transform", "base")
        view    = TransformSelectView(self, side, current)
        await interaction.response.send_message(
            f"Current form: **{_TRANSFORM_LABELS.get(current, 'Base')}**. Choose a transformation:",
            view=view, ephemeral=True,
        )


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

        for p, mention in [(p_a, self.challenger.mention), (p_b, self.target.mention)]:
            if p["captured_by"]:
                await interaction.response.edit_message(
                    content=f"{mention} is under arrest and cannot fight.",
                    embed=None, view=None,
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

        a_data     = _build_fighter_data(p_a, self.challenger)
        b_data     = _build_fighter_data(p_b, self.target)
        state      = battle_logic.create_battle(a_data, b_data)
        channel_id = str(interaction.channel_id)
        battle_id  = str(uuid.uuid4())

        db.create_battle(battle_id, channel_id, cid, tid, state)

        embed = _battle_embed(state)
        view  = BattleView(fighter_a_id=cid, fighter_b_id=tid,
                           battle_id=battle_id, channel_id=channel_id)

        try:
            await interaction.response.edit_message(
                content=f"{self.challenger.mention}  {self.target.mention}",
                embed=embed,
                view=view,
            )
            msg = await interaction.original_response()
            db.set_battle_message(battle_id, str(msg.id))
        except Exception:
            db.delete_battle(battle_id)
            raise

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


# ── /battle ───────────────────────────────────────────────────────────────────

@discord.app_commands.command(
    name="battle",
    description="Challenge another player to a fight",
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
    p_self = db.get_player(uid)
    if not p_self:
        await interaction.response.send_message("Register first — pick your allegiance from the role picker.", ephemeral=True)
        return
    if p_self["captured_by"]:
        await interaction.response.send_message(
            "You're under arrest and cannot start a battle.", ephemeral=True
        )
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


# ── /engage ───────────────────────────────────────────────────────────────────

async def _engage_autocomplete(interaction: discord.Interaction, current: str):
    try:
        uid    = str(interaction.user.id)
        player = db.get_player(uid)
        if not player:
            return []
        q, r = game.get_position(uid)
        choices = []
        for npc in get_npcs_at(q, r):
            name = (npc.get("name") or "").strip()
            if not name:
                continue
            if current.lower() not in name.lower():
                continue
            choices.append(discord.app_commands.Choice(
                name=name[:100],
                value=f"npc:{npc['id']}"[:100],
            ))
        return choices[:25]
    except discord.NotFound:
        return []
    except Exception:
        return []


@discord.app_commands.command(
    name="engage",
    description="Fight an NPC on your current tile",
)
@discord.app_commands.describe(target="NPC to fight")
@discord.app_commands.autocomplete(target=_engage_autocomplete)
@discord.app_commands.guilds(MY_GUILD)
async def engage_cmd(interaction: discord.Interaction, target: str):
    uid    = str(interaction.user.id)
    player = db.get_player(uid)

    if not player:
        await interaction.response.send_message("Register first — pick your allegiance from the role picker.", ephemeral=True)
        return
    if db.get_battle_by_player(uid):
        await interaction.response.send_message(
            "You're already in a battle. Use `/forfeit` to end it first.", ephemeral=True
        )
        return

    if not target.startswith("npc:"):
        await interaction.response.send_message("Select an NPC from the list.", ephemeral=True)
        return

    npc_id  = target[4:]
    npc_row = get_npc_by_id(npc_id)
    if not npc_row:
        await interaction.response.send_message("NPC not found.", ephemeral=True)
        return

    if not db.get_player_moves(uid):
        await interaction.response.send_message(
            "You have no moves in your kit yet — use `/kit add` first.", ephemeral=True
        )
        return

    a_data     = _build_fighter_data(player, interaction.user)
    b_data     = build_npc_fighter(npc_row)
    state      = battle_logic.create_battle(a_data, b_data)
    channel_id = str(interaction.channel_id)
    battle_id  = str(uuid.uuid4())

    db.create_battle(battle_id, channel_id, uid, f"npc:{npc_id}", state)

    embed   = _battle_embed(state)
    view    = BattleView(fighter_a_id=uid, fighter_b_id=f"npc:{npc_id}",
                         battle_id=battle_id, channel_id=channel_id)
    try:
        await interaction.response.send_message(
            content=f"<@{uid}>",
            embed=embed,
            view=view,
        )
        msg = await interaction.original_response()
        db.set_battle_message(battle_id, str(msg.id))
    except discord.NotFound:
        # interaction token expired (bot lagged past the 3s window) —
        # post the battle straight to the channel instead
        try:
            msg = await interaction.channel.send(
                content=f"<@{uid}>", embed=embed, view=view
            )
            db.set_battle_message(battle_id, str(msg.id))
        except Exception:
            db.delete_battle(battle_id)
            raise
    except Exception:
        # message never reached the channel — don't leave an orphaned battle
        db.delete_battle(battle_id)
        raise


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

    state = db.get_battle_state(row["battle_id"]) if row.get("battle_id") else None
    if not state:
        # corrupt or legacy row — just clear it so the player is unblocked
        if row.get("battle_id"):
            db.delete_battle(row["battle_id"])
        else:
            db.db.execute("DELETE FROM battles WHERE channel_id=?", (row["channel_id"],))
            db.db.commit()
        await interaction.response.send_message(
            "Cleared a stuck battle — you're free to fight again.", ephemeral=True
        )
        return

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

    for f in (fa, fb):
        fid = str(f["id"])
        if not fid.startswith("npc:"):
            db.update_player_hp(fid, max(0, f["hp"]))

    db.delete_battle(row["battle_id"])
    result_msg = f"**{forfeiter['name']}** forfeited. 🏆 **{winner['name']}** wins!"
    try:
        await interaction.response.send_message(result_msg)
    except discord.NotFound:
        try:
            await interaction.channel.send(result_msg)
        except Exception:
            pass


# ── /cannons ──────────────────────────────────────────────────────────────────

async def _cannon_autocomplete(interaction: discord.Interaction, current: str):
    try:
        uid    = str(interaction.user.id)
        player = db.get_player(uid)
        if not player or not player["crew_id"]:
            return []

        my_crew  = db.get_crew(player["crew_id"])
        if not my_crew:
            return []
        mq, mr   = my_crew["q"] or 0, my_crew["r"] or 0
        in_range = game.crews_in_cannon_range(player["crew_id"])
        choices  = []
        for c in in_range:
            if current.lower() not in c["name"].lower():
                continue
            dist = game._hex_dist(mq, mr, c["q"] or 0, c["r"] or 0)
            choices.append(discord.app_commands.Choice(
                name=f"{c['name']}  ({dist} tile{'s' if dist != 1 else ''})",
                value=c["id"],
            ))
        return choices[:25]
    except (discord.NotFound, Exception):
        return []


@discord.app_commands.command(
    name="cannons",
    description="Fire cannons at an enemy crew within range (captain only)",
)
@discord.app_commands.describe(target="Enemy crew to fire at")
@discord.app_commands.autocomplete(target=_cannon_autocomplete)
@discord.app_commands.guilds(MY_GUILD)
async def cannons_cmd(interaction: discord.Interaction, target: str):
    uid    = str(interaction.user.id)
    player = db.get_player(uid)

    if not player or not player["crew_id"]:
        await interaction.response.send_message("You need to be in a crew.", ephemeral=True)
        return

    crew = db.get_crew(player["crew_id"])
    if str(crew["captain_id"]) != uid:
        await interaction.response.send_message(
            "Only the captain can give the order to fire.", ephemeral=True
        )
        return

    if player["following_id"] != "ship":
        await interaction.response.send_message(
            "You need to be on the ship to fire cannons.", ephemeral=True
        )
        return

    ship_hp, _ = db.get_ship_hp(player["crew_id"])
    if ship_hp <= 0:
        await interaction.response.send_message(
            "Your ship is disabled — it needs repairs before it can fight.", ephemeral=True
        )
        return

    if (crew["roll"] or 0) < game.CANNON_ROLL_COST:
        await interaction.response.send_message(
            f"Not enough rolls to fire. Need {game.CANNON_ROLL_COST}.", ephemeral=True
        )
        return

    target_crew = db.get_crew(target)
    if not target_crew:
        await interaction.response.send_message("Target crew not found.", ephemeral=True)
        return

    dist = game._hex_dist(
        crew["q"] or 0, crew["r"] or 0,
        target_crew["q"] or 0, target_crew["r"] or 0,
    )

    if dist == 0:
        await interaction.response.send_message(
            "You're on the same tile — use `/battle` for close combat.", ephemeral=True
        )
        return

    if dist > game.CANNON_RANGE:
        await interaction.response.send_message(
            f"**{target_crew['name']}** is out of range "
            f"({dist} tiles away, max {game.CANNON_RANGE}).", ephemeral=True
        )
        return

    db.spend_crew_roll(player["crew_id"], game.CANNON_ROLL_COST)

    hit_a, dmg_a, chance_a, _ = game.cannon_volley(crew, target_crew)
    t_hp, t_max = db.get_ship_hp(target)
    result_a = f"hit! (-{dmg_a})" if hit_a else "miss"
    if hit_a:
        db.damage_ship(target, dmg_a)
        if db.get_ship_hp(target)[0] <= 0:
            result_a += " 🔥 disabled!"

    t_hp_now, _ = db.get_ship_hp(target)
    result_b = ""
    if t_hp_now > 0:
        hit_b, dmg_b, chance_b, _ = game.cannon_volley(target_crew, crew)
        result_b = f"hit! (-{dmg_b})" if hit_b else "miss"
        if hit_b:
            db.damage_ship(player["crew_id"], dmg_b)
            if db.get_ship_hp(player["crew_id"])[0] <= 0:
                result_b += " 🔥 disabled!"

    ship_name = (target_crew["ship_name"] or "").strip()
    target_label = f"the **{ship_name}**" if ship_name else f"**{target_crew['name']}**"

    line1 = f"💥 **{crew['name']}** open fire on {target_label}! ({result_a})"
    line2 = f"↩️ **{target_crew['name']}** return fire! ({result_b})" if result_b else ""

    embed = discord.Embed(
        description=f"{line1}\n{line2}".strip(),
        color=0x8a2a1a,
    )
    await interaction.response.send_message(embed=embed)
