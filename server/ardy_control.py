"""Planning of root-path constraints for ARDY. Pure Python: no GPU, no ARDY, easy to test.

ARDY can be told where its character's root (x, z in metres, in the model's own world frame) should be at chosen future
frames. NVIDIA's interactive demo builds its "target velocity" control exactly this way: blend the current velocity into
the wanted one, integrate to get future positions, and put a waypoint every few frames. This module does the same
(our own small implementation of that idea; NVIDIA's demo is Apache-2.0, see CREDITS.md) and adds a "go to a point and
stop there" planner, which is what a follower needs.

A plan is a list of (offset, x, z): the root should be at (x, z) `offset` frames AFTER the last frame of the history.
Everything here is in ARDY's world frame (metres, +Z is where she faces when a session starts).
"""

import math
from dataclasses import dataclass, field
from typing import List, Tuple

DEFAULT_INTERVAL = 4        # frames between waypoints (the demo uses about 4)
DEFAULT_LOOKAHEAD_S = 4.0   # how far ahead the plan reaches
DEFAULT_TRANSITION_S = 1.0  # time to blend the current velocity into the wanted one (a guess; tune it)
DEFAULT_MAX_ACCEL = 1.5     # m/s^2, how quickly she may speed up or slow down
DEFAULT_MAX_TURN_DPS = 90.0 # degrees per second, the fastest she is asked to turn while walking
DEFAULT_TURN_SPEED = 0.3    # m/s, the pace while she is still turning towards the goal (a gentle arc, not a stand-still)
DEFAULT_ARRIVE_RADIUS = 0.35  # m, within this of the goal she is simply told to stand still (no chasing the last centimetres)


@dataclass
class RootPlan:
    points: List[Tuple[int, float, float]] = field(default_factory=list)

    def __bool__(self):
        return bool(self.points)

    def last(self):
        return self.points[-1] if self.points else None


def _emit(positions, interval):
    return RootPlan([(i, x, z) for i, (x, z) in enumerate(positions, 1) if i % interval == 0])


def velocity_plan(root_xz, vel_xz, target_vel_xz, fps, lookahead_s=DEFAULT_LOOKAHEAD_S,
                  interval=DEFAULT_INTERVAL, transition_s=DEFAULT_TRANSITION_S):
    """Move at `target_vel_xz` (m/s): the current velocity is blended linearly into it over `transition_s`."""
    n = max(1, int(round(fps * lookahead_s)))
    nt = max(1, int(round(fps * transition_s)))
    dt = 1.0 / fps
    x, z = root_xz
    positions = []
    for i in range(1, n + 1):
        a = min(1.0, i / nt)
        vx = (1 - a) * vel_xz[0] + a * target_vel_xz[0]
        vz = (1 - a) * vel_xz[1] + a * target_vel_xz[1]
        x += vx * dt
        z += vz * dt
        positions.append((x, z))
    return _emit(positions, interval)


def goto_plan(root_xz, vel_xz, goal_xz, speed, fps, lookahead_s=DEFAULT_LOOKAHEAD_S,
              interval=DEFAULT_INTERVAL, max_accel=DEFAULT_MAX_ACCEL):
    """Walk to `goal_xz` at no more than `speed` m/s and stop there. She slows down early enough to stop exactly on the
    goal (the wanted speed is min(speed, sqrt(2 * accel * distance))), never overshoots, and stays put once she arrives."""
    n = max(1, int(round(fps * lookahead_s)))
    dt = 1.0 / fps
    x, z = root_xz
    vx, vz = vel_xz
    gx, gz = goal_xz
    positions = []
    for _ in range(n):
        dx, dz = gx - x, gz - z
        dist = math.hypot(dx, dz)
        if dist < 1e-3:
            vx = vz = 0.0
            positions.append((gx, gz))
            x, z = gx, gz
            continue
        v_des = min(speed, math.sqrt(2.0 * max_accel * dist))
        tx, tz = dx / dist * v_des, dz / dist * v_des
        ax, az = tx - vx, tz - vz           # the change of velocity we would like
        am = math.hypot(ax, az)
        limit = max_accel * dt
        if am > limit:
            ax, az = ax / am * limit, az / am * limit
        vx, vz = vx + ax, vz + az
        if math.hypot(vx * dt, vz * dt) >= dist:   # the step would reach or pass the goal: stop on it
            x, z = gx, gz
            vx = vz = 0.0
        else:
            x += vx * dt
            z += vz * dt
        positions.append((x, z))
    return _emit(positions, interval)


