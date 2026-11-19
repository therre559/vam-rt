"""world_frame.py - learns how ARDY's world (where the stream thinks she is) maps onto VaM's world (where Senses measures her).

The BVH export and import can rotate, mirror and offset the horizontal plane, so a goal measured in VaM (the user, the bed) cannot
be sent to the stream as ARDY metres without knowing that transform. Rather than assuming it, this fits it from what both sides
see: every time she stands still, ARDY's root (x, z, heading) and Senses' hips (x, z, facing) are one pair. Two pairs a step apart
give the rotation and the offset; the direction she turned between them says whether one frame is the mirror of the other.

    vam = k * s * R(theta) * ardy + t    s = +1 (same handedness) or -1 (mirrored: x negated before the rotation); k = scale
    (k is fitted too, within 0.6..1.6: VaM's hips do not always travel the full ARDY distance)

Pure Python, no numpy. Tests at the bottom (python world_frame.py).
"""
import math


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


class FrameFit:
    def __init__(self, min_spread=0.5, max_pairs=12, max_residual=0.12, scale_range=(1.0, 1.0)):
        self.pairs = []           # (ax, az, ah, vx, vz, vh)
        self.min_spread = min_spread
        self.max_pairs = max_pairs
        self.max_residual = max_residual
        self.dropped = None       # the last point thrown out as an outlier (for the log)
        # the BVH export is 1:1 with VaM metres (every good fit so far: scale 1.00), so the scale is fixed unless asked for: a free scale
        # let three lagged points be "fitted" with scale 0.68 and a 102-degree rotation in the 31 Oct evening test
        self.scale_range = scale_range
        self.s, self.theta, self.tx, self.tz, self.k = 1.0, 0.0, 0.0, 0.0, 1.0
        self.residual = None
        self.calibrated = False

    def reset(self):
        self.__init__(self.min_spread, self.max_pairs, self.max_residual, self.scale_range)

    def add_pair(self, ardy_xz, ardy_heading, vam_xz, vam_heading):
        """Call only while she stands still (both sides agree then). Returns True if the pair was kept."""
        ax, az = float(ardy_xz[0]), float(ardy_xz[1])
        vx, vz = float(vam_xz[0]), float(vam_xz[1])
        for p in self.pairs:
            if math.hypot(p[0] - ax, p[1] - az) < self.min_spread and math.hypot(p[3] - vx, p[4] - vz) < self.min_spread:
                # the same spot again: refresh it (she may have drifted a little) instead of adding a duplicate
                self.pairs.remove(p)
                break
        self.pairs.append((ax, az, float(ardy_heading), vx, vz, float(vam_heading)))
        self.pairs = self.pairs[-self.max_pairs:]
        self._fit()
        return True

    def _fit(self):
        self._fit_pairs()
        # one stale point (she was teleported between two readings, or the world file lagged) must not block the fit for good:
        # with four or more points, drop the single point whose removal makes everything else line up, and forget it
        if (not self.calibrated and len(self.pairs) >= 4 and self.residual is not None and self.residual > self.max_residual):
            best = None
            for i in range(len(self.pairs)):
                trial = FrameFit(self.min_spread, self.max_pairs, self.max_residual)
                trial.pairs = self.pairs[:i] + self.pairs[i + 1:]
                trial._fit_pairs()
                if trial.residual is not None and (best is None or trial.residual < best[1]):
                    best = (i, trial.residual)
            if best is not None and best[1] <= 0.5 * self.max_residual:   # only when the rest then agree closely: a real fit is 1-2 cm
                self.dropped = self.pairs[best[0]]
                self.pairs = self.pairs[:best[0]] + self.pairs[best[0] + 1:]
                self._fit_pairs()

    def _fit_pairs(self):
        n = len(self.pairs)
        self.calibrated = False
        if n < 2:
            return
        # handedness from the turning direction: with a mirror, heading changes have opposite signs
        votes = 0.0
        for i in range(n):
            for j in range(i + 1, n):
                da = _wrap(self.pairs[j][2] - self.pairs[i][2])
                dv = _wrap(self.pairs[j][5] - self.pairs[i][5])
                if abs(da) > math.radians(20) and abs(dv) > math.radians(20):
                    votes += math.copysign(min(abs(da), abs(dv)), da * dv)
        s = -1.0 if votes < 0 else 1.0
        sols = {cand: self._solve(cand) for cand in (1.0, -1.0)}
        # three or more spread-out points settle the handedness by fit alone; with fewer, the turning direction decides
        if n >= 3 and min(sols[1.0][4], sols[-1.0][4]) < 0.5 * max(sols[1.0][4], sols[-1.0][4]):
            s = 1.0 if sols[1.0][4] <= sols[-1.0][4] else -1.0
        th, tx, tz, k, res = sols[s]
        self.s, self.theta, self.tx, self.tz, self.k, self.residual = s, th, tx, tz, k, res
        spread = max(math.hypot(p[0] - q[0], p[1] - q[1]) for p in self.pairs for q in self.pairs)
        # two points on their own cannot tell a mirror from a rotation: that needs either a clear turn between them or a third
        # point off the line through the first two
        area = 0.0
        for i in range(n):
            for j in range(i + 1, n):
                for m in range(j + 1, n):
                    a, b, c = self.pairs[i], self.pairs[j], self.pairs[m]
                    area = max(area, abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])))
        decisive = abs(votes) >= math.radians(25) or area >= 0.06
        self.calibrated = spread >= self.min_spread and self.residual <= self.max_residual and decisive

    def _solve(self, s):
        """Least-squares rotation + translation for a given handedness (Procrustes in 2-D, closed form)."""
        n = len(self.pairs)
        amx = sum(p[0] for p in self.pairs) / n
        amz = sum(p[1] for p in self.pairs) / n
        vmx = sum(p[3] for p in self.pairs) / n
        vmz = sum(p[4] for p in self.pairs) / n
        # mirrored: negate ardy x first
        sx, sy = 0.0, 0.0   # sum of cross and dot terms
        for p in self.pairs:
            ax, az = s * (p[0] - amx), p[1] - amz
            vx, vz = p[3] - vmx, p[4] - vmz
            sy += ax * vx + az * vz          # dot
            sx += ax * vz - az * vx          # cross (z-component)
        theta = math.atan2(sx, sy) if (sx or sy) else 0.0
        aa = sum((p[0] - amx) ** 2 + (p[1] - amz) ** 2 for p in self.pairs)
        k = math.hypot(sx, sy) / aa if aa > 1e-9 else 1.0
        k = max(self.scale_range[0], min(self.scale_range[1], k))
        c, si = math.cos(theta), math.sin(theta)
        tx = vmx - k * (c * s * amx - si * amz)
        tz = vmz - k * (si * s * amx + c * amz)
        res = 0.0
        for p in self.pairs:
            x, z = self._apply(s, theta, tx, tz, p[0], p[1], k)
            res = max(res, math.hypot(x - p[3], z - p[4]))
        return theta, tx, tz, k, res

    @staticmethod
    def _apply(s, theta, tx, tz, ax, az, k=1.0):
        ax = s * ax
        c, si = math.cos(theta), math.sin(theta)
        return k * (c * ax - si * az) + tx, k * (si * ax + c * az) + tz

    def ardy_to_vam(self, ax, az):
        return self._apply(self.s, self.theta, self.tx, self.tz, ax, az, self.k)

    def vam_to_ardy(self, vx, vz):
        c, si = math.cos(self.theta), math.sin(self.theta)
        x, z = (vx - self.tx) / self.k, (vz - self.tz) / self.k
        ax, az = c * x + si * z, -si * x + c * z
        return self.s * ax, az

    def dump(self):
        """One line per resting point: ARDY (x, z, heading) -> VaM (x, z, facing). For the log when a fit fails."""
        out = []
        for p in self.pairs:
            out.append(f"ardy ({p[0]:.2f}, {p[1]:.2f}, {math.degrees(p[2]):.0f} deg) -> vam ({p[3]:.2f}, {p[4]:.2f}, {math.degrees(p[5]):.0f} deg)")
        return out

    def describe(self):
        note = ""
        if self.dropped is not None:
            d = self.dropped
            note = (f" (one odd point was ignored: ardy ({d[0]:.2f}, {d[1]:.2f}) -> vam ({d[3]:.2f}, {d[4]:.2f}), "
                    f"probably a reading from before she was moved)")
            self.dropped = None
        if not self.calibrated:
            n = len(self.pairs)
            if n < 2:
                return f"frame link: not calibrated yet ({n} point(s); she needs to have walked somewhere)"
            spread = max(math.hypot(p[0] - q[0], p[1] - q[1]) for p in self.pairs for q in self.pairs)
            vspread = max(math.hypot(p[3] - q[3], p[4] - q[4]) for p in self.pairs for q in self.pairs)
            why = []
            if spread < self.min_spread:
                why.append(f"her ARDY positions are too close together ({spread * 100:.0f} cm)")
            if vspread < 0.6 * self.min_spread:
                why.append(f"her VaM position hardly moved ({vspread * 100:.0f} cm): In Place ON, or Senses is not seeing her hips travel")
            if self.residual is not None and self.residual > self.max_residual:
                why.append(f"the two tracks do not line up (best fit still {self.residual * 100:.0f} cm off, scale {self.k:.2f})")
            if not why:
                why.append("the points lie on a line and she did not turn between them (mirror undecided)")
            return f"frame link: not calibrated after {n} point(s): " + "; ".join(why) + note
        return (f"frame link: {'mirrored, ' if self.s < 0 else ''}rotated {math.degrees(self.theta):.0f} deg, scale {self.k:.2f}, offset "
                f"({self.tx:.2f}, {self.tz:.2f}), worst error {self.residual * 100:.0f} cm over {len(self.pairs)} points" + note)


