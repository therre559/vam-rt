"""ardy_stream.py - continuous ARDY generation -> VaM, one chunk at a time.

Unlike ardy_to_vam.py (one independent clip per prompt), this keeps the character's motion
history between chunks and uses ARDY's own streaming call (model.autoregressive_step, the same
one the interactive demo uses). Each chunk continues from where the last one ended, in world
coordinates, so position and heading carry over automatically.

Put this file next to ardy_to_vam.py (the ARDY `scripts` folder) and run it from the ARDY
folder with the `ardy` conda environment active:

    python scripts/ardy_stream.py --out-dir "<VaM>\\Saves\\Animation\\ardy"

Then type prompts. The character keeps moving; a new prompt takes effect at the next chunk.
    > A person walks forward.
    > A person waves with their right hand.
    /reset       forget history (character restarts at the origin)
    quit

Sequences: an ACTION prompt ("stands up") describes a transition, so the model keeps re-doing it
every chunk. Follow it with a STATE prompt to hold the result:
    A person stands up. >> A person stands upright.
    A person sits down in a chair. @3 >> A person sits in a chair.      (@3 = play the first part 3 s)
Add [free] anywhere in the line for activities that keep moving (dancing, jogging, waving): it turns
off the "freeze a still hold in place" feature for that prompt, so a pause in the activity isn't mistaken
for a hold:
    A person dances. [free]
The first part plays for --action-seconds (default 2) unless @N is given, then it switches to the
last part, which holds until you change the prompt.

Useful options:
    --model core8        the Horizon8 checkpoint (0.4 s per step instead of 2 s): much more
                         responsive. Combine with --chunk-seconds to batch several steps per file.
    --chunk-seconds 1.2  how much motion goes in each BVH file
    --history 20         frames of history fed back each step (more = smoother, default = 1 token)
    --steps N            denoising steps (fewer = faster, rougher)
    --postprocess        run ARDY's foot-skate cleanup on each chunk (off by default: it adds
                         latency and can cause tiny seams at chunk edges)
"""

import argparse
import math
import os
import re
import sys
import threading
import time
import warnings
from pathlib import Path

os.environ.setdefault("TQDM_DISABLE", "1")
warnings.filterwarnings("ignore")
VERSION = "ardy_stream v22 (typed moves: /walk /goto /home /stop /speed /accel; duration guard; upside-down recovery, repeat requests, no-motion fallback)"


class _DropLines:
    """Wrap a stream and silently drop the endless 'MatMul8bitLt: ...' lines from bitsandbytes."""

    NEEDLE = "MatMul8bitLt"

    def __init__(self, stream):
        self._s = stream
        self._swallow_nl = False

    def write(self, text):
        if self._swallow_nl:
            self._swallow_nl = False
            if text == "\n":
                return 1
        if self.NEEDLE in text:
            kept = []
            for ln in text.splitlines(keepends=True):
                if self.NEEDLE in ln:
                    if not ln.endswith("\n"):
                        self._swallow_nl = True
                else:
                    kept.append(ln)
            rest = "".join(kept)
            if rest:
                self._s.write(rest)
            return len(text)
        return self._s.write(text)

    def __getattr__(self, name):
        return getattr(self._s, name)


if "--show-warnings" not in sys.argv:
    sys.stdout = _DropLines(sys.stdout)
    sys.stderr = _DropLines(sys.stderr)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ardy_to_vam as a2v  # noqa: E402  (reuses ArdyGenerator, save_npz, rename_bvh_text, ...)
try:
    import move_control  # noqa: E402  (typed moves)
except ImportError:      # an incomplete install must not stop the stream; only the typed moves are lost
    move_control = None

PICKUP_DELAY = 0.10  # the VaM plugin polls every 0.1 s


# --------------------------------------------------------------------------- helpers
def joint_speed(output, fps):
    """Average joint speed over a chunk, in m/s (0 = frozen). None if it can't be measured."""
    import numpy as np

    try:
        pj = np.asarray(output["posed_joints"])[0]  # [T, J, 3]
        if pj.shape[0] < 2:
            return None
        step = np.linalg.norm(np.diff(pj, axis=0), axis=-1)  # metres moved per frame, per joint
        return float(step.mean() * fps)
    except Exception:
        return None


def _joint_indices(model):
    """Indices of the joints the safety check needs (None if the skeleton doesn't expose them)."""
    try:
        bi = model.skeleton.bone_index
        idx = {"head": bi["Head"], "rfoot": bi["RightFoot"], "lfoot": bi["LeftFoot"]}
    except Exception:
        return None
    try:   # the hips give her facing direction (optional: only the moves need them)
        idx["lhip"], idx["rhip"] = bi["LeftUpLeg"], bi["RightUpLeg"]
    except Exception:
        pass
    return idx


def last_pose(output):
    """Joint positions of the chunk's final frame, [J, 3] (None if unavailable)."""
    import numpy as np

    try:
        return np.asarray(output["posed_joints"])[0, -1]
    except Exception:
        return None


def pose_distance(a, b):
    """Average distance (m) between two poses' joints."""
    import numpy as np

    return float(np.linalg.norm(np.asarray(a) - np.asarray(b), axis=-1).mean())


def slice_time(output, start, total):
    """Keep frames [start:] of every array whose time axis (axis 1) has length `total`.

    Returns (new_dict, set_of_time_keys). Works on a dict of torch tensors.
    """
    out, time_keys = {}, set()
    for k, v in output.items():
        if hasattr(v, "shape") and len(v.shape) >= 2 and v.shape[1] == total:
            out[k] = v[:, start:]
            time_keys.add(k)
        else:
            out[k] = v
    return out, time_keys


def concat_chunks(pieces, time_keys):
    """Join several (numpy) step outputs along the time axis."""
    import numpy as np

    if len(pieces) == 1:
        return pieces[0]
    merged = {}
    for k in pieces[0]:
        if k in time_keys:
            merged[k] = np.concatenate([p[k] for p in pieces], axis=1)
        else:
            merged[k] = pieces[0][k]
    return merged


