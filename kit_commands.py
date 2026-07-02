# ═══════════════════════════════════════════════════════════════════════════════
#  kit_commands.py  ·  /kit command group
#  Add to bot.py:
#      from kit_commands import kit_group
#      bot.tree.add_command(kit_group)
# ═══════════════════════════════════════════════════════════════════════════════

import discord
import db
from config import GUILD_ID

# ── Pool stat system ──────────────────────────────────────────────────────────
# Each move spends POOL_TOTAL points across Power / Accuracy / Speed, each stat
# between STAT_MIN and STAT_MAX. Keywords are separate riders, not stat points.
# Score → battle effect (kept in sync with battle.py's mapping):
#   Power    p → damage ×(0.7 + 0.1·(p−1))    → 0.70 .. 1.20
#   Accuracy a → hit chance 55 + 8·(a−1) %     → 55 .. 95
#   Speed    s → evasion 7·(s−1)% + pierce 3·(s−1)% + initiative

POOL_TOTAL = 10
STAT_MIN   = 1
STAT_MAX   = 6
MAX_MOVES  = 4


def dmg_mult(power):     return round(0.7 + 0.1 * (power - 1), 2)   # 0.70 .. 1.20
def hit_pct(accuracy):   return 55 + 8 * (accuracy - 1)            # 55 .. 95
def evasion_pct(speed):  return max(0, 7 * (speed - 1))            # 0 .. 35
def pierce_pct(speed):   return max(0, 3 * (speed - 1))            # 0 .. 15


KEYWORDS = {
    "RISKY":  {"desc": "You take 20% of the damage you deal as recoil.",   "recoil": 0.20},
    "SLASH":  {"desc": "Makes this a slash attack (needs a bladed weapon).",   "attack_type": "slash"},
    "PIERCE": {"desc": "Makes this a pierce attack (needs a piercing weapon).", "attack_type": "pierce"},
}


def build_pool_move(name, power, accuracy, speed, keywords):
    """
    Build a move from three pool scores + keyword list.
    Returns a result dict: name, stats, keywords, errors, warnings.
    """
    errors   = []
    warnings = []

    for label, v in (("Power", power), ("Accuracy", accuracy), ("Speed", speed)):
        if not isinstance(v, int) or not (STAT_MIN <= v <= STAT_MAX):
            errors.append(f"{label} must be a whole number from {STAT_MIN} to {STAT_MAX}.")

    nums  = [v for v in (power, accuracy, speed) if isinstance(v, int)]
    total = sum(nums)
    if not errors and total != POOL_TOTAL:
        errors.append(
            f"Power + Accuracy + Speed must total {POOL_TOTAL} — yours total {total}."
        )

    kws         = []
    attack_type = "blunt"
    recoil      = 0.0
    for raw in keywords:
        k = raw.strip().upper()
        if not k:
            continue
        if k not in KEYWORDS:
            errors.append(f"Unknown keyword `{k}`.")
            continue
        if k in kws:
            continue
        kws.append(k)
        e = KEYWORDS[k]
        if "attack_type" in e:
            attack_type = e["attack_type"]
        if "recoil" in e:
            recoil = e["recoil"]

    if len([k for k in kws if k in ("SLASH", "PIERCE")]) > 1:
        errors.append("Pick only one of `SLASH` or `PIERCE`.")

    stats = {
        "power": power, "accuracy": accuracy, "speed": speed,
        "attack_type": attack_type, "recoil": recoil,
    }
    return {"name": name, "stats": stats, "keywords": kws,
            "errors": errors, "warnings": warnings}


def to_battle_dict(result):
    """Convert a build result into the move dict battle.py consumes."""
    s = result["stats"]
    return {
        "name":        result["name"],
        "attack_type": s["attack_type"],
        "power":       s["power"],       # 1..6 pool score
        "accuracy":    s["accuracy"],    # 1..6 pool score
        "speed":       s["speed"],       # 1..6 pool score
        "recoil":      s["recoil"],
        # dormant fields kept so the engine's optional paths never KeyError
        "hits":        1,
        "hp_cost":     0,
        "burn":        False,
        "hot":         False,
        "_keywords":   result["keywords"],
        "_pool":       {"power": s["power"], "accuracy": s["accuracy"], "speed": s["speed"]},
    }


