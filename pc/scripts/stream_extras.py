"""stream_extras.py - small helpers for ardy_stream.py (kept separate so the stream file only needs a few added lines).

  PoseHoldGuard  a held pose (not plain standing) whose anchor keeps being released is the model fighting the pose;
                 left alone it ends in a flip (the splits did). After `releases` releases of the same pose in a row
                 (or `seconds` of holding it, if you set that) the guard says so and the stream goes back to standing
                 in a controlled way instead of waiting for the upside-down block and its teleporting recovery.
  prewarm        encode a list of wordings (wordings.txt, written by motion_prompter.py) before streaming starts, so the
                 first request for each costs no text-encoding time (the LLM2Vec fallback takes ~0.5 s per wording).
"""
import math
import os
import time

STAND = "A person stands upright."


class PoseHoldGuard:
    def __init__(self, seconds=0.0, releases=3, safe=STAND):
        self.seconds = seconds          # 0 = no time limit (sitting in a chair for minutes is fine)
        self.releases = releases        # 0 = off
        self.safe = safe
        self.reset()

    def reset(self):
        self.key = None
        self.held_s = 0.0
        self.released = 0
        self.calm = 0

    def update(self, prompt, hold, anchored, chunk_s, released_now):
        """Once per chunk. True = give up on this pose and stand."""
        if not hold or prompt == self.safe or (self.releases <= 0 and self.seconds <= 0):
            self.reset()
            return False
        if prompt != self.key:
            self.reset()
            self.key = prompt
        self.held_s += chunk_s
        if released_now:
            self.released += 1
            self.calm = 0
        elif anchored:
            self.calm += 1
            if self.calm >= 15:      # about 15 stable chunks: the pose is fine, forget earlier releases
                self.released = 0
        if self.releases > 0 and self.released >= self.releases:
            return True
        return self.seconds > 0 and self.held_s >= self.seconds


def load_wordings(path):
    out, seen = [], set()
    try:
        with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
            for ln in f:
                ln = " ".join(ln.split())
                if ln and ln not in seen:
                    seen.add(ln)
                    out.append(ln)
    except OSError:
        pass
    return out


def prewarm(streamer, path, budget_s=60.0, log=print):
    """Encode the wordings in `path` (one per line) until done or `budget_s` seconds have passed."""
    lines = load_wordings(path)
    if not lines:
        return 0
    t0 = time.time()
    done = 0
    for text in lines:
        if time.time() - t0 > budget_s:
            break
        try:
            streamer.prefetch(text)
            done += 1
        except Exception as e:     # never let this stop the stream
            log(f"  (pre-encoding stopped: {e})")
            break
    log(f"  pre-encoded {done}/{len(lines)} wordings in {time.time() - t0:.1f}s")
    return done


class StepGovernor:
    """The 3090 is shared with VaM's VR rendering, Chatterbox and Whisper, so generation time comes in bursts: 0.4 s per chunk
    most of the time, then 1.0-1.3 s for 5-15 chunks (more than the 0.89 s chunk), and playback runs dry. Denoising cost is
    roughly proportional to the step count, so this drops a step whenever a chunk came close to the chunk length, and adds
    one back once things have been comfortably fast for a few chunks. Quality dips a little during a burst instead of the
    motion stuttering."""

    def __init__(self, base_steps, min_steps=4, slow_frac=0.78, fast_frac=0.45, fast_chunks=20):
        self.base = int(base_steps)
        self.min = max(1, min(int(min_steps), self.base))
        self.steps = self.base
        self.slow_frac, self.fast_frac, self.fast_chunks = slow_frac, fast_frac, fast_chunks
        self.fast_n = 0

    def update(self, cost_s, chunk_s, allow_up=True):
        """cost_s = generate + export time of the chunk just made. Returns the step count for the next chunk.
        allow_up=False (while she walks a planned move) only lets the count fall: every change alters the look of the motion a
        little, and a change in the middle of a walk showed up as a twitch."""
        if chunk_s <= 0:
            return self.steps
        if not allow_up and cost_s <= self.slow_frac * chunk_s:
            self.fast_n = 0
            return self.steps
        if cost_s > self.slow_frac * chunk_s:
            self.fast_n = 0
            if self.steps > self.min:
                self.steps -= 1
        elif cost_s < self.fast_frac * chunk_s * (self.steps / float(self.steps + 1)):
            # fast enough that one more step would still fit well inside the chunk
            self.fast_n += 1
            if self.fast_n >= self.fast_chunks and self.steps < self.base:
                self.steps += 1
                self.fast_n = 0
        else:
            self.fast_n = 0
        return self.steps


# --------------------------------------------------------------------------- the world file (written by VaM-RT Senses)
def read_world(path, max_age=4.0):
    """The scene as Senses last saw it ({"user": {...}, "objects": [...], "follow": {...}}), or None if the file is missing,
    unreadable or older than `max_age` seconds. Everything in it is in HER frame: metres ahead (forward) and to her right."""
    import json
    try:
        st = os.stat(path)
        if time.time() - st.st_mtime > max_age:
            return None
        with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


class GroundSnap:
    """Long walks under root constraints make ARDY's root creep upward (root y 0.94 -> 1.09 in one session) and with In Place OFF the
    BVH player plays that height as it is: she floats. This keeps her lowest joint on the floor by sliding every exported chunk DOWN
    by a slowly adjusted offset: at most `max_step` metres of change per chunk, so it never pops, and nothing happens while the lowest
    joint is within `band` of the floor. It never lifts her: a foot a few centimetres under the floor while walking is normal foot
    skate, not drift (lifting the whole body for it looked like floating)."""

    def __init__(self, floor=0.01, max_step=0.015, band=0.03, limit=0.3, lift=0.0):
        self.floor, self.max_step, self.band, self.limit = floor, max_step, band, limit
        self.offset = 0.0
        self.lift = float(lift or 0.0)     # a constant raise (--lift) for a scene floor that sits above the BVH floor
        self.hold = 0.0                    # v39b: the freeze-hold's raise (lying on a bed: the floor pose lifted to the mattress), eased

    def apply(self, merged):
        import numpy as np
        try:
            pj = merged.get("posed_joints")
            rp = merged.get("root_positions")
            if pj is None or rp is None:
                return merged, None
            lowest = float(np.asarray(pj)[0, :, :, 1].min())
            err = lowest + self.offset - self.floor        # where the lowest joint would land with the current offset
            if err > self.band:                             # floating: pull down a little
                self.offset -= min(self.max_step, err)
            elif err < -self.band and self.offset < 0:      # pulled down earlier, now sinking: ease the offset back towards zero
                self.offset = min(0.0, self.offset + min(self.max_step, -err))
            self.offset = max(-self.limit, min(0.0, self.offset))
            want = float(HOLD_LIFT)
            if want > self.hold:
                self.hold = min(want, self.hold + 0.12)      # up with the lie-down (it is ramped by the hold itself)
            elif want < self.hold:
                self.hold = max(want, self.hold - 0.08)      # down over ~5 s when she leaves the bed
            total = self.offset + self.lift + self.hold
            if abs(total) < 1e-4:
                return merged, None
            out = dict(merged)
            out["posed_joints"] = np.array(pj, copy=True)
            out["posed_joints"][..., 1] += total
            out["root_positions"] = np.array(rp, copy=True)
            out["root_positions"][..., 1] += total
            return out, total
        except Exception:
            return merged, None


