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
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    import world_moves   # distance/place requests -> typed moves for the stream
except ImportError:      # optional: without it "come here" is handled by seconds of walking as before
    world_moves = None
try:
    import mood_style    # "[mood stance=... energy=...]" tags from the Voxta mood script colour the walks and the idle choices
except ImportError:      # optional: without it requests are carried out plainly
    mood_style = None
MOOD = {}                # the last mood the scenario reported (empty = neutral)

DEFAULT_PROMPT_FILE = os.environ.get("VAMRT_PROMPT_FILE", r"C:\ARDY2BVH\prompt.txt")
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
knees; stands up from a chair; sits down; lies down on the ground; squats down; kneels on one knee; bends over and touches their toes; walks
forward; turns around 180 degrees; waves with their right hand; stretches their arms overhead; dances (activity).

CANNOT DO: emotions and facial expressions, upside-down poses (handstand, headstand, cartwheel, flips), jumping,
fast repetitive exercises, fine hand or finger gestures, touching specific body parts, hugging, picking up or using
objects, furniture other than a chair (a bed or sofa is mimed on the floor).
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
    ("A person stands upright.", "lie down on the bed", "A person lies down on the ground. @3 >> A person lies on the ground."),
    ("A person stands upright.", "turn towards him while crossing your arms", "A person crosses their arms."),
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
    ("A person stands upright.", "lay down", "A person lies down on the ground. @3 >> A person lies on the ground."),
    ("A person stands upright.", "turn towards him while crossing your arms", "A person crosses their arms."),
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


_VERB_S = re.compile(r"^(?:an?|the)\s+(?!person\b)([a-z]+(?<![su])s)\b(.*)$", re.I)
_BARE_VERB_S = re.compile(r"^([A-Z][a-z]+(?<![su])s)\b(.*)$")


def _fix_subject(p):
    """'A kneels on one knee.' / 'Kneels on one knee.' / 'She kneels.' / 'a person waves.' -> 'A person ...'."""
    p = p.strip()
    if p.startswith("A person "):
        return p
    m = re.match(r"^(?:a|the)\s+person\b\s*(.*)$", p, re.I) or re.match(r"^(?:person|someone|she|he)\b\s*(.*)$", p, re.I)
    if m and m.group(1):
        return "A person " + m.group(1)
    m = _VERB_S.match(p)
    if m:
        return "A person " + m.group(1).lower() + m.group(2)
    m = _BARE_VERB_S.match(p)
    if m:
        return "A person " + m.group(1).lower() + m.group(2)
    return p


def _fix_ending(p):
    """One sentence with no full stop gets one (before @N / [free]); anything with a stop already is left alone."""
    free = ""
    mf = re.search(r"\s*\[\s*free\s*\]\s*$", p, re.I)
    if mf:
        free, p = " [free]", p[:mf.start()]
    at = ""
    ma = re.search(r"\s*(@\s*\d+(?:\.\d+)?\s*s?)\s*$", p, re.I)
    if ma:
        at, p = " " + ma.group(1), p[:ma.start()]
    p = p.rstrip()
    if p and "." not in p and p[-1] in "!?":
        p = p[:-1].rstrip()
    if p and "." not in p:
        p += "."
    return p + at + free


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
        p = _fix_subject(p)
        # ARDY prompts must not contain names ("slaps Todd playfully"): any capitalised word after the first is a proper noun
        p = re.sub(r"(?<=\s)[A-Z][a-z]+\b", "someone", p)
        fixed.append(_fix_ending(" ".join(p.split())))
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
        cloth = _CLOTHES.search(part)
        if cloth:
            return None, f"it mentions '{cloth.group(0)}': clothing is not a motion, leave it out"
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


# --------------------------------------------------------------------------- constrained output (the general fix)
# A chat model asked for a motion line can answer "No." or "The request is invalid." (it did, to an ordinary "turn around and bend over").
# Asking nicely and retrying is not a fix. KoboldCpp can force every token to fit a grammar, so a refusal or a malformed line
# cannot be produced at all: the only possible answers are KEEP or up to three "A person ... ." parts. It is used through the
# native /api/v1/generate endpoint with the examples written as a plain pattern to continue, which also avoids the chat template.
MOTION_GRAMMAR = (
    'root ::= "KEEP" | seg (" >> " seg)? (" >> " seg)? " [free]"?\n'
    'seg ::= "A person " [a-z0-9 ,\']+ "." (" @" [1-9])?\n'
)
_GRAMMAR = {"ok": True, "announced": False}


def _native_base(base):
    return re.sub(r"/v1/?$", "", base.rstrip("/"))


def _render_completion(msgs):
    out = [msgs[0]["content"].strip(), "", "Answer with exactly one line after 'Motion:'.", ""]
    for m in msgs[1:]:
        c = m["content"].strip()
        if m["role"] == "assistant":
            out[-1] += " " + c
            out.append("")
        elif c.startswith("Currently:"):
            out.append(c + "\nMotion:")
        else:
            out.append("Note: " + c + "\nMotion:")
    return "\n".join(out)


