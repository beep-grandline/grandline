# ═══════════════════════════════════════════════════════════════════════════════
#  kit_commands.py  ·  /kit command group
#  Add to bot.py:
#      from kit_commands import kit_group
#      bot.tree.add_command(kit_group)
# ═══════════════════════════════════════════════════════════════════════════════

import discord
import db
from config import GUILD_ID

# ── Keyword system ────────────────────────────────────────────────────────────
# Mirrored from move_builder.py (no IPython dependency here)

SLOTS = 4
BASE  = {"power": 3, "accuracy": 75, "priority": 0,
         "tracking": 5, "hits": 1, "hp_cost": 0, "recoil": 0.0}

POWER_TIERS = {"CHIP", "LIGHT", "MEDIUM", "HEAVY", "CRUSHER"}
HIT_TIERS   = {"FLURRY", "BARRAGE"}   # mutually exclusive — can't combine

KEYWORDS = {
    # power tiers
    "CHIP":        {"slots": -1, "apply": {"power": -2}, "sign": "-", "desc": "power → 1",  "cat": "descriptor", "stat": "power"},
    "LIGHT":       {"slots":  0, "apply": {"power":  0}, "sign": "=", "desc": "power → 3",  "cat": "descriptor", "stat": "power"},
    "MEDIUM":      {"slots":  1, "apply": {"power": +2}, "sign": "+", "desc": "power → 5",  "cat": "descriptor", "stat": "power"},
    "HEAVY":       {"slots":  2, "apply": {"power": +4}, "sign": "+", "desc": "power → 7",  "cat": "descriptor", "stat": "power"},
    "CRUSHER":     {"slots":  3, "apply": {"power": +6}, "sign": "+", "desc": "power → 9",  "cat": "descriptor", "stat": "power"},
    # accuracy
    "PRECISE":     {"slots":  1, "apply": {"accuracy": +15}, "sign": "+", "desc": "accuracy +15", "cat": "descriptor", "stat": "accuracy"},
    "SHARPEYE":    {"slots":  1, "apply": {"accuracy": +10}, "sign": "+", "desc": "accuracy +10", "cat": "descriptor", "stat": "accuracy"},
    "INACCURATE":  {"slots": -1, "apply": {"accuracy": -20}, "sign": "-", "desc": "accuracy -20", "cat": "descriptor", "stat": "accuracy"},
    # priority
    "BURST":       {"slots":  2, "apply": {"priority": +2}, "sign": "+", "desc": "priority +2", "cat": "descriptor", "stat": "priority"},
    "QUICK":       {"slots":  1, "apply": {"priority": +1}, "sign": "+", "desc": "priority +1", "cat": "descriptor", "stat": "priority"},
    "SLOW":        {"slots": -1, "apply": {"priority": -1}, "sign": "-", "desc": "priority -1", "cat": "descriptor", "stat": "priority"},
    "SLUGGISH":    {"slots": -2, "apply": {"priority": -2}, "sign": "-", "desc": "priority -2", "cat": "descriptor", "stat": "priority"},
    # tracking
    "HOMING":      {"slots":  1, "apply": {"tracking": +3}, "sign": "+", "desc": "tracking +3", "cat": "descriptor", "stat": "tracking"},
    "FOCUSED":     {"slots":  1, "apply": {"tracking": +2}, "sign": "+", "desc": "tracking +2", "cat": "descriptor", "stat": "tracking"},
    "TELEGRAPHED": {"slots": -1, "apply": {"tracking": -3}, "sign": "-", "desc": "tracking -3", "cat": "descriptor", "stat": "tracking"},
    # hits
    "MULTI":       {"slots":  1, "apply": {"hits": +1},  "sign": "+", "desc": "+1 hit roll", "cat": "descriptor", "stat": "hits"},
    "FLURRY":      {"slots":  1, "apply": {"hits": +5},  "sign": "+", "desc": "+5 hit rolls (power spread, independent rolls)", "cat": "descriptor", "stat": "hits"},
    "BARRAGE":     {"slots":  1, "apply": {"hits": +29}, "sign": "+", "desc": "+29 hit rolls (30 total, 2× scale on full connect)", "cat": "descriptor", "stat": "hits"},
    # conditions
    "DRAINING":    {"slots": -1, "apply": {"hp_cost": 15},    "sign": "-", "desc": "15 HP on use",  "cat": "condition", "stat": "hp_cost"},
    "EXHAUSTING":  {"slots": -1, "apply": {"hp_cost": 25},    "sign": "-", "desc": "25 HP on use",  "cat": "condition", "stat": "hp_cost"},
    "RISKY":       {"slots": -1, "apply": {"recoil": 0.20},   "sign": "-", "desc": "20% recoil",    "cat": "condition", "stat": "recoil"},
}

