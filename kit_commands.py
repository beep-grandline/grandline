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
BASE  = {"power": 3, "accuracy": 75, "speed": 0,
         "tracking": 5, "hits": 1, "hp_cost": 0, "recoil": 0.0,
         "burn": False, "hot": False}

POWER_TIERS = {"CHIP", "LIGHT", "MEDIUM", "HEAVY", "CRUSHER"}
HIT_TIERS   = {"FLURRY", "BARRAGE"}   # mutually exclusive — can't combine

KEYWORDS = {
    # power tiers
    "CHIP":        {"slots": -1, "apply": {"power": -2, "accuracy": +15}, "sign": "-", "desc": "power → 1, accuracy +15", "cat": "descriptor", "stat": "power"},
    "LIGHT":       {"slots":  0, "apply": {"power":  0}, "sign": "=", "desc": "power → 3",  "cat": "descriptor", "stat": "power"},
    "MEDIUM":      {"slots":  1, "apply": {"power": +2}, "sign": "+", "desc": "power → 5",  "cat": "descriptor", "stat": "power"},
    "HEAVY":       {"slots":  2, "apply": {"power": +4}, "sign": "+", "desc": "power → 7",  "cat": "descriptor", "stat": "power"},
    "CRUSHER":     {"slots":  3, "apply": {"power": +6}, "sign": "+", "desc": "power → 9",  "cat": "descriptor", "stat": "power"},
    # accuracy
    "PRECISE":     {"slots":  2, "apply": {"accuracy": +15}, "sign": "+", "desc": "accuracy +15", "cat": "descriptor", "stat": "accuracy"},
    "SHARPEYE":    {"slots":  1, "apply": {"accuracy": +10}, "sign": "+", "desc": "accuracy +10", "cat": "descriptor", "stat": "accuracy"},
    "INACCURATE":  {"slots": -1, "apply": {"accuracy": -20}, "sign": "-", "desc": "accuracy -20", "cat": "descriptor", "stat": "accuracy"},
    # speed
    "BURST":       {"slots":  2, "apply": {"speed": +2}, "sign": "+", "desc": "speed +2", "cat": "descriptor", "stat": "speed"},
    "QUICK":       {"slots":  1, "apply": {"speed": +1}, "sign": "+", "desc": "speed +1", "cat": "descriptor", "stat": "speed"},
    "SLOW":        {"slots": -1, "apply": {"speed": -1}, "sign": "-", "desc": "speed -1", "cat": "descriptor", "stat": "speed"},
    "SLUGGISH":    {"slots": -1, "apply": {"speed": -2, "power": -2}, "sign": "-", "desc": "speed -2, power -2", "cat": "descriptor", "stat": "speed"},
    # tracking
    "HOMING":      {"slots":  2, "apply": {"tracking": +3}, "sign": "+", "desc": "tracking +3", "cat": "descriptor", "stat": "tracking"},
    "FOCUSED":     {"slots":  1, "apply": {"tracking": +2}, "sign": "+", "desc": "tracking +2", "cat": "descriptor", "stat": "tracking"},
    "TELEGRAPHED": {"slots": -1, "apply": {"tracking": -3}, "sign": "-", "desc": "tracking -3", "cat": "descriptor", "stat": "tracking"},
    # hits
    "MULTI":       {"slots":  1, "apply": {"hits": +1},  "sign": "+", "desc": "+1 hit roll", "cat": "descriptor", "stat": "hits"},
    "FLURRY":      {"slots":  2, "apply": {"hits": +5},  "sign": "+", "desc": "+5 hit rolls (power spread, independent rolls)", "cat": "descriptor", "stat": "hits"},
    "BARRAGE":     {"slots":  3, "apply": {"hits": +29}, "sign": "+", "desc": "+29 hit rolls (30 total, 2× scale on full connect)", "cat": "descriptor", "stat": "hits"},
    # conditions
    "DRAINING":    {"slots": -1, "apply": {"hp_cost": 15},    "sign": "-", "desc": "15 HP on use",       "cat": "condition", "stat": "hp_cost"},
    "EXHAUSTING":  {"slots": -1, "apply": {"hp_cost": 25},    "sign": "-", "desc": "25 HP on use",       "cat": "condition", "stat": "hp_cost"},
    "RISKY":       {"slots": -1, "apply": {"recoil": 0.20},   "sign": "-", "desc": "20% recoil",         "cat": "condition", "stat": "recoil"},
    "BURN":        {"slots":  1, "apply": {},                  "sign": "+", "desc": "30% burn on hit (8 dmg/turn, 2 turns)", "cat": "condition", "stat": "burn"},
    "HOT":         {"slots":  1, "apply": {"power": +1},      "sign": "+", "desc": "ignores armor, +2 dmg vs blocks",       "cat": "condition", "stat": "hot"},
}

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
        if key == "BURN":
            stats["burn"] = True
        if key == "HOT":
            stats["hot"] = True
        for stat, delta in entry["apply"].items():
            if stat == "recoil":
                stats["recoil"] = round(stats["recoil"] + delta, 2)
            elif stat == "hp_cost":
                stats["hp_cost"] += delta
            elif stat not in ("burn", "hot"):
                stats[stat] += delta

    stats["power"]    = max(1,  min(10,  stats["power"]))
    stats["accuracy"] = max(5,  min(100, stats["accuracy"]))
    stats["tracking"] = max(1,  min(10,  stats["tracking"]))
    stats["speed"]    = max(-2, min(2,   stats["speed"]))
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
        "power":       s["power"],
        "accuracy":    s["accuracy"],
        "attack_type": attack_type,
        "hp_cost":     s["hp_cost"],
        "recoil":      s["recoil"],
        "hits":        s["hits"],
        "speed":       s["speed"],
        "tracking":    s["tracking"],
        "burn":        s.get("burn", False),
        "hot":         s.get("hot", False),
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
        f"Speed **{s['speed']:+d}**  ·  Slots **{slot_str}**",
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
        f"Speed **{s.get('speed', 0):+d}**",
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


