import io
import json
import math
import os
from functools import lru_cache

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from matplotlib.collections import PatchCollection, LineCollection
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.image import imread
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
from scipy.interpolate import griddata
from scipy.ndimage import gaussian_filter
from scipy.spatial import cKDTree
import gc


import game
import islands as islands_mod

matplotlib.use("Agg")  


# ── Constants ─────────────────────────────────────────────────────────────────

MAP_PATH = "map.json"   # path to the exported editor JSON

SQRT3 = math.sqrt(3)
SIZE  = 3.0             # hex radius in data units

TERRAIN_COLORS = {
    # "island":    "#c4f5d7",
    "island":    "#f2e6d6",
    "redline":   "#c7706b",
    "calm_belt": "#76b8d4",
    # fallback for anything else
    "sea":       "#75e1ff",
}

# BORDER_COLOR     = "#f0f8ff"
BORDER_COLOR     = "#63584a"
BORDER_WIDTH     = 1.5   # land-sea edge thickness
SEA_GRID_WIDTH   = 1.5   # sea-sea grid line thickness
PLAYER_COLOR     = "#F0D060"
LABEL_COLOR      = "#171717"
SEA_COLOR        = TERRAIN_COLORS["sea"]
# Plain white page background — replaces the ocean texture fill.
BACKGROUND_COLOR = "#ffffff"

# Calm belt — any hex where abs(r) > game.CALM_BELT_R is treated as impassable
# calm belt regardless of what the JSON says. The JSON calm_belt terrain type
# is ignored. Read game.CALM_BELT_R live (not copied) since it's recomputed
# by game.set_calm_belt_bounds() on startup, after this module is imported.

# The old ±36 latitude band predates the island-editor coordinate system,
# where islands are placed at arbitrary (q, r). With it enabled, render_map
# would skip every island tile beyond that band as "calm belt", hiding them
# entirely (while the ocean texture still shaded around them). Disabled until
# the calm belt is redefined in the new coordinate space.
CALM_BELT_ENABLED = False

# Impel Down — reserved special hex rendered gray
IMPEL_DOWN = (180, 0)
IMPEL_DOWN_COLOR = "#5a5a6a"

# ── Marine facilities — gray hexes rendered with the normal island logic ──────
# Centers here are mirrored in islands.py (SPECIAL_ISLANDS) so marines can
# navigate to them. Edit tiles in one place; keep islands.py centers in sync.
GRAY_HEX_COLOR = "#9a9aa3"

MARINE_SHIP_START = (228, -20)   # where /marine sail commissions a battleship

# Marineford forms a crescent: 5 of the 6 tiles surrounding the ship start
# (the sixth is left open so the ring reads as a crescent).
_MF_DIRS = [(1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1)]
MARINEFORD_TILES = [
    (MARINE_SHIP_START[0] + dq, MARINE_SHIP_START[1] + dr)
    for dq, dr in _MF_DIRS[:5]
]

GRAY_FACILITIES = {
    "Marine Base G8": [(50, 11)],
    "Marine Base G6": [(111, -25)],
    "Marineford":     MARINEFORD_TILES,
}

# Flat lookup set of every gray facility tile
GRAY_HEXES = {tile for tiles in GRAY_FACILITIES.values() for tile in tiles}

# Calm belt overlay — translucent white drawn above the sea texture
CALM_BELT_COLOR = (1.0, 1.0, 1.0, 0.38)

# Player ship icon — loaded once, falls back to dot if file missing.
# SHIP_ROTATION: number of 90° counter-clockwise turns (1=90°, 2=180°, 3=270°)
SHIP_ROTATION  = 3  # 3 × 90° CCW = 270° CCW = 90° clockwise
SHIP_ICON_SIZE = 28   # display size in pixels — tweak to taste

_SHIP_ICON = None
_SHIP_ICON_RAW = None

def _get_ship_icon():
    global _SHIP_ICON
    if _SHIP_ICON is None:
        try:
            img = imread("img/boat.png")
            if SHIP_ROTATION:
                img = np.rot90(img, k=SHIP_ROTATION)
            _SHIP_ICON = img
        except FileNotFoundError:
            pass
    return _SHIP_ICON


def _get_other_ship_icon():
    """Ship icon for other crews — random 90° rotation each render."""
    import random
    global _SHIP_ICON_RAW
    if _SHIP_ICON_RAW is None:
        try:
            _SHIP_ICON_RAW = imread("img/boat.png")
        except FileNotFoundError:
            return None
    return np.rot90(_SHIP_ICON_RAW, k=random.randint(0, 3))

# Edge index pairs for each axial neighbour direction (flat-top orientation)
HEX_DIRS = [(1,0),(-1,0),(0,1),(0,-1),(1,-1),(-1,1)]

NEIGHBOR_TO_EDGE = {
    ( 1,  0): (0, 1),
    ( 0,  1): (1, 2),
    (-1,  1): (2, 3),
    (-1,  0): (3, 4),
    ( 0, -1): (4, 5),
    ( 1, -1): (5, 0),
}

# ── Map data cache ────────────────────────────────────────────────────────────
# Reload from disk only when the file's mtime changes.

_cache = {
    "mtime":      None,
    "hex_lookup": {},   # (q, r) -> hex_type string ("island")
    "labels":     {},   # (q, r) -> hex_label string (per-hex labels only)
    "island_names": {}, # (q, r) -> island_name string
    "origins":    {},   # island_name -> (q, r) origin or None
    "tile_meta":  {},   # (q, r) -> per-tile meta dict (npcs, dialogue, buildings, …)
    "islands":    [],   # [ {name, oq, orr, radius, tiles:set((q,r))} ] for broad-phase
}


