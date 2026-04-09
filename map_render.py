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

# Log pose targets — (q, r) tuples the arrow points toward.
# Replace with dynamic data later (e.g. from db or game state).
LOG_POSE_TARGETS = [(32, 10)]

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
    "labels":     {},   # (q, r) -> label string  (island_name or hex_label)
}


def _load_map():
    """Load map JSON into module-level cache. No-op if file unchanged."""
    try:
        mtime = os.path.getmtime(MAP_PATH)
    except FileNotFoundError:
        return

    if mtime == _cache["mtime"]:
        return  # already up to date

    with open(MAP_PATH, "r") as f:
        data = json.load(f)

    hex_lookup = {}
    labels     = {}

    for tile in data.get("tiles", []):
        q, r = tile.get("q"), tile.get("r")
        if q is None or r is None:
            continue
        hex_type = tile.get("hex_type", "sea")
        hex_lookup[(q, r)] = hex_type

        # Use hex_label if present, otherwise fall back to island_name
        label = tile.get("hex_label") or tile.get("island_name") or ""
        if label:
            labels[(q, r)] = label

    _cache["mtime"]      = mtime
    _cache["hex_lookup"] = hex_lookup
    _cache["labels"]     = labels


# ── Geometry helpers ──────────────────────────────────────────────────────────

def _hex_to_pixel(q, r):
    """Axial → pixel centre (pointy-top)."""
    return (
        SIZE * SQRT3 * (q + r / 2),
        SIZE * 1.5   * r,
    )


def _hex_corners(q, r):
    """Return the 6 corner (x, y) points of a hex."""
    cx, cy = _hex_to_pixel(q, r)
    return [
        (cx + SIZE * math.cos(math.pi / 3 * i - math.pi / 6),
         cy + SIZE * math.sin(math.pi / 3 * i - math.pi / 6))
        for i in range(6)
    ]


def _hex_distance(q1, r1, q2, r2):
    return max(abs(q1 - q2), abs(r1 - r2), abs((q1 + r1) - (q2 + r2)))


# ── Log pose arrow helper ─────────────────────────────────────────────────────