# ── Legacy conversion ─────────────────────────────────────────────────────────
# Best-effort remap of pre-pool moves (old keyword/slot builds, or NPC CSV tags)
# into the pool model. Used by /admin recalcmoves and the NPC move builder.

_OLD_POWER_ADJ = {"CRUSHER": 3, "HEAVY": 2, "MEDIUM": 1, "LIGHT": 0, "CHIP": -1, "SLUGGISH": -1}
_OLD_ACC_ADJ   = {"PRECISE": 2, "SHARPEYE": 1, "INACCURATE": -2}
_OLD_SPD_ADJ   = {"BURST": 2, "QUICK": 1, "SLOW": -1, "SLUGGISH": -2}


def _distribute_pool(rp, ra, rs):
    """Turn three raw affinities into integer scores in [STAT_MIN, STAT_MAX] summing to POOL_TOTAL."""
    raws  = [max(0.01, rp), max(0.01, ra), max(0.01, rs)]
    tot   = sum(raws)
    rem   = POOL_TOTAL - 3 * STAT_MIN
    alloc = [r / tot * rem for r in raws]
    base  = [int(a) for a in alloc]
    scores = [STAT_MIN + b for b in base]
    left  = rem - sum(base)
    order = sorted(range(3), key=lambda i: alloc[i] - base[i], reverse=True)
    for i in range(left):
        scores[order[i]] += 1
    # clamp to STAT_MAX, spilling overflow to stats with room (keeps the total)
    for i in range(3):
        if scores[i] > STAT_MAX:
            over = scores[i] - STAT_MAX
            scores[i] = STAT_MAX
            for j in range(3):
                if over <= 0:
                    break
                room = STAT_MAX - scores[j]
                if room > 0:
                    take = min(over, room)
                    scores[j] += take
                    over -= take
    return scores[0], scores[1], scores[2]


def legacy_to_pool(old_move):
    """Return (power, accuracy, speed, keywords, attack_type) for a pre-pool move."""
    attack_type = old_move.get("attack_type", "blunt")

    # already a pool move — keep its scores, just normalise keywords
    pool = old_move.get("_pool")
    if pool:
        power    = pool.get("power", 3)
        accuracy = pool.get("accuracy", 3)
        speed    = pool.get("speed", 4)
    else:
        disp = old_move.get("_display") or {}
        kws  = [k.upper() for k in old_move.get("_keywords", [])]
        if disp:
            rp = disp.get("power", 3)                       # 1..10
            ra = (disp.get("accuracy", 75) - 40) / 12.0     # ~45..100 → ~0.4..5
            rs = disp.get("speed", 0) + 3                   # tier -2..2 → 1..5
        else:
            rp = 3 + sum(_OLD_POWER_ADJ.get(k, 0) for k in kws)
            ra = 3 + sum(_OLD_ACC_ADJ.get(k, 0)   for k in kws)
            rs = 3 + sum(_OLD_SPD_ADJ.get(k, 0)   for k in kws)
        power, accuracy, speed = _distribute_pool(rp, ra, rs)

    new_kws = []
    if attack_type == "slash":
        new_kws.append("SLASH")
    elif attack_type == "pierce":
        new_kws.append("PIERCE")
    old_kws = [k.upper() for k in old_move.get("_keywords", [])]
    if old_move.get("recoil", 0) or "RISKY" in old_kws:
        new_kws.append("RISKY")
    return power, accuracy, speed, new_kws, attack_type


# ── Discord display helpers ───────────────────────────────────────────────────

def _bar(val, max_val, width=8):
    if max_val <= 0:
        return "░" * width
    filled = max(0, min(width, round((val / max_val) * width)))
    return "█" * filled + "░" * (width - filled)


