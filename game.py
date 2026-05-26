# ═══════════════════════════════════════════════════════════════════════════════
#  game.py  ·  Core game logic — coordinates, movement, rolls.
#  Import this everywhere instead of reading q/r directly from the DB.
# ═══════════════════════════════════════════════════════════════════════════════

import db

# ── Constants ─────────────────────────────────────────────────────────────────

HEX_DIRECTIONS = {
    "fw":  ( 1,  0),
    "bw":  (-1,  0),
    "rf":  ( 0,  1),
    "rb":  (-1,  1),
    "lf":  ( 1, -1),
    "lb":  ( 0, -1),
}

DIRECTION_LABELS = {
    "fw": "Forward",
    "bw": "Backward",
    "rf": "Right — Forward",
    "rb": "Right — Back",
    "lf": "Left — Forward",
    "lb": "Left — Back",
}

ROLL_MAX           = 12
ROLL_REGEN_MINUTES = 60   # one roll added per interval
ROLL_REGEN_AMOUNT  = 1

CALM_BELT_R = 36          # abs(r) > this is impassable calm belt

DEFAULT_LOG_POSE = "alabasta"

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
    """Returns False for calm belt and any other impassable terrain."""
    if abs(r) > CALM_BELT_R:
        return False
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

    log_pose = crew.get("log_pose") or DEFAULT_LOG_POSE

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

    if direction not in HEX_DIRECTIONS:
        return player["q"] or 0, player["r"] or 0, False, "invalid_direction"

    dq, dr  = HEX_DIRECTIONS[direction]
    new_q   = (player["q"] or 0) + dq
    new_r   = (player["r"] or 0) + dr

    if not is_passable(new_q, new_r):
        return player["q"] or 0, player["r"] or 0, False, "impassable"

    db.update_player_position(str(player_id), new_q, new_r)
    return new_q, new_r, True, "ok"


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


# ── Roll replenishment (called by background task) ────────────────────────────

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
