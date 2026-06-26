# ═══════════════════════════════════════════════════════════════════════════════
#  game.py  ·  Core game logic — coordinates, movement, rolls.
#  Import this everywhere instead of reading q/r directly from the DB.
# ═══════════════════════════════════════════════════════════════════════════════

import datetime
import random as _random

import db

# ── Constants ─────────────────────────────────────────────────────────────────

HEX_DIRECTIONS = {
    "f":  ( 1,  0),
    "b":  (-1,  0),
    "fr": ( 1, -1),
    "br": ( 0, -1),
    "fl": ( 0,  1),
    "bl": (-1,  1),
}

DIRECTION_LABELS = {
    "f":  "Forward (East)",
    "b":  "Backward (West)",
    "fl": "Forward-Port (NE)",
    "bl": "Backward-Port (NW)",
    "fr": "Forward-Starboard (SE)",
    "br": "Backward-Starboard (SW)",
}

ROLL_MAX           = 12
ROLL_REGEN_MINUTES = 60   # one roll added per interval
ROLL_REGEN_AMOUNT  = 1

# Walk rolls — on-foot stamina, regenerates like ship rolls
WALK_ROLL_MAX      = 4    # natural regen cap
WALK_ROLL_OVERFILL = 8    # hard cap with stamina meals
STAMINA_MEAL_ROLLS = 4    # walk rolls granted by a stamina meal

# Meal effects
HEARTY_BUFF_MULT     = 1.10   # +10% atk/def/spd for the next battle
HP_REGEN_PER_HOUR    = 5      # natural recovery
HP_REGEN_BOOSTED     = 15     # with an active recovery meal
RECOVERY_MEAL_HOURS  = 4      # how long a recovery meal lasts

CALM_BELT_R = 36          # abs(r) > this is impassable calm belt

# Hard-blocked tiles — never passable regardless of terrain
# (-1, 0) plugs the Reverse Mountain waterfall.
BLOCKED_TILES = {(-1, 0)}

DEFAULT_LOG_POSE = "alabasta"

# Impel Down — reserved hex, rendered gray, used as marine prison destination
IMPEL_DOWN_Q = 180
IMPEL_DOWN_R = 0

# ── Position resolver ─────────────────────────────────────────────────────────

def get_position(player_id, _depth=0):
    """
    Returns (q, r) for a player based on their following_id:
      'ship'     → crew's q/r
      player_id  → that player's resolved position (captain follow)
      None       → own q/r
    _depth guards against circular follow chains.
    """
    if _depth > 5:
        return 0, 0

    player = db.get_player(str(player_id))
    if not player:
        return 0, 0

    fid = player["following_id"]

    if fid == "ship":
        if player["crew_id"]:
            crew = db.get_crew(player["crew_id"])
            if crew:
                return crew["q"] or 0, crew["r"] or 0
        # no crew — fall through to own position
    elif fid:
        return get_position(fid, _depth + 1)

    return player["q"] or 0, player["r"] or 0


# ── Passability ───────────────────────────────────────────────────────────────

def is_passable(q, r):
    """Returns False for calm belt, islands, redlines, and blocked tiles."""
    if (q, r) in BLOCKED_TILES:
        return False
    if abs(r) > CALM_BELT_R:
        return False
    try:
        from map_render import _cache, _load_map
        _load_map()
        terrain = _cache["hex_lookup"].get((q, r), "sea")
        if terrain not in ("sea", "calm_belt"):
            return False
    except Exception:
        pass
    return True


# ── Ship movement (captain) ───────────────────────────────────────────────────

