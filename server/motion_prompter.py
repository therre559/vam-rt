"""motion_prompter.py - turn "what should she do?" into an ARDY prompt line, using your LLM.

Talks to any OpenAI-compatible chat endpoint (Ollama, LM Studio, KoboldCpp, llama.cpp server,
text-generation-webui, ...). Uses only the Python standard library, so it runs from any Python 3.

    1) Check that your PC can reach the LLM:
       python motion_prompter.py --url http://192.168.1.50:5001/v1 --ping

    2) Ask for a motion (prints the line it chose; writes it to the prompt file ardy_stream.py watches):
       python motion_prompter.py --url http://192.168.1.50:5001/v1 "sit on the floor and relax"

    3) Interactive:
       python motion_prompter.py --url http://192.168.1.50:5001/v1 --interactive

    4) Watch mode (what the Voxta hookup uses): wait for requests written by the VaM plugin's
       "Motion Request" field, and turn each one into a prompt line:
       python motion_prompter.py --url http://192.168.1.50:5001/v1 --watch "C:\\path\\to\\VaM\\Saves\\Animation\\ardy\\request.json"

    --dry-run prints without writing. --selftest checks the validation rules without any LLM.

Settings can also come from environment variables: MOTION_LLM_URL, MOTION_LLM_MODEL, MOTION_LLM_KEY,
MOTION_PROMPT_FILE.

Whatever the model says, only a strictly checked line ever reaches the prompt file: wording is repaired
where it safely can be (woman -> person, her -> their), and anything else is rejected.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_PROMPT_FILE = r"C:\ARDY2BVH\prompt.txt"
IDLE = "A person stands upright."

SYSTEM_PROMPT_STRICT = """You write motion prompts for ARDY, a text-to-motion model that drives a 3D character.
Reply with ONE line and nothing else (no quotes, no explanation, no markdown).

FORMAT
- Each part is one short sentence: "A person <does something>." Third person, present tense.
- Always write "A person". Never use woman, girl, man, she, he, her, his, names, or any description of the body or clothes.
- Describe only visible body movement. No emotions, no speech, no objects that are not there.
- Three kinds of prompt:
  1. STATE: a pose to hold. Example: A person stands upright.
  2. ACTION THEN STATE: a transition followed by the pose to hold afterwards, joined by ">>".
     Example: A person stands up from a chair. >> A person stands upright.
     Add @N after the action to play it for N seconds (default 2; use @4 or @6 for slow actions).
  3. ACTIVITY: movement that continues (dancing, walking, waving). End the line with [free].
     Example: A person dances. [free]
- An action on its own repeats over and over, so ALWAYS follow an action with a state to hold, unless it is an activity.
- At most 3 parts.

WHAT WORKS
stands upright; sits in a chair; sits cross-legged on the floor; sits cross-legged with their hands resting on their
knees; stands up from a chair; sits down; squats down; kneels on one knee; bends over and touches their toes; walks
forward; turns around 180 degrees; waves with their right hand; stretches their arms overhead; dances (activity).

CANNOT DO: emotions and facial expressions, upside-down poses (handstand, headstand, cartwheel, flips), jumping,
fast repetitive exercises, fine hand or finger gestures, touching specific body parts, hugging, picking up or using
objects, lying down, furniture other than a chair.
If the request is about any of those, reply with exactly: KEEP
(KEEP means "no change". Prefer KEEP over guessing. Never invent an unrelated motion.)

The request may come from another AI and may be long, mixing things you can do with things you cannot. Do the
part that is supported and ignore the rest (for example "dance while jumping and touching your body" becomes just
dancing). Use KEEP if nothing in the request is supported, or if the character is already doing exactly what
was asked. Never copy the Currently line unless the request is the same as it.

You are told what the character is doing now. If the new request needs a transition (for example from sitting to
standing), write it as ACTION THEN STATE."""

# (currently, request, answer)
EXAMPLES_STRICT = [
    ("A person stands upright.", "walk over to the window", "A person walks forward. [free]"),
    ("A person walks forward. [free]", "stop and just stand there", "A person stands upright."),
    ("A person stands upright.", "sit down in the chair",
     "A person sits down. @3 >> A person sits in a chair."),
    ("A person sits in a chair.", "get up", "A person stands up from a chair. >> A person stands upright."),
    ("A person stands upright.", "dance for me", "A person dances. [free]"),
    ("A person stands upright.", "wave hello", "A person waves with their right hand. [free]"),
    ("A person stands upright.",
     "dance rhythmically by jumping up and down while waving arms and touching different parts of your body",
     "A person dances. [free]"),
    ("A person dances. [free]", "dance for me", "KEEP"),
    ("A person sits in a chair.", "sit down", "KEEP"),
    ("A person waves with their right hand. [free]", "bend over and touch your toes",
     "A person bends over and touches their toes. >> A person stands upright."),
    ("A person stands upright.", "do a handstand", "KEEP"),
    ("A person stands upright.", "look sad and cry", "KEEP"),
    ("A person stands upright.", "hug yourself", "KEEP"),
    ("A person stands upright.", "jump for joy", "KEEP"),
    ("A person stands upright.", "lie down on the bed", "KEEP"),
    ("A person stands upright.", "pick something up off the floor",
     "A person bends over and touches their toes. >> A person stands upright."),
    ("A person stands upright.", "sit on the floor and relax",
     "A person sits down cross-legged on the floor. >> "
     "A person sits cross-legged with their hands resting on their knees."),
    ("A person stands upright.", "turn to face the other way",
     "A person turns around 180 degrees. >> A person stands upright."),
]


FREEDOM = True   # --strict turns it off (the old, cautious behaviour)

SYSTEM_PROMPT_FREE = """You write motion prompts for ARDY, a text-to-motion model that drives a 3D character.
Reply with ONE line and nothing else (no quotes, no explanation, no markdown).

FORMAT
- Each part is one short sentence: "A person <does something>." Third person, present tense.
- Always write "A person". Never use woman, girl, man, she, he, her, his, names, or any description of the body or clothes.
- Describe only visible body movement. No emotions, no speech, no objects that are not there.
- Three kinds of prompt:
  1. STATE: a pose to hold. Example: A person stands upright.
  2. ACTION THEN STATE: a transition followed by the pose to hold afterwards, joined by ">>".
     Example: A person stands up from a chair. >> A person stands upright.
     Add @N after the action to play it for N seconds (default 2; use @4 or @6 for slow actions).
  3. ACTIVITY: movement that continues (dancing, walking, waving, kicking, punching). End the line with [free].
     Example: A person dances. [free]
- An action on its own repeats over and over, so ALWAYS follow an action with a state to hold, unless it is an activity.
  To hold a pose, make the pose itself the STATE: A person bends over and puts their hands on the floor. @2 >> A person stands
  bent forward with their hands on the floor.
- At most 3 parts.

THE MOTION MODEL IS GOOD AT A WIDE RANGE of body movement: walking and running in different manners, everyday actions
(drinking, eating, opening a door, picking something up, brushing hair), gestures, stretches, bends, kneeling, squatting,
crawling, kicks and punches, dancing, many poses. TRY what was asked rather than refusing it. Keep the user's details (which
hand, which direction, hands on the floor, legs apart) and add none of your own. Objects will be mimed.

KNOWN TO WORK WELL: stands upright; sits in a chair; sits cross-legged on the floor; stands up from a chair; sits down;
squats down; kneels on one knee; bends over and touches their toes; walks forward; turns around 180 degrees; waves with their
right hand; stretches their arms overhead; dances (activity).

