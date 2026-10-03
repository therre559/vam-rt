"""Gait quality metrics for generated walking. Pure Python (lists of tuples): no GPU, no numpy, easy to test.

Root-position tracking alone cannot tell a natural walk from a glide: a character can reach a goal behind her by walking
backwards, or sidestep to a goal beside her, and the root path still looks perfect. These metrics look at the body:

  facing vs travel   angle between where the pelvis faces and where she travels. ~0 deg = walking forward, ~90 = sidestepping,
                     ~180 = walking backwards.
  turning            total heading change and the fastest turn rate.
  foot skate         how fast a planted foot slides over the ground. A good walk plants its foot (about 0 m/s).
"""

import math


def _unit(x, z):
    n = math.hypot(x, z)
    return (x / n, z / n) if n > 1e-9 else (0.0, 0.0)


def facing_vectors(left_xz, right_xz, calib=(0.0, 1.0), calib_frames=5):
    """Per-frame unit vectors (x, z) of where the pelvis faces, from the line between the left and right hip joints.
    Which of the two perpendiculars is 'forward' depends on the skeleton's handedness, so the sign is chosen such that the
    first frames face `calib` (ARDY starts every session facing +Z)."""
    raw = []
    for (lx, lz), (rx, rz) in zip(left_xz, right_xz):
        dx, dz = rx - lx, rz - lz
        raw.append(_unit(-dz, dx))
    k = min(calib_frames, len(raw))
    dot = sum(f[0] * calib[0] + f[1] * calib[1] for f in raw[:k])
    s = 1.0 if dot >= 0 else -1.0
    return [(s * f[0], s * f[1]) for f in raw]


def velocities(xz, fps, window=5):
    """Smoothed velocity (m/s) per frame: displacement over a centred window."""
    n, half = len(xz), window // 2
    out = []
    for i in range(n):
        a, b = max(0, i - half), min(n - 1, i + half)
        dt = (b - a) / fps
        out.append(((xz[b][0] - xz[a][0]) / dt, (xz[b][1] - xz[a][1]) / dt) if dt > 0 else (0.0, 0.0))
    return out


def angle_deg(a, b):
    """Unsigned angle in degrees (0..180) between two 2D vectors."""
    return math.degrees(math.atan2(abs(a[0] * b[1] - a[1] * b[0]), a[0] * b[0] + a[1] * b[1]))


def misalignment_deg(forward, root_xz, fps, min_speed=0.4, window=5):
    """Angle between where she faces and where she travels, for every frame faster than `min_speed` m/s."""
    vel = velocities(root_xz, fps, window)
    return [angle_deg(f, v) for f, v in zip(forward, vel) if math.hypot(v[0], v[1]) >= min_speed]


def percentile(values, q):
    if not values:
        return None
    v = sorted(values)
    pos = (len(v) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def _unwrap(angles):
    out = [angles[0]] if angles else []
    for a in angles[1:]:
        d = (a - out[-1] + math.pi) % (2 * math.pi) - math.pi
        out.append(out[-1] + d)
    return out


def _moving_average(values, n):
    """Centred moving average. Near the ends the window shrinks symmetrically (the very first and last values are left as they
    are), so a turn close to the start or end of a clip is not blurred away."""
    half, out, last = n // 2, [], len(values) - 1
    for i in range(len(values)):
        h = min(half, i, last - i)
        out.append(sum(values[i - h:i + h + 1]) / (2 * h + 1))
    return out


def turn_stats(forward, fps, smooth_s=1.0):
    """(total absolute heading change in degrees, fastest turn rate in degrees per second).
    The pelvis sways with every stride, so the (unwrapped) heading is averaged over `smooth_s` seconds first (about one stride
    cycle); otherwise a straight walk would look like it is turning. Averaging angles, not direction vectors, keeps a sudden
    half turn from cancelling itself out."""
    if len(forward) < 2:
        return 0.0, 0.0
    yaw = _unwrap([math.atan2(f[0], f[1]) for f in forward])
    n = max(1, int(round(smooth_s * fps)))
    if n > 1:
        yaw = _moving_average(yaw, n)
    total = sum(abs(b - a) for a, b in zip(yaw, yaw[1:]))
    fastest = max(abs(b - a) for a, b in zip(yaw, yaw[1:])) * fps
    return math.degrees(total), math.degrees(fastest)


def foot_skate(foot_xyz, fps, plant_height=0.04):
    """Mean horizontal speed (m/s) of a foot over the frames where it is planted (within `plant_height` of the lowest
    point it reaches). None if it is never planted."""
    if len(foot_xyz) < 2:
        return None
    ground = min(p[1] for p in foot_xyz)
    planted = [p[1] <= ground + plant_height for p in foot_xyz]
    speeds = [math.hypot(b[0] - a[0], b[2] - a[2]) * fps
              for a, b, pa, pb in zip(foot_xyz, foot_xyz[1:], planted, planted[1:]) if pa and pb]
    return sum(speeds) / len(speeds) if speeds else None
