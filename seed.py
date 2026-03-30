import db

def seed():
    COLS = 70
    ROWS = 270
    # put 0,0 at column 12 from left, middle height
    ORIGIN_COL = 12
    ORIGIN_ROW = ROWS // 2
    
    for col in range(COLS):
        for row in range(ROWS):
            q, r = offset_to_axial(col - ORIGIN_COL, row - ORIGIN_ROW)
            db.db.execute("""
                INSERT OR IGNORE INTO hexes (q, r, terrain, region)
                VALUES (?, ?, 'sea', 'open_sea')
            """, (q, r))
    
    db.db.commit()
    print("Grid filled.")
    
    # then define your islands on top
    islands = [
        # (q, r, terrain, region, island_name, island_type, arc)
        (35, 10, "island", "grand_line", "Twin Capes",     "town",       "east_blue"),
        (35, 20, "desert", "grand_line", "Whiskey Peak",   "town",       "alabasta"),
        (35, 30, "forest", "grand_line", "Little Garden",  "wilderness", "alabasta"),
        (35, 40, "snow",   "grand_line", "Drum Island",    "town",       "alabasta"),
        (35, 50, "desert", "grand_line", "Alabasta",       "town",       "alabasta"),
        # add more here...
    ]

    for (q, r, terrain, region, name, itype, arc) in islands:
        # update the hex terrain
        db.db.execute("""
            INSERT OR REPLACE INTO hexes (q, r, terrain, region)
            VALUES (?, ?, ?, ?)
        """, (q, r, terrain, region))
        # insert the island metadata
        db.db.execute("""
            INSERT OR IGNORE INTO islands (q, r, name, type, arc)
            VALUES (?, ?, ?, ?, ?)
        """, (q, r, name, itype, arc))

    db.db.commit()
    print(f"Seeded {len(islands)} islands.")

def offset_to_axial(col, row):
    q = col
    r = row - (col - (col % 2)) // 2
    return q, r

if __name__ == "__main__":
    seed()
