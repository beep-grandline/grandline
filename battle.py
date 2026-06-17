# ═══════════════════════════════════════════════════════════════════════════════
#  battle.py  ·  Pure battle logic for the Discord bot.
#  No print statements. No Discord imports. No DB calls.
#  All state is a plain JSON-serialisable dict.
# ═══════════════════════════════════════════════════════════════════════════════

import random

# Counter damage on a successful block, as a fraction of the BLOCKER's own
# attack stat (never the incoming hit). Keep this proportional to the
# defender's power so blocking a heavy hitter doesn't reflect huge damage.
COUNTER_ATK_FRACTION = 0.15

# Damage scaling.
#  DAMAGE_SCALE      — global flat multiplier on all damage (tune to slow/speed fights).
#  ATK_DEF_EXPONENT  — dampens the atk/defense ratio so stat gaps matter but don't
#                      nuke. 1.0 = raw linear ratio (old behaviour); 0.5 = square-root
#                      dampening (a 8× atk advantage becomes ~2.8×, not 8×).
DAMAGE_SCALE     = 0.85
ATK_DEF_EXPONENT = 0.5

# ── Type Chart 1: Elemental (Pokemon gen 6) ───────────────────────────────────

ELEMENTAL_CHART = {
    "Normal":   {"Rock": 0.5, "Steel": 0.5, "Ghost": 0},
    "Fire":     {"Fire": 0.5, "Water": 0.5, "Rock": 0.5, "Dragon": 0.5,
                 "Grass": 2, "Ice": 2, "Bug": 2, "Steel": 2},
    "Water":    {"Water": 0.5, "Grass": 0.5, "Dragon": 0.5,
                 "Fire": 2, "Ground": 2, "Rock": 2},
    "Grass":    {"Fire": 0.5, "Grass": 0.5, "Poison": 0.5, "Flying": 0.5,
                 "Bug": 0.5, "Dragon": 0.5, "Steel": 0.5,
                 "Water": 2, "Ground": 2, "Rock": 2},
    "Electric": {"Grass": 0.5, "Electric": 0.5, "Dragon": 0.5, "Ground": 0,
                 "Water": 2, "Flying": 2},
    "Ice":      {"Water": 0.5, "Ice": 0.5, "Fire": 0.5, "Steel": 0.5,
                 "Grass": 2, "Ground": 2, "Flying": 2, "Dragon": 2},
    "Fighting": {"Poison": 0.5, "Flying": 0.5, "Psychic": 0.5,
                 "Bug": 0.5, "Fairy": 0.5, "Ghost": 0,
                 "Normal": 2, "Ice": 2, "Rock": 2, "Dark": 2, "Steel": 2},
    "Poison":   {"Poison": 0.5, "Ground": 0.5, "Rock": 0.5,
                 "Ghost": 0.5, "Steel": 0,
                 "Grass": 2, "Fairy": 2},
    "Ground":   {"Grass": 0.5, "Bug": 0.5, "Flying": 0,
                 "Fire": 2, "Electric": 2, "Poison": 2, "Rock": 2, "Steel": 2},
    "Flying":   {"Electric": 0.5, "Rock": 0.5, "Steel": 0.5,
                 "Grass": 2, "Fighting": 2, "Bug": 2},
    "Psychic":  {"Psychic": 0.5, "Steel": 0.5, "Dark": 0,
                 "Fighting": 2, "Poison": 2},
    "Bug":      {"Fire": 0.5, "Fighting": 0.5, "Flying": 0.5,
                 "Ghost": 0.5, "Steel": 0.5, "Fairy": 0.5,
                 "Grass": 2, "Psychic": 2, "Dark": 2},
    "Rock":     {"Fighting": 0.5, "Ground": 0.5, "Steel": 0.5,
                 "Fire": 2, "Ice": 2, "Flying": 2, "Bug": 2},
    "Ghost":    {"Normal": 0, "Dark": 0.5, "Ghost": 2, "Psychic": 2},
    "Dragon":   {"Steel": 0.5, "Fairy": 0, "Dragon": 2},
    "Dark":     {"Fighting": 0.5, "Dark": 0.5, "Fairy": 0.5,
                 "Ghost": 2, "Psychic": 2},
    "Steel":    {"Fire": 0.5, "Water": 0.5, "Electric": 0.5, "Steel": 0.5,
                 "Ice": 2, "Rock": 2, "Fairy": 2},
    "Fairy":    {"Fire": 0.5, "Poison": 0.5, "Steel": 0.5,
                 "Fighting": 2, "Dragon": 2, "Dark": 2},
}

