"""Ambient idle life: small things she does by herself while nothing is being asked of her.

When she has been standing quietly for a while, one of the idle wordings you verified in the motion lab (every
verified_prompts.json key that starts with "idle.") is played for a few seconds, then she goes back to standing.
Gaps between them are irregular and the same few never repeat: the last four are avoided, and a group that has
been played recently is less likely until it has been absent for a while.

What this does NOT do: it never chooses what she says or does in reply to you. It only fills silence. Any request
(from Voxta, the prompt file, or you) ends an idle motion at once and holds the next one off for a while.

The module touches only the prompt file. It does not import the prompter or the stream, so it can be tested
without a GPU (tests/test_idle_life.py).
"""
import random
import re
import time

IDLE_POSE = "A person stands upright."

# how often each verified idle group comes up (relative) and how long it plays (seconds) before she stands again.
# Anything not listed here counts as weight 1, 4 seconds. The quiet ones (a nod, a look, a head tilt, a shoulder roll) carry
# most of the weight; the busy ones (gesturing, a stretch, fixing her hair, crossing her arms) are kept rare, so a quiet
# evening does not look like she is performing. A new "idle.<name>" in verified_prompts.json joins at weight 1 / 4 s.
GROUPS = {
    "idle.nod_slow":     (1.5, 3),
    "idle.listen":       (1.5, 4),
    "idle.glance_back":  (1.3, 3),
    "idle.look":         (1.5, 4),
    "idle.look_around":  (1.3, 4),
    "idle.shoulders":    (1.2, 3),
    "idle.shrug_tilt":   (0.9, 3),
    "idle.talk_hands":   (0.6, 4),
    "idle.hair":         (0.6, 3),
    "idle.stretch":      (0.4, 4),
    "idle.arms_cross":   (0.6, 4),
}
AVOID_LAST = 4
# groups that move her through the room: left out unless you list them in `allow`
TRAVELS = {"idle.pace"}

_AT_PART = re.compile(r"@\s*(\d+(?:\.\d+)?)")
_FREE_TAG = re.compile(r"\[\s*free\s*\]", re.I)


def plan_seconds(line):
    """Seconds taken by the timed (non-final) parts of a prompt line: 'A @4 >> B' -> 4."""
    parts = [p for p in _FREE_TAG.sub("", line or "").split(">>")]
    return sum(float(m.group(1)) for p in parts[:-1] for m in [_AT_PART.search(p)] if m)


def ends_standing(line):
    """True if the line's last part is the plain standing pose (so nothing is being held or acted out)."""
    last = _FREE_TAG.sub("", line or "").split(">>")[-1]
    last = _AT_PART.sub("", last).split("??")[0].strip()
    return last == IDLE_POSE


class IdleLife:
    def __init__(self, read_line, write_line, verified, validate=None, min_gap=35.0, max_gap=95.0, quiet=8.0,
                 margin=4.0, allow=(), rng=None, log=print, weight=None):
        self.read_line = read_line      # () -> the current prompt line
        self.write_line = write_line    # (line) -> None
        self.verified = verified        # dict, shared with the prompter: key -> wording
        self.validate = validate        # (line) -> (line or None, error); the prompter's own rules
        self.min_gap, self.max_gap, self.quiet, self.margin = min_gap, max_gap, quiet, margin
        self.allow = set(allow)
        self.weight = weight            # optional (key) -> multiplier on the group's weight (mood_style: how she feels right now)
        self.rng = rng or random.Random()
        self.log = log
        self.seen_line = None           # what the file held when we last looked
        self.seen_at = 0.0              # when it last changed (not counting our own writes)
        self.ours = None                # the line we wrote last
        self.ours_end = 0.0             # when that idle motion is over
        self.next_at = None
        self.recent = []                # last idle keys played
        self.played = 0

    # ------------------------------------------------------------------ choosing
    def candidates(self):
        out = []
        for key, wording in self.verified.items():
            if not key.startswith("idle.") or not wording:
                continue
            if key in TRAVELS and key not in self.allow:
                continue
            weight, secs = GROUPS.get(key, (1.0, 4))
            if self.weight is not None:
                try:
                    weight *= float(self.weight(key))
                except Exception:
                    pass
            if weight > 0:
                out.append((key, wording, weight, secs))
        return out

    def pick(self):
        cands = self.candidates()
        if not cands:
            return None
        # avoid the last few; with a small menu, relax to the last two, then the last one
        fresh = []
        for n in (AVOID_LAST, 2, 1):
            fresh = [c for c in cands if c[0] not in self.recent[-n:]]
            if fresh:
                break
        fresh = fresh or cands
        total = sum(c[2] for c in fresh)
        r = self.rng.uniform(0, total)
        for c in fresh:
            r -= c[2]
            if r <= 0:
                return c
        return fresh[-1]

    def compose(self, wording, secs):
        line = f"{wording.strip()} @{secs} >> {IDLE_POSE}"
        if self.validate:
            checked, _err = self.validate(line)
            return checked
        return line

    # ------------------------------------------------------------------ the clock
    def _gap(self):
        return self.rng.uniform(self.min_gap, self.max_gap)

    def note_activity(self, now=None):
        """Something other than us asked for movement: hold idle life off for a while."""
        now = time.monotonic() if now is None else now
        self.seen_at = now
        self.next_at = now + self.quiet + self.rng.uniform(2.0, 8.0)

    def interrupt(self, now=None):
        """A request has arrived. If an idle motion is still playing, end it right now (she stands, and the request,
        if it changes anything, follows a moment later)."""
        now = time.monotonic() if now is None else now
        busy = self.ours is not None and now < self.ours_end and self.read_line() == self.ours
        if busy:
            self.write_line(IDLE_POSE)
            self.log("  (idle: stopped, a request came in)")
        self.ours = None
        self.note_activity(now)
        return busy

    def tick(self, now=None):
        """Call a few times a second. Returns the idle key it just started, or None."""
        now = time.monotonic() if now is None else now
        line = self.read_line()
        if line != self.seen_line:
            if line == self.ours:
                self.seen_line = line                  # our own write
            else:
                self.seen_line = line                  # someone else wrote it: that is activity
                self.ours = None
                self.note_activity(now)
        if self.next_at is None:
            self.next_at = now + self.quiet + self._gap()
            return None
        if now < self.next_at or now < self.ours_end:
            return None
        # eligible only when she is plainly standing and whatever was asked has played out
        if not ends_standing(line):
            return None
        if self.ours is None and now - self.seen_at < plan_seconds(line) + self.margin + self.quiet:
            return None
        choice = self.pick()
        if choice is None:
            self.next_at = now + 60.0                  # nothing verified: look again in a minute
            return None
        key, wording, _w, secs = choice
        new = self.compose(wording, secs)
        if not new:
            self.recent.append(key)                    # unusable wording: skip it for now
            self.next_at = now + 5.0
            return None
        self.write_line(new)
        self.ours = new
        self.seen_line = new
        self.ours_end = now + secs + self.margin
        self.next_at = self.ours_end + self._gap()
        self.recent = (self.recent + [key])[-6:]
        self.played += 1
        self.log(f"  (idle: {wording.rstrip('.')})")
        return key
