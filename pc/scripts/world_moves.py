"""world_moves.py - requests that are about DISTANCE and PLACE ("come here", "step closer", "take two steps back", "walk to the bed")
become typed moves for the stream ("/go 1.4 -0.3", "/walk 1.2") instead of seconds of "A person walks forward.".

Where things are comes from the world file VaM-RT Senses writes (Saves/PluginData/vamrt_world.json): the user and the nearby
objects, each as metres ahead of her and to her right. Without that file only the step requests work (they need no target).

Pure Python, no GPU, no VaM: tests at the bottom (python world_moves.py).
"""
import json
import math
import os
import re
import time

USER_STOP = 0.9      # she stops this far from the user (arm's reach)
OBJECT_STOP = 0.55   # ... and this far from a piece of furniture
# sitting on something the right way round (needs "yaw_deg" from Senses 0.6.4+): she walks to a point in front of the seat, then up to
# it, turns her back to it, and sits. SIT_FRONT = where she stands before sitting, metres in front of the seat's centre (her hips
# move back about that much as she sits); SIT_VIA = the point she approaches from, so she never cuts through the seat.
SIT_FRONT = 0.25
SIT_VIA = 1.1
SEAT_HEIGHT = 0.45       # a chair/couch seat above its atom control (which usually sits on the floor)
BED_HEIGHT = 0.50        # the top of a mattress above its atom control; lying on it, the stream raises the floor pose this much
HIP_ABOVE_SEAT = 0.09    # her BVH hips when seated on it (the 7 Nov chair hold was at 0.54 for a 0.45 seat)
LAST_SEAT = None         # {"name", "hip_y", "seat_y"} after a seat plan, for the stream's freeze-hold; None after any other plan
TURN_LINE = "A person turns around 180 degrees. @4 >> A person stands upright."
STEP_M = 0.6         # one step
MAX_MOVE = 7.5       # the stream refuses longer moves (--max-move 8)

_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "couple of": 2, "few": 3}

# "come here", "come closer", "come over here", "step closer to me", "walk up to me", "approach Todd", "get closer"
_TO_USER = re.compile(
    r"\b(?:come|walk|step|move|go|get)(?:s|es|ing)?\s+(?:on\s+)?(?:over\s+)?(?:here|closer|nearer|over here|to me|towards? me|up to me|next to me|over to me|"
    r"closer to me|right up to me)\b|\b(?:sit|stand|be|get)(?:s|ing)?\s+(?:down\s+)?(?:next to|beside|by|near|with|close to)\s+me\b|\bapproach(?:es|ing)?\s+(?:me|him|her|todd|the user)\b|\b(?:come|walk|step|move)(?:s|ing)?\s+(?:over\s+)?(?:up\s+)?"
    r"(?:to|towards?)\s+(?:him|her|todd|the user|you)\b|\bcloser\b", re.I)
# "walk to the bed", "go over to the chair", "come sit on the sofa" (the approach part), "stand by the table", "go to the window"
_TO_OBJECT = re.compile(
    r"\b(?:walk|go|come|move|step|head|stand|wander|stroll|saunter|strut|sashay|make[s]? (?:her|their|his) way|cross(?:es)? the room)(?:s|es|ing)?\s+(?:on\s+)?(?:over\s+)?(?:up\s+)?(?:to|towards?|next to|by|beside|near|over to)\s+"
    r"(?:the|that|this|my|your|her)\s+([a-z][a-z ]{1,30}?)(?=\s*(?:$|[.,!?;]|\band\b|\bthen\b|\bso\b|\bwhere\b))", re.I)
# "step very close to Todd", "get right up next to him", "move close to me": a full approach, not one step; "very close" = closer than arm's reach
_CLOSE_TO_USER = re.compile(
    r"\b(?:step|steps|stepping|move|moves|moving|come|comes|coming|get|gets|getting|walk|walks|walking|go|goes|going|stand|stands|standing)\s+"
    r"(?:over\s+)?(?:(very|really|real|right|super|extra)\s+)?(?:close|near|up|up close|next)\s+(?:to|beside|by|next to|against)\s+(?:me|him|her|todd|the user|you)\b", re.I)
_VERY_CLOSE_STOP = 0.5