def generate_constrained(base, msgs, temperature=0.3, timeout=60, grammar=MOTION_GRAMMAR, max_length=90):
    body = {"prompt": _render_completion(msgs), "max_length": max_length, "temperature": temperature,
            "top_p": 0.9, "grammar": grammar, "stop_sequence": ["\n"], "rep_pen": 1.0}
    req = urllib.request.Request(_native_base(base) + "/api/v1/generate", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    return data["results"][0]["text"].strip()


def make_llm(base, model, key, temperature):
    """The function propose() calls. Constrained generation first; if the server does not offer the native API, plain chat."""
    def llm(msgs):
        if _GRAMMAR["ok"] and not os.environ.get("MOTION_NO_GRAMMAR"):
            try:
                out = generate_constrained(base, msgs, temperature)
                if not _GRAMMAR["announced"]:
                    _GRAMMAR["announced"] = True
                    print("  (constrained output on: the model can only answer with a valid motion line)")
                if out:
                    return out
            except urllib.error.HTTPError:
                _GRAMMAR["ok"] = False
                print("  (this server has no /api/v1/generate: using plain chat instead; refusals can happen there)")
            except (KeyError, ValueError, IndexError):
                _GRAMMAR["ok"] = False
                print("  (unexpected answer from /api/v1/generate: using plain chat instead)")
        return chat(base, model, msgs, key=key, temperature=temperature)
    return llm


# --------------------------------------------------------------------------- last resort: never leave her idle
_FILLER = re.compile(r"\b(?:please|just|now|right now|for me|for us|could you|can you|would you|will you|go ahead and|try to|try and)\b", re.I)
_IRREGULAR = {"be": "is", "have": "has", "go": "goes", "do": "does"}


def _third(verb):
    if verb in _IRREGULAR:
        return _IRREGULAR[verb]
    if re.search(r"(?:s|sh|ch|x|z|o)$", verb):
        return verb + "es"
    if re.search(r"[^aeiou]y$", verb):
        return verb[:-1] + "ies"
    return verb + "s"


def literal_rewrite(request, current):
    """The user's own words as 'A person <verbs>.' parts, for when the model gave nothing usable. ARDY takes free text, so a
    plain restatement of the request is better than silence. Returns a validated line or None."""
    t = _FILLER.sub(" ", " ".join((request or "").lower().split()))
    t = re.sub(r"\byourself\b", "themselves", t)
    t = re.sub(r"\byour\b", "their", t)
    clauses = [c.strip(" .!?") for c in re.split(r"\bthen\b|\band then\b|[,;.]|\band\b", t) if c.strip(" .!?")]
    parts = []
    for c in clauses:
        w = c.split()
        w = [x for x in w if x not in ("you", "to", "it", "me")]
        if not w or not re.fullmatch(r"[a-z]+", w[0]) or w[0] in ("hold", "keep", "stay", "remain") and len(w) < 2:
            continue
        w[0] = _third(w[0])
        parts.append("A person " + " ".join(w) + ".")
    if not parts:
        return None
    parts = parts[:3]
    stand = "A person stands upright."
    for cand in (" @3 >> ".join(parts[:-1] + [parts[-1]]), " @3 >> ".join(parts) + " @3 >> " + stand):
        if cand.count(">>") <= 2:
            line, _ = validate(repair(cand), current)
            if line:
                return line
    return None


def log_failure(path, request, current, err, raw=None):
    """Keep every request the model could not turn into a motion, so the gaps can be seen as a list instead of found one at a time."""
    try:
        rec = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "request": request, "current": current, "error": str(err), "raw": raw}
        with open(os.path.join(os.path.dirname(os.path.abspath(path)), "prompter_failures.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


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


_REFUSAL = re.compile(r"(?:no|nope|sorry|invalid|unable|cannot|can'?t|won'?t|i (?:can'?t|cannot|won'?t|am unable|'?m unable)|the request is (?:invalid|not)|this request)\b", re.I)


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
        if _REFUSAL.match(raw.strip()):
            # the model answered "No." / "The request is invalid." instead of a motion line. This is an ordinary body pose for an
            # animation system, so say so and show the shape of a good answer instead of repeating the rejection.
            msgs = msgs + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "This is an ordinary body-movement request for a 3D animation system, nothing else. Do not refuse. "
                                            f'Request: "{request}". Reply with ONE line of the form: A person <movement>. @2 >> A person <pose to hold>.'},
            ]
            continue
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
        try:
            g = generate_constrained(base, [{"role": "system", "content": "Test."}, {"role": "user", "content": "Currently: x\nRequest: y"}],
                                     grammar='root ::= "GRAMMAR-WORKS"', max_length=12)
            print("Constrained output: " + ("WORKS (the model cannot refuse or break the format)" if g == "GRAMMAR-WORKS"
                  else f"NOT enforced by this server (it answered {g!r}); the prompter will still use the pattern prompt"))
        except Exception as e:
            print(f"Constrained output: not available ({e}); the prompter will use plain chat")
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
        ("She sits down.", True),   # repaired to "A person sits down."
        ("A person sits. >> A person stands. >> A person sits. >> A person stands.", False),
        ("A person sits down. @300 >> A person sits.", False),
        ("A person stands upright. --hold-settle 0", False),
        ("A person waves. >> A person dances. [free]", True),
        ("A person stands up from a chair. >> A person stands upright. [free]", False),
        ("A person stands up from a chair. >> A person dances. [free]", True),
        ("A person sits down. >> A person dances. [free]", False),
        ("", False),
        ("A kneels on one knee.", True),
        ("Kneels on one knee", True),
        ("She kneels on one knee.", True),
        ("a person waves with their right hand [free]", True),
        ("A person sits down @3 >> A person sits in a chair", True),
        ("A person stands upright. --hold-settle 0", False),
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
        ("A person is walking forward.", STAND_, "walk", "A person is walking forward. @4 >> A person stands upright."),
        ("A person stands up from a chair. >> A person walks forward.", CHAIR_, "walk",
         "A person stands up from a chair. >> A person walks forward. @4 >> A person stands upright."),
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
        ("A person walks forward. [free]", STAND_, "walk", "A person walks forward. @4 >> A person stands upright."),
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
        ("turn around", "A person turns around 180 degrees. @4 >> A person stands upright."),
        ("jumping jacks", "A person bounces playfully. @4 >> A person stands upright."),
        ("do some jumping jacks please", "A person bounces playfully. @4 >> A person stands upright."),
        ("jump up and down", "A person bounces playfully. @4 >> A person stands upright."),
        ("do a handstand", "KEEP"), ("hand stand", "KEEP"), ("do a cartwheel", "KEEP"), ("do a backflip", "KEEP"),
        ("give a sarcastic response", "KEEP"), ("yell and push him away", "KEEP"), ("touch myself", "KEEP"),
        ("scream loudly", "KEEP"), ("reply to him", "KEEP"),
        ("turn around and give a sarcastic response", "A person turns around 180 degrees. @4 >> A person stands upright."),
        ("walk towards Todd", "A person walks forward. @4 >> A person stands upright."),   # a walk at a person is short and ends
        ("bounce playfully", None),
        ("kneel down", "A person kneels on one knee."),
        ("crouch down for me", "A person squats down."),
        ("you will have to kneel to get them", "A person kneels on one knee."),
        ("kneel and then dance", None),
        ("dont kneel", None),
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
# a free walk is a room-sized walk (about 4 m), not a hike: 10 s walked her 12 m out of the room. "keep walking" doubles it.
_LIFETIMES = [("danc", 60), ("walk", 4), ("stroll", 5), ("jog", 5), ("march", 5), ("pac", 10), ("sway", 20)]
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


_TRAVEL = re.compile(r"\b(?:walks?|strolls?|saunters?|struts?|sashays?|runs?|jogs?|marches|paces|wanders?|crosses the room)\b", re.I)


