"""Typed moves for the live test: walk N metres, go to a point, come home, stop. Pure Python (no GPU), easy to test.

The stream asks the driver once per chunk what to do. While a move is active the driver answers with the text to generate
("walks forward" / "stands upright") and a root plan from ardy_control.steer_plan, planned from where ARDY says she is
(closed loop). A move ends by itself: on arrival she settles for a couple of chunks and control goes back to the normal prompt
flow; a timeout brakes her if she has not arrived in good time and gives up if even that fails; /stop brakes her at once.

Everything is in ARDY's world frame (metres; she starts at the origin facing +Z). A pose is (x, z, heading, vx, vz) where the
heading is 0 for +Z and grows towards +X (the same convention as ardy_control.steer_plan and Streamer.root_pose).

Not for following a moving user: ARDY's pose is the END of the last generated chunk, which VaM plays 2-4 seconds later, so a goal
relative to it is only right while she is standing still. Give moves while she stands.
"""

import math
import threading

import ardy_control as ctl

WALK = "A person walks forward."
STAND = "A person stands upright."

MIN_SPEED, MAX_SPEED = 0.5, 1.6
MIN_ACCEL, MAX_ACCEL = 0.5, 2.0


class MoveDriver:
    IDLE, MOVING, SETTLING = "idle", "moving", "settling"

    def __init__(self, fps, speed=1.0, max_move=8.0, settle_chunks=2, done_radius=0.25, max_accel=1.0, max_home=60.0,
                 staging=2.5, via_radius=0.6, free_walk=True, free_align_deg=15.0, free_min_dist=1.2, mode="sparse"):
        self.mode = mode                        # sparse: one goal waypoint, the model plans the walk; dense: a planned path
        self.walk_text = WALK                   # the wording used while she walks (the stream sets a mood-coloured one per move)
        self.free_walk = free_walk              # walk by text (no root constraint) while lined up with the goal
        self.free_align = math.radians(free_align_deg)
        self.free_min_dist = free_min_dist
        self.fps = fps
        self.speed = max(MIN_SPEED, min(MAX_SPEED, speed))
        self.max_move = max_move          # the farthest a single move may ask for (metres); 0 = moves are off
        self.max_home = max_home          # /home may come from farther away than any other move
        self.staging = staging            # /home aims for a point this far behind the origin first, so she arrives facing forward
        self.via_radius = via_radius
        self.via = []                     # waypoints still to pass before the goal
        self.settle_chunks = settle_chunks
        # A move is finished within this of its goal. Not smaller: ARDY cannot translate by less than about one step, so asking her to
        # creep the last few centimetres makes her shuffle back and forth across the goal (seen in the first live test).
        self.done_radius = done_radius
        self.max_accel = max(MIN_ACCEL, min(MAX_ACCEL, max_accel))   # how hard she speeds up and brakes (m/s^2)
        self.start_pose = None            # where the current / last move began
        self._lock = threading.Lock()
        self.state = self.IDLE
        self.goal = (0.0, 0.0)
        self.label = ""
        self.braking = False
        self.deadline = 0.0
        self.settle_left = 0

    @property
    def active(self):
        return self.state != self.IDLE

    def set_speed(self, v):
        self.speed = max(MIN_SPEED, min(MAX_SPEED, float(v)))
        return self.speed

    def set_accel(self, a):
        self.max_accel = max(MIN_ACCEL, min(MAX_ACCEL, float(a)))
        return self.max_accel

    # ------------------------------------------------------------------ starting a move (called from the console thread)
    def goto(self, pose, goal_xz, now, label="goto", via=(), limit=None):
        """Walk to a point, optionally passing the `via` points first. Returns (ok, message)."""
        if self.max_move <= 0:
            return False, "moves are switched off (--max-move 0)"
        gx, gz = float(goal_xz[0]), float(goal_xz[1])
        if not (math.isfinite(gx) and math.isfinite(gz)):
            return False, "that is not a number"
        limit = self.max_move if limit is None else limit
        dist = math.hypot(gx - pose[0], gz - pose[1])
        if dist > limit:
            which = "--max-home" if limit == self.max_home and limit != self.max_move else "--max-move"
            return False, f"{dist:.1f} m is farther than the limit of {limit:g} m ({which})"
        if dist <= self.done_radius and not via:
            return False, "she is already there"
        route = [tuple(pose[:2])] + [tuple(v) for v in via] + [(gx, gz)]
        length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(route, route[1:]))
        with self._lock:
            self.state = self.MOVING
            self.goal = (gx, gz)
            self.via = [tuple(v) for v in via]
            self.label = label
            self.braking = False
            self.start_pose = tuple(pose)
            self.deadline = now + max(8.0, 3.0 * length / self.speed + 6.0)
        return True, f"{label}: {length:.1f} m to go at {self.speed:g} m/s"

    def home(self, pose, now):
        """Walk back to the origin from anywhere (up to --max-home) and arrive FACING FORWARD: she faces the way she travels, so she walks to a
        staging point behind the origin first and then straight onto it."""
        dist = math.hypot(pose[0], pose[1])
        heading = (pose[2] + math.pi) % (2 * math.pi) - math.pi
        if dist <= self.done_radius and abs(math.degrees(heading)) < 30:
            return False, "she is already home, facing forward"
        return self.goto(pose, (0.0, 0.0), now, "home", via=[(0.0, -self.staging)], limit=self.max_home)

    def walk(self, pose, distance, now):
        h = pose[2]
        return self.goto(pose, (pose[0] + math.sin(h) * distance, pose[1] + math.cos(h) * distance), now, f"walk {distance:g} m")

    def go_relative(self, pose, forward, right, now):
        h = pose[2]
        gx = pose[0] + forward * math.sin(h) + right * math.cos(h)      # forward = (sin h, cos h), right = (cos h, -sin h)
        gz = pose[1] + forward * math.cos(h) - right * math.sin(h)
        return self.goto(pose, (gx, gz), now, f"go {forward:g} ahead, {right:g} right")

    def stop(self, pose, now):
        """Brake: aim for the point she would stop at (v^2 / 2a ahead) and settle there. Returns (ok, message)."""
        with self._lock:
            if self.state == self.IDLE:
                return False, "she is not on a move"
            self._brake(pose, now)
        return True, "braking"

    def _brake(self, pose, now):
        v = math.hypot(pose[3], pose[4])
        if v < 0.05:
            self.goal = (pose[0], pose[1])
        else:
            d = v * v / (2.0 * self.max_accel)
            self.goal = (pose[0] + pose[3] / v * d, pose[1] + pose[4] / v * d)
        self.via = []
        self.braking = True
        self.label = "braking"
        self.state = self.MOVING
        self.deadline = now + 6.0

    # ------------------------------------------------------------------ once per chunk (called from the generation thread)
    def next_chunk(self, pose, now):
        """None when idle (the normal prompt flow runs), else (prompt, plan, note)."""
        with self._lock:
            if self.state == self.IDLE:
                return None
            if self.state == self.SETTLING:
                return self._settle(pose)
            x, z = pose[0], pose[1]
            while self.via and self._passed(pose):
                self.via.pop(0)
            dist = math.hypot(self.goal[0] - x, self.goal[1] - z)
            expired = now > self.deadline
            if (dist <= self.done_radius and not self.via) or (expired and self.braking):
                self.state = self.SETTLING
                self.settle_left = self.settle_chunks
                return self._settle(pose)
            if expired:                          # far too long: brake instead of walking on
                self._brake(pose, now)
                dist = math.hypot(self.goal[0] - x, self.goal[1] - z)
            if self.mode == "sparse" and not self.via and not self.braking:
                secs = max(1.5, min(4.0, dist / self.speed + 1.0))   # a second for getting going: a 0.6 m goal in 1 s from standstill made her lunge and crouch
                off = int(round(secs * self.fps))
                plan = ctl.RootPlan([(off, self.goal[0], self.goal[1]), (off + int(self.fps), self.goal[0], self.goal[1])])
                return self.walk_text, plan, f"{self.label}: {dist:.1f} m to go (goal in {secs:.1f} s, the model plans the walk)"
            if self.free_walk and not self.via and not self.braking and dist > self.free_min_dist:
                err = (math.atan2(self.goal[0] - x, self.goal[1] - z) - pose[2] + math.pi) % (2 * math.pi) - math.pi
                if abs(err) <= self.free_align:
                    return self.walk_text, None, f"{self.label}: {dist:.1f} m to go, lined up: walking freely"
            # arrive_radius is tiny here on purpose: the planner's usual "stand still within 35 cm" would stop her short of a typed goal
            plan = ctl.steer_plan((x, z), (pose[3], pose[4]), pose[2], self.goal, self.speed, self.fps, max_accel=self.max_accel,
                                  arrive_radius=0.02, via=self.via, via_radius=self.via_radius)
            # The text stays "walks forward" until the move is done: with "stands upright" and a plan that still moves her she shuffles.
            note = f"{self.label}: {dist:.1f} m to go" + (f", via a staging point" if self.via else "")
            return self.walk_text, plan, note

    def _passed(self, pose):
        """Has she already gone past the next staging point? Within its radius, or beyond it along the way to the next target."""
        p = self.via[0]
        nxt = self.via[1] if len(self.via) > 1 else self.goal
        if math.hypot(pose[0] - p[0], pose[1] - p[1]) <= self.via_radius:
            return True
        ax, az = nxt[0] - p[0], nxt[1] - p[1]
        length = math.hypot(ax, az)
        if length < 1e-6:
            return True
        t = ((pose[0] - p[0]) * ax + (pose[1] - p[1]) * az) / length
        perp = abs((pose[0] - p[0]) * az - (pose[1] - p[1]) * ax) / length
        # only BETWEEN the staging point and the next target counts (at least 0.5 m short of it): standing on the goal, or beyond it, has not
        # gone through the staging point at all, and she still has to go round it to arrive facing the right way
        return 0 <= t <= length - 0.5 and perp <= 1.0

    def _settle(self, pose):
        if self.settle_left <= 0:
            self.state = self.IDLE
            return None
        self.settle_left -= 1
        plan = ctl.steer_plan((pose[0], pose[1]), (pose[3], pose[4]), pose[2], (pose[0], pose[1]), self.speed, self.fps)
        return STAND, plan, f"settled, standing ({self.settle_left} chunk(s) before control goes back to the normal prompts)"

    def result(self, pose):
        """One line describing the move that just ended: from where to where, in ARDY metres."""
        sp = self.start_pose or pose
        return (f"from ({sp[0]:.2f}, {sp[1]:.2f}) to ({pose[0]:.2f}, {pose[1]:.2f}), "
                f"{math.hypot(pose[0] - sp[0], pose[1] - sp[1]):.2f} m, facing {math.degrees(pose[2]):.0f} deg")