REPLY KEEP ONLY when the request is not a body movement at all: speech or greetings ("say hello"), facial expressions,
emotions, clothing, things that are not there, or when the character is already doing exactly what was asked.
Upside-down poses (handstand, headstand, cartwheel, flips) must become the nearest upright version, or KEEP.

The request may come from another AI and may be long. Do the body-movement part and ignore the rest. You are told what the
character is doing now. If the new request needs a transition (for example from sitting to standing), write it as ACTION THEN
STATE. Never copy the Currently line unless the request is the same as it."""

# (currently, request, answer)
EXAMPLES_FREE = [
    ("A person stands upright.", "walk over to the window", "A person walks forward. [free]"),
    ("A person walks forward. [free]", "stop and just stand there", "A person stands upright."),
    ("A person stands upright.", "sit down in the chair", "A person sits down. @3 >> A person sits in a chair."),
    ("A person sits in a chair.", "get up", "A person stands up from a chair. >> A person stands upright."),
    ("A person stands upright.", "dance for me", "A person dances. [free]"),
    ("A person stands upright.", "wave hello", "A person waves with their right hand. [free]"),
    ("A person stands upright.", "dance while jumping and touching different parts of your body", "A person dances. [free]"),
    ("A person dances. [free]", "dance for me", "KEEP"),
    ("A person stands upright.", "bend over and keep your palms on the ground",
     "A person bends over and puts their hands on the floor. @2 >> A person stands bent forward with their hands on the floor."),
    ("A person stands upright.", "throw a punch", "A person throws a punch with their right arm. @2 >> A person stands upright."),
    ("A person stands upright.", "take a sip of your drink", "A person drinks from a cup. @3 >> A person stands upright."),
    ("A person stands upright.", "kneel down", "A person kneels on one knee."),
    ("A person stands upright.", "hug yourself", "A person wraps their arms around themselves. @3 >> A person stands upright."),
    ("A person stands upright.", "do a handstand", "KEEP"),
    ("A person stands upright.", "look sad and cry", "KEEP"),
    ("A person stands upright.", "say hello", "KEEP"),
    ("A person stands upright.", "pick something up off the floor", "A person picks up an object from the floor. @3 >> A person stands upright."),
    ("A person stands upright.", "sit on the floor and relax",
     "A person sits down cross-legged on the floor. >> A person sits cross-legged with their hands resting on their knees."),
    ("A person stands upright.", "turn to face the other way", "A person turns around 180 degrees. >> A person stands upright."),
]


# --------------------------------------------------------------------------- cleaning + checking
_SUBJECT = re.compile(r"^(?:a|the)\s+(?:woman|girl|man|boy|lady|guy|female|male|character|avatar|figure)\b", re.I)
_POSSESSIVE = re.compile(r"\b(?:her|his|hers)\b", re.I)
_BANNED = re.compile(
    r"\b(?:woman|women|girl|man|men|boy|lady|guy|she|he|him|female|male|handstand|headstand|cartwheel|flip|"
    r"flips|somersault|upside|jump|jumps|jumping|bed|couch|sofa|table|desk|--\w+)\b",
    re.I,
)
_FREE = re.compile(r"\[\s*free\s*\]", re.I)
_AT = re.compile(r"\s*@\s*(\d+(?:\.\d+)?)\s*s?\s*$", re.I)
_CHARS = re.compile(r"^[A-Za-z0-9 ,.'\-@>\[\]]+$")
_ACTIVITY = re.compile(
    r"\b(?:dance|dances|dancing|walk|walks|walking|wave|waves|waving|jog|jogs|jogging|run|runs|running|clap|claps|"
    r"clapping|sway|sways|swaying|march|marches|marching|pace|paces|pacing|stretch|stretches|stretching)\b", re.I)
_STANDING_ACTIVITY = re.compile(
    r"\b(?:dance|dances|dancing|walk|walks|walking|jog|jogs|jogging|run|runs|running|march|marches|marching|"
    r"pace|paces|pacing)\b", re.I)
_SEATED = re.compile(r"\b(?:sits|sitting|seated|cross-legged)\b", re.I)
_GOES_DOWN = re.compile(r"\b(?:down|lowers|settles|squats|kneels)\b", re.I)
_GETS_UP = re.compile(r"\b(?:stands|up|rises|gets)\b", re.I)


def first_line(raw):
    for ln in (raw or "").splitlines():
        if ln.strip():
            return ln.strip()
    return ""


def repair(raw):
    """Fix the harmless things models do: quotes, labels, 'A woman', 'her'."""
    line = first_line((raw or "").replace("*", "").replace("_", " ")).strip("`\"' ")
    line = re.sub(r"^(?:output|answer|prompt|line)\s*:\s*", "", line, flags=re.I)
    if line.strip(" .!").upper() == "KEEP":
        return "KEEP"
    parts = [p.strip() for p in line.split(">>")]
    fixed = []
    for p in parts:
        p = _SUBJECT.sub("A person", p)
        p = _POSSESSIVE.sub("their", p)
        # ARDY prompts must not contain names ("slaps Todd playfully"): any capitalised word after the first is a proper noun
        p = re.sub(r"(?<=\s)[A-Z][a-z]+\b", "someone", p)
        fixed.append(" ".join(p.split()))
    return " >> ".join(x for x in fixed if x)


def validate(line, current=None):
    """(normalized_line, None) if acceptable, else (None, reason). `current` is what she is doing now."""
    if not line:
        return None, "the answer was empty"
    if line == "KEEP":
        return "KEEP", None
    if not _CHARS.match(line):
        return None, "it contains characters that are not allowed (letters, digits and , . ' - @ > [ ] only)"
    free = _FREE.search(line) is not None
    text = _FREE.sub("", line).strip()
    parts = [p.strip() for p in text.split(">>") if p.strip()]
    if not parts:
        return None, "the answer had no motion in it"
    if len(parts) > 4:
        return None, "it has more than 4 parts"
    out = []
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        seconds = None
        m = _AT.search(part)
        if m:
            if last:
                return None, "@N is only allowed after an action that is followed by '>>'"
            seconds = float(m.group(1))
            part = part[: m.start()].strip()
            if not 1 <= seconds <= 180:
                return None, "@N must be between 1 and 180 seconds"
        if not part.startswith("A person "):
            return None, f"'{part[:40]}' must start with 'A person'"
        if not part.endswith("."):
            return None, f"'{part[:40]}' must end with a full stop"
        if not 12 <= len(part) <= 140:
            return None, "each part must be between 12 and 140 characters"
        bad = _BANNED.search(part)
        if bad:
            return None, f"it uses '{bad.group(0)}', which must not appear (use 'A person', no unsafe poses)"
        out.append(part + (f" @{seconds:g}" if seconds is not None else ""))
    if free and not _ACTIVITY.search(parts[-1]):
        return None, ("[free] is only for an ongoing activity (dancing, walking, waving) as the LAST part, "
                      "not for a pose or a one-off action")
    plain = [_AT.sub("", p).strip() for p in parts]
    cur_final = _FREE.sub("", (current or "").split(">>")[-1])
    cur_seated = _SEATED.search(cur_final) is not None
    if cur_seated and _STANDING_ACTIVITY.search(plain[0]) and not _GETS_UP.search(plain[0]):
        return None, "she is sitting, so an activity on her feet must start with standing up (stands up from a chair >> ...)"
    for i, (a, b) in enumerate(zip(plain, plain[1:])):
        # if she is already seated, an action that isn't a stand-up (e.g. turning) leaves her seated
        a_seated = _SEATED.search(a) is not None or (i == 0 and cur_seated and not _GETS_UP.search(a))
        if _SEATED.search(b) and not a_seated and not _GOES_DOWN.search(a) and not _GOES_DOWN.search(b):
            return None, f"the held pose '{b[:40]}' does not follow from the action '{a[:40]}'"
        if re.search(r"\bstands\b", b, re.I) and a_seated and not _GETS_UP.search(a):
            return None, f"the held pose '{b[:40]}' does not follow from the action '{a[:40]}'"
        if _STANDING_ACTIVITY.search(b) and a_seated and not _GETS_UP.search(a):
            return None, f"'{b[:40]}' needs her on her feet, but '{a[:40]}' leaves her seated"
    return " >> ".join(out) + (" [free]" if free else ""), None


# --------------------------------------------------------------------------- talking to the LLM
def build_messages(request, current):
    msgs = [{"role": "system", "content": SYSTEM_PROMPT_FREE if FREEDOM else SYSTEM_PROMPT_STRICT}]
    for cur, req, ans in (EXAMPLES_FREE if FREEDOM else EXAMPLES_STRICT):
        msgs.append({"role": "user", "content": f"Currently: {cur}\nRequest: {req}"})
        msgs.append({"role": "assistant", "content": ans})
    msgs.append({"role": "user", "content": f"Currently: {current}\nRequest: {request}"})
    return msgs


def _headers(key):
    h = {"Content-Type": "application/json"}
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


def chat(base, model, messages, key=None, temperature=0.3, max_tokens=90, timeout=60):
    body = {"messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if model:
        body["model"] = model
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions", data=json.dumps(body).encode("utf-8"),
        headers=_headers(key), method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def autofix(line, current):
    """Repair the two posture slips models make, so a sensible answer isn't thrown away:
    a seated hold with no sit-down before it, and a standing hold with no get-up before it."""
    free = _FREE.search(line) is not None
    parts = [p.strip() for p in _FREE.sub("", line).split(">>") if p.strip()]
    if len(parts) != 2:
        return None
    a, b = parts
    a_plain = _AT.sub("", a).strip()
    cur_seated = _SEATED.search(_FREE.sub("", (current or "").split(">>")[-1])) is not None
    a_seated = _SEATED.search(a_plain) is not None or (cur_seated and not _GETS_UP.search(a_plain))
    tail = " [free]" if free else ""
    if _SEATED.search(b) and not a_seated and not _GOES_DOWN.search(a_plain):
        return "A person sits down. @3 >> " + b + tail
    if re.search(r"\bstands\b", b, re.I) and a_seated and not _GETS_UP.search(a_plain):
        return "A person stands up from a chair. >> " + b + tail
    return None


def propose(request, current, llm, attempts=3):
    """Ask the model; re-ask once with the reason if the answer is rejected. Returns (line, error)."""
    msgs = build_messages(request, current)
    err = None
    cur_norm, _ = validate(repair(current)) if current else (None, None)
    asked_same = False
    for _ in range(attempts):
        raw = llm(msgs)
        repaired = repair(raw)
        line, err = validate(repaired, current)
        if not line:
            fixed = autofix(repaired, current)
            if fixed:
                line, _ = validate(fixed, current)
        if line:
            if cur_norm and line == cur_norm and line != "KEEP":
                # the model just copied what she is already doing; make it look at the request again
                if not asked_same:
                    asked_same = True
                    msgs = msgs + [
                        {"role": "assistant", "content": raw},
                        {"role": "user", "content": f'That is exactly what she is doing right now. The request was: "{request}". '
                                                    "Reply with the motion that fulfils the request, or KEEP if she is already doing it."},
                    ]
                    continue
                return "KEEP", None
            return line, None
        msgs = msgs + [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": f"That was rejected because {err}. Answer again with ONE valid line only."},
        ]
    return None, err


# --------------------------------------------------------------------------- prompt file
def read_current(path):
    try:
        with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
            for ln in f:
                if ln.strip():
                    return ln.strip()
    except FileNotFoundError:
        pass
    return IDLE


def write_prompt_file(path, line):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(line + "\n", encoding="utf-8")
    err = None
    for _ in range(25):
        try:
            os.replace(tmp, path)
            return
        except PermissionError as e:  # the stream may be reading it right now
            err = e
            time.sleep(0.04)
    raise err


# --------------------------------------------------------------------------- commands
def explain_connection_error(e, base):
    print(f"Could not reach the LLM at {base}: {e}")
    print("Check: the IP and port are right; the program on the other PC is set to accept connections from the")
    print("network (not just 'localhost'); and Windows Firewall on that PC allows the port.")


def ping(base, model, key):
    try:
        req = urllib.request.Request(base.rstrip("/") + "/models", headers=_headers(key))
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        names = [m.get("id", "?") for m in data.get("data", [])]
        print("Connected. Models reported:", ", ".join(names) if names else "(none listed)")
    except (urllib.error.URLError, OSError, ValueError) as e:
        explain_connection_error(e, base)
        return 1
    try:
        t0 = time.time()
        out = chat(base, model, [{"role": "user", "content": "Reply with the single word: OK"}], key=key, max_tokens=8)
        print(f"Chat works ({time.time() - t0:.1f}s). The model said: {out.strip()!r}")
    except Exception as e:
        print("The connection works but a chat request failed:", e)
        print("If it needs a model name, add --model <name> (use one of the names listed above).")
        return 1
    return 0


def selftest():
    cases = [
        ("A person stands upright.", True),
        ("A person stands up from a chair. >> A person stands upright.", True),
        ("A person sits down. @3 >> A person sits in a chair.", True),
        ("A person dances. [free]", True),
        ("A woman sits down. @3 >> A woman sits in her chair.", True),   # repaired
        ('"A person waves with their right hand. [free]"', True),
        ("Output: A person walks forward. [free]", True),
        ("A person does a handstand.", False),
        ("A person jumps up and down.", False),
        ("A person lies down on a bed.", False),
        ("KEEP", True),
        ("keep.", True),
        ("A person stands upright. [free]", False),
        ("A person bends over and touches their toes. [free]", False),
        ("A person turns around slowly. >> A person sits cross-legged with their hands resting on their knees.", False),
        ("A person sits down. >> A person stands upright.", False),
        ("A person turns around 180 degrees. >> A person stands upright.", True),
        ("A person stands up from a chair. >> A person stands upright.", True),
        ("A person sits down cross-legged on the floor. >> A person sits cross-legged with their hands resting on their knees.", True),
        ("A person sits in a chair.", True),
        ("She sits down.", False),
        ("A person sits. >> A person stands. >> A person sits. >> A person stands.", False),
        ("A person sits down. @300 >> A person sits.", False),
        ("A person stands upright. --hold-settle 0", False),
        ("A person waves. >> A person dances. [free]", True),
        ("A person stands up from a chair. >> A person stands upright. [free]", False),
        ("A person stands up from a chair. >> A person dances. [free]", True),
        ("A person sits down. >> A person dances. [free]", False),
        ("", False),
    ]
    bad = 0
    SEATED_NOW = "A person sits cross-legged with their hands resting on their knees."
    cases += [
        ("A person turns around slowly. >> A person sits down cross-legged on the floor.", True, SEATED_NOW),
        ("A person turns around slowly. >> A person sits down cross-legged on the floor.", True, "A person stands upright."),
        ("A person turns around slowly. >> A person sits cross-legged with their hands resting on their knees.", False, "A person stands upright."),
        ("A person turns around slowly. >> A person stands upright.", False, SEATED_NOW),
        ("A person stands up from the floor. >> A person stands upright.", True, SEATED_NOW),
        ("A person dances. [free]", False, "A person sits down."),
        ("A person stands up from a chair. >> A person dances. [free]", True, "A person sits down."),
        ("A person dances. [free]", True, "A person stands upright."),
        ("A person walks forward. [free]", False, SEATED_NOW),
    ]
    DANCING = "A person dances. [free]"
    cases += [
        ("A person stops dancing. >> A person sits in a chair.", False, DANCING),   # as written: rejected ...
    ]
    STAND_, CHAIR_ = "A person stands upright.", "A person sits down. @3 >> A person sits in a chair."
    FLOOR_ = "A person sits cross-legged with their hands resting on their knees."
    lifetime_cases = [
        ("A person wiggles their hips playfully.", STAND_, "tease playfully",
         "A person wiggles their hips playfully. @4 >> A person stands upright."),
        ("A person claps their hands.", STAND_, "clap", "A person claps their hands. @4 >> A person stands upright."),
        ("A person dances.", STAND_, "dance", "A person dances. @60 >> A person stands upright."),
        ("A person stands with their legs wide apart.", STAND_, "pose", "A person stands with their legs wide apart."),
        ("A person sits in a chair.", CHAIR_, "sit", "A person sits in a chair."),
        ("A person is bent over at the waist, touching their toes.", STAND_, "pose",
         "A person is bent over at the waist, touching their toes."),
        ("A person is walking forward.", STAND_, "walk", "A person is walking forward. @10 >> A person stands upright."),
        ("A person stands up from a chair. >> A person walks forward.", CHAIR_, "walk",
         "A person stands up from a chair. >> A person walks forward. @10 >> A person sits down. @3 >> A person sits in a chair."),
        ("A person turns around 180 degrees.", STAND_, "turn", "A person turns around 180 degrees. @4 >> A person stands upright."),
        ("A person stands and waves.", STAND_, "wave", "A person stands and waves. @4 >> A person stands upright."),
        ("A person stands with their arms raised overhead.", STAND_, "pose", "A person stands with their arms raised overhead."),
        ("A person sits cross-legged with their hands resting on their knees.", STAND_, "pose",
         "A person sits cross-legged with their hands resting on their knees."),
        ("A person squats down.", STAND_, "pose", "A person squats down."),
        ("A person dances. [free]", STAND_, "keep dancing for a long time", "A person dances. @120 >> A person stands upright."),
        ("A person waves with their right hand. [free]", STAND_, "wave",
         "A person waves with their right hand. @4 >> A person stands upright."),
        ("A person dances. [free]", STAND_, "dance", "A person dances. @60 >> A person stands upright."),
        ("A person dances. [free]", STAND_, "keep dancing", "A person dances. @120 >> A person stands upright."),
        ("A person walks forward. [free]", STAND_, "walk", "A person walks forward. @10 >> A person stands upright."),
        ("A person waves with their right hand. [free]", CHAIR_, "wave",
         "A person waves with their right hand. @4 >> A person sits in a chair."),
        ("A person stands up from a chair. >> A person dances. [free]", CHAIR_, "dance",
         "A person stands up from a chair. >> A person dances. @60 >> A person sits down. @3 >> A person sits in a chair."),
        ("A person waves with their right hand. [free]", FLOOR_, "wave",
         "A person waves with their right hand. @4 >> " + FLOOR_),
        ("A person dances. [free]", "A person waves with their right hand. @4 >> A person stands upright.", "dance",
         "A person dances. @60 >> A person stands upright."),
        ("A person dances. [free]", "A person dances. [free]", "dance", "A person dances. @60 >> A person stands upright."),
        ("A person stands upright.", STAND_, "stand", "A person stands upright."),
        ("A person walks forward. @2 >> A person stands upright.", STAND_, "steps",
         "A person walks forward. @2 >> A person stands upright."),
    ]
    SP = "A person dances slowly and sensually, swaying their hips."
    fb_cases = [
        (f"{SP} @60 >> A person stands upright.", f"{SP} ?? A person dances. @60 >> A person stands upright."),
        ("A person dances. @60 >> A person stands upright.", "A person dances. @60 >> A person stands upright."),
        (f"A person stands up from a chair. >> {SP} @60 >> A person sits down. @3 >> A person sits in a chair.",
         f"A person stands up from a chair. >> {SP} ?? A person dances. @60 >> A person sits down. @3 >> A person sits in a chair."),
        ("A person waves with their right hand. @4 >> A person stands upright.", "A person waves with their right hand. @4 >> A person stands upright."),
    ]
    scrubbed, _ = validate(repair("A person slaps Todd playfully with their right hand. @2 >> A person stands upright."), "A person stands upright.")
    ok = scrubbed is not None and "Todd" not in scrubbed and "someone" in scrubbed
    print(("ok  " if ok else "BAD ") + "names are scrubbed from prompts -> " + str(scrubbed))
    bad += (not ok)
    STAND0 = "A person stands upright."
    fast_cases = [
        ("keep my legs spread wide, bend over, and touch the ground",
         "A person bends over and puts their hands on the floor with their legs wide apart. @2 >> "
         "A person stands with their legs wide apart, bent over with their hands on the floor."),
        ("keep your legs spread wide, bend over and touch your toes",
         "A person bends over with their legs wide apart. @2 >> A person is bent over at the waist with their legs wide apart."),
        ("stand with your legs spread wide apart", "A person stands with their legs wide apart."),
        ("stand with your legs wide apart", "A person stands with their legs wide apart."),
        ("bend over all the way", "A person bends over and touches their toes. >> A person stands upright."),
        ("bend over and touch the ground",
         "A person bends over and puts their hands on the floor. @2 >> A person stands bent forward with their hands on the floor."),
        ("now bend over and keep your palms on the ground between your legs",
         "A person bends over and puts their hands on the floor. @2 >> A person stands bent forward with their hands on the floor."),
        ("walk with your legs wide apart", None),                    # pose + another action: the LLM composes it
        ("legs wide apart and hands on your hips", None),            # two poses: the LLM composes it
        ("bend over with your legs apart", "A person bends over with their legs wide apart. @2 >> "
                                           "A person is bent over at the waist with their legs wide apart."),
        ("say hello", "KEEP"),
        ("a chair (close, ahead-left)", "KEEP"),
        ("a chair close by, in front and to the left. it can be sat on.", "KEEP"),
        ("a table within reach, to the right. it is a flat surface.", "KEEP"),
        ("a table (within reach, ahead-right, a surface)", "KEEP"),
        ("there is a chair within reach, in front and to the left", "KEEP"),
        ("turn around", "A person turns around 180 degrees. >> A person stands upright."),
    ]
    for req_, want in fast_cases:
        got = fast_path(req_, STAND0)
        flag = "ok " if got == want else "BAD"
        bad += got != want
        print(f"{flag} fast path {req_!r:62} -> {got}")
    for line_, want in fb_cases:
        got = attach_fallbacks(line_)
        flag = "ok " if got == want else "BAD"
        bad += got != want
        back = strip_fallbacks(got)
        if back.replace("  ", " ") != line_.replace("  ", " "):
            flag, bad = "BAD", bad + 1
        print(f"{flag} fallback round trip: {got[:110]}")
    for line_, cur_, req_, want in lifetime_cases:
        got = apply_lifetime(line_, cur_, req_)
        flag = "ok " if got == want else "BAD"
        bad += got != want
        print(f"{flag} lifetime {req_!r:14} from {cur_[:34]!r:36} -> {got}")
    for case in cases:
        raw, expect_ok = case[0], case[1]
        cur = case[2] if len(case) > 2 else None
        line, err = validate(repair(raw), cur)
        ok = line is not None
        flag = "ok " if ok == expect_ok else "BAD"
        bad += ok != expect_ok
        print(f"{flag} {raw!r:76} -> {line!r}" if ok else f"{flag} {raw!r:76} -> rejected: {err}")
    print("selftest:", "all good" if not bad else f"{bad} unexpected result(s)")
    return 1 if bad else 0


# --------------------------------------------------------------------------- lifetimes (common sense)
# Gestures are short and then she goes back to what she was doing; activities run for a while and then end,
# unless the user says "keep going". Anything tagged [free] gets a duration and a return pose here.
_GESTURE = re.compile(
    r"\b(?:wave|waves|waving|clap|claps|clapping|nod|nods|nodding|shake|shakes|shaking|point|points|pointing|"
    r"salute|salutes|bow|bows|shrug|shrugs|stretch|stretches|stretching|beckon|beckons)\b", re.I)
_LIFETIMES = [("danc", 60), ("walk", 10), ("stroll", 10), ("jog", 12), ("march", 10), ("pac", 10), ("sway", 20)]
_KEEP_GOING = re.compile(r"\b(?:keep|continue|carry on|more|again|longer|forever)\b", re.I)
# Style words the fast path can carry into the prompt instead of throwing away ("do a sexy dance" otherwise becomes
# a plain "A person dances."). First match wins. OFF by default: these wordings are untested against ARDY (the
# first one produced a frozen pose, 0.01 m/s, instead of a dance). Launch with --styles to experiment; every styled
# dance carries the plain prompt as a fallback, and the stream switches to it if the styled one produces no movement.
STYLES_ON = False
# (words in the request, lab group key, experimental wording). The wording only matters with --styles; a wording the
# motion lab verified (verified_prompts.json, key e.g. "dance.sexy") is always used instead of it.
DANCE_STYLES = [
    (re.compile(r"\bbelly[\s-]*danc\w*", re.I), "dance.belly", "A person belly dances."),
    (re.compile(r"\bsalsa\b", re.I), "dance.salsa", "A person dances salsa."),
    (re.compile(r"\bhip[\s-]*hop\b", re.I), "dance.hiphop", "A person dances hip hop."),
    (re.compile(r"\bdisco\b", re.I), "dance.disco", "A person dances disco."),
    (re.compile(r"\b(?:waltz\w*|ballroom)\b", re.I), "dance.waltz", "A person dances a waltz."),
    (re.compile(r"\bballet\b", re.I), "dance.ballet", "A person dances ballet."),
    (re.compile(r"\b(?:sexy|sensual|sensually|seductive|seductively|provocative|provocatively|flirty|erotic)\b", re.I),
     "dance.sexy", "A person dances slowly and sensually, swaying their hips."),
    (re.compile(r"\bslow(?:ly)?\b", re.I), "dance.slow", "A person dances slowly."),
    (re.compile(r"\b(?:energetic|energetically|fast|wild|wildly|lively|upbeat|crazy|enthusiastic)\b", re.I),
     "dance.energetic", "A person dances energetically."),
    (re.compile(r"\b(?:playful|playfully|silly|goofy|fun)\b", re.I), "dance.playful", "A person dances playfully."),
    (re.compile(r"\b(?:graceful|gracefully|elegant|elegantly|gentle|gently|smooth|smoothly|calm)\b", re.I),
     "dance.graceful", "A person dances gracefully."),
]
VERIFIED = {}   # filled from verified_prompts.json (written by ardy_lab.py)
VERIFIED_FILE = Path(__file__).resolve().with_name("verified_prompts.json")


def load_verified(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return {k: v.strip() for k, v in data.items() if isinstance(v, str) and v.strip() and not k.startswith("_")}


def load_verified_settings(path):
    """The stream settings the wordings were verified under (recorded by ardy_lab.py), or ''."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return str(json.load(f).get("_settings", ""))
    except (OSError, ValueError, AttributeError):
        return ""


