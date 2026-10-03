# Changelog

## 0.4.3
- Typed moves no longer shuffle at the end: a move is done within 25 cm of the goal (was 10 cm) and the text stays "walks forward" until it is done (it used to switch to "stands upright" within
  0.5 m while the plan still moved her; the log showed her crossing the goal back and forth by about 25 cm for six seconds). Reasoned from the live log, not reproducible offline.
- Live log notes: limits and speed clamps work; "sit down on the chair" sits in place (no chair under her): walking to a chair is the next feature.

## 0.4.2
- First live results (docs/LIVE_TEST.md): moves end within 2-3 cm of the goal in ARDY, she walks and turns naturally in VaM, speed changes look natural, but 1.2 m/s looks like a jog,
  she walks through furniture (the physics does not stop her) and a short first move was followed by a crouch.
- Stream v22: the move texts are encoded at startup (the first move no longer causes a playback gap), moves default to 1.0 m/s and a gentler 1.0 m/s^2 (`--move-accel`, `/accel`),
  and every move ends with a result line (from, to, distance, facing).

## 0.4.1
- **Typed moves** (stream v21): `/walk 3`, `/goto 2 4`, `/go 2 1`, `/home`, `/stop`, `/speed`, `/where` in the stream window make her really walk with the steering planner. Each move ends by
  itself (arrival within 10 cm, a timeout that brakes and then gives up, `/stop`), the farthest single move is `--max-move` (8 m). New `move_control.py`, tests, and docs/LIVE_TEST.md.
- The stream knows her facing (from the hips, calibrated once; rolled back with a rolled-back chunk) via `Streamer.root_pose()`.
- Senses 0.4.1: follow measures her at the **hips** (they travel when In Place is off; the base control stays behind), plus a **Position report** and a "Set origin here" button for
  comparing real and intended displacement.

## 0.4.0
- Senses: **Follow (dry run)**. Reports what she would do to stay within reach of the user: distance band, goal point, obstacles (six physics rays),
  ground ahead, allowed area. Nothing is sent and she does not move. Callable actions *Start follow (dry run)* / *Stop follow (dry run)*.
- Probe: `--postprocess` and `--pp-constraints` to try ARDY's post-processing against foot sliding. `Streamer` can pass the root plan to it.
- Docs: new FOLLOW.md and LOCOMOTION.md findings, updated ARCHITECTURE.md, README.md and TESTING.md. This changelog replaces the per-version notes.

## 0.3.7
- Steering planner: arrival radius (within 0.35 m she stands still) and a distance-limited speed while turning. Fixes her looping around the goal.
  Tested on 720 simulated starts.

## 0.3.6
- `steer_plan`: a heading-aware planner (limited turn rate, slow while misaligned, brakes to stop). Probe scenarios turn2, turn3, side2.
  Turning is averaged over a second so stride sway does not count; foot skate uses the toes.

## 0.3.5
- Probe version 2: gait metrics (facing vs travel, turning, foot skate) and BVH export to watch results in VaM. Showed that constraints alone make her walk
  backwards to a goal behind her.

## 0.3.4
- Locomotion groundwork: `ardy_control.py` (velocity and go-to plans), constraint tensors in `Streamer.step(prompt, plan=None)` built with the
  recipe of NVIDIA's interactive demo, and `constraint_probe.py`. First result: she follows root paths to 1 cm.

## 0.3.3
- Durations: every final movement in a plan gets a lifetime and a return (the prompter recognises "is walking" and multi-part plans), the stream gets a
  runaway guard (`--runaway-seconds`, default 60) and clamps timed parts to 180 s, the BVH Player warns about loop modes.

## 0.3.2
- Senses plugin offers callable actions (*Send snapshot now*, *Calibrate standing height*, *Fire On Approach/Leave/Stare*), shows E-Motion's controls
  in the debug numbers. BVH Player: Auto Reload on and the Watch File pre-filled with the stream's output by default.

## 0.3.1
- **Reactions** replace the trigger panels of 0.3.0 (which did not compile: `EventTrigger` is MacGruber's own wrapper, not part of VaM): for each of
  approach / leave / stare pick an atom, one of its plugins and an action to call.

## 0.3.0
- E-Motion mood in the scene description. (The trigger panels in this version did not compile in VaM; see 0.3.1.)

## 0.2.x
- Events: approach, leave and stare, sent to Voxta without interrupting conversations (cooldown, quiet time, stare re-arms after a look away,
  rotating wording). A new chat resets the cooldowns.
- Prompter: names are scrubbed from ARDY prompts, one-part movements end after a few seconds, held poses.

## 0.1.x
- First import of the working prototype; the Senses plugin loads in VaM (plugin class first in the file, no System.Reflection).