HOLD_LIFT = 0.0   # metres the freeze-hold wants the whole pose raised (lying on a bed); GroundSnap eases towards it and never undoes it

# --------------------------------------------------------------------------- freeze-hold (v37)
import re as _re

_FREEZE_CLASS = [
    # the final state of a plan is one of these; the words come from the prompter's hold wordings (POSE_DEFAULTS) and the LLM's own
    ("bend", _re.compile(r"\b(?:bent|bends?|bending)\b|\btoes\b|\bhands? (?:on|to|touch\w*) the (?:floor|ground)\b|"
                         r"\btouch\w* the (?:floor|ground)\b", _re.I)),
    ("low", _re.compile(r"\b(?:squat\w*|kneel\w*|crouch\w*|lies|lying|lie|lays?|on all fours|sits? (?:down )?on the (?:floor|ground)|"
                        r"splits)\b", _re.I)),
    ("seat", _re.compile(r"\b(?:sits?|sitting|seated)\b", _re.I)),
]


def freeze_class(prompt, safe=STAND):
    """Which kind of hold a final-state prompt is: 'bend' (judged by the head going down and coming back up), 'low' / 'seat' (the hips),
    'still' (anything else that is not plain standing: frozen once it has settled), or None for plain standing / nothing to hold."""
    t = " ".join((prompt or "").split())
    if not t or t == safe:
        return None
    for name, rx in _FREEZE_CLASS:
        if rx.search(t):
            return name
    return "still"


SEAT_HINT_FILE = "vamrt_seat.json"   # written by motion_prompter beside the world file when she is sent to sit on a known seat
SEAT_HINT_PATH = None                # set by WorldLink from the world file's folder
SEAT_HINT_MAX_AGE = 120.0


def seat_hint():
    """{'hip_y': metres, 'name': ...} for a seat the prompter planned a sit on within the last two minutes, else None."""
    import json
    path = SEAT_HINT_PATH
    if not path:
        return None
    try:
        if time.time() - os.stat(path).st_mtime > SEAT_HINT_MAX_AGE:
            return None
        with open(path, "r", encoding="utf-8-sig") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and ("hip_y" in d or "top_y" in d) else None
    except (OSError, ValueError):
        return None