# Held poses (not motions). Matched before the generic stand/sit/bend handling so that "stand with your legs wider apart" is no
# longer flattened into a plain "A person stands upright." A wording verified with `ardy_lab.py --suite poses` is used as the
# held state; without one the request goes to the LLM instead of being silently dropped.
# Defaults used when nothing is verified yet (the lab's first candidate for each pose). They are attempts, not promises.
POSE_DEFAULTS = {
    "pose.wide": "A person stands with their legs wide apart.",
    "pose.hands_hips": "A person stands with their hands on their hips.",
    "pose.arms_crossed": "A person stands with their arms crossed.",
    "pose.splits": "A person sits on the floor in the splits position.",
    "pose.bend": "A person is bent over at the waist, touching their toes.",
    "pose.bend_floor": "A person stands bent forward with their hands on the floor.",
    "pose.wide_bend": "A person is bent over at the waist with their legs wide apart.",
    "pose.wide_bend_floor": "A person stands with their legs wide apart, bent over with their hands on the floor.",
}
_HANDS_FLOOR = re.compile(r"\b(?:palms?|hands?|fingers?)\b.*\b(?:ground|floor)\b|\b(?:ground|floor)\b.*\b(?:palms?|hands?)\b|"
                          r"\btouch\w*\s+(?:the\s+|your\s+)?(?:ground|floor)\b", re.I)