# ── Type Chart 2: Physical defence ───────────────────────────────────────────

PHYSICAL_CHART = {
    "none":    {"slash": 1.0,  "blunt": 1.0,  "pierce": 1.0},
    "sponge":  {"slash": 2.0,  "blunt": 0.0,  "pierce": 1.0},
    "armor":   {"slash": 0.7,  "blunt": 0.6,  "pierce": 1.5},
    "logia":   {"slash": 0.0,  "blunt": 0.0,  "pierce": 0.0},
    "shell":   {"slash": 0.6,  "blunt": 0.45, "pierce": 2.0},
    "buffer":  {"slash": 0.5,  "blunt": 0.8,  "pierce": 0.5},
    "deflect": {"slash": 0.7,  "blunt": 0.5,  "pierce": 0.5},
    "escape":  {"slash": 1.0,  "blunt": 1.0,  "pierce": 1.0},
    "big":     {"slash": 0.8,  "blunt": 0.5,  "pierce": 0.9},
}

ACCURACY_MOD_TYPES = {"deflect", "big"}
BLOCK_ONLY_TYPES   = {"shell", "buffer"}
PASSIVE_DMG_TYPES  = {"none", "sponge", "armor", "logia"}

ESCAPE_MODIFIERS = {
    "escape": 1.8,
    "none":   1.0,
    "sponge": 1.0,
    "armor":  0.9,
    "logia":  0.9,
    "shell":  0.8,
    "buffer": 1.0,
    "deflect":1.0,
    "big":    0.7,
}

# ── Type modifier helpers ─────────────────────────────────────────────────────

def _elemental_mod(move_element, defender_type1):
    if not move_element or not defender_type1:
        return 1.0
    return ELEMENTAL_CHART.get(move_element, {}).get(defender_type1, 1.0)

def _passive_physical_mod(attack_type, defender_type2):
    if defender_type2 not in PASSIVE_DMG_TYPES:
        return 1.0
    return PHYSICAL_CHART.get(defender_type2, {}).get(attack_type, 1.0)

def _block_physical_mod(attack_type, defender_type2):
    if defender_type2 not in BLOCK_ONLY_TYPES:
        return 1.0
    return PHYSICAL_CHART.get(defender_type2, {}).get(attack_type, 1.0)

def _accuracy_mod(attack_type, defender_type2):
    if defender_type2 not in ACCURACY_MOD_TYPES:
        return 1.0
    return PHYSICAL_CHART.get(defender_type2, {}).get(attack_type, 1.0)

# ── Rolls ─────────────────────────────────────────────────────────────────────

def _roll_dodge(defender, attacker, move):
    move_spd           = move.get("spd", 5)
    attacker_effective = attacker["spd"] + move_spd
    chance             = defender["spd"] / (defender["spd"] + attacker_effective)
    return random.random() < chance, round(chance * 100)

def _roll_block(defender, attacker):
    delta   = (defender["defense"] - attacker["atk"]) * 3
    chance  = max(10, min(90, 50 + delta)) / 100
    return random.random() < chance, round(chance * 100)