def _load_map():
    """
    Load map JSON into module-level cache. No-op if file unchanged.

    Expects the island-editor compact format:
      {
        "islands": {
          "<name>": {
            "origin": {"q":..,"r":..},
            "radius": int,
            "hexes":  [[dq,dr], ...],         # offsets from origin
            "elev":   [int, ...],             # parallel to hexes; used by the topography view
            "meta":   {"dq,dr": {...}, ...}   # sparse per-tile metadata
          }
        }
      }

    Note: marine facilities / Impel Down are hardcoded constants in this module,
    not part of map.json, so they are unaffected by this loader.
    """
    try:
        mtime = os.path.getmtime(MAP_PATH)
    except FileNotFoundError:
        return

    if mtime == _cache["mtime"]:
        return

    with open(MAP_PATH, "r") as f:
        data = json.load(f)

    hex_lookup   = {}   # (q,r) -> "island"   (global; used by game passability)
    labels       = {}   # (q,r) -> hex_label
    island_names = {}   # (q,r) -> name
    origins      = {}   # name  -> (q,r)
    tile_meta    = {}   # (q,r) -> meta dict
    islands      = []   # per-island broad-phase index

    for name, isl in data.get("islands", {}).items():
        if not isinstance(isl, dict):
            continue
        o = isl.get("origin") or {}
        oq, orr = o.get("q"), o.get("r")
        if oq is None or orr is None:
            continue
        origins[name] = (oq, orr)

        hexes = isl.get("hexes", []) or []
        elevs = isl.get("elev", []) or []
        meta  = isl.get("meta", {}) or {}
        tiles = set()
        elev  = {}
        max_d = 0

        for i, (dq, dr) in enumerate(hexes):
            q, r = oq + dq, orr + dr
            hex_lookup[(q, r)]   = "island"
            island_names[(q, r)] = name
            tiles.add((q, r))
            elev[(q, r)] = elevs[i] if i < len(elevs) else 0
            d = max(abs(dq), abs(dr), abs(dq + dr))
            if d > max_d:
                max_d = d

            m = meta.get("%d,%d" % (dq, dr))
            if m:
                tile_meta[(q, r)] = m
                if m.get("hex_label"):
                    labels[(q, r)] = m["hex_label"]

        radius = isl.get("radius")
        if not isinstance(radius, int):
            radius = max_d

        islands.append({
            "name":   name,
            "oq":     oq,
            "orr":    orr,
            "radius": radius,
            "tiles":  tiles,
            "elev":   elev,
        })

    _cache["mtime"]        = mtime
    _cache["hex_lookup"]   = hex_lookup
    _cache["labels"]       = labels
    _cache["island_names"] = island_names
    _cache["origins"]      = origins
    _cache["tile_meta"]    = tile_meta
    _cache["islands"]      = islands

    # Invalidate texture/topography caches whenever the map file changes
    _texture_cache.clear()
    _topography_cache.clear()


# ── Per-tile metadata accessors ────────────────────────────────────────────────

def get_tile_meta(q, r):
    """Return the per-tile meta dict at (q, r), or None."""
    _load_map()
    return _cache["tile_meta"].get((q, r))


def get_dialogue(q, r):
    """Return the list of dialogue boxes at (q, r) (possibly empty)."""
    m = get_tile_meta(q, r)
    return list(m.get("dialogue", [])) if m else []


def islands_near(pq, pr, reach):
    """
    Broad-phase: island index entries whose tiles could fall within `reach`
    hexes of (pq, pr) — i.e. centre distance <= reach + island radius.
    """
    _load_map()
    return [
        isl for isl in _cache["islands"]
        if _hex_distance(isl["oq"], isl["orr"], pq, pr) <= reach + isl["radius"]
    ]


def get_island_centers() -> dict:
    """
    Returns {island_name: (oq, orr)} — the authored origin/centre hex of
    each island on the current map. Used by game.set_calm_belt_bounds() to
    size the calm belt around wherever islands actually sit.
    """
    _load_map()
    return dict(_cache["origins"])


# ── Geometry helpers ──────────────────────────────────────────────────────────

def _hex_to_pixel(q, r):
    """Axial → pixel centre (pointy-top)."""
    return (
        SIZE * SQRT3 * (q + r / 2),
        SIZE * 1.5   * r,
    )


@lru_cache(maxsize=4096)
def _hex_corners(q, r):
    """Return the 6 corner (x, y) points of a hex. Cached — called frequently."""
    cx, cy = _hex_to_pixel(q, r)
    return [
        (cx + SIZE * math.cos(math.pi / 3 * i - math.pi / 6),
         cy + SIZE * math.sin(math.pi / 3 * i - math.pi / 6))
        for i in range(6)
    ]


def _hex_distance(q1, r1, q2, r2):
    return max(abs(q1-q2), abs(r1-r2), abs((q1+r1)-(q2+r2)))


def _reachable_sea(pq, pr, move_range, hex_lookup):
    """
    BFS from (pq, pr) over navigable sea, up to move_range steps.
    Tiles behind islands/blocked tiles are excluded — only hexes a ship
    can actually sail to count. Returns a set of (q, r), origin excluded.
    """
    visited  = {(pq, pr)}
    frontier = {(pq, pr)}
    for _ in range(move_range):
        nxt = set()
        for (q, r) in frontier:
            for dq, dr in HEX_DIRS:
                n = (q + dq, r + dr)
                if n in visited:
                    continue
                if n in game.BLOCKED_TILES:
                    continue
                if abs(n[1]) > game.CALM_BELT_R:
                    continue
                terrain = hex_lookup.get(n, "sea")
                if terrain == "calm_belt":
                    terrain = "sea"
                if terrain != "sea":
                    continue
                visited.add(n)
                nxt.add(n)
        frontier = nxt
    visited.discard((pq, pr))
    return visited