def move_ship(crew_id, direction):
    """
    Move the crew ship one hex. Spends 1 roll.
    Returns (new_q, new_r, success: bool, reason: str).
    reason on failure: 'no_rolls' | 'impassable' | 'invalid_direction' | 'crew_not_found'
    """
    crew = db.get_crew(crew_id)
    if not crew:
        return 0, 0, False, "crew_not_found"

    if (crew["roll"] or 0) <= 0:
        return crew["q"] or 0, crew["r"] or 0, False, "no_rolls"

    ship_hp = crew["ship_hp"] if crew["ship_hp"] is not None else 500
    if ship_hp <= 0:
        return crew["q"] or 0, crew["r"] or 0, False, "ship_disabled"

    if direction not in HEX_DIRECTIONS:
        return crew["q"] or 0, crew["r"] or 0, False, "invalid_direction"

    dq, dr  = HEX_DIRECTIONS[direction]
    new_q   = (crew["q"] or 0) + dq
    new_r   = (crew["r"] or 0) + dr

    if not is_passable(new_q, new_r):
        return crew["q"] or 0, crew["r"] or 0, False, "impassable"

    db.move_crew(crew_id, new_q, new_r)
    db.spend_crew_roll(crew_id, ROLL_REGEN_AMOUNT)
    return new_q, new_r, True, "ok"


# ── Auto travel toward log pose ───────────────────────────────────────────────

def _hex_dist(q1, r1, q2, r2):
    return max(abs(q1 - q2), abs(r1 - r2), abs((q1 + r1) - (q2 + r2)))


def step_toward_log_pose(crew_id):
    """
    Move the ship one step toward the crew's log pose island.
    Returns (new_q, new_r, success: bool, reason: str).
    reason on success: the direction key used.
    reason on failure: 'no_rolls' | 'island_not_found' | 'already_there' |
                       'no_path' | 'impassable' | 'crew_not_found'
    """
    crew = db.get_crew(crew_id)
    if not crew:
        return 0, 0, False, "crew_not_found"

    if (crew["roll"] or 0) <= 0:
        return crew["q"] or 0, crew["r"] or 0, False, "no_rolls"

    log_pose = crew["log_pose"] if crew["log_pose"] else DEFAULT_LOG_POSE

    # Lazy import to avoid circular dependency with map_render
    try:
        from map_render import _cache, _load_map
        _load_map()
        origins = _cache.get("origins", {})
        target  = origins.get(log_pose)
    except Exception:
        target = None

    if not target:
        return crew["q"] or 0, crew["r"] or 0, False, "island_not_found"

    tq, tr = target
    cq, cr = crew["q"] or 0, crew["r"] or 0

    if (cq, cr) == (tq, tr):
        return cq, cr, False, "already_there"

    # Greedy: pick the passable neighbour closest to target
    best_dir  = None
    best_dist = float("inf")
    for dir_name, (dq, dr) in HEX_DIRECTIONS.items():
        nq, nr = cq + dq, cr + dr
        if not is_passable(nq, nr):
            continue
        d = _hex_dist(nq, nr, tq, tr)
        if d < best_dist:
            best_dist = d
            best_dir  = dir_name

    if not best_dir:
        return cq, cr, False, "no_path"

    dq, dr  = HEX_DIRECTIONS[best_dir]
    new_q, new_r = cq + dq, cr + dr

    db.move_crew(crew_id, new_q, new_r)
    db.spend_crew_roll(crew_id, ROLL_REGEN_AMOUNT)
    return new_q, new_r, True, best_dir


# ── Solo / player movement ────────────────────────────────────────────────────

def move_player(player_id, direction):
    """
    Move an independent player one hex (following_id must be None).
    Returns (new_q, new_r, success: bool, reason: str).
    """
    player = db.get_player(str(player_id))
    if not player:
        return 0, 0, False, "not_found"

    if player["captured_by"]:
        return player["q"] or 0, player["r"] or 0, False, "captured"

    if direction not in HEX_DIRECTIONS:
        return player["q"] or 0, player["r"] or 0, False, "invalid_direction"

    walk_rolls = player["walk_roll"] if player["walk_roll"] is not None else WALK_ROLL_MAX
    if walk_rolls <= 0:
        return player["q"] or 0, player["r"] or 0, False, "no_walk_rolls"

    dq, dr  = HEX_DIRECTIONS[direction]
    new_q   = (player["q"] or 0) + dq
    new_r   = (player["r"] or 0) + dr

    # calm belt is still impassable on foot
    if abs(new_r) > CALM_BELT_R:
        return player["q"] or 0, player["r"] or 0, False, "impassable"

    # players on foot can only walk on island tiles
    try:
        from map_render import _cache, _load_map
        _load_map()
        terrain = _cache["hex_lookup"].get((new_q, new_r), "sea")
        if terrain not in ("island",):
            return player["q"] or 0, player["r"] or 0, False, "no_walking_on_sea"
    except Exception:
        pass

    db.update_player_position(str(player_id), new_q, new_r)
    db.spend_walk_roll(str(player_id))
    return new_q, new_r, True, "ok"