def her_frame_to_vam(self_x, self_z, facing_deg, fwd, right):
    """A point given as metres ahead / to her right, in VaM world coordinates (0 deg = +Z, positive towards +X; right of +Z is +X)."""
    h = math.radians(facing_deg)
    fx, fz = math.sin(h), math.cos(h)
    rx, rz = math.cos(h), -math.sin(h)
    return self_x + fwd * fx + right * rx, self_z + fwd * fz + right * rz


def goal_short_of(from_xz, target_xz, stop):
    """The point `stop` metres short of target on the straight line from `from`. None if already within stop + 0.25 m."""
    dx, dz = target_xz[0] - from_xz[0], target_xz[1] - from_xz[1]
    d = math.hypot(dx, dz)
    if d <= stop + 0.25:
        return None
    k = (d - stop) / d
    return from_xz[0] + dx * k, from_xz[1] + dz * k


if __name__ == "__main__":
    import random

    bad = 0
    for s_true, th_true, tx_true, tz_true, k_true in [(1, 0.0, 0.0, 0.0, 1.0), (1, 0.7, 2.0, -1.0, 0.8), (-1, 0.0, 0.0, 0.0, 1.0), (-1, 2.1, -3.0, 0.5, 1.2), (1, math.pi, 1, 1, 1.0)]:
        f = FrameFit(scale_range=(0.6, 1.6)) if k_true != 1.0 else FrameFit()   # the scale is only free when asked for
        rng = random.Random(1)
        pts = [(0, 0, 0.0), (1.5, 0.3, 0.6), (0.4, 2.0, -1.2), (-1.0, 1.0, 2.0)]
        for ax, az, ah in pts:
            vx, vz = FrameFit._apply(s_true, th_true, tx_true, tz_true, ax, az, k_true)
            vx += rng.uniform(-0.03, 0.03); vz += rng.uniform(-0.03, 0.03)
            vh = s_true * ah + th_true   # heading maps the same way (mirror flips the turning direction)
            f.add_pair((ax, az), ah, (vx, vz), vh)
        gx, gz = f.vam_to_ardy(*FrameFit._apply(s_true, th_true, tx_true, tz_true, 2.0, -1.0, k_true))
        ok = f.calibrated and f.s == s_true and abs(_wrap(f.theta - th_true)) < 0.05 and abs(gx - 2.0) < 0.1 and abs(gz + 1.0) < 0.1
        bad += not ok
        print("ok " if ok else "BAD", s_true, round(th_true, 2), "->", f.describe(), "| test goal", round(gx, 2), round(gz, 2))
    # two points only, mirrored: the turning direction must settle the handedness
    f = FrameFit()
    f.add_pair((0, 0), 0.0, (0, 0), 0.0)
    f.add_pair((1.0, 1.0), 0.8, FrameFit._apply(-1, 0.0, 0, 0, 1.0, 1.0), -0.8)
    ok = f.calibrated and f.s == -1
    bad += not ok
    print("ok " if ok else "BAD", "two-point mirror:", f.describe())
    x, z = her_frame_to_vam(1, 1, 90, 2, 0)
    ok = abs(x - 3) < 1e-6 and abs(z - 1) < 1e-6
    bad += not ok
    print("ok " if ok else "BAD", "her frame facing +X, 2 m ahead ->", round(x, 2), round(z, 2))
    print(goal_short_of((0, 0), (3, 4), 1.0))
    raise SystemExit(bad)
