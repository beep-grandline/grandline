import sqlite3
import json
import time

db = sqlite3.connect("grandline.db", check_same_thread=False)
db.row_factory = sqlite3.Row

def init_db():
    db.executescript("""
        CREATE TABLE IF NOT EXISTS hexes (
            q             INTEGER NOT NULL,
            r             INTEGER NOT NULL,
            region        TEXT DEFAULT 'open_sea',
            terrain       TEXT DEFAULT 'sea',
            movement_cost INTEGER DEFAULT 1,
            hazard        TEXT,
            PRIMARY KEY (q, r)
        );

        CREATE TABLE IF NOT EXISTS islands (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            q       INTEGER NOT NULL,
            r       INTEGER NOT NULL,
            name    TEXT,
            type    TEXT,
            arc     TEXT,
            FOREIGN KEY (q, r) REFERENCES hexes(q, r)
        );

        CREATE TABLE IF NOT EXISTS players (
            id      TEXT PRIMARY KEY,
            name    TEXT,
            crew_id TEXT,
            q       INTEGER DEFAULT 0,
            r       INTEGER DEFAULT 0,
            role    TEXT DEFAULT 'pirate',
            bounty  INTEGER DEFAULT 0,
            hp      INTEGER DEFAULT 100,
            berry   INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS crews (
            id          TEXT PRIMARY KEY,
            name        TEXT,
            captain_id  TEXT,
            home_q      INTEGER,
            home_r      INTEGER,
            bounty      INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS battles (
            channel_id   TEXT PRIMARY KEY,
            fighter_a_id TEXT NOT NULL,
            fighter_b_id TEXT NOT NULL,
            state        TEXT NOT NULL,
            pending_a    TEXT,
            pending_b    TEXT,
            message_id   TEXT,
            last_updated REAL NOT NULL
        );
    """)
    db.commit()

    # ── Migrations — safe to run every startup, silently ignored if already applied
    for sql in  [
        "ALTER TABLE crews ADD COLUMN ship_hp     INTEGER DEFAULT 500",
        "ALTER TABLE battles ADD COLUMN battle_id TEXT",
        "ALTER TABLE crews ADD COLUMN ship_max_hp INTEGER DEFAULT 500",
        "ALTER TABLE players ADD COLUMN following_id TEXT DEFAULT 'ship'",
        "ALTER TABLE crews   ADD COLUMN q            INTEGER DEFAULT 0",
        "ALTER TABLE crews   ADD COLUMN r            INTEGER DEFAULT 0",
        "ALTER TABLE crews   ADD COLUMN roll         INTEGER DEFAULT 12",
        "ALTER TABLE crews   ADD COLUMN log_pose     TEXT    DEFAULT 'alabasta'",
        "ALTER TABLE crews   ADD COLUMN pose_type    TEXT    DEFAULT 'log'",
        "ALTER TABLE players ADD COLUMN max_hp       INTEGER DEFAULT 100",
    ]:
        try:
            db.execute(sql)
            db.commit()
        except Exception:
            pass  # column already exists

# ── Utility ───────────────────────────────────────────────────────────────────

def row_to_dict(row):
    """Convert a sqlite3.Row to a plain dict. Returns None if row is None.
    
    Use this whenever you need .get() or want to safely pass row data around.
    sqlite3.Row supports row["key"] but not row.get("key", default).
    """
    if row is None:
        return None
    return dict(row)

# ── Hex queries ───────────────────────────────────────────────────────────────

def get_hex(q, r):
    return db.execute(
        "SELECT * FROM hexes WHERE q=? AND r=?", (q, r)
    ).fetchone()

def get_all_hexes():
    return db.execute("SELECT * FROM hexes").fetchall()

def insert_hex(q, r, terrain="sea", region="open_sea"):
    db.execute("""
        INSERT OR IGNORE INTO hexes (q, r, terrain, region)
        VALUES (?, ?, ?, ?)
    """, (q, r, terrain, region))
    db.commit()

def insert_island(q, r, name, island_type="town", arc=None):
    db.execute("""
        INSERT OR IGNORE INTO islands (q, r, name, type, arc)
        VALUES (?, ?, ?, ?, ?)
    """, (q, r, name, island_type, arc))
    db.commit()

def get_all_islands():
    return db.execute("SELECT * FROM islands").fetchall()

# ── Player queries ────────────────────────────────────────────────────────────

