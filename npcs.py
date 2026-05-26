# ═══════════════════════════════════════════════════════════════════════════════
#  npcs.py  ·  NPC data loader and battle helpers.
#  Call load_npcs() in bot.py on_ready alongside load_fruits().
# ═══════════════════════════════════════════════════════════════════════════════

import csv
import random

from fruits import get_fruit_by_id

NPC_CSV_PATH = "data/npcs.csv"
NPCS: list = []

POWER_SCALE = 9   # must match kit_commands.POWER_SCALE

ATTACK_TYPE_MAP = {"1": "slash", "2": "pierce", "": "blunt"}

# AI action weights
_AI_WEIGHTS = {"attack": 60, "block": 20, "dodge": 15, "charge": 5}

# ── CSV loader ────────────────────────────────────────────────────────────────

def load_npcs():
    global NPCS
    try:
        with open(NPC_CSV_PATH, newline="", encoding="utf-8") as f:
            NPCS = list(csv.DictReader(f))
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
    out = []
    for npc in NPCS:
        try:
            if int(npc.get("q", 0)) == q and int(npc.get("r", 0)) == r:
                out.append(npc)
        except (ValueError, TypeError):
            continue
    return out


# ── Move builder ──────────────────────────────────────────────────────────────
# Reproduces the keyword build logic without importing kit_commands
# to avoid circular dependencies.

from kit_commands import _build_move   # safe — kit_commands doesn't import npcs


def _build_npc_move(name: str, type_code: str, tags_str: str) -> dict:
    """Parse one NPC move row into a battle-ready move dict."""
    attack_type = ATTACK_TYPE_MAP.get(str(type_code).strip(), "blunt")
    keywords    = [k.strip().upper() for k in tags_str.split() if k.strip()]

    result = _build_move(name, attack_type, keywords)
    s      = result["stats"]

    return {
        "name":        name,
        "power":       s["power"] * POWER_SCALE,
        "accuracy":    s["accuracy"],
        "priority":    s["priority"],
        "tracking":    s["tracking"],
        "hits":        s["hits"],
        "hp_cost":     s["hp_cost"],
        "recoil":      s["recoil"],
        "attack_type": attack_type,
        "_keywords":   keywords,
    }


# ── Fighter builder ───────────────────────────────────────────────────────────

def build_npc_fighter(npc_row: dict) -> dict:
    """Convert a CSV row into the fighter state dict the battle engine expects."""
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

    print(f"[npc] {npc_row['name']} moves: {[m['name'] for m in moves]}")
    
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
        "charging":           False,
        "priority_next_turn": False,
        "escaped":            False,
    }


# ── NPC AI ────────────────────────────────────────────────────────────────────

def npc_pick_action(fighter_state: dict) -> list:
    """
    Returns an action list [action, move_name_or_None] for an NPC fighter.
    Weights: attack 60%, block 20%, dodge 15%, charge 5%.
    If already charging, always attack.
    """
    moves = fighter_state.get("moves", [])

    # if charging, must release — attack
    if fighter_state.get("charging") and moves:
        return ["attack", random.choice(moves)["name"]]

    choices = list(_AI_WEIGHTS.keys())
    weights = list(_AI_WEIGHTS.values())
    action  = random.choices(choices, weights=weights, k=1)[0]

    if action == "attack":
        if moves:
            return ["attack", random.choice(moves)["name"]]
        return ["block", None]   # no moves fallback

    return [action, None]
