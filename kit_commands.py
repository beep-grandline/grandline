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
    "MULTI":       {"slots":  1, "apply": {"hits": +1}, "sign": "+", "desc": "+1 hit roll", "cat": "descriptor", "stat": "hits"},
    # conditions
    "DRAINING":    {"slots": -1, "apply": {"hp_cost": 15},    "sign": "-", "desc": "15 HP on use",  "cat": "condition", "stat": "hp_cost"},
    "EXHAUSTING":  {"slots": -1, "apply": {"hp_cost": 25},    "sign": "-", "desc": "25 HP on use",  "cat": "condition", "stat": "hp_cost"},
    "RISKY":       {"slots": -1, "apply": {"recoil": 0.20},   "sign": "-", "desc": "20% recoil",    "cat": "condition", "stat": "recoil"},
}

# Power is stored on a 1–10 scale; multiply by this to fit battle.py's damage range
POWER_SCALE = 9

MAX_MOVES = 6


def _build_move(name, attack_type, keywords):
    """
    Build a move from a keyword list.
    Returns a result dict with keys: stats, used, remaining, log, errors, warnings.
    """
    stats    = dict(BASE)
    used     = 0
    log      = []
    errors   = []
    warnings = []
    tiers_seen = []

    for kw in keywords:
        key = kw.strip().upper()
        if key not in KEYWORDS:
            errors.append(key)
            continue
        if key in POWER_TIERS:
            tiers_seen.append(key)
            if len(tiers_seen) > 1:
                warnings.append(f"Multiple power tiers: {tiers_seen}")
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
    stats["hits"]     = max(1,  min(6,   stats["hits"]))

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

async def _keywords_autocomplete(interaction: discord.Interaction, current: str):
    upper   = current.upper()
    parts   = upper.split()
    if current and not current.endswith(" "):
        partial = parts[-1] if parts else ""
        already = set(parts[:-1])
    else:
        partial = ""
        already = set(parts)

    choices = []
    for kw, entry in KEYWORDS.items():
        if kw in already or not kw.startswith(partial):
            continue
        full_val = (current.rstrip() + " " + kw).strip()
        n        = -entry["slots"]
        slot_s   = "free" if n == 0 else f"{n:+d} slot{'s' if abs(n) != 1 else ''}"
        choices.append(discord.app_commands.Choice(
            name=f"{kw}  —  {entry['desc']}  ({slot_s})"[:100],
            value=full_val[:100],
        ))

    return choices[:25]


async def _move_name_autocomplete(interaction: discord.Interaction, current: str):
    moves = db.get_player_moves(str(interaction.user.id))
    return [
        discord.app_commands.Choice(name=m["name"], value=m["name"])
        for m in moves
        if current.lower() in m["name"].lower()
    ][:25]


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
        await interaction.response.send_message("Register first with `/register`.", ephemeral=True)
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


@kit_group.command(name="preview", description="Preview a move without saving it")
@discord.app_commands.describe(
    name="Move name",
    attack_type="Attack type",
    keywords="Keywords  (e.g. HEAVY QUICK EXHAUSTING)",
)
@discord.app_commands.choices(attack_type=_TYPE_CHOICES)
@discord.app_commands.autocomplete(keywords=_keywords_autocomplete)
async def kit_preview(interaction: discord.Interaction, name: str, attack_type: str, keywords: str):
    built = _build_move(name, attack_type, keywords.upper().split())
    over  = built["remaining"] < 0
    embed = discord.Embed(
        title=f"Preview: {name}  ·  `{attack_type}`",
        description=_format_built(built),
        color=0xe05555 if over else 0x1a3f6b,
    )
    if over:
        embed.set_footer(text=f"⚠ Over budget by {-built['remaining']} slot(s) — not saveable")
    else:
        embed.set_footer(text="Looks good? Use /kit add with the same params to save.")
    for e in built["errors"]:
        embed.add_field(name="⚠ Unknown keyword", value=e, inline=True)
    for w in built["warnings"]:
        embed.add_field(name="⚠ Warning", value=w, inline=True)

    await interaction.response.send_message(embed=embed, ephemeral=True)


@kit_group.command(name="add", description="Add a move to your kit")
@discord.app_commands.describe(
    name="Move name",
    attack_type="Attack type",
    keywords="Keywords  (e.g. HEAVY QUICK EXHAUSTING)",
)
@discord.app_commands.choices(attack_type=_TYPE_CHOICES)
@discord.app_commands.autocomplete(keywords=_keywords_autocomplete)
async def kit_add(interaction: discord.Interaction, name: str, attack_type: str, keywords: str):
    uid   = str(interaction.user.id)
    if not db.get_player(uid):
        await interaction.response.send_message("Register first with `/register`.", ephemeral=True)
        return

    moves = db.get_player_moves(uid)
    if len(moves) >= MAX_MOVES:
        await interaction.response.send_message(
            f"Kit is full ({MAX_MOVES}/{MAX_MOVES}). Remove a move first with `/kit remove`.",
            ephemeral=True,
        )
        return

    if any(m["name"].lower() == name.lower() for m in moves):
        await interaction.response.send_message(
            f"You already have a move called **{name}**. Remove it first.", ephemeral=True
        )
        return

    built = _build_move(name, attack_type, keywords.upper().split())

    if built["errors"]:
        await interaction.response.send_message(
            f"Unknown keyword(s): `{'`, `'.join(built['errors'])}`.", ephemeral=True
        )
        return

    if built["remaining"] < 0:
        await interaction.response.send_message(
            f"**{name}** is over budget by {-built['remaining']} slot(s). "
            "Use `/kit preview` to adjust your keywords.",
            ephemeral=True,
        )
        return

    move_dict = _to_battle_dict(name, attack_type, built)
    db.add_player_move(uid, move_dict)

    embed = discord.Embed(
        title=f"✓  Added: {name}  ·  `{attack_type}`",
        description=_format_built(built),
        color=0x2d9e5f,
    )
    embed.set_footer(text=f"{len(moves) + 1}/{MAX_MOVES} moves in kit")
    await interaction.response.send_message(embed=embed, ephemeral=True)


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
