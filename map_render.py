import io
import json
import math
import os

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from matplotlib.collections import PatchCollection, LineCollection
from matplotlib.image import imread
from matplotlib.offsetbox import OffsetImage, AnnotationBbox

# ── Constants ─────────────────────────────────────────────────────────────────

MAP_PATH = "map.json"

SQRT3 = math.sqrt(3)
SIZE  = 3.0

TERRAIN_COLORS = {
    "island":    "#c4f5d7",
    "redline":   "#c7706b",
    "calm_belt": "#76b8d4",
    "sea":       "#75e1ff",
}

BORDER_COLOR   = "#f0f8ff"
BORDER_WIDTH   = 1.5
SEA_GRID_WIDTH = 1.5
PLAYER_COLOR   = "#F0D060"
LABEL_COLOR    = "#171717"
SEA_COLOR      = TERRAIN_COLORS["sea"]

LOG_POSE_TARGETS = [(32, 10)]

SHIP_ROTATION  = 3
SHIP_ICON_SIZE = 28

# Ocean color ramp as float32 RGB — used for fast imshow color mapping
_OCEAN_RAMP = np.array([
    [0x75, 0xe1, 0xff],
    [0x6d, 0xd4, 0xf5],
    [0x65, 0xc9, 0xeb],
    [0x5c, 0xbd, 0xe0],
    [0x54, 0xb2, 0xd6],
], dtype=np.float32) / 255.0

# Hex corner offsets — precomputed once, reused every render
# Avoids 6 trig calls per hex per frame (~1800 calls saved per render)
_HEX_CORNER_OFFSETS = tuple(
    (SIZE * math.cos(math.pi / 3 * i - math.pi / 6),
     SIZE * math.sin(math.pi / 3 * i - math.pi / 6))
    for i in range(6)
)

NEIGHBOR_TO_EDGE = {
    ( 1,  0): (0, 1),
    ( 0,  1): (1, 2),
    (-1,  1): (2, 3),
    (-1,  0): (3, 4),
    ( 0, -1): (4, 5),
    ( 1, -1): (5, 0),
}

# ── Map data cache ────────────────────────────────────────────────────────────

_cache = {
    "mtime":      None,
    "hex_lookup": {},
    "labels":     {},
}


def _load_map():
    try:
        mtime = os.path.getmtime(MAP_PATH)
    except FileNotFoundError:
        return
    if mtime == _cache["mtime"]:
        return
    with open(MAP_PATH, "r") as f:
        data = json.load(f)
    hex_lookup, labels = {}, {}
    for tile in data.get("tiles", []):
        q, r = tile.get("q"), tile.get("r")
        if q is None or r is None:
            continue
        hex_lookup[(q, r)] = tile.get("hex_type", "sea")
        label = tile.get("hex_label") or tile.get("island_name") or ""
        if label:
            labels[(q, r)] = label
    _cache["mtime"]      = mtime
    _cache["hex_lookup"] = hex_lookup
    _cache["labels"]     = labels


# ── Geometry helpers ──────────────────────────────────────────────────────────

def _hex_to_pixel(q, r):
    return (SIZE * SQRT3 * (q + r / 2), SIZE * 1.5 * r)


def _hex_corners(q, r):
    cx, cy = _hex_to_pixel(q, r)
    return [(cx + ox, cy + oy) for ox, oy in _HEX_CORNER_OFFSETS]


def _hex_distance(q1, r1, q2, r2):
    return max(abs(q1-q2), abs(r1-r2), abs((q1+r1)-(q2+r2)))


# ── Ship icon cache ───────────────────────────────────────────────────────────

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


# ── Ocean texture ─────────────────────────────────────────────────────────────

_OCEAN_PHASES = [
    (1.3, 0.7, 2.1, 1.8),
    (0.5, 2.4, 1.1, 0.3),
    (2.7, 0.9, 1.6, 2.2),
    (0.2, 1.5, 2.9, 0.8),
]


