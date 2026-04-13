import io
import json
import math
import os
from functools import lru_cache

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from matplotlib.collections import PatchCollection, LineCollection
from matplotlib.image import imread
from matplotlib.offsetbox import OffsetImage, AnnotationBbox

# ── Constants ─────────────────────────────────────────────────────────────────

MAP_PATH = "map.json"   # path to the exported editor JSON

SQRT3 = math.sqrt(3)
SIZE  = 3.0             # hex radius in data units

TERRAIN_COLORS = {
    "island":    "#c4f5d7",
    "redline":   "#c7706b",
    "calm_belt": "#76b8d4",
    # fallback for anything else
    "sea":       "#75e1ff",
}

BORDER_COLOR     = "#f0f8ff"
BORDER_WIDTH     = 1.5   # land-sea edge thickness
SEA_GRID_WIDTH   = 1.5   # sea-sea grid line thickness
PLAYER_COLOR     = "#F0D060"
LABEL_COLOR      = "#171717"
SEA_COLOR        = TERRAIN_COLORS["sea"]

# Calm belt — any hex where abs(r) > 36 is treated as impassable calm belt
# regardless of what the JSON says. The JSON calm_belt terrain type is ignored.
CALM_BELT_R = 36

# Calm belt overlay — translucent white drawn above the sea texture
CALM_BELT_COLOR = (1.0, 1.0, 1.0, 0.38)

# Log pose targets — (q, r) tuples the arrow points toward.
# Replace with dynamic data later (e.g. from db or game state).
LOG_POSE_TARGETS = [(32, 10)]

# Whirlpool tiles — list of (q, r) that get the concentric-ring effect
WHIRLPOOL_TILES = [(-3, 5)]

# Player ship icon — loaded once, falls back to dot if file missing.
# SHIP_ROTATION: number of 90° counter-clockwise turns (1=90°, 2=180°, 3=270°)
SHIP_ROTATION  = 3  # 3 × 90° CCW = 270° CCW = 90° clockwise
SHIP_ICON_SIZE = 28   # display size in pixels — tweak to taste

_SHIP_ICON = None

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
    "hex_lookup": {},   # (q, r) -> hex_type string
    "labels":     {},   # (q, r) -> hex_label string (per-hex labels only)
    "island_names": {}, # (q, r) -> island_name string
    "origins":    {},   # island_name -> (q, r) origin or None
}


def _load_map():
    """Load map JSON into module-level cache. No-op if file unchanged."""
    try:
        mtime = os.path.getmtime(MAP_PATH)
    except FileNotFoundError:
        return

    if mtime == _cache["mtime"]:
        return

    with open(MAP_PATH, "r") as f:
        data = json.load(f)

    hex_lookup    = {}
    labels        = {}
    island_names  = {}

    for tile in data.get("tiles", []):
        q, r = tile.get("q"), tile.get("r")
        if q is None or r is None:
            continue
        hex_type = tile.get("hex_type", "sea")
        hex_lookup[(q, r)] = hex_type

        # hex_label is a per-hex label (e.g. "Royal Palace") — shown on that hex
        hex_label = tile.get("hex_label", "")
        if hex_label:
            labels[(q, r)] = hex_label

        # island_name links the hex to a named island — used for island label
        name = tile.get("island_name", "")
        if name:
            island_names[(q, r)] = name

    # Load per-island origins from the islands block if present
    origins = {}
    for name, idata in data.get("islands", {}).items():
        orig = idata.get("origin")
        if orig and orig.get("q") is not None and orig.get("r") is not None:
            origins[name] = (orig["q"], orig["r"])
        else:
            origins[name] = None

    _cache["mtime"]        = mtime
    _cache["hex_lookup"]   = hex_lookup
    _cache["labels"]       = labels
    _cache["island_names"] = island_names
    _cache["origins"]      = origins

    # Invalidate texture cache whenever the map file changes
    _texture_cache.clear()


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

def _draw_whirlpools(ax, whirlpool_tiles, pq, pr, radius):
    """
    Draw concentric-ring whirlpool effect on any WHIRLPOOL_TILES hex that
    falls within the current viewport.

    Rings are clipped to the hex shape so they don't bleed into neighbours.
    """
    from matplotlib.path import Path as MPath
    from matplotlib.patches import PathPatch

    RINGS      = 6          # number of concentric rings
    RING_COLOR = (0.08, 0.25, 0.55)   # deep blue RGB
    PIT_COLOR  = (0.05, 0.15, 0.42)   # darker centre

    for (wq, wr) in whirlpool_tiles:
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
        )

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


# ── Public API ────────────────────────────────────────────────────────────────