# ── Wind field ────────────────────────────────────────────────────────────────
# Smooth noise angle field using layered sines, snapped to nearest hex direction.
# Scale=1 gives large slow-turning wind regions across the map.

_WIND_SCALE  = 1
_WIND_PHASES = [1.3, 0.7, 2.1, 0.5, 2.4, 1.1]
_WIND_FREQS  = [1.0, 1.8, 3.2]
_WIND_DIR_ANGLES = [0, math.pi, math.pi*2/3, math.pi*5/3, math.pi/3, math.pi*4/3]

def _get_wind_angle(q, r):
    """Returns a continuous angle for the wind at (q, r)."""
    s = _WIND_SCALE * 0.12
    a = 0.0
    for i, f in enumerate(_WIND_FREQS):
        w = 1.0 / f
        a += w * math.sin(q * s * f + r * s * f * 0.71 + _WIND_PHASES[i*2])
        a += w * math.cos(q * s * f * 0.83 - r * s * f * 1.1 + _WIND_PHASES[i*2+1])
    return a * math.pi

def get_wind(q, r):
    """Returns the wind as (dq, dr) snapped to the nearest of 6 hex directions."""
    angle = _get_wind_angle(q, r)
    best_idx, best_dot = 0, -math.inf
    for i, da in enumerate(_WIND_DIR_ANGLES):
        d = math.cos(angle - da)
        if d > best_dot:
            best_dot = d
            best_idx = i
    return HEX_DIRS[best_idx]


# ── Whirlpool helper ──────────────────────────────────────────────────────────

# 8-way compass arrows, keyed by sector index (0 = East, going CCW)
_COMPASS_ARROWS = ["→", "↗", "↑", "↖", "←", "↙", "↓", "↘"]

