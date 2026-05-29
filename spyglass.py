# ═══════════════════════════════════════════════════════════════════════════════
#  spyglass.py  ·  /spyglass command — islands and nearby ships
#
#  pip install pillow numpy requests scipy
#
#  map_render.py — add inside _load_map() after hex_lookup loop:
#      _cache["island_names"] = {}
#      for hex_data in data.get("hexes", []):
#          name = hex_data.get("island_name")
#          if name:
#              _cache["island_names"][(hex_data["q"], hex_data["r"])] = name
#
#  bot.py:
#      from spyglass import spyglass_cmd, load_islands, prerender_all_flags
#      bot.tree.add_command(spyglass_cmd)
#      # in on_ready:
#      load_islands()
#      asyncio.create_task(prerender_all_flags())
#
#  crew_commands.py — when jolly_roger_url is updated:
#      from spyglass import invalidate_flag_cache
#      invalidate_flag_cache(old_url)
# ═══════════════════════════════════════════════════════════════════════════════

import csv
import math
import os
import hashlib
import asyncio
import requests
import numpy as np
import discord

from io import BytesIO
from PIL import Image, ImageFilter
from scipy.ndimage import map_coordinates, binary_dilation

import db
import game
from config import GUILD_ID

# ── Spyglass constants ────────────────────────────────────────────────────────

ISLANDS_CSV      = "data/islands.csv"
SPYGLASS_OVERLAY = "img/spyglass.png"
SPYGLASS_RANGE   = 7
CACHE_DIR        = "data/spyglass_cache"

FISHEYE_STR      = 0.2
FISHEYE_POWER    = 3
CHROMA_SHIFT     = 6
GRAIN_STR        = 3

# ── Flag rendering constants (relative to spyglass overlay size) ──────────────
# NOTE: overlay is 630×441. Anchor is lower-left corner of the flag in pixels.
# ANCHOR_Y is clamped to overlay height automatically.
# Re-tune these against your actual overlay dimensions.

FLAG_SCALE      = 0.17   # flag height as fraction of overlay height
FLAG_ANCHOR_X   = 486
FLAG_ANCHOR_Y   = 585
FLAG_DARKEN     = 0.9
FLAG_OUTLINE    = 1
FLAG_ROTATION   = -5
WAVE_AMP        = 4
WAVE_FREQ       = 2
WAVE_SPEED      = 3
WAVE_SECONDARY  = 0.3
PERSP_TOP       = 10
PERSP_BOT       = 6
POLE_INDENT     = 18
POLE_FREQ       = 1.0
POLE_FALLOFF    = 2.0

_SIZE   = 30
_SQRT3  = math.sqrt(3)

_island_urls: dict = {}
_overlay_cache     = None


# ── CSV / overlay loaders ─────────────────────────────────────────────────────

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



_ship_bg_cache = None


def _get_overlay():
    global _overlay_cache
    if _overlay_cache is None:
        _overlay_cache = Image.open(SPYGLASS_OVERLAY).convert("RGBA")
    return _overlay_cache


def _get_ship_bg():
    global _ship_bg_cache
    if _ship_bg_cache is None:
        try:
            _ship_bg_cache = Image.open("img/ship_bg.png").convert("RGBA")
        except Exception as e:
            print(f"[spyglass] failed to load img/ship_bg.png: {e}")
    if _ship_bg_cache:
        return _ship_bg_cache.copy()
    return Image.new("RGBA", (1208, 716), (20, 40, 65, 255))


# ── Hex helpers ───────────────────────────────────────────────────────────────

def _hex_to_pixel(q, r):
    return (_SIZE * _SQRT3 * (q + r / 2), _SIZE * 1.5 * r)


def _clock_hour(from_q, from_r, to_q, to_r):
    px1, py1 = _hex_to_pixel(from_q, from_r)
    px2, py2 = _hex_to_pixel(to_q,   to_r)
    angle         = math.degrees(math.atan2(py2 - py1, px2 - px1))
    cw_from_north = (90 - angle) % 360
    hour          = round(cw_from_north / 30) % 12
    return hour if hour != 0 else 12


def _get_island_sightings(player_q, player_r):
    from map_render import _cache, _load_map
    _load_map()
    hex_lookup   = _cache.get("hex_lookup",   {})
    island_names = _cache.get("island_names", {})
    buckets = {}
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
        cq   = sum(h[0] for h in hexes) / len(hexes)
        cr   = sum(h[1] for h in hexes) / len(hexes)
        hour = _clock_hour(player_q, player_r, cq, cr)
        results.append((name, hour))
    results.sort(key=lambda x: x[1])
    return results


