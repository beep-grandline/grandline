# ═══════════════════════════════════════════════════════════════════════════════
#  npcs.py  ·  NPC data loader and battle helpers.
#  Call load_npcs() in bot.py on_ready alongside load_fruits().
# ═══════════════════════════════════════════════════════════════════════════════

import csv
import random

from fruits import get_fruit_by_id

# ── Style: Rokushiki ──────────────────────────────────────────────────────────

ROKUSHIKI_MOVES = [
    # Tempest Kick
    ("Tempest Kick", "1", "SLASH HEAVY PRECISE"),
    # Finger Pistol
    ("Finger Pistol", "2", "MEDIUM PRECISE HOMING"),
]

ROKUSHIKI_DODGES = ["Paper Art", "Moonwalk", "Shave"]

NPC_CSV_PATH = "data/npcs.csv"
NPCS: list = []

ATTACK_TYPE_MAP = {"1": "slash", "2": "pierce", "": "blunt"}

# Aggro level → AI action weights
AGGRO_WEIGHTS = {
    1: {"attack": 30, "block": 30, "dodge": 22, "charge": 5, "escape": 13},
    2: {"attack": 55, "block": 20, "dodge": 15, "charge": 5, "escape":  5},
    3: {"attack": 78, "block":  9, "dodge":  8, "charge": 5, "escape":  0},
}
DEFAULT_AGGRO = 3

# Neutral initiate affiliation rules: npc affiliation → set of player affiliations it attacks
NEUTRAL_ATTACK_MAP = {
    "m": {"p"},
    "b": {"p"},
}

# ── CSV loader ────────────────────────────────────────────────────────────────

