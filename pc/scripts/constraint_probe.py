"""Experiment: does the ARDY Core model follow a root-path constraint, and does it still walk NATURALLY? No VaM, no Voxta.

It loads the model like the stream does, generates motion chunk by chunk, and steers the character's root with plans from
ardy_control.py (a velocity, or "go to this point and stop"), re-planning from where she really is after every chunk (closed
loop, exactly what a follower will do). Then it prints how well she followed AND how the body moved (gait_metrics.py):
whether she faces where she travels, how she turns, and how much her planted feet slide.

Run from the ARDY folder with the `ardy` environment active (close VaM and Voxta first if VRAM is tight):

    python scripts/constraint_probe.py                    # every scenario, one after the other
    python scripts/constraint_probe.py --scenario turn    # just one
    python scripts/constraint_probe.py --save-bvh         # also write probe_bvh/probe_<scenario>.bvh to watch in VaM
    python scripts/constraint_probe.py --postprocess      # with ARDY's post-processing (compare the foot skate numbers)
    python scripts/constraint_probe.py --postprocess --pp-constraints   # ... and let it pull the root onto the plan

Scenarios (ARDY world frame: she starts at the origin facing +Z):
    baseline  no constraint at all: how she walks on her own
    forward   walk straight ahead (+Z) at --speed
    goto      walk to (2, 4) and stop there
    stop      walk to (0, 3) and stop there (tests braking)
    turn      walk to (0, -3), a point BEHIND her (does she turn around, or walk backwards?)
    side      walk to (3, 0), a point to one side (does she turn, or sidestep?)

  Heading-aware versions (the plan curves the way a person would turn, using where she really faces):
    turn2     the same goal behind her, steering planner, text "walks forward"
    turn3     as turn2, but the text switches to "turns around" while she is badly misaligned with the goal
    side2     the side goal with the steering planner

Each run writes probe_<scenario>.csv (time, x, z, speed). A "WARNING: root constraint not applied" line means the constraint
was rejected and that run was unconstrained; send that line.
"""

import argparse
import csv
import math
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ardy_control as ctl  # noqa: E402
import ardy_to_vam as a2v  # noqa: E402
import gait_metrics as gm  # noqa: E402
from ardy_stream import Streamer  # noqa: E402

WALK = "A person walks forward."
STAND = "A person stands upright."
TURN_TEXT = "A person turns around 180 degrees."
GOALS = {"goto": (2.0, 4.0), "stop": (0.0, 3.0), "turn": (0.0, -3.0), "side": (3.0, 0.0),
         "turn2": (0.0, -3.0), "turn3": (0.0, -3.0), "side2": (3.0, 0.0)}
ALL = ["baseline", "forward", "goto", "stop", "turn", "side", "turn2", "turn3", "side2"]
STEERED = ("turn2", "turn3", "side2")
JOINTS = (("lhip", "LeftUpLeg"), ("rhip", "RightUpLeg"), ("lfoot", "LeftFoot"), ("rfoot", "RightFoot"))
OPTIONAL_JOINTS = (("ltoe", "LeftToeBase"), ("rtoe", "RightToeBase"))   # steadier than the ankles for judging foot sliding


def decide(scenario, state, speed, fps, heading=0.0):
    """(prompt, plan) for the next chunk, planned from where she really is (and, for the steered scenarios, where she faces)."""
    x, z, vx, vz = state if state else (0.0, 0.0, 0.0, 0.0)
    if scenario == "baseline":
        return WALK, None
    if scenario == "forward":
        return WALK, ctl.velocity_plan((x, z), (vx, vz), (0.0, speed), fps)
    goal = GOALS[scenario]
    near = math.hypot(goal[0] - x, goal[1] - z) < 0.5
    if scenario in STEERED:
        plan = ctl.steer_plan((x, z), (vx, vz), heading, goal, speed, fps)
        err = abs((math.atan2(goal[0] - x, goal[1] - z) - heading + math.pi) % (2 * math.pi) - math.pi)
        if near:
            return STAND, plan
        return (TURN_TEXT if scenario == "turn3" and err > math.radians(100) else WALK), plan
    return (STAND if near else WALK), ctl.goto_plan((x, z), (vx, vz), goal, speed, fps)


def joint_indices(model):
    """{'lhip': i, ...} for the joints the gait metrics need, or None if the skeleton does not expose them. Toes are optional."""
    try:
        bi = model.skeleton.bone_index
        idx = {key: bi[name] for key, name in JOINTS}
    except Exception:
        return None
    for key, name in OPTIONAL_JOINTS:
        try:
            idx[key] = bi[name]
        except Exception:
            pass
    return idx