# ── Adjacency helpers ─────────────────────────────────────────────────────────

def adjacent_hexes(q: int, r: int) -> list:
    """Returns list of (q, r) for all 6 neighbours."""
    return [(q + dq, r + dr) for dq, dr in HEX_DIRECTIONS.values()]


def adjacent_island_tile(q: int, r: int):
    """
    Returns the first adjacent (q, r) that is an island tile, or None.
    """
    try:
        from map_render import _cache, _load_map
        _load_map()
        hex_lookup = _cache["hex_lookup"]
    except Exception:
        return None
    for nq, nr in adjacent_hexes(q, r):
        if hex_lookup.get((nq, nr)) == "island":
            return nq, nr
    return None


def is_adjacent(q1: int, r1: int, q2: int, r2: int) -> bool:
    return (q2, r2) in adjacent_hexes(q1, r1)


# ── Boarding state changes ────────────────────────────────────────────────────

def disembark(player_id):
    """
    Leave the ship. Syncs player q/r to current ship position.
    If captain → following_id = None (independent).
    If crew    → following_id = captain_id (follow the captain on land).
    Returns True on success.
    """
    player = db.get_player(str(player_id))
    if not player or not player["crew_id"]:
        return False

    crew = db.get_crew(player["crew_id"])
    if not crew:
        return False

    sq, sr = crew["q"] or 0, crew["r"] or 0
    db.update_player_position(str(player_id), sq, sr)

    if str(crew["captain_id"]) == str(player_id):
        db.set_following(str(player_id), None)
    else:
        db.set_following(str(player_id), str(crew["captain_id"]))

    return True


def reboard(player_id):
    """
    Return to the ship. Syncs q/r to ship and sets following_id = 'ship'.
    Returns True on success.
    """
    player = db.get_player(str(player_id))
    if not player or not player["crew_id"]:
        return False

    crew = db.get_crew(player["crew_id"])
    if not crew:
        return False

    sq, sr = crew["q"] or 0, crew["r"] or 0
    db.update_player_position(str(player_id), sq, sr)
    db.set_following(str(player_id), "ship")
    return True


def go_solo(player_id):
    """Break away from captain/ship to move fully independently."""
    q, r = get_position(str(player_id))
    db.update_player_position(str(player_id), q, r)
    db.set_following(str(player_id), None)


# ── Tile queries ──────────────────────────────────────────────────────────────

def get_players_at(q: int, r: int, exclude_uid: str = None) -> list:
    """
    Returns player rows whose resolved position is (q, r).
    Checks own q/r (solo players) and crew ship position.
    """
    from db import db as con
    results = []

    solo = con.execute(
        "SELECT * FROM players WHERE following_id IS NULL AND q=? AND r=?",
        (q, r)
    ).fetchall()

    on_ship = con.execute(
        """
        SELECT p.* FROM players p
        JOIN crews c ON p.crew_id = c.id
        WHERE p.following_id = 'ship' AND c.q=? AND c.r=?
        """,
        (q, r)
    ).fetchall()

    seen = set()
    for row in list(solo) + list(on_ship):
        uid = str(row["id"])
        if uid == exclude_uid or uid in seen:
            continue
        seen.add(uid)
        results.append(row)

    return results