def _get_ship_sightings(player_q, player_r, player_crew_id):
    results = []
    for crew in db.get_all_crews():
        if crew["id"] == player_crew_id:
            continue
        cq   = crew["q"] or 0
        cr   = crew["r"] or 0
        dist = game._hex_dist(player_q, player_r, cq, cr)
        if dist <= SPYGLASS_RANGE:
            hour = _clock_hour(player_q, player_r, cq, cr)
            results.append((crew, hour))
    results.sort(key=lambda x: x[1])
    return results


# ── Spyglass image pipeline ───────────────────────────────────────────────────

def _fisheye(img):
    arr          = np.array(img, dtype=np.float32)
    h, w         = arr.shape[:2]
    y_idx, x_idx = np.mgrid[0:h, 0:w].astype(np.float32)
    xn = (x_idx - w / 2) / (w / 2)
    yn = (y_idx - h / 2) / (h / 2)
    r  = np.sqrt(xn**2 + yn**2)
    factor = 1 + FISHEYE_STR * r**FISHEYE_POWER
    xd = np.clip((xn / factor + 1) / 2 * (w - 1), 0, w - 1)
    yd = np.clip((yn / factor + 1) / 2 * (h - 1), 0, h - 1)
    x0 = np.floor(xd).astype(int);  y0 = np.floor(yd).astype(int)
    x1 = np.clip(x0 + 1, 0, w - 1); y1 = np.clip(y0 + 1, 0, h - 1)
    wx = (xd - x0)[..., np.newaxis]; wy = (yd - y0)[..., np.newaxis]
    out = (arr[y0,x0]*(1-wx)*(1-wy) + arr[y0,x1]*wx*(1-wy) +
           arr[y1,x0]*(1-wx)*wy     + arr[y1,x1]*wx*wy)
    return Image.fromarray(out.astype(np.uint8))


def _chromatic_aberration(img):
    if CHROMA_SHIFT == 0:
        return img
    arr = np.array(img).astype(np.float32)
    h, w = arr.shape[:2]
    cx, cy = w / 2, h / 2
    out = arr.copy()
    for ch, direction in [(0, CHROMA_SHIFT), (2, -CHROMA_SHIFT)]:
        y_idx, x_idx = np.mgrid[0:h, 0:w].astype(np.float32)
        xn = (x_idx - cx) / cx
        yn = (y_idx - cy) / cy
        r  = np.sqrt(xn**2 + yn**2)
        xd = np.clip(x_idx + xn * r * direction, 0, w - 1)
        yd = np.clip(y_idx + yn * r * direction, 0, h - 1)
        out[..., ch] = map_coordinates(arr[..., ch], [yd.ravel(), xd.ravel()], order=1).reshape(h, w)
    return Image.fromarray(out.astype(np.uint8))


def _film_grain(img):
    if GRAIN_STR == 0:
        return img
    arr   = np.array(img).astype(np.float32)
    noise = np.random.normal(0, GRAIN_STR, arr.shape[:2])
    for ch in range(3):
        arr[..., ch] = np.clip(arr[..., ch] + noise, 0, 255)
    return Image.fromarray(arr.astype(np.uint8))


def _apply_spyglass_pipeline(bg):
    """Scale → fisheye → crop → chroma → grain → overlay."""
    overlay = _get_overlay()
    ow, oh  = overlay.size
    scale   = 1.0 + FISHEYE_STR * 0.1
    tw, th  = int(ow * scale), int(oh * scale)

    bg_ratio = bg.width / bg.height
    tg_ratio = tw / th
    if bg_ratio > tg_ratio:
        new_h = th; new_w = int(bg.width * (th / bg.height))
    else:
        new_w = tw; new_h = int(bg.height * (tw / bg.width))

    bg = bg.resize((new_w, new_h), Image.LANCZOS)
    cx = (new_w - tw) // 2;  cy = (new_h - th) // 2
    bg = bg.crop((cx, cy, cx + tw, cy + th))

    bg_dist = _fisheye(bg)
    left = (bg_dist.width  - ow) // 2
    top  = (bg_dist.height - oh) // 2
    bg_dist = bg_dist.crop((left, top, left + ow, top + oh))

    bg_dist = _chromatic_aberration(bg_dist)
    bg_dist = _film_grain(bg_dist)

    result = bg_dist.convert("RGBA")
    result.paste(overlay, (0, 0), overlay)
    return result


