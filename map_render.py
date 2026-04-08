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
    "sea":       "#90d9ed",
}

BORDER_COLOR  = "#f0f8ff"
BORDER_WIDTH  = 1.5
PLAYER_COLOR  = "#F0D060"
LABEL_COLOR   = "#171717"
SEA_COLOR     = TERRAIN_COLORS["sea"]

# Player ship icon — loaded once, falls back to dot if file missing.
# SHIP_ROTATION: number of 90° counter-clockwise turns (1=90°, 2=180°, 3=270°)
SHIP_ROTATION  = 3
SHIP_ICON_SIZE = 34   # display size in pixels — tweak to taste

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


# ── Public API ────────────────────────────────────────────────────────────────

def render_map(uid: str, radius: int = 10):
    """
    Render a viewport map centred on the player's position.

    Returns a BytesIO PNG buffer, or None if the player isn't registered.
    The caller is responsible for reading the buffer (it is rewound to 0).
    """
    import db  # local import to avoid circular dependency at module level

    player = db.get_player(uid)
    if not player:
        return None

    # sqlite3.Row supports index access but not .get() — use [] with fallback
    pq = player["q"] if player["q"] is not None else 0
    pr = player["r"] if player["r"] is not None else 0

    _load_map()
    hex_lookup = _cache["hex_lookup"]
    labels     = _cache["labels"]

    # ── Collect hexes in viewport ─────────────────────────────────────────────
    land_patches = []
    land_colors  = []
    border_segs  = []   # land-sea border edges
    sea_segs     = []   # sea-sea grid edges (thin outline)
    label_data   = []   # (x, y, text) triples

    for q in range(pq - radius, pq + radius + 1):
        for r in range(pr - radius, pr + radius + 1):
            if _hex_distance(q, r, pq, pr) > radius:
                continue

            terrain = hex_lookup.get((q, r), "sea")
            cx, cy  = _hex_to_pixel(q, r)
            corners = _hex_corners(q, r)

            if terrain == "sea":
                # Only draw edges that face another in-viewport sea hex or the
                # viewport boundary — avoids double-drawing every shared edge
                for (dq, dr), (i1, i2) in NEIGHBOR_TO_EDGE.items():
                    nq, nr = q + dq, r + dr
                    if _hex_distance(nq, nr, pq, pr) <= radius:
                        # Only add the edge once (when dq>0, or dq==0 and dr>0)
                        if dq > 0 or (dq == 0 and dr > 0):
                            p1, p2 = corners[i1], corners[i2]
                            sea_segs.append([p1, p2])
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
    fig, ax = plt.subplots(figsize=(10, 10), facecolor=SEA_COLOR)
    ax.set_aspect("equal")
    ax.axis("off")

    # Sea grid — drawn first so land sits on top
    if sea_segs:
        ax.add_collection(LineCollection(
            sea_segs,
            colors=(1.0, 1.0, 1.0, 0.25),
            linewidths=0.5,
            zorder=1,
        ))

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
    px, py = _hex_to_pixel(pq, pr)
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
    margin = SIZE * radius * 1.1
    ax.set_xlim(px - margin, px + margin)
    ax.set_ylim(py - margin, py + margin)

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