def replenish_rolls():
    """
    Add ROLL_REGEN_AMOUNT rolls to every crew that is under ROLL_MAX.
    Returns the number of crews that received rolls.
    """
    crews   = db.get_all_crews()
    updated = 0
    for crew in crews:
        current = crew["roll"] or 0
        if current < ROLL_MAX:
            db.set_crew_roll(crew["id"], min(ROLL_MAX, current + ROLL_REGEN_AMOUNT))
            updated += 1
    return updated


def hourly_regen():
    """One tick of all hourly regeneration: ship rolls, walk rolls, HP."""
    updated = replenish_rolls()
    db.regen_walk_rolls(WALK_ROLL_MAX, 1)
    db.regen_hp(HP_REGEN_PER_HOUR, HP_REGEN_BOOSTED)
    return updated


# ── Cannon system ─────────────────────────────────────────────────────────────

CANNON_RANGE = 7
CANNON_DMG_MIN = 40
CANNON_DMG_MAX = 80
CANNON_ROLL_COST = 1


def cannon_hit_chance(distance: int) -> int:
    """90% at 1 tile, 30% at 7 tiles."""
    return max(30, 90 - (distance - 1) * 10)


def cannon_volley(attacker_crew, defender_crew) -> tuple:
    """
    Roll one cannon volley from attacker at defender.
    Returns (hit: bool, damage: int, hit_chance: int, distance: int).
    """
    aq, ar = attacker_crew["q"] or 0, attacker_crew["r"] or 0
    dq, dr = defender_crew["q"] or 0, defender_crew["r"] or 0
    dist   = _hex_dist(aq, ar, dq, dr)
    chance = cannon_hit_chance(dist)
    hit    = _random.randint(1, 100) <= chance
    dmg    = _random.randint(CANNON_DMG_MIN, CANNON_DMG_MAX) if hit else 0
    return hit, dmg, chance, dist


def cannon_hp_bar(hp: int, max_hp: int, width: int = 12) -> str:
    filled = max(0, round((hp / max(max_hp, 1)) * width))
    return "█" * filled + "░" * (width - filled)


def crews_in_cannon_range(crew_id: str) -> list:
    """Returns all other crews within CANNON_RANGE tiles."""
    my_crew = db.get_crew(crew_id)
    if not my_crew:
        return []
    mq, mr    = my_crew["q"] or 0, my_crew["r"] or 0
    all_crews = db.get_all_crews()
    return [
        c for c in all_crews
        if c["id"] != crew_id
        and _hex_dist(mq, mr, c["q"] or 0, c["r"] or 0) <= CANNON_RANGE
    ]


# ── Whirlpool field ───────────────────────────────────────────────────────────
# A field of whirlpools is generated once per day (and on every bootup). Each
# whirlpool stores a fixed destination 4-10 tiles away, decided at creation
# time so the teleport is deterministic at runtime — a ship that sails onto a
# whirlpool is always flung to the same place until the next daily refresh.
# Whirlpools only ever sit on open, navigable sea: never on islands, the Red
# Line, the Calm Belt, marine facilities, Impel Down, or other reserved tiles.

WHIRLPOOL_COUNT      = 40
WHIRLPOOL_MIN_HOP    = 4
WHIRLPOOL_MAX_HOP    = 10
WHIRLPOOL_R_LIMIT    = 34
# Playable-region quadrilateral (q, r). Whirlpools only spawn inside this.
WHIRLPOOL_CORNERS    = [(10, -40), (-27, 34), (211, 34), (246, -39)]
# Always-present test whirlpool(s).
WHIRLPOOL_TEST_TILES = [(100, -30)]

_whirlpools: dict = {}        # {(q, r): (dest_q, dest_r)}
_whirlpool_day            = None   # iso date the current set was generated for