@kit_group.command(name="help", description="How to build your kit")
async def kit_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="How to build your kit",
        description=(
            "Your kit is your moveset - build four unique moves that represent your character! "
            "Each move can be built from any mix of the keywords below so long as you follow these constraints:\n\n"
            "• Each move has a **4 slot budget**.\n"
            "• You cannot pick two keywords in the same category (except for extra conditions).\n"
            "• You cannot use more than 4 keywords, even if the slot usage is acceptable.\n"
            "• You can unlock slash and pierce moves if you own appropriate weapons."
        ),
        color=0x3a7ebf,
    )
    embed.add_field(name="Power",            value="`CHIP` (+1, +acc) · `LIGHT` (0) · `MEDIUM` (−1) · `HEAVY` (−2) · `CRUSHER` (−3)", inline=False)
    embed.add_field(name="Accuracy",         value="`INACCURATE` (+1) · `SHARPEYE` (−1) · `PRECISE` (−2)", inline=False)
    embed.add_field(name="Speed",            value="`SLUGGISH` (+2, −pwr) · `SLOW` (+1) · `QUICK` (−1) · `BURST` (−2)", inline=False)
    embed.add_field(name="Tracking",         value="`TELEGRAPHED` (+1) · `FOCUSED` (−1) · `HOMING` (−2)", inline=False)
    embed.add_field(name="Hits",             value="`MULTI` (−1) · `FLURRY` (−2) · `BARRAGE` (−3)", inline=False)
    embed.add_field(name="Extra conditions", value="`DRAINING` (+1) · `EXHAUSTING` (+1) · `RISKY` (+1) · `BURN` (−1) · `HOT` (−1)", inline=False)
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


_VALID_TYPES = {"blunt", "slash", "pierce"}