def _roll_escape(escaper, pursuer):
    speed_ratio = escaper["spd"] / (escaper["spd"] + pursuer["spd"])
    escape_mod  = ESCAPE_MODIFIERS.get(escaper.get("type2", "none"), 1.0)
    chance      = min(0.99, speed_ratio * escape_mod)
    return random.random() < chance, round(chance * 100)

# ── Damage calculation ────────────────────────────────────────────────────────

def _calculate_damage(attacker, defender, move, is_blocking=False):
    attack_type = move.get("attack_type", "blunt")

    base_acc      = move["accuracy"]
    acc_mod       = _accuracy_mod(attack_type, defender.get("type2", "none"))
    effective_acc = base_acc * acc_mod
    hit           = random.uniform(0, 100) <= effective_acc
    if not hit:
        return 0, False, False, 1.0, 1.0

    ratio = attacker["atk"] / max(defender["defense"], 1)
    base  = move["power"] * (ratio ** ATK_DEF_EXPONENT) * DAMAGE_SCALE
    base *= random.uniform(0.85, 1.15)

    crit = random.random() < 0.0625
    if crit:
        base *= 1.5

    move_element  = move.get("element", attacker.get("type1", "Normal"))
    e_mod         = _elemental_mod(move_element, defender.get("type1", "Normal"))
    p_mod_passive = _passive_physical_mod(attack_type, defender.get("type2", "none"))
    p_mod_block   = _block_physical_mod(attack_type, defender.get("type2", "none")) if is_blocking else 1.0
    flat_block    = 0.0 if is_blocking and defender.get("type2") not in BLOCK_ONLY_TYPES else 1.0
    total_p_mod   = p_mod_passive * p_mod_block * flat_block

    if e_mod == 0 or total_p_mod == 0 or abs(total_p_mod) < 1e-9:
        return 0, True, False, e_mod, total_p_mod

    final = max(1, round(base * e_mod * total_p_mod))
    return final, True, crit, e_mod, total_p_mod

# ── Helpers ───────────────────────────────────────────────────────────────────

def _effectiveness_label(e_mod, p_mod):
    combined = e_mod * p_mod
    if combined == 0:    return "→ No effect!"
    if combined >= 2.0:  return "→ Super effective!"
    if combined <= 0.5:  return "→ Not very effective..."
    return ""

def _find_move(fighter, move_name):
    for m in fighter.get("moves", []):
        if m["name"].lower() == move_name.lower():
            return m
    return None

# ── Special abilities ─────────────────────────────────────────────────────────

SPECIAL_MOVES = {
    "paw_warn": {
        "name":        "✋ Nikyu Nikyu",
        "attack_type": "blunt",
        "power":       0,
        "accuracy":    100,
        "priority":    0,
        "tracking":    5,
        "hits":        1,
        "hp_cost":     0,
        "recoil":      0.0,
        "special":     "paw_warn",
    },
}

FRUIT_SPECIALS = {
    "paw": ["paw_warn"],
}


def _handle_paw_warn(actor, target, lines):
    """Phase 1: telegraph the teleport. Target has one turn to escape."""
    target["paw_incoming"]    = True
    target["paw_warning_by"]  = str(actor.get("id", ""))
    lines.append(f"✋ {actor['name']} gently places a glowing paw on {target['name']}...")
    lines.append("→ *Block and dodge are useless. Only escape can save you now.*")


def _handle_paw_teleport(actor, target, lines):
    """
    Sends target to a random island tile.
    Tries named island origins first, falls back to any hex with terrain 'island'.
    """
    try:
        from map_render import _cache, _load_map
        _load_map()

        # prefer named island origins — skip any with None coords
        origins = _cache.get("origins", {})
        valid   = [
            (name, q, r)
            for name, coords in origins.items()
            if coords is not None
            for q, r in [coords]
        ]

        # fall back to any island hex if no named origins
        if not valid:
            valid = [
                (f"({q},{r})", q, r)
                for (q, r), terrain in _cache.get("hex_lookup", {}).items()
                if terrain == "island"
            ]
    except Exception:
        valid = []

    if not valid:
        lines.append(f"✋ {actor['name']} reaches out — but nowhere to send them!")
        return

    island, q, r = random.choice(valid)
    target["teleport_to"] = {"q": q, "r": r, "island": island, "by": actor["id"]}
    lines.append(f"✋ {actor['name']} places their Nikyu Nikyu paw on {target['name']}!")
    lines.append(f"→ {target['name']} is sent flying toward **{island}**!")