def _build_ocean_image(px, py, margin, land_pixels):
    """
    Returns an RGBA float32 array (H, W, 4) for the ocean texture.
    Uses imshow instead of contourf — ~10x faster for this use case.
    land_pixels: list of (ix, iy) pixel coords of nearby land hexes
    """
    N = 220  # grid resolution — 220×220 is plenty for a 10-dpi map
    ox = np.linspace(px - margin, px + margin, N, dtype=np.float32)
    oy = np.linspace(py - margin, py + margin, N, dtype=np.float32)
    X, Y = np.meshgrid(ox, oy)
    Z = np.zeros((N, N), dtype=np.float32)

    for i in range(4):
        f = 1.8 ** i
        a = 1.0 / f
        p = _OCEAN_PHASES[i]
        Z += a * np.sin(X * 0.09*f + Y * 0.055*f*0.7  + p[0])
        Z += a * np.cos(X * 0.045*f*0.8 - Y * 0.07*f   + p[1])
        Z += a * np.sin(X * 0.06*f*0.6  + Y * 0.08*f   + p[2]) * 0.4
        Z += a * np.cos(X * 0.075*f     - Y * 0.05*f*0.9 + p[3]) * 0.4

    # Normalize
    zmin, zmax = Z.min(), Z.max()
    Z = (Z - zmin) / (zmax - zmin + 1e-9)

    # Shallow water — vectorized over all land hexes at once
    if land_pixels:
        lp = np.array(land_pixels, dtype=np.float32)  # (K, 2)
        fade_r = SIZE * 2.5
        # Broadcast: (K, N, N) distance array, take minimum across K
        dx = lp[:, 0, None, None] - X[None, :, :]
        dy = lp[:, 1, None, None] - Y[None, :, :]
        dists = np.sqrt(dx*dx + dy*dy)           # (K, N, N)
        min_dist = dists.min(axis=0)             # (N, N)
        shallow = np.clip(1.0 - min_dist / fade_r, 0, 1) ** 2
        Z -= shallow * 0.45
        Z = np.clip(Z, 0, 1)

    # Map Z → RGBA using linear interpolation across _OCEAN_RAMP
    idx_f = Z * (len(_OCEAN_RAMP) - 1)
    idx0  = np.floor(idx_f).astype(np.int32).clip(0, len(_OCEAN_RAMP) - 2)
    idx1  = idx0 + 1
    t     = (idx_f - idx0)[:, :, None]
    rgb   = _OCEAN_RAMP[idx0] * (1 - t) + _OCEAN_RAMP[idx1] * t
    rgba  = np.dstack([rgb, np.ones((N, N), dtype=np.float32)])
    return rgba


# ── Log pose arrows ───────────────────────────────────────────────────────────

def _draw_log_pose_arrows(ax, px, py, margin, targets):
    ARROW_FILL  = (1.0, 1.0, 1.0, 0.75)
    ARROW_EDGE  = (0.35, 0.35, 0.35, 0.9)
    ARROW_INSET = margin * 0.12
    ARROW_SIZE  = margin * 0.09

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
        angle  = math.atan2(ny, nx) - math.pi / 2
        cos_a, sin_a = math.cos(angle), math.sin(angle)

        pts = [
            (tip_x + (lx*cos_a - ly*sin_a) * ARROW_SIZE,
             tip_y + (lx*sin_a + ly*cos_a) * ARROW_SIZE)
            for lx, ly in BASE_SHAPE
        ]
        ax.add_patch(mpatches.Polygon(
            pts, closed=True,
            facecolor=ARROW_FILL, edgecolor=ARROW_EDGE,
            linewidth=1.0, zorder=8,
        ))