def render_map(uid: str, radius: int = 10, view: str = "default"):
    """
    Render a viewport map centred on the player's position.

    view: "default" — normal map
          "roll"    — highlights reachable ocean hexes within move_range
    Returns a BytesIO PNG buffer, or None if the player isn't registered.
    """
    import db

    player = db.get_player(uid)
    if not player:
        return None

    pq = player["q"] if player["q"] is not None else 0
    pr = player["r"] if player["r"] is not None else 0

    MOVE_RANGE = 5  # placeholder — swap for player stat later

    _load_map()
    hex_lookup    = _cache["hex_lookup"]
    labels        = _cache["labels"]
    island_names  = _cache["island_names"]
    origins       = _cache["origins"]

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

    for q in range(pq - radius, pq + radius + 1):
        for r in range(pr - radius, pr + radius + 1):
            if _hex_distance(q, r, pq, pr) > radius:
                continue

            # Calm belt — driven purely by r axis, ignore JSON calm_belt entirely
            if abs(r) > CALM_BELT_R:
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

            # Ignore calm_belt terrain from JSON — treat as plain sea
            terrain = hex_lookup.get((q, r), "sea")
            if terrain == "calm_belt":
                terrain = "sea"

            cx, cy  = _hex_to_pixel(q, r)
            corners = _hex_corners(q, r)   # cached

            if terrain == "sea":
                for (dq, dr), (i1, i2) in NEIGHBOR_TO_EDGE.items():
                    nq, nr = q + dq, r + dr
                    if _hex_distance(nq, nr, pq, pr) <= radius:
                        if dq > 0 or (dq == 0 and dr > 0):
                            p1, p2 = corners[i1], corners[i2]
                            sea_segs.append([p1, p2])

                # Roll dots: only on navigable sea, never in calm belt
                if view == "roll" and _hex_distance(q, r, pq, pr) <= MOVE_RANGE:
                    reachable_centers.append((cx, cy))
                continue

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
                name = island_names.get((q, r), "")
                if name:
                    island_accum.setdefault(name, []).append((cx, cy))

            for (dq, dr), (i1, i2) in NEIGHBOR_TO_EDGE.items():
                nq, nr = q + dq, r + dr
                if hex_lookup.get((nq, nr), "sea") == "sea":
                    p1, p2 = corners[i1], corners[i2]
                    border_segs.append([p1, p2])

    # ── Wind-boosted hexes for roll view ─────────────────────────────────────
    if view == "roll":
        wdq, wdr = get_wind(pq, pr)
        # base reachable set as axial coords for fast lookup
        base_set = {(q, r)
                    for q in range(pq - MOVE_RANGE, pq + MOVE_RANGE + 1)
                    for r in range(pr - MOVE_RANGE, pr + MOVE_RANGE + 1)
                    if _hex_distance(q, r, pq, pr) <= MOVE_RANGE}
        seen = set()
        for step in (1, 2):
            for (bq, br) in base_set:
                wq, wr = bq + wdq * step, br + wdr * step
                if (wq, wr) in seen or (wq, wr) in base_set:
                    continue
                # Wind dots never land in calm belt
                if hex_lookup.get((wq, wr), "sea") == "sea" and abs(wr) <= CALM_BELT_R:
                    seen.add((wq, wr))
                    wind_centers.append(_hex_to_pixel(wq, wr))

    # ── Resolve island name label positions ──────────────────────────────────
    # Use the stored origin if set, otherwise use centroid of visible hexes
    island_label_data = []
    for name, pts in island_accum.items():
        origin = origins.get(name)
        if origin:
            lx, ly = _hex_to_pixel(origin[0], origin[1])
        else:
            lx = sum(p[0] for p in pts) / len(pts)
            ly = sum(p[1] for p in pts) / len(pts)
        island_label_data.append((lx, ly, name))

    # ── Build figure ──────────────────────────────────────────────────────────
    px, py  = _hex_to_pixel(pq, pr)
    margin  = SIZE * radius * 1.1

    fig, ax = plt.subplots(figsize=(10, 10), facecolor=SEA_COLOR)
    ax.set_aspect("equal")
    ax.axis("off")

    # Ocean texture — fetch from cache or compute once
    _X, _Y, _Z = _get_ocean_texture(pq, pr, radius, hex_lookup)

    ax.contourf(
        _X, _Y, _Z,
        levels=4,
        colors=["#75e1ff", "#6dd4f5", "#65c9eb", "#5cbde0", "#54b2d6"],
        zorder=0,
    )

    if sea_segs:
        ax.add_collection(LineCollection(
            sea_segs,
            colors=(1.0, 1.0, 1.0, 0.18),
            linewidths=SEA_GRID_WIDTH,
            zorder=1,
        ))

    if view == "roll" and reachable_centers:
        xs, ys = zip(*reachable_centers)
        ax.scatter(xs, ys, s=18, color=(1.0, 1.0, 1.0, 0.55),
                   linewidths=0, zorder=2)

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

    if border_segs:
        lc = LineCollection(
            border_segs,
            colors=BORDER_COLOR,
            linewidths=BORDER_WIDTH,
            capstyle="round",
            zorder=3,
        )
        ax.add_collection(lc)

    # Whirlpool effects — drawn above sea, below labels and player
    _draw_whirlpools(ax, WHIRLPOOL_TILES, pq, pr, radius)

    # Island name labels — one per island, at origin or centroid
    for (lx, ly, text) in island_label_data:
        ax.text(lx, ly, text,
                ha="center", va="center",
                fontsize=8, color="#1a2a3a",
                fontweight="bold", clip_on=True, zorder=7)

    # Per-hex labels (hex_label field — e.g. "Royal Palace")
    for (lx, ly, text) in hex_label_data:
        ax.text(lx, ly, text,
                ha="center", va="center",
                fontsize=6, color=LABEL_COLOR,
                fontweight="bold", clip_on=True, zorder=6)

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

    ax.set_xlim(px - margin, px + margin)
    ax.set_ylim(py - margin, py + margin)

    _draw_log_pose_arrows(ax, px, py, margin, LOG_POSE_TARGETS)

    # ── Render to buffer and clean up ─────────────────────────────────────────
    buf = io.BytesIO()
    fig.savefig(
        buf, format="png", dpi=100,   # 100 vs 150 saves ~2× on PNG encode
        bbox_inches="tight",
        facecolor=SEA_COLOR,
        pad_inches=0,
    )
    plt.close(fig)
    buf.seek(0)
    return buf
