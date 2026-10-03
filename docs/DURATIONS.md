# How long things last

Nothing the character does may run forever. Every layer has its own limit, so a bug in one cannot leave her stuck.

| Layer | What it enforces | Defaults |
|---|---|---|
| **Prompter** (`motion_prompter.py`) | The last part of a plan is open-ended ("hold until changed"), so it must be a pose. Any final *movement* gets a length and a return to what she was doing. | gesture or unknown reaction 4 s, walk or march or pace 10 s, jog 12 s, sway 20 s, dance 60 s; "keep ..." doubles it; never more than 180 s |
| **Stream** (`ardy_stream.py` v20) | Timed parts are clamped to 180 s. **Duration guard:** an open-ended part that keeps moving (above 0.12 m/s) for 60 s without settling is cut off and she goes back to her last settled pose (or standing). | `--runaway-seconds 60` (0 = off) |
| **BVH Player** | With play mode "once" (the default) it freezes on the last frame when no new chunk arrives, so a crashed stream leaves her holding a pose. Loop or ping-pong would repeat the last chunk; the watch status now warns about that. | play mode: once |

What the prompter now recognises as a pose (held) or a movement (timed):
- Poses: `A person stands with their legs wide apart.`, `sits cross-legged ...`, `squats down.`, `stands with their arms raised overhead.`
- Movements: anything with a motion verb even when it starts like a pose (`A person is walking forward.`, `A person stands and waves.`),
  and any line that does not start with a pose verb. Unknown verbs count as movements, because ending a pose early is harmless and
  holding a movement forever is not.

## Quick checks
1. Start the stream with a short guard: `--runaway-seconds 15`. In its console type `A person walks forward. [free]`.
   After about 15 s it prints "duration guard: ... going back to ..." and she settles.
2. While she walks, press Ctrl+C in the stream window. She must freeze, not keep stepping.
3. Ask for "keep walking" through Voxta: the prompter writes `@20 >> A person stands upright.`
4. `python motion_prompter.py --selftest` and `python tests/test_stream_guard.py` (in `server`) must both end well.

## Requirements for locomotion (before any root motion is switched on)
These come from the lessons above. Locomotion stays off by default until every one is in place and tested:
1. **A lease, not a command.** Every move has an expiry: the distance divided by the speed plus a margin, and a hard maximum
   (30 s). No renewal means she stops.
2. **Only while the animation is fresh.** Root travel is applied only while the watched file is still being updated. If it is
   stale for more than two chunks (4 s), travel stops at once and she holds.
3. **Arrival and progress.** Stop when within a set distance of the target, or when she has not made progress for a few seconds.
4. **Any new request cancels the move first.** A new prompt replaces the plan, and a move is part of the plan.
5. **A stop action.** "Stop moving" is callable from Voxta, a trigger and a button, and always wins.
6. **Bounded area.** She can only travel within a radius of where the move started (or inside marked bounds).
7. **In place remains the default.** A separate switch turns travel on.
