"""Tests the stream's typed-move plumbing without a GPU: facing from the hips, the pose, rollback, and the worker override.
Run from the server folder:  python tests/test_stream_moves.py"""
import io
import contextlib
import math
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import numpy as np  # noqa: E402
import ardy_stream as st  # noqa: E402
import move_control as mc  # noqa: E402

bad = 0


def check(name, cond, detail=""):
    global bad
    bad += not cond
    print(("ok   " if cond else "BAD  ") + name + ("" if cond else "   " + str(detail)))


def quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


# ---------------- facing from the hips ----------------
def skeleton_frames(heading_deg, frames=10, swap=False):
    """posed_joints [1, T, 2, 3]: joint 0 = left hip, joint 1 = right hip, hips 0.2 m apart, pelvis facing heading_deg."""
    h = math.radians(heading_deg)
    fwd = (math.sin(h), math.cos(h))
    right = (fwd[1], -fwd[0])
    left_p = (-right[0] * 0.1, -right[1] * 0.1)
    right_p = (right[0] * 0.1, right[1] * 0.1)
    if swap:
        left_p, right_p = right_p, left_p
    frame = [[left_p[0], 0.9, left_p[1]], [right_p[0], 0.9, right_p[1]]]
    return {"posed_joints": np.array([[frame] * frames], dtype=float)}


def fake_streamer():
    return types.SimpleNamespace(idx={"lhip": 0, "rhip": 1}, _face=None, _face_sign=None, _face_backup=None, motion=None,
                                 _warned=set(), _warn_once=lambda k, t: None)


for swap in (False, True):
    fs = fake_streamer()
    st.Streamer._update_face(fs, skeleton_frames(0, swap=swap))
    check(f"first chunk facing +Z is recognised as forward = (0, 1) (hips {'swapped' if swap else 'normal'})",
          fs._face is not None and abs(fs._face[0]) < 1e-6 and abs(fs._face[1] - 1) < 1e-6, fs._face)
    st.Streamer._update_face(fs, skeleton_frames(90, swap=swap))
    check(f"a later chunk facing +X (90 deg) gives heading 90 (hips {'swapped' if swap else 'normal'})",
          abs(math.degrees(math.atan2(fs._face[0], fs._face[1])) - 90) < 0.1, fs._face)
    st.Streamer._update_face(fs, skeleton_frames(-135, swap=swap))
    check("... and -135 deg", abs(math.degrees(math.atan2(fs._face[0], fs._face[1])) + 135) < 0.1, fs._face)
fs = types.SimpleNamespace(idx=None, _face=None, _face_sign=None, _warn_once=lambda k, t: None)
st.Streamer._update_face(fs, skeleton_frames(0))
check("a skeleton without hip joints: no crash, no facing", fs._face is None)
fs = fake_streamer()
st.Streamer._update_face(fs, {"posed_joints": "garbage"})
check("garbage input never raises (a diagnostic must not take the stream down)", fs._face is None)

# ---------------- root_pose ----------------
fs = fake_streamer()
fs.root_state = lambda: None
check("before anything is generated: the origin, facing +Z, standing", st.Streamer.root_pose(fs) == (0.0, 0.0, 0.0, 0.0, 0.0))
fs.motion = object()
fs.root_state = lambda: (1.0, 2.0, 0.5, 0.0)
fs._face = (1.0, 0.0)           # facing +X
x, z, h, vx, vz = st.Streamer.root_pose(fs)
check("with history: position, velocity from the history and heading from the hips", (x, z, vx, vz) == (1.0, 2.0, 0.5, 0.0) and abs(h - math.pi / 2) < 1e-9, (x, z, h))

# ---------------- rollback and reset keep the facing consistent ----------------
fs = types.SimpleNamespace(motion="M", anchor=None, anchored=False, anchor_pose=None, _face=(0.0, 1.0), _face_backup=None, _backup=None)
fs.drop_anchor = types.MethodType(st.Streamer.drop_anchor, fs)
st.Streamer.begin_chunk(fs, False)
fs._face = (1.0, 0.0)                      # the chunk turned her ...
st.Streamer.rollback(fs)                   # ... but it was rolled back (upside-down guard)
check("rolling a chunk back also rolls back her facing", fs._face == (0.0, 1.0), fs._face)
st.Streamer.reset(fs)
check("a reset forgets her facing (she restarts facing +Z)", fs._face is None)

# ---------------- the worker override ----------------
class PoseStreamer:
    def __init__(self): self.dropped = 0
    def root_pose(self): return (0.0, 0.0, 0.0, 0.0, 0.0)
    def drop_anchor(self): self.dropped += 1


state = types.SimpleNamespace(mover=mc.MoveDriver(20))
ps = PoseStreamer()
out = quiet(st.apply_typed_move, state, ps, "A person stands upright.", True, True, True, 100.0)
check("no move running: the normal prompt, no plan, flags untouched", out == ("A person stands upright.", None, True, True, True), out)
state.mover.walk(ps.root_pose(), 3.0, 100.0)
prompt, plan, fresh, hold, open_ended = quiet(st.apply_typed_move, state, ps, "A person stands upright.", True, True, True, 100.0)
check("a move running: it overrides the text", prompt == mc.WALK, prompt)
check("... supplies a root plan", bool(plan))
check("... and is never fresh, held or open-ended (no anchor, no duration guard)", (fresh, hold, open_ended) == (False, False, False))
state.mover.state = state.mover.SETTLING
state.mover.settle_left = 0
out = quiet(st.apply_typed_move, state, ps, "A person stands upright.", False, True, True, 102.0)
check("when the move is over the normal flow takes over again", out[0] == "A person stands upright." and out[1] is None and not state.mover.active, out)
check("... and the anchor is dropped so the pose restarts cleanly", ps.dropped == 1, ps.dropped)
check("a stream started with moves off has no mover: nothing changes",
      quiet(st.apply_typed_move, types.SimpleNamespace(), ps, "p", True, False, False, 1.0) == ("p", None, True, False, False))

print("\nALL GOOD" if not bad else f"\nFAILURES: {bad}")
sys.exit(1 if bad else 0)