def _compass_arrow(dx, dy):
    """Return the unicode arrow nearest the pixel-space direction (dy up)."""
    ang = math.degrees(math.atan2(dy, dx)) % 360
    return _COMPASS_ARROWS[int((ang + 22.5) % 360 // 45)]


def _draw_whirlpools(ax, whirlpools, pq, pr, radius):
    """
    Draw concentric-ring whirlpool effect on any whirlpool hex that
    falls within the current viewport, plus a small label showing the
    direction and number of tiles it teleports a ship.

    `whirlpools` maps (q, r) source -> (q, r) destination.
    Rings are clipped to the hex shape so they don't bleed into neighbours.
    """
    from matplotlib.path import Path as MPath
    from matplotlib.patches import PathPatch
    import matplotlib.patheffects as pe

    RINGS      = 6          # number of concentric rings
    RING_COLOR = (0.08, 0.25, 0.55)   # deep blue RGB
    PIT_COLOR  = (0.05, 0.15, 0.42)   # darker centre

    for (wq, wr), dest in whirlpools.items():
        if _hex_distance(wq, wr, pq, pr) > radius:
            continue

        cx, cy  = _hex_to_pixel(wq, wr)
        corners = _hex_corners(wq, wr)

        # Build hex clip path
        verts = corners + [corners[0]]
        codes = ([MPath.MOVETO]
                 + [MPath.LINETO] * (len(corners) - 1)
                 + [MPath.CLOSEPOLY])
        clip_patch = PathPatch(
            MPath(verts, codes),
            transform=ax.transData,
            facecolor="none",
            edgecolor="none",
        )
        ax.add_patch(clip_patch)

        # Draw rings from outermost inward so inner ones paint over outer
        for i in range(RINGS, 0, -1):
            r_frac = i / RINGS
            ring_r = r_frac * SIZE * 0.88
            alpha  = 0.10 + (RINGS - i) * 0.07   # inner rings darker
            lw     = 0.8 + (RINGS - i) * 0.25

            circle = mpatches.Circle(
                (cx, cy), ring_r,
                fill=False,
                edgecolor=(*RING_COLOR, alpha),
                linewidth=lw,
                zorder=4,
            )
            circle.set_clip_path(clip_patch)
            ax.add_patch(circle)

        # Dark centre pit
        pit = mpatches.Circle(
            (cx, cy), SIZE * 0.10,
            fill=True,
            facecolor=(*PIT_COLOR, 0.55),
            edgecolor="none",
            zorder=4,
        )
        pit.set_clip_path(clip_patch)
        ax.add_patch(pit)

        # Direction + number of tiles it teleports to (predetermined).
        if dest:
            dq, dr = dest
            dist   = _hex_distance(wq, wr, dq, dr)
            tx, ty = _hex_to_pixel(dq, dr)
            arrow  = _compass_arrow(tx - cx, ty - cy)
            ax.text(
                cx, cy + SIZE * 0.62, f"{arrow}{dist}",
                ha="center", va="bottom",
                fontsize=6, color="#eaf4ff", fontweight="bold",
                zorder=6, clip_on=True,
                path_effects=[pe.withStroke(linewidth=1.6, foreground=(0.03, 0.10, 0.30))],
            )


# ── Log pose arrow helper ─────────────────────────────────────────────────────

def _draw_log_pose_arrows(ax, px, py, margin, targets):
    """
    For each target (tq, tr), draw a compass-style arrow on the viewport edge
    pointing toward that hex. Skipped if the target is inside the viewport.
    """
    ARROW_FILL   = (1.0, 1.0, 1.0, 0.75)
    ARROW_EDGE   = (0.35, 0.35, 0.35, 0.9)
    ARROW_INSET  = margin * 0.12
    ARROW_SIZE   = margin * 0.09

    BASE_SHAPE = [
        ( 0.00,  1.00),
        ( 0.48, -0.38),
        ( 0.00,  0.08),
        (-0.48, -0.38),
    ]

    for (tq, tr) in targets:
        tx, ty = _hex_to_pixel(tq, tr)
        dx, dy = tx - px, ty - py

        if abs(dx) <= margin and abs(dy) <= margin:
            continue

        dist = math.hypot(dx, dy)
        if dist == 0:
            continue
        nx, ny = dx / dist, dy / dist

        if abs(nx) < 1e-9:
            t_hit = margin / abs(ny)
        elif abs(ny) < 1e-9:
            t_hit = margin / abs(nx)
        else:
            t_hit = min(margin / abs(nx), margin / abs(ny))

        tip_x = px + nx * (t_hit - ARROW_INSET)
        tip_y = py + ny * (t_hit - ARROW_INSET)

        angle = math.atan2(ny, nx) - math.pi / 2
        cos_a, sin_a = math.cos(angle), math.sin(angle)

        def rotate_and_place(lx, ly):
            rx = lx * cos_a - ly * sin_a
            ry = lx * sin_a + ly * cos_a
            return (tip_x + rx * ARROW_SIZE, tip_y + ry * ARROW_SIZE)

        pts = [rotate_and_place(lx, ly) for lx, ly in BASE_SHAPE]

        arrow = mpatches.Polygon(
            pts, closed=True,
            facecolor=ARROW_FILL,
            edgecolor=ARROW_EDGE,
            linewidth=1.0,
            zorder=8,
        )
        ax.add_patch(arrow)


# ── Ocean texture cache ───────────────────────────────────────────────────────
# Key: (pq, pr, radius) — reused across calls from the same viewport position.
# Stores the pre-computed (_X, _Y, _Z) arrays so repeated /map calls by
# players standing still skip all the numpy work entirely.
#
# Cache is intentionally small: Discord bots rarely have >handful of concurrent
# viewports. Entries are evicted when the map file changes (see _load_map).

_texture_cache: dict = {}
_TEXTURE_CACHE_MAX = 32   # max number of (pq, pr, radius) entries to keep

# Reduce grid resolution: 150×150 feeds contourf identically to 300×300
# because contourf interpolates; halving saves ~4× the numpy work.
_TEXTURE_GRID = 150


def _get_ocean_texture(pq, pr, radius, hex_lookup):
    """
    Return (X, Y, Z) numpy arrays for the ocean contourf layer.
    Results are cached by (pq, pr, radius) so repeat renders at the same
    position are essentially free.
    """
    key = (pq, pr, radius)
    if key in _texture_cache:
        return _texture_cache[key]

    px, py  = _hex_to_pixel(pq, pr)
    margin  = SIZE * radius * 1.1

    ox = np.linspace(px - margin, px + margin, _TEXTURE_GRID)
    oy = np.linspace(py - margin, py + margin, _TEXTURE_GRID)
    X, Y = np.meshgrid(ox, oy)
    Z = np.zeros_like(X)

    phases = [(1.3, 0.7, 2.1, 1.8), (0.5, 2.4, 1.1, 0.3),
              (2.7, 0.9, 1.6, 2.2), (0.2, 1.5, 2.9, 0.8)]
    for i in range(4):
        f = 1.8 ** i
        a = 1.0 / f
        p = phases[i]
        Z += a * np.sin(X * 0.09 * f + Y * 0.055 * f * 0.7 + p[0])
        Z += a * np.cos(X * 0.045 * f * 0.8 - Y * 0.07 * f + p[1])
        Z += a * np.sin(X * 0.06 * f * 0.6 + Y * 0.08 * f + p[2]) * 0.4
        Z += a * np.cos(X * 0.075 * f - Y * 0.05 * f * 0.9 + p[3]) * 0.4

    # Land proximity fade — only consider tiles inside the viewport
    fade_radius = SIZE * 2.5
    shallow = np.zeros_like(Z)
    for (tq, tr), terrain in hex_lookup.items():
        if terrain in ("sea", "calm_belt"):
            continue
        # ── OPT: skip tiles outside this viewport ──────────────────────────
        if _hex_distance(tq, tr, pq, pr) > radius:
            continue
        ix, iy = _hex_to_pixel(tq, tr)
        dist = np.sqrt((X - ix) ** 2 + (Y - iy) ** 2)
        bump = np.clip(1.0 - dist / fade_radius, 0, 1) ** 2
        shallow = np.maximum(shallow, bump)

    zmin, zmax = Z.min(), Z.max()
    Z = (Z - zmin) / (zmax - zmin + 1e-9)
    Z -= shallow * 0.45
    Z = np.clip(Z, 0, 1)

    # Evict oldest entry if cache is full
    if len(_texture_cache) >= _TEXTURE_CACHE_MAX:
        _texture_cache.pop(next(iter(_texture_cache)))

    _texture_cache[key] = (X, Y, Z)
    return X, Y, Z


# ── Topography (navigator view) ──────────────────────────────────────────────
# Per-island elevation contour, ported from the Colab prototype. Land mask is
# geometric (tile-distance based via a KDTree), independent of elevation, so
# elevation-0 land tiles stay land, and coastline isolines can't render past
# it (NaN-excluded cells stop the marching-squares algorithm).
#
# Cached per island name (not per-viewport, unlike the ocean texture) since
# an island's own shape never depends on who's looking at it or from where.
# Entries are cleared whenever the map file reloads (see _load_map).

_topography_cache: dict = {}

# _TOPO_GRID_PER_HEX = 14    # grid cells per hex of island radius
# _TOPO_GRID_MIN     = 90    # small islands still get a smooth-looking grid
# _TOPO_GRID_MAX     = 260   # cap so a huge island (e.g. Redline) stays cheap
#
# # Blur radius in hex-widths (SIZE units), not grid pixels — converted to a
# # pixel sigma per-island based on that island's actual grid spacing.
# _TOPO_BLUR_HEXES   = 1.0

# Fixed grid resolution + blur sigma, matching the prototype script exactly
# (both are in raw grid-pixel units, not scaled per island). The dynamic
# per-island sizing above was the source of the mismatch between the filled
# contour's NaN cutoff (blocky at low res) and the smooth soft_mask coastline
# contour drawn over it — at low grid_res the two visibly diverge.
_TOPO_GRID_RES     = 200
_TOPO_BLUR_SIGMA   = 1.8
_TOPO_MASK_RADIUS  = 1.06  # x SIZE — tile-center distance counted as "land"

_TOPO_N_FILL_LEVELS  = 18
_TOPO_N_LINE_LEVELS  = 16
_TOPO_LINE_LEVEL_MIN = 2.0  # skip isolines near sea level — keeps the coast clean
_TOPO_ELEV_MIN, _TOPO_ELEV_MAX = 0, 20

# _TOPO_CMAP = LinearSegmentedColormap.from_list(
#     "topo", [(0 / 3, "#a8e386"), (1 / 3, "#d9c466"), (2 / 3, "#e85733"), (3 / 3, "#9f4dd1")]
# )
# Flat ground color — no elevation color scale, just the plain ground color
# under the contour lines.
_TOPO_CMAP = LinearSegmentedColormap.from_list(
    "topo", [(0 / 20, "#f2e6d6"), (10 / 20, "#f2e6d6"), (20 / 20, "#f2e6d6")]
)

# Coastline drawn from the same soft_mask used to cut elev_final, so isolines
# can never render past it (NaN-excluded cells stop marching squares).
_TOPO_COASTLINE_COLOR = "#63584a"
_TOPO_COASTLINE_WIDTH = 1.8


def _get_island_topography(isl: dict):
    """
    Returns (X, Y, elev_final, soft_mask) for one island's elevation field,
    in the same pixel space as the hex grid. Computed once per island name
    and cached — repeat views (by any player, at any position) are free.
    """
    name = isl["name"]
    if name in _topography_cache:
        return _topography_cache[name]

    tiles   = list(isl["tiles"])
    elev    = isl["elev"]
    centers = np.array([_hex_to_pixel(q, r) for (q, r) in tiles])
    values  = np.array([elev.get(t, 0) for t in tiles], dtype=float)

    # Ocean ring — every sea hex directly touching the island, elevation 0.
    tile_set   = isl["tiles"]
    ocean_ring = set()
    for (q, r) in tiles:
        for dq, dr in HEX_DIRS:
            n = (q + dq, r + dr)
            if n not in tile_set:
                ocean_ring.add(n)

    if ocean_ring:
        ocean_centers = np.array([_hex_to_pixel(q, r) for q, r in ocean_ring])
        ocean_values  = np.zeros(len(ocean_ring))
        aug_centers   = np.vstack([centers, ocean_centers])
        aug_values    = np.concatenate([values, ocean_values])
    else:
        aug_centers, aug_values = centers, values

    margin = SIZE * 3
    minx, maxx = centers[:, 0].min() - margin, centers[:, 0].max() + margin
    miny, maxy = centers[:, 1].min() - margin, centers[:, 1].max() + margin

    # gx = np.linspace(minx, maxx, grid_res)   # (old dynamic grid_res)
    # Fixed grid resolution — matches the prototype script for every island.
    gx = np.linspace(minx, maxx, _TOPO_GRID_RES)
    gy = np.linspace(miny, maxy, _TOPO_GRID_RES)
    X, Y = np.meshgrid(gx, gy)

    # Fixed blur sigma (raw grid-pixel units) — matches the prototype script.
    blur_sigma = _TOPO_BLUR_SIGMA

    # Land mask — geometric, distance-to-tile-center based via KDTree.
    tree = cKDTree(centers)
    dist, _ = tree.query(np.column_stack([X.ravel(), Y.ravel()]))
    raw_mask  = (dist <= SIZE * _TOPO_MASK_RADIUS).astype(float).reshape(X.shape)
    soft_mask = gaussian_filter(raw_mask, sigma=blur_sigma)

    # Elevation field — one cubic interpolation (land + ocean=0 points),
    # 0.0 fallback outside its hull, then blurred.
    smooth       = griddata(aug_centers, aug_values, (X, Y), method="cubic")
    combined     = np.where(np.isnan(smooth), 0.0, smooth)
    elev_blurred = gaussian_filter(combined, sigma=blur_sigma)
    elev_final   = np.where(soft_mask > 0.5, elev_blurred, np.nan)

    result = (X, Y, elev_final, soft_mask)
    _topography_cache[name] = result
    return result


def _draw_topography(ax, islands):
    """Draw the elevation contour for each island, above the ocean texture
    (zorder 0) and below the white hex-grid pattern (zorder >= 1). The
    coastline is drawn here directly from each island's soft_mask (not the
    hex-edge border_segs) — ported straight from the prototype recipe."""
    for isl in islands:
        X, Y, elev_final, soft_mask = _get_island_topography(isl)

        # Flat ground fill (cmap is a single-color ramp — no elevation
        # color scale) — same contourf shape/levels as the original scaled
        # version, just with a flat-colored cmap swapped in.
        ax.contourf(
            X, Y, elev_final,
            levels=_TOPO_N_FILL_LEVELS,
            cmap=_TOPO_CMAP,
            vmin=_TOPO_ELEV_MIN, vmax=_TOPO_ELEV_MAX,
            zorder=0.4,
        )

        line_levels = np.linspace(_TOPO_LINE_LEVEL_MIN, _TOPO_ELEV_MAX, _TOPO_N_LINE_LEVELS)
        ax.contour(
            X, Y, elev_final,
            levels=line_levels,
            colors="black", linewidths=0.8, alpha=0.20,
            zorder=0.5,
        )

        # Coastline — same soft_mask used to cut elev_final, so isolines
        # above can never render past it (NaN-excluded cells stop the
        # marching-squares algorithm).
        ax.contour(
            X, Y, soft_mask,
            levels=[0.5],
            colors=_TOPO_COASTLINE_COLOR, linewidths=_TOPO_COASTLINE_WIDTH,
            zorder=0.6,
        )


# ── Public API ────────────────────────────────────────────────────────────────

def render_map(uid: str, radius: int = 10, view: str = "default",
               show_whirlpools: bool = False):
    """
    Render a viewport map centred on the player's position.

    view: "default"     — normal map
          "roll"        — highlights reachable ocean hexes within move_range
          "topography"  — elevation contour over islands (navigator-only; gate in the caller)
    show_whirlpools: draw whirlpool tiles (navigators only).
    Returns a BytesIO PNG buffer, or None if the player isn't registered.
    """
    import db

    player = db.get_player(uid)
    if not player:
        return None

    # pq = player["q"] if player["q"] is not None else 0
    # pr = player["r"] if player["r"] is not None else 0
    pq, pr = game.get_position(uid)

    crew_rolls = 0
    if player["crew_id"]:
        crew = db.get_crew(player["crew_id"])
        if crew:
            crew_rolls = crew["roll"] or 0
    MOVE_RANGE = max(1, crew_rolls)

    _load_map()
    hex_lookup    = _cache["hex_lookup"]
    reachable_set = _reachable_sea(pq, pr, MOVE_RANGE, hex_lookup) if view == "roll" else set()
    labels        = _cache["labels"]
    origins       = _cache["origins"]

    # ── Broad-phase: only islands whose centre is near enough to reach the ──────
    # viewport contribute land tiles. Build a local land set + name map.
    nearby_islands = islands_near(pq, pr, radius)
    nearby_tiles = set()        # (q, r) of every land tile on a nearby island
    nearby_name  = {}           # (q, r) -> island_name
    for isl in nearby_islands:
        for t in isl["tiles"]:
            nearby_tiles.add(t)
            nearby_name[t] = isl["name"]

    # ── Collect hexes in viewport ─────────────────────────────────────────────
    land_patches      = []
    land_colors       = []
    calm_patches      = []   # calm belt hexes — rendered as translucent white overlay
    border_segs       = []
    sea_segs          = []
    hex_label_data    = []
    reachable_centers = []
    wind_centers      = []   # roll view — wind-boosted hexes (reddish dots)
    island_accum      = {}
    impel_down_center = None  # set if (180, 0) is in the viewport

    for q in range(pq - radius, pq + radius + 1):
        for r in range(pr - radius, pr + radius + 1):
            if _hex_distance(q, r, pq, pr) > radius:
                continue

            # Calm belt — driven purely by r axis, ignore JSON calm_belt entirely
            if CALM_BELT_ENABLED and abs(r) > game.CALM_BELT_R:
                cx, cy  = _hex_to_pixel(q, r)
                corners = _hex_corners(q, r)
                calm_patches.append(
                    mpatches.RegularPolygon(
                        (cx, cy), numVertices=6,
                        radius=SIZE, orientation=0,
                    )
                )
                for (dq, dr), (i1, i2) in NEIGHBOR_TO_EDGE.items():
                    nq, nr = q + dq, r + dr
                    if _hex_distance(nq, nr, pq, pr) <= radius:
                        if dq > 0 or (dq == 0 and dr > 0):
                            p1, p2 = corners[i1], corners[i2]
                            sea_segs.append([p1, p2])
                continue

            # Impel Down — record center for post-figure rendering
            if (q, r) == IMPEL_DOWN:
                cx, cy  = _hex_to_pixel(q, r)
                corners = _hex_corners(q, r)
                impel_down_center = (cx, cy)
                # still contribute sea grid edges (skipping this tile would leave 3 edges undrawn)
                for (dq2, dr2), (i1, i2) in NEIGHBOR_TO_EDGE.items():
                    nq2, nr2 = q + dq2, r + dr2
                    if _hex_distance(nq2, nr2, pq, pr) <= radius:
                        if dq2 > 0 or (dq2 == 0 and dr2 > 0):
                            sea_segs.append([corners[i1], corners[i2]])
                continue

            # Marine facilities — gray hexes, rendered like islands
            if (q, r) in GRAY_HEXES:
                cx, cy  = _hex_to_pixel(q, r)
                corners = _hex_corners(q, r)
                land_patches.append(
                    mpatches.RegularPolygon(
                        (cx, cy), numVertices=6,
                        radius=SIZE, orientation=0,
                    )
                )
                land_colors.append(GRAY_HEX_COLOR)
                # Border only where the neighbour is open sea — adjacent gray
                # facility tiles read as one landmass.
                for (dq, dr), (i1, i2) in NEIGHBOR_TO_EDGE.items():
                    nq, nr = q + dq, r + dr
                    neighbor_is_land = (
                        (nq, nr) in nearby_tiles
                        or (nq, nr) in GRAY_HEXES
                    )
                    if not neighbor_is_land:
                        border_segs.append([corners[i1], corners[i2]])
                continue

            # Land iff this tile belongs to a nearby island, else open sea.
            terrain = "island" if (q, r) in nearby_tiles else "sea"

            cx, cy  = _hex_to_pixel(q, r)
            corners = _hex_corners(q, r)   # cached

            if terrain == "sea":
                for (dq, dr), (i1, i2) in NEIGHBOR_TO_EDGE.items():
                    nq, nr = q + dq, r + dr
                    if _hex_distance(nq, nr, pq, pr) <= radius:
                        if dq > 0 or (dq == 0 and dr > 0):
                            p1, p2 = corners[i1], corners[i2]
                            sea_segs.append([p1, p2])

                # Roll dots: only tiles actually reachable by sailing (BFS)
                if view == "roll" and (q, r) in reachable_set:
                    reachable_centers.append((cx, cy, _hex_distance(q, r, pq, pr)))
                continue

            # Topography view renders islands via the elevation contour
            # instead — skip the flat fill so it isn't painted over it.
            if view != "topography":
                color = TERRAIN_COLORS.get(terrain, TERRAIN_COLORS["island"])
                land_patches.append(
                    mpatches.RegularPolygon(
                        (cx, cy), numVertices=6,
                        radius=SIZE, orientation=0,
                    )
                )
                land_colors.append(color)

            if terrain not in ("redline",):
                # Per-hex label (e.g. "Royal Palace")
                if (q, r) in labels:
                    hex_label_data.append((cx, cy, labels[(q, r)]))
                # Accumulate pixel positions for island name centroid
                name = nearby_name.get((q, r), "")
                if name:
                    island_accum.setdefault(name, []).append((cx, cy))

            # if view == "topography":
            #     # No island outline in this view — instead, this tile
            #     # contributes to the same uniform hex grid as sea tiles do,
            #     # so the grid pattern reads as one layer over the whole map.
            #     for (dq, dr), (i1, i2) in NEIGHBOR_TO_EDGE.items():
            #         nq, nr = q + dq, r + dr
            #         if _hex_distance(nq, nr, pq, pr) <= radius:
            #             if dq > 0 or (dq == 0 and dr > 0):
            #                 p1, p2 = corners[i1], corners[i2]
            #                 sea_segs.append([p1, p2])
            # else:
            #     for (dq, dr), (i1, i2) in NEIGHBOR_TO_EDGE.items():
            #         nq, nr = q + dq, r + dr
            #         if (nq, nr) not in nearby_tiles:
            #             p1, p2 = corners[i1], corners[i2]
            #             border_segs.append([p1, p2])

            if view == "topography":
                # No hex-edge outline in this view — the coastline is drawn
                # from the island's soft_mask in _draw_topography instead.
                # This tile still contributes to the uniform hex grid, same
                # as sea tiles, so the grid reads as one layer over the map.
                for (dq, dr), (i1, i2) in NEIGHBOR_TO_EDGE.items():
                    nq, nr = q + dq, r + dr
                    if _hex_distance(nq, nr, pq, pr) <= radius:
                        if dq > 0 or (dq == 0 and dr > 0):
                            p1, p2 = corners[i1], corners[i2]
                            sea_segs.append([p1, p2])
            else:
                for (dq, dr), (i1, i2) in NEIGHBOR_TO_EDGE.items():
                    nq, nr = q + dq, r + dr
                    if (nq, nr) not in nearby_tiles:
                        p1, p2 = corners[i1], corners[i2]
                        border_segs.append([p1, p2])

    # ── Wind-boosted hexes for roll view ─────────────────────────────────────
    if view == "roll":
        wdq, wdr = get_wind(pq, pr)
        # base reachable set — actual sailable tiles from BFS
        base_set = reachable_set | {(pq, pr)}
        seen = set()
        for step in (1, 2):
            for (bq, br) in base_set:
                wq, wr = bq + wdq * step, br + wdr * step
                if (wq, wr) in seen or (wq, wr) in base_set:
                    continue
                # Wind dots never land in calm belt
                if (hex_lookup.get((wq, wr), "sea") == "sea"
                        and abs(wr) <= game.CALM_BELT_R
                        and (wq, wr) not in game.BLOCKED_TILES):
                    seen.add((wq, wr))
                    wind_centers.append(_hex_to_pixel(wq, wr))

    # Island names are intentionally not shown — players discover islands via /spyglass
    island_label_data = []

    # Determine log pose arrow target from crew db
    log_pose_targets = []
    crew = db.get_crew(player["crew_id"]) if player["crew_id"] else None
    if crew:
        target_name = crew["log_pose"] or game.DEFAULT_LOG_POSE
        island_data = islands_mod.get_island(target_name)
        tq = island_data["q"] if island_data else None
        tr = island_data["r"] if island_data else None
        if tq is not None and tr is not None:
            # Only draw arrow if no tiles of the target island are in the viewport
            target_visible = any(
                n == target_name
                for (q2, r2), n in nearby_name.items()
                if _hex_distance(q2, r2, pq, pr) <= radius
            )
            if not target_visible:
                log_pose_targets = [(tq, tr)]

    # ── Build figure ──────────────────────────────────────────────────────────
    px, py  = _hex_to_pixel(pq, pr)
    margin  = SIZE * radius * 1.1

    # fig, ax = plt.subplots(figsize=(10, 10), facecolor=SEA_COLOR)
    fig, ax = plt.subplots(figsize=(10, 10), facecolor=BACKGROUND_COLOR)
    ax.set_aspect("equal")
    ax.axis("off")

    if view == "topography":
        # Skip the ocean texture entirely in this view — the wavy sea
        # contourf isn't visible under the elevation contour anyway, so
        # computing and drawing it would just waste time. A flat sea color
        # stands in for it.
        ax.set_facecolor(SEA_COLOR)
        _draw_topography(ax, nearby_islands)
    else:
        # Ocean texture — fetch from cache or compute once
        _X, _Y, _Z = _get_ocean_texture(pq, pr, radius, hex_lookup)

        # ax.contourf(
        #     _X, _Y, _Z,
        #     levels=4,
        #     colors=["#75e1ff", "#6dd4f5", "#65c9eb", "#5cbde0", "#54b2d6"],
        #     zorder=0,
        # )
        ax.set_facecolor(BACKGROUND_COLOR)

    if sea_segs:
        ax.add_collection(LineCollection(
            sea_segs,
            colors=(1.0, 1.0, 1.0, 0.18),
            linewidths=SEA_GRID_WIDTH,
            zorder=1,
        ))

    if view == "roll" and reachable_centers:
        xs, ys, dists = zip(*reachable_centers)
        # alpha rolloff: ~0.62 nearest → ~0.28 (half) at 9 tiles out
        ROLL_ALPHA_NEAR, ROLL_ALPHA_FAR, ROLL_ALPHA_DIST = 0.62, 0.18, 9.0
        colors = [
            (1.0, 1.0, 1.0,
             max(ROLL_ALPHA_FAR,
                 ROLL_ALPHA_NEAR - (ROLL_ALPHA_NEAR - ROLL_ALPHA_FAR) * (max(0, d - 1) / ROLL_ALPHA_DIST)))
            for d in dists
        ]
        ax.scatter(xs, ys, s=18, color=colors, linewidths=0, zorder=2)

    if view == "roll" and wind_centers:
        wxs, wys = zip(*wind_centers)
        ax.scatter(wxs, wys, s=18, color=(0.85, 0.25, 0.20, 0.50),
                   linewidths=0, zorder=2)

    if calm_patches:
        cc = PatchCollection(
            calm_patches,
            facecolors=[CALM_BELT_COLOR] * len(calm_patches),
            edgecolors="none",
            linewidths=0,
            match_original=False,
            zorder=2,
        )
        ax.add_collection(cc)

    if land_patches:
        pc = PatchCollection(
            land_patches,
            facecolors=land_colors,
            edgecolors="none",
            linewidths=0,
            match_original=False,
            zorder=2,
        )
        ax.add_collection(pc)

    if border_segs and view != "topography":
        lc = LineCollection(
            border_segs,
            colors=BORDER_COLOR,
            linewidths=BORDER_WIDTH,
            capstyle="round",
            zorder=3,
        )
        ax.add_collection(lc)

    # Whirlpool effects — drawn above sea, below labels and player.
    # Only navigators can see them, so the caller gates this.
    if show_whirlpools:
        _draw_whirlpools(ax, game.get_whirlpools(), pq, pr, radius)

    # Impel Down — concentric circles, outer rings behind the hex grid
    if impel_down_center is not None:
        icx, icy   = impel_down_center
        TOP_RADIUS = SIZE * 0.52
        # bottom shadow — slightly larger, dark ocean blue, behind the hex grid
        ax.add_patch(mpatches.Circle(
            (icx, icy), TOP_RADIUS + SIZE * 0.28,
            facecolor="#3a7a92",
            edgecolor="none",
            zorder=0.5,
        ))
        # top circle — slate gray, above the grid
        ax.add_patch(mpatches.Circle(
            (icx, icy), TOP_RADIUS,
            facecolor="#575768",
            edgecolor="none",
            zorder=3,
        ))
        ax.text(icx, icy + TOP_RADIUS * 0.65, "Impel Down",
                ha="center", va="bottom",
                fontsize=5.5, color="#d0d0e8",
                fontweight="bold", clip_on=True, zorder=6)

    # Per-hex labels (hex_label field — e.g. "Royal Palace")
    for (lx, ly, text) in hex_label_data:
        ax.text(lx, ly, text,
                ha="center", va="center",
                fontsize=6, color=LABEL_COLOR,
                fontweight="bold", clip_on=True, zorder=6)

    player_on_land = hex_lookup.get((pq, pr)) == "island"

    if player_on_land:
        ax.plot(px, py, "o",
                color=PLAYER_COLOR, markersize=10,
                markeredgecolor="#000", markeredgewidth=0.8,
                zorder=5)
    else:
        icon = _get_ship_icon()
        if icon is not None:
            oi = OffsetImage(icon, zoom=SHIP_ICON_SIZE / max(icon.shape[:2]))
            oi.image.axes = ax
            ab = AnnotationBbox(oi, (px, py), frameon=False, pad=0, zorder=5)
            ax.add_artist(ab)
        else:
            ax.plot(px, py, "o",
                    color=PLAYER_COLOR, markersize=14,
                    markeredgecolor="#000", markeredgewidth=0.8,
                    zorder=5)
            ax.text(px, py, "S",
                    ha="center", va="center",
                    fontsize=7, color="black", fontweight="bold",
                    zorder=6)

    # Other crews' ships in viewport — same icon, random rotation
    own_crew_id = player["crew_id"]
    for other in db.get_all_crews():
        if own_crew_id and other["id"] == own_crew_id:
            continue
        oq, orr = other["q"] or 0, other["r"] or 0
        if _hex_distance(oq, orr, pq, pr) > radius:
            continue
        ox, oy = _hex_to_pixel(oq, orr)
        oicon  = _get_other_ship_icon()
        if oicon is not None:
            ooi = OffsetImage(oicon, zoom=SHIP_ICON_SIZE / max(oicon.shape[:2]))
            ooi.image.axes = ax
            oab = AnnotationBbox(ooi, (ox, oy), frameon=False, pad=0, zorder=4)
            ax.add_artist(oab)
        else:
            ax.plot(ox, oy, "o",
                    color="#b0b0b0", markersize=12,
                    markeredgecolor="#000", markeredgewidth=0.8,
                    zorder=4)

    ax.set_xlim(px - margin, px + margin)
    ax.set_ylim(py - margin, py + margin)

    _draw_log_pose_arrows(ax, px, py, margin, log_pose_targets)

    # ── Render to buffer and clean up ─────────────────────────────────────────
    buf = io.BytesIO()
    fig.savefig(
        buf, format="png", dpi=100,   # 100 vs 150 saves ~2× on PNG encode
        bbox_inches="tight",
        # facecolor=SEA_COLOR,
        facecolor=BACKGROUND_COLOR,
        pad_inches=0,
    )
    plt.close(fig)
    gc.collect()
    buf.seek(0)
    return buf