# Power is stored on a 1–10 scale; multiply by this to fit battle.py's damage range
POWER_SCALE = 9

MAX_MOVES = 4


def _build_move(name, attack_type, keywords):
    """
    Build a move from a keyword list.
    Returns a result dict with keys: stats, used, remaining, log, errors, warnings.
    """
    stats      = dict(BASE)
    used       = 0
    log        = []
    errors     = []
    warnings   = []
    tiers_seen = []

    # hard check — multiple power tiers can't coexist
    tiers_in_input = [k.strip().upper() for k in keywords if k.strip().upper() in POWER_TIERS]
    if len(tiers_in_input) > 1:
        errors.append(f"Only one power tier allowed — you used: {', '.join(tiers_in_input)}")
        return {
            "name": name, "type": attack_type,
            "stats": stats, "used": 0, "remaining": SLOTS,
            "log": [], "errors": errors, "warnings": [],
        }

    # hard check — flurry and barrage can't coexist
    hit_tiers_in_input = [k.strip().upper() for k in keywords if k.strip().upper() in HIT_TIERS]
    if len(hit_tiers_in_input) > 1:
        errors.append(f"FLURRY and BARRAGE can't be combined — pick one")
        return {
            "name": name, "type": attack_type,
            "stats": stats, "used": 0, "remaining": SLOTS,
            "log": [], "errors": errors, "warnings": [],
        }

    for kw in keywords:
        key = kw.strip().upper()
        if key not in KEYWORDS:
            errors.append(key)
            continue
        if key in POWER_TIERS:
            tiers_seen.append(key)
        entry = KEYWORDS[key]
        used += entry["slots"]
        log.append((key, entry))
        for stat, delta in entry["apply"].items():
            if stat == "recoil":
                stats["recoil"] = round(stats["recoil"] + delta, 2)
            elif stat == "hp_cost":
                stats["hp_cost"] += delta
            else:
                stats[stat] += delta

    stats["power"]    = max(1,  min(10,  stats["power"]))
    stats["accuracy"] = max(5,  min(100, stats["accuracy"]))
    stats["tracking"] = max(1,  min(10,  stats["tracking"]))
    stats["priority"] = max(-2, min(2,   stats["priority"]))
    stats["hits"]     = max(1,  min(30,  stats["hits"]))

    return {
        "name":      name,
        "type":      attack_type,
        "stats":     stats,
        "used":      used,
        "remaining": SLOTS - used,
        "log":       log,
        "errors":    errors,
        "warnings":  warnings,
    }


def _to_battle_dict(name, attack_type, built):
    """
    Convert build result to a dict battle.py can use.
    Stores _display and _keywords for kit show rendering.
    """
    s = built["stats"]
    return {
        # battle.py fields
        "name":        name,
        "power":       round(s["power"] * POWER_SCALE),
        "accuracy":    s["accuracy"],
        "attack_type": attack_type,
        "hp_cost":     s["hp_cost"],
        "recoil":      s["recoil"],
        "hits":        s["hits"],
        "priority":    s["priority"],
        "tracking":    s["tracking"],
        # display metadata (underscore = ignored by battle.py)
        "_keywords":   [kw for kw, _ in built["log"]],
        "_display":    s,
    }


# ── Discord display helpers ───────────────────────────────────────────────────

def _bar(val, max_val, width=8):
    if max_val <= 0:
        return "░" * width
    filled = max(0, min(width, round((val / max_val) * width)))
    return "█" * filled + "░" * (width - filled)


def _format_built(built):
    """Format a freshly-built move (has stats dict) for an embed field."""
    s   = built["stats"]
    kws = " ".join(kw for kw, _ in built["log"]) or "none"
    over = built["remaining"] < 0
    slot_str = f"{built['used']}/{SLOTS}" + (" ⚠ OVER BUDGET" if over else "")
    lines = [
        f"`{_bar(s['power'],    10)}` **{s['power']}/10** pwr  "
        f"`{_bar(s['accuracy'], 100)}` **{s['accuracy']}%** acc  "
        f"`{_bar(s['tracking'], 10)}` **{s['tracking']}/10** trk",
        f"Priority **{s['priority']:+d}**  ·  Slots **{slot_str}**",
    ]
    mods = []
    if s["hits"] > 1:    mods.append(f"×{s['hits']} hits")
    if s["hp_cost"] > 0: mods.append(f"{s['hp_cost']} HP on use")
    if s["recoil"] > 0:  mods.append(f"{int(s['recoil']*100)}% recoil")
    if mods:
        lines.append("Modifiers: " + " · ".join(mods))
    lines.append(f"Keywords: `{kws}`")
    return "\n".join(lines)