class FreezeHold:
    """Hold a pose by HOLDING it: once she has reached the final state of a plan, the stream stops asking the model for more of that
    pose and plays the reached frame (with a breath) until the prompt changes. The model's history is pinned at that frame, so the
    next prompt continues from the held pose.

    Why: a state wording such as 'A person is bent over at the waist, touching their toes' is, to the model, a clip of bending over
    (down and up again) - the 2 Nov log shows the hold chunks at 0.26-0.45 m/s with the anchor released three times and the pose guard
    sending her back to standing: 'bend over and hold that position' played as bend-stand-bend-stand. Generating from an anchor
    cannot fix that; the only way to hold a pose the model will not hold is to stop generating it.

    How the moment is chosen (observe(), once per chunk, on what is about to be played):
      bend  the head's lowest point: when the head has come back up `rise` metres from its lowest, the lowest frame was the pose
      low / seat  the same with the hips (root y)
      still  (arms crossed, hands on hips, legs apart ...) the pose the stream's anchor settled into; when the model then tries to
             leave it (would have been 'anchor released'), the chunk is eased back onto that pose and it is held from there
    If no turning point shows within `search_s` seconds of the hold starting, the best frame so far is taken (bend/low/seat).
    A frame is only ever held if it is the right way up and her lowest joint is near the floor.
    """

    MIN_DROP = {"bend": 0.25, "low": 0.28, "seat": 0.25}    # metres the head (bend) or hips must come down for it to count as the pose
    STILL_MPS = 0.12                                         # a time-out may only hold a frame she has come to rest in (joint speed)

    def __init__(self, fps, idx=None, search_s=4.0, rise=0.05, breath=0.004, classes=("bend", "low", "seat", "still"),
                 safe=STAND, log=print, giveup_s=20.0):
        self.fps = float(fps)
        self.giveup_s = float(giveup_s)
        self.idx = idx or {}
        self.search_s, self.rise, self.breath = float(search_s), float(rise), float(breath)
        self.classes = set(classes)
        self.safe, self.log = safe, log
        self.phase = 0.0
        self.reset()

    # ------------------------------------------------------------------ state
    def reset(self):
        self.key = None             # the hold prompt being watched
        self.cls = None
        self.frozen = None          # the frame being held, in output form ({key: array[1, 1, ...]})
        self.tkeys = set()
        self.T = 0
        self.held_s = 0.0
        self.hold_s = 0.0           # seconds since the final state started
        self.best = None            # (score, frame dict) for bend/low/seat
        self.prev_score = None      # score of the previous chunk's last frame
        self.rest = None            # 'still': the frame the anchor settled on
        self.n = 0                  # chunks of this hold seen so far
        self.start = None           # the score (head or hip height) when the plan began: the pose must get well below it
        self.seat_y = None          # 'seat' with a known seat (vamrt_seat.json): hold the first frame whose hips are down at this height
        self.seat_name = "the seat"
        self.lie_top = None         # 'low' lying on a known bed: the floor pose is raised to the mattress as she goes down
        global HOLD_LIFT
        HOLD_LIFT = 0.0

    def release(self):
        was = self.key if self.frozen is not None else None
        self.reset()
        return was

    def begin(self, prompt, hold, fresh, final=None):
        """Call once per chunk before generating. `final` is the plan's last (hold) prompt. Returns True when this chunk should be
        the held frame (no generation). The action before a bend/low/seat hold ('bends over ... @2') is watched too: she often
        reaches the bottom before the hold wording even starts, and that is the moment to hold."""
        if fresh:
            self.reset()
            self.gave_up = None
        if hold and prompt == getattr(self, "gave_up", None):
            return False            # this hold was given up on (she never got into the pose): the model keeps it
        if hold:
            if prompt != self.key:
                self.reset()
                self.key = prompt
                self.cls = freeze_class(prompt, self.safe)
                self._load_seat()
        else:
            fcls = freeze_class(final, self.safe) if final else None
            if fcls in ("bend", "low", "seat") and freeze_class(prompt, self.safe) == fcls:
                if self.key != final:
                    self.reset()
                    self.key, self.cls = final, fcls
                    self._load_seat()
            else:
                self.reset()
        return self.frozen is not None

    def _load_seat(self):
        """A seat the prompter sent her to (chair / bed / couch with a known height): the sit is stopped when her hips reach it.
        The model does not know a chair from the floor - on 7 Nov she walked to the chair, turned, and sat on the floor in front
        of it - but Senses knows where the seat is, and a sit-down passes through the seat height on its way to the floor."""
        self.seat_y = None
        self.lie_top = None
        h = seat_hint()
        if not h:
            return
        kind = str(h.get("kind") or "seat")
        try:
            if self.cls == "seat" and kind == "seat":
                self.seat_y = float(h["hip_y"])
                self.seat_name = str(h.get("name") or "the seat")
            elif self.cls == "low" and kind == "lie":
                self.lie_top = float(h["top_y"])
                self.seat_name = str(h.get("name") or "the bed")
        except (TypeError, ValueError, KeyError):
            self.seat_y = None
            self.lie_top = None

    # ------------------------------------------------------------------ scoring
    def _scores(self, merged):
        import numpy as np
        pj = np.asarray(merged["posed_joints"])[0]            # [T, J, 3]
        if self.cls == "bend" and "head" in self.idx:
            return pj[:, self.idx["head"], 1]
        return np.asarray(merged["root_positions"])[0, :, 1]  # hips

    def _tail_speed(self, merged, frames=6):
        """Average joint speed (m/s) over the chunk's last few frames: is she still moving at its end?"""
        try:
            import numpy as np
            pj = np.asarray(merged["posed_joints"])[0]
            if pj.shape[0] < frames + 1:
                return None
            step = np.linalg.norm(np.diff(pj[-(frames + 1):], axis=0), axis=-1)
            return float(step.mean() * self.fps)
        except Exception:
            return None

    def _sane(self, merged, k):
        import numpy as np
        try:
            pj = np.asarray(merged["posed_joints"])[0, k]
            if float(pj[:, 1].min()) < -0.25:
                return False
            if "head" in self.idx and "lfoot" in self.idx:
                feet = min(float(pj[self.idx["lfoot"], 1]), float(pj[self.idx["rfoot"], 1]))
                if feet - float(pj[self.idx["head"], 1]) > 0.15:
                    return False
            return True
        except Exception:
            return False

    @staticmethod
    def _frame(merged, k, tkeys):
        import numpy as np
        return {key: np.array(np.asarray(v)[:, k:k + 1]) for key, v in merged.items() if key in tkeys}

    @staticmethod
    def _time_keys(merged):
        import numpy as np
        T = int(np.asarray(merged["root_positions"]).shape[1])
        keys = {k for k, v in merged.items() if hasattr(v, "shape") and len(v.shape) >= 2 and v.shape[1] == T}
        return T, keys

    # ------------------------------------------------------------------ the decision
    def observe(self, merged, streamer, prompt, hold, chunk_s, left_anchor=False):
        """Once per chunk, after the chunk is generated (and before it is exported). Returns (merged, message):
        `merged` may have its tail replaced by the held frame; message is a log line when the hold starts, else None."""
        if self.frozen is not None or self.key is None or self.cls is None or self.cls not in self.classes:
            return merged, None
        if hold and prompt != self.key:
            return merged, None
        if not hold and (self.cls == "still" or freeze_class(prompt, self.safe) != self.cls):
            return merged, None
        try:
            import numpy as np
            T, tkeys = self._time_keys(merged)
            self.hold_s += chunk_s
            self.n += 1
            if self.cls == "still":
                if self.rest is None and getattr(streamer, "anchor", None) is not None:
                    self.rest = self._frame(merged, T - 1, tkeys)   # the anchor ends on this chunk's last frame
                    return merged, None
                if left_anchor and self.rest is not None:
                    # the model is leaving the settled pose: ease this chunk back onto it and hold it from here
                    try:
                        import hold_blend
                        merged = hold_blend.pull_to_pose(merged, self.rest, end_frames=T // 2, start_frames=0)
                    except Exception:
                        pass
                    pinned = getattr(streamer, "anchor", None)
                    self._freeze(self.rest, T, tkeys, streamer, pinned)
                    return merged, f"  hold: the model tried to leave '{self.key}'; holding the pose she settled into instead"
                return merged, None
            scores = self._scores(merged)
            if self.start is None:
                self.start = float(scores[0])
            k = int(scores.argmin())
            cand = (float(scores[k]), k)
            # the previous chunk's last frame counts too: if the turn came right at the chunk edge, frame 0 of this chunk is the pose
            if self.prev_score is not None and self.prev_score <= cand[0]:
                cand = (self.prev_score, 0)
            if self.best is None or cand[0] < self.best[0] - 1e-4:
                self.best = (cand[0], self._frame(merged, cand[1], tkeys), cand[1], self.n)
            self.prev_score = float(scores[-1])
            if self.lie_top is not None and self.lie_top > 0.05:
                # lying on a bed: the model lies on its floor; the whole pose is raised to the mattress as her hips come down, so
                # she lowers herself onto the bed instead of through it. GroundSnap carries the raise and eases it off afterwards.
                global HOLD_LIFT
                prog = max(0.0, min(1.0, (self.start - float(scores[-1])) / max(0.2, self.start - 0.3)))
                HOLD_LIFT = max(HOLD_LIFT, self.lie_top * prog)
            if self.seat_y is not None and self.start - self.seat_y >= 0.12:
                # a known seat: the first frame whose hips are down at the seat is the pose, whatever the model meant to do next
                down = np.nonzero(scores <= self.seat_y + 0.02)[0]
                if len(down) == 0:
                    if self.hold_s >= self.giveup_s:
                        key = self.key
                        self.reset()
                        self.gave_up = key if hold else None
                        return merged, f"  (freeze-hold: she never came down to the {self.seat_name} ({self.seat_y:.2f} m); leaving that pose to the model)"
                    return merged, None
                kk = int(down[0])
                if not self._sane(merged, kk):
                    self.reset()
                    return merged, None
                frame = self._frame(merged, kk, tkeys)
                out = dict(merged)
                for key in tkeys:
                    arr = np.array(np.asarray(merged[key]), copy=True)
                    arr[:, kk + 1:] = frame[key]
                    out[key] = arr
                pinned = self._pin(streamer, T, kk)
                self._freeze(frame, T, tkeys, streamer, pinned)
                return out, (f"  hold: '{self.key}' - her hips are down at the {self.seat_name} ({float(scores[kk]):.2f} m); "
                             f"holding that pose until the prompt changes")
            best_score, best_frame, best_k, best_n = self.best
            # the pose has to be a real one: the hips (or head) well below where they started. On 7 Nov "sits down >> sits in a
            # chair" was held at hip height 0.84 (standing is 0.93): a dip and a wobble read as "reached it". Until she is really
            # down nothing is held; if she never gets there the model keeps the pose (the old anchor behaviour).
            if self.start - best_score < self.MIN_DROP.get(self.cls, 0.25):
                if self.hold_s >= self.giveup_s:
                    msg = (f"  (freeze-hold: she never got down into '{self.key}' ({(self.start - best_score) * 100:.0f} cm below where she "
                           f"started); leaving that pose to the model)")
                    key = self.key
                    self.reset()
                    self.gave_up = key if hold else None
                    return merged, msg
                return merged, None
            after = scores[best_k:] if best_n == self.n else scores
            turned = float(after.max()) > best_score + self.rise
            # the time-out may only take a frame she has come to rest in: on 7 Nov it fired the moment her hips reached the seat,
            # mid-sit, leaning forward, and held that (the hunched-over chair). Still moving = keep waiting (up to giveup_s)
            tail_speed = self._tail_speed(merged)
            timed_out = self.hold_s >= self.search_s and (tail_speed is None or tail_speed < self.STILL_MPS)
            if self.hold_s >= self.search_s and not timed_out and self.hold_s >= self.giveup_s:
                key = self.key
                self.reset()
                self.gave_up = key if hold else None
                return merged, f"  (freeze-hold: '{key}' never came to rest ({tail_speed:.2f} m/s); leaving that pose to the model)"
            if not (turned or timed_out):
                return merged, None
            if best_n != self.n:
                # the lowest point was in an earlier chunk (already played). Continuity first: hold this chunk's first frame if it is
                # still (nearly) that pose, else this chunk's own lowest frame
                best_k = 0 if float(scores[0]) <= best_score + self.rise else k
                best_frame = self._frame(merged, best_k, tkeys)
            if not self._sane(merged, best_k):
                self.reset()      # not a pose to hold (upside down / through the floor): leave it to the old guards
                return merged, None
            # everything after the chosen frame in this chunk becomes the held frame
            out = dict(merged)
            for key in tkeys:
                arr = np.array(np.asarray(merged[key]), copy=True)
                arr[:, best_k + 1:] = best_frame[key]
                out[key] = arr
            pinned = self._pin(streamer, T, best_k)
            self._freeze(best_frame, T, tkeys, streamer, pinned)
            why = "she has reached it" if turned else f"no turning point in {self.search_s:g}s; holding the lowest point so far"
            return out, f"  hold: '{self.key}' - {why}; holding that pose until the prompt changes"
        except Exception as e:
            self.reset()
            return merged, f"  (freeze-hold off for this pose: {e})"

    def _pin(self, streamer, T, k):
        """The model history that ends on frame k of the chunk just generated (so the next prompt continues from the held pose)."""
        try:
            tail = getattr(streamer, "last_tail", None)
            if tail is None:
                return None
            cut = int(tail.shape[1]) - (T - 1 - k)
            if cut < streamer.patch:
                return None
            keep = (min(cut, streamer.history_frames) // streamer.patch) * streamer.patch
            return tail[:, cut - keep:cut].clone()
        except Exception:
            return None

    def _freeze(self, frame, T, tkeys, streamer, pinned):
        self.frozen, self.T, self.tkeys = frame, T, tkeys
        self.held_s = 0.0
        if pinned is not None:
            streamer.motion = pinned
        try:
            streamer.drop_anchor()
        except Exception:
            pass

    # ------------------------------------------------------------------ what plays while held
    def chunk(self, T=None):
        """A chunk of the held frame (with a slow breath on the hips so she is not a statue)."""
        import numpy as np
        T = int(T or self.T)
        out = {}
        for key, v in self.frozen.items():
            out[key] = np.repeat(np.asarray(v), T, axis=1)
        if self.breath > 0 and "root_positions" in out:
            t = (np.arange(T) + self.phase) / self.fps
            bob = self.breath * np.sin(2.0 * math.pi * 0.22 * t)
            out["root_positions"] = np.array(out["root_positions"], copy=True)
            out["root_positions"][0, :, 1] += bob
            if "posed_joints" in out:
                out["posed_joints"] = np.array(out["posed_joints"], copy=True)
                out["posed_joints"][0, :, :, 1] += bob[:, None]
            self.phase += T
        self.held_s += T / self.fps
        return out, set(self.tkeys)


STATUS_FILE = "ardy_status.json"    # written beside the prompt file; read by motion_prompter.py (idle life waits while busy)


class WorldLink:
    """The bridge to VaM-RT Senses' world file, run as a daemon thread.
      * learns the ARDY <-> VaM frame (world_frame.FrameFit) from her resting positions, so a goal measured in VaM can be walked to
        in ARDY coordinates without assuming how the BVH export rotates or mirrors the floor plane
      * the first time a goal is asked for, it calibrates with short planned steps (1.2 m ahead, 0.8 m ahead-right; a third ahead-left if needed): three
        resting points, not on a line, fix rotation, mirror and offset. No goal is ever walked to on a guess.
      * carries out approach requests from the prompter ("/approach x z stop" in the prompt file -> state.approach_req)
      * carries out Senses' follow decision (follow.goal in VaM world), once calibrated"""

    # all three are planned steps (0.8 m ahead, 0.4 m ahead-right, and ahead-left only if the first two leave the mirror undecided).
    # A text walk ("walks forward" for 1.6 s, then "stands upright") took 3-6 m to come to a stop in the 31 Oct tests and carried
    # her away from the person who had just said "come here"; a planned step stops where it is told.
    CAL_WALK = "A person walks forward. @1.6 >> A person stands upright."
    CAL_STEPS = [("go", 1.2, 0.0), ("go", 0.8, 0.8), ("go", 0.8, -0.8)]   # a wide enough triangle: 0.4 m steps were inside the lag error
    STAGE_TIMEOUT = 25.0

    # ---- social facing: a person talking to someone faces them most of the time. When she has stood with you well off her front
    # for a while (nothing else going on), she turns to you: a 180 turn when you are behind her, a short step toward you when you
    # are off to the side (she faces the way she walks). Not while she is withdrawn or furious (ardy_mood.json from the prompter),
    # not for a while after she deliberately walked away, never in the middle of a move, a request or a calibration.
    FACE_OFF_DEG = 75.0        # you this far off her front counts as "she is not facing you"
    FACE_TURN_DEG = 125.0      # from here on a 180 turn is the move; between, a short step toward you
    FACE_AFTER_S = 6.0         # ... for this long before she does something about it (twice that while guarded)
    FACE_COOLDOWN_S = 25.0     # at most one turn/step this often: glances away and looking at things stay possible
    FACE_RETRY_S = 10.0        # ... except after a turn that fell short: one earlier retry
    FACE_SETTLE_S = 3.0        # she must have been plainly standing (no idle motion playing) this long first: the 2 Nov log showed
                               # turns issued right after a nod or a look-around turning her 6-32 deg instead of 180
    FACE_MIN_DIST, FACE_MAX_DIST = 0.8, 6.0
    FACE_STEP = 0.5            # the side step: about one pace toward you
    AWAY_HOLD_S = 90.0         # after "walk away" / storming off she does not turn back to you for this long
    # @4: with the default 2 s the turn was cut short (the 2 Nov log: six turns, you still 120-170 deg off after each)
    TURN_LINE = "A person turns around 180 degrees. @4 >> A person stands upright."
    TURN_BUSY_S = 8.0          # idle life holds off while the turn plays

    def __init__(self, streamer, state, path, right_sign=1.0, poll=0.3, log=print):
        self.streamer, self.state, self.path, self.right_sign, self.poll, self.log = streamer, state, path, right_sign, poll, log
        global SEAT_HINT_PATH
        try:
            SEAT_HINT_PATH = os.path.join(os.path.dirname(os.path.abspath(path)), SEAT_HINT_FILE)
        except Exception:
            SEAT_HINT_PATH = None
        try:
            import world_frame
            self.fit = world_frame.FrameFit()
            self.wf = world_frame
        except ImportError:
            self.fit, self.wf = None, None
        self.track = []            # (time, x, z) of her hips in VaM, to know when she is still
        self.last_sig = None
        self.last_move_done = 0.0
        self.last_pair_at = 0.0
        self.pair_count = 0
        self.announced = False
        self.moving = False
        self.follow_start_dist = 0.0
        self.follow_paused_until = 0.0
        self.calib = None          # {"stage": n, "since": t, "pairs": count_at_stage_start, "pending": approach_req}
        self._last_ardy = None
        self.started = time.monotonic()   # no resting pairs in the first seconds: the player may still be moving her to the new stream's origin
        self.active_goal = None
        self.face_since = None     # when you were first seen off her front (None = you are in front, or nothing to do)
        self.face_last = -1e9
        self.away_until = 0.0
        self.turn_until = 0.0
        self.turn_from = None      # (ARDY heading, VaM facing, user angle) when a turn started: the result is logged when it is over
        self.turn_pending = None   # (vx, vz, stop, label, legs, user[, via]): a walk that starts once the turn-around has played (v38)
        self.calib_via = None      # staging points of an approach that waits for the calibration (v39)
        self.turn_short = False    # the last turn left you still off her front: the next try is a planned step (if calibrated)
        self._last_plan_text = ""
        self.plain_since = None
        self._mood_sig = None
        self._mood = {}
        self.facing_on = bool(getattr(self.state, "facing", True))
        try:
            self.state.world_link = True     # tells the stream's move-done hook that the after-move line is written from here
        except Exception:
            pass

    # ------------------------------------------------------------------ helpers
    def _vam_still(self, now):
        self.track = [t for t in self.track if now - t[0] <= 3.0]
        if len(self.track) < 2:
            return False
        a, b = self.track[0], self.track[-1]
        return math.hypot(b[1] - a[1], b[2] - a[2]) < 0.06 and (b[0] - a[0]) >= 1.5

    def _mover(self):
        return getattr(self.state, "mover", None)

    def _plain_standing(self):
        with self.state.lock:
            plan = [list(p) for p in self.state.plan]
        return len(plan) == 1 and plan[0][0] == STAND

    TURN_FIRST_DEG = 110.0     # a goal this far round from where she faces: turn around first, then walk (v38)
    TURN_FIRST_MIN_M = 0.8     # ... unless it is only a step away

    def go_to_vam(self, vx, vz, stop, label, legs=1, user=None, turn_first=True, via=None):
        """Walk to a VaM world point, stopping `stop` metres short. Only with a calibrated frame. `legs` > 1 lets an approach that is
        farther than one move (--max-move) continue with another leg when this one ends, re-aimed at where the person is then.
        A goal well behind her is reached by turning around first (the 7 Nov chair: she walked 2 s the wrong way before the model
        turned her) - the walk is queued in turn_pending and starts when the turn has played."""
        mover = self._mover()
        if mover is None or self.fit is None or not self.fit.calibrated:
            return False
        goal = self.fit.vam_to_ardy(vx, vz)
        pose = self.streamer.root_pose()
        # v39: staging points (VaM coords) she passes on the way - round the furniture, or the front of a seat - in ONE move
        via_a = [self.fit.vam_to_ardy(px, pz) for px, pz in (via or [])]
        via_a = [v for v in via_a if math.hypot(v[0] - pose[0], v[1] - pose[1]) > 0.4]     # a staging point she is already at is skipped
        short = self.wf.goal_short_of((pose[0], pose[1]), goal, stop) if stop > 0 else goal
        if short is None:
            if via_a:
                short = goal          # she is near the goal but has to go round through the staging point first
            else:
                self.log(f"  {label}: she is already there")
                return False
        first = via_a[0] if via_a else short
        d = math.hypot(first[0] - pose[0], first[1] - pose[1])
        if turn_first and d >= self.TURN_FIRST_MIN_M:
            rel = (math.degrees(math.atan2(first[0] - pose[0], first[1] - pose[1]) - pose[2]) + 180.0) % 360.0 - 180.0
            if abs(rel) >= self.TURN_FIRST_DEG:
                # the turn is issued from the tick once she has come to rest: a turn written straight after a walk (7 Nov, right
                # after a calibration step) came out as an 8 m run with "stands upright" showing 0.8 m/s
                self.turn_pending = (vx, vz, stop, label, legs, user, via)
                self.turn_issued = False
                self.turn_wait_since = time.monotonic()
                self.log(f"  {label}: the goal is {abs(rel):.0f} deg round from where she faces: she turns around first, then walks")
                return True
        d = math.hypot(short[0] - pose[0], short[1] - pose[1])
        if d > mover.max_move and not via_a:   # too far for one move: go as far as allowed, the next decision continues
            k = (mover.max_move - 0.2) / d
            short = (pose[0] + (short[0] - pose[0]) * k, pose[1] + (short[1] - pose[1]) * k)
        ok, msg = mover.goto(pose, short, time.monotonic(), label, via=via_a)
        if ok and via_a:
            msg += f" through {len(via_a)} staging point(s)"
        self.log(f"  {label}: {msg}" if ok else f"  {label} refused: {msg}")
        if ok:
            # another leg later re-aims at the person only if the person WAS the target (not the bed she was sent to)
            to_user = bool(user) and math.hypot(vx - user[0], vz - user[1]) < 1.0
            self.active_goal = {"label": label, "target": (vx, vz), "stop": stop, "legs": legs - 1 if to_user else 0,
                                "goal_vam": self.fit.ardy_to_vam(short[0], short[1])}
        return ok

    def _after_move(self, g, data, now):
        """A move ended and VaM has caught up (she is still on screen). Judge it by whether she reached the point she was sent to
        (her VaM position against the goal), never by the distance to the person, who may have walked off meanwhile.
        Returns True if another leg was started."""
        me = data.get("self") or {}
        if not g or "x" not in me:
            return False
        miss = math.hypot(float(me["x"]) - g["goal_vam"][0], float(me["z"]) - g["goal_vam"][1])
        if miss > 1.2:
            self.log(f"  {g['label']}: she ended {miss:.1f} m from where that move was meant to end; the frame link is off and is "
                     f"being re-learned (following pauses for 90 s)")
            self.follow_paused_until = now + 90.0
            if self.fit is not None:
                self.fit.reset()
                self.calib = None
            return False
        if g["label"] == "approach" and g["legs"] > 0:
            user = data.get("user") or {}
            if "x" in user:
                ux, uz = float(user["x"]), float(user["z"])
                dist = math.hypot(ux - float(me["x"]), uz - float(me["z"]))
                if dist > g["stop"] + 1.0:
                    self.log(f"  approach: still {dist:.1f} m from you (you moved, or it was farther than one move): another leg")
                    return self.go_to_vam(ux, uz, g["stop"], "approach", legs=g["legs"], user=(ux, uz))
        return False

    @staticmethod
    def _user_xy(data):
        u = (data or {}).get("user") or {}
        return (float(u["x"]), float(u["z"])) if "x" in u and "z" in u else None

    def _say_fit(self):
        """Log the learned frame once per change (the pair loop and the stage loop can both notice it)."""
        d = self.fit.describe()
        if d != getattr(self, "_last_fit_desc", None):
            self._last_fit_desc = d
            self.log("  " + d)
            for line in self.fit.dump():
                self.log("    " + line)

    def _finish_after_move(self):
        """What the prompter asked to happen once the walk is over ("lie on the bed" = walk there, then lie down): the stream's move-done
        hook writes it when a move really ran; this covers the cases where no move ran at all."""
        line = getattr(self.state, "after_move", None)
        mover = self._mover()
        if line and not (mover is not None and mover.active):
            self.state.after_move = None
            if self._write_prompt(line):
                self.log(f"  after the walk: {line}")

    def _write_prompt(self, text):
        path = getattr(self.state, "prompt_file", None)
        if not path:
            return False
        try:
            tmp = str(path) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text + "\n")
            os.replace(tmp, path)
            return True
        except OSError:
            return False

    # ------------------------------------------------------------------ social facing
    def _mood_stance(self):
        """The stance the scenario last reported, via the prompter's ardy_mood.json beside the prompt file ('' if unknown)."""
        pf = getattr(self.state, "prompt_file", None)
        if not pf:
            return ""
        path = os.path.join(os.path.dirname(os.path.abspath(pf)), "ardy_mood.json")
        try:
            st = os.stat(path)
            sig = (st.st_mtime_ns, st.st_size)
            if sig != self._mood_sig:
                import json
                with open(path, "r", encoding="utf-8") as f:
                    self._mood = json.load(f) or {}
                self._mood_sig = sig
        except (OSError, ValueError):
            return ""
        return str(self._mood.get("stance", ""))

    def _note_plan(self, now):
        """Watch what she is doing for a deliberate walk-away (turn, then walk): she keeps her back to you for a while after that."""
        try:
            with self.state.lock:
                text = " ".join(str(p[0]) for p in self.state.plan)
        except Exception:
            return
        if text != self._last_plan_text:
            self._last_plan_text = text
            self.plain_since = now if text == STAND else None
            if "turns around" in text and "walks" in text:
                self.away_until = now + self.AWAY_HOLD_S
                self.face_since = None
        elif text == STAND and self.plain_since is None:
            self.plain_since = now

    def _turn_result(self, data, now, me):
        """How much a text turn really turned her, in both frames (the next log tells whether the wording is right)."""
        if self.turn_from is None or now < self.turn_until + 2.0:
            return
        h0, f0, a0 = self.turn_from
        self.turn_from = None
        pose = self.streamer.root_pose()
        dh = (math.degrees(pose[2] - h0) + 180.0) % 360.0 - 180.0
        user = data.get("user") or {}
        a1 = abs(math.degrees(math.atan2(float(user.get("right", 0.0)), float(user.get("fwd", 1.0))))) if "fwd" in user else None
        try:
            df = (float(me.get("facing_deg")) - f0 + 180.0) % 360.0 - 180.0 if f0 is not None and "facing_deg" in me else None
        except (TypeError, ValueError):
            df = None
        self.turn_short = a1 is not None and a1 >= self.FACE_OFF_DEG
        self.log(f"  facing: the turn moved her {abs(dh):.0f} deg in ARDY" + (f", {abs(df):.0f} deg on screen" if df is not None else "")
                 + (f"; you are now {a1:.0f} deg off her front" if a1 is not None else "")
                 + (" (short: the next try is a step toward you)" if self.turn_short else ""))

    def _social_facing(self, data, now, mover, me, ardy_still):
        """Once per tick, after the move/request/calibration logic has found nothing to do."""
        if not self.facing_on or now < self.away_until or now < self.turn_until:
            return
        self._turn_result(data, now, me)
        user = data.get("user") or {}
        if "fwd" not in user or "right" not in user or "x" not in user:
            return
        stance = self._mood_stance()
        if stance in ("withdrawn", "disengage"):
            self.face_since = None
            return
        fwd, right = float(user["fwd"]), float(user["right"])
        dist = float(user.get("dist", math.hypot(fwd, right)) or math.hypot(fwd, right))
        ang = abs(math.degrees(math.atan2(right, fwd)))
        if ang < self.FACE_OFF_DEG or dist < self.FACE_MIN_DIST or dist > self.FACE_MAX_DIST:
            self.face_since = None
            return
        if self.face_since is None:
            self.face_since = now
            return
        after = self.FACE_AFTER_S * (2.0 if stance == "guarded" else 1.0)
        cooldown = self.FACE_RETRY_S if self.turn_short else self.FACE_COOLDOWN_S
        if now - self.face_since < after or now - self.face_last < cooldown:
            return
        if self.plain_since is None or now - self.plain_since < self.FACE_SETTLE_S:
            return
        # only while she simply stands there, on both sides of the link, with nothing in flight
        if (mover is not None and mover.active) or self.calib is not None or getattr(self, "judge", None) is not None:
            return
        if getattr(self.state, "approach_req", None) or getattr(self.state, "after_move", None):
            return
        if not self._plain_standing() or not ardy_still or not self._vam_still(now) or now - self.last_move_done < 6.0:
            return
        if str(data.get("pose", "standing")) != "standing":
            return
        follow = data.get("follow") or {}
        if follow.get("enabled") and follow.get("cmd") == "goto":
            return
        calibrated = self.fit is not None and self.fit.calibrated
        self.face_last = now
        self.face_since = None
        # behind you: a text turn, unless the last turn fell short (then a planned step, which the model turns into a turn-and-step)
        if (ang >= self.FACE_TURN_DEG and not (calibrated and self.turn_short)) or not calibrated:
            if not calibrated and ang < 100.0:
                return      # a side step needs the frame link (otherwise it could go the mirrored way); a 180 would overshoot
            if self._write_prompt(self.TURN_LINE):
                self.turn_until = now + self.TURN_BUSY_S
                self.last_move_done = now
                try:
                    f0 = float(me.get("facing_deg")) if "facing_deg" in me else None
                except (TypeError, ValueError):
                    f0 = None
                self.turn_from = (self.streamer.root_pose()[2], f0, ang)
                self.log(f"  facing: you have been {ang:.0f} deg off her front for a while: she turns around")
            return
        step = min(self.FACE_STEP, dist - 0.5)
        if step < 0.3:
            return
        if self.go_to_vam(float(user["x"]), float(user["z"]), dist - step, "face", turn_first=False):
            self.turn_short = False
            self.log(f"  facing: you have been {ang:.0f} deg off her front for a while: a step toward you so she faces you")

    def _start_stage(self, n, now):
        mover = self._mover()
        pose = self.streamer.root_pose()
        step = self.CAL_STEPS[n]
        if step[0] == "text":
            ok = self._write_prompt(step[1])
            msg = "a short plain walk (by text)" if ok else "could not write the prompt file"
            self.text_stage_until = now + 5.0      # the walk takes ~1 s to start and ~2 s to play; pairs wait until after that
        elif step[0] == "walk":
            ok, msg = mover.walk(pose, step[1], now)
        else:
            ok, msg = mover.go_relative(pose, step[1], step[2], now)
        self.calib.update(stage=n, since=now, pairs=self.pair_count)
        self.log(f"  frame link: calibration step {n + 1}/{len(self.CAL_STEPS)}: {msg}" if ok else f"  frame link: calibration step refused: {msg}")
        return ok

    # ------------------------------------------------------------------ the loop
    def run(self):
        while not self.state.stop:
            time.sleep(self.poll)
            try:
                self._tick()
            except Exception as e:     # a bad file must never take the stream down
                self.log(f"  world link: ignored ({e})")

    def _status(self, now):
        """Tell the prompter what the stream is busy with (ardy_status.json beside the prompt file), so idle life does not
        write a stretch or a hair-flick into the middle of a calibration or a planned walk. Rewritten on change and every 5 s."""
        pf = getattr(self.state, "prompt_file", None)
        if not pf:
            return
        mover = self._mover()
        busy = "moving" if (mover is not None and mover.active) else ("calibrating" if self.calib is not None else ("turning" if now < self.turn_until else ""))
        if busy == getattr(self, "_status_last", None) and now - getattr(self, "_status_at", 0.0) < 5.0:
            return
        self._status_last, self._status_at = busy, now
        path = os.path.join(os.path.dirname(os.path.abspath(pf)), STATUS_FILE)
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write('{"busy": "%s", "time": %.1f}\n' % (busy, time.time()))
            os.replace(tmp, path)
        except OSError:
            pass

    def _tick(self):
        mover = self._mover()
        self._status(time.monotonic())
        try:
            st = os.stat(self.path)
        except OSError:
            return
        sig = (st.st_mtime_ns, st.st_size)
        fresh = sig != self.last_sig
        self.last_sig = sig
        data = read_world(self.path, max_age=10.0)
        if not data:
            return
        now = time.monotonic()
        me = data.get("self") or {}
        # after /reset she is back at ARDY's origin: what was learned about the frame no longer holds
        pose = self.streamer.root_pose()
        if self.fit is not None and self.fit.pairs and self._last_ardy is not None:
            if math.hypot(pose[0] - self._last_ardy[0], pose[1] - self._last_ardy[1]) > 2.5 and (mover is None or not mover.active):
                self.fit.reset()
                self.track = []
                self.calib = None
                self.log("  frame link: forgotten (her ARDY position jumped: /reset or a recovery)")
        self._last_ardy = (pose[0], pose[1])
        self._note_plan(now)
        if fresh and "x" in me and "z" in me:
            self.track.append((now, float(me["x"]), float(me["z"])))
        # a resting pair for the frame fit: both sides still, nothing in flight
        ardy_still = math.hypot(pose[3], pose[4]) < 0.1
        if (self.fit is not None and "facing_deg" in me and "x" in me and ardy_still and self._vam_still(now)
                and (mover is None or not mover.active) and now - self.last_move_done > 4.0 and now - self.last_pair_at > 2.0
                and now > getattr(self, "text_stage_until", 0.0) and now - self.started > 8.0):
            was = self.fit.calibrated
            self.fit.add_pair((pose[0], pose[1]), pose[2], (float(me["x"]), float(me["z"])), math.radians(float(me["facing_deg"])))
            self.pair_count += 1
            self.last_pair_at = now
            if self.fit.calibrated and not was:
                self._say_fit()
        if mover is not None and mover.active:
            self.last_move_done = now
            self.moving = True
            return
        if self.moving:    # a move just ended in ARDY; VaM shows it 1-2 s later, so the judgement waits until she is still on screen
            self.moving = False
            self.follow_start_dist = 0.0
            self.judge = (getattr(self, "active_goal", None), now)
            self.active_goal = None
            self.track = []
        if getattr(self, "judge", None) is not None and ((now - self.judge[1] > 2.5 and self._vam_still(now)) or now - self.judge[1] > 8.0):
            g, _t0 = self.judge
            self.judge = None
            if g is not None and self._after_move(g, data, now):
                self.last_move_done = now
                self.moving = True
                return
            if self.calib is None and not getattr(self.state, "approach_req", None):
                self._finish_after_move()      # not between calibration steps: the real walk has not happened yet then
        # calibration in progress: wait for the resting pair after each step, then the next step
        if self.calib is not None:
            if self.pair_count > self.calib["pairs"]:
                nxt = self.calib["stage"] + 1
                if nxt < len(self.CAL_STEPS) and not (self.fit and self.fit.calibrated):
                    self._start_stage(nxt, now)
                    return
                pending = self.calib.get("pending")
                self.calib = None
                if self.fit.calibrated:
                    self._say_fit()
                    if pending:
                        vx, vz, stop, label = pending
                        if not self.go_to_vam(vx, vz, stop, label, legs=2, user=self._user_xy(data), via=self.calib_via):
                            self._finish_after_move()
                else:
                    self.log("  " + self.fit.describe())
                    for line in self.fit.dump():
                        self.log("    " + line)
                    if pending:
                        self._finish_after_move()
            elif now - self.calib["since"] > self.STAGE_TIMEOUT:
                self.log("  frame link: calibration timed out (no resting position from Senses after the step); giving up for now")
                self.calib = None
                self._finish_after_move()
            return
        # a walk that waited for a turn-around (v38)
        tp = getattr(self, "turn_pending", None)
        if tp is not None:
            if not getattr(self, "turn_issued", False):
                settled = ardy_still and self._vam_still(now) and self._plain_standing() and now - self.last_move_done >= 2.5
                if settled or now - getattr(self, "turn_wait_since", now) > 12.0:
                    if self._write_prompt(self.TURN_LINE):
                        self.turn_issued = True
                        self.turn_until = now + self.TURN_BUSY_S
                        self.last_move_done = now
                    else:
                        self.turn_pending = None
                return
            if now >= self.turn_until and ardy_still and self._vam_still(now):
                self.turn_pending = None
                vx, vz, stop, label, legs, user = tp[:6]
                via = tp[6] if len(tp) > 6 else None
                if not self.go_to_vam(vx, vz, stop, label, legs=legs, user=user, turn_first=False, via=via):
                    self._finish_after_move()
            return
        # an approach asked for by the prompter
        req = getattr(self.state, "approach_req", None)
        if req:
            self.state.approach_req = None
            vx, vz, stop, label = req
            via = getattr(self.state, "approach_via", None) or None
            self.state.approach_via = None
            started = False
            user_xy = self._user_xy(data)
            if self.fit is not None and self.fit.calibrated:
                started = self.go_to_vam(vx, vz, stop, label, legs=2, user=user_xy, via=via)
            elif self.fit is not None and mover is not None and "x" in me:
                self.log("  frame link: not learned yet; taking two short steps first, then she walks to the goal")
                self.calib = {"pending": req}
                self.calib_via = via
                self._start_stage(0, now)
                started = True
            else:
                self.log(f"  {label}: cannot plan it (no position from Senses in the world file)")
            if not started:
                self._finish_after_move()      # nothing to walk: whatever was to follow the walk happens now
            return
        # follow: only once the frame link is known
        follow = data.get("follow") or {}
        if not fresh or not follow.get("enabled") or follow.get("cmd") != "goto":
            self._social_facing(data, now, mover, me, ardy_still)
            return
        if self.fit is None or not self.fit.calibrated:
            if not self.announced:
                self.announced = True
                self.log("  follow: waiting for the frame link (ask her to 'come here' once; she calibrates with two short steps)")
            return
        if now < self.follow_paused_until:
            return
        if time.time() - st.st_mtime > float(follow.get("lease_s", 3.0)) or now - self.last_move_done < 2.0:
            return
        if not self._plain_standing() or not ardy_still:
            return
        goal = follow.get("goal") or {}
        if "x" in goal and "z" in goal:
            if self.go_to_vam(float(goal["x"]), float(goal["z"]), 0.0, "follow", turn_first=False):
                self.follow_start_dist = float((data.get("user") or {}).get("dist", 0) or 0)


def follow_loop(streamer, state, path, right_sign=1.0, poll=0.3, log=print):
    """Entry point used by ardy_stream (thread target)."""
    WorldLink(streamer, state, path, right_sign, poll, log).run()
