# Locomotion: findings and tools

How the character will walk to a point, follow the user and turn naturally, using ARDY's kinematic constraints. Everything here was
measured on the Core model (ARDY-Core-RP-20FPS-Horizon40) with `server/constraint_probe.py`.

## Summary
1. **Root paths are followed almost exactly.** Position error is 0.01 m; asked for 1.0 m/s she walks 0.98 m/s with 0.10 m sideways drift over 13 m.
2. **Constraints do not control where she faces.** Asked for a goal behind her she walks *backwards*; for a goal beside her she glides sideways.
3. **A steering planner fixes that.** A path that curves the way a forward walker would turn (limited turn rate, slow while misaligned) is walked
   forward the whole way, and the turn text ("turns around") is not needed.
4. **She stops cleanly** with an arrival radius: within 0.35 m of the goal the plan is "stand still". Without it she wandered ~0.3 m around the goal.
5. **Compute is not the limit.** A 2 s chunk takes ~85 ms with the GPU to herself (250-350 ms in the live stream, which shares it with VaM, Voxta and
   the voice). Responsiveness is limited by the 2 s chunk length.
6. **Foot sliding grows as she walks slower than her natural pace** (toe skate 0.40 / 0.33 / 0.30 at 0.7 / 1.0 / 1.3 m/s, 0.23 unconstrained at
   1.64 m/s). So the follower should walk at 1.2-1.3 m/s to catch up or keep pace; for a slow-walking user, short natural-speed bursts with pauses
   may look better than a constant slow slide. Not yet judged by eye.

## Facts about ARDY's constraints
Sources: ARDY's README, `ardy/model/ardy_model.py` (`autoregressive_step`), and the interactive demo's `gen_constraints.py` and `generation.py`.
- A constraint is two tensors, `motion_mask` and `observed_motion` (`[batch, frames, motion_rep_dim]`), passed to `autoregressive_step`.
- The window is `[history | generation horizon | future]`. History frames are never constrained. A waypoint 2-4 s ahead needs a window longer than
  history + horizon (10 s at most).
- Positions are in the same world frame as the generated motion. The model recentres the history internally and translates back.
- Recipe: `Root2DConstraintSet(skeleton, frame_indices, root_xz)` -> `motion_rep.create_conditions_from_constraints(...)` -> `motion_rep.normalize(...)`
  -> multiply by the mask.
- The demo's "target velocity" is a list of future (x, z) positions every ~4 frames, integrated from the current root position and velocity.
- Constraint strength is the second number of `cfg_weight` = (text, constraint); the stream sends 2.0.
- Optional post-processing (`post_process_motion`) can use the constraints to improve how closely they are followed and to reduce foot skating.
- Unknown: the heading convention of the demo (its comment says 0 is +Z, its formula is atan2(vz, vx)); `ardy/constraints.py` has not been read.
  Heading is not constrained here at all; the planner steers instead.

## Results
Run settings: history 40, text guidance 3, constraint guidance 2, seed 1, speed 1.0 m/s unless noted. "Facing vs travel" is the angle between her
pelvis direction and her travel direction (0 = forward, 90 = sidestep, 180 = backwards).

| Scenario | Goal | Result |
|---|---|---|
| baseline (no constraint) | none | walks 1.64 m/s (peak 2.93), curves ~6 m off line in 22 m |
| forward | straight ahead at 1.0 m/s | 0.98 m/s, drift 0.10 m, facing vs travel 3 deg |
| goto, stop | 27 deg off / straight ahead | error 0.00 m, ends at 0.0 m/s, facing vs travel 3 deg |
| turn, side (plain planner) | behind her / to her side | error 0.00 m but facing vs travel **172 / 120 deg**: backwards / gliding |
| turn2, turn3, side2 (steering planner) | behind / behind with turn text / side | facing vs travel 7 / 5 / 16 deg; error 0.04 / 0.04 / 0.07 m; ends at 0.01 m/s |

Walking speed (forward scenario): asked 0.7 -> 0.69, 1.0 -> 0.98, 1.3 -> 1.24 m/s; facing vs travel 5 / 3 / 4 deg.

The steering planner's first version looped around the goal (0.3 m wander, 500+ deg of turning): near the goal the direction to it is noisy, and in a
simulation a goal inside the walker's turning circle was orbited forever. Fixed with the arrival radius and a distance-limited speed while turning;
`tests/test_control.py` checks 720 simulated starts (all directions, distances, headings, speeds): all arrive, stop and never orbit.

## Not yet known
- How it looks in VaM: the physics body walking with In Place off, turn naturalness, visible foot sliding (watch the `probe_*.bvh` files).
- Whether ARDY's post-processing (`--postprocess`, `--pp-constraints`) reduces the sliding. The flags exist in the probe; not yet measured.
- Behaviour with a moving target (a user who walks away mid-chunk) and the 2 s chunk lag.

## Tools in this repo
- `server/ardy_control.py`: plans. `velocity_plan`, `goto_plan` (straight, brakes to stop), `steer_plan` (heading-aware), `constraint_frames`,
  `postprocess_frames`. Pure Python, tested without a GPU (`tests/test_control.py`).
- `server/ardy_stream.py`: `Streamer.step(prompt, plan=None)` builds the constraint tensors with the demo's recipe. Off unless a plan is passed; if
  the constraint cannot be built the step runs without it and prints one warning. `Streamer.root_state()` reports where she is and how fast she moves.
- `server/gait_metrics.py`: facing vs travel, turning (averaged over a second, so stride sway does not count), foot skate (toes).
- `server/constraint_probe.py`: the experiment below. `tests/test_probe_logic.py` checks it with a good walker and a moonwalker.
- The Senses plugin's Follow (dry run), which decides what she would do: see FOLLOW.md.

## Running the probe
From the ARDY folder, with the `ardy` environment active (VaM, Voxta and the stream do not need to be, and should be closed). It takes 10-15 seconds.

    call "C:\Users\Todd Herre\Miniconda3\Scripts\activate.bat" ardy
    python scripts\constraint_probe.py --save-bvh --bvh-dir "C:\Users\Todd Herre\Desktop\New folder (4)\Saves\Animation\probe"

Useful options: `--scenario <name>`, `--speed 0.7`, `--postprocess`, `--postprocess --pp-constraints`, `--cfg-constraint 4`.
Scenarios: baseline, forward, goto, stop, turn, side (plain planner) and turn2, turn3, side2 (steering planner).

To watch a clip: close the stream, switch **In Place** off in the BVH Player, press "Select Watch File", pick `Saves/Animation/probe/probe_turn2.bvh`.
Afterwards select `Saves/Animation/ardy/latest_vam.bvh` again and switch In Place back on.

Reading the summary: `WARNING: root constraint not applied (...)` means the model rejected the constraint and that run was unconstrained;
`goal`: error, arrival time, how far off the straight line; `facing vs travel` and `turning`: whether she faces where she goes and how she turns;
`foot skate`: mean sliding speed of a planted toe (compare walking scenarios with each other, never read the absolute value).
