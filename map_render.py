from PIL import Image, ImageDraw, ImageFont
import math
import db

SIZE = 20  # hex size in pixels
SQRT3 = math.sqrt(3)

TERRAIN_COLORS = {
    "sea":       (26,  63, 107),
    "island":    (201,148, 58),
    "forest":    (42, 107, 58),
    "desert":    (200,164, 74),
    "snow":      (138,184,204),
    "volcano":   (139, 42, 16),
    "redline":   (58,   8,  8),
    "grandline": (22,  42, 82),
}

def hex_to_pixel(q, r):
    x = SIZE * (1.5 * q)
    y = SIZE * SQRT3 * (r + (0.5 if q % 2 == 1 else 0))
    return x, y

def hex_corners(cx, cy):
    corners = []
    for i in range(6):
        angle = math.pi / 3 * i
        corners.append((
            cx + SIZE * math.cos(angle),
            cy + SIZE * math.sin(angle)
        ))
    return corners

def render_map(player_id, radius=5):
    player = db.get_player(player_id)
    if not player:
        return None

    pq, pr = player["q"], player["r"]

    # collect hexes within radius of player
    hexes = []
    for q in range(pq - radius, pq + radius + 1):
        for r in range(pr - radius, pr + radius + 1):
            if abs(q - pq) + abs(r - pr) + abs((q + r) - (pq + pr)) <= radius * 2:
                hex = db.get_hex(q, r)
                if hex:
                    hexes.append(hex)

    # figure out canvas size
    pixels = [hex_to_pixel(h["q"], h["r"]) for h in hexes]
    min_x = min(p[0] for p in pixels) - SIZE * 2
    min_y = min(p[1] for p in pixels) - SIZE * 2
    max_x = max(p[0] for p in pixels) + SIZE * 2
    max_y = max(p[1] for p in pixels) + SIZE * 2

    w = int(max_x - min_x)
    h = int(max_y - min_y)

    img = Image.new("RGB", (w, h), (2, 10, 20))
    draw = ImageDraw.Draw(img)

    for hex in hexes:
        cx, cy = hex_to_pixel(hex["q"], hex["r"])
        cx -= min_x
        cy -= min_y
        corners = hex_corners(cx, cy)
        color = TERRAIN_COLORS.get(hex["terrain"], TERRAIN_COLORS["sea"])
        draw.polygon(corners, fill=color, outline=(255, 255, 255, 30))

        # draw island name if it has one
        island = db.get_island(hex["q"], hex["r"])
        if island:
            draw.text((cx, cy), island["name"][:8], fill=(255,255,255), anchor="mm")

    # draw player marker
    all_players = db.get_all_players()
    for p in all_players:
        if abs(p["q"] - pq) <= radius and abs(p["r"] - pr) <= radius:
            cx, cy = hex_to_pixel(p["q"], p["r"])
            cx -= min_x
            cy -= min_y
            r_px = SIZE * 0.4
            draw.ellipse([cx-r_px, cy-r_px, cx+r_px, cy+r_px], fill=(240, 208, 96))
            draw.text((cx, cy), p["name"][0], fill=(0,0,0), anchor="mm")

    img.save("map_snapshot.png")
    return "map_snapshot.png"