POSE_REQUESTS = [
    (re.compile(r"\bwide(?:r)?\s+stance|\bstand\s+wider|\b(?:legs?|feet)\b[^.,;]*\b(?:apart|wide|wider|spread|farther|further)\b|"
                r"\bspread\w*\b[^.,;]*\b(?:legs|feet)\b", re.I), "pose.wide"),
    (re.compile(r"\bhands?\s+on\s+(?:your\s+|her\s+|their\s+)?hips", re.I), "pose.hands_hips"),
    (re.compile(r"\b(?:cross(?:ed)?|fold(?:ed)?)\s+(?:your\s+|her\s+|their\s+)?arms|\barms\s+(?:crossed|folded)", re.I),
     "pose.arms_crossed"),
    (re.compile(r"\bsplits\b", re.I), "pose.splits"),
    (re.compile(r"\bbend\w*\b.*\b(?:hold|stay|keep|palms?|hands?|ground|floor)\b|\b(?:hold|stay|keep|remain)\b.*\bbent\b|"
                r"\b(?:ground|floor)\b.*\bbend\w*\b", re.I), "pose.bend"),
]


def _styled_dance_phrases():
    phrases = {ph for _, _, ph in DANCE_STYLES}
    phrases |= {v for k, v in VERIFIED.items() if k.startswith("dance.")}
    phrases.discard("A person dances.")
    return phrases


