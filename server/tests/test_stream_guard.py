"""Tests for the duration guard in ardy_stream.py. They need no GPU and no ARDY install.
Run from the server folder:  python tests/test_stream_guard.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import ardy_stream as s  # noqa: E402

bad = 0


def check(name, got, want):
    global bad
    ok = got == want
    bad += not ok
    print(("ok   " if ok else "BAD  ") + name + ("" if ok else f"   got {got!r}, wanted {want!r}"))


CHUNK = 2.0


def run(guard, key, open_ended, speeds):
    """Feed one speed per chunk; return the index (1-based) of the first chunk at which it says 'cut', or None."""
    for i, sp in enumerate(speeds, 1):
        if guard.update(key, open_ended, sp, CHUNK):
            return i
    return None


# a walk that never ends: cut after 60 s = 30 chunks
check("endless walk is cut at 60 s", run(s.RunawayGuard(60), "walk", True, [1.0] * 100), 30)
# the same walk as a TIMED part is never watched (it ends by itself)
check("timed parts are not watched", run(s.RunawayGuard(60), "walk", False, [1.0] * 100), None)
# a pose that settles is never cut, however long it holds
check("a settling pose is never cut", run(s.RunawayGuard(60), "stand", True, [0.5, 0.3, 0.1, 0.04] + [0.01] * 500), None)
# the real hip-wiggle from the log: moving for ~40 s, calming, then fine
check("a wiggle that calms down is not cut", run(s.RunawayGuard(60), "wiggle", True, [0.29] * 20 + [0.05] * 3 + [0.02] * 50), None)
# ... but one that keeps going for over a minute is
check("a wiggle that never calms is cut", run(s.RunawayGuard(60), "wiggle", True, [0.29] * 20 + [0.13] * 40), 30)
# calm chunks reset the clock, so two long moves with a real rest between them are fine
check("a rest resets the clock", run(s.RunawayGuard(60), "x", True, [0.5] * 25 + [0.01] * 3 + [0.5] * 25), None)
# a new prompt starts counting again from zero
g = s.RunawayGuard(60)
run(g, "walk", True, [1.0] * 25)
check("a new prompt resets the clock", run(g, "dance", True, [1.0] * 25), None)
# unknown speed (no information) does not count as movement
check("unknown speed does not count", run(s.RunawayGuard(60), "x", True, [None] * 100), None)
# 0 switches the guard off
check("limit 0 disables the guard", run(s.RunawayGuard(0), "walk", True, [1.0] * 500), None)
# after a cut, resetting lets the fallback pose hold normally
g = s.RunawayGuard(60)
run(g, "walk", True, [1.0] * 40)
g.reset()
check("after reset the fallback pose is not cut", run(g, "stand", True, [0.01] * 200), None)

# timed parts in a plan file can never exceed MAX_PART_SECONDS
plan = s.parse_plan("A person walks forward. @999 >> A person stands upright.", CHUNK, 3)
check("a timed part is clamped to 180 s (90 chunks)", plan[0][1], 90)
plan = s.parse_plan("A person waves. @4 >> A person stands upright.", CHUNK, 3)
check("normal timed parts are untouched", plan[0][1], 2)
check("the last part is the open-ended hold", plan[-1][1], None)

print("\nALL GOOD" if not bad else f"\nFAILURES: {bad}")
sys.exit(1 if bad else 0)