def _format_stored(move):
    """Format a stored move dict (has _display) for an embed field."""
    s   = move.get("_display", {})
    kws = " ".join(move.get("_keywords", [])) or "legacy move"
    lines = [
        f"`{_bar(s.get('power',    3),  10)}` **{s.get('power', 3)}/10** pwr  "
        f"`{_bar(s.get('accuracy', 75), 100)}` **{s.get('accuracy', 75)}%** acc  "
        f"`{_bar(s.get('tracking', 5),  10)}` **{s.get('tracking', 5)}/10** trk",
        f"Priority **{s.get('priority', 0):+d}**",
    ]
    mods = []
    if move.get("hits", 1) > 1:   mods.append(f"×{move['hits']} hits")
    if move.get("hp_cost", 0) > 0: mods.append(f"{move['hp_cost']} HP on use")
    if move.get("recoil",  0) > 0: mods.append(f"{int(move['recoil']*100)}% recoil")
    if mods:
        lines.append("Modifiers: " + " · ".join(mods))
    lines.append(f"Keywords: `{kws}`")
    return "\n".join(lines)


# ── Autocomplete handlers ─────────────────────────────────────────────────────

async def _kw_autocomplete(interaction: discord.Interaction, current: str):
    try:
        ns = interaction.namespace
        already = {
            (getattr(ns, "kw1", "") or "").upper(),
            (getattr(ns, "kw2", "") or "").upper(),
            (getattr(ns, "kw3", "") or "").upper(),
            (getattr(ns, "kw4", "") or "").upper(),
        } - {""}

        partial = current.upper()
        choices = []
        for kw, entry in KEYWORDS.items():
            if kw in already:
                continue
            if partial and not kw.startswith(partial):
                continue
            choices.append(discord.app_commands.Choice(
                name=kw,
                value=kw,
            ))
        return choices[:25]
    except (discord.NotFound, Exception):
        return []


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


class ConfirmMoveView(discord.ui.View):
    def __init__(self, uid: str, move_dict: dict, built: dict, move_count: int):
        super().__init__(timeout=120)
        self.uid        = uid
        self.move_dict  = move_dict
        self.built      = built
        self.move_count = move_count

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
        await interaction.response.edit_message(embed=embed, view=self)

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
@discord.app_commands.describe(
    name="Move name",
    attack_type="Attack type",
    kw1="Keyword 1",
    kw2="Keyword 2",
    kw3="Keyword 3",
    kw4="Keyword 4",
)
@discord.app_commands.choices(attack_type=_TYPE_CHOICES)
@discord.app_commands.autocomplete(kw1=_kw_autocomplete, kw2=_kw_autocomplete,
                                   kw3=_kw_autocomplete, kw4=_kw_autocomplete)
async def kit_add(
    interaction: discord.Interaction,
    name: str,
    attack_type: str,
    kw1: str = None,
    kw2: str = None,
    kw3: str = None,
    kw4: str = None,
):
    uid = str(interaction.user.id)
    if not db.get_player(uid):
        await interaction.response.send_message("Register first — pick your allegiance from the role picker.", ephemeral=True)
        return

    moves = db.get_player_moves(uid)
    if len(moves) >= MAX_MOVES:
        await interaction.response.send_message(
            f"Kit is full ({MAX_MOVES}/{MAX_MOVES}). Remove a move first with `/kit remove`.",
            ephemeral=True,
        )
        return

    keywords = [k.upper() for k in [kw1, kw2, kw3, kw4] if k]
    built    = _build_move(name, attack_type, keywords)

    if built["errors"]:
        await interaction.response.send_message(
            f"Unknown keyword(s): `{'`, `'.join(built['errors'])}`.", ephemeral=True
        )
        return

    over = built["remaining"] < 0
    embed = discord.Embed(
        title=f"{'⚠  Over budget: ' if over else 'Preview: '}{name}  ·  `{attack_type}`",
        description=_format_built(built),
        color=0xe05555 if over else 0x1a3f6b,
    )

    if built["warnings"]:
        embed.add_field(name="⚠ Warning", value="\n".join(built["warnings"]), inline=False)

    if over:
        embed.set_footer(text=f"Over budget by {-built['remaining']} slot(s) — adjust your keywords.")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    embed.set_footer(text=f"Slot budget: {built['used']}/{SLOTS}  ·  Kit: {len(moves)}/{MAX_MOVES}")
    move_dict = _to_battle_dict(name, attack_type, built)
    view      = ConfirmMoveView(uid=uid, move_dict=move_dict, built=built, move_count=len(moves))
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


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