_STEPS = re.compile(r"\b(?:take\s+)?(?:(\d+|a|an|one|two|three|four|five|six|couple of|few)\s+)?(?:big\s+|small\s+|little\s+|slow\s+|quick\s+|short\s+)?"
                    r"(steps?|paces?)\s*(forward|forwards|ahead|back|backwards|backward|closer|away|toward\w*|to the (?:left|right)|left|right)?", re.I)
_STEP_VERB = re.compile(r"\bstep(?:s)?\s+(forward|forwards|ahead|back|backwards|backward|closer|away|aside|to the (?:left|right)|left|right)\b", re.I)
_BACK = re.compile(r"\b(?:back (?:up|off|away)|step back|move back|get back|backs? away|give me (?:some )?space|a step back)\b", re.I)
_NEG = re.compile(r"\b(?:don'?t|do not|never|stop|no)\b", re.I)


def load_world(path, max_age=20.0):    # Senses writes at most every 3 s and only when something changed: 4 s was too strict (7 Nov, 15:01)
    """The scene as Senses last wrote it, or None (missing, stale, unreadable)."""
    if not path:
        return None
    try:
        st = os.stat(path)
        if time.time() - st.st_mtime > max_age:
            return None
        with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------- routing round the furniture (v42)
# An approach is a straight line in the stream. On 7 Nov the straight line from where she stood to the chair ran through the bed, and
# with collisions on that was a physics explosion. Senses gives no sizes, so each object gets a footprint radius from its name; a leg
# that would pass closer than that (plus a margin) gets a via point beside the obstacle, up to two legs deep.
_FOOTPRINT = [("bed", 1.25), ("couch", 1.0), ("sofa", 1.0), ("settee", 1.0), ("table", 0.8), ("desk", 0.8), ("counter", 0.9),
              ("dresser", 0.7), ("cabinet", 0.6), ("shelf", 0.6), ("piano", 0.9), ("bath", 1.0), ("tub", 1.0), ("chair", 0.45),
              ("stool", 0.35), ("bench", 0.8), ("plant", 0.4), ("lamp", 0.3)]
ROUTE_MARGIN = 0.35      # clearance beyond the footprint
ROUTE_DEFAULT = 0.6      # footprint of an object whose name says nothing
ROUTE_PERSON = 0.5


def footprint(obj):
    name = str(obj.get("name", "")).lower()
    if obj.get("person"):
        return ROUTE_PERSON
    for key, r in _FOOTPRINT:
        if key in name:
            return r
    return ROUTE_DEFAULT


def _xz(d):
    try:
        return float(d["x"]), float(d["z"])
    except (KeyError, TypeError, ValueError):
        return None


def route(world, goal, exclude=None, depth=0):
    """Via points (list of (x, z)) that take her from where Senses says she is to `goal` without crossing the furniture. [] when the
    straight line is clear (or nothing is known). `exclude` is the object she is walking TO (its own footprint is no obstacle)."""
    start = _xz((world or {}).get("self") or {})
    if start is None or goal is None or depth > 1:
        return []
    px, pz = start
    gx, gz = goal
    dx, dz = gx - px, gz - pz
    length2 = dx * dx + dz * dz
    if length2 < 0.5 * 0.5:
        return []
    hit = None
    for o in (world or {}).get("objects") or []:
        if exclude is not None and o is exclude:
            continue
        c = _xz(o)
        if c is None:
            continue
        r = footprint(o) + ROUTE_MARGIN
        cx, cz = c
        if math.hypot(cx - px, cz - pz) < r:         # she is standing in (or on) it already: it cannot block her leaving
            continue
        if math.hypot(cx - gx, cz - gz) < footprint(o):   # the goal is on it: that is where she is going
            continue
        t = ((cx - px) * dx + (cz - pz) * dz) / length2
        if t <= 0.02 or t >= 0.98:
            continue
        qx, qz = px + t * dx, pz + t * dz
        off = math.hypot(cx - qx, cz - qz)
        if off < r and (hit is None or t < hit[0]):
            hit = (t, o, qx, qz, off, r)
    if hit is None:
        return []
    t, o, qx, qz, off, r = hit
    cx, cz = _xz(o)
    if off > 1e-3:
        nx, nz = (qx - cx) / off, (qz - cz) / off     # away from the obstacle's centre, perpendicular-ish to the leg
    else:
        L = math.sqrt(length2)
        nx, nz = -dz / L, dx / L                      # dead centre: step off to her left
    via = (round(cx + nx * r, 2), round(cz + nz * r, 2))
    rest = route(dict(world, self={"x": via[0], "z": via[1]}), goal, exclude, depth + 1)
    return [via] + rest