GESTURE_SECONDS = 4
DEFAULT_SECONDS = 12


def base_pose(current):
    """The pose to go back to: the held pose at the end of what she is doing now (default: standing)."""
    cur = (current or "").strip()
    if not cur or _FREE.search(cur):
        return IDLE
    last = _AT.sub("", cur.split(">>")[-1]).strip()
    if _ACTIVITY.search(last):
        return IDLE
    if re.search(r"\bcross-legged\b", last, re.I) or (_SEATED.search(last) and re.search(r"\bfloor\b", last, re.I)):
        return last if last.endswith(".") else last + "."
    if _SEATED.search(last):
        return "A person sits in a chair."
    return IDLE


def _return_parts(base, ends_standing):
    if not ends_standing or not _SEATED.search(base):
        return [base]
    if re.search(r"cross-legged", base, re.I):
        return ["A person sits down cross-legged on the floor. @3", base]
    return ["A person sits down. @3", "A person sits in a chair."]


def attach_fallbacks(line):
    """'STYLED @60 >> HOLD' -> 'STYLED ?? PLAIN @60 >> HOLD' for the styled dances we know a plain version of."""
    free = _FREE.search(line) is not None
    parts, changed = [], False
    for part in _FREE.sub("", line).split(">>"):
        part = part.strip()
        m = _AT.search(part)
        core, at = (part[:m.start()].strip(), part[m.start():]) if m else (part, "")
        fb = "A person dances." if core in _styled_dance_phrases() else None
        if fb:
            part, changed = f"{core} ?? {fb}{at}", True
        parts.append(part)
    return " >> ".join(parts) + (" [free]" if free else "") if changed else line


