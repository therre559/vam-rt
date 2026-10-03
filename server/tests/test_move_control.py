"""Tests for move_control.py with simulated bodies (no GPU). Run from the server folder:  python tests/test_move_control.py"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import move_control as mc  # noqa: E402

bad = 0


def check(name, cond, detail=""):
    global bad
    bad += not cond
    print(("ok   " if cond else "BAD  ") + name + ("" if cond else "   " + str(detail)))


FPS, CHUNK = 20, 2.0


class Body:
    """Follows the first 40 frames of every plan exactly; turns to face the way it travels (like the real model with a steered plan)."""
    def __init__(self, stuck=False):
        self.x = self.z = self.psi = self.vx = self.vz = 0.0
        self.stuck = stuck

    def pose(self):
        return (self.x, self.z, self.psi, self.vx, self.vz)

    def apply(self, plan):
        if self.stuck or not plan:
            self.vx = self.vz = 0.0
            return
        pts = [(0, self.x, self.z)] + list(plan.points)
        for k in range(1, 41):
            nx, nz = self.x, self.z
            for (o0, x0, z0), (o1, x1, z1) in zip(pts, pts[1:]):
                if o0 <= k <= o1:
                    a = (k - o0) / (o1 - o0)
                    nx, nz = x0 + a * (x1 - x0), z0 + a * (z1 - z0)
                    break
            self.vx, self.vz = (nx - self.x) * FPS, (nz - self.z) * FPS
            if math.hypot(self.vx, self.vz) > 0.2:
                self.psi = math.atan2(self.vx, self.vz)
            self.x, self.z = nx, nz


def run(driver, body, chunks=40, t0=100.0, hook=None):
    """Drive until the driver goes idle. Returns (chunks used, list of (prompt, note))."""
    log, now = [], t0
    for c in range(chunks):
        if hook:
            hook(c, now)
        r = driver.next_chunk(body.pose(), now)
        if r is None:
            return c, log
        log.append((r[0], r[2]))
        body.apply(r[1])
        now += CHUNK
    return chunks, log


def new(**kw):
    return mc.MoveDriver(FPS, **kw)


# ---- walk
d, b = new(), Body()
ok, msg = d.walk(b.pose(), 3.0, 100.0)
check("walk 3: accepted", ok, msg)
n, log = run(d, b)
check("walk 3: she ends about 3 m ahead (within the 25 cm done radius)", abs(b.z - 3.0) < 0.26 and abs(b.x) < 0.1, (b.x, b.z))
check("walk 3: she ends standing still", math.hypot(b.vx, b.vz) < 0.1, (b.vx, b.vz))
check("walk 3: the driver hands control back by itself", not d.active and n < 12, n)
check("walk 3: she walks first, then stands", log[0][0] == mc.WALK and log[-1][0] == mc.STAND, log)
check("walk 3: it settles for the set number of chunks before going idle", sum(1 for p, nt in log if "settled" in nt) == 2, log)

# ---- goto (and the facing follows the path)
d, b = new(), Body()
ok, _ = d.goto(b.pose(), (2.0, 4.0), 100.0)
run(d, b)
check("goto (2, 4): arrives within 25 cm", math.hypot(b.x - 2.0, b.z - 4.0) < 0.26, (b.x, b.z))
d, b = new(), Body()
d.goto(b.pose(), (0.0, -3.0), 100.0)
run(d, b)
check("goto a point BEHIND her: arrives within 25 cm", math.hypot(b.x, b.z + 3.0) < 0.26, (b.x, b.z))
check("... and she ends facing the way she travelled (about -Z)", abs(abs(b.psi) - math.pi) < 0.5, b.psi)

# ---- home from far away
d, b = new(), Body()
b.x, b.z = 3.0, 4.0
ok, msg = d.goto(b.pose(), (0.0, 0.0), 100.0, "home")
check("home from (3, 4): 5 m is within the default limit", ok, msg)
run(d, b)
check("home: she gets back to the origin (within 25 cm)", math.hypot(b.x, b.z) < 0.26, (b.x, b.z))

# ---- relative moves use her heading
d, b = new(), Body()
b.psi = math.pi / 2           # facing +X
ok, _ = d.go_relative(b.pose(), 2.0, 1.0, 100.0)    # 2 ahead (+X), 1 to her right (-Z when facing +X)
run(d, b)
check("go 2 ahead 1 right while facing +X: ends near (2, -1)", abs(b.x - 2.0) < 0.26 and abs(b.z + 1.0) < 0.26, (b.x, b.z))

# ---- limits and refusals
d, b = new(max_move=8.0), Body()
ok, msg = d.walk(b.pose(), 9.0, 100.0)
check("a move farther than the limit is refused, with the reason", (not ok) and "limit" in msg and not d.active, msg)
ok, msg = new(max_move=0).walk(b.pose(), 1.0, 100.0)
check("--max-move 0 switches moves off", (not ok) and "off" in msg, msg)
ok, msg = new().goto(b.pose(), (0.2, 0.0), 100.0)
check("a goal she is already within 25 cm of is refused", (not ok) and "already" in msg, msg)
ok, msg = new().goto(b.pose(), (float("nan"), 1.0), 100.0)
check("a goal that is not a number is refused", not ok, msg)
d = new()
check("the speed is clamped to a safe range", d.set_speed(5.0) == 1.6 and d.set_speed(0.1) == 0.5)

# ---- speed is respected
d, b = new(), Body()
d.set_speed(0.8)
d.walk(b.pose(), 6.0, 100.0)
speeds = []
now = 100.0
for _ in range(20):
    r = d.next_chunk(b.pose(), now)
    if r is None:
        break
    b.apply(r[1]); speeds.append(math.hypot(b.vx, b.vz)); now += CHUNK
check("the walking speed setting is respected (never over 0.8 m/s + a little)", max(speeds) < 0.9, max(speeds))

# ---- stop
d, b = new(), Body()
d.walk(b.pose(), 8.0, 100.0)
b.apply(d.next_chunk(b.pose(), 100.0)[1])          # one chunk walking
b.apply(d.next_chunk(b.pose(), 102.0)[1])          # a second one: now moving at speed
v_before = math.hypot(b.vx, b.vz)
z_before = b.z
ok, msg = d.stop(b.pose(), 104.0)
check("stop: accepted while moving", ok and v_before > 0.8, (ok, v_before))
n, log = run(d, b, t0=104.0)
check("stop: she brakes and stands still", math.hypot(b.vx, b.vz) < 0.1, (b.vx, b.vz))
check("stop: she stops close by, about v^2 / 2a (0.5 m) beyond where she was, nowhere near the 8 m goal", b.z - z_before < 1.5 and not d.active, (b.z - z_before, d.active))
check("stop with nothing to stop is refused", not new().stop(Body().pose(), 100.0)[0])

# ---- she cannot get there: it must still end
d, b = new(), Body(stuck=True)
d.walk(b.pose(), 3.0, 100.0)
n, log = run(d, b, chunks=60)
check("a body that never moves: the driver gives up and hands control back (never runs forever)", not d.active and n < 30, n)
check("... after trying to brake first", any("braking" in nt for p, nt in log), [nt for p, nt in log][:8])

# ---- the plan the stream receives is a real root plan
d, b = new(), Body()
d.walk(b.pose(), 3.0, 100.0)
prompt, plan, note = d.next_chunk(b.pose(), 100.0)
check("a move hands the stream a plan with waypoints and the walking text", bool(plan) and prompt == mc.WALK and "m to go" in note, (prompt, note))
check("idle driver returns None (the normal prompt flow runs)", new().next_chunk(Body().pose(), 100.0) is None)

# ---- acceleration, defaults and the result line
d = new()
check("the defaults are a 1.0 m/s walk with a gentle 1.0 m/s^2 start and stop (1.2 looked like a jog)", d.speed == 1.0 and d.max_accel == 1.0)
check("the acceleration is clamped to a safe range", d.set_accel(9.0) == 2.0 and d.set_accel(0.01) == 0.5)
stops = []
for a in (2.0, 1.0):
    d, b = new(max_accel=a), Body()
    d.walk(b.pose(), 8.0, 100.0)
    b.apply(d.next_chunk(b.pose(), 100.0)[1]); b.apply(d.next_chunk(b.pose(), 102.0)[1])
    z0 = b.z
    d.stop(b.pose(), 104.0)
    run(d, b, t0=104.0)
    stops.append(b.z - z0)
check("a gentler acceleration brakes over a longer distance (it is the point of it)", stops[1] > stops[0], stops)
d, b = new(), Body()
d.walk(b.pose(), 3.0, 100.0)
run(d, b)
check("the result line names the start, the end and the distance", d.result(b.pose()).startswith("from (0.00, 0.00) to (0.00, 2.") or d.result(b.pose()).startswith("from (0.00, 0.00) to (0.00, 3."), d.result(b.pose()))

# ---- sanity check with a body that moves in whole steps (0.3 m minimum). NOTE: this does not reproduce the shuffle seen in the first live test
# (that came from how the real model reacts to the text "stands upright" while she is still being moved; it cannot be simulated here). It checks
# termination, and the property the old code violated: the text stays "walks forward" for the whole approach. The real check is a live run.
class StepBody(Body):
    STEP = 0.3

    def apply(self, plan):
        x0, z0 = self.x, self.z
        Body.apply(self, plan)
        d = math.hypot(self.x - x0, self.z - z0)
        if 0.02 < d < self.STEP:
            self.x, self.z = x0 + (self.x - x0) / d * self.STEP, z0 + (self.z - z0) / d * self.STEP


worst = []
for extra in (0.26, 0.3, 0.4, 0.5, 0.7, 0.9):
    d, b = new(), StepBody()
    b.z = -(2.0 + extra)                                  # start 2.0 + extra metres short of a goal at the origin... walking +Z towards z = -2.0 + 2.0
    d.goto(b.pose(), (0.0, -2.0), 100.0)
    start_z = b.z
    n, log = run(d, b, chunks=30)
    worst.append((extra, n, round(math.hypot(b.x, b.z + 2.0), 2), [p for p, _ in log if p != mc.WALK and not _.startswith("settled")]))
check("a body that moves in whole steps: every move still finishes within 8 chunks",
      all(n < 8 for _, n, _, _ in worst), worst)
check("... within 30 cm of the goal", all(e <= 0.31 for _, _, e, _ in worst), worst)
check("... and the text is 'walks forward' for the whole approach (the old code switched to 'stands upright' within 0.5 m, which is when she shuffled)", all(not x for _, _, _, x in worst), worst)

print("\nALL GOOD" if not bad else f"\nFAILURES: {bad}")
sys.exit(1 if bad else 0)