def _draw_rock_texture():
    pass  # placeholder — kept for future use


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

    MOVE_RANGE = 5

    _load_map()
    hex_lookup = _cache["hex_lookup"]
    labels     = _cache["labels"]

    # ── Collect viewport hexes ────────────────────────────────────────────────
    land_patches      = []
    land_colors       = []
    border_segs       = []
    sea_segs          = []
    label_data        = []
    reachable_centers = []
    land_pixels       = []  # pixel coords of land hexes for shallow water

    for q in range(pq - radius, pq + radius + 1):
        for r in range(pr - radius, pr + radius + 1):
            if _hex_distance(q, r, pq, pr) > radius:
                continue

            terrain = hex_lookup.get((q, r), "sea")
            cx, cy  = _hex_to_pixel(q, r)
            corners = _hex_corners(q, r)

            if terrain == "sea":
                for (dq, dr), (i1, i2) in NEIGHBOR_TO_EDGE.items():
                    nq, nr = q + dq, r + dr
                    if _hex_distance(nq, nr, pq, pr) <= radius:
                        if dq > 0 or (dq == 0 and dr > 0):
                            sea_segs.append([corners[i1], corners[i2]])
                if view == "roll" and _hex_distance(q, r, pq, pr) <= MOVE_RANGE:
                    reachable_centers.append((cx, cy))
                continue

            color = TERRAIN_COLORS.get(terrain, TERRAIN_COLORS["island"])
            land_patches.append(mpatches.RegularPolygon(
                (cx, cy), numVertices=6, radius=SIZE, orientation=0,
            ))
            land_colors.append(color)
            land_pixels.append((cx, cy))

            if terrain not in ("redline", "calm_belt") and (q, r) in labels:
                label_data.append((cx, cy, labels[(q, r)]))

            for (dq, dr), (i1, i2) in NEIGHBOR_TO_EDGE.items():
                nq, nr = q + dq, r + dr
                if hex_lookup.get((nq, nr), "sea") == "sea":
                    border_segs.append([corners[i1], corners[i2]])

    # ── Build figure ──────────────────────────────────────────────────────────
    px, py = _hex_to_pixel(pq, pr)
    margin  = SIZE * radius * 1.1

    fig, ax = plt.subplots(figsize=(10, 10), facecolor=SEA_COLOR)
    ax.set_aspect("equal")
    ax.axis("off")

    # Viewport must be set before imshow so extent lands correctly
    ax.set_xlim(px - margin, px + margin)
    ax.set_ylim(py - margin, py + margin)

    # Ocean texture — imshow is ~10x faster than contourf
    ocean_img = _build_ocean_image(px, py, margin, land_pixels)
    ax.imshow(
        ocean_img,
        extent=[px - margin, px + margin, py - margin, py + margin],
        origin="lower", aspect="auto", interpolation="bilinear",
        zorder=0,
    )

    if sea_segs:
        ax.add_collection(LineCollection(
            sea_segs, colors=(1.0, 1.0, 1.0, 0.18),
            linewidths=SEA_GRID_WIDTH, zorder=1,
        ))

    if view == "roll" and reachable_centers:
        xs, ys = zip(*reachable_centers)
        ax.scatter(xs, ys, s=18, color=(1.0, 1.0, 1.0, 0.55),
                   linewidths=0, zorder=2)

    if land_patches:
        ax.add_collection(PatchCollection(
            land_patches, facecolors=land_colors,
            edgecolors="none", linewidths=0,
            match_original=False, zorder=2,
        ))

    if border_segs:
        ax.add_collection(LineCollection(
            border_segs, colors=BORDER_COLOR,
            linewidths=BORDER_WIDTH, capstyle="round", zorder=3,
        ))

    for lx, ly, text in label_data:
        ax.text(lx, ly, text, ha="center", va="center",
                fontsize=7, color=LABEL_COLOR, fontweight="bold", clip_on=True)

    icon = _get_ship_icon()
    if icon is not None:
        oi = OffsetImage(icon, zoom=SHIP_ICON_SIZE / max(icon.shape[:2]))
        oi.image.axes = ax
        ax.add_artist(AnnotationBbox(oi, (px, py), frameon=False, pad=0, zorder=5))
    else:
        ax.plot(px, py, "o", color=PLAYER_COLOR, markersize=14,
                markeredgecolor="#000", markeredgewidth=0.8, zorder=5)
        ax.text(px, py, "S", ha="center", va="center",
                fontsize=7, color="black", fontweight="bold", zorder=6)

    _draw_log_pose_arrows(ax, px, py, margin, LOG_POSE_TARGETS)

    # ── Render to buffer ──────────────────────────────────────────────────────
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, facecolor=SEA_COLOR, pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    return buf
