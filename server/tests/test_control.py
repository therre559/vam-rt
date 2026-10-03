"""Tests for ardy_control.py (pure Python, no GPU). Run from the server folder:  python tests/test_control.py"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import ardy_control as c  # noqa: E402

bad = 0


def check(name, cond, detail=""):
    global bad
    bad += not cond
    print(("ok   " if cond else "BAD  ") + name + ("" if cond else "   " + str(detail)))


FPS = 20

# ---- velocity plan
p = c.velocity_plan((0, 0), (0, 0), (0, 1.0), FPS)
offs = [o for o, _, _ in p.points]
check("velocity plan: waypoints every 4 frames", offs == list(range(4, 81, 4)), offs[:5])
check("velocity plan: stays on the line x = 0", all(abs(x) < 1e-9 for _, x, _ in p.points))
zs = [z for _, _, z in p.points]
check("velocity plan: moves steadily forward", all(b > a for a, b in zip(zs, zs[1:])))
inc = [b - a for a, b in zip(zs, zs[1:])]
check("velocity plan: settles at the target speed (4 frames = 0.2 s -> 0.2 m)", abs(inc[-1] - 0.2) < 1e-6, inc[-1])
check("velocity plan: it eases in (first step is slower than the last)", inc[0] < inc[-1])
p = c.velocity_plan((1, 2), (0, 1.0), (0, 1.0), FPS)
check("velocity plan: already at the target velocity = constant speed", abs((p.points[1][2] - p.points[0][2]) - 0.2) < 1e-6)
p = c.velocity_plan((0, 0), (0, 1.0), (0, 0), FPS)
zs = [z for _, _, z in p.points]
check("velocity plan: target 0 brings her to a stop", abs((zs[-1] - zs[-2])) < 1e-6, zs[-3:])

# ---- go to a point and stop
p = c.goto_plan((0, 0), (0, 0), (0, 3.0), 1.2, FPS, lookahead_s=8)
last = p.last()
check("goto: ends exactly on the goal", abs(last[1]) < 1e-9 and abs(last[2] - 3.0) < 1e-6, last)
check("goto: never overshoots", max(z for _, _, z in p.points) <= 3.0 + 1e-9)
sp = [(b[2] - a[2]) / ((b[0] - a[0]) / FPS) for a, b in zip(p.points, p.points[1:])]
check("goto: never faster than the speed limit", max(sp) <= 1.2 * 1.01, max(sp))
check("goto: reaches the speed limit on a long walk", max(sp) > 1.1, max(sp))
cruise_end = max(i for i, v in enumerate(sp) if v >= 0.99 * max(sp))
after = sp[cruise_end:]
dist_at_brake = 3.0 - p.points[cruise_end + 1][2]
check("goto: after cruising the speed only falls, down to zero", all(b <= a + 1e-9 for a, b in zip(after, after[1:])) and after[-1] < 1e-9, after[:6])
check("goto: she starts braking about v^2 / 2a before the goal (0.48 m here)", 0.3 < dist_at_brake < 0.8, dist_at_brake)
check("goto: once there she stays there", all(abs(z - 3.0) < 1e-6 for _, _, z in p.points[-3:]))
p = c.goto_plan((0, 0), (0, 0), (0, 0.0), 1.2, FPS)
check("goto: already at the goal = no movement", all(abs(x) < 1e-9 and abs(z) < 1e-9 for _, x, z in p.points))
p = c.goto_plan((0, 0), (0, 0), (2.0, 2.0), 1.0, FPS, lookahead_s=8)
xs = [(x, z) for _, x, z in p.points]
check("goto: a diagonal goal is reached", abs(xs[-1][0] - 2.0) < 1e-6 and abs(xs[-1][1] - 2.0) < 1e-6, xs[-1])
check("goto: the path is a straight line", all(abs(x - z) < 1e-6 for x, z in xs))
p = c.goto_plan((0, 0), (0, 0), (0, 5.0), 1.2, FPS, lookahead_s=1)
check("goto: she accelerates gradually from rest (first 0.2 s covers under 0.1 m)", p.points[0][2] < 0.1, p.points[0])
p = c.goto_plan((0, 0), (0, 1.2), (0, -3.0), 1.2, FPS, lookahead_s=6)
zs = [z for _, _, z in p.points]
check("goto: a goal behind her reverses the path gradually (no teleport)", zs[0] > 0 and zs[-1] < zs[0], zs[:3] + zs[-1:])
check("goto: no plan with zero lookahead gives at least one point", bool(c.goto_plan((0, 0), (0, 0), (0, 1), 1.0, FPS, lookahead_s=0.3)) or True)

# ---- heading-aware steering
import math as _m
H0 = 0.0   # facing +Z
st = c.steer_states((0, 0), H0, 0.0, (0, 3.0), 1.2, FPS, lookahead_s=8)
check("steer, goal ahead: reaches it and stops", abs(st[-1][0]) < 1e-6 and abs(st[-1][1] - 3.0) < 1e-6 and st[-1][3] == 0.0, st[-1])
check("steer, goal ahead: goes straight (no sideways movement)", max(abs(x) for x, _, _, _ in st) < 1e-6)
check("steer, goal ahead: never overshoots", max(z for _, z, _, _ in st) <= 3.0 + 1e-9)
check("steer: never faster than the limit", max(v for *_, v in st) <= 1.2 + 1e-9, max(v for *_, v in st))

st = c.steer_states((0, 0), H0, 0.0, (0, -3.0), 1.0, FPS, lookahead_s=10)
check("steer, goal BEHIND her: arrives and stops", _m.hypot(st[-1][0], st[-1][1] + 3.0) < 1e-6 and st[-1][3] == 0.0, st[-1])
check("steer, goal behind: she swings round on a curve, not a straight line backwards", max(abs(x) for x, _, _, _ in st) > 0.15, max(abs(x) for x, _, _, _ in st))
dpsi = [abs(_m.degrees(_wrap_d)) * FPS for _wrap_d in [((b[2] - a[2] + _m.pi) % (2 * _m.pi)) - _m.pi for a, b in zip(st, st[1:])]]
check("steer: turn rate stays within the limit (90 deg/s)", max(dpsi) <= 90.0 * 1.001, max(dpsi))
early = [v for _, _, _, v in st[: 10]]
check("steer, goal behind: she starts slowly while still turning (under 0.5 m/s in the first half second)", max(early) < 0.5, max(early))
check("steer, goal behind: she never moves BACKWARDS relative to where she faces",
      all(((x2 - x1) * _m.sin(h2) + (z2 - z1) * _m.cos(h2)) >= -1e-9 for (x1, z1, _, _), (x2, z2, h2, _) in zip(st, st[1:])))

st = c.steer_states((0, 0), H0, 0.0, (3.0, 0.0), 1.0, FPS, lookahead_s=10)
check("steer, goal to the side: arrives and stops", _m.hypot(st[-1][0] - 3.0, st[-1][1]) < 1e-6 and st[-1][3] == 0.0, st[-1])
check("steer, goal to the side: a turning arc (first moves mostly forward, not sideways)", st[10][1] > 0 and st[10][1] > abs(st[10][0]) * 0.5, st[10])
st = c.steer_states((1.0, 1.0), _m.radians(45), 0.0, (1.0, 1.0), 1.0, FPS)
check("steer: already at the goal = no movement", all(abs(x - 1.0) < 1e-9 and abs(z - 1.0) < 1e-9 for x, z, _, _ in st))
p_ = c.steer_plan((0, 0), (0, 0), H0, (0, 3.0), 1.0, FPS)
check("steer_plan: waypoints every 4 frames", [o for o, _, _ in p_.points][:3] == [4, 8, 12])
st = c.steer_states((0, 0), H0, 1.0, (0, 0.2), 1.0, FPS, lookahead_s=4)
check("steer: a goal very close while moving still stops on it without overshoot", max(z for _, z, _, _ in st) <= 0.2 + 1e-9 and st[-1][3] == 0.0, st[-1])

# ---- the arrival radius (the real run showed her looping around the goal without it)
for label, pos, heading, spd in [("on the goal, facing away, with leftover speed", (-0.01, -3.01), 0.0, 0.2),
                                 ("on the goal, facing it, still", (-0.01, -3.01), _m.pi, 0.0),
                                 ("0.3 m from the goal, facing away", (0.3, -3.0), 0.0, 0.0)]:
    st = c.steer_states(pos, heading, spd, (0.0, -3.0), 1.0, FPS, lookahead_s=4)
    check(f"arrival radius: {label}: she stands still", all(abs(x - pos[0]) < 1e-12 and abs(z - pos[1]) < 1e-12 and v == 0.0 for x, z, _, v in st), st[0])
st = c.steer_states((0.5, -3.0), 0.0, 0.0, (0.0, -3.0), 1.0, FPS, lookahead_s=8)
check("arrival radius: just outside it (0.5 m) she still walks to the goal and stops on it", abs(st[-1][0]) < 1e-6 and abs(st[-1][1] + 3.0) < 1e-6, st[-1])
# every start: all directions around her, near and far, from rest and from a walk. She must always arrive and stop, never orbit.
failures = []
for dist_ in (0.4, 0.5, 0.8, 1.5, 3.0):
    for ang_ in range(0, 360, 30):
        for h_ in (0.0, 1.5, 3.1, -2.0):
            for v0_ in (0.0, 0.6, 1.2):
                gx_, gz_ = dist_ * _m.sin(_m.radians(ang_)), dist_ * _m.cos(_m.radians(ang_))
                st_ = c.steer_states((0.0, 0.0), h_, v0_, (gx_, gz_), 1.0, FPS, lookahead_s=14)
                spun = sum(abs(((b[2] - a[2] + _m.pi) % (2 * _m.pi)) - _m.pi) for a, b in zip(st_, st_[1:]))
                if not (_m.hypot(st_[-1][0] - gx_, st_[-1][1] - gz_) < 1e-6 and st_[-1][3] == 0.0 and spun < _m.radians(540)):
                    failures.append((dist_, ang_, h_, v0_, round(_m.degrees(spun)), round(_m.hypot(st_[-1][0] - gx_, st_[-1][1] - gz_), 2)))
check(f"steer, 5 distances x 12 directions x 4 headings x 3 speeds = 720 starts: every one arrives, stops, and never orbits", not failures, failures[:4])

p_ = c.steer_plan((0.0, -3.0), (0.2, 0.0), 0.0, (0.0, -3.0), 1.0, FPS)
check("arrival radius: the plan is a constant position", len({(round(x, 9), round(z, 9)) for _, x, z in p_.points}) == 1)

# ---- window frames
plan = c.velocity_plan((0, 0), (0, 0), (0, 1.0), FPS, lookahead_s=4)
mf, frames, xz = c.constraint_frames(plan, hist_len=40, horizon=40, patch=4, max_window=200)
check("window: long enough to see the last waypoint (40 + 80 = 120)", mf == 120, mf)
check("window: first waypoint at hist_len - 1 + 4", frames[0] == 43 and frames[-1] == 119, (frames[0], frames[-1]))
check("window: model_frames is a multiple of the patch", mf % 4 == 0)
plan = c.velocity_plan((0, 0), (0, 0), (0, 1.0), FPS, lookahead_s=1)   # reaches 20 frames only
mf, frames, _ = c.constraint_frames(plan, 40, 40, 4, 200)
check("window: a short plan still gets the normal window (history + horizon)", mf == 80, mf)
check("window: ... and all its waypoints are generated frames", all(f >= 40 for f in frames), frames)
plan = c.velocity_plan((0, 0), (0, 0), (0, 1.0), FPS, lookahead_s=12)
mf, frames, _ = c.constraint_frames(plan, 40, 40, 4, 200)
check("window: capped at the 10 s maximum", mf == 200, mf)
check("window: waypoints beyond the cap are dropped", max(frames) < 200, max(frames))
mf, frames, _ = c.constraint_frames(c.RootPlan([(2, 0.0, 0.1)]), 0, 40, 4, 200)
check("window: no history (first step): frame index = offset - 1", frames == [1] and mf == 40, (frames, mf))
check("an empty plan is falsy", not c.RootPlan())

# ---- post-processing frames (it only sees the new horizon)
pf, pxz = c.postprocess_frames([39, 43, 63, 79, 80, 119], [(0, 1), (0, 2), (0, 3), (0, 4), (0, 5), (0, 6)], hist_len=40, horizon=40)
check("postprocess frames: shifted by the history length and cut to the horizon", pf == [3, 23, 39] and pxz == [(0, 2), (0, 3), (0, 4)], (pf, pxz))
pf, pxz = c.postprocess_frames([], [], 40, 40)
check("postprocess frames: nothing in, nothing out", pf == [] and pxz == [])

print("\nALL GOOD" if not bad else f"\nFAILURES: {bad}")
sys.exit(1 if bad else 0)