def _routed(world, res, exclude=None):
    """Put via points in front of a '/approach x z stop' result: ('/approach via 0', note, [then], [goal approach] + chain)."""
    if not res or not isinstance(res[0], str) or not res[0].startswith("/approach "):
        return res
    try:
        _, x, z, stop = res[0].split()
        goal = (float(x), float(z))
    except ValueError:
        return res
    opts = dict(res[4]) if len(res) > 4 and isinstance(res[4], dict) else {}
    own = list(opts.get("via") or [])
    first = own[0] if own else goal           # with a staging point of its own (a seat's front) the route is to that point
    vias = route(world, first, exclude)
    if not vias:
        return res
    names = ", ".join(str(o.get("name")) for o in _blockers(world, first, exclude))
    note = res[1] + (f" (round the {names})" if names else " (round the furniture)")
    then_req = res[2] if len(res) > 2 else None
    chain = list(res[3]) if len(res) > 3 else []
    opts["via"] = vias + own
    return (res[0], note, then_req, chain, opts)


def _blockers(world, goal, exclude):
    """The objects whose footprint the straight line crosses (for the note only)."""
    start = _xz((world or {}).get("self") or {})
    if start is None:
        return []
    px, pz = start
    gx, gz = goal
    dx, dz = gx - px, gz - pz
    L2 = dx * dx + dz * dz
    out = []
    for o in (world or {}).get("objects") or []:
        c = _xz(o)
        if c is None or o is exclude or L2 < 1e-6:
            continue
        cx, cz = c
        r = footprint(o) + ROUTE_MARGIN
        if math.hypot(cx - px, cz - pz) < r or math.hypot(cx - gx, cz - gz) < footprint(o):
            continue
        t = ((cx - px) * dx + (cz - pz) * dz) / L2
        if 0.02 < t < 0.98 and math.hypot(cx - (px + t * dx), cz - (pz + t * dz)) < r:
            out.append(o)
    return out


def _approach(target, stop, note):
    """"/approach x z stop" when Senses gave world coordinates (the stream converts them with its learned frame), else None."""
    if target and "x" in target and "z" in target:
        return (f"/approach {round(float(target['x']), 2)} {round(float(target['z']), 2)} {round(stop, 2)}", note)
    return None


def _towards(fwd, right, stop):
    """A goal `stop` metres short of a point (fwd, right) in her frame. None if she is already there."""
    d = math.hypot(fwd, right)
    if d <= stop + 0.25:
        return None
    k = (d - stop) / d
    return fwd * k, right * k


def _clamp(fwd, right):
    d = math.hypot(fwd, right)
    if d > MAX_MOVE:
        fwd, right = fwd * MAX_MOVE / d, right * MAX_MOVE / d
    return round(fwd, 2), round(right, 2)


def _find_object(world, words):
    """The nearest reported object whose name contains one of the words ('bed' matches 'cyberpunkbed')."""
    best = None
    for o in (world or {}).get("objects") or []:
        name = str(o.get("name", "")).lower()
        if any(w and w in name for w in words):
            d = math.hypot(float(o.get("fwd", 0)), float(o.get("right", 0)))
            if best is None or d < best[0]:
                best = (d, o)
    return best[1] if best else None


# "lie on the bed", "go lay down on the bed", "sit on the chair", "kneel by the sofa": walk to it, then do the thing
_ON_OBJECT = re.compile(
    r"\b(?:(?:go|come|walk|move)\s+(?:and\s+|over\s+and\s+)?)?(lie|lies|lay|lays|lying|laying|sit|sits|sitting|kneel|kneels|kneeling|stand|stands|get|gets)\s+"
    r"(?:down\s+)?(?:on|onto|in|into|at|by|beside|next to|near|upon)\s+(?:the|that|this|my|your|her)\s+([a-z][a-z ]{1,30}?)"
    r"(?=\s*(?:$|[.,!?;]|\band\b|\bthen\b|\bso\b))", re.I)