def _point_in_quad(q, r, poly):
    """Ray-cast point-in-polygon test, run directly in axial (q, r) space."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > r) != (yj > r):
            x_cross = xi + (r - yi) * (xj - xi) / (yj - yi)
            if q < x_cross:
                inside = not inside
        j = i
    return inside


def _whirlpool_usable(q, r):
    """True only for open navigable sea — excludes every reserved tile type."""
    if abs(r) > CALM_BELT_R:
        return False
    if (q, r) in BLOCKED_TILES:
        return False
    if (q, r) == (IMPEL_DOWN_Q, IMPEL_DOWN_R):
        return False
    try:
        from map_render import _cache, _load_map, GRAY_HEXES, MARINE_SHIP_START
        _load_map()
        if (q, r) in GRAY_HEXES or (q, r) == MARINE_SHIP_START:
            return False
        terrain = _cache["hex_lookup"].get((q, r), "sea")
        if terrain not in ("sea", "calm_belt"):
            return False
    except Exception:
        return False
    return True


def _ring_offsets(dist):
    """All (dq, dr) offsets exactly `dist` hexes away (hex distance)."""
    out = []
    for dq in range(-dist, dist + 1):
        for dr in range(-dist, dist + 1):
            if max(abs(dq), abs(dr), abs(dq + dr)) == dist:
                out.append((dq, dr))
    return out


def _pick_whirlpool_dest(q, r, taken):
    """Pick a destination exactly 4-10 tiles from (q, r) on open sea, or None."""
    for _ in range(60):
        dist = _random.randint(WHIRLPOOL_MIN_HOP, WHIRLPOOL_MAX_HOP)
        odq, odr = _random.choice(_ring_offsets(dist))
        dq, dr = q + odq, r + odr
        if (dq, dr) in taken:
            continue
        if _whirlpool_usable(dq, dr):
            return (dq, dr)
    return None


def _generate_whirlpools():
    qs = [c[0] for c in WHIRLPOOL_CORNERS]
    rs = [c[1] for c in WHIRLPOOL_CORNERS]
    qmin, qmax = min(qs), max(qs)
    rmin = max(-WHIRLPOOL_R_LIMIT, min(rs))
    rmax = min(WHIRLPOOL_R_LIMIT, max(rs))

    result: dict = {}
    taken: set = set()

    # Always seed the test whirlpool(s) first.
    for (tq, tr) in WHIRLPOOL_TEST_TILES:
        dest = _pick_whirlpool_dest(tq, tr, taken | {(tq, tr)})
        if dest:
            result[(tq, tr)] = dest
            taken.update({(tq, tr), dest})

    attempts = 0
    while (len([k for k in result if k not in WHIRLPOOL_TEST_TILES]) < WHIRLPOOL_COUNT
           and attempts < 20000):
        attempts += 1
        q = _random.randint(qmin, qmax)
        r = _random.randint(rmin, rmax)
        if (q, r) in taken:
            continue
        if not _point_in_quad(q, r, WHIRLPOOL_CORNERS):
            continue
        if not _whirlpool_usable(q, r):
            continue
        dest = _pick_whirlpool_dest(q, r, taken | {(q, r)})
        if not dest:
            continue
        result[(q, r)] = dest
        taken.update({(q, r), dest})

    return result


def ensure_whirlpools(force=False):
    """Regenerate the whirlpool set on first use, on a new day, or on demand."""
    global _whirlpools, _whirlpool_day
    today = datetime.date.today().isoformat()
    if force or not _whirlpools or _whirlpool_day != today:
        _whirlpools = _generate_whirlpools()
        _whirlpool_day = today
    return _whirlpools


def get_whirlpools():
    """Return {(q, r): (dest_q, dest_r)} for all active whirlpools."""
    return dict(ensure_whirlpools())


def whirlpool_dest(q, r):
    """Return the (dest_q, dest_r) for a whirlpool at (q, r), or None."""
    return ensure_whirlpools().get((q, r))


def check_ship_whirlpool(crew_id, q, r):
    """If (q, r) holds a whirlpool, sweep the crew to its destination.

    Returns (final_q, final_r, teleported)."""
    dest = whirlpool_dest(q, r)
    if dest:
        dq, dr = dest
        db.move_crew(crew_id, dq, dr)
        return dq, dr, True
    return q, r, False
