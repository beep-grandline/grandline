import sqlite3

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
            id     TEXT PRIMARY KEY,
            name   TEXT,
            home_q INTEGER,
            home_r INTEGER,
            bounty INTEGER DEFAULT 0
        );
    """)
    db.commit()

# ── hex queries ───────────────────────────────────
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

# ── player queries ────────────────────────────────
def get_player(player_id):
    return db.execute(
        "SELECT * FROM players WHERE id=?", (player_id,)
    ).fetchone()

def get_all_players():
    return db.execute("SELECT * FROM players").fetchall()

def upsert_player(player_id, name):
    db.execute(
        "INSERT OR IGNORE INTO players (id, name) VALUES (?, ?)",
        (player_id, name)
    )
    db.commit()

def update_player_position(player_id, q, r):
    db.execute(
        "UPDATE players SET q=?, r=? WHERE id=?", (q, r, player_id)
    )
    db.commit()

# ── island queries ────────────────────────────────
def get_island(q, r):
    return db.execute(
        "SELECT * FROM islands WHERE q=? AND r=?", (q, r)
    ).fetchone()

# ── Currency management ────────────────────────────
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
    if player["berry"] < amount:
        return False  # not enough funds
    db.execute(
        "UPDATE players SET berry = berry - ? WHERE id=?", (amount, player_id)
    )
    db.commit()
    return True



# ── Crew management ────────────────────────────
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

def upsert_crew(crew_id, name):
    db.execute("""
        INSERT INTO crews (id, name)
        VALUES (?, ?)
        ON CONFLICT(id) DO UPDATE SET name=excluded.name
    """, (crew_id, name))
    db.commit()

init_db()  # runs on import, creates tables if they don't exist
