# ═══════════════════════════════════════════════════════════════════════════════
#  items.py  ·  Structured item definitions
#
#  ITEM_TYPES  — template for each structured category (what fields/behavior)
#  NAMED_ITEMS — pre-defined items GMs can give by name
#
#  Freeform items (no entry here) still work; they just have no mechanical
#  effect beyond sitting in inventory.
# ═══════════════════════════════════════════════════════════════════════════════

# ── Item type schemas ─────────────────────────────────────────────────────────
# Each type declares its required keyword that triggers it, and what happens.

ITEM_TYPES = {
    "consumable": {
        "trigger_keyword": "consumable",   # item must have this keyword to be /use-able
        "stackable": True,
    },
    "eternal_pose": {
        "trigger_keyword": "eternal",      # matched in _pose_autocomplete
        "stackable": False,
    },
    "weapon": {
        "trigger_keyword": "weapon",
        "stackable": False,
    },
}

# ── Named item registry ───────────────────────────────────────────────────────
# GMs can give these by name via /gm giveitem and fields auto-fill.
# "effect" for consumables: {"heal": N} restores N HP.

NAMED_ITEMS = {
    # ── Consumables ───────────────────────────────────────────────────────────
    "Mega Potion": {
        "keywords":    ["consumable"],
        "description": "Restores 50 HP.",
        "stackable":   True,
        "effect":      {"heal": 50},
    },
    "Potion": {
        "keywords":    ["consumable"],
        "description": "Restores 20 HP.",
        "stackable":   True,
        "effect":      {"heal": 20},
    },
    "Elixir": {
        "keywords":    ["consumable"],
        "description": "Fully restores HP.",
        "stackable":   True,
        "effect":      {"heal": 9999},
    },
    "Rum Flask": {
        "keywords":    ["consumable"],
        "description": "Restores 10 HP. Tastes awful.",
        "stackable":   True,
        "effect":      {"heal": 10},
    },

    # ── Restraints ────────────────────────────────────────────────────────────
    "Sea Prism Cuffs": {
        "keywords":    ["restraint"],
        "description": "Nullifies devil fruit powers when worn.",
        "stackable":   False,
        "effect":      None,
    },

    # ── Misc ──────────────────────────────────────────────────────────────────
    "Treasure Chest": {
        "keywords":    ["treasure"],
        "description": "A chest filled with berry.",
        "stackable":   True,
        "effect":      None,
    },
}


def get_item(name: str):
    """Returns the named item definition, or None."""
    return NAMED_ITEMS.get(name)


def get_consumable_effect(item_dict: dict):
    """
    Given an inventory item dict, return its heal amount or None.
    Checks keywords for 'consumable', then looks up effect from NAMED_ITEMS.
    """
    keywords = [k.lower() for k in item_dict.get("keywords", [])]
    if "consumable" not in keywords:
        return None
    definition = NAMED_ITEMS.get(item_dict.get("name", ""))
    if not definition:
        return None
    return (definition.get("effect") or {}).get("heal")