def _draw_log_pose_arrows(ax, px, py, margin, targets):
    """
    For each target (tq, tr), draw a compass-style arrow on the viewport edge
    pointing toward that hex. Skipped if the target is inside the viewport.
    """
    ARROW_FILL   = (1.0, 1.0, 1.0, 0.75)   # translucent white fill
    ARROW_EDGE   = (0.35, 0.35, 0.35, 0.9)  # lightened dark outline
    ARROW_INSET  = margin * 0.07            # tip inset from viewport edge
    ARROW_SIZE   = margin * 0.09            # overall scale of the arrow

    # Base shape pointing in +y direction, normalized to ARROW_SIZE.
    # 4 points: tip, lower-right outer, notch center (chevron), lower-left outer.
    # The notch pulls the base center inward, creating the cursor silhouette.
    BASE_SHAPE = [
        ( 0.00,  1.00),   # tip
        ( 0.48, -0.38),   # lower-right outer wing
        ( 0.00,  0.08),   # notch center (chevron indent)
        (-0.48, -0.38),   # lower-left outer wing
    ]

    for (tq, tr) in targets:
        tx, ty = _hex_to_pixel(tq, tr)
        dx, dy = tx - px, ty - py

        # Skip if target is already visible in the viewport
        if abs(dx) <= margin and abs(dy) <= margin:
            continue

        dist = math.hypot(dx, dy)
        if dist == 0:
            continue
        nx, ny = dx / dist, dy / dist

        # Find intersection of direction ray with viewport boundary
        if abs(nx) < 1e-9:
            t_hit = margin / abs(ny)
        elif abs(ny) < 1e-9:
            t_hit = margin / abs(nx)
        else:
            t_hit = min(margin / abs(nx), margin / abs(ny))

        # Arrow tip position (inset from edge)
        tip_x = px + nx * (t_hit - ARROW_INSET)
        tip_y = py + ny * (t_hit - ARROW_INSET)

        # Rotation angle: our base shape points in +y, rotate to face (nx, ny)
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
    hex_lookup = _cache["hex_lookup"]
    labels     = _cache["labels"]

    # ── Collect hexes in viewport ─────────────────────────────────────────────
    land_patches      = []
    land_colors       = []
    border_segs       = []
    sea_segs          = []
    label_data        = []
    reachable_centers = []  # roll view — (cx, cy) of reachable sea hexes

    for q in range(pq - radius, pq + radius + 1):
        for r in range(pr - radius, pr + radius + 1):
            if _hex_distance(q, r, pq, pr) > radius:
                continue

            terrain = hex_lookup.get((q, r), "sea")
            cx, cy  = _hex_to_pixel(q, r)
            corners = _hex_corners(q, r)

            if terrain == "sea":
                # Sea grid edges
                for (dq, dr), (i1, i2) in NEIGHBOR_TO_EDGE.items():
                    nq, nr = q + dq, r + dr
                    if _hex_distance(nq, nr, pq, pr) <= radius:
                        if dq > 0 or (dq == 0 and dr > 0):
                            p1, p2 = corners[i1], corners[i2]
                            sea_segs.append([p1, p2])

                # Roll view — collect center for dot marker
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

            # Label — only on non-redline, non-calm_belt tiles
            if terrain not in ("redline", "calm_belt") and (q, r) in labels:
                label_data.append((cx, cy, labels[(q, r)]))

            # Border edges where land meets sea
            for (dq, dr), (i1, i2) in NEIGHBOR_TO_EDGE.items():
                nq, nr = q + dq, r + dr
                if hex_lookup.get((nq, nr), "sea") == "sea":
                    p1, p2 = corners[i1], corners[i2]
                    border_segs.append([p1, p2])

    # ── Build figure ──────────────────────────────────────────────────────────
    px, py = _hex_to_pixel(pq, pr)
    margin  = SIZE * radius * 1.1

    fig, ax = plt.subplots(figsize=(10, 10), facecolor=SEA_COLOR)
    ax.set_aspect("equal")
    ax.axis("off")

    # Ocean texture — frequencies scaled to actual map data units (~±33 range)
    _ox = np.linspace(px - margin, px + margin, 300)
    _oy = np.linspace(py - margin, py + margin, 300)
    _X, _Y = np.meshgrid(_ox, _oy)
    _Z = np.zeros_like(_X)
    for _i in range(4):
        _f = 1.8 ** _i
        _a = 1.0 / _f
        _Z += _a * np.sin(_X * 0.09 * _f + _Y * 0.055 * _f * 0.7)
        _Z += _a * np.cos(_X * 0.045 * _f * 0.8 - _Y * 0.07 * _f)

    # Shallow water — subtract a bump near island/redline hexes to pull
    # coastal Z values toward the minimum, which maps to the lightest color band
    _fade_radius = SIZE * 2.5
    _shallow = np.zeros_like(_Z)
    for (_tq, _tr), _terrain in hex_lookup.items():
        if _terrain in ("sea", "calm_belt"):
            continue
        if _hex_distance(_tq, _tr, pq, pr) > radius:
            continue
        _ix, _iy = _hex_to_pixel(_tq, _tr)
        _dist = np.sqrt((_X - _ix) ** 2 + (_Y - _iy) ** 2)
        _bump = np.clip(1.0 - _dist / _fade_radius, 0, 1) ** 2
        _shallow = np.maximum(_shallow, _bump)
    # Normalize first so wave bands are evenly distributed
    _zmin, _zmax = _Z.min(), _Z.max()
    _Z = (_Z - _zmin) / (_zmax - _zmin + 1e-9)

    # Now push coastal values toward 0 (lightest band) — happens after normalize
    # so it isn't rescaled away
    _Z -= _shallow * 0.45
    _Z = np.clip(_Z, 0, 1)

    ax.contourf(
        _X, _Y, _Z,
        levels=4,
        colors=["#75e1ff", "#6dd4f5", "#65c9eb", "#5cbde0", "#54b2d6"],
        zorder=0,
    )

    # Sea grid — drawn first so land sits on top
    if sea_segs:
        ax.add_collection(LineCollection(
            sea_segs,
            colors=(1.0, 1.0, 1.0, 0.18),
            linewidths=SEA_GRID_WIDTH,
            zorder=1,
        ))

    # Roll view — small dot in each reachable sea hex
    if view == "roll" and reachable_centers:
        xs, ys = zip(*reachable_centers)
        ax.scatter(
            xs, ys,
            s=18,                          # dot size in points² — tweak to taste
            color=(1.0, 1.0, 1.0, 0.55),  # semi-transparent white
            linewidths=0,
            zorder=2,
        )

    # Land hexes — single draw call via PatchCollection
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

    # Border edges — single draw call via LineCollection
    if border_segs:
        lc = LineCollection(
            border_segs,
            colors=BORDER_COLOR,
            linewidths=BORDER_WIDTH,
            capstyle="round",
            zorder=3,
        )
        ax.add_collection(lc)

    # Labels
    for (lx, ly, text) in label_data:
        ax.text(
            lx, ly, text,
            ha="center", va="center",
            fontsize=7, color=LABEL_COLOR,
            fontweight="bold", clip_on=True,
        )

    # Player marker — ship icon if available, dot fallback otherwise
    icon = _get_ship_icon()
    if icon is not None:
        # OffsetImage sizes in pixels, unaffected by axes data scaling —
        # no stretch regardless of the hex grid's x/y unit ratio
        oi = OffsetImage(icon, zoom=SHIP_ICON_SIZE / max(icon.shape[:2]))
        oi.image.axes = ax
        ab = AnnotationBbox(
            oi, (px, py),
            frameon=False,
            pad=0,
            zorder=5,
        )
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

    # Viewport
    ax.set_xlim(px - margin, px + margin)
    ax.set_ylim(py - margin, py + margin)

    # Log pose arrows — one per target, drawn at viewport edge pointing inward/outward
    _draw_log_pose_arrows(ax, px, py, margin, LOG_POSE_TARGETS)

    # ── Render to buffer and clean up ─────────────────────────────────────────
    buf = io.BytesIO()
    fig.savefig(
        buf, format="png", dpi=150,
        bbox_inches="tight",
        facecolor=SEA_COLOR,
        pad_inches=0,
    )
    plt.close(fig)   # free memory — critical in a long-running bot
    buf.seek(0)
    return buf
