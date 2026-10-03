# Changelog

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