_THEN_DO = {"lie": "lie down", "lay": "lie down", "sit": "sit down", "kneel": "kneel down", "stand": None, "get": None}
# "go to the bed and lie down": what comes after the place
_AND_THEN = re.compile(r"\b(?:and|then|and then)\s+([a-z][^.!?;]{2,60})", re.I)


def _then_request(t, after_pos):
    """The part of the request to carry out once she has walked there ('and lie down' -> 'lie down'), or None."""
    m = _AND_THEN.search(t, after_pos)
    if m:
        rest = m.group(1).strip()
        if rest and not re.match(r"^(?:stop|wait|stay)\b", rest):
            return rest
    return None


def named_place(request):
    """The place a request wants her to go to or be at ("walk to the bed", "sits on the couch"), or None. Used to tell "no such
    object in the scene" apart from "not a place request" when move_for() returns None."""
    t = " ".join((request or "").lower().split())
    for rx in (_ON_OBJECT, _TO_OBJECT):
        m = rx.search(t)
        if m:
            target = m.group(2) if rx is _ON_OBJECT else m.group(1)
            words = [w for w in re.split(r"[^a-z]+", target) if len(w) > 2 and w not in ("the", "and", "over", "there")]
            if words and words[0] not in ("me", "him", "her", "todd", "user", "left", "right", "side", "front", "back", "way"):
                return " ".join(words)
    return None


# lying on a bed the right way round (v39b): the model's "lies down" sits and lies BACK, so she stands at the foot of the bed with her
# back to it and lies back along its length; the stream raises the pose to the mattress as she goes down (vamrt_seat.json, kind lie).
# The foot of the bed is taken as the atom's forward (+yaw) end; `[sit flip]` in the atom name flips it, as for seats.
LIE_HALF = [("bed", 0.95), ("couch", 0.8), ("sofa", 0.8), ("settee", 0.8), ("bench", 0.7), ("table", 0.8)]
LIE_VIA = 1.0        # staging point this far beyond the foot edge
LIE_STAND = 0.2      # where she stands before lying back, beyond the foot edge
LIE_BACK = True      # she lies back (turns her back to the bed first); False if the model turns out to lie face down


def _lie_plan(obj):
    try:
        cx, cz = float(obj["x"]), float(obj["z"])
        yaw = math.radians(float(obj["yaw_deg"]))
    except (KeyError, TypeError, ValueError):
        return None
    name = str(obj.get("name", "")).lower()
    half = next((h for key, h in LIE_HALF if key in name), 0.6)
    fx, fz = math.sin(yaw), math.cos(yaw)
    foot = (cx + fx * half, cz + fz * half)
    via = (round(foot[0] + fx * LIE_VIA, 2), round(foot[1] + fz * LIE_VIA, 2))
    stand = (round(foot[0] + fx * LIE_STAND, 2), round(foot[1] + fz * LIE_STAND, 2))
    try:
        y = float(obj.get("y", 0.0))
    except (TypeError, ValueError):
        y = 0.0
    top = y if y >= 0.25 else y + BED_HEIGHT
    global LAST_SEAT
    LAST_SEAT = {"name": str(obj.get("name")), "kind": "lie", "top_y": round(top, 2)}
    note = f"walks round to the foot of the {obj.get('name')}" + (", turns her back to it and lies back along it" if LIE_BACK else " and lies down along it")
    return (f"/approach {stand[0]} {stand[1]} 0", note, "lie down", [TURN_LINE] if LIE_BACK else [], {"via": [via]})