def _render_move_result(uid: str, name_raw: str, type_raw: str, kw_raw: str):
    """
    Validate and build a move from raw modal input.
    Returns (embed, view) — view always has an Edit button; an Add button too
    when the move is valid and within budget.
    """
    name        = (name_raw or "").strip()[:50] or "Unnamed"
    attack_type = (type_raw or "").strip().lower()
    keywords    = [k.upper() for k in (kw_raw or "").split()]
    moves       = db.get_player_moves(uid)

    # invalid attack type → reject
    if attack_type not in _VALID_TYPES:
        embed = discord.Embed(
            title="⚠  Invalid attack type",
            description=(
                f"`{type_raw}` isn't a valid attack type.\n"
                "Use one of: `blunt` · `slash` · `pierce`."
            ),
            color=0xe05555,
        )
        view = MoveResultView(uid, name_raw, type_raw, kw_raw, addable=False)
        return embed, view

    built = _build_move(name, attack_type, keywords)

    # unknown keywords → reject
    if built["errors"]:
        embed = discord.Embed(
            title="⚠  Unknown keyword(s)",
            description=(
                f"These aren't valid keywords: `{'`, `'.join(built['errors'])}`\n"
                "Use `/kit help` for the full list, then press **Edit** to fix them."
            ),
            color=0xe05555,
        )
        view = MoveResultView(uid, name_raw, type_raw, kw_raw, addable=False)
        return embed, view

    over  = built["remaining"] < 0
    embed = discord.Embed(
        title=f"{'⚠  Over budget: ' if over else 'Preview: '}{name}  ·  `{attack_type}`",
        description=_format_built(built),
        color=0xe05555 if over else 0x1a3f6b,
    )
    if built["warnings"]:
        embed.add_field(name="⚠ Warning", value="\n".join(built["warnings"]), inline=False)

    if over:
        embed.set_footer(text=f"Over budget by {-built['remaining']} slot(s) — press Edit to adjust.")
        view = MoveResultView(uid, name_raw, type_raw, kw_raw, addable=False)
        return embed, view

    embed.set_footer(text=f"Slot budget: {built['used']}/{SLOTS}  ·  Kit: {len(moves)}/{MAX_MOVES}")
    move_dict = _to_battle_dict(name, attack_type, built)
    view = MoveResultView(
        uid, name_raw, type_raw, kw_raw,
        addable=True, move_dict=move_dict, built=built, move_count=len(moves),
    )
    return embed, view


class KitAddModal(discord.ui.Modal):
    def __init__(self, uid: str, name: str = "", attack_type: str = "",
                 keywords: str = "", edit_existing: bool = False):
        super().__init__(title="Build a Move")
        self.uid           = uid
        self.edit_existing = edit_existing

        self.name_input = discord.ui.TextInput(
            label="Move name",
            default=name,
            max_length=50,
            required=True,
        )
        self.type_input = discord.ui.TextInput(
            label="Attack type (blunt / slash / pierce)",
            default=attack_type or "blunt",
            max_length=10,
            required=True,
        )
        self.kw_input = discord.ui.TextInput(
            label="Keywords (space-separated)",
            placeholder="e.g. CRUSHER BURST HOMING",
            default=keywords,
            style=discord.TextStyle.paragraph,
            max_length=200,
            required=False,
        )
        self.add_item(self.name_input)
        self.add_item(self.type_input)
        self.add_item(self.kw_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not db.get_player(self.uid):
            await interaction.response.send_message(
                "Register first — pick your allegiance from the role picker.", ephemeral=True
            )
            return

        if len(db.get_player_moves(self.uid)) >= MAX_MOVES:
            await interaction.response.send_message(
                f"Kit is full ({MAX_MOVES}/{MAX_MOVES}). Remove a move first with `/kit remove`.",
                ephemeral=True,
            )
            return

        embed, view = _render_move_result(
            self.uid, str(self.name_input.value),
            str(self.type_input.value), str(self.kw_input.value),
        )
        if self.edit_existing:
            await interaction.response.edit_message(content=None, embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class MoveResultView(discord.ui.View):
    def __init__(self, uid: str, raw_name: str, raw_type: str, raw_keywords: str,
                 addable: bool = False, move_dict: dict = None,
                 built: dict = None, move_count: int = 0):
        super().__init__(timeout=300)
        self.uid          = uid
        self.raw_name     = raw_name
        self.raw_type     = raw_type
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
            attack_type=self.raw_type,
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
