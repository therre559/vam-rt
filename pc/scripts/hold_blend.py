"""Smooth joins while she holds a settled pose.

While a pose is held, the stream restarts every chunk from the same saved anchor instead of from where the previous chunk ended
(that is what stops errors piling up). The price: each chunk wanders a little during its two seconds (a hand, the head, a leg),
and the next chunk starts again from the anchor, so the join snaps back by that distance. That was the periodic twitch in a
motionless stand, and now and then a big one (19 cm on a leg in one play-test log).

The fix keeps the anchor and changes only what is PLAYED: the last frames of a held chunk are eased back to the anchor pose, and the
first frames are eased in from it, so every held chunk starts and ends exactly on the anchor and the joins are seamless. Nothing
about what she does changes: this applies only to chunks generated from the anchor, i.e. a pose that is already being held still.

numpy only, so it can be tested without a GPU (tests/test_hold_blend.py).
"""
import numpy as np

ROT = "local_rot_mats"       # [1, T, J, 3, 3]
ROOT = "root_positions"      # [1, T, 3]
JOINTS = "posed_joints"      # [1, T, J, 3]  (only kept consistent for the stream's own checks; the BVH uses ROT and ROOT)


# --------------------------------------------------------------------------- rotations
def mat_to_quat(R):
    """Rotation matrices [..., 3, 3] -> unit quaternions [..., 4] as (w, x, y, z)."""
    R = np.asarray(R, dtype=np.float64)
    m00, m01, m02 = R[..., 0, 0], R[..., 0, 1], R[..., 0, 2]
    m10, m11, m12 = R[..., 1, 0], R[..., 1, 1], R[..., 1, 2]
    m20, m21, m22 = R[..., 2, 0], R[..., 2, 1], R[..., 2, 2]
    q_abs = np.sqrt(np.maximum(0.0, np.stack([1 + m00 + m11 + m22, 1 + m00 - m11 - m22,
                                              1 - m00 + m11 - m22, 1 - m00 - m11 + m22], axis=-1)))
    cands = np.stack([
        np.stack([q_abs[..., 0] ** 2, m21 - m12, m02 - m20, m10 - m01], axis=-1),
        np.stack([m21 - m12, q_abs[..., 1] ** 2, m10 + m01, m02 + m20], axis=-1),
        np.stack([m02 - m20, m10 + m01, q_abs[..., 2] ** 2, m12 + m21], axis=-1),
        np.stack([m10 - m01, m20 + m02, m21 + m12, q_abs[..., 3] ** 2], axis=-1),
    ], axis=-2)
    cands = cands / (2.0 * np.maximum(q_abs[..., None], 0.1))
    best = q_abs.argmax(axis=-1)
    q = np.take_along_axis(cands, best[..., None, None], axis=-2)[..., 0, :]
    return q / np.linalg.norm(q, axis=-1, keepdims=True)


def quat_to_mat(q):
    q = np.asarray(q, dtype=np.float64)
    q = q / np.linalg.norm(q, axis=-1, keepdims=True)
    w, x, y, z = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    R = np.empty(q.shape[:-1] + (3, 3))
    R[..., 0, 0] = 1 - 2 * (y * y + z * z)
    R[..., 0, 1] = 2 * (x * y - z * w)
    R[..., 0, 2] = 2 * (x * z + y * w)
    R[..., 1, 0] = 2 * (x * y + z * w)
    R[..., 1, 1] = 1 - 2 * (x * x + z * z)
    R[..., 1, 2] = 2 * (y * z - x * w)
    R[..., 2, 0] = 2 * (x * z - y * w)
    R[..., 2, 1] = 2 * (y * z + x * w)
    R[..., 2, 2] = 1 - 2 * (x * x + y * y)
    return R


def slerp(q0, q1, t):
    """Shortest-path spherical interpolation; t broadcasts against the leading dimensions."""
    q0, q1 = np.broadcast_arrays(np.asarray(q0, dtype=np.float64), np.asarray(q1, dtype=np.float64))
    dot = np.sum(q0 * q1, axis=-1, keepdims=True)
    q1 = np.where(dot < 0, -q1, q1)
    dot = np.abs(dot)
    t = np.asarray(t, dtype=np.float64)
    while t.ndim < dot.ndim:
        t = t[..., None]
    theta = np.arccos(np.clip(dot, -1.0, 1.0))
    sin = np.sin(theta)
    small = sin < 1e-6
    a = np.where(small, 1.0 - t, np.sin((1.0 - t) * theta) / np.where(small, 1.0, sin))
    b = np.where(small, t, np.sin(t * theta) / np.where(small, 1.0, sin))
    out = a * q0 + b * q1
    return out / np.linalg.norm(out, axis=-1, keepdims=True)


# --------------------------------------------------------------------------- the blend
def _smooth(s):
    s = np.clip(s, 0.0, 1.0)
    return s * s * (3.0 - 2.0 * s)


def weights(total, end_frames, start_frames):
    """Per-frame weight of the anchor pose: 1 on the first and last frame, 0 in between, eased."""
    w = np.zeros(total)
    end_frames = int(min(max(end_frames, 0), total // 2))
    start_frames = int(min(max(start_frames, 0), total // 4))
    if end_frames > 0:
        s = (np.arange(total - end_frames, total) - (total - end_frames) + 1) / end_frames
        w[total - end_frames:] = _smooth(s)
    if start_frames > 0:
        s = 1.0 - np.arange(start_frames) / start_frames
        w[:start_frames] = np.maximum(w[:start_frames], _smooth(s))
    return w


def last_frame(chunk):
    """The chunk's final frame, in the form pull_to_pose wants (None if the chunk has no usable arrays)."""
    try:
        return {k: np.array(np.asarray(chunk[k])[:, -1:]) for k in (ROT, ROOT, JOINTS) if k in chunk}
    except Exception:
        return None


def pull_to_pose(chunk, rest, end_frames=20, start_frames=6):
    """A copy of `chunk` whose first and last frames are exactly the `rest` pose, eased in and out.
    chunk: dict of numpy arrays with a time axis 1; rest: from last_frame(). Anything unusable returns the chunk unchanged."""
    try:
        if not rest or ROT not in rest or ROT not in chunk or ROOT not in chunk:
            return chunk
        rot = np.asarray(chunk[ROT])
        total = rot.shape[1]
        w = weights(total, end_frames, start_frames)
        if not w.any():
            return chunk
        out = dict(chunk)
        q = mat_to_quat(rot)                                   # [1, T, J, 4]
        qr = mat_to_quat(rest[ROT])                            # [1, 1, J, 4]
        wq = w[None, :, None]                                  # [1, T, 1]
        out[ROT] = quat_to_mat(slerp(q, qr, wq)).astype(rot.dtype, copy=False)
        root = np.asarray(chunk[ROOT])
        out[ROOT] = (root + (np.asarray(rest[ROOT]) - root) * w[None, :, None]).astype(root.dtype, copy=False)
        if JOINTS in chunk and JOINTS in rest:
            pj = np.asarray(chunk[JOINTS])
            out[JOINTS] = (pj + (np.asarray(rest[JOINTS]) - pj) * w[None, :, None, None]).astype(pj.dtype, copy=False)
        return out
    except Exception:
        return chunk


def small_wander(dev, release):
    """True if a held chunk ended close enough to the anchor for easing it back to be a small, invisible correction. A chunk that
    ended far away (dev, metres averaged over joints, against the stream's --hold-release) is the model trying to LEAVE the pose:
    pulling that back over a second would be a visible yank, so it is shown as generated and the anchor is let go."""
    return dev is not None and dev <= release