def _seat_plan(obj):
    """Sit on a chair/bed the right way round: ("/approach via", note, "sit down", [chained lines]). The chain runs after the first
    walk: walk up to the seat, turn around (her back to it), and only then the sit. yaw_deg is the seat's facing in VaM
    (0 = +Z, positive towards +X, the same convention Senses uses for her own facing)."""
    try:
        yaw = math.radians(float(obj["yaw_deg"]))
        cx, cz = float(obj["x"]), float(obj["z"])
    except (KeyError, TypeError, ValueError):
        return None
    fx, fz = math.sin(yaw), math.cos(yaw)
    # a chair's control sits where she sits; a bed's or couch's sits in the middle of something long, so the front edge is further out
    name = str(obj.get("name", "")).lower()
    edge = next((h for key, h in LIE_HALF if key in name), 0.0) if any(k in name for k in ("bed", "couch", "sofa", "settee", "bench")) else 0.0
    via = (round(cx + fx * (edge + SIT_VIA), 2), round(cz + fz * (edge + SIT_VIA), 2))
    stand = (cx + fx * (edge + SIT_FRONT), cz + fz * (edge + SIT_FRONT))
    note = f"walks round to the front of the {obj.get('name')}, up to it, turns her back to it, then sits"
    # the seat height for the stream's freeze-hold (vamrt_seat.json): Senses' y is the atom control's height, which for most
    # furniture is the floor, so a standard seat height is added; a control that already sits at seat height is taken as it is
    try:
        y = float(obj.get("y", 0.0))
    except (TypeError, ValueError):
        y = 0.0
    seat_y = y if y >= 0.25 else y + SEAT_HEIGHT
    global LAST_SEAT
    LAST_SEAT = {"name": str(obj.get("name")), "kind": "seat", "hip_y": round(seat_y + HIP_ABOVE_SEAT, 2), "seat_y": round(seat_y, 2)}
    # one planned move through the staging point in front of the seat (v39), then the turn; the sit is the then-request
    return (f"/approach {round(stand[0], 2)} {round(stand[1], 2)} 0", note, "sit down", [TURN_LINE], {"via": [via]})