def constraint_frames(plan, hist_len, horizon, patch, max_window):
    """Which window frames the plan's waypoints land on, and how long the model's window has to be to see them.

    The window is [history | generation horizon | future]. Waypoint `offset` sits `offset` frames after the last history
    frame, i.e. at window index hist_len - 1 + offset, and must be at or after the first generated frame (hist_len).
    Returns (model_frames, frame_indices, xz_list); model_frames is a multiple of `patch`, never shorter than
    history + horizon and never longer than `max_window`; waypoints that do not fit are dropped."""
    last = max(o for o, _, _ in plan.points)
    need = hist_len + max(horizon, last)
    model_frames = min(max_window, -(-need // patch) * patch)
    model_frames = max(model_frames, hist_len + horizon)
    frames, xz = [], []
    for off, x, z in plan.points:
        fi = hist_len - 1 + off
        if hist_len <= fi < model_frames:
            frames.append(fi)
            xz.append((x, z))
    return model_frames, frames, xz


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def steer_states(root_xz, heading_rad, speed_now, goal_xz, speed, fps, lookahead_s=DEFAULT_LOOKAHEAD_S,
                 max_accel=DEFAULT_MAX_ACCEL, max_turn_dps=DEFAULT_MAX_TURN_DPS, turn_speed=DEFAULT_TURN_SPEED,
                 arrive_radius=DEFAULT_ARRIVE_RADIUS):
    """Simulate a walker that steers like a person: it turns towards the goal at a limited rate, walks slowly while it is not yet
    facing the goal (fast only once aligned), brakes in time and stops exactly on the goal. heading_rad is 0 for +Z and grows
    towards +X; she moves along (sin h, cos h). Returns one (x, z, heading, speed) per frame.

    Within `arrive_radius` of the goal at the start she is told to stand still where she is. Near the goal the direction to it is
    noisy and the slow turning pace would otherwise make her loop around it (the first real test did exactly that).

    Why: ARDY follows a root path exactly but does not control where she FACES. Asked for a point behind her it walks backwards,
    and for a point beside her it glides sideways. A path that curves the way a forward walker would turn is followed naturally."""
    n = max(1, int(round(fps * lookahead_s)))
    dt = 1.0 / fps
    wmax = math.radians(max_turn_dps)
    x, z = root_xz
    psi, v = heading_rad, speed_now
    gx, gz = goal_xz
    if math.hypot(gx - x, gz - z) <= arrive_radius:
        return [(x, z, psi, 0.0)] * n
    out = []
    for _ in range(n):
        dx, dz = gx - x, gz - z
        dist = math.hypot(dx, dz)
        if dist < 1e-3 and v < 0.05:
            v = 0.0
            out.append((gx, gz, psi, 0.0))
            x, z = gx, gz
            continue
        err = _wrap(math.atan2(dx, dz) - psi) if dist > 1e-3 else 0.0
        psi += max(-wmax, min(wmax, err / 0.25)) * dt            # turn towards the goal, at a limited rate
        align = max(0.0, math.cos(err))                          # 1 when facing the goal, 0 at 90 degrees or more away
        v_cap = turn_speed + (speed - turn_speed) * align
        v_des = min(v_cap, math.sqrt(2.0 * max_accel * dist))    # and slow down early enough to stop on the goal
        if align < 0.94:                                         # still turning (more than ~20 degrees off):
            v_des = min(v_des, 0.5 * wmax * dist)                # keep the goal outside the turning circle, or she would orbit it
        v += max(-max_accel * dt, min(max_accel * dt, v_des - v))
        step = v * dt
        if step >= dist:
            x, z, v = gx, gz, 0.0
        else:
            x += math.sin(psi) * step
            z += math.cos(psi) * step
        out.append((x, z, psi, v))
    return out


def steer_plan(root_xz, vel_xz, heading_rad, goal_xz, speed, fps, lookahead_s=DEFAULT_LOOKAHEAD_S, interval=DEFAULT_INTERVAL,
               max_accel=DEFAULT_MAX_ACCEL, max_turn_dps=DEFAULT_MAX_TURN_DPS, turn_speed=DEFAULT_TURN_SPEED,
               arrive_radius=DEFAULT_ARRIVE_RADIUS):
    """Root waypoints for a heading-aware walk to `goal_xz` (see steer_states)."""
    states = steer_states(root_xz, heading_rad, math.hypot(vel_xz[0], vel_xz[1]), goal_xz, speed, fps, lookahead_s,
                          max_accel, max_turn_dps, turn_speed, arrive_radius)
    return _emit([(x, z) for x, z, _, _ in states], interval)


def postprocess_frames(frames, xz, hist_len, horizon):
    """Constraint frames for ARDY's post-processing step. It only sees the newly generated horizon, so window frame f becomes
    f - hist_len, and only frames inside the horizon [0, horizon) are kept (the interactive demo does the same)."""
    keep = [(f - hist_len, p) for f, p in zip(frames, xz) if 0 <= f - hist_len < horizon]
    return [f for f, _ in keep], [p for _, p in keep]
