"""mood_style.py - how she feels colours how she moves (first step of "emotional affect on motion").

The Voxta mood script owns her state (stance: engage / playful / guarded / withdrawn / disengage, plus an energy level). It reaches
the prompter through the same channel as every movement request - the BVH Player's "Motion Request" - as a tag:

    walk over to me [mood stance=guarded energy=low]        (appended to a request by perform_action)
    [mood stance=playful energy=high]                      (on its own, sent when the stance changes)

The prompter strips the tag before anything else looks at the request (the fast path, the cache, the LLM), remembers the mood,
and applies it in two places that the ARDY model is known to respond to:
  * the ACTION part of a line ("A person walks forward." -> "A person walks forward slowly with slumped shoulders."): adverbs and
    posture words that HumanML3D-style captions use. The final hold part is never touched: the stream, the stand guard and idle life
    all key on the plain "A person stands upright." text.
  * idle life: each stance prefers some idle groups over others (arms crossed and glances when guarded, hair and talk-hands when playful).
Nothing here forbids anything: a request is still carried out in every mood; only its manner changes.
"""
import re

TAG = re.compile(r"\s*\[\s*mood\b([^\]]*)\]\s*", re.I)
_KV = re.compile(r"(\w+)\s*=\s*([\w.-]+)")

STANCES = ("engage", "playful", "guarded", "withdrawn", "disengage")
ENERGY = ("low", "mid", "high")
# "walk=seductive" in the tag: how SHE said she walks ("*saunters over to the bed, hips swaying*"): it beats the stance's manner
WALK_MANNERS = {
    "seductive": " seductively, swaying their hips", "slow": " slowly", "brisk": " briskly", "quick": " quickly",
    "confident": " confidently", "playful": " with a bounce in their step", "nervous": " nervously", "lazy": " lazily",
    "tiptoe": " on tiptoe", "stagger": " unsteadily",
}

# action verb (regex on the part) -> {stance: phrase appended before the full stop}; "" = leave it plain.
# energy refines engage/playful only, so a calm happy walk stays a plain walk.
_WALK = {
    "engage":    {"low": " slowly", "mid": "", "high": " briskly"},
    "playful":   {"low": " with a light, easy step", "mid": " with a bounce in their step", "high": " briskly with a bounce in their step"},
    "guarded":   " slowly with their arms crossed",
    "withdrawn": " slowly with slumped shoulders",
    "disengage": " quickly with their head down",
}
_DANCE = {
    "engage": {"low": " slowly", "mid": "", "high": " energetically"},
    "playful": {"low": " playfully", "mid": " playfully", "high": " energetically and playfully"},
    "guarded": " half-heartedly", "withdrawn": " slowly and half-heartedly", "disengage": " stiffly",
}
_WAVE = {"engage": "", "playful": " cheerfully", "guarded": " briefly", "withdrawn": " weakly", "disengage": " dismissively"}
_STRETCH = {"engage": "", "playful": " happily", "guarded": "", "withdrawn": " slowly", "disengage": ""}
_TURN = {"engage": "", "playful": " quickly", "guarded": " slowly", "withdrawn": " slowly", "disengage": " sharply"}

STYLES = [
    (re.compile(r"^A person (?:walks|is walking|strolls|marches|paces)\b", re.I), _WALK),
    (re.compile(r"^A person (?:dances|is dancing)\b", re.I), _DANCE),
    (re.compile(r"^A person waves\b", re.I), _WAVE),
    (re.compile(r"^A person stretches\b", re.I), _STRETCH),
    (re.compile(r"^A person turns (?:around|left|right)\b", re.I), _TURN),
]
# a part that already carries a manner is left alone (the LLM or the user chose it)
_HAS_MANNER = re.compile(r"\b(?:slowly|quickly|briskly|happily|sadly|angrily|nervously|lazily|cheerfully|energetically|playfully|"
                         r"half-heartedly|stiffly|sharply|weakly|dismissively|slumped|head down|arms crossed|bounce)\b", re.I)

# idle life: group weight multipliers per stance (1 = as usual). Keys are the idle groups in idle_life.GROUPS / wordings.
IDLE_BIAS = {
    "engage":    {},
    "playful":   {"idle.hair": 2.0, "idle.talk_hands": 1.8, "idle.shrug_tilt": 1.5, "idle.stretch": 1.5, "idle.arms_cross": 0.3},
    "guarded":   {"idle.arms_cross": 3.0, "idle.glance_back": 1.5, "idle.look": 1.5, "idle.talk_hands": 0.4, "idle.hair": 0.4, "idle.stretch": 0.3},
    "withdrawn": {"idle.arms_cross": 3.0, "idle.glance_back": 2.0, "idle.lean": 1.5, "idle.talk_hands": 0.2, "idle.hair": 0.2,
                  "idle.stretch": 0.1, "idle.nod_slow": 0.5, "idle.listen": 0.5},
    "disengage": {"idle.arms_cross": 3.0, "idle.glance_back": 2.0, "idle.talk_hands": 0.1, "idle.hair": 0.1, "idle.stretch": 0.1,
                  "idle.nod_slow": 0.2, "idle.listen": 0.3, "idle.shrug_tilt": 0.3},
}


