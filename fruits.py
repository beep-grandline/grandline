# ═══════════════════════════════════════════════════════════════════════════════
#  fruits.py  ·  Shared devil fruit data
#  Import this everywhere instead of loading the CSV in bot.py.
#  In bot.py: remove the FRUITS list, load_fruits(), get_fruit_by_id(),
#             and fruit_autocomplete() — replace with:
#                 from fruits import FRUITS, get_fruit_by_id, fruit_autocomplete
# ═══════════════════════════════════════════════════════════════════════════════

import csv
import discord

FRUITS = []


def load_fruits():
    global FRUITS
    try:
        with open("data/fruits.csv", encoding="utf-8") as f:
            FRUITS = [row for row in csv.DictReader(f) if row.get("id")]
        print(f"Loaded {len(FRUITS)} devil fruits.")
    except FileNotFoundError:
        print("Warning: data/fruits.csv not found.")


def get_fruit_by_id(fruit_id):
    return next((f for f in FRUITS if f["id"] == fruit_id), None)


def get_fighter_types(fruit_id):
    """
    Returns (type1, type2) from the fruit's CSV columns.
    Falls back to Normal / none for players without a fruit.
    """
    if not fruit_id:
        return "Normal", "none"
    fruit = get_fruit_by_id(fruit_id)
    if not fruit:
        return "Normal", "none"
    return (fruit.get("type1") or "Normal"), (fruit.get("type2") or "none")


async def fruit_autocomplete(interaction: discord.Interaction, current: str):
    try:
        current = current.lower().strip()
        matches = []
        seen    = set()
        for f in FRUITS:
            eng = (f.get("eng") or "").strip()
            jap = (f.get("jap") or "").strip()
            fid = f.get("id", "")
            if fid in seen:
                continue
            if current in eng.lower() or current in jap.lower():
                seen.add(fid)
                matches.append(discord.app_commands.Choice(name=jap[:100], value=fid))
        return matches[:25]
    except (discord.NotFound, Exception):
        return []


load_fruits()