def get_player(player_id):
    """Returns a sqlite3.Row or None. Use row["field"] not row.get()."""
    return db.execute(
        "SELECT * FROM players WHERE id=?", (player_id,)
    ).fetchone()

def get_player_position(player_id):
    """Returns (q, r) tuple, or None if player not found."""
    row = db.execute(
        "SELECT q, r FROM players WHERE id=?", (player_id,)
    ).fetchone()
    if not row:
        return None
    return (row["q"] if row["q"] is not None else 0,
            row["r"] if row["r"] is not None else 0)

def get_all_players():
    return db.execute("SELECT * FROM players").fetchall()

def upsert_player(player_id, name):
    db.execute(
        "INSERT OR IGNORE INTO players (id, name) VALUES (?, ?)",
        (player_id, name)
    )
    db.commit()

def delete_player(player_id):
    db.execute("DELETE FROM players WHERE id=?", (player_id,))
    db.commit()

def update_player_position(player_id, q, r):
    db.execute(
        "UPDATE players SET q=?, r=? WHERE id=?", (q, r, player_id)
    )
    db.commit()


def update_player_hp(player_id: str, hp: int):
    """Persist a player's current HP after battle."""
    db.execute("UPDATE players SET hp=? WHERE id=?", (hp, str(player_id)))
    db.commit()


def get_player_hp(player_id: str) -> tuple:
    """Returns (hp, max_hp) for the player, defaulting to (100, 100)."""
    row = db.execute(
        "SELECT hp, max_hp FROM players WHERE id=?", (str(player_id),)
    ).fetchone()
    if not row:
        return 100, 100
    return row["hp"] or 100, row["max_hp"] or 100


# ── Island queries ────────────────────────────────────────────────────────────

def get_island(q, r):
    return db.execute(
        "SELECT * FROM islands WHERE q=? AND r=?", (q, r)
    ).fetchone()

# ── Currency management ───────────────────────────────────────────────────────

def get_berry(player_id):
    player = db.execute(
        "SELECT berry FROM players WHERE id=?", (player_id,)
    ).fetchone()
    return player["berry"] if player else None

def set_berry(player_id, amount):
    db.execute(
        "UPDATE players SET berry=? WHERE id=?", (amount, player_id)
    )
    db.commit()

def add_berry(player_id, amount):
    db.execute(
        "UPDATE players SET berry = berry + ? WHERE id=?", (amount, player_id)
    )
    db.commit()

def remove_berry(player_id, amount):
    player = get_player(player_id)
    if not player or player["berry"] < amount:
        return False  # not found or not enough funds
    db.execute(
        "UPDATE players SET berry = berry - ? WHERE id=?", (amount, player_id)
    )
    db.commit()
    return True

# ── Crew management ───────────────────────────────────────────────────────────

def get_crew(crew_id):
    return db.execute(
        "SELECT * FROM crews WHERE id=?", (crew_id,)
    ).fetchone()

def delete_crew(crew_id):
    db.execute("UPDATE players SET crew_id=NULL WHERE crew_id=?", (crew_id,))
    db.execute("DELETE FROM crews WHERE id=?", (crew_id,))
    db.commit()

def get_crew_by_name(name):
    return db.execute(
        "SELECT * FROM crews WHERE LOWER(name)=LOWER(?)", (name,)
    ).fetchone()

def upsert_crew(crew_id, name, captain_id=None):
    db.execute("""
        INSERT INTO crews (id, name, captain_id)
        VALUES (?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,
            captain_id=COALESCE(excluded.captain_id, captain_id)
    """, (crew_id, name, captain_id))
    db.commit()

def set_player_crew(player_id, crew_id):
    """Set or clear a player's crew. Pass None to remove from crew."""
    db.execute(
        "UPDATE players SET crew_id=? WHERE id=?", (crew_id, player_id)
    )
    db.commit()

def get_crew_members(crew_id):
    return db.execute(
        "SELECT * FROM players WHERE crew_id=?", (crew_id,)
    ).fetchall()

def get_battle(battle_id):
    """Returns battle row as dict, or None."""
    row = db.execute(
        "SELECT * FROM battles WHERE battle_id=?", (battle_id,)
    ).fetchone()
    return row_to_dict(row)
 
 
def get_battle_by_player(player_id):
    """Returns any active battle involving this player, or None."""
    row = db.execute(
        "SELECT * FROM battles WHERE fighter_a_id=? OR fighter_b_id=?",
        (player_id, player_id)
    ).fetchone()
    return row_to_dict(row)
 
 