# ── Action resolution ─────────────────────────────────────────────────────────

def _resolve_action(actor, target, action, move_name, opp_action):
    """
    Resolves actor's chosen action against target.
    Mutates actor["hp"] and target["hp"] in place.
    Returns list of log line strings.
    """
    lines = []

    if action == "attack":
        move = _find_move(actor, move_name) if move_name else None
        if not move:
            lines.append(f"{actor['name']} tried to use an unknown move!")
            return lines

        attack_type = move.get("attack_type", "blunt")
        hits        = move.get("hits", 1)

        # special ability — handle before normal damage
        special = move.get("special")
        if special:
            lines.append(f"{actor['name']} used **{move['name']}**!")
            # dodge still applies
            if opp_action == "dodge":
                ok, pct = _roll_dodge(target, actor, move)
                if ok:
                    lines.append(f"{target['name']} evades! ({pct}% chance)")
                    target["priority_next_turn"] = True
                    return lines
                else:
                    lines.append(f"{target['name']} couldn't evade! ({pct}% chance)")
            if special == "paw_warn":
                _handle_paw_warn(actor, target, lines)
            elif special == "paw_teleport":
                _handle_paw_teleport(actor, target, lines)
            return lines

        # consume charge — applies regardless of hit, miss, or dodge
        charge_mult = 2.0 if actor.pop("charging", False) else 1.0

        # hp cost on use — triggers regardless of hit/miss/dodge
        hp_cost = move.get("hp_cost", 0)
        if hp_cost > 0:
            actor["hp"] = max(0, actor["hp"] - hp_cost)
            lines.append(f"{actor['name']} exerts themselves! (-{hp_cost} HP)")

        # dodge check — a successful dodge beats the whole move
        if opp_action == "dodge":
            ok, pct = _roll_dodge(target, actor, move)
            if ok:
                lines.append(f"{target['name']} dodges {actor['name']}'s {move['name']}! ({pct}% chance)")
                target["priority_next_turn"] = True
                return lines
            else:
                lines.append(f"{target['name']} tried to dodge but couldn't! ({pct}% chance)")

        lines.append(f"{actor['name']} used **{move['name']}**! [{attack_type} | {hits} hit{'s' if hits > 1 else ''}]")

        if hits == 1:
            # ── single hit — roll block here, only for this path ──────────────
            is_blocking = (opp_action == "block")
            if is_blocking:
                ok, pct = _roll_block(target, actor)
                if ok:
                    block_str = f" with {target['block']}!" if target.get("block") else "!"
                    lines.append(f"{target['name']} blocks{block_str} ({pct}% chance)")
                else:
                    lines.append(f"{target['name']}'s block fails! ({pct}% chance)")
                    is_blocking = False

            dmg, hit, crit, e_mod, p_mod = _calculate_damage(actor, target, move, is_blocking)

            if not hit:
                lines.append("→ Missed!")
            else:
                if crit:
                    lines.append("→ Critical hit!")
                if not (dmg == 0 and is_blocking):  # skip label when block fully negates
                    label = _effectiveness_label(e_mod, p_mod)
                    if label:
                        lines.append(label)
                if dmg == 0 and is_blocking:
                    lines.append(f"→ {target['name']} blocks the hit completely!")
                elif dmg > 0:
                    if charge_mult > 1.0:
                        dmg = max(1, round(dmg * charge_mult))
                    target["hp"] = max(0, target["hp"] - dmg)
                    charge_tag = " ⚡ Charged!" if charge_mult > 1.0 else ""
                    lines.append(f"→{charge_tag} {target['name']} took **{dmg}** damage. (e:{e_mod}× p:{p_mod:.2f}×)")
                    recoil = move.get("recoil", 0.0)
                    if recoil > 0:
                        recoil_dmg = max(1, round(dmg * recoil))
                        actor["hp"] = max(0, actor["hp"] - recoil_dmg)
                        lines.append(f"→ {actor['name']} takes {recoil_dmg} recoil damage!")
                elif dmg == 0:
                    label2 = _effectiveness_label(e_mod, p_mod)
                    if not label2:
                        lines.append("→ No effect!")

                # counter fires whenever block succeeded, even on full block
                if is_blocking:
                    counter_dmg = max(1, round(target["atk"] * COUNTER_ATK_FRACTION))
                    actor["hp"] = max(0, actor["hp"] - counter_dmg)
                    lines.append(f"→ {target['name']} counters! **{counter_dmg}** damage.")

        else:
            # ── multi-hit (multi / flurry / barrage) ──────────────────────────
            # Scale and accuracy penalty vary by hit count so each tier is
            # meaningfully different: MULTI(2) ≈ MEDIUM, FLURRY(6) ≈ HEAVY,
            # BARRAGE(30) ≈ CRUSHER in expected damage.
            if hits >= 20:       # BARRAGE — massive barrage, each hit weak
                scale, acc_penalty = 3.5, 0.60
            elif hits >= 5:      # FLURRY — spread burst
                scale, acc_penalty = 1.8, 0.80
            else:                # MULTI — double tap
                scale, acc_penalty = 1.3, 0.90

            per_hit_move = dict(move)
            per_hit_move["power"]    = move["power"] / hits * scale
            per_hit_move["accuracy"] = move["accuracy"] * acc_penalty

            hit_count    = 0
            blocked_full = 0   # hits fully negated by block
            total_dmg    = 0
            got_crit     = False
            any_blocked  = False

            # Roll block once for the whole sequence from the raw action,
            # not from is_blocking (which was scoped to single-hit above).
            block_active = False
            if opp_action == "block":
                b_ok, b_pct = _roll_block(target, actor)
                block_str = f" with {target['block']}!" if target.get("block") else "!"
                if b_ok:
                    lines.append(f"{target['name']} blocks{block_str} ({b_pct}% chance)")
                    block_active = True
                    any_blocked  = True
                else:
                    lines.append(f"{target['name']}'s block fails! ({b_pct}% chance)")

            for _ in range(hits):
                dmg, did_hit, crit, e_mod, p_mod = _calculate_damage(
                    actor, target, per_hit_move, is_blocking=False
                )
                if not did_hit:
                    continue
                if crit:
                    got_crit = True
                if block_active:
                    blocked_full += 1
                else:
                    hit_count += 1
                    total_dmg += dmg

            landed = hit_count + blocked_full

            if got_crit:
                lines.append("→ Critical hit in the barrage!")

            if total_dmg == 0 and not any_blocked:
                lines.append("→ All hits missed!")
            else:
                if total_dmg > 0:
                    if charge_mult > 1.0:
                        total_dmg = max(1, round(total_dmg * charge_mult))
                    target["hp"] = max(0, target["hp"] - total_dmg)
                charge_tag = " ⚡ Charged!" if charge_mult > 1.0 else ""
                summary = f"→{charge_tag} {landed}/{hits} connected"
                if blocked_full:
                    summary += f", {blocked_full} blocked"
                if total_dmg > 0:
                    summary += f" — **{total_dmg}** total damage"
                lines.append(summary)

                if total_dmg > 0:
                    recoil = move.get("recoil", 0.0)
                    if recoil > 0:
                        recoil_dmg = max(1, round(total_dmg * recoil))
                        actor["hp"] = max(0, actor["hp"] - recoil_dmg)
                        lines.append(f"→ {actor['name']} takes {recoil_dmg} recoil damage!")

                # counter fires if any hit was blocked (consistent with single-hit)
                if any_blocked:
                    counter_dmg = max(1, round(target["atk"] * COUNTER_ATK_FRACTION))
                    actor["hp"] = max(0, actor["hp"] - counter_dmg)
                    lines.append(f"→ {target['name']} counters! **{counter_dmg}** damage.")

    elif action == "block":
        if opp_action != "attack":
            lines.append(f"{actor['name']} takes a defensive stance.")

    elif action == "dodge":
        if opp_action != "attack":
            lines.append(f"{actor['name']} attempts to dodge.")

    elif action == "charge":
        actor["charging"] = True
        lines.append(f"⚡ {actor['name']} is charging up — next attack hits twice as hard!")

    elif action == "escape":
        ok, pct = _roll_escape(actor, target)
        if ok:
            lines.append(f"{actor['name']} escapes the fight! ({pct}% chance)")
            actor["escaped"] = True
        else:
            lines.append(f"{actor['name']} tries to escape but fails! ({pct}% chance)")

    return lines