def _format_pool(power, accuracy, speed, attack_type, keywords, recoil=0.0):
    """Shared renderer for a pool move's stat block."""
    total = power + accuracy + speed
    over  = (total != POOL_TOTAL)
    lines = [
        f"`{_bar(power,    STAT_MAX)}` **{power}** pwr → ×{dmg_mult(power)} dmg",
        f"`{_bar(accuracy, STAT_MAX)}` **{accuracy}** acc → {hit_pct(accuracy)}% to hit",
        f"`{_bar(speed,    STAT_MAX)}` **{speed}** spd → {evasion_pct(speed)}% evade · "
        f"{pierce_pct(speed)}% pierce",
        f"Pool **{total}/{POOL_TOTAL}**" + ("  ⚠ must total 10" if over else "")
        + f"  ·  Type `{attack_type}`",
    ]
    kws = " ".join(keywords) if keywords else "none"
    lines.append(f"Keywords: `{kws}`")
    return "\n".join(lines)


def _format_built(result):
    """Format a freshly-built pool move for an embed field."""
    s = result["stats"]
    return _format_pool(s["power"], s["accuracy"], s["speed"],
                        s["attack_type"], result["keywords"], s["recoil"])


def _format_stored(move):
    """Format a stored move dict for an embed field."""
    pool = move.get("_pool") or {}
    power    = pool.get("power",    move.get("power", 3))
    accuracy = pool.get("accuracy", move.get("accuracy", 3))
    speed    = pool.get("speed",    move.get("speed", 4))
    return _format_pool(power, accuracy, speed,
                        move.get("attack_type", "blunt"),
                        move.get("_keywords", []), move.get("recoil", 0.0))


# ── Autocomplete handlers ─────────────────────────────────────────────────────

async def _move_name_autocomplete(interaction: discord.Interaction, current: str):
    try:
        moves = db.get_player_moves(str(interaction.user.id))
        return [
            discord.app_commands.Choice(name=m["name"], value=m["name"])
            for m in moves
            if current.lower() in m["name"].lower()
        ][:25]
    except (discord.NotFound, Exception):
        return []


# ── Kit command group ─────────────────────────────────────────────────────────

kit_group = discord.app_commands.Group(
    name="kit",
    description="Manage your moveset",
    guild_ids=[GUILD_ID],
)

_TYPE_CHOICES = [
    discord.app_commands.Choice(name="blunt",  value="blunt"),
    discord.app_commands.Choice(name="slash",  value="slash"),
    discord.app_commands.Choice(name="pierce", value="pierce"),
]


@kit_group.command(name="help", description="How to build your kit")
async def kit_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="How to build your kit",
        description=(
            "Your kit is your moveset — build up to four moves that represent your character!\n\n"
            f"Every move spends **{POOL_TOTAL} points** across three stats. Each stat must be "
            f"between **{STAT_MIN}** and **{STAT_MAX}**, and the three must add up to exactly "
            f"**{POOL_TOTAL}**."
        ),
        color=0x3a7ebf,
    )
    embed.add_field(
        name="Power",
        value="Bigger hits. Score → damage: 1 = ×0.70 … 6 = ×1.20.",
        inline=False,
    )
    embed.add_field(
        name="Accuracy",
        value="Chance to land. Score → hit %: 1 = 55% … 6 = 95%.",
        inline=False,
    )
    embed.add_field(
        name="Speed",
        value=("Weave and strike first. Score → evasion (dodge incoming hits) + pierce "
               "(cut a target's evasion) + initiative. 1 = 0% / 0% … 6 = 35% / 15%."),
        inline=False,
    )
    kw_lines = "\n".join(f"`{k}` — {v['desc']}" for k, v in KEYWORDS.items())
    embed.add_field(name="Keywords (optional)", value=kw_lines, inline=False)
    embed.set_footer(text="Example: Power 5 · Accuracy 4 · Speed 1  +  keyword RISKY")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@kit_group.command(name="show", description="Show your current moveset")