def move_for(request, world=None, right_sign=1.0):
    """("/go f r" or "/walk d", note) for a distance/place request, else None (let the normal prompter handle it).
    right_sign = -1 mirrors the Senses frame (if she walks to the wrong side on "come here", the two frames differ in handedness)."""
    if world and right_sign != 1.0:
        world = json.loads(json.dumps(world))
        for o in [world.get("user") or {}] + list(world.get("objects") or []):
            if "right" in o:
                o["right"] = float(o["right"]) * right_sign
    global LAST_SEAT
    LAST_SEAT = None
    t = " ".join((request or "").lower().replace("'", "'").split())
    if not t or _NEG.search(t):
        return None
    user = (world or {}).get("user") or None

    # a thing to do AT a place: "lie on the bed", "sit on the chair", "go lay down on the bed"
    m = _ON_OBJECT.search(t)
    if m:
        verb = re.sub(r"(?:s|es|ing)$", "", m.group(1).lower())
        verb = {"lie": "lie", "ly": "lie", "lay": "lay", "sit": "sit", "sitt": "sit", "kneel": "kneel", "stand": "stand", "get": "get"}.get(verb, verb)
        words = [w for w in re.split(r"[^a-z]+", m.group(2).lower()) if len(w) > 2 and w not in ("the", "and", "over", "there")]
        obj = _find_object(world, words) if words else None
        if obj is not None and verb == "sit" and "yaw_deg" in obj and "x" in obj and "z" in obj:
            seat = _seat_plan(obj)
            if seat:
                return _routed(world, seat, obj)
        if (obj is not None and verb in ("lie", "lay") and "yaw_deg" in obj and "x" in obj and "z" in obj
                and (obj.get("lie") or any(k in str(obj.get("name", "")).lower() for k in ("bed", "couch", "sofa", "settee")))):
            lie = _lie_plan(obj)
            if lie:
                return _routed(world, lie, obj)
        if obj is not None:
            then = _THEN_DO.get(verb)
            if then in ("lie down", "sit down"):
                try:
                    y = float(obj.get("y", 0.0))
                except (TypeError, ValueError):
                    y = 0.0
                if then == "lie down":
                    top = y if y >= 0.25 else y + BED_HEIGHT
                    LAST_SEAT = {"name": str(obj.get("name")), "kind": "lie", "top_y": round(top, 2)}
                else:
                    seat_y = y if y >= 0.25 else y + SEAT_HEIGHT
                    LAST_SEAT = {"name": str(obj.get("name")), "kind": "seat", "hip_y": round(seat_y + HIP_ABOVE_SEAT, 2), "seat_y": round(seat_y, 2)}
            g = _towards(float(obj.get("fwd", 0)), float(obj.get("right", 0)), OBJECT_STOP)
            if g is None:        # already there: only the thing itself is left to do
                return ("KEEP", f"she is already at the {obj.get('name')}") if not then else ("THEN", then, then)
            note = f"walks to the {obj.get('name')} ({math.hypot(*g):.1f} m)" + (f", then {then}" if then else "")
            ap = _approach(obj, OBJECT_STOP, note)
            if ap:
                return _routed(world, ap + ((then,) if then else ()), obj)
            f, r = _clamp(*g)
            return (f"/go {f} {r}", note) + ((then,) if then else ())
    # a place: "walk to the bed"
    m = _TO_OBJECT.search(t)
    if m:
        target = m.group(1).strip()
        then = _then_request(t, m.end())
        words = [w for w in re.split(r"[^a-z]+", target) if len(w) > 2 and w not in ("the", "and", "over", "there")]
        if not words or words[0] in ("me", "him", "her", "todd", "user", "left", "right", "side", "front", "back", "door", "way"):
            m = None
        else:
            obj = _find_object(world, words)
            if obj is None:
                return None   # the LLM / fast path can still make something of it (or nothing)
            g = _towards(float(obj.get("fwd", 0)), float(obj.get("right", 0)), OBJECT_STOP)
            if g is None:
                return ("KEEP", f"she is already at the {obj.get('name')}")
            note = f"walks to the {obj.get('name')} ({math.hypot(*g):.1f} m)" + (f", then {then}" if then else "")
            ap = _approach(obj, OBJECT_STOP, note)
            if ap:
                return _routed(world, ap + ((then,) if then else ()), obj)
            f, r = _clamp(*g)
            return (f"/go {f} {r}", note) + ((then,) if then else ())

    # "step very close to him": an approach that ends close, whatever the verb (the step branch below would make it one 0.6 m step)
    m = _CLOSE_TO_USER.search(t)
    if m and user:
        stop = _VERY_CLOSE_STOP if m.group(1) else USER_STOP
        g = _towards(float(user.get("fwd", 0)), float(user.get("right", 0)), stop)
        if g is None:
            return ("KEEP", "she is already that close")
        f, r = _clamp(*g)
        ap = _approach(user, stop, f"comes {'very ' if m.group(1) else ''}close to you ({math.hypot(f, r):.1f} m)")
        ap = _routed(world, ap) if ap else None
        return ap if ap else (f"/go {f} {r}", f"comes close to you ({math.hypot(f, r):.1f} m)")

    # backing off needs no target
    if _BACK.search(t):
        n = _step_n(t) or 2
        return (f"/go {-round(n * STEP_M, 2)} 0", f"backs away {n} step(s)")

    # steps with a direction
    sm = _STEP_VERB.search(t) or _STEPS.search(t)
    if sm and re.search(r"\bsteps?\b|\bpaces?\b", t):
        direction = (sm.group(sm.lastindex) or "forward").lower() if sm.lastindex else "forward"
        n = _step_n(t) or 1
        d = round(n * STEP_M, 2)
        if direction.startswith(("back",)) or direction == "away":
            return (f"/go {-d} 0", f"{n} step(s) back")
        if "left" in direction:
            return (f"/go 0 {-d}", f"{n} step(s) to the left")
        if "right" in direction:
            return (f"/go 0 {d}", f"{n} step(s) to the right")
        if direction in ("closer",) or direction.startswith("toward") or _TO_USER.search(t):
            if user:
                g = _towards(float(user.get("fwd", 0)), float(user.get("right", 0)), USER_STOP)
                if g is None:
                    return ("KEEP", "she is already within reach")
                gf, gr = g
                dist = math.hypot(gf, gr)
                full = math.hypot(float(user.get("fwd", 0)), float(user.get("right", 0)))
                ap = _approach(user, max(USER_STOP, full - d), f"{n} step(s) towards you")
                if ap:
                    return _routed(world, ap)
                k = min(1.0, d / dist) if dist > 0 else 0
                f, r = _clamp(gf * k, gr * k)
                return (f"/go {f} {r}", f"{n} step(s) towards you")
            return (f"/walk {d}", f"{n} step(s) forward (no world file: straight ahead)")
        return (f"/walk {d}", f"{n} step(s) forward")

    # the user: "come here", "come closer", "walk up to me"
    if _TO_USER.search(t):
        if not user:
            if world:        # Senses is writing the world file but has no camera position: a blind walk would be worse than nothing
                return ("KEEP", "Senses reports no position for you (no camera in the world file), so there is nowhere to walk to")
            return None
        g = _towards(float(user.get("fwd", 0)), float(user.get("right", 0)), USER_STOP)
        if g is None:
            return ("KEEP", "she is already within reach")
        f, r = _clamp(*g)
        ap = _approach(user, USER_STOP, f"walks up to you ({math.hypot(f, r):.1f} m)")
        if ap:
            return _routed(world, ap)
        return (f"/go {f} {r}", f"walks up to you ({math.hypot(f, r):.1f} m)")
    return None