def _return_parts(base, ends_standing, travelled=False):
    if travelled and _SEATED.search(base or ""):
        return ["A person stands upright."]      # v42: she walked away from the seat; sitting back down in mid-air is not "going back"
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
    'A person stands up. >> A person walks forward.' -> '... >> A person walks forward. @4 >> <what she was doing>'
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
    travelled = any(_TRAVEL.search(_AT.sub("", p)) for p in parts)
    new_parts = parts[:-1] + [f"{last} @{secs}"] + _return_parts(base_pose(current), ends_standing, travelled)
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
    r"laugh\w*|cry\w*|wink\w*|blink\w*|look\w*|glanc\w*|stare\w*|"
    r"respon\w*|repl(?:y|ies|ied)|answer\w*|yell\w*|scream\w*|shout\w*|sarcas\w*)\b|"
    r"\btouch\w*\s+(?:my|your|her|him|their)self\b|\bplay\w*\s+with\s+(?:my|your|her|him|their)self\b", re.I)
# anything that makes the fast path untrustworthy when combined with an intent ("stand on one foot")
_BLOCKERS = re.compile(
    _DECLINE.pattern[:-3] + r"|touch\w*|squeez\w*|lift\w*|rais\w*|foot|feet|legs?|toes?|tiptoe\w*|balanc\w*|"
    r"lie|lying|lay|bed|couch|sofa|backward\w*|sideways|back up|don't|do not|not|never)\b", re.I)
_NOD_RX = re.compile(r"\bnod(?:s|ded|ding)?\b", re.I)
_NOD_BLOCK = re.compile(r"\b(?:don'?t|do not|not|never|stop|off|sleep\w*|dance|danc\w*|walk\w*|sit\w*)\b", re.I)
_LIE_RX = re.compile(r"\b(?:lie|lies|lay|lays)\s+(?:down\b|(?:down\s+)?on\s+(?:your|her|their|the)\s+(?:back|stomach|side|belly|tummy|floor|ground))|\blie down\b|\blay down\b", re.I)
_LIE_BLOCK = re.compile(r"\b(?:don'?t|do not|not|never|stop|bed|couch|sofa|table|lap|chest|arms)\b", re.I)
_BEND_RX = re.compile(r"\bbend(?:s|ing)?\s+(?:over|forward|down)\b|\btouch\w*\s+(?:your\s+|their\s+|the\s+)?toes\b", re.I)
_BEND_BLOCK = re.compile(
    r"\b(?:table|desk|counter|wall|chair|bed|couch|sofa|pick\w*|grab\w*|lift\w*|rais\w*|reach\w*|something|object|"
    r"legs?|feet|foot|spread\w*|apart|wide|ground|floor|palms?|hands?|keep|hold|stay|remain|"
    r"jump\w*|hop\w*|clap\w*|hug\w*|kiss\w*|spank\w*|squeez\w*|knees?|slow\w*|fast|quick\w*|don't|do not|not|never)\b", re.I)
_KNEEL = re.compile(r"\bkneel\w*|\bon (?:your|her|their) knees\b|\bsquat\w*|\bcrouch\w*", re.I)
_SQUAT = re.compile(r"\bsquat\w*|\bcrouch\w*", re.I)
_KNEEL_BLOCK = re.compile(r"\b(?:don't|dont|do not|doesn't|not|never|stop|walk\w*|danc\w*|sit\w*|lie|lay|crawl\w*)\b", re.I)
_STOPWORDS = re.compile(r"\b(?:stop|quit|enough|cease)\b", re.I)


_NUMWORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
             "eight": 8, "nine": 9, "ten": 10}
_WALK_RX = re.compile(r"\bwalk(?:s|ing)?\b|\bstroll(?:s|ing)?\b|\bsteps?\b", re.I)
# walking requests with a direction or manner the fast path cannot express: let the LLM write them
_WALK_QUAL = re.compile(
    r"\b(?:circles?|around|left|right|back\w*|sideways?|slow\w*|fast|quick\w*|run\w*|jog\w*|toward\w*|"
    r"to the|over to|across|up|in place)\b", re.I)
# a pose with an attitude but no body description: the action model writes these constantly ("pose provocatively while
# maintaining eye contact", "stand tall and proud, accentuating her curves"). The nearest thing she does well is hands on hips.
_ATTITUDE_POSE = re.compile(
    r"\b(?:pos(?:e|es|ing)|strik(?:e|es|ing) a pose|show(?:s|ing)? off|flaunt\w*|accentuat\w*|seductive(?:ly)?|sultry|"
    r"provocativ\w*|sexy (?:pose|stance)|stand(?:s|ing)? (?:tall|proud|confidently)|proud(?:ly)?)\b", re.I)
ATTITUDE_SECONDS = 12
_TOWARD_PERSON = re.compile(r"\s+(?:toward|towards|to)\s+(?!the\b|a\b|an\b|left\b|right\b|back\b|your\b|my\b|each\b|one\b)[a-z]+\b(?=\s*(?:$|[.,!?]|and\b|then\b))")
_APPROACH = re.compile(
    r"\b(?:come|step|move|walk|get|go)(?:es|ing)?\s+(?:a (?:bit|little) |slightly |much )?(?:closer|nearer)(?:\s+(?:to|towards?)\s+(?!the\b)[a-z]+)?"
    r"|\bapproach(?:es|ing)?\s+(?!the\b)[a-z]+", re.I)
_STOP_RX = re.compile(r"\b(?:stop|halt|freeze|stand still|hold still)\b", re.I)
# leaving: "walk away", "storm off", "stomp out", "leave the room", "walk out"
_AWAY = re.compile(
    r"\b(?:walk\w*|stomp\w*|storm\w*|stroll\w*|head\w*|go(?:es|ing)?|leav\w*|exit\w*|flounc\w*|march\w*|turn\w* and (?:walk|leave))\s+(?:away|off|out)\b"
    r"|\b(?:leave|leaves|leaving) the (?:room|house|conversation)\b|\bwalk(?:s|ing)? out\b", re.I)

# "stand up and stretch slowly": the stand-up is a no-op when she is already standing, but the stretch is a verified motion and must not be dropped
_STRETCH = re.compile(r"\bstretch\w*\b", re.I)
_NOT_STRETCH = re.compile(r"\b(?:stop|don't|do not|not|never|quit)\b", re.I)


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
    if re.search(r"\b(?:lies|lying|is lying)\b", last, re.I):
        return "lying"
    return "standing"