def strip_fallbacks(line):
    """Remove the ' ?? plain prompt' parts again (the prompter itself never needs them)."""
    out = []
    for part in (line or "").split(">>"):
        if "??" in part:
            head, _, tail = part.partition("??")
            m = _AT.search(tail)
            part = head.rstrip() + (tail[m.start():] if m else "")
        out.append(part)
    return ">>".join(out)


# --------------------------------------------------------------------------- durations: nothing may run forever
# The LAST part of a plan is open-ended ("hold until changed"). It must be a pose that settles. If it is a movement it would
# run until someone interrupts it, so here every final movement gets a lifetime and a return to what she was doing.
MAX_PART_SECONDS = 180   # the longest any one movement may last (the validator accepts 1-180 s)
# a line that describes a pose: "A person stands with their legs wide apart."
_STATE_START = re.compile(r"^A person (?:stands|sits|kneels|squats|crouches|lies|leans|is|holds|rests|waits|stays|remains|has)\b", re.I)
# verbs that mean she is MOVING even when the line starts like a pose: "A person is walking forward."
_MOVING = re.compile(
    r"\b(?:walk|run|jog|march|step|stride|shuffle|pace|danc|wiggl|sway|shak|bounc|hop|jump|skip|spin|turn|kick|punch|clap|wav|"
    r"stretch|crawl|climb|swim|rock|nod|jiggl|twirl|swing|stomp|flap|scratch|wipe|brush|throw|slap|bow|salute|shrug|beckon)\w*", re.I)


def _is_movement(text):
    """True if the line describes something she DOES (it ends or repeats) and not a pose she HOLDS. Unknown verbs count as
    movements, because wrongly ending a pose is harmless and wrongly holding a movement is not."""
    t = (text or "").strip()
    if _STATE_START.match(t) and not (_MOVING.search(t) or _ACTIVITY.search(t) or _GESTURE.search(t)):
        return False
    return True


def apply_lifetime(line, current, request=""):
    """Give the final movement of a plan a lifetime and a way back.
    'A person waves. [free]'                       -> 'A person waves. @4 >> <what she was doing>'
    'A person wiggles their hips playfully.'       -> '... @4 >> <what she was doing>'   (a reaction, not an activity)
    'A person stands up. >> A person walks forward.' -> '... >> A person walks forward. @10 >> <what she was doing>'
    Dances, walks and the like keep their longer lifetimes; the lengths are in _LIFETIMES. A final pose is left alone."""
    if not line or line == "KEEP":
        return line
    free = _FREE.search(line) is not None
    parts = [p.strip() for p in _FREE.sub("", line).split(">>") if p.strip()]
    if not parts:
        return line
    last = _AT.sub("", parts[-1]).strip()
    if not free and not _is_movement(last):
        return line                      # the final part is a pose: it settles by itself
    activity = free or _ACTIVITY.search(last) is not None
    if _GESTURE.search(last):
        secs = GESTURE_SECONDS
    else:
        secs = next((d for kw, d in _LIFETIMES if re.search(r"\b" + kw, last, re.I)),
                    DEFAULT_SECONDS if activity else GESTURE_SECONDS)
    if _KEEP_GOING.search(request or ""):
        secs *= 2
    secs = int(max(1, min(secs, MAX_PART_SECONDS)))
    cur_seated = _SEATED.search(_FREE.sub("", (current or "").split(">>")[-1])) is not None
    ends_standing = (not cur_seated) or any(_GETS_UP.search(p) for p in parts[:-1])
    new_parts = parts[:-1] + [f"{last} @{secs}"] + _return_parts(base_pose(current), ends_standing)
    new = " >> ".join(new_parts)
    checked, _ = validate(new, current)
    return checked if checked else line


# --------------------------------------------------------------------------- fast path (no LLM call)
_INTENTS = [
    ("sit_floor", re.compile(r"\bcross[- ]?legged\b|\bsit(?:s|ting)?\b.*\b(?:floor|ground)\b|\b(?:floor|ground)\b.*\bsit(?:s|ting)?\b", re.I)),
    ("sit", re.compile(r"\bsit(?:s|ting)?\b|\b(?:take|have) a seat\b", re.I)),
    ("stand", re.compile(r"\bstand(?:s|ing)?\b|\bget up\b|\brise\b|\bstay (?:still|put)\b|\bhold still\b|\bfreeze\b|\bstop\b", re.I)),
    ("dance", re.compile(r"\bdanc(?:e|es|ing)\b|\bbelly[\s-]*danc\w*|\bsalsa\b|\bwaltz\w*|\bballroom\b|"
                         r"\bhip[\s-]*hop\b|\bdisco\b|\bballet\b", re.I)),
    ("walk", re.compile(r"\bwalk(?:s|ing)?\b|\bstroll(?:s|ing)?\b|\bsteps?\b", re.I)),
    ("wave", re.compile(r"\bwav(?:e|es|ing)\b", re.I)),
    ("turn", re.compile(r"\b(?:turn|spin)(?:s|ning)?\s+around\b|\bface the other way\b", re.I)),
]
# things the motion model cannot do: with no supported intent in the request, answer KEEP without asking the LLM
_DECLINE = re.compile(
    r"\b(?:jump\w*|hop\w*|clap\w*|flap\w*|nod\w*|smil\w*|frown\w*|laugh\w*|cry\w*|wink\w*|blink\w*|hug\w*|kiss\w*|"
    r"spank\w*|handstand|headstand|cartwheel|flip\w*|somersault|look\w*|glanc\w*|stare\w*|tilt\w*|shak\w*)\b", re.I)
# freedom mode declines only what is not a body movement (voice, face, eyes); everything physical is attempted
_DECLINE_FREE = re.compile(
    r"\b(?:say|says|saying|speak\w*|talk\w*|tell\w*|greet\w*|hello|hi|introduc\w*|whisper\w*|sing\w*|smil\w*|frown\w*|"
    r"laugh\w*|cry\w*|wink\w*|blink\w*|look\w*|glanc\w*|stare\w*)\b", re.I)
# anything that makes the fast path untrustworthy when combined with an intent ("stand on one foot")
_BLOCKERS = re.compile(
    _DECLINE.pattern[:-3] + r"|touch\w*|squeez\w*|lift\w*|rais\w*|foot|feet|legs?|toes?|tiptoe\w*|balanc\w*|"
    r"lie|lying|lay|bed|couch|sofa|backward\w*|sideways|back up|don't|do not|not|never)\b", re.I)
_BEND_RX = re.compile(r"\bbend(?:s|ing)?\s+(?:over|forward|down)\b|\btouch\w*\s+(?:your\s+|their\s+|the\s+)?toes\b", re.I)
_BEND_BLOCK = re.compile(
    r"\b(?:table|desk|counter|wall|chair|bed|couch|sofa|pick\w*|grab\w*|lift\w*|rais\w*|reach\w*|something|object|"
    r"legs?|feet|foot|spread\w*|apart|wide|ground|floor|palms?|hands?|keep|hold|stay|remain|"
    r"jump\w*|hop\w*|clap\w*|hug\w*|kiss\w*|spank\w*|squeez\w*|knees?|slow\w*|fast|quick\w*|don't|do not|not|never)\b", re.I)