def parse(text):
    """Split a request into (request_without_tag, mood_or_None). mood = {"stance": ..., "energy": ...} (unknown values dropped)."""
    mood = None
    for m in TAG.finditer(text or ""):
        kv = dict((k.lower(), v.lower()) for k, v in _KV.findall(m.group(1)))
        mood = {}
        if kv.get("stance") in STANCES:
            mood["stance"] = kv["stance"]
        if kv.get("energy") in ENERGY:
            mood["energy"] = kv["energy"]
        if kv.get("walk") in WALK_MANNERS:
            mood["walk"] = kv["walk"]
        if kv.get("src") in ("self", "user"):
            mood["src"] = kv["src"]      # self = a movement she narrated herself ("*walks to the bed*"), not something the user asked
    clean = " ".join(TAG.sub(" ", text or "").split())
    return clean, mood


def phrase(table, mood):
    stance = (mood or {}).get("stance", "engage")
    if table is _WALK and (mood or {}).get("walk") in WALK_MANNERS:
        return WALK_MANNERS[mood["walk"]]
    v = table.get(stance, "")
    if isinstance(v, dict):
        v = v.get((mood or {}).get("energy", "mid"), "")
    return v or ""


def style_line(line, mood):
    """Colour the action parts of a validated prompt line by the mood. The final part (the hold) and '[free]' are kept as they are."""
    if not line or line == "KEEP" or not mood:
        return line
    if mood.get("stance", "engage") == "engage" and mood.get("energy", "mid") == "mid" and not mood.get("walk"):
        return line
    parts = line.split(">>")
    if len(parts) < 2:
        return line                      # a single open-ended part: it is the hold itself
    out = []
    for i, part in enumerate(parts):
        p = part.strip()
        if i == len(parts) - 1:
            out.append(p)
            continue
        m = re.search(r"\s*@\s*\d+(?:\.\d+)?\s*$", p)
        at = p[m.start():] if m else ""
        body = p[: m.start()].strip() if m else p
        if body.endswith(".") and not _HAS_MANNER.search(body):
            for rx, table in STYLES:
                if rx.search(body):
                    add = phrase(table, mood)
                    if add:
                        body = body[:-1] + add + "."
                    break
        out.append(body + at)
    return " >> ".join(out)


def walk_text(mood):
    """The wording for a planned walk in this mood ("A person walks forward slowly with their arms crossed."), or None when plain."""
    add = phrase(_WALK, mood) if mood else ""
    return f"A person walks forward{add}." if add else None


def idle_weight(key, mood):
    return IDLE_BIAS.get((mood or {}).get("stance", "engage"), {}).get(key, 1.0)


def describe(mood):
    if not mood:
        return "neutral"
    return " ".join(f"{k}={v}" for k, v in sorted(mood.items()))


if __name__ == "__main__":
    tests = [
        ("walk over to me [mood stance=guarded energy=low]", "walk over to me", {"stance": "guarded", "energy": "low"}),
        ("[mood stance=playful energy=high]", "", {"stance": "playful", "energy": "high"}),
        ("sit down", "sit down", None),
        ("dance [mood stance=nonsense]", "dance", {}),
        ("walk to the bed [mood stance=engage energy=mid walk=seductive src=self]", "walk to the bed", {"stance": "engage", "energy": "mid", "walk": "seductive", "src": "self"}),
    ]
    for text, want_clean, want_mood in tests:
        c, md = parse(text)
        assert (c, md) == (want_clean, want_mood), (text, c, md)
    assert walk_text({"stance": "engage", "energy": "mid", "walk": "seductive"}) == "A person walks forward seductively, swaying their hips."
    assert style_line("A person walks forward. @3 >> A person stands upright.", {"stance": "engage", "energy": "mid", "walk": "slow"}) == \
        "A person walks forward slowly. @3 >> A person stands upright."
    W = "A person walks forward. @4 >> A person stands upright."
    assert style_line(W, {"stance": "withdrawn"}) == "A person walks forward slowly with slumped shoulders. @4 >> A person stands upright."
    assert style_line(W, {"stance": "engage", "energy": "mid"}) == W
    assert style_line(W, {"stance": "engage", "energy": "high"}) == "A person walks forward briskly. @4 >> A person stands upright."
    assert style_line("A person stands upright.", {"stance": "disengage"}) == "A person stands upright."
    assert style_line("A person walks forward slowly. @4 >> A person stands upright.", {"stance": "playful", "energy": "high"}) == \
        "A person walks forward slowly. @4 >> A person stands upright."
    assert style_line("A person stands up from a chair. >> A person dances. [free]", {"stance": "playful", "energy": "high"}) == \
        "A person stands up from a chair. >> A person dances. [free]"
    assert style_line("A person turns around 180 degrees. >> A person walks forward. @8 >> A person stands upright.", {"stance": "disengage"}) == \
        "A person turns around 180 degrees sharply. >> A person walks forward quickly with their head down. @8 >> A person stands upright."
    assert idle_weight("idle.arms_cross", {"stance": "guarded"}) == 3.0 and idle_weight("idle.hair", None) == 1.0
    assert walk_text({"stance": "guarded"}) == "A person walks forward slowly with their arms crossed." and walk_text({"stance": "engage"}) is None
    print("mood_style: all good")