_SCENE_NOTE = re.compile(
    r"\((?:[^)]*\b(?:ahead|behind|within reach|touching distance|m away|can be sat on|a surface|worth looking at)\b)|"
    r"\bwhat .{0,40} is aware of\b|\bphysical situation of\b|\bthere is an? .{1,40}\b(?:within reach|close by|m away)\b|"
    r"\b(?:close by|within reach|about \d+ m away|right beside \w+),? (?:directly|in front|behind|to the (?:left|right))|"
    r"\bit can be sat on\b|\bit is a flat surface\b|\bit is worth looking at\b", re.I)


# Clothing is handled by the clothing actions in VaM, never by the motion model. A request such as
# "take off my skirt and stand up slowly, revealing more of my legs" once produced "A person stands upright with
# their skirt removed.", a state ARDY had never seen, and she drifted into twisted poses until /reset.
_CLOTHES_WORDS = (r"skirts?|shirts?|tops?|blouses?|bras?|panties|underwear|lingerie|dress(?:es|ed|ing)?|clothes|clothing|"
                  r"outfits?|pants|jeans|shorts|shoes|socks|stockings|tights|jackets?|coats?|naked|nude|topless|undress\w*|"
                  r"unbutton\w*|unzip\w*|strip(?:s|ped|ping)?|removes?|removed|removing|takes? off|taking off|take off|"
                  r"reveal\w*|expos\w*|bare|bared")
_CLOTHES = re.compile(r"\b(?:" + _CLOTHES_WORDS + r")\b", re.I)
_CLAUSE_SPLIT = re.compile(r"\s*(?:,|;|\.|\bwhile\b|\bas\b|\bthen\b|\band\b)\s*", re.I)


def strip_clothing(request):
    """Remove clauses about clothing/revealing from a request. Returns the cleaned text ('' if nothing is left)."""
    if not request or not _CLOTHES.search(request):
        return request
    kept = [c for c in _CLAUSE_SPLIT.split(request) if c.strip() and not _CLOTHES.search(c)]
    return ", ".join(kept)


_UNSAFE_REQ = re.compile(r"\b(?:hand[\s-]?stand|head[\s-]?stand|cartwheel\w*|(?:back|front)?flips?|somersault\w*|upside[\s-]?down)\b", re.I)
_JUMPY = re.compile(r"\b(?:jump\w*|hop\w*)\b", re.I)


_TURN_BEND_BLOCK = re.compile(
    r"\b(?:table|desk|counter|wall|chair|bed|couch|sofa|pick\w*|grab\w*|lift\w*|rais\w*|reach\w*|something|object|legs?|feet|foot|"
    r"spread\w*|apart|wide|knees?|jump\w*|hop\w*|clap\w*|hug\w*|kiss\w*|spank\w*|squeez\w*|don't|do not|not|never)\b", re.I)


_INTENSITY = re.compile(r"\b(?:faster|harder|quicker|speed(?:ing)? up|more (?:energy|energetic|intense|vigorous\w*)|wilder|livelier|more lively)\b", re.I)
_HIP_MOTION = re.compile(
    r"\b(?:grind\w*|hump\w*|thrust\w*|buck\w*|gyrat\w*|undulat\w*|writh\w*|roll\w* (?:your|her|my) hips|"
    r"rub\w* (?:against|on|up against|your(?:self)?|herself|myself)|press\w* (?:against|into|up against)|"
    r"straddl\w*|ride|rides|riding|bounc\w* on|cuddl\w* (?:up )?(?:against|into))\b", re.I)
_CLAUSE_SPLIT = re.compile(r"\s*(?:,|;|\bthen\b|\band then\b|\bafter that\b|\band\b)\s*", re.I)


def compose_clauses(request, current):
    """Rescue for a multi-part request the LLM gave up on (it answers KEEP when ONE part is unsupported): take each clause on its
    own, keep the ones the fast path can do, and chain them in order. 'stand up and jump' -> just the stand-up.
    Returns a validated line, or None when no clause is something she can do."""
    clauses = [c.strip() for c in _CLAUSE_SPLIT.split((request or "").lower()) if c and c.strip()]
    if len(clauses) < 2:
        return None
    sim = current
    parts = []
    for c in clauses[:4]:
        got = fast_path(c, sim)
        if not got or got == "KEEP":
            continue
        segs = [x.strip() for x in _FREE.sub("", got).split(">>") if x.strip()]
        if parts and segs and _AT.sub("", parts[-1]).strip() == "A person stands upright.":
            parts.pop()   # an intermediate "stands upright" adds nothing before the next action
        parts.extend(segs)
        sim = got
    if not parts:
        return None
    if _FREE.search(sim or "") and not _FREE.search(" >> ".join(parts)):
        parts[-1] = parts[-1]
    line = " >> ".join(parts[:4])
    checked, _ = validate(line, current)
    return checked