# ── Flag pipeline ─────────────────────────────────────────────────────────────

def _apply_flag_warps(img):
    arr          = np.array(img).astype(np.float32)
    h, w         = arr.shape[:2]
    y_idx, x_idx = np.mgrid[0:h, 0:w].astype(np.float32)
    y_norm       = y_idx / h
    x_norm       = x_idx / w

    y_shift  = WAVE_AMP * np.sin(2 * np.pi * WAVE_FREQ * x_idx / w + WAVE_SPEED)
    x_shift  = WAVE_AMP * WAVE_SECONDARY * np.sin(2 * np.pi * WAVE_FREQ * y_idx / h + WAVE_SPEED * 0.7)
    arch     = np.sin(np.pi * y_norm * POLE_FREQ) ** 2
    fade     = (1.0 - x_norm) ** POLE_FALLOFF
    x_shift += POLE_INDENT * arch * fade
    y_shift += (1.0 - x_norm) * (PERSP_TOP * (1 - y_norm) - PERSP_BOT * y_norm)

    coords = [(y_idx - y_shift).ravel(), (x_idx - x_shift).ravel()]
    out    = np.zeros_like(arr)
    for c in range(4):
        out[..., c] = map_coordinates(arr[..., c], coords, order=1, mode='constant', cval=0).reshape(h, w)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def _darken_flag(img, factor):
    if factor == 1.0:
        return img
    arr          = np.array(img).astype(np.float32)
    arr[..., :3] = np.clip(arr[..., :3] * factor, 0, 255)
    return Image.fromarray(arr.astype(np.uint8))


def _outline_flag(img, thickness):
    if thickness == 0:
        return img
    arr      = np.array(img.convert("RGBA"))
    mask     = arr[..., 3] > 128
    expanded = binary_dilation(mask, iterations=thickness)
    border   = expanded & ~mask
    out      = arr.copy()
    out[~mask & (arr[..., 3] > 0), 3] = 0
    out[border] = [0, 0, 0, 255]
    return Image.fromarray(out)


def _build_flag_image(jolly_roger_url):
    """Renders flag onto full-size sea background. Pipeline resizes to overlay later."""
    try:
        r    = requests.get(jolly_roger_url, timeout=10)
        r.raise_for_status()
        flag = Image.open(BytesIO(r.content)).convert("RGBA")
    except Exception as e:
        print(f"[spyglass] failed to load flag: {e}")
        return None

    # use full-size background — anchor coords tuned for this resolution
    bg     = _get_ship_bg()
    bw, bh = bg.size

    fh   = max(1, int(bh * FLAG_SCALE))
    fw   = max(1, int(flag.width * (fh / flag.height)))
    flag = flag.resize((fw, fh), Image.LANCZOS)

    pad    = int(max(WAVE_AMP, PERSP_TOP, PERSP_BOT, POLE_INDENT) * 3 + 8)
    padded = Image.new("RGBA", (fw + pad*2, fh + pad*2), (0, 0, 0, 0))
    padded.paste(flag, (pad, pad))
    flag   = padded

    flag = _apply_flag_warps(flag)
    flag = _darken_flag(flag, FLAG_DARKEN)
    flag = _outline_flag(flag, FLAG_OUTLINE)
    if FLAG_ROTATION != 0:
        flag = flag.rotate(FLAG_ROTATION, resample=Image.BILINEAR, expand=True)

    ax = min(FLAG_ANCHOR_X, bw - 1)
    ay = min(FLAG_ANCHOR_Y, bh) - flag.height
    bg.paste(flag, (ax, ay), flag)
    return bg


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _island_cache_path(island_name):
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in island_name).strip()
    return os.path.join(CACHE_DIR, f"island_{safe}.png")


def _flag_cache_path(jolly_roger_url):
    h = hashlib.sha256(jolly_roger_url.encode()).hexdigest()[:16]
    return os.path.join(CACHE_DIR, f"flag_{h}.png")


def invalidate_flag_cache(old_url):
    """Call from crew_commands when jolly_roger_url is updated."""
    if not old_url:
        return
    path = _flag_cache_path(old_url)
    if os.path.exists(path):
        os.remove(path)
        print(f"[spyglass] invalidated flag cache: {os.path.basename(path)}")


# ── Sync render functions ─────────────────────────────────────────────────────

