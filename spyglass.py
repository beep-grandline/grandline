# ═══════════════════════════════════════════════════════════════════════════════
#  spyglass.py  ·  /spyglass command
#
#  Requires:
#    pip install pillow numpy requests
#
#  In map_render.py, add to _load_map() after building hex_lookup:
#
#      _cache["island_names"] = {}
#      for hex_data in data.get("hexes", []):
#          name = hex_data.get("island_name")
#          if name:
#              q = hex_data["q"]
#              r = hex_data["r"]
#              _cache["island_names"][(q, r)] = name
#
#  In bot.py:
#      from spyglass import spyglass_cmd, load_islands
#      bot.tree.add_command(spyglass_cmd)
#      # in on_ready:
#      load_islands()
# ═══════════════════════════════════════════════════════════════════════════════

import csv
import math
import asyncio
import requests
import numpy as np
import discord

from io import BytesIO
from PIL import Image

import db
import game
from config import GUILD_ID

ISLANDS_CSV      = "data/islands.csv"
SPYGLASS_OVERLAY = "img/spyglass.png"
SPYGLASS_RANGE   = 7
FISHEYE_STR      = 0.3

_SIZE   = 30          # must match SIZE in map_render.py
_SQRT3  = math.sqrt(3)

_island_urls: dict = {}   # island_name → url
_overlay_cache      = None # loaded once


# ── CSV loader ────────────────────────────────────────────────────────────────

def load_islands():
    global _island_urls
    try:
        with open(ISLANDS_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                name = (row.get("island") or "").strip()
                url  = (row.get("url")    or "").strip()
                if name:
                    _island_urls[name] = url
        print(f"[spyglass] loaded {len(_island_urls)} island entries")
    except FileNotFoundError:
        print("[spyglass] data/islands.csv not found")


def _get_overlay() -> Image.Image:
    global _overlay_cache
    if _overlay_cache is None:
        _overlay_cache = Image.open(SPYGLASS_OVERLAY).convert("RGBA")
    return _overlay_cache


# ── Hex / pixel helpers ───────────────────────────────────────────────────────

def _hex_to_pixel(q, r):
    """Pointy-top axial → pixel centre. Must match map_render._hex_to_pixel."""
    return (
        _SIZE * _SQRT3 * (q + r / 2),
        _SIZE * 1.5   * r,
    )


def _clock_hour(from_q, from_r, to_q, to_r) -> int:
    """Returns clock hour (1-12) from one hex position toward another."""
    px1, py1 = _hex_to_pixel(from_q, from_r)
    px2, py2 = _hex_to_pixel(to_q,   to_r)
    angle    = math.degrees(math.atan2(py2 - py1, px2 - px1))
    # in matplotlib y-up: angle=90 is north
    cw_from_north = (90 - angle) % 360
    hour = round(cw_from_north / 30) % 12
    return hour if hour != 0 else 12


def _get_island_sightings(player_q: int, player_r: int) -> list:
    """
    Scans within SPYGLASS_RANGE tiles for island hexes.
    Groups by island_name, computes centroid, returns:
    [(island_name, clock_hour), ...]  sorted by clock hour.
    """
    from map_render import _cache, _load_map
    _load_map()
    hex_lookup    = _cache.get("hex_lookup",    {})
    island_names  = _cache.get("island_names",  {})

    buckets: dict = {}   # island_name → list of (q, r)

    for dq in range(-SPYGLASS_RANGE, SPYGLASS_RANGE + 1):
        for dr in range(-SPYGLASS_RANGE, SPYGLASS_RANGE + 1):
            nq, nr = player_q + dq, player_r + dr
            if game._hex_dist(player_q, player_r, nq, nr) > SPYGLASS_RANGE:
                continue
            if hex_lookup.get((nq, nr)) == "island":
                name = island_names.get((nq, nr))
                if name:
                    buckets.setdefault(name, []).append((nq, nr))

    results = []
    for name, hexes in buckets.items():
        cq = sum(h[0] for h in hexes) / len(hexes)
        cr = sum(h[1] for h in hexes) / len(hexes)
        hour = _clock_hour(player_q, player_r, cq, cr)
        results.append((name, hour))

    results.sort(key=lambda x: x[1])
    return results


# ── Image rendering ───────────────────────────────────────────────────────────

def _fisheye(img: Image.Image, strength: float = FISHEYE_STR) -> Image.Image:
    """Barrel / fisheye distortion using r**3 falloff. Pure numpy."""
    arr = np.array(img, dtype=np.float32)
    h, w = arr.shape[:2]

    y_idx, x_idx = np.mgrid[0:h, 0:w].astype(np.float32)
    xn = (x_idx - w / 2) / (w / 2)
    yn = (y_idx - h / 2) / (h / 2)
    r  = np.sqrt(xn**2 + yn**2)

    factor = 1 + strength * r**3
    xd = np.clip((xn / factor + 1) / 2 * (w - 1), 0, w - 1)
    yd = np.clip((yn / factor + 1) / 2 * (h - 1), 0, h - 1)

    x0 = np.floor(xd).astype(int)
    y0 = np.floor(yd).astype(int)
    x1 = np.clip(x0 + 1, 0, w - 1)
    y1 = np.clip(y0 + 1, 0, h - 1)

    wx = (xd - x0)[..., np.newaxis]
    wy = (yd - y0)[..., np.newaxis]

    out = (arr[y0, x0] * (1-wx) * (1-wy) +
           arr[y0, x1] * wx     * (1-wy) +
           arr[y1, x0] * (1-wx) * wy     +
           arr[y1, x1] * wx     * wy)

    return Image.fromarray(out.astype(np.uint8))


def _render_sync(island_name: str) -> BytesIO | None:
    """Blocking render — run in executor."""
    url = _island_urls.get(island_name, "")
    if not url:
        return None

    try:
        r  = requests.get(url, timeout=10)
        r.raise_for_status()
        bg = Image.open(BytesIO(r.content)).convert("RGBA")
    except Exception as e:
        print(f"[spyglass] failed to load bg for {island_name}: {e}")
        return None

    overlay = _get_overlay()
    bg      = bg.resize(overlay.size, Image.LANCZOS)
    bg_dist = _fisheye(bg)

    result = bg_dist.convert("RGBA")
    result.paste(overlay, (0, 0), overlay)

    out = BytesIO()
    result.convert("RGB").save(out, format="PNG")
    out.seek(0)
    return out


async def render_spyglass(island_name: str) -> BytesIO | None:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _render_sync, island_name)