def run(streamer, scenario, args):
    """Returns (full, log, extra): full = [(t, x, z, speed)], extra = joint tracks and the raw chunks for export."""
    streamer.reset()
    fps, horizon = streamer.fps, streamer.horizon
    idx = joint_indices(streamer.model)
    chunks = max(1, int(round(args.seconds * fps / horizon)))
    rows, log, outs = [], [], []
    tracks = {k: [] for k in (idx or {})}
    tkeys = None
    heading = 0.0
    t_frame = 0
    for c in range(chunks):
        state = streamer.root_state()
        prompt, plan = decide(scenario, state, args.speed, fps, heading)
        streamer.begin_chunk(False)
        t0 = time.time()
        out, tkeys = streamer.step(prompt, plan)
        streamer.end_chunk(False, False, None)
        gen_ms = (time.time() - t0) * 1000
        outs.append(out)
        for r in out["root_positions"][0]:
            rows.append((t_frame / fps, float(r[0]), float(r[2])))
            t_frame += 1
        if idx:
            for frame in out["posed_joints"][0]:
                for key in idx:
                    p = frame[idx[key]]
                    tracks[key].append((float(p[0]), float(p[1]), float(p[2])))
            fwd = gm.facing_vectors([(p[0], p[2]) for p in tracks["lhip"]], [(p[0], p[2]) for p in tracks["rhip"]])
            heading = math.atan2(fwd[-1][0], fwd[-1][1])     # where she faces now: 0 = +Z, growing towards +X
        end = rows[-1]
        goal = GOALS.get(scenario)
        gd = f"{math.hypot(goal[0] - end[1], goal[1] - end[2]):.2f} m to goal" if goal else ""
        log.append(f"  chunk {c + 1:2d}  {prompt:26s} ends at x {end[1]:6.2f} z {end[2]:6.2f}  {gd:16s} ({gen_ms:.0f} ms)")
    full = []
    for i, (t, x, z) in enumerate(rows):
        sp = 0.0 if i == 0 else math.hypot(x - rows[i - 1][1], z - rows[i - 1][2]) * fps
        full.append((t, x, z, sp))
    with open(f"probe_{scenario}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t", "x", "z", "speed"])
        for r in full:
            w.writerow([f"{r[0]:.3f}", f"{r[1]:.4f}", f"{r[2]:.4f}", f"{r[3]:.3f}"])
    return full, log, {"tracks": tracks if idx else None, "outs": outs, "tkeys": tkeys}


def summarize(scenario, full, extra, fps):
    t, x, z, sp = zip(*full)
    n = len(full)
    moving = [s for s in sp if s > 0.2]
    r = {"scenario": scenario, "end": f"({x[-1]:.2f}, {z[-1]:.2f})",
         "speed": f"max {max(sp):.2f}, walking {(sum(moving) / len(moving)) if moving else 0:.2f}, "
                  f"at the end {sum(sp[-10:]) / min(10, n):.2f} m/s"}
    goal = GOALS.get(scenario)
    if goal:
        d = [math.hypot(goal[0] - a, goal[1] - b) for a, b in zip(x, z)]
        arrived = next((tt for tt, dd in zip(t, d) if dd < 0.3), None)
        gl = math.hypot(*goal)
        dev = max(abs(a * goal[1] - b * goal[0]) / gl for a, b in zip(x, z))
        r["goal"] = f"error {d[-1]:.2f} m, arrived at {('%.1fs' % arrived) if arrived is not None else 'never'}, max {dev:.2f} m off the line"
    elif scenario == "forward":
        r["goal"] = f"{z[-1]:.2f} m in {t[-1]:.0f}s, sideways drift {max(abs(a) for a in x):.2f} m"
    else:
        r["goal"] = f"{math.hypot(x[-1], z[-1]):.2f} m in {t[-1]:.0f}s"

    tr = (extra or {}).get("tracks")
    if tr and tr["lhip"]:
        fw = gm.facing_vectors([(p[0], p[2]) for p in tr["lhip"]], [(p[0], p[2]) for p in tr["rhip"]])
        mis = gm.misalignment_deg(fw, [(a, b) for _, a, b, _ in full], fps)
        if mis:
            r["facing vs travel"] = (f"median {gm.percentile(mis, 0.5):.0f} deg, 90th percentile {gm.percentile(mis, 0.9):.0f} deg "
                                     f"(0 = forward, 90 = sidestep, 180 = backwards)")
        else:
            r["facing vs travel"] = "she barely moved"
        total, fastest = gm.turn_stats(fw, fps)
        r["turning"] = f"{total:.0f} deg in total, fastest {fastest:.0f} deg/s"
        keys = ("ltoe", "rtoe") if "ltoe" in tr else ("lfoot", "rfoot")
        skates = [s for s in (gm.foot_skate(tr[keys[0]], fps), gm.foot_skate(tr[keys[1]], fps)) if s is not None]
        r["foot skate"] = (f"{sum(skates) / len(skates):.2f} m/s while planted ({'toes' if keys[0] == 'ltoe' else 'ankles'}; "
                           f"compare walking scenarios only)") if skates else "no planted frames"
    else:
        r["body metrics"] = "unavailable (the skeleton did not expose the hip and foot joints)"
    return r