def create_battle(battle_id, channel_id, fighter_a_id, fighter_b_id, state, message_id=None):
    db.execute("""
        INSERT OR REPLACE INTO battles
            (battle_id, channel_id, fighter_a_id, fighter_b_id, state,
             pending_a, pending_b, message_id, last_updated)
        VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?)
    """, (battle_id, channel_id, fighter_a_id, fighter_b_id,
          json.dumps(state), message_id, time.time()))
    db.commit()
 
 
def update_battle_state(battle_id, state):
    """Persist updated state dict after a turn resolves."""
    db.execute("""
        UPDATE battles SET state=?, pending_a=NULL, pending_b=NULL, last_updated=?
        WHERE battle_id=?
    """, (json.dumps(state), time.time(), battle_id))
    db.commit()
 
 
def set_battle_message(battle_id, message_id):
    """Store the Discord message ID so bot.py can edit it each turn."""
    db.execute(
        "UPDATE battles SET message_id=? WHERE battle_id=?",
        (message_id, battle_id)
    )
    db.commit()
 
 
def set_pending_action(battle_id, side, action):
    """
    Record one player's chosen action for the turn.
    side: "a" | "b"
    action: ["attack", "Move Name"] | ["block", None] | ["dodge", None] | ["escape", None]
    Returns True if BOTH sides now have a pending action (turn ready to resolve).
    """
    col = "pending_a" if side == "a" else "pending_b"
    db.execute(
        f"UPDATE battles SET {col}=?, last_updated=? WHERE battle_id=?",
        (json.dumps(action), time.time(), battle_id)
    )
    db.commit()
 
    row = db.execute(
        "SELECT pending_a, pending_b FROM battles WHERE battle_id=?",
        (battle_id,)
    ).fetchone()
    return row is not None and row["pending_a"] is not None and row["pending_b"] is not None
 
 
def get_pending_actions(battle_id):
    """
    Returns (action_a, action_b) as Python lists, or None for each if not yet submitted.
    Call after set_pending_action returns True.
    """
    row = db.execute(
        "SELECT pending_a, pending_b FROM battles WHERE battle_id=?",
        (battle_id,)
    ).fetchone()
    if not row:
        return None, None
    pa = json.loads(row["pending_a"]) if row["pending_a"] else None
    pb = json.loads(row["pending_b"]) if row["pending_b"] else None
    return pa, pb
 
 
def get_battle_state(battle_id):
    """Returns the state dict for a battle, or None."""
    row = db.execute(
        "SELECT state FROM battles WHERE battle_id=?", (battle_id,)
    ).fetchone()
    return json.loads(row["state"]) if row else None
 
 
def delete_battle(battle_id):
    db.execute("DELETE FROM battles WHERE battle_id=?", (battle_id,))
    db.commit()
 
 
def get_stale_battles(timeout_seconds=1800):
    """Returns list of battle dicts inactive for longer than timeout_seconds."""
    cutoff = time.time() - timeout_seconds
    rows = db.execute(
        "SELECT * FROM battles WHERE last_updated < ?", (cutoff,)
    ).fetchall()
    return [row_to_dict(r) for r in rows]

def get_player_moves(player_id):
    """Returns the player's move list, or [] if none."""
    row = db.execute(
        "SELECT moves_json FROM players WHERE id=?", (player_id,)
    ).fetchone()
    if not row or not row["moves_json"]:
        return []
    return json.loads(row["moves_json"])
 
 
def set_player_moves(player_id, moves):
    """Replace the player's entire move list."""
    db.execute(
        "UPDATE players SET moves_json=? WHERE id=?",
        (json.dumps(moves), player_id)
    )
    db.commit()
 
 
def add_player_move(player_id, move_dict):
    """
    Append a move. Returns False if a move with that name already exists,
    True on success.
    """
    moves = get_player_moves(player_id)
    if any(m["name"].lower() == move_dict["name"].lower() for m in moves):
        return False
    moves.append(move_dict)
    set_player_moves(player_id, moves)
    return True
 
 
def remove_player_move(player_id, move_name):
    """
    Remove a move by name (case-insensitive).
    Returns False if not found, True on success.
    """
    moves     = get_player_moves(player_id)
    new_moves = [m for m in moves if m["name"].lower() != move_name.lower()]
    if len(new_moves) == len(moves):
        return False
    set_player_moves(player_id, new_moves)
    return True
 
 
# ── Fighter stat management (called by /gm setstats) ─────────────────────────
 