_STOPWORDS = re.compile(r"\b(?:stop|quit|enough|cease)\b", re.I)


_NUMWORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
             "eight": 8, "nine": 9, "ten": 10}
_WALK_RX = re.compile(r"\bwalk(?:s|ing)?\b|\bstroll(?:s|ing)?\b|\bsteps?\b", re.I)
# walking requests with a direction or manner the fast path cannot express: let the LLM write them
_WALK_QUAL = re.compile(
    r"\b(?:circles?|around|left|right|back\w*|sideways?|slow\w*|fast|quick\w*|run\w*|jog\w*|toward\w*|"
    r"to the|over to|across|up|in place)\b", re.I)
_STOP_RX = re.compile(r"\b(?:stop|halt|freeze|stand still|hold still)\b", re.I)


def _step_count(t):
    """How many steps were asked for ('take three steps' -> 3), or None."""
    m = re.search(r"\b(\d+|an?|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:big |small |slow |quick |short |long )?steps?\b", t)
    if m:
        v = m.group(1)
        return int(v) if v.isdigit() else _NUMWORDS[v]
    if re.search(r"\bsteps\b", t):
        return 3
    if re.search(r"\bstep\b", t):
        return 1
    return None


def posture(current):
    last = _FREE.sub("", (current or "").split(">>")[-1])
    if re.search(r"\bcross-legged\b", last, re.I) or (_SEATED.search(last) and re.search(r"\bfloor\b", last, re.I)):
        return "floor"
    if _SEATED.search(last):
        return "chair"
    return "standing"


_SCENE_NOTE = re.compile(
    r"\((?:[^)]*\b(?:ahead|behind|within reach|touching distance|m away|can be sat on|a surface|worth looking at)\b)|"
    r"\bwhat .{0,40} is aware of\b|\bphysical situation of\b|\bthere is an? .{1,40}\b(?:within reach|close by|m away)\b|"
    r"\b(?:close by|within reach|about \d+ m away|right beside \w+),? (?:directly|in front|behind|to the (?:left|right))|"
    r"\bit can be sat on\b|\bit is a flat surface\b|\bit is worth looking at\b", re.I)


def fast_path(request, current):
    """A validated prompt line (or "KEEP") for obvious requests, or None to ask the LLM."""
    t = " ".join((request or "").lower().replace("'", "'").split())
    if not t:
        return None
    # The Senses plugin's scene description sometimes gets mistaken for a request by the action model
    # ("a chair (close, ahead-left)" made her sit down). Those are never movements.
    if _SCENE_NOTE.search(t):
        return "KEEP"
    intents = {name for name, rx in _INTENTS if rx.search(t)}
    hits = [key for rx, key in POSE_REQUESTS if rx.search(t)]
    if hits:
        # a pose plus another action ("walk with your legs wide apart") or several poses at once: a fast answer
        # would silently drop part of it, so let the LLM compose them
        if posture(current) != "standing" or intents - {"stand"}:
            return None
        wide_bend = "pose.wide" in hits and ("pose.bend" in hits or _BEND_RX.search(t))
        if wide_bend and set(hits) <= {"pose.wide", "pose.bend"}:
            floor = _HANDS_FLOOR.search(t) is not None
            hold_key = "pose.wide_bend_floor" if floor else "pose.wide_bend"
            hold = VERIFIED.get(hold_key) or POSE_DEFAULTS[hold_key]
            move = ("A person bends over and puts their hands on the floor with their legs wide apart." if floor
                    else "A person bends over with their legs wide apart.")
            line = f"{move} @2 >> {hold}"
        elif len(hits) > 1:
            return None
        elif hits[0] == "pose.bend":   # a bend you can hold: do the bend, then hold the bent pose as the final state
            floor = _HANDS_FLOOR.search(t) is not None
            hold = VERIFIED.get("pose.bend_floor" if floor else "pose.bend") or POSE_DEFAULTS["pose.bend_floor" if floor else "pose.bend"]
            move = ("A person bends over and puts their hands on the floor." if floor
                    else "A person bends over and touches their toes.")
            line = f"{move} @2 >> {hold}"
        else:
            line = VERIFIED.get(hits[0]) or (POSE_DEFAULTS.get(hits[0]) if FREEDOM else None)
            if line is None:
                return None
        checked, _ = validate(line, current)
        if checked is None:
            return None
        if _AT.sub("", checked.split(">>")[-1]).strip() == _AT.sub("", (current or "").split(">>")[-1]).strip():
            return "KEEP"   # she is already holding that pose
        return checked
    if "sit_floor" in intents:
        intents.discard("sit")
    # "bend over and touch your toes": a verified motion (touch/toes would otherwise count as blockers)
    if _BEND_RX.search(t) and not intents and not _BEND_BLOCK.search(t):
        if posture(current) != "standing":
            return None
        checked, _ = validate("A person bends over and touches their toes. >> A person stands upright.", current)
        return checked
    if _BEND_RX.search(t) and intents:  # a bend plus another action: let the LLM order them
        return None
    # "take three steps forward and stop" / "walk forward and stop": a short walk, then standing
    steps = _step_count(t)
    bounded = False
    if "walk" in intents and intents <= {"walk", "stand"}:
        walk_at = _WALK_RX.search(t).start()
        stops = [m.start() for m in _STOP_RX.finditer(t)]
        if steps is not None or (stops and max(stops) > walk_at):
            intents = {"walk"}
            bounded = True
    if bounded:
        pass
    elif _STOPWORDS.search(t):
        if intents <= {"dance", "walk", "wave", "stand"}:
            intents = {"stand"}
        else:  # "stop dancing and sit down": the stop applies to the activity; the target is what is left
            intents -= {"dance", "walk", "wave", "stand"}
    if not intents:
        return "KEEP" if (_DECLINE_FREE if FREEDOM else _DECLINE).search(t) else None
    if len(intents) != 1 or _BLOCKERS.search(t):
        return None
    intent = next(iter(intents))
    if intent == "walk" and _WALK_QUAL.search(t):
        return None
    where = posture(current)
    up = {"chair": "A person stands up from a chair.", "floor": "A person stands up.", "standing": None}[where]

    def standing_first(activity):
        return f"{up} >> {activity}" if up else activity

    if intent == "stand":
        line = f"{up} >> A person stands upright." if up else "A person stands upright."
    elif intent == "sit":
        line = "KEEP" if where != "standing" else "A person sits down. @3 >> A person sits in a chair."
    elif intent == "sit_floor":
        if where == "floor":
            line = "KEEP"
        elif where == "chair":
            return None
        else:
            line = ("A person sits down cross-legged on the floor. >> "
                    "A person sits cross-legged with their hands resting on their knees.")
    elif intent == "dance":
        phrase = "A person dances."
        for rx, key, experimental in DANCE_STYLES:
            if rx.search(t):
                phrase = VERIFIED.get(key) or (experimental if STYLES_ON else "A person dances.")
                break
        line = standing_first(phrase + " [free]")
    elif intent == "walk":
        if bounded:
            secs = 4 if steps is None else max(2, min(8, round(steps * 0.6)))
            line = standing_first(f"A person walks forward. @{secs} >> A person stands upright.")
        else:
            line = standing_first("A person walks forward. [free]")
    elif intent == "wave":
        line = "A person waves with their right hand. [free]"
    elif intent == "turn":
        if where != "standing":
            return None
        line = "A person turns around 180 degrees. >> A person stands upright."
    else:
        return None
    if line == "KEEP":
        return "KEEP"
    checked, _ = validate(line, current)
    return checked  # None (-> ask the LLM) if it somehow fails the same rules the LLM answers must pass