async def kit_show(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    if not db.get_player(uid):
        await interaction.response.send_message("Register first — pick your allegiance from the role picker.", ephemeral=True)
        return

    moves = db.get_player_moves(uid)
    embed = discord.Embed(
        title=f"⚔  {interaction.user.display_name}'s Kit",
        color=0x1a3f6b,
    )

    if not moves:
        embed.description = "No moves yet. Use `/kit add` to build your kit."
    else:
        for m in moves:
            embed.add_field(
                name=f"{m['name']}  ·  `{m['attack_type']}`",
                value=_format_stored(m),
                inline=False,
            )
        embed.set_footer(text=f"{len(moves)}/{MAX_MOVES} moves")

    await interaction.response.send_message(embed=embed, ephemeral=True)


def _parse_int(raw):
    try:
        return int(str(raw).strip())
    except (ValueError, TypeError):
        return None


def _render_move_result(uid, name_raw, power_raw, acc_raw, speed_raw, kw_raw):
    """
    Validate and build a pool move from raw modal input.
    Returns (embed, view) — Edit button always; Add button when the move is valid.
    """
    name     = (name_raw or "").strip()[:50] or "Unnamed"
    keywords = [k.upper() for k in (kw_raw or "").split()]
    moves    = db.get_player_moves(uid)

    power    = _parse_int(power_raw)
    accuracy = _parse_int(acc_raw)
    speed    = _parse_int(speed_raw)

    result = build_pool_move(name, power, accuracy, speed, keywords)
    raws   = (name_raw, power_raw, acc_raw, speed_raw, kw_raw)

    if result["errors"]:
        embed = discord.Embed(
            title="⚠  Can't build that move",
            description="• " + "\n• ".join(result["errors"])
                        + "\n\nPress **Edit** to fix it. See `/kit help` for the rules.",
            color=0xe05555,
        )
        return embed, MoveResultView(uid, *raws, addable=False)

    s = result["stats"]
    embed = discord.Embed(
        title=f"Preview: {name}  ·  `{s['attack_type']}`",
        description=_format_built(result),
        color=0x1a3f6b,
    )
    embed.set_footer(text=f"Kit: {len(moves)}/{MAX_MOVES} moves")
    move_dict = to_battle_dict(result)
    view = MoveResultView(
        uid, *raws,
        addable=True, move_dict=move_dict, built=result, move_count=len(moves),
    )
    return embed, view


class KitAddModal(discord.ui.Modal):
    def __init__(self, uid: str, name: str = "", power: str = "",
                 accuracy: str = "", speed: str = "", keywords: str = "",
                 edit_existing: bool = False):
        super().__init__(title="Build a Move")
        self.uid           = uid
        self.edit_existing = edit_existing

        self.name_input = discord.ui.TextInput(
            label="Move name", default=name, max_length=50, required=True,
        )
        self.power_input = discord.ui.TextInput(
            label="Power (1-6)", default=power, max_length=1, required=True,
            placeholder="e.g. 5",
        )
        self.acc_input = discord.ui.TextInput(
            label="Accuracy (1-6)", default=accuracy, max_length=1, required=True,
            placeholder="e.g. 4",
        )
        self.speed_input = discord.ui.TextInput(
            label="Speed (1-6)  ·  must total 10", default=speed, max_length=1,
            required=True, placeholder="e.g. 1",
        )
        self.kw_input = discord.ui.TextInput(
            label="Keywords (optional)",
            placeholder="RISKY  ·  SLASH  ·  PIERCE",
            default=keywords, max_length=100, required=False,
        )
        self.add_item(self.name_input)
        self.add_item(self.power_input)
        self.add_item(self.acc_input)
        self.add_item(self.speed_input)
        self.add_item(self.kw_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not db.get_player(self.uid):
            await interaction.response.send_message(
                "Register first — pick your allegiance from the role picker.", ephemeral=True
            )
            return

        if not self.edit_existing and len(db.get_player_moves(self.uid)) >= MAX_MOVES:
            await interaction.response.send_message(
                f"Kit is full ({MAX_MOVES}/{MAX_MOVES}). Remove a move first with `/kit remove`.",
                ephemeral=True,
            )
            return

        embed, view = _render_move_result(
            self.uid, str(self.name_input.value), str(self.power_input.value),
            str(self.acc_input.value), str(self.speed_input.value),
            str(self.kw_input.value),
        )
        if self.edit_existing:
            await interaction.response.edit_message(content=None, embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class MoveResultView(discord.ui.View):
    def __init__(self, uid: str, raw_name: str, raw_power: str, raw_acc: str,
                 raw_speed: str, raw_keywords: str,
                 addable: bool = False, move_dict: dict = None,
                 built: dict = None, move_count: int = 0):
        super().__init__(timeout=300)
        self.uid          = uid
        self.raw_name     = raw_name
        self.raw_power    = raw_power
        self.raw_acc      = raw_acc
        self.raw_speed    = raw_speed
        self.raw_keywords = raw_keywords
        self.move_dict    = move_dict
        self.built        = built
        self.move_count   = move_count
        if not addable:
            self.remove_item(self.confirm)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True

    @discord.ui.button(label="Add to Kit", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("This isn't your move.", ephemeral=True)
            return
        self.stop()
        for child in self.children:
            child.disabled = True

        # re-check slot count in case they spammed /kit add
        current = db.get_player_moves(self.uid)
        if len(current) >= MAX_MOVES:
            await interaction.response.edit_message(
                content=f"Kit is full ({MAX_MOVES}/{MAX_MOVES}). Remove a move first.",
                embed=None, view=self,
            )
            return

        if any(m["name"].lower() == self.move_dict["name"].lower() for m in current):
            await interaction.response.edit_message(
                content=f"You already have a move called **{self.move_dict['name']}**.",
                embed=None, view=self,
            )
            return

        db.add_player_move(self.uid, self.move_dict)
        name  = self.move_dict["name"]
        atype = self.move_dict["attack_type"]
        embed = discord.Embed(
            title=f"✓  Added: {name}  ·  `{atype}`",
            description=_format_built(self.built),
            color=0x2d9e5f,
        )
        embed.set_footer(text=f"{self.move_count + 1}/{MAX_MOVES} moves in kit")
        await interaction.response.edit_message(content=None, embed=embed, view=self)

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.primary)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("This isn't your move.", ephemeral=True)
            return
        modal = KitAddModal(
            self.uid,
            name=self.raw_name,
            power=self.raw_power,
            accuracy=self.raw_acc,
            speed=self.raw_speed,
            keywords=self.raw_keywords,
            edit_existing=True,
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("This isn't your move.", ephemeral=True)
            return
        self.stop()
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="Cancelled.", embed=None, view=self
        )


@kit_group.command(name="add", description="Add a move to your kit")
async def kit_add(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    if not db.get_player(uid):
        await interaction.response.send_message("Register first — pick your allegiance from the role picker.", ephemeral=True)
        return

    if len(db.get_player_moves(uid)) >= MAX_MOVES:
        await interaction.response.send_message(
            f"Kit is full ({MAX_MOVES}/{MAX_MOVES}). Remove a move first with `/kit remove`.",
            ephemeral=True,
        )
        return

    await interaction.response.send_modal(KitAddModal(uid))


@kit_group.command(name="remove", description="Remove a move from your kit")
@discord.app_commands.describe(name="Move to remove")
@discord.app_commands.autocomplete(name=_move_name_autocomplete)
async def kit_remove(interaction: discord.Interaction, name: str):
    uid     = str(interaction.user.id)
    removed = db.remove_player_move(uid, name)
    if not removed:
        await interaction.response.send_message(
            f"No move called **{name}** in your kit.", ephemeral=True
        )
        return
    moves = db.get_player_moves(uid)
    await interaction.response.send_message(
        f"Removed **{name}** from your kit. ({len(moves)}/{MAX_MOVES} moves)",
        ephemeral=True,
    )