def export_bvh(scenario, extra, fps, args):
    """Write the whole scenario as one BVH (VaM joint names) into --bvh-dir, without touching the live latest_vam.bvh."""
    try:
        import ardy_stream as st

        merged = st.concat_chunks(extra["outs"], extra["tkeys"])
        ns = SimpleNamespace(out_dir=args.bvh_dir, converter=args.converter, scale=args.scale, keep=True)
        st.export_chunk(merged, fps, scenario, ns, f"probe_{scenario}")
        print(f"  wrote {Path(args.bvh_dir) / ('probe_' + scenario + '.bvh')}")
    except Exception as e:
        print(f"  could not write the BVH ({type(e).__name__}: {e})")


def main():
    p = argparse.ArgumentParser(description="Does ARDY follow root-path constraints, and does she still walk naturally?")
    p.add_argument("--scenario", default="all", choices=["all"] + ALL)
    p.add_argument("--speed", type=float, default=1.0, help="walking speed to ask for, m/s (default 1.0)")
    p.add_argument("--seconds", type=float, default=14, help="how long to run each scenario (default 14)")
    p.add_argument("--history", type=int, default=40, help="history frames (default 40 = 2 s, like the stream)")
    p.add_argument("--cfg-text", type=float, default=3.0)
    p.add_argument("--cfg-constraint", type=float, default=2.0, help="how hard the model follows the constraint")
    p.add_argument("--steps", type=int, default=None, help="denoising steps (default: the model's own)")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--postprocess", action="store_true",
                   help="run ARDY's post-processing (reduces foot skating; a little slower). Compare the foot skate numbers with and without it")
    p.add_argument("--pp-constraints", action="store_true",
                   help="with --postprocess: also give the post-processing the root plan, so it can pull the root onto it")
    p.add_argument("--save-bvh", action="store_true", help="also write each scenario as a BVH you can play in VaM")
    p.add_argument("--bvh-dir", default="probe_bvh")
    p.add_argument("--converter", default=a2v.DEFAULT_CONVERTER, help="path to ardy2bvh.py (only for --save-bvh)")
    p.add_argument("--scale", type=float, default=100)
    p.add_argument("--model", default=None)
    p.add_argument("--checkpoints_dir", default=None)
    p.add_argument("--full-encoder", action="store_true")
    args = p.parse_args()

    if not args.full_encoder:
        os.environ.setdefault("ARDY_TEXT_ENCODER_INT8", a2v.INT8_REPO)
    gen = a2v.ArdyGenerator(args.model, args.checkpoints_dir)
    streamer = Streamer(gen, history_frames=args.history, steps=args.steps, postprocess=args.postprocess or args.pp_constraints,
                        cfg_weight=(args.cfg_text, args.cfg_constraint), pp_constraints=args.pp_constraints)
    try:
        from ardy.tools import seed_everything
    except Exception:
        seed_everything = None

    scenarios = ALL if args.scenario == "all" else [args.scenario]
    results = []
    for scn in scenarios:
        if seed_everything:
            seed_everything(args.seed)
        print(f"\n=== {scn} ===")
        full, log, extra = run(streamer, scn, args)
        print("\n".join(log))
        if args.save_bvh:
            export_bvh(scn, extra, streamer.fps, args)
        results.append(summarize(scn, full, extra, streamer.fps))

    print("\n================ SUMMARY (paste this) ================")
    print(f"speed asked {args.speed} m/s, text guidance {args.cfg_text:g}, constraint guidance {args.cfg_constraint:g}, "
          f"history {streamer.history_frames} frames, seed {args.seed}, post-processing "
          f"{'with the root plan' if args.pp_constraints else ('on' if args.postprocess else 'off')}")
    for r in results:
        print(f"\n  {r['scenario'].upper()}  ends at {r['end']}")
        for k, v in r.items():
            if k not in ("scenario", "end"):
                print(f"      {k}: {v}")
    print("======================================================")


if __name__ == "__main__":
    main()
