"""Tests for gait_metrics.py with synthetic walkers (no GPU). Run from the server folder:  python tests/test_gait_metrics.py"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import gait_metrics as g  # noqa: E402

bad = 0


def check(name, cond, detail=""):
    global bad
    bad += not cond
    print(("ok   " if cond else "BAD  ") + name + ("" if cond else "   " + str(detail)))


FPS = 20
N = 60


def walker(heading_deg, travel_deg, speed=1.0, swap=False):
    """A pelvis that faces `heading_deg` (0 = +Z, 90 = +X) moving in the direction `travel_deg`. Hips 0.2 m apart."""
    h, t = math.radians(heading_deg), math.radians(travel_deg)
    fwd = (math.sin(h), math.cos(h))
    right = (fwd[1], -fwd[0])                    # a perpendicular of the facing direction
    root, left, rightp = [], [], []
    for i in range(N):
        x, z = math.sin(t) * speed * i / FPS, math.cos(t) * speed * i / FPS
        root.append((x, z))
        left.append((x - right[0] * 0.1, z - right[1] * 0.1))
        rightp.append((x + right[0] * 0.1, z + right[1] * 0.1))
    return (rightp, left, root) if swap else (left, rightp, root)


def med(heading, travel, swap=False):
    left, right, root = walker(heading, travel, swap=swap)
    fw = g.facing_vectors(left, right)
    return g.percentile(g.misalignment_deg(fw, root, FPS), 0.5)


check("walking forward: facing and travel agree (about 0 deg)", med(0, 0) < 5, med(0, 0))
check("walking backwards: about 180 deg", med(0, 180) > 175, med(0, 180))
check("sidestepping: about 90 deg", 85 < med(0, 90) < 95, med(0, 90))
check("works with the hips listed the other way round (handedness)", med(0, 0, swap=True) < 5, med(0, 0, swap=True))
check("backwards is still detected with swapped hips", med(0, 180, swap=True) > 175)
left, right, root = walker(0, 0, speed=0.1)
check("standing almost still gives no samples (below the speed threshold)",
      g.misalignment_deg(g.facing_vectors(left, right), root, FPS) == [])

# turning
def spinning(deg_total, seconds=2.0, pad=2.0):
    """Steady for `pad` s, then turns `deg_total` degrees over `seconds`, then steady again (a turn in the middle of a clip)."""
    n, k = int(seconds * FPS), int(pad * FPS)
    fw = []
    for i in range(-k, n + k + 1):
        a = math.radians(deg_total * min(max(i, 0), n) / n)
        fw.append((math.sin(a), math.cos(a)))
    return fw


tot, fast = g.turn_stats(spinning(90), FPS)
check("a 90 degree turn over 2 s: total about 90", 88 < tot < 92, tot)
check("... at about 45 degrees per second", 43 < fast < 47, fast)
tot, fast = g.turn_stats(spinning(-180, 2), FPS)
check("turning the other way counts the same (total 180)", 178 < tot < 182, tot)
tot, _ = g.turn_stats([(0.0, 1.0)] * 40, FPS)
check("not turning at all = 0", tot < 1e-6, tot)
tot, _ = g.turn_stats(spinning(350, 3), FPS)
check("wrapping past 180 degrees does not break the sum", 345 < tot < 355, tot)

# pelvis sway must not count as turning
sway = [(math.sin(math.radians(12 * math.sin(2 * math.pi * 1.0 * i / FPS))), math.cos(math.radians(12 * math.sin(2 * math.pi * 1.0 * i / FPS))))
        for i in range(8 * FPS)]
raw_total = sum(abs(math.degrees((math.atan2(b[0], b[1]) - math.atan2(a[0], a[1]) + math.pi) % (2 * math.pi) - math.pi)) for a, b in zip(sway, sway[1:]))
tot, _ = g.turn_stats(sway, FPS)
check("a straight walk with a 12 degree stride sway: smoothed turning is small", tot < raw_total * 0.25, (tot, raw_total))

# foot skate
planted = [(0.0, 0.0, 0.0)] * 20
check("a planted foot does not skate (0 m/s)", g.foot_skate(planted, FPS) < 1e-9)
sliding = [(0.5 * i / FPS, 0.0, 0.0) for i in range(20)]
check("a foot sliding at 0.5 m/s is reported as 0.5", abs(g.foot_skate(sliding, FPS) - 0.5) < 1e-6, g.foot_skate(sliding, FPS))
# a real step cycle: planted for 10 frames, then swings (lifted) for 10 frames
cycle = [(0.0, 0.0, 0.0)] * 10 + [(0.1 * k, 0.15, 0.1 * k) for k in range(10)]
check("a swinging foot is not counted (only planted frames)", g.foot_skate(cycle * 3, FPS) < 0.2, g.foot_skate(cycle * 3, FPS))
check("a foot that is only ever on the ground for a single frame gives None (no pair of planted frames)",
      g.foot_skate([(0, 0.0, 0), (1, 0.5, 1), (2, 1.0, 2), (3, 1.5, 3)], FPS, plant_height=0.01) is None)
check("percentile of a short list", g.percentile([1, 2, 3, 4, 5], 0.5) == 3 and g.percentile([], 0.5) is None)

print("\nALL GOOD" if not bad else f"\nFAILURES: {bad}")
sys.exit(1 if bad else 0)