def load_npcs():
    global NPCS
    try:
        with open(NPC_CSV_PATH, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        # strip whitespace from all keys/values and drop rows with no id or name
        cleaned = []
        for row in rows:
            row = {k.strip(): (v.strip() if v else "") for k, v in row.items()}
            if row.get("id") and row.get("name"):
                cleaned.append(row)
        NPCS = cleaned
        print(f"[npcs] loaded {len(NPCS)} NPCs")
    except FileNotFoundError:
        NPCS = []
        print("[npcs] npcs.csv not found — no NPCs loaded")


def get_npc_by_id(npc_id: str):
    for npc in NPCS:
        if npc["id"].strip() == npc_id.strip():
            return npc
    return None


def get_npcs_at(q: int, r: int) -> list:
    """
    Which NPCs are at (q, r) is driven by the map JSON (tile meta `npcs`: a
    list of NPC ids placed in the island editor). Their stats/behaviour still
    come from data/npcs.csv, looked up by id. NPC q/r columns are ignored.
    """
    from map_render import get_tile_meta   # lazy import avoids circular load
    meta = get_tile_meta(q, r) or {}
    out = []
    for npc_id in meta.get("npcs", []):
        npc = get_npc_by_id(str(npc_id))
        if npc:
            out.append(npc)
    return out


# ── Move builder ──────────────────────────────────────────────────────────────
# Reproduces the keyword build logic without importing kit_commands
# to avoid circular dependencies.

# safe — kit_commands doesn't import npcs
from kit_commands import legacy_to_pool, build_pool_move, to_battle_dict


def _build_npc_move(name: str, type_code: str, tags_str: str) -> dict:
    """Parse one NPC move row (type code + old-style tags) into a pool move."""
    attack_type = ATTACK_TYPE_MAP.get(str(type_code).strip(), "blunt")
    tags        = [k.strip().upper() for k in tags_str.split() if k.strip()]

    # Reuse the legacy converter to map the CSV's old keyword tags into pool scores.
    p, a, s, kws, _ = legacy_to_pool({"attack_type": attack_type, "_keywords": tags})
    result = build_pool_move(name, p, a, s, kws)
    return to_battle_dict(result)


# ── Fighter builder ───────────────────────────────────────────────────────────

def build_npc_fighter(npc_row) -> dict:
    """Convert a CSV row into the fighter state dict the battle engine expects."""
    if not isinstance(npc_row, dict):
        npc_row = dict(npc_row)
    moves = []
    for i in range(1, 5):
        name     = (npc_row.get(f"move{i}") or "").strip()
        type_code = (npc_row.get(f"type{i}") or "").strip()
        tags      = (npc_row.get(f"tags{i}") or "").strip()
        if name:
            moves.append(_build_npc_move(name, type_code, tags))

    fruit_id = (npc_row.get("fruit_id") or "").strip()
    type1, type2 = "Normal", "none"
    if fruit_id:
        fruit = get_fruit_by_id(fruit_id)
        if fruit:
            type1 = (fruit.get("type1") or "Normal").strip()
            type2 = (fruit.get("type2") or "none").strip()

    block_name = (npc_row.get("block") or "").strip() or "Block"
    dodge_name = (npc_row.get("dodge") or "").strip() or "Dodge"

    # inject Rokushiki techniques
    style = (npc_row.get("style") or "").strip().lower()
    if style == "rokushiki":
        for r_name, r_type, r_tags in ROKUSHIKI_MOVES:
            if not any(m["name"] == r_name for m in moves):
                moves.append(_build_npc_move(r_name, r_type, r_tags))
        dodge_name = random.choice(ROKUSHIKI_DODGES)

    # inject special moves granted by fruit
    from battle import SPECIAL_MOVES, FRUIT_SPECIALS
    for special_key in FRUIT_SPECIALS.get(fruit_id.lower(), []):
        special_move = SPECIAL_MOVES.get(special_key)
        if special_move and not any(m["name"] == special_move["name"] for m in moves):
            moves.append(special_move)

    return {
        "id":                 f"npc:{npc_row['id'].strip()}",
        "name":               npc_row["name"].strip(),
        "hp":                 int(npc_row.get("hp") or 100),
        "max_hp":             int(npc_row.get("hp") or 100),
        "atk":                int(npc_row.get("atk") or 10),
        "defense":            int(npc_row.get("def") or 10),
        "spd":                int(npc_row.get("spd") or 10),
        "type1":              type1,
        "type2":              type2,
        "block":              block_name,
        "dodge":              dodge_name,
        "moves":              moves,
        "aggro":              int(npc_row.get("aggro") or DEFAULT_AGGRO),
        "initiate":           int(npc_row.get("initiate") or 0),
        "affiliation":        (npc_row.get("affiliation") or "").strip().lower(),
        "charging":           False,
        "priority_next_turn": False,
        "escaped":            False,
    }


# ── NPC AI ────────────────────────────────────────────────────────────────────

def should_npc_initiate(npc_row: dict, player_row) -> bool:
    """
    Returns True if the NPC should initiate combat with the player.
    initiate=0: passive, never initiates.
    initiate=1: neutral, checks affiliation rules.
    initiate=2: aggressive, always initiates.
    """
    if not isinstance(player_row, dict):
        player_row = dict(player_row)
    initiate = int(npc_row.get("initiate") or 0)
    if initiate == 0:
        return False
    if initiate == 2:
        return True
    # neutral (1): check affiliation
    npc_aff    = (npc_row.get("affiliation") or "").strip().lower()
    # player affiliation stored in role column for now — update if you add an affiliation column
    player_aff = (player_row.get("role") or "").strip().lower()
    targets    = NEUTRAL_ATTACK_MAP.get(npc_aff, set())
    return any(t in player_aff for t in targets)


def npc_pick_action(fighter_state: dict) -> list:
    """
    Returns an action list [action, move_name_or_None] for an NPC fighter.
    Uses aggro level (1-3) to determine action weights.
    If already charging, always attack.
    """
    moves = fighter_state.get("moves", [])
    aggro = int(fighter_state.get("aggro") or DEFAULT_AGGRO)
    weights_map = AGGRO_WEIGHTS.get(aggro, AGGRO_WEIGHTS[DEFAULT_AGGRO])

    # charging must release
    if fighter_state.get("charging") and moves:
        return ["attack", random.choice(moves)["name"]]

    choices = list(weights_map.keys())
    weights = list(weights_map.values())
    action  = random.choices(choices, weights=weights, k=1)[0]

    if action == "attack":
        if moves:
            return ["attack", random.choice(moves)["name"]]
        return ["block", None]

    return [action, None]