def _step_n(t):
    m = re.search(r"\b(\d+|a|an|one|two|three|four|five|six|couple of|few)\s+(?:big\s+|small\s+|little\s+|slow\s+|quick\s+|short\s+)?(?:steps?|paces?)\b", t)
    if m:
        v = m.group(1)
        return int(v) if v.isdigit() else _NUM.get(v, 1)
    return 3 if re.search(r"\bsteps\b|\bpaces\b", t) else (1 if re.search(r"\bstep\b|\bpace\b", t) else None)


if __name__ == "__main__":
    WS = {"user": {"fwd": 3, "right": 0, "x": 0, "z": 3}, "objects": [{"name": "aptchair", "fwd": 2.0, "right": 1.0, "x": 2.0, "z": 0.0, "yaw_deg": 90.0, "sit": True}]}
    r = move_for("sit down in that chair", WS)
    assert r[0] == "/approach 2.25 0.0 0" and r[2] == "sit down" and "turns around" in r[3][0] and r[4]["via"] == [(3.1, 0.0)], r
    assert LAST_SEAT == {"name": "aptchair", "kind": "seat", "hip_y": 0.54, "seat_y": 0.45}, LAST_SEAT
    assert move_for("lie on the chair", WS)[0].startswith("/approach 2.0 0.0 0.55"), move_for("lie on the chair", WS)
    print("ok  seat plan:", r[1])
    W2 = {"user": {"fwd": 3.2, "right": -1.5, "dist": 3.5, "x": 1.0, "z": 4.0}, "objects": [{"name": "cyberpunkbed", "fwd": -1.0, "right": 1.8, "x": -2.0, "z": 0.5}]}
    print("coords:", move_for("come here", W2), move_for("walk to the bed", W2), move_for("step closer", W2))
    W = {"user": {"fwd": 3.2, "right": -1.5, "dist": 3.5},
         "objects": [{"name": "cyberpunkbed", "fwd": -1.0, "right": 1.8, "sit": True, "lie": True},
                     {"name": "chair", "fwd": 2.0, "right": 2.0, "sit": True}]}
    cases = [
        ("step forward", None, "/walk 0.6"), ("take three steps forward", None, "/walk 1.8"), ("step back", None, "/go -0.6 0"),
        ("back up", None, "/go -1.2 0"), ("take a step to the left", None, "/go 0 -0.6"), ("come here", None, None),
        ("come here", W, "/go"), ("come closer", W, "/go"), ("step closer", W, "/go"), ("walk to the bed", W, "/go -0.7"),
        ("go over to the chair", W, "/go"), ("walk to the window", W, None), ("don't come closer", W, None),
        ("dance for me", W, None), ("sit down", W, None), ("walk forward", None, None), ("come sit next to me", W, "/go"),
        ("step very close to Todd", W2, "/approach 1.0 4.0 0.5"), ("steps closer to him", W2, "/approach 1.0 4.0"),
        ("get right up next to me", W2, "/approach 1.0 4.0 0.5"), ("move close to you", W, "/go"), ("step very close to Todd", None, "/walk 0.6"),
    ]
    bad = 0
    for req, w, want in cases:
        got = move_for(req, w)
        line = got[0] if got else None
        ok = (want is None and line is None) or (want is not None and line is not None and line.startswith(want))
        bad += not ok
        print(("ok " if ok else "BAD"), f"{req!r:34} -> {got}")
    raise SystemExit(bad)