def set_fighter_stats(player_id, atk=None, defense=None, spd=None,
                      block_name=None, dodge_name=None, hp=None):
    """Update any combination of fighter stats. None values are skipped."""
    fields = []
    values = []
    for col, val in [("atk", atk), ("defense", defense), ("spd", spd),
                     ("block_name", block_name), ("dodge_name", dodge_name),
                     ("hp", hp)]:
        if val is not None:
            fields.append(f"{col}=?")
            values.append(val)
    if not fields:
        return
    values.append(player_id)
    db.execute(f"UPDATE players SET {', '.join(fields)} WHERE id=?", values)
    db.commit()
 
 
def set_player_fruit(player_id, fruit_id):
    """Assign a devil fruit to a player by fruit ID."""
    db.execute("UPDATE players SET fruit_id=? WHERE id=?", (fruit_id, player_id))
    db.commit()
 
 
def get_player_fruit(player_id):
    """Returns the player's fruit_id string, or None."""
    row = db.execute(
        "SELECT fruit_id FROM players WHERE id=?", (player_id,)
    ).fetchone()
    return row["fruit_id"] if row else None
 

def set_profile(player_id, char_name=None, fighting_style=None, summary=None, epithet=None):
    """Update profile fields. None values are skipped."""
    fields = []
    values = []
    for col, val in [("char_name", char_name), ("epithet", epithet),
                 ("fighting_style", fighting_style), ("summary", summary)]:
        if val is not None:
            fields.append(f"{col}=?")
            values.append(val)
    if not fields:
        return
    values.append(player_id)
    db.execute(f"UPDATE players SET {', '.join(fields)} WHERE id=?", values)
    db.commit()

def get_held_fruit(player_id):
    """Returns the fruit_id string of the held (uneaten) fruit, or None."""
    row = db.execute(
        "SELECT held_fruit_id FROM players WHERE id=?", (player_id,)
    ).fetchone()
    return row["held_fruit_id"] if row else None
 
 
def set_held_fruit(player_id, fruit_id):
    db.execute(
        "UPDATE players SET held_fruit_id=? WHERE id=?", (fruit_id, player_id)
    )
    db.commit()
 
 
def clear_held_fruit(player_id):
    db.execute(
        "UPDATE players SET held_fruit_id=NULL WHERE id=?", (player_id,)
    )
    db.commit()
 
 
def eat_fruit(player_id):
    """
    Moves held_fruit_id → fruit_id.
    Returns (True, fruit_id) on success.
    Returns (False, "no_held_fruit") or (False, "already_eaten") on failure.
    """
    row = db.execute(
        "SELECT fruit_id, held_fruit_id FROM players WHERE id=?", (player_id,)
    ).fetchone()
    if not row or not row["held_fruit_id"]:
        return False, "no_held_fruit"
    if row["fruit_id"]:
        return False, "already_eaten"
    db.execute(
        "UPDATE players SET fruit_id=?, held_fruit_id=NULL WHERE id=?",
        (row["held_fruit_id"], player_id)
    )
    db.commit()
    return True, row["held_fruit_id"]
 
 
# ── Inventory ─────────────────────────────────────────────────────────────────
# Each item: {"name": str, "qty": int, "keywords": [str]}
 
def get_inventory(player_id):
    """Returns the inventory list, or []."""
    row = db.execute(
        "SELECT inventory FROM players WHERE id=?", (player_id,)
    ).fetchone()
    if not row or not row["inventory"]:
        return []
    return json.loads(row["inventory"])
 
 
def set_inventory(player_id, items):
    db.execute(
        "UPDATE players SET inventory=? WHERE id=?",
        (json.dumps(items), player_id)
    )
    db.commit()
 
 
def add_inventory_item(player_id, name, qty=1, keywords=None):
    """
    Adds qty of an item. Stacks if name already exists.
    Returns the updated inventory list.
    """
    items = get_inventory(player_id)
    for item in items:
        if item["name"].lower() == name.lower():
            item["qty"] += qty
            set_inventory(player_id, items)
            return items
    items.append({"name": name, "qty": qty, "keywords": keywords or []})
    set_inventory(player_id, items)
    return items
 
 
def remove_inventory_item(player_id, name, qty=1):
    """
    Removes qty of an item by name.
    Removes the entry entirely if qty reaches 0.
    Returns (True, remaining_qty) or (False, 0) if not found.
    """
    items = get_inventory(player_id)
    for i, item in enumerate(items):
        if item["name"].lower() == name.lower():
            item["qty"] -= qty
            if item["qty"] <= 0:
                items.pop(i)
                set_inventory(player_id, items)
                return True, 0
            set_inventory(player_id, items)
            return True, item["qty"]
    return False, 0