BENCH = [
    "walk over to the window", "stop and stand still", "sit down in the chair", "get back up", "dance for me",
    "wave hello", "do a handstand", "sit on the floor and relax", "look shy and hug yourself",
    "turn around slowly", "bend over and pick something up", "jump up and down with joy",
    "lie down on the bed", "stretch like you just woke up",
    "dance rhythmically by jumping up and down while waving arms and touching different parts of your body",
    "slowly sit down on the edge of the bed and look at the user",
    "walk around the room while looking at the user and smiling",
]


def bench(base, args, key):
    """Run a fixed set of varied requests (nothing is written) and report how the model does."""
    current = IDLE
    ok_n = first_try = 0
    for req in BENCH:
        calls = {"n": 0}

        def llm(msgs):
            calls["n"] += 1
            return chat(base, args.model, msgs, key=key, temperature=args.temperature)

        t0 = time.time()
        try:
            line, err = propose(req, current, llm)
        except (urllib.error.URLError, OSError) as e:
            explain_connection_error(e, base)
            return 1
        dt = time.time() - t0
        print(f"{req!r}\n   -> {line if line else 'REJECTED: ' + str(err)}   [{dt:.1f}s, {calls['n']} call(s)]")
        if line:
            ok_n += 1
            first_try += calls["n"] == 1
            if line != "KEEP":
                current = line
    print(f"\n{ok_n}/{len(BENCH)} produced a valid line; {first_try} of those on the first try.")
    return 0


def _signature(path):
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def read_request(path):
    """Text of the newest request: {"request": "..."} as written by the VaM plugin, or a plain text file."""
    for _ in range(6):
        try:
            raw = Path(path).read_text(encoding="utf-8-sig", errors="ignore").strip()
        except OSError:
            time.sleep(0.05)
            continue
        if not raw:
            time.sleep(0.05)
            continue
        try:
            data = json.loads(raw)
            return str(data.get("request", "")).strip() if isinstance(data, dict) else str(data).strip()
        except ValueError:
            return raw  # plain text
    return ""


def watch(args, base, key):
    """Turn every request that appears in the request file into a prompt line."""
    path = args.watch
    last = _signature(path)  # whatever is already there is old; only act on new writes
    print(f"Watching {path}")
    print(f"Prompts go to {args.prompt_file}. Ctrl+C to stop.")
    while True:
        try:
            time.sleep(0.2)
            sig = _signature(path)
            if sig is None or sig == last:
                continue
            last = sig
            text = read_request(path)
            if not text:
                continue
            print(f"request: {text!r}")
            t0 = time.time()
            run_request(text, args, base, key)
            print(f"  ({time.time() - t0:.1f}s)")
        except KeyboardInterrupt:
            break


def run_request(request, args, base, key):
    current = strip_fallbacks(read_current(args.prompt_file))
    tidy, _ = validate(repair(current))
    shown = tidy if tidy and tidy != "KEEP" else current
    llm = lambda msgs: chat(base, args.model, msgs, key=key, temperature=args.temperature)
    line, err = None, None
    if not args.no_fast:
        line = fast_path(request, shown)
        if line is not None:
            print("  (fast path: no LLM call)")
    if line is None:
        try:
            line, err = propose(request, shown, llm)
        except (urllib.error.URLError, OSError) as e:
            explain_connection_error(e, base)
            return False
    if not line:
        print(f"  rejected twice ({err}); leaving the prompt as it is: {current}")
        return False
    if line == "KEEP":
        print("  no change (nothing in that request is something the motion model does reliably, "
              "or she is already doing it)")
        return True
    if not args.no_lifetime:
        timed = apply_lifetime(line, shown, request)
        if timed != line:
            print(f"  (timed: {line}  ->  it ends and she goes back)")
            line = timed
    line = attach_fallbacks(line)
    print(f"  {line}")
    if not args.dry_run:
        write_prompt_file(args.prompt_file, line)
    return True


def main():
    p = argparse.ArgumentParser(description="LLM -> ARDY prompt line")
    p.add_argument("request", nargs="*", help="What the character should do, in plain words")
    p.add_argument("--url", default=os.environ.get("MOTION_LLM_URL"),
                   help="OpenAI-compatible base URL, e.g. http://192.168.1.50:5001/v1")
    p.add_argument("--model", default=os.environ.get("MOTION_LLM_MODEL"))
    p.add_argument("--key", default=os.environ.get("MOTION_LLM_KEY"), help="API key, if the server wants one")
    p.add_argument("--prompt-file", default=os.environ.get("MOTION_PROMPT_FILE", DEFAULT_PROMPT_FILE))
    p.add_argument("--temperature", type=float, default=0.3)
    p.add_argument("--interactive", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="Print the result without writing the prompt file")
    p.add_argument("--ping", action="store_true", help="Test the connection and exit")
    p.add_argument("--bench", action="store_true", help="Run a set of sample requests (writes nothing)")
    p.add_argument("--no-fast", action="store_true", help="Always ask the LLM (skip the keyword fast path)")
    p.add_argument("--verified", default=None,
                   help="Wordings verified by ardy_lab.py (default: verified_prompts.json next to this script)")
    p.add_argument("--styles", action="store_true",
                   help="EXPERIMENTAL: carry style words (sexy, slow, playful...) into dance prompts. Each styled dance "
                        "falls back to a plain one if ARDY produces no movement for it")
    p.add_argument("--strict", action="store_true",
                   help="The old cautious behaviour: the LLM prefers KEEP for anything outside a short list of motions")
    p.add_argument("--no-lifetime", action="store_true",
                   help="Don't give gestures/activities an end and a return pose (they repeat until told otherwise)")
    p.add_argument("--watch", metavar="REQUEST_FILE", default=None,
                   help="Watch the file the VaM plugin writes requests to, and act on each new one")
    p.add_argument("--selftest", action="store_true", help="Test the validation rules (no LLM needed)")
    args = p.parse_args()
    global STYLES_ON, FREEDOM
    STYLES_ON = args.styles
    FREEDOM = not args.strict
    VERIFIED.update(load_verified(args.verified or VERIFIED_FILE))
    if VERIFIED and not args.selftest:
        print("Verified wordings in use: " + ", ".join(sorted(VERIFIED)))
        made_under = load_verified_settings(args.verified or VERIFIED_FILE)
        if made_under:
            print(f"  (verified with the stream running: {made_under})")

    if args.selftest:
        sys.exit(selftest())
    if not args.url:
        sys.exit("Give the LLM address with --url (for example http://192.168.1.50:5001/v1), "
                 "or set MOTION_LLM_URL.")
    if args.ping:
        sys.exit(ping(args.url, args.model, args.key))

    if args.bench:
        sys.exit(bench(args.url, args, args.key))
    if args.watch:
        watch(args, args.url, args.key)
        return

    if args.interactive:
        print(f"Type what she should do. Prompt file: {args.prompt_file}. 'quit' to exit.")
        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if line.lower() in ("quit", "exit", "q"):
                break
            if line:
                run_request(line, args, args.url, args.key)
        return
    request = " ".join(args.request).strip()
    if not request:
        sys.exit("Say what she should do, e.g.:  python motion_prompter.py \"sit on the floor and relax\"")
    sys.exit(0 if run_request(request, args, args.url, args.key) else 1)


if __name__ == "__main__":
    main()