def fast_path(request, current):
    """A validated prompt line (or "KEEP") for obvious requests, or None to ask the LLM."""
    t = " ".join((request or "").lower().replace("'", "'").split())
    if not t:
        return None
    # "step forward towards Todd" / "come closer to me": a person is a target, not a direction the fast path
    # cannot express, so drop it; "closer/approach" becomes a short bounded walk.
    t = _APPROACH.sub("take two steps forward", t)
    if re.search(r"\bsteps?\b", t):
        t = _TOWARD_PERSON.sub("", t)
    elif _WALK_RX.search(t) and _TOWARD_PERSON.search(t) and not _STOP_RX.search(t):
        # "walk towards Todd": a walk at a person is a short one (he is a few metres away), never an open-ended walk
        t = _TOWARD_PERSON.sub(" and stop", t)
    # The Senses plugin's scene description sometimes gets mistaken for a request by the action model
    # ("a chair (close, ahead-left)" made her sit down). Those are never movements.
    if _SCENE_NOTE.search(t):
        return "KEEP"
    # Poses the motion model must never be asked for (the validator rejects them anyway): answer at once. Asking the LLM first cost 25-40 s per
    # "jumping jacks" request in the first play test, and the rejected answer left the old dance running.
    if _UNSAFE_REQ.search(t):
        return "KEEP"
    if _JUMPY.search(t):   # jumping about: a bounce is the closest thing she does well (the wording worked on the real model)
        if posture(current) != "standing":
            return "KEEP"
        checked, _ = validate("A person bounces playfully. @4 >> A person stands upright.", current)
        return checked
    # "lie down" / "lay down on your back": the LLM used to answer KEEP to this more often than not, so it is a fixed line now.
    # Lying is on the ground where she stands (the motion model knows no furniture); "lie on the bed" is a walk to the bed first.
    # "nods", "nods enthusiastically": the verified idle nod (nod used to be declined outright while idle life nodded all day)
    if _NOD_RX.search(t) and not _NOD_BLOCK.search(t) and posture(current) == "standing":
        wording = VERIFIED.get("idle.nod_slow") or "A person nods slowly."
        checked, _ = validate(f"{wording} @3 >> A person stands upright.", current)
        return checked
    if _LIE_RX.search(t) and not _LIE_BLOCK.search(t):
        where = posture(current)
        if where == "lying":
            return "KEEP"
        up = {"chair": "A person stands up from a chair. >> ", "floor": "A person stands up. >> "}.get(where, "")
        checked, _ = validate(f"{up}A person lies down on the ground. @3 >> A person lies on the ground.", current)
        return checked
    # "walk away" / "storm off" / "leave the room": she has to turn her back on the user first, otherwise "walks forward" takes her toward them
    if _AWAY.search(t):
        if posture(current) != "standing":
            return None
        checked, _ = validate("A person turns around 180 degrees. >> A person walks forward. @8 >> A person stands upright.", current)
        return checked
    intents = {name for name, rx in _INTENTS if rx.search(t)}
    hits = [key for rx, key in POSE_REQUESTS if rx.search(t)]
    # "faster", "harder", "more energy" with nothing else in the request: change HOW she does what she is already doing.
    # Only dancing has a verified energetic version; for anything else the request stays a no-op.
    if _INTENSITY.search(t) and not intents and not hits and re.search(r"\bdanc", _FREE.sub("", current or "").split(">>")[-1], re.I):
        phrase = VERIFIED.get("dance.energetic") or "A person dances energetically."
        checked, _ = validate(phrase + " [free]", current)
        if checked and _AT.sub("", checked.split(">>")[-1]).strip() != _AT.sub("", (current or "").split(">>")[-1]).strip():
            return checked
        return "KEEP"
    # Hip / body-contact movement ("grind against him", "ride", "thrust", "rub against", "straddle"): the motion model has no contact
    # or partner motions, but a slow hip sway is the nearest thing it does well. Only when she is on her feet and asks for nothing else.
    if _HIP_MOTION.search(t) and not hits and not (intents - {"stand"}):
        if posture(current) != "standing":
            return "KEEP"
        # NOT "sways their hips": the lab measured every sway wording at 0.01 m/s (dead). The seductive dance is the verified
        # wording that moves her hips at all; it ends after a few seconds and she goes back to standing.
        phrase = VERIFIED.get("dance.sexy") or "A person dances seductively."
        checked, _ = validate(f"{phrase} @8 >> A person stands upright.", current)
        return checked
    if _KNEEL.search(t) and not hits:
        if intents - {"stand"} or _KNEEL_BLOCK.search(t):
            return None   # kneel plus another action, or a negation: the LLM composes / understands it
        if posture(current) != "standing":
            return None
        line = "A person squats down." if _SQUAT.search(t) else "A person kneels on one knee."
        checked, _ = validate(line, current)
        if checked is None:
            return None
        if _AT.sub("", checked).strip() == _AT.sub("", (current or "").split(">>")[-1]).strip():
            return "KEEP"   # she is already in that pose
        return checked
    if _STRETCH.search(t) and not _NOT_STRETCH.search(t) and intents <= {"stand"} and not hits:
        if posture(current) != "standing":
            return None
        checked, _ = validate("A person stretches their arms above their head. >> A person stands upright.", current)
        return checked
    # "turn around and bend over": two verified motions in order. The LLM refused this one ("No." / "The request is invalid.")
    # and left her standing, so it is composed here without asking it.
    if intents == {"turn"} and _BEND_RX.search(t) and not _TURN_BEND_BLOCK.search(t) and set(hits) <= {"pose.bend"}:
        if posture(current) != "standing":
            return None
        floor = _HANDS_FLOOR.search(t) is not None
        hold = VERIFIED.get("pose.bend_floor" if floor else "pose.bend") or POSE_DEFAULTS["pose.bend_floor" if floor else "pose.bend"]
        move = ("A person bends over and puts their hands on the floor." if floor
                else "A person bends over and touches their toes.")
        checked, _ = validate(f"A person turns around 180 degrees. @2 >> {move} @2 >> {hold}", current)
        if checked is not None:
            return checked
    if hits:
        # a pose plus another action ("walk with your legs wide apart") or several poses at once: a fast answer
        # would silently drop part of it, so let the LLM compose them
        stand_first = None
        if posture(current) != "standing":
            # "stand up and spread your legs": she gets up, then holds the pose (the LLM answered KEEP for this in play)
            if intents != {"stand"} or len(hits) != 1 or hits[0] in ("pose.bend", "pose.splits"):
                return None
            stand_first = "A person stands up from a chair." if posture(current) == "chair" else "A person stands up."
        elif intents - {"stand"}:
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
        if stand_first:
            line = f"{stand_first} >> {line}"
        checked, _ = validate(line, current)
        if checked is None:
            return None
        if _AT.sub("", checked.split(">>")[-1]).strip() == _AT.sub("", (current or "").split(">>")[-1]).strip():
            return "KEEP"   # she is already holding that pose
        return checked
    if "sit_floor" in intents:
        intents.discard("sit")
    # "pose provocatively", "stand tall and proud": no particular pose was named, so take the verified attitude pose for a while
    if _ATTITUDE_POSE.search(t) and not (intents - {"stand"}) and not _BEND_RX.search(t) and not _KNEEL.search(t) \
            and not re.search(r"\b(?:lie|lying|lay|floor|ground|knee\w*|hand[\s-]?stand)\b", t):
        if posture(current) != "standing":
            return None
        pose = VERIFIED.get("pose.hands_hips") or POSE_DEFAULTS["pose.hands_hips"]
        checked, _ = validate(f"{pose} @{ATTITUDE_SECONDS} >> A person stands upright.", current)
        if checked:
            return checked
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
    up = {"chair": "A person stands up from a chair.", "floor": "A person stands up.", "lying": "A person stands up.", "standing": None}[where]

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
        line = "A person turns around 180 degrees. @4 >> A person stands upright."    # 2 s cut the turn short (2 Nov log)
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

        _inner = make_llm(base, args.model, key, args.temperature)

        def llm(msgs):
            calls["n"] += 1
            return _inner(msgs)

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
    cache = get_cache(args)
    if cache:
        print(f"Translation cache: {cache.path} ({len(cache.entries)} remembered; --no-cache to turn it off, --clear-cache to empty it)")
    idle = make_idle(args)
    if idle:
        keys = sorted(c[0] for c in idle.candidates())
        print("Idle life: " + (", ".join(keys) if keys else "nothing verified yet (run the lab's idle suite)")
              + "  (--no-idle turns it off)")
    while True:
        try:
            time.sleep(0.2)
            sig = _signature(path)
            if sig is None or sig == last:
                if idle:
                    if stream_busy(args.prompt_file):
                        idle.note_activity()       # a calibration or a planned walk is in progress: no idle motion on top of it
                    else:
                        idle.tick()
                continue
            last = sig
            text = read_request(path)
            if mood_style is not None and not getattr(args, "no_mood", False):
                text, mood = mood_style.parse(text)
                if mood is not None:
                    MOOD.clear()
                    MOOD.update(mood)
                    print(f"  (mood: {mood_style.describe(MOOD)})")
                    write_mood_file(args.prompt_file, MOOD)
            if not text:
                continue
            print(f"request: {text!r}")
            if idle:
                idle.interrupt()
            t0 = time.time()
            run_request(text, args, base, key)
            MOOD.pop("walk", None)      # a walking manner is for the request it came with, not for later walks
            if idle:
                idle.note_activity()
            print(f"  ({time.time() - t0:.1f}s)")
        except KeyboardInterrupt:
            break