# ── Public API ────────────────────────────────────────────────────────────────

def create_battle(a_data, b_data):
    """
    Build an initial battle state from two fighter data dicts.
    a_data / b_data keys: id, name, hp, atk, defense, spd, moves,
                          type1, type2, block (optional), dodge (optional)
    Returns a JSON-serialisable state dict.
    """
    def _init(data):
        return {
            "id":       str(data["id"]),
            "name":     data["name"],
            "hp":       data["hp"],
            "max_hp":   data.get("max_hp") or data["hp"],
            "atk":      data.get("atk", 10),
            "defense":  data.get("defense", 10),
            "spd":      data.get("spd", 10),
            "moves":    data.get("moves", []),
            "type1":    data.get("type1", "Normal"),
            "type2":    data.get("type2", "none"),
            "block":    data.get("block"),
            "dodge":    data.get("dodge"),
            "escaped":  False,
            "charging": False,
        }

    return {
        "turn":     0,
        "fighters": {"a": _init(a_data), "b": _init(b_data)},
        "status":   "active",   # "active" | "finished"
        "winner":   None,       # None | "a" | "b" | "draw"
        "log":      [],
    }


def resolve_turn(state, action_a, action_b):
    """
    Resolve one turn of combat.

    action_a / action_b:
        ["attack", "Move Name"] | ["block", None] | ["dodge", None] | ["escape", None]

    Mutates state in place and returns (state, log_lines).
    log_lines is a list of strings ready to join into a Discord message.
    """
    # normalise — JSON round-trips turn tuples into lists
    act_a, move_a = action_a[0], action_a[1]
    act_b, move_b = action_b[0], action_b[1]

    fa = state["fighters"]["a"]
    fb = state["fighters"]["b"]

    state["turn"] += 1
    log = [f"**── Turn {state['turn']} ──**"]

    # ── Phase 2 paw check ─────────────────────────────────────────────────────
    # If a fighter has paw_incoming, the teleport fires this turn.
    # Only a successful escape can prevent it.
    for victim, attacker, victim_action in [
        (fa, fb, act_a), (fb, fa, act_b)
    ]:
        if not victim.pop("paw_incoming", False):
            continue
        by = victim.pop("paw_warning_by", "")

        if victim_action == "escape":
            ok, pct = _roll_escape(victim, attacker)
            if ok:
                log.append(f"💨 {victim['name']} breaks free just in time! ({pct:.0f}% chance)")
                victim["escaped"] = True
            else:
                log.append(f"✋ {victim['name']} couldn't escape! ({pct:.0f}% chance)")
                _handle_paw_teleport(attacker, victim, log)
        else:
            log.append(f"✋ Block and dodge are useless. {victim['name']} is helpless...")
            _handle_paw_teleport(attacker, victim, log)

        state["log"] = log
        return state, log
    # ── end paw check ─────────────────────────────────────────────────────────

    # dodge priority flip — successful dodge last turn grants initiative
    a_priority = fa.pop("priority_next_turn", False)
    b_priority = fb.pop("priority_next_turn", False)

    if a_priority and not b_priority:
        log.append(f"⚡ {fa['name']} moves first from last turn's dodge!")
        a_goes_first = True
    elif b_priority and not a_priority:
        log.append(f"⚡ {fb['name']} moves first from last turn's dodge!")
        a_goes_first = False
    else:
        pri_move_a = (_find_move(fa, move_a) or {}).get("priority", 0) if act_a == "attack" else 0
        pri_move_b = (_find_move(fb, move_b) or {}).get("priority", 0) if act_b == "attack" else 0
        # priority is a discrete tier; weight heavily so it overrides speed
        total_a = fa["spd"] + pri_move_a * 10
        total_b = fb["spd"] + pri_move_b * 10
        a_goes_first = total_a >= total_b

    if a_goes_first:
        first,  second  = fa, fb
        act_f,  move_f  = act_a, move_a
        act_s,  move_s  = act_b, move_b
        opp_f,  opp_s   = act_b, act_a
    else:
        first,  second  = fb, fa
        act_f,  move_f  = act_b, move_b
        act_s,  move_s  = act_a, move_a
        opp_f,  opp_s   = act_a, act_b

    log += _resolve_action(first, second, act_f, move_f, opp_f)

    if second["hp"] > 0 and not second.get("escaped"):
        log += _resolve_action(second, first, act_s, move_s, opp_s)
    elif not second.get("escaped"):
        log.append(f"{second['name']} was knocked out before they could act!")

    # end conditions
    a_escaped = fa.get("escaped")
    b_escaped = fb.get("escaped")
    a_down    = fa["hp"] <= 0 or a_escaped
    b_down    = fb["hp"] <= 0 or b_escaped

    if a_down and b_down:
        state["status"]     = "finished"
        state["winner"]     = "draw"
        state["end_reason"] = "draw"
        log.append("Both fighters are down — it's a draw!")
    elif a_down:
        state["status"]     = "finished"
        state["winner"]     = "b"
        state["end_reason"] = "escape" if a_escaped else "hp"
        if not a_escaped:
            log.append(f"🏆 **{fb['name']}** wins!")
    elif b_down:
        state["status"]     = "finished"
        state["winner"]     = "a"
        state["end_reason"] = "escape" if b_escaped else "hp"
        if not b_escaped:
            log.append(f"🏆 **{fa['name']}** wins!")

    state["log"] = log
    return state, log


# ── Display helpers ───────────────────────────────────────────────────────────

def hp_bar(hp, max_hp, width=12):
    filled = min(width, round((hp / max_hp) * width)) if max_hp > 0 else 0
    return "█" * max(0, filled) + "░" * (width - max(0, filled))


def status_block(state):
    """
    Returns a list of two strings, one per fighter, for embedding in Discord.
    e.g. "Luffy        [████████░░░░] 213/320 HP"
    """
    lines = []
    for side in ("a", "b"):
        f    = state["fighters"][side]
        name = f["name"][:20]  # guard against unexpectedly long display names
        bar  = hp_bar(f["hp"], f["max_hp"])
        lines.append(f"`{name:<12} [{bar}] {f['hp']}/{f['max_hp']} HP`")
    return lines


def move_list(fighter_state):
    """Returns list of move name strings for a fighter. Used to build Discord select menus."""
    return [m["name"] for m in fighter_state.get("moves", [])]


def is_finished(state):
    return state["status"] == "finished"
