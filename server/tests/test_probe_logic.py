"""Tests the probe's closed-loop logic and its body metrics with FAKE characters (no GPU, no ARDY):
 - a good walker follows each plan perfectly AND faces where she travels
 - a moonwalker follows the same plans perfectly but keeps facing +Z (walks backwards / sidesteps)
The probe must tell them apart. Whether the real model walks naturally is what constraint_probe.py measures.
Run from the server folder:  python tests/test_probe_logic.py"""
import math
import os
import re
import sys
import tempfile
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import constraint_probe as cp  # noqa: E402

bad = 0


def check(name, cond, detail=""):
    global bad
    bad += not cond
    print(("ok   " if cond else "BAD  ") + name + ("" if cond else "   " + str(detail)))


class Args:
    speed = 1.0
    seconds = 14


class FakeStreamer:
    fps, horizon, history_frames = 20, 40, 40
    model = SimpleNamespace(skeleton=SimpleNamespace(bone_index={"LeftUpLeg": 0, "RightUpLeg": 1, "LeftFoot": 2, "RightFoot": 3}))

    def __init__(self, face_travel=True):
        self.face_travel = face_travel
        self.reset()

    def reset(self):
        self.x = self.z = self.vx = self.vz = 0.0
        self.face = (0.0, 1.0)
        self.started = False

    def root_state(self):
        return (self.x, self.z, self.vx, self.vz) if self.started else None

    def begin_chunk(self, hold):
        pass

    def end_chunk(self, *a):
        pass

    def step(self, prompt, plan=None):
        pts = [(0, self.x, self.z)] + (list(plan.points) if plan else [])
        roots, joints = [], []
        for k in range(1, self.horizon + 1):
            nx, nz = self.x, self.z
            if plan:
                for (o0, x0, z0), (o1, x1, z1) in zip(pts, pts[1:]):
                    if o0 <= k <= o1:
                        a = (k - o0) / (o1 - o0)
                        nx, nz = x0 + a * (x1 - x0), z0 + a * (z1 - z0)
                        break
            else:
                nz = self.z + 1.2 / self.fps
            self.vx, self.vz = (nx - self.x) * self.fps, (nz - self.z) * self.fps
            self.x, self.z = nx, nz
            sp = math.hypot(self.vx, self.vz)
            if self.face_travel and sp > 0.2:
                self.face = (self.vx / sp, self.vz / sp)
            right = (self.face[1], -self.face[0])
            roots.append([nx, 0.9, nz])
            joints.append([[nx - right[0] * 0.1, 0.9, nz - right[1] * 0.1], [nx + right[0] * 0.1, 0.9, nz + right[1] * 0.1],
                           [nx - right[0] * 0.1, 0.0, nz - right[1] * 0.1], [nx + right[0] * 0.1, 0.0, nz + right[1] * 0.1]])
        self.started = True
        return {"root_positions": [roots], "posed_joints": [joints]}, {"root_positions", "posed_joints"}


def num(text, pattern):
    m = re.search(pattern, text)
    return float(m.group(1)) if m else None


def study(face_travel):
    os.chdir(tempfile.mkdtemp())
    fs, res = FakeStreamer(face_travel), {}
    for scn in cp.ALL:
        full, log, extra = cp.run(fs, scn, Args)
        res[scn] = cp.summarize(scn, full, extra, fs.fps)
    return res


good, moon = study(True), study(False)

# ---- the closed loop (same for both walkers: the root follows the plans perfectly)
for name, res in (("good walker", good), ("moonwalker", moon)):
    check(f"{name}: baseline walks about 1.2 m/s * 14 s", 15 < num(res["baseline"]["goal"], r"^([0-9.]+) m") < 18, res["baseline"]["goal"])
    check(f"{name}: forward goes straight", num(res["forward"]["goal"], r"drift ([0-9.]+)") < 0.01, res["forward"]["goal"])
    check(f"{name}: forward covers about 1 m/s * 14 s", 12 < num(res["forward"]["goal"], r"^([0-9.]+) m") < 14.5, res["forward"]["goal"])
    for scn in ("goto", "stop", "turn", "side"):
        check(f"{name}: {scn} arrives within 0.3 m", num(res[scn]["goal"], r"error ([0-9.]+)") < 0.3, res[scn]["goal"])
        check(f"{name}: {scn} ends standing still", num(res[scn]["speed"], r"at the end ([0-9.]+)") < 0.1, res[scn]["speed"])
    check(f"{name}: goto stays near the straight line", num(res["goto"]["goal"], r"max ([0-9.]+) m off") < 0.3, res["goto"]["goal"])

# ---- the steered scenarios (heading-aware plans)
for scn in ("turn2", "turn3", "side2"):
    check(f"good walker: {scn} arrives within 0.3 m", num(good[scn]["goal"], r"error ([0-9.]+)") < 0.3, good[scn]["goal"])
    check(f"good walker: {scn} ends standing still", num(good[scn]["speed"], r"at the end ([0-9.]+)") < 0.1, good[scn]["speed"])
    check(f"good walker: {scn} faces where she goes (median under 30 deg)", num(good[scn]["facing vs travel"], r"median ([0-9]+)") < 30, good[scn])
check("steered turn: she actually turned around (about 180 deg of heading change)", num(good["turn2"]["turning"], r"^([0-9]+)") > 150, good["turn2"]["turning"])
check("the prompt switches to 'turns around' only in turn3 and only while misaligned",
      cp.decide("turn3", (0, 0, 0, 0), 1.0, 20, 0.0)[0] == cp.TURN_TEXT and cp.decide("turn2", (0, 0, 0, 0), 1.0, 20, 0.0)[0] == cp.WALK
      and cp.decide("turn3", (0, -1.0, 0, -1), 1.0, 20, math.pi)[0] == cp.WALK, "decide()")

# ---- the body metrics must tell a real walker from a moonwalker
check("good walker, forward: faces where she goes (median under 10 deg)", num(good["forward"]["facing vs travel"], r"median ([0-9]+)") < 10, good["forward"])
check("good walker, turn: turns around, so the goal behind her is not walked backwards",
      num(good["turn"]["facing vs travel"], r"median ([0-9]+)") < 20 and num(good["turn"]["turning"], r"^([0-9]+)") > 150, good["turn"])
check("moonwalker, turn: caught walking BACKWARDS (about 180 deg)", num(moon["turn"]["facing vs travel"], r"median ([0-9]+)") > 150, moon["turn"])
check("moonwalker, turn: never turned", num(moon["turn"]["turning"], r"^([0-9]+)") < 10, moon["turn"]["turning"])
check("moonwalker, side: caught SIDESTEPPING (about 90 deg)", 80 < num(moon["side"]["facing vs travel"], r"median ([0-9]+)") < 100, moon["side"])
check("moonwalker, forward: still fine (the one case where the root path is also the facing)",
      num(moon["forward"]["facing vs travel"], r"median ([0-9]+)") < 10, moon["forward"])
check("foot skate is reported", "m/s while planted" in good["goto"]["foot skate"] or "no planted" in good["goto"]["foot skate"], good["goto"])
check("a CSV is written per scenario", all(os.path.exists(f"probe_{s}.csv") for s in cp.ALL))

print("\nALL GOOD" if not bad else f"\nFAILURES: {bad}")
sys.exit(1 if bad else 0)
