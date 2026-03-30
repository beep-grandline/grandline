from PIL import Image, ImageDraw
import math
import db

SIZE = 100
RADIUS = 4
SQRT3 = math.sqrt(3)

TERRAIN_COLORS = {
    "sea":       (24, 152, 213),
    "island":    (24, 152, 213),
    "forest":    ( 42, 107,  58),
    "desert":    (200, 164,  74),
    "snow":      (138, 184, 204),
    "volcano":   (139,  42,  16),
    "redline":   ( 58,   8,   8),
    "grandline": ( 60, 100, 180),
}

BG_COLOR = (24, 152, 213)

def hex_to_pixel(q, r):
    x = SIZE * SQRT3 * (q + r / 2)
    y = SIZE * 1.5 * r
    return x, y

def hex_corners(cx, cy):
    corners = []
    for i in range(6):
        angle = math.pi / 3 * i + math.pi / 6
        corners.append((
            cx + SIZE * math.cos(angle),
            cy + SIZE * math.sin(angle)
        ))
    return corners

def hex_distance(q1, r1, q2, r2):
    return max(abs(q1-q2), abs(r1-r2), abs((q1+r1)-(q2+r2)))

def render_map(player_id, radius=RADIUS):
    player = db.get_player(player_id)
    if not player:
        return None

    pq, pr = player["q"], player["r"]

    # collect hex-radius circle as before
    hexes = []
    for q in range(pq - radius, pq + radius + 1):
        for r in range(pr - radius, pr + radius + 1):
            if hex_distance(q, r, pq, pr) <= radius:
                hex = db.get_hex(q, r)
                hexes.append(hex if hex else {"q": q, "r": r, "terrain": "sea"})

    if not hexes:
        return None

    pixels = [hex_to_pixel(h["q"], h["r"]) for h in hexes]
    min_x = min(p[0] for p in pixels) - SIZE * 2
    min_y = min(p[1] for p in pixels) - SIZE * 2
    max_x = max(p[0] for p in pixels) + SIZE * 2
    max_y = max(p[1] for p in pixels) + SIZE * 2

    w = int(max_x - min_x)
    h = int(max_y - min_y)

    img = Image.new("RGB", (w, h), BG_COLOR)
    draw = ImageDraw.Draw(img)

    for hex in hexes:
        cx, cy = hex_to_pixel(hex["q"], hex["r"])
        cx -= min_x
        cy -= min_y
        corners = hex_corners(cx, cy)
        color = TERRAIN_COLORS.get(hex["terrain"], TERRAIN_COLORS["sea"])
        draw.polygon(corners, fill=color)
        draw.line(corners + [corners[0]], fill=(180, 200, 220), width=4)

        island = db.get_island(hex["q"], hex["r"])
        if island:
            draw.text((cx, cy), island["name"][:8], fill=(255, 255, 255), anchor="mm")

    # draw player markers
    all_players = db.get_all_players()
    for p in all_players:
        if hex_distance(p["q"], p["r"], pq, pr) <= radius:
            cx, cy = hex_to_pixel(p["q"], p["r"])
            cx -= min_x
            cy -= min_y
            r_px = SIZE * 0.4
            draw.ellipse([cx-r_px, cy-r_px, cx+r_px, cy+r_px], fill=(240, 208, 96))
            draw.text((cx, cy), p["name"][0], fill=(0, 0, 0), anchor="mm")

    # crop to a centered rectangle
    cx_img = w // 2
    cy_img = h // 2
    crop_w = int(SIZE * SQRT3 * radius * 1.8)
    crop_h = int(SIZE * 1.5 * radius * 1.8)
    left   = max(0, cx_img - crop_w // 2)
    top    = max(0, cy_img - crop_h // 2)
    right  = min(w, cx_img + crop_w // 2)
    bottom = min(h, cy_img + crop_h // 2)
    img = img.crop((left, top, right, bottom))

    img.save("map_snapshot.png")
    return "map_snapshot.png"