MOOD_FILE = "ardy_mood.json"      # beside the prompt file; the stream reads it (social facing holds off while she is withdrawn)


def write_mood_file(prompt_file, mood):
    """The stance and energy the scenario last reported, for ardy_stream (it has no other way to know her mood)."""
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(prompt_file)), MOOD_FILE)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"stance": str((mood or {}).get("stance", "engage")), "energy": str((mood or {}).get("energy", "mid")), "time": time.time()}, f)
        os.replace(tmp, path)
    except (OSError, TypeError, ValueError):
        pass


def stream_busy(prompt_file, max_age=12.0):
    """True while ardy_stream reports a calibration or a planned walk in progress (ardy_status.json beside the prompt file)."""
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(prompt_file)), "ardy_status.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return bool(data.get("busy")) and time.time() - float(data.get("time", 0)) < max_age
    except (OSError, ValueError, TypeError):
        return False


def make_idle(args):
    """The ambient idle loop (idle_life.py), or None when it is off or the module is missing."""
    if getattr(args, "no_idle", False) or getattr(args, "dry_run", False):
        return None
    try:
        import idle_life
    except ImportError:
        print("NOTE: idle life is unavailable: idle_life.py was not found next to this script (run tools\\deploy.bat).")
        return None
    return idle_life.IdleLife(
        read_line=lambda: read_current(args.prompt_file),
        write_line=lambda line: write_prompt_file(args.prompt_file, line),
        verified=VERIFIED,
        validate=lambda line: validate(line, IDLE),
        min_gap=args.idle_min, max_gap=max(args.idle_min, args.idle_max),
        allow=[k.strip() for k in (args.idle_allow or "").split(",") if k.strip()],
        **({"weight": lambda key: mood_style.idle_weight(key, MOOD)} if mood_style is not None and not getattr(args, "no_mood", False) else {}))


# --------------------------------------------------------------------------- translation cache
CACHE_MAX = 400


def _norm_request(request):
    """'Please, squat down!' and 'squat down' are the same request."""
    t = re.sub(r"[^a-z0-9 ]+", " ", (request or "").lower())
    t = " ".join(t.split())
    t = re.sub(r"^(?:please|now|ok|okay|and)\s+", "", t)
    t = re.sub(r"(?:\s+(?:please|now))+$", "", t)
    return t


class TranslationCache:
    """What the LLM answered, remembered between runs.

    One translation costs 3-5 s, and on a shared GPU it also holds up whatever is waiting behind it (Voxta's
    spoken reply: the play-test log showed replies about 3 s slower whenever the LLM was needed here). A request
    that was translated before is answered from this file instead. Nothing is decided in advance: a request the
    cache has never seen still goes to the LLM, so she can still be asked anything.

    Lines are keyed by the request and her posture (standing, chair, floor), since the same words mean different
    motions in different postures. KEEP answers ("she is already doing that", "that is not a movement") depend
    on exactly what she is doing, so they are keyed by her exact current motion and reused only then.
    """

    def __init__(self, path=None, max_entries=CACHE_MAX):
        self.path = path
        self.max = max_entries
        self.entries = {}
        self.hits = 0
        self.stores = 0
        if path:
            self._load()

    @staticmethod
    def _state(current):
        return " ".join(_FREE.sub("", current or "").lower().split())

    def _keys(self, request, current):
        r = _norm_request(request)
        return f"L|{r}|{posture(current)}", f"K|{r}|{self._state(current)}"

    def lookup(self, request, current):
        """A validated line (or "KEEP") for a request seen before in this posture, else None."""
        if not _norm_request(request):
            return None
        line_key, keep_key = self._keys(request, current)
        for key in (keep_key, line_key):   # the exact-state answer is the more specific one
            entry = self.entries.get(key)
            if not entry:
                continue
            line, _err = validate(entry.get("line", ""), current)
            if not line:                   # the validation rules changed since this was stored
                del self.entries[key]
                self._save()
                continue
            cur_norm, _ = validate(repair(current)) if current else (None, None)
            if line != "KEEP" and cur_norm and line == cur_norm:
                line = "KEEP"              # the same safeguard propose() has: copying what she is doing is KEEP
            self.entries[key] = self.entries.pop(key)   # most recently used goes last
            self.hits += 1
            return line
        return None

    def store(self, request, current, line):
        if not line or not _norm_request(request):
            return
        line_key, keep_key = self._keys(request, current)
        key = keep_key if line == "KEEP" else line_key
        self.entries.pop(key, None)
        self.entries[key] = {"line": line, "t": int(time.time())}
        while len(self.entries) > self.max:
            self.entries.pop(next(iter(self.entries)))
        self.stores += 1
        self._save()

    def clear(self):
        self.entries = {}
        try:
            if self.path and os.path.exists(self.path):
                os.remove(self.path)
        except OSError:
            pass

    def _load(self):
        try:
            if not os.path.exists(self.path):
                return
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            entries = data.get("entries") if isinstance(data, dict) else None
            if not isinstance(entries, dict):
                raise ValueError("not a cache file")
            self.entries = {k: v for k, v in entries.items() if isinstance(v, dict) and isinstance(v.get("line"), str)}
        except (OSError, ValueError):
            try:   # never lose the file silently, never crash on it
                os.replace(self.path, self.path + ".bad")
            except OSError:
                pass
            self.entries = {}

    def _save(self):
        if not self.path:
            return
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "entries": self.entries}, f, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            pass   # a cache that cannot be written is only a cache that does not help