# --------------------------------------------------------------------------- streaming core
class Streamer:
    """Holds the rolling motion history and produces one horizon of new frames per step()."""

    def __init__(self, gen, history_frames=None, steps=None, postprocess=False, cfg_weight=(2.0, 2.0), pp_constraints=False):
        self.gen = gen
        self.torch = gen.torch
        self.model = gen.model
        self.device = gen.device
        self.fps = gen.fps
        m = self.model
        self.patch = int(m.num_frames_per_token)
        self.horizon = int(m.gen_horizon_len)
        max_window = (int(10 * self.fps) // self.patch) * self.patch
        crop_max = ((max_window - self.horizon) // self.patch) * self.patch
        h = history_frames if history_frames else self.patch
        self.history_frames = max(self.patch, min((h // self.patch) * self.patch, crop_max))
        self.steps = int(steps) if steps else int(m.diffusion.num_base_steps)
        self.steps = max(1, min(self.steps, int(m.diffusion.num_base_steps)))
        self.postprocess = postprocess
        self.pp_constraints = pp_constraints  # also give the post-processing the root plan (only with postprocess on)
        self._pp_cset = None
        self.cfg_weight = tuple(cfg_weight)
        self.motion = None  # normalized motion tensor [1, T, D]; only the recent tail is kept
        self._text_cache = {}
        self._text_lock = threading.Lock()
        self.encoding = False  # True while a new prompt is being encoded (GPU is shared)
        self.anchor = None     # settled hold-pose history that hold chunks are generated from
        self.anchored = False  # True if the chunk being generated now is conditioned on the anchor
        self.anchor_pose = None  # joint positions of the frame the anchor ends on
        self.idx = _joint_indices(self.model)
        self._backup = None
        self._face = None        # (x, z) unit vector: where her pelvis faced at the end of the last chunk (ARDY world)
        self._face_sign = None   # which perpendicular of the hip line is "forward"; learned once, the session starts facing +Z
        self._face_backup = None

    def reset(self):
        self.motion = None
        self._face = None
        self.anchor = None
        self.anchored = False
        self.anchor_pose = None

    def drop_anchor(self):
        self.anchor = None
        self.anchored = False
        self.anchor_pose = None

    def is_inverted(self, output, margin=0.15):
        """True if, at any point in the chunk, both feet are clearly higher than the head
        (handstand, cartwheel, flip...). VaM's physics body can't cope with that."""
        if not self.idx:
            return False
        try:
            import numpy as np

            pj = np.asarray(output["posed_joints"])[0]  # [T, J, 3]
            head = pj[:, self.idx["head"], 1]
            feet = np.minimum(pj[:, self.idx["rfoot"], 1], pj[:, self.idx["lfoot"], 1])
            return bool(((feet - head) > margin).any())
        except Exception:
            return False

    def rollback(self):
        """Undo the chunk that was just generated (history, anchor), as if it never happened."""
        if self._backup is not None:
            self.motion, self.anchor, self.anchored, self.anchor_pose = self._backup
            self._face = self._face_backup

    def begin_chunk(self, hold):
        """Call before generating a file's worth of steps. While holding a settled pose, every chunk
        restarts from the same saved anchor instead of from the previous chunk's output, so small
        errors can't accumulate. Not holding (or no anchor yet) = normal free-running generation."""
        self._backup = (self.motion, self.anchor, self.anchored, self.anchor_pose)
        self._face_backup = self._face
        if not hold:
            self.drop_anchor()
        elif self.anchor is not None:
            self.motion = self.anchor.clone()
            self.anchored = True
        else:
            self.anchored = False

    def end_chunk(self, hold, settled, pose=None):
        """Call after the steps. `settled` = the pose has been (nearly) still for long enough: save it.
        `pose` = the joints of this chunk's last frame, kept to notice if later chunks wander off."""
        if hold and settled and self.anchor is None and self.motion is not None:
            self.anchor = self.motion.clone()
            self.anchor_pose = pose

    def _embed(self, prompt):
        key = prompt.strip()
        hit = self._text_cache.get(key)
        if hit is not None:  # cached: never wait on an encode that is running for a different prompt
            return hit
        with self._text_lock:
            hit = self._text_cache.get(key)
            if hit is None:
                self.encoding = True
                try:
                    with self.torch.no_grad():
                        hit = self.model._encode_text([key])
                finally:
                    self.encoding = False
                self._text_cache[key] = hit
            return hit

    def prefetch(self, prompt):
        """Encode a prompt now (call this when the user types it) so the next chunk doesn't pay for it.
        Returns the seconds it took (0 if it was already cached)."""
        t0 = time.time()
        already = prompt.strip() in self._text_cache
        self._embed(prompt)
        return 0.0 if already else time.time() - t0

    def root_state(self):
        """(x, z, vx, vz) of the last frame in the rolling history: ARDY world metres and m/s. None without history.
        Everything in a root plan (ardy_control.py) is in this same frame."""
        try:
            if self.motion is None or int(self.motion.shape[1]) < 2:
                return None
            mr = self.model.motion_rep
            root = mr.extract_root(mr.unnormalize(self.motion))
            p = root[0, :, mr.slice_dict["root_pos"]]
            x, z = float(p[-1, 0]), float(p[-1, 2])
            px, pz = float(p[-2, 0]), float(p[-2, 2])
            return x, z, (x - px) * self.fps, (z - pz) * self.fps
        except Exception as e:  # never let a diagnostic take the stream down
            self._warn_once("root_state", f"could not read her root position ({e})")
            return None

    def root_pose(self):
        """(x, z, heading, vx, vz) of her root at the end of the last generated chunk, in ARDY world metres and m/s. The heading is
        0 for +Z and grows towards +X. Before anything is generated she is at the origin facing +Z. NOTE: this is the END of the
        last chunk, which VaM plays 2-4 s later; it is only where she is on screen while she stands still."""
        st = self.root_state()
        x, z, vx, vz = st if st else (0.0, 0.0, 0.0, 0.0)
        f = self._face if self.motion is not None else None
        return x, z, (math.atan2(f[0], f[1]) if f else 0.0), vx, vz

    def _update_face(self, out):
        """Remember where her pelvis faces in the last frame of `out` (from the hip joints)."""
        try:
            if not self.idx or "lhip" not in self.idx:
                return
            pj = out["posed_joints"][0]

            def forward_at(t):
                l, r = pj[t][self.idx["lhip"]], pj[t][self.idx["rhip"]]
                dx, dz = float(r[0] - l[0]), float(r[2] - l[2])
                n = math.hypot(dx, dz)
                return (-dz / n, dx / n) if n > 1e-6 else None

            if self._face_sign is None:     # a session starts facing +Z: choose the sign so the first frames do
                first = [v for v in (forward_at(t) for t in range(min(5, len(pj)))) if v]
                if first:
                    self._face_sign = 1.0 if sum(v[1] for v in first) >= 0 else -1.0
            if self._face_sign is not None:
                f = forward_at(len(pj) - 1)
                if f:
                    self._face = (self._face_sign * f[0], self._face_sign * f[1])
        except Exception as e:  # a diagnostic must never take the stream down
            self._warn_once("face", f"could not read her facing direction ({e})")

    def _warn_once(self, key, text):
        seen = getattr(self, "_warned", None)
        if seen is None:
            seen = self._warned = set()
        if key not in seen:
            seen.add(key)
            print(f"  WARNING: {text}")

    def _constraint_tensors(self, plan, hist_len):
        """Turn a root plan into the model's (motion_mask, observed_motion) with the recipe NVIDIA's interactive demo uses
        (scripts/interactive_demo/gen_constraints.py): a Root2DConstraintSet -> create_conditions_from_constraints ->
        normalize -> multiply by the mask. Returns (model_frames, mask, observed). Raises if anything is not as expected."""
        import ardy_control as ctl
        from ardy.constraints import Root2DConstraintSet

        torch, m = self.torch, self.model
        max_window = (int(10 * self.fps) // self.patch) * self.patch
        model_frames, frames, xz = ctl.constraint_frames(plan, hist_len, self.horizon, self.patch, max_window)
        if not frames:
            raise ValueError("no waypoint falls inside the model window")
        frame_idx = torch.tensor(frames)                                            # CPU long, as in the demo
        root_pos_2d = torch.tensor(xz, dtype=torch.float32, device=self.device)    # [N, 2] = (x, z)
        cset = Root2DConstraintSet(m.motion_rep.skeleton, frame_idx, root_pos_2d)
        observed, mask = m.motion_rep.create_conditions_from_constraints(
            [cset], length=model_frames, to_normalize=False, device=self.device)
        observed = m.motion_rep.normalize(observed)
        observed = observed * mask       # unobserved frames are non-zero after normalization
        mask = mask.clone()
        mask[:hist_len] = 0.0            # history frames are never constrained
        observed[:hist_len] = 0.0
        # the same waypoints, shifted to the new horizon, for the optional post-processing
        self._pp_cset = None
        if self.pp_constraints:
            pf, pxz = ctl.postprocess_frames(frames, xz, hist_len, self.horizon)
            if pf:
                self._pp_cset = Root2DConstraintSet(m.motion_rep.skeleton, torch.tensor(pf),
                                                    torch.tensor(pxz, dtype=torch.float32, device=self.device))
        return model_frames, mask.unsqueeze(0), observed.unsqueeze(0)

    def step(self, prompt, plan=None):
        """Generate one horizon of new frames. Returns (numpy_output_dict, time_keys).
        `plan` (optional, ardy_control.RootPlan) asks the root to pass through waypoints; if building the constraint fails the
        step simply runs without it (one warning), so a bad plan can never stop the stream."""
        from ardy.postprocess import post_process_motion
        from ardy.tools import to_numpy

        torch, m = self.torch, self.model
        feat, mask = self._embed(prompt)
        hist = self.motion
        hist_len = 0 if hist is None else int(hist.shape[1])
        num_frames = hist_len + self.horizon      # what comes back (history + the new horizon)
        model_frames, motion_mask, observed_motion = num_frames, None, None
        self._pp_cset = None
        if plan:
            try:
                model_frames, motion_mask, observed_motion = self._constraint_tensors(plan, hist_len)
            except Exception as e:
                self._warn_once("constraints", f"root constraint not applied ({type(e).__name__}: {e}); generating without it")
                model_frames, motion_mask, observed_motion = num_frames, None, None

        with torch.no_grad():
            samples = m.autoregressive_step(
                num_frames=model_frames,
                num_denoising_steps=self.steps,
                motion_mask=motion_mask,
                observed_motion=observed_motion,
                cfg_weight=self.cfg_weight,
                texts=None,
                text_feat=feat,
                text_pad_mask=mask,
                init_history_sequence=hist,
                init_global_translation=None,  # model defaults: origin, facing +Z (first step only)
                init_first_heading_angle=None,
            )
            unnorm = m.motion_rep.unnormalize(samples)
            full = m.motion_rep.inverse(unnorm, is_normalized=False)

        new, time_keys = slice_time(full, hist_len, num_frames)
        self._update_face(new)

        if self.postprocess:
            corrected = post_process_motion(
                new["local_rot_mats"],
                new["root_positions"],
                new["foot_contacts"],
                m.skeleton,
                constraint_lst=[self._pp_cset] if self._pp_cset is not None else None,
            )
            new.update(corrected)

        # roll the history forward (uncorrected samples, same as the model produced them)
        tail = samples if hist is None else torch.cat([hist, samples[:, hist_len:]], dim=1)
        keep = (min(tail.shape[1], self.history_frames) // self.patch) * self.patch
        self.motion = tail[:, -keep:].clone()

        return to_numpy(new), time_keys


# --------------------------------------------------------------------------- BVH export
_converter_mod = None


def _load_converter(path):
    """Import ardy2bvh.py once so we can call write_bvh() directly (no subprocess per chunk)."""
    global _converter_mod
    if _converter_mod is None:
        import importlib.util

        spec = importlib.util.spec_from_file_location("ardy2bvh_inproc", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _converter_mod = mod
    return _converter_mod


def _swap_in(tmp_path, final, tries=50, delay=0.02):
    """Atomically replace `final`. Windows refuses while VaM has the file open, so retry briefly."""
    err = None
    for _ in range(tries):
        try:
            os.replace(tmp_path, final)
            return
        except PermissionError as e:  # VaM is reading the file right now
            err = e
            time.sleep(delay)
    raise err


def export_chunk(output, fps, text, args, stem):
    """Arrays -> BVH (in-process) -> rename joints -> atomic write of latest_vam.bvh. Returns seconds taken."""
    import numpy as np

    t0 = time.time()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    conv = _load_converter(args.converter)
    rot = np.asarray(output["local_rot_mats"], dtype=np.float64)
    root = np.asarray(output["root_positions"], dtype=np.float64)
    if rot.ndim == 5:  # drop the batch dimension (batch of 1)
        rot, root = rot[0], root[0]

    raw = out_dir / "latest_vam.bvh.raw"
    conv.write_bvh(raw, rot, root, fps, args.scale)
    with open(raw, newline="") as f:
        body = f.read()
    body, _, _ = a2v.rename_bvh_text(body)

    tmp_final = out_dir / "latest_vam.bvh.tmp"
    final = out_dir / "latest_vam.bvh"
    with open(tmp_final, "w", newline="") as f:
        f.write(body)
    _swap_in(tmp_final, final)
    if args.keep:
        with open(out_dir / f"{stem}.bvh", "w", newline="") as f:
            f.write(body)
    return time.time() - t0


# --------------------------------------------------------------------------- the loop
class State:
    """Shared between the input threads and the generator. `plan` is a list of [prompt, chunks_left];
    chunks_left None means 'hold until changed' (always the last entry)."""

    def __init__(self, steps, raw, free=False):
        self.plan = [list(x) for x in steps]
        self._raw = raw
        self.had_timed = any(n is not None for _, n in steps)  # has timed parts that end, then a hold
        self.fallbacks = {}  # {prompt: plainer prompt to use if it produces no movement}
        self.free = free  # True = never anchor this plan (an activity, not a held pose)
        self.lock = threading.Lock()
        self.stop = False
        self.reset = False
        self.set_time = time.monotonic()
        self.fresh = False  # True until the first chunk of a newly set plan has been taken

    def raw(self):
        """The plan text while the plan is still in effect. Once a timed plan has played out (only its final
        hold is left) this is None, so asking for the same thing again starts it again instead of being
        dropped as 'already doing that'."""
        with self.lock:
            if self.had_timed and len(self.plan) == 1:
                return None
            return self._raw

    def swap_fallback(self, prompt):
        """Replace the current part's prompt with its fallback (once). Returns the fallback, or None."""
        with self.lock:
            fb = self.fallbacks.pop(prompt, None)
            if fb and self.plan and self.plan[0][0] == prompt:
                self.plan[0][0] = fb
                return fb
            return None

    def set_plan(self, steps, raw, free=False, fallbacks=None):
        with self.lock:
            self.fallbacks = dict(fallbacks or {})
            self.plan = [list(x) for x in steps]
            self.had_timed = any(n is not None for _, n in steps)
            self._raw = raw
            self.free = free
            self.set_time = time.monotonic()
            self.fresh = True

    def take(self):
        """(prompt, fresh, hold) for the next chunk; advances the plan when an action part has played out.
        `fresh` is True for the first chunk generated after a new plan was set; `hold` is True when this
        chunk is part of the final, open-ended state (the one that just holds)."""
        with self.lock:
            entry = self.plan[0]
            prompt = entry[0]
            hold = entry[1] is None
            fresh, self.fresh = self.fresh, False
            if entry[1] is not None:
                entry[1] -= 1
                if entry[1] <= 0 and len(self.plan) > 1:
                    self.plan.pop(0)
            return prompt, fresh, hold


SAFE_PROMPT = "A person stands upright."


class RunawayGuard:
    """The last part of a plan is open-ended ("hold until changed"). A pose settles by itself, but a movement (a walk, a dance, a
    wiggle) never does, so if one gets through it would run until something interrupts it. This watches the open-ended part: if it
    keeps moving (above `moving_speed` m/s) for `limit_s` seconds without ever settling, update() says so and the caller falls back
    to a safe hold. Timed parts are not watched (they end by themselves). limit_s = 0 turns it off."""

    def __init__(self, limit_s, moving_speed=0.12, calm_chunks=2):
        self.limit_s = limit_s
        self.moving_speed = moving_speed
        self.calm_chunks = calm_chunks
        self.reset()

    def reset(self):
        self.key = None
        self.moving_s = 0.0
        self.calm = 0

    def update(self, key, open_ended, speed, chunk_s):
        """key identifies the part being played (its prompt). Returns True when it has been moving for too long."""
        if not open_ended or self.limit_s <= 0:
            self.reset()
            return False
        if key != self.key:
            self.reset()
            self.key = key
        if speed is None:
            return False
        if speed >= self.moving_speed:
            self.moving_s += chunk_s
            self.calm = 0
        else:
            self.calm += 1
            if self.calm >= self.calm_chunks:   # it really settled: start counting again from zero
                self.moving_s = 0.0
        return self.moving_s >= self.limit_s


def _write_prompt(path, text):
    """Make the prompt file say `text` (atomic, so the watcher never sees half a line)."""
    if not path:
        return
    try:
        tmp = str(path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        os.replace(tmp, path)
    except OSError:
        pass


def _write_idle(path):
    """Make the prompt file say what the stream is really doing again."""
    _write_prompt(path, SAFE_PROMPT)


def recover_from_block(state, streamer, blocked, prompt_file=None):
    """Called after an upside-down chunk was rolled back. The last safe pose can itself be the start of the flip
    (it was, for 'the splits'), so retrying the same prompt forever freezes her. Escalate instead:
      1st block -> 'retry'    : try again (different random noise may be fine)
      2nd block -> 'standing' : drop the plan and ask for plain standing
      3rd block -> 'reset'    : throw the motion history away and restart from a neutral standing pose"""
    if blocked <= 1:
        return "retry"
    state.set_plan([[SAFE_PROMPT, None]], SAFE_PROMPT, False)
    _write_idle(prompt_file)
    if blocked == 2:
        return "standing"
    streamer.reset()
    return "reset"


def watchdog(state, prompt, hold, speed, dead, dead_speed, dead_chunks):
    """If an activity that has a fallback prompt produces (almost) no movement for `dead_chunks` chunks in a
    row, switch it to the fallback. `dead` is a small [prompt, count] list kept between calls.
    Returns the fallback prompt when it switched, else None."""
    if hold or speed is None or dead_chunks <= 0:
        dead[:] = [None, 0]
        return None
    if speed >= dead_speed:
        dead[:] = [prompt, 0]
        return None
    dead[:] = [prompt, dead[1] + 1 if dead[0] == prompt else 1]
    if dead[1] >= dead_chunks:
        fb = state.swap_fallback(prompt)
        if fb:
            dead[:] = [None, 0]
            return fb
    return None


def apply_typed_move(state, streamer, prompt, fresh, hold, open_ended, now=None):
    """A running typed move (/walk, /goto ...) overrides the text for this chunk and supplies a root plan; the normal prompt flow
    carries on underneath and takes over again when the move is over. Returns (prompt, plan, fresh, hold, open_ended)."""
    mover = getattr(state, "mover", None)
    if mover is None or not mover.active:
        return prompt, None, fresh, hold, open_ended
    pose = streamer.root_pose()
    mv = mover.next_chunk(pose, time.monotonic() if now is None else now)
    if mv is None:
        print(f"  move finished: {mover.result(pose)}; back to the normal prompts")
        streamer.drop_anchor()
        return prompt, None, fresh, hold, open_ended
    text, plan, note = mv
    print(f"  move: {note}  | ARDY pose x {pose[0]:.2f} z {pose[1]:.2f}, facing {math.degrees(pose[2]):.0f} deg")
    # a move is never a held pose and never open-ended, so neither the anchor nor the duration guard apply to it
    return text, plan, False, False, False


def worker(streamer, args, state):
    fps = streamer.fps
    steps_per_file = max(1, round(args.chunk_seconds * fps / streamer.horizon))
    chunk_dur = steps_per_file * streamer.horizon / fps / args.playback_speed
    est_end = 0.0          # monotonic time at which everything written so far has finished playing
    hold_prompt, still_n, off_hist = None, 0, []
    dead = [None, 0]       # no-movement watchdog: [prompt, consecutive still chunks]
    blocked = 0
    recent = [0.7]         # recent chunk costs (generate + export); seeded so chunk 2 starts early enough
    last_logged = None
    n = 0
    print(
        f"Streaming: {steps_per_file} step(s) x {streamer.horizon} frames per file "
        f"= {chunk_dur:.2f}s of motion, history {streamer.history_frames} frames, {streamer.steps} denoising steps, "
        f"text guidance {streamer.cfg_weight[0]:g}"
    )

    if args.metrics_file:  # the lab records which settings its results were measured under
        try:
            with open(args.metrics_file, "a", encoding="utf-8") as mf:
                mf.write(f"# settings model={args.model or 'default'} horizon={streamer.horizon} "
                         f"history={streamer.history_frames} steps={streamer.steps} "
                         f"cfg_text={streamer.cfg_weight[0]:g}\n")
        except OSError:
            pass

    guard = RunawayGuard(args.runaway_seconds)
    settled_prompt = None   # the last pose that really settled: where the duration guard sends her back to
    while not state.stop:
        # start the next chunk early enough that it is ready when the current one ends
        remaining = est_end - time.monotonic()
        need = min(max(recent), chunk_dur) + args.margin + (0.6 if streamer.encoding else 0.0)
        if remaining > need:
            time.sleep(0.01)
            continue
        with state.lock:
            if state.reset:
                streamer.reset()
                state.reset = False
                hold_prompt, still_n, off_hist = None, 0, []
        prompt, fresh, hold = state.take()
        open_ended = hold               # the last part of the plan: "until changed"
        hold = hold and not state.free  # from here on `hold` means "may be anchored"
        prompt, move_plan, fresh, hold, open_ended = apply_typed_move(state, streamer, prompt, fresh, hold, open_ended)
        if not prompt:
            time.sleep(0.05)
            continue
        if fresh:  # a new prompt was just set: forget any old anchor right away
            streamer.drop_anchor()
            still_n = 0
        if hold:
            if prompt != hold_prompt:
                still_n = 0
            hold_prompt = prompt
        else:
            hold_prompt, still_n = None, 0

        t0 = time.time()
        streamer.begin_chunk(hold)
        pieces, tkeys = [], set()
        for _ in range(steps_per_file):
            piece, tkeys = streamer.step(prompt, move_plan)
            pieces.append(piece)
        t_gen = time.time() - t0
        merged = concat_chunks(pieces, tkeys)
        if not args.allow_inverted and streamer.is_inverted(merged):
            streamer.rollback()  # forget this chunk; the model carries on from the last safe pose
            blocked += 1
            action = recover_from_block(state, streamer, blocked, args.prompt_file)
            if action == "retry":
                print("  BLOCKED: that chunk was upside down (feet above head), which VaM's physics can't handle. "
                      "Trying again.")
            elif action == "standing":
                print("  still upside down: dropping that motion and going back to standing.")
            else:
                print("  still upside down from that pose: restarting her motion from a neutral standing pose "
                      "(launch with --allow-inverted to send such poses anyway).")
                blocked, hold_prompt, still_n, off_hist = 0, None, 0, []
            time.sleep(0.2)
            continue
        blocked = 0
        speed = joint_speed(merged, fps)
        if guard.update(prompt, open_ended, speed, chunk_dur):
            fb = settled_prompt or SAFE_PROMPT
            print(f"  duration guard: '{prompt}' kept moving for {args.runaway_seconds:.0f}s without settling; "
                  f"going back to '{fb}'")
            state.set_plan([[fb, None]], fb)
            _write_prompt(args.prompt_file, fb)
            guard.reset()
        fb = watchdog(state, prompt, hold, speed, dead, args.dead_speed, args.dead_chunks)
        if fb:
            print(f"  no-motion watchdog: '{prompt}' produced no movement for {args.dead_chunks} chunks "
                  f"(motion {speed:.2f} m/s); switching to '{fb}'")
        pose = last_pose(merged)
        dev = None
        if streamer.anchored and streamer.anchor_pose is not None and pose is not None:
            # how far did this chunk end from the anchor pose? A true hold stays close to it.
            dev = pose_distance(pose, streamer.anchor_pose)
            off_hist = (off_hist + [dev > args.hold_release])[-4:]
            if sum(off_hist) >= 2:  # 2 of the last 4 chunks ended far from the anchor
                print(f"  anchor released: the model keeps moving away from the anchored pose "
                      f"({dev:.2f} m off); generating freely again")
                streamer.drop_anchor()
                still_n, off_hist = 0, []
        else:
            off_hist = []
        if hold and not streamer.anchored and speed is not None and speed < args.hold_still:
            still_n += 1
        elif hold and not streamer.anchored:
            still_n = 0
        streamer.end_chunk(hold, bool(args.hold_settle) and still_n >= args.hold_settle, pose)
        if hold and streamer.anchored:
            settled_prompt = prompt   # she has really settled into this pose: it is a safe place to return to
        t_exp = None
        for attempt in range(5):  # the model's history already moved on, so a lost chunk means a jump
            try:
                t_exp = export_chunk(merged, fps, prompt, args, f"{slug(prompt)}_{n:04d}")
                break
            except Exception as e:
                print(f"  export error (attempt {attempt + 1}/5): {e}")
                time.sleep(0.1)
        if t_exp is None:
            print("  chunk could NOT be written; expect a jump in the motion")
            continue

        now = time.monotonic()
        start_play = max(now + PICKUP_DELAY, est_end)
        gap = max(0.0, now + PICKUP_DELAY - est_end) if est_end else 0.0
        est_end = start_play + chunk_dur
        if fresh and n > 0:
            print(
                f"  latency: the first chunk with the new prompt was written {now - state.set_time:.1f}s after it "
                f"was set, and should start playing in ~{start_play - now:.1f}s more "
                f"(about {now - state.set_time + start_play - now:.1f}s in total from the moment it was set)"
            )
        if n > 0:
            recent = (recent + [t_gen + t_exp])[-4:]
        n += 1
        slow = (t_gen + t_exp) > 0.8 * chunk_dur
        try:  # model-space heights of the last frame: if these creep down over minutes, the model is drifting
            heights = (f", root y {float(merged['root_positions'][0, -1, 1]):.2f}"
                       f", lowest joint {float(merged['posed_joints'][0, -1, :, 1].min()):.2f}")
        except Exception:
            heights = ""
        if args.metrics_file:  # one line per chunk, read by ardy_lab.py: time, motion, root y, hold, prompt
            try:
                ry = float(merged["root_positions"][0, -1, 1])
            except Exception:
                ry = float("nan")
            try:
                with open(args.metrics_file, "a", encoding="utf-8") as mf:
                    mf.write(f"{time.time():.2f}\t{(speed if speed is not None else float('nan')):.3f}\t{ry:.3f}\t"
                             f"{int(bool(hold))}\t{prompt}\n")
            except OSError:
                pass
        if speed is not None:
            heights += f", motion {speed:.2f} m/s"
        if dev is not None:
            heights += f", {dev:.2f} m off anchor"
        # quiet by default so the screen isn't scrolling while you type: only log on news
        if args.verbose or gap > 0.05 or slow or prompt != last_logged or n % 10 == 1:
            last_logged = prompt
            print(
                f"  chunk {n}: gen {t_gen*1000:.0f} ms, export {t_exp*1000:.0f} ms"
                f"{f', GAP {gap:.2f}s (playback ran dry)' if gap > 0.05 else ''}"
                f"{', SLOW (close to the chunk length)' if slow else ''}"
                f"{heights}{', anchored hold' if streamer.anchored else ''}  | '{prompt}'"
            )


def clean_prompt(line):
    """Drop a trailing '| 2.5' (that syntax belongs to ardy_to_vam.py) and tidy whitespace."""
    if "|" in line:
        head, _, tail = line.rpartition("|")
        try:
            float(tail.strip())
            line = head
        except ValueError:
            pass
    return " ".join(line.split())


_AT = re.compile(r"\s*@\s*(\d+(?:\.\d+)?)\s*s?\s*$", re.I)


MAX_PART_SECONDS = 180   # no single timed part may last longer than this, whatever the prompt file says


def parse_plan(text, chunk_dur, default_seconds):
    """'A >> B' -> [[A, n_chunks], [B, None]]. '@3' after a non-final part sets its length in seconds."""
    parts = [x.strip() for x in text.split(">>")]
    parts = [x for x in parts if x]
    steps = []
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        seconds = None
        m = _AT.search(part)
        if m:
            seconds = float(m.group(1))
            part = part[: m.start()]
        prompt = clean_prompt(part)
        if not prompt:
            continue
        if last:
            steps.append([prompt, None])
        else:
            sec = min(seconds if seconds is not None else default_seconds, MAX_PART_SECONDS)
            steps.append([prompt, max(1, math.ceil(sec / chunk_dur - 1e-9))])
    if steps and steps[-1][1] is not None:  # a trailing action with no hold state: just keep it
        steps[-1][1] = None
    return steps


_FREE = re.compile(r"\[\s*free\s*\]", re.I)
_CLI = re.compile(r"\s--[A-Za-z]")


def split_fallbacks(text):
    """'STYLED ?? PLAIN @60 >> HOLD' -> ('STYLED @60 >> HOLD', {'STYLED': 'PLAIN'}).
    PLAIN is used only if STYLED turns out to produce no movement."""
    fallbacks, parts = {}, []
    for part in text.split(">>"):
        if "??" in part:
            head, _, tail = part.partition("??")
            at = ""
            m = _AT.search(tail)
            if m:
                at = f" @{m.group(1)}"
                tail = tail[: m.start()]
            primary, fb = clean_prompt(head), clean_prompt(tail)
            if primary and fb:
                fallbacks[primary] = fb
            part = head + at
        parts.append(part)
    return ">>".join(parts), fallbacks


def prepare_line(line):
    """Split a prompt line into (text, free, removed_flags).
    - '[free]' marks an activity that must never be anchored.
    - anything from the first '--option' on is dropped: those belong on the launch command, not here."""
    removed = None
    m = _CLI.search(line)
    if m:
        removed = line[m.start():].strip()
        line = line[: m.start()]
    free = _FREE.search(line) is not None
    line = _FREE.sub("", line)
    return " ".join(line.split()), free, removed


def describe_plan(steps):
    out = []
    for prompt, n in steps:
        out.append(prompt if n is None else f"{prompt} [{n} chunk{'s' if n != 1 else ''}]")
    return "  >>  ".join(out)


def apply_line(streamer, state, line, chunk_dur, default_seconds, source):
    """Parse a typed/file line into a plan, encode its prompts, and make it current."""
    text, free, removed = prepare_line(line)
    text, fallbacks = split_fallbacks(text)
    steps = parse_plan(text, chunk_dur, default_seconds)
    if not steps:
        return False
    raw = describe_plan(steps) + ("  [free]" if free else "")
    if raw == state.raw():
        return False
    if removed:
        print(f"  note: ignored '{removed}' in the prompt. Options like that go on the launch command, not in the prompt.")
    dt = streamer.prefetch(steps[0][0])  # encode before switching so the generator never waits
    state.set_plan(steps, raw, free, fallbacks)
    print(f"  prompt set ({source}): {raw}  (encoded in {dt*1000:.0f} ms)")
    for prompt, _ in steps[1:]:
        streamer.prefetch(prompt)  # the hold state is needed a chunk or two from now
    for fb in fallbacks.values():
        streamer.prefetch(fb)      # so a switch to the fallback never waits on the text encoder
    if fallbacks:
        print("  (if that produces no movement it falls back to: " + "; ".join(fallbacks.values()) + ")")
    return True


def prompt_file_watcher(streamer, state, path, chunk_dur, default_seconds):
    """Change the prompt by editing + saving a text file (first non-empty line). No typing in the
    terminal while the log scrolls, and it is the hook a Voxta/LLM bridge can write to later."""
    last_sig = None
    while not state.stop:
        try:
            st = os.stat(path)
            sig = (st.st_mtime_ns, st.st_size)
            if sig != last_sig:
                last_sig = sig
                text = ""
                with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
                    for ln in f:
                        if ln.strip():
                            text = ln
                            break
                apply_line(streamer, state, text, chunk_dur, default_seconds, "file")
        except FileNotFoundError:
            pass
        except Exception as e:
            print("  prompt file error:", e)
        time.sleep(0.2)


def first_prompt_line(path):
    """First non-empty line of the prompt file, cleaned ('' if the file is missing or empty)."""
    try:
        with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
            for ln in f:
                if ln.strip():
                    return clean_prompt(ln)
    except FileNotFoundError:
        pass
    return ""


def initial_prompt(args):
    """The prompt file (if there is one and it has text) wins over --prompt, so a stale launch
    argument can never produce a stray first chunk. Returns (prompt, where_it_came_from)."""
    if args.prompt_file:
        from_file = first_prompt_line(args.prompt_file)
        if from_file:
            return from_file, "prompt file"
        Path(args.prompt_file).write_text(clean_prompt(args.prompt) + "\n", encoding="utf-8")
    return clean_prompt(args.prompt), "launch argument"


def slug(text):
    return a2v.slugify(text, 24)


MOVE_HELP = """Typed moves (ARDY world: metres, she starts at the origin facing +Z; give them while she STANDS STILL):
  /walk <m>         walk this far straight ahead
  /goto <x> <z>     walk to a point
  /go <fwd> <right> walk to a point this far ahead and to her right (negative = behind / left)
  /home             walk back to the origin (where she started)
  /stop             brake and stand
  /speed <m/s>      walking speed (0.5 - 1.6)
  /accel <m/s2>     how hard she speeds up and brakes (0.5 - 2.0; lower = gentler; short moves are the most abrupt)
  /where            print where ARDY thinks she is (compare with the Senses plugin's position report in VaM)
A move ends by itself on arrival, or after a timeout; the farthest one move may go is --max-move."""


def handle_move_command(line, streamer, state):
    """Typed moves. Returns True if the line was one of them (handled, even if refused)."""
    parts = line.split()
    cmd = parts[0].lower() if parts else ""
    if cmd not in ("/walk", "/goto", "/go", "/home", "/stop", "/speed", "/accel", "/where", "/moves"):
        return False
    mover = getattr(state, "mover", None)
    if cmd == "/moves":
        print(MOVE_HELP)
        return True
    pose = streamer.root_pose()
    if cmd == "/where":
        print(f"  ARDY pose: x {pose[0]:.2f} z {pose[1]:.2f}, facing {math.degrees(pose[2]):.0f} deg (0 = +Z, positive towards +X), "
              f"speed {math.hypot(pose[3], pose[4]):.2f} m/s; move: {mover.state if mover else 'off'}")
        return True
    if mover is None:
        print("  moves are switched off (start the stream without --max-move 0)")
        return True
    now = time.monotonic()
    try:
        nums = [float(x) for x in parts[1:]]
    except ValueError:
        print("  numbers only, for example /walk 3")
        return True
    if cmd == "/stop":
        ok, msg = mover.stop(pose, now)
    elif cmd == "/home":
        ok, msg = mover.goto(pose, (0.0, 0.0), now, "home")
    elif cmd == "/speed":
        if len(nums) != 1:
            print("  usage: /speed 1.0")
            return True
        print(f"  walking speed {mover.set_speed(nums[0]):g} m/s")
        return True
    elif cmd == "/accel":
        if len(nums) != 1:
            print("  usage: /accel 1.0")
            return True
        print(f"  acceleration {mover.set_accel(nums[0]):g} m/s^2")
        return True
    elif cmd == "/walk" and len(nums) == 1 and nums[0] > 0:
        ok, msg = mover.walk(pose, nums[0], now)
    elif cmd == "/goto" and len(nums) == 2:
        ok, msg = mover.goto(pose, (nums[0], nums[1]), now)
    elif cmd == "/go" and len(nums) == 2:
        ok, msg = mover.go_relative(pose, nums[0], nums[1], now)
    else:
        print("  usage: /walk 3   /goto 2 4   /go 2 1   /home   /stop   (/moves for help)")
        return True
    if ok and cmd != "/stop" and math.hypot(pose[3], pose[4]) > 0.3:
        msg += "  (she is moving now: ARDY's pose is ahead of what is on screen, so this goal may be off; give moves while she stands)"
    print(f"  {'OK' if ok else 'refused'}: {msg}")
    return True


def main():
    p = argparse.ArgumentParser(description="ARDY continuous streaming -> VaM BVH")
    p.add_argument("--prompt", default="A person stands still.", help="Initial prompt")
    p.add_argument("--out-dir", default=a2v.DEFAULT_OUT_DIR)
    p.add_argument("--converter", default=a2v.DEFAULT_CONVERTER, help="Path to ardy2bvh.py")
    p.add_argument("--scale", type=float, default=100)
    p.add_argument("--model", default=None, help="e.g. core8 for the Horizon8 checkpoint")
    p.add_argument("--checkpoints_dir", default=None)
    p.add_argument("--full-encoder", action="store_true")
    p.add_argument("--chunk-seconds", type=float, default=2.0, help="Motion per BVH file")
    p.add_argument("--history", type=int, default=None, help="History frames fed back each step")
    p.add_argument("--steps", type=int, default=None, help="Denoising steps")
    p.add_argument("--action-seconds", type=float, default=2.0,
                   help="How long the first part of 'action >> state' plays (default 2; override with @N)")
    p.add_argument("--hold-settle", type=int, default=2,
                   help="How many consecutive nearly-still chunks a hold needs before its pose is saved as an "
                        "anchor that later chunks restart from (stops slow drift). 0 = off")
    p.add_argument("--hold-still", type=float, default=0.05,
                   help="'Nearly still' = average joint speed below this many m/s (see 'motion' in the log)")
    p.add_argument("--metrics-file", default=None,
                   help="Append one line per chunk (time, motion m/s, root y, hold, prompt) here; used by ardy_lab.py")
    p.add_argument("--dead-speed", type=float, default=0.05,
                   help="Below this joint speed (m/s) a chunk counts as 'no movement' for the fallback watchdog")
    p.add_argument("--max-move", type=float, default=8.0,
                   help="typed moves (/walk /goto /home): the farthest one move may ask for, metres (default 8, 0 = moves off)")
    p.add_argument("--move-speed", type=float, default=1.0, help="walking speed of typed moves, m/s (default 1.0; /speed changes it)")
    p.add_argument("--move-accel", type=float, default=1.0,
                   help="how hard typed moves speed up and brake, m/s^2 (default 1.0; lower = gentler starts and stops; /accel changes it)")
    p.add_argument("--runaway-seconds", type=float, default=60,
                   help="duration guard: an open-ended movement that keeps moving this long without settling is cut off and she "
                        "goes back to her last settled pose (0 = off)")
    p.add_argument("--dead-chunks", type=int, default=3,
                   help="Consecutive no-movement chunks before an activity switches to its fallback prompt (0 = off)")
    p.add_argument("--allow-inverted", action="store_true",
                   help="Send upside-down poses (handstands, flips) to VaM instead of blocking them")
    p.add_argument("--hold-release", type=float, default=0.06,
                   help="Release the anchor if 2 of the last 4 hold chunks end this many metres (average per joint) "
                        "away from it: the model is trying to leave that pose")
    p.add_argument("--cfg-text", type=float, default=2.0,
                   help="Text guidance strength (default 2.0). Higher = follows the prompt harder, can look stiffer")
    p.add_argument("--margin", type=float, default=0.35, help="Extra seconds of safety before a chunk is due")
    p.add_argument("--playback-speed", type=float, default=1.0, help="Match the player's Speed (%%)/100")
    p.add_argument("--postprocess", action="store_true")
    p.add_argument("--keep", action="store_true", help="Also keep every chunk as its own .bvh")
    p.add_argument("--prompt-file", default=None,
                   help="Text file to watch: edit + save it to change the prompt (created if missing)")
    p.add_argument("--verbose", action="store_true", help="Log every chunk (default: only on news)")
    p.add_argument("--show-warnings", action="store_true", help="Don't filter the MatMul8bitLt warning spam")
    args = p.parse_args()

    if not Path(args.converter).exists():
        raise SystemExit(f"Can't find ardy2bvh.py at {args.converter} (use --converter).")
    if not args.full_encoder:
        os.environ.setdefault("ARDY_TEXT_ENCODER_INT8", a2v.INT8_REPO)

    gen = a2v.ArdyGenerator(args.model, args.checkpoints_dir)
    streamer = Streamer(
        gen, history_frames=args.history, steps=args.steps, postprocess=args.postprocess,
        cfg_weight=(args.cfg_text, 2.0),
    )

    steps_per_file = max(1, round(args.chunk_seconds * gen.fps / streamer.horizon))
    chunk_dur = steps_per_file * streamer.horizon / gen.fps / args.playback_speed

    start_text, source = initial_prompt(args)
    text, free, removed = prepare_line(start_text)
    steps = parse_plan(text, chunk_dur, args.action_seconds)
    if not steps:
        raise SystemExit("The starting prompt is empty.")
    if removed:
        print(f"note: ignored '{removed}' in the prompt. Options like that go on the launch command, not in the prompt.")
    t0 = time.time()
    for prompt, _ in steps:
        streamer.prefetch(prompt)  # encode BEFORE streaming starts, so chunk 1 isn't slowed
    state = State(steps, describe_plan(steps) + ("  [free]" if free else ""), free)
    state.mover = (move_control.MoveDriver(streamer.fps, speed=args.move_speed, max_move=args.max_move, max_accel=args.move_accel)
                   if (move_control is not None and args.max_move > 0) else None)
    if state.mover is not None:    # encode the move texts now: the first move used to pay for it with a playback gap
        try:
            for text in (move_control.WALK, move_control.STAND):
                streamer._embed(text)
        except Exception as e:
            print(f"  (could not pre-encode the move texts: {e})")
    if move_control is None and args.max_move > 0:
        print("NOTE: typed moves are unavailable: move_control.py was not found next to this script (run tools\\deploy.bat).")
    print(f"Starting prompt ({source}): {state.raw()}  (encoded in {(time.time()-t0)*1000:.0f} ms)")

    t = threading.Thread(target=worker, args=(streamer, args, state), daemon=True)
    t.start()

    if args.prompt_file:
        pf = Path(args.prompt_file)
        threading.Thread(target=prompt_file_watcher, args=(streamer, state, str(pf), chunk_dur, args.action_seconds),
                         daemon=True).start()
        print(f"Watching prompt file: {pf}  (edit the first line and save)")
    print(VERSION)
    print("Type a prompt to change what the character does. /reset to restart, quit to exit.")
    if state.mover is not None:
        print("Moves (she must be standing still; needs In Place OFF in the BVH Player to travel): /walk 3  /goto 2 4  /go 2 1  /home  "
              "/stop  /speed 1.0  /accel 1.0  /where   (/moves for help)")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line.lower() in ("quit", "exit", "q"):
            break
        if line == "/reset":
            with state.lock:
                state.reset = True
            print("  history cleared")
            continue
        if handle_move_command(line, streamer, state):
            continue
        apply_line(streamer, state, line, chunk_dur, args.action_seconds, "typed")
    state.stop = True
    t.join(timeout=5)


if __name__ == "__main__":
    main()