def set_crew_details(crew_id, description=None, jolly_roger_url=None,
                          ship_name=None, ship_url=None, motto=None):
         fields = []; values = []
         for col, val in [("description", description),
                          ("jolly_roger_url", jolly_roger_url),
                          ("ship_name", ship_name),
                          ("ship_url", ship_url),
                          ("motto", motto)]:
             if val is not None:
                 fields.append(f"{col}=?"); values.append(val)
         if not fields: return
         values.append(crew_id)
         db.execute(f"UPDATE crews SET {', '.join(fields)} WHERE id=?", values)
         db.commit()

# ═══════════════════════════════════════════════════════════════════════════════
#  db_game_additions.py  ·  Paste these into db.py
#
#  Add to migrations list in init_db():
#      "ALTER TABLE players ADD COLUMN following_id TEXT DEFAULT 'ship'",
#      "ALTER TABLE crews   ADD COLUMN q            INTEGER DEFAULT 0",
#      "ALTER TABLE crews   ADD COLUMN r            INTEGER DEFAULT 0",
#      "ALTER TABLE crews   ADD COLUMN roll         INTEGER DEFAULT 12",
#      "ALTER TABLE crews   ADD COLUMN log_pose     TEXT    DEFAULT 'alabasta'",
# ═══════════════════════════════════════════════════════════════════════════════


# ── Player following state ────────────────────────────────────────────────────

def set_following(player_id, following_id):
    """
    Set the player's following_id.
      'ship'     → follows crew ship
      player_id  → follows a specific player
      None       → moves independently
    """
    db.execute(
        "UPDATE players SET following_id=? WHERE id=?",
        (following_id, player_id)
    )
    db.commit()


# ── Crew movement ─────────────────────────────────────────────────────────────

def move_crew(crew_id, q, r):
    db.execute(
        "UPDATE crews SET q=?, r=? WHERE id=?", (q, r, crew_id)
    )
    db.commit()


def get_crew_position(crew_id):
    row = db.execute(
        "SELECT q, r FROM crews WHERE id=?", (crew_id,)
    ).fetchone()
    return (row["q"] or 0, row["r"] or 0) if row else (0, 0)


# ── Crew rolls ────────────────────────────────────────────────────────────────

def spend_crew_roll(crew_id, amount=1):
    db.execute(
        "UPDATE crews SET roll = MAX(0, roll - ?) WHERE id=?",
        (amount, crew_id)
    )
    db.commit()


def set_crew_roll(crew_id, amount):
    db.execute(
        "UPDATE crews SET roll=? WHERE id=?", (amount, crew_id)
    )
    db.commit()


def get_all_crews():
    """Returns all crew rows — used by roll replenishment task."""
    return db.execute("SELECT * FROM crews").fetchall()

def get_ship_hp(crew_id):
    row = db.execute("SELECT ship_hp, ship_max_hp FROM crews WHERE id=?", (crew_id,)).fetchone()
    return (row["ship_hp"] or 500, row["ship_max_hp"] or 500) if row else (500, 500)

def damage_ship(crew_id, amount):
    db.execute("UPDATE crews SET ship_hp = MAX(0, ship_hp - ?) WHERE id=?", (amount, crew_id))
    db.commit()
    return db.execute("SELECT ship_hp FROM crews WHERE id=?", (crew_id,)).fetchone()["ship_hp"]

def repair_ship(crew_id, amount=None):
    if amount is None:
        db.execute("UPDATE crews SET ship_hp = ship_max_hp WHERE id=?", (crew_id,))
    else:
        db.execute("UPDATE crews SET ship_hp = MIN(ship_max_hp, ship_hp + ?) WHERE id=?", (amount, crew_id))
    db.commit()
    return db.execute("SELECT ship_hp FROM crews WHERE id=?", (crew_id,)).fetchone()["ship_hp"]


# ── Log pose ──────────────────────────────────────────────────────────────────

def set_log_pose(crew_id, island_name, pose_type="log"):
    db.execute(
        "UPDATE crews SET log_pose=?, pose_type=? WHERE id=?",
        (island_name, pose_type, crew_id)
    )
    db.commit()

init_db()  # runs on import, creates tables if they don't exist