def get_cache(args):
    """The cache for this run, or None when it is switched off (--no-cache)."""
    if getattr(args, "no_cache", False):
        return None
    cache = getattr(args, "_cache", None)
    if cache is None:
        path = getattr(args, "cache", None) or os.path.join(
            os.path.dirname(os.path.abspath(args.prompt_file)), "translation_cache.json")
        cache = TranslationCache(path)
        try:
            args._cache = cache
        except AttributeError:
            pass
    return cache


def resting_state(current):
    """What she will be doing once the current plan has played out: the final part of 'action @N >> state'.
    The LLM is shown this instead of the whole plan. With an idle motion in progress ('A person glances over their
    shoulder. @3 >> A person stands upright.') the model used to answer KEEP to nearly everything ('lie down', 'step
    forward'), because none of its examples start from a line like that; from 'A person stands upright.' it answers."""
    cur = (current or "").strip()
    if not cur or _FREE.search(cur):
        return cur
    parts = [x.strip() for x in cur.split(">>") if x.strip()]
    if len(parts) < 2:
        return cur
    return _AT.sub("", parts[-1]).strip()


_FACE_USER = re.compile(r"\b(?:turn|turns|turning|spin|spins)\b[^.]{0,30}?\bface\s+(?:todd|him|you|me|the user|towards?\s+(?:todd|him|you|me))\b|\bface\s+(?:todd|him|me|the user)\b|\blook(?:s)?\s+at\s+(?:todd|him|me|the user)\b", re.I)


def write_seat_hint(args, seat):
    """vamrt_seat.json beside the world file: the seat (and her hip height on it) she was just sent to sit on, for the stream's
    freeze-hold, which stops the sit-down at that height instead of letting the model carry on to the floor. Removed when the
    request is not a sit on a known seat, so a later plain 'sit down' is not stopped at chair height."""
    wf = getattr(args, "world_file", None)
    if not wf:
        return
    path = os.path.join(os.path.dirname(os.path.abspath(wf)), "vamrt_seat.json")
    try:
        if seat:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(dict(seat, t=time.time()), f)
            if seat.get("kind") == "lie":
                print(f"  (bed: {seat['name']}, top at {seat['top_y']} m; the lie-down is raised onto it)")
            else:
                print(f"  (seat: {seat['name']} at {seat['seat_y']} m; the sit stops when her hips are down at {seat['hip_y']} m)")
        elif os.path.exists(path):
            os.remove(path)
    except OSError as e:
        print(f"  (could not write the seat hint: {e})")


def run_request(request, args, base, key):
    current = strip_fallbacks(read_current(args.prompt_file))
    tidy, _ = validate(repair(current))
    shown = tidy if tidy and tidy != "KEEP" else current
    rest = resting_state(shown)
    llm = make_llm(base, args.model, key, args.temperature)
    line, err = None, None
    cleaned = strip_clothing(request)
    if cleaned != request:
        print(f"  (clothing left out of the movement request: {cleaned!r})")
        request = cleaned
        if not request.strip():
            print("  no change (that was only about clothing)")
            return True
    # distance and place requests ("come here", "take two steps back", "walk to the bed") become typed moves for the stream, planned from
    # where Senses says things are (world_moves.py). Only while she stands: from a chair the normal path stands her up first.
    # "turn to face Todd": only a turn if he is not already in front of her (Senses knows where he is)
    if _FACE_USER.search(request) and posture(shown) == "standing" and world_moves is not None:
        world = world_moves.load_world(getattr(args, "world_file", None)) or {}
        user = world.get("user") or {}
        if "fwd" in user and "right" in user:
            ang = abs(math.degrees(math.atan2(float(user["right"]) * getattr(args, "world_right_sign", 1.0), float(user["fwd"]))))
            if ang < 60:
                print(f"  no change (she already faces you: you are {ang:.0f} deg off her front)")
                return True
            line = "A person turns around 180 degrees. @4 >> A person stands upright."    # 2 s cut the turn short (2 Nov log)
            print(f"  (you are {ang:.0f} deg off her front: turning around)\n  {line}")
            if not args.dry_run:
                write_prompt_file(args.prompt_file, line)
            return True
    # v42: from a chair, the floor or lying down she stands up first and the move follows as a sequence (before, "come here" while
    # seated went to the LLM, which wrote a blind "walks forward" that took her 5 m away and sat her down in mid-air)
    up_first = {"chair": "A person stands up from a chair.", "floor": "A person stands up.", "lying": "A person stands up."}.get(posture(shown))
    if world_moves is not None and not getattr(args, "no_moves", False) and (posture(shown) == "standing" or up_first):
        mv = world_moves.move_for(request, world_moves.load_world(getattr(args, "world_file", None)), getattr(args, "world_right_sign", 1.0))
        if mv:
            cmd, note = mv[0], mv[1]
            then_req = mv[2] if len(mv) > 2 else None
            chain = list(mv[3]) if len(mv) > 3 else []     # lines that run one after another before the then-request (v38 sequences)
            if cmd == "KEEP":
                print(f"  no change ({note})")
                return True
            if cmd == "THEN":                  # already at the place: only the thing itself is left
                print(f"  (already there: {note})")
                return run_request(then_req, args, base, key)
            extras = []
            if mood_style is not None and MOOD and not getattr(args, "no_mood", False):
                wt = mood_style.walk_text(MOOD)
                if wt:
                    extras.append(f"walk={wt}")
            opts = mv[4] if len(mv) > 4 and isinstance(mv[4], dict) else {}
            if opts.get("via"):                      # staging points of the one planned move (v39): the seat's front, round furniture
                extras.append("via=" + ";".join(f"{round(x, 2)},{round(z, 2)}" for x, z in opts["via"]))
            for c in chain:
                extras.append(f"then={c}")
            if then_req:
                then_line = translate_only(then_req, IDLE, args, base, key)
                if then_line and then_line != "KEEP":
                    extras.append(f"then={then_line}")
                    print(f"  (then: {then_line})")
                else:
                    print(f"  (could not turn {then_req!r} into a motion; she will only walk there)")
            cmd = " | ".join([cmd] + extras)
            write_seat_hint(args, getattr(world_moves, "LAST_SEAT", None))
            if up_first:
                cmd = f"{up_first} >> A person stands upright. | then={cmd}"
                note = f"stands up first, then {note}"
            print(f"  (move: {note})\n  {cmd}")
            if not args.dry_run:
                write_prompt_file(args.prompt_file, cmd)
            return True
        if MOOD.get("src") == "self":
            # she narrated going somewhere ("*saunters over to the bed*") and Senses reports no such thing: a walk on the spot
            # into the wall would be worse than nothing (a user's request still goes to the model below: he can see the room)
            place = world_moves.named_place(request)
            if place:
                print(f"  no change (she said she goes to the {place}, but Senses reports no '{place}' in the scene; "
                      f"add it to the Senses object list and she will)")
                return True
    write_seat_hint(args, None)      # not a sit on a known seat: no seat height for the freeze-hold
    if not args.no_fast:
        line = fast_path(request, shown)
        if line is not None:
            print("  (fast path: no LLM call)")
    cache = get_cache(args)
    if line is None and cache:
        line = cache.lookup(request, rest)
        if line is not None:
            print("  (remembered from an earlier translation: no LLM call)")
    if line is None:
        try:
            line, err = propose(request, rest, llm)
        except (urllib.error.URLError, OSError) as e:
            explain_connection_error(e, base)
            return False
        if line and cache:
            cache.store(request, rest, line)
    if (not line or line == "KEEP") and not args.no_fast:
        rescued = compose_clauses(request, shown)
        if rescued and rescued != "KEEP":
            print(f"  (the model found nothing usable in the whole request; doing the parts it can: {rescued})")
            line = rescued
    if not line:
        log_failure(args.prompt_file, request, shown, err)
        line = literal_rewrite(request, shown)
        if line:
            print(f"  (the model gave nothing usable ({err}); using the request's own words instead)")
        else:
            print(f"  rejected ({err}); leaving the prompt as it is: {current}")
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
    if mood_style is not None and MOOD and not getattr(args, "no_mood", False):
        styled = mood_style.style_line(line, MOOD)   # after the lifetime: a free walk is one part until @N is added
        if styled != line:
            print(f"  (in her mood, {mood_style.describe(MOOD)}: {styled})")
            line = styled
    line = attach_fallbacks(line)
    print(f"  {line}")
    if not args.dry_run:
        write_prompt_file(args.prompt_file, line)
    return True