# ── Autocomplete ──────────────────────────────────────────────────────────────

async def _spyglass_autocomplete(interaction: discord.Interaction, current: str):
    uid    = str(interaction.user.id)
    player = db.get_player(uid)
    if not player:
        return []

    q, r      = game.get_position(uid)
    sightings = _get_island_sightings(q, r)

    return [
        discord.app_commands.Choice(
            name=f"⚓ {hour} o'clock",
            value=name,
        )
        for name, hour in sightings
        if not current or current.lower() in f"{hour}"
    ][:25]


# ── /spyglass ─────────────────────────────────────────────────────────────────

@discord.app_commands.command(
    name="spyglass",
    description="Peer through the spyglass to scout nearby islands",
)
@discord.app_commands.describe(target="Direction to look (select from the list)")
@discord.app_commands.autocomplete(target=_spyglass_autocomplete)
@discord.app_commands.guilds(GUILD_ID)
async def spyglass_cmd(interaction: discord.Interaction, target: str):
    uid    = str(interaction.user.id)
    player = db.get_player(uid)

    if not player:
        await interaction.response.send_message("Register first.", ephemeral=True)
        return

    if player["following_id"] != "ship":
        await interaction.response.send_message(
            "You need to be on the ship to use the spyglass.", ephemeral=True
        )
        return

    q, r = game.get_position(uid)

    from map_render import _cache, _load_map
    _load_map()
    terrain = _cache.get("hex_lookup", {}).get((q, r), "sea")
    if terrain != "sea":
        await interaction.response.send_message(
            "The spyglass only works at sea.", ephemeral=True
        )
        return

    await interaction.response.defer()

    image_data = await render_spyglass(target)
    if not image_data:
        await interaction.followup.send(
            "Couldn't load the image for that island.", ephemeral=True
        )
        return

    file  = discord.File(image_data, filename="spyglass.png")
    embed = discord.Embed(color=0x0a1a2e)
    embed.set_image(url="attachment://spyglass.png")
    await interaction.followup.send(embed=embed, file=file)