def _render_island_sync(island_name):
    url = _island_urls.get(island_name, "")
    if not url:
        return None

    cached = _island_cache_path(island_name)
    if os.path.exists(cached):
        with open(cached, "rb") as f:
            return BytesIO(f.read())

    try:
        r  = requests.get(url, timeout=10)
        r.raise_for_status()
        bg = Image.open(BytesIO(r.content)).convert("RGBA")
    except Exception as e:
        print(f"[spyglass] failed to load island {island_name}: {e}")
        return None

    result = _apply_spyglass_pipeline(bg)

    os.makedirs(CACHE_DIR, exist_ok=True)
    result.convert("RGB").save(cached, format="PNG")

    out = BytesIO()
    result.convert("RGB").save(out, format="PNG")
    out.seek(0)
    return out


def _render_flag_sync(jolly_roger_url):
    if not jolly_roger_url:
        bg     = _get_ship_bg()
        result = _apply_spyglass_pipeline(bg)
        out = BytesIO()
        result.convert("RGB").save(out, format="PNG")
        out.seek(0)
        return out

    cached = _flag_cache_path(jolly_roger_url)
    if os.path.exists(cached):
        with open(cached, "rb") as f:
            return BytesIO(f.read())

    bg = _build_flag_image(jolly_roger_url)
    if bg is None:
        return None

    result = _apply_spyglass_pipeline(bg)

    os.makedirs(CACHE_DIR, exist_ok=True)
    result.convert("RGB").save(cached, format="PNG")

    out = BytesIO()
    result.convert("RGB").save(out, format="PNG")
    out.seek(0)
    return out


# ── Async wrappers ────────────────────────────────────────────────────────────

async def render_spyglass(island_name):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _render_island_sync, island_name)


async def render_flag_spyglass(jolly_roger_url):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _render_flag_sync, jolly_roger_url)


async def prerender_all_flags():
    """Pre-renders all crew jolly rogers at startup. Skips already-cached."""
    crews   = db.get_all_crews()
    pending = [
        c for c in crews
        if (c["jolly_roger_url"] or "").strip()
        and not os.path.exists(_flag_cache_path((c["jolly_roger_url"] or "").strip()))
    ]
    if not pending:
        return
    print(f"[spyglass] pre-rendering {len(pending)} crew flags...")
    loop = asyncio.get_event_loop()
    for crew in pending:
        await loop.run_in_executor(None, _render_flag_sync, crew["jolly_roger_url"].strip())
    print(f"[spyglass] pre-render done")


# ── Autocomplete ──────────────────────────────────────────────────────────────

async def _spyglass_autocomplete(interaction: discord.Interaction, current: str):
    uid    = str(interaction.user.id)
    player = db.get_player(uid)
    if not player:
        return []

    q, r    = game.get_position(uid)
    choices = []

    for name, hour in _get_island_sightings(q, r):
        choices.append(discord.app_commands.Choice(
            name=f"⚓ {hour} o'clock", value=name
        ))

    crew_id = player["crew_id"]
    for crew, hour in _get_ship_sightings(q, r, crew_id):
        choices.append(discord.app_commands.Choice(
            name=f"🏴 {hour} o'clock", value=f"ship:{crew['id']}"
        ))

    return choices[:25]


# ── /spyglass ─────────────────────────────────────────────────────────────────

@discord.app_commands.command(
    name="spyglass",
    description="Peer through the spyglass to scout nearby islands and ships",
)
@discord.app_commands.describe(target="Direction to look (select from list)")
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
    if _cache.get("hex_lookup", {}).get((q, r), "sea") != "sea":
        await interaction.response.send_message(
            "The spyglass only works at sea.", ephemeral=True
        )
        return

    await interaction.response.defer()

    if target.startswith("ship:"):
        crew_id = target[5:]
        crew    = db.get_crew(crew_id)
        if not crew:
            await interaction.followup.send("Ship not found.", ephemeral=True)
            return
        url        = (crew["jolly_roger_url"] or "").strip()
        image_data = await render_flag_spyglass(url)
    else:
        image_data = await render_spyglass(target)

    if not image_data:
        await interaction.followup.send(
            "Couldn't load the image for that target.", ephemeral=True
        )
        return

    file  = discord.File(image_data, filename="spyglass.png")
    embed = discord.Embed(color=0x0a1a2e)
    embed.set_image(url="attachment://spyglass.png")
    await interaction.followup.send(embed=embed, file=file)