def translate_only(request, shown, args, base, key):
    """A validated, timed prompt line for `request` as if she were doing `shown` (fast path, then the cache, then the LLM), or None.
    Used for the part of a request that happens after a walk ("lie on the bed" -> the lying-down line)."""
    rest = resting_state(shown)
    line = None
    if not args.no_fast:
        line = fast_path(request, shown)
    cache = get_cache(args)
    if line is None and cache:
        line = cache.lookup(request, rest)
    if line is None:
        try:
            line, _err = propose(request, rest, make_llm(base, args.model, key, args.temperature))
        except (urllib.error.URLError, OSError):
            line = None
        if line and cache:
            cache.store(request, rest, line)
    if not line or line == "KEEP":
        return line
    if not args.no_lifetime:
        line = apply_lifetime(line, shown, request)
    if mood_style is not None and MOOD and not getattr(args, "no_mood", False):
        line = mood_style.style_line(line, MOOD)
    return attach_fallbacks(line)


def write_wordings(args):
    """List every wording the fast path can produce in wordings.txt beside the prompt file, so the stream can
    pre-encode them at startup and the first request for each one costs no encoding time."""
    try:
        lines = set()
        for v in list(VERIFIED.values()) + list(POSE_DEFAULTS.values()) + [d[2] for d in DANCE_STYLES]:
            if isinstance(v, str):
                lines.update(x.strip() for x in re.split(r">>|@\d+", re.sub(r"\[free\]", "", v)) if x.strip())
        lines.update(["A person stands upright.", "A person walks forward.", "A person dances.",
                      "A person stands up.", "A person stands up from a chair.", "A person sits down.",
                      "A person sits in a chair."])
        out = Path(args.prompt_file).resolve().parent / "wordings.txt"
        out.write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")
        print(f"Wrote {len(lines)} wordings for pre-encoding: {out}")
    except Exception as e:
        print(f"(could not write wordings.txt: {e})")


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
    p.add_argument("--no-cache", action="store_true", help="Do not remember or reuse earlier LLM translations")
    p.add_argument("--clear-cache", action="store_true", help="Forget all remembered translations first")
    p.add_argument("--cache", default=None, help="Where translations are remembered (default: next to the prompt file)")
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
    p.add_argument("--no-idle", action="store_true", help="Turn off ambient idle motions (--watch mode)")
    p.add_argument("--world-file", default=None,
                   help="the scene file VaM-RT Senses writes (default: vamrt_world.json next to the request file); 'come here' and "
                        "'walk to the bed' are planned from it as real distances")
    p.add_argument("--world-right-sign", type=float, default=1.0,
                   help="-1 if she walks to the wrong side on 'come here' (give the stream the same value)")
    p.add_argument("--no-moves", action="store_true", help="never turn requests into typed moves (/go, /walk); walk by seconds instead")
    p.add_argument("--no-mood", action="store_true", help="ignore [mood ...] tags from the scenario (requests are carried out plainly)")
    p.add_argument("--idle-min", type=float, default=35.0, help="Shortest pause between idle motions, seconds (default 35)")
    p.add_argument("--idle-max", type=float, default=95.0, help="Longest pause between idle motions, seconds (default 95)")
    p.add_argument("--idle-allow", default="", help="Idle groups that are normally left out because they travel, e.g. idle.pace")
    p.add_argument("--selftest", action="store_true", help="Test the validation rules (no LLM needed)")
    args = p.parse_args()
    if args.clear_cache and not args.no_cache:
        get_cache(args).clear()
        print("Translation cache emptied.")
    global STYLES_ON, FREEDOM
    STYLES_ON = args.styles
    FREEDOM = not args.strict
    VERIFIED.update(load_verified(args.verified or VERIFIED_FILE))
    if VERIFIED and not args.selftest:
        print("Verified wordings in use: " + ", ".join(sorted(VERIFIED)))
        made_under = load_verified_settings(args.verified or VERIFIED_FILE)
        if made_under:
            print(f"  (verified with the stream running: {made_under})")

    if not args.selftest:
        write_wordings(args)

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
        if not args.world_file:
            args.world_file = os.path.join(os.path.dirname(os.path.abspath(args.watch)), "vamrt_world.json")
        if world_moves is not None:
            print(f"World file (Senses): {args.world_file}  (--no-moves turns typed moves off)")
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
