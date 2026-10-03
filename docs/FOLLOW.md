# Follow: staying within reach of the user

Goal: "walk and talk with me". She keeps within a comfortable distance of the user, turns and walks like a person, and never walks through walls,
off an edge or out of an allowed area. Time is not the limit; conditions are.

## Status
**Dry run only (Senses plugin 0.4.1).** The plugin measures, decides and *reports* what she would do. Nothing is sent and she does not move. This lets
you verify every rule by walking around before any real movement exists. Her position is measured at her hips (they are what travels when In Place is off).
Real movement is being tested separately with typed moves: see LIVE_TEST.md.

## What live movement taught us (typed moves, 2026-10-03)
- She walked into a chair and through it: **VaM's physics does not stop her**, so the obstacle and ground checks must be enforced by us before and during every move.
- She finishes facing the way she walked, so "face the user on arrival" needs its own step.
- A walking speed of about 1.0 m/s looks right on Ava (1.2 looks like a jog): the follower's speed should be a setting, ideally scaled to the body.
- ARDY follows the plans to 2-3 cm, so the remaining error budget is VaM's physics and the lag.

## Why it is not live yet
ARDY's pose is the end of the chunk it just generated, which VaM plays 2-4 s later, so a command "N m ahead of her" is applied from a pose that is already
about 3 m ahead of what is on screen while she walks. The live follower needs commands in a frame that does not depend on that lag (the goal as a fixed point in
the world, with a measured transform between VaM's and ARDY's coordinates) and a feedback file from the stream so the plugin can see what the stream is doing.
The typed-move test provides the measurements for that.

## The design in one picture
    Senses plugin (VaM)                                   motion stream (Python)
      every 0.5 s:  where is she, where is the user,        every 2 s chunk:
      what is in the way, is there floor, inside the area?    read the command; if its lease has run out -> stand
      -> decision                                             convert "ahead / right" to ARDY's world frame
      -> command (her own frame, short lease)  ---------->    steer_plan(...) -> root waypoints -> constraint
                                                              text: "walks forward" or "stands upright"

- **A lease, not a command.** Every command is valid for 3 s. The plugin renews it while its conditions hold. If the plugin stops (reload, crash, stale
  senses) nothing renews it and she stands within seconds. The stream's 60 s runaway guard stays for uncontrolled movement.
- **Her own frame.** The command says "1.6 m ahead, 0.4 m to the right". The stream converts it with her real position and heading, so VaM's and ARDY's
  coordinates never have to be calibrated against each other, and any drift is corrected at the next measurement.
- **The planner handles the walking.** `ardy_control.steer_plan` turns at a limited rate, walks slowly while still turning, brakes to stop on the goal, and
  stands still within 35 cm of it (see LOCOMOTION.md).

## What the dry run checks
| Check | Rule |
|---|---|
| distance to the user | closer than the minimum (0.8 m): stays put. Within the maximum (2.5 m): stays put. Farther: aims for a point 1.8 m from the user, on the line towards her |
| allowed area | a radius (6 m) around a centre (where she was when follow was switched on, or set by the button). The goal is clamped to it, so she is brought back to its edge, never farther out |
| obstacles | six rays towards the goal (knee and waist height, centre and 30 cm either side); her own body is looked through, triggers are ignored. An obstacle on the way closer than 0.95 m (0.6 m stopping margin + the 0.35 m arrival radius): she stays put; farther: she walks up to 0.6 m short of it. Obstacles beyond the goal are ignored |
| ground | a ray down every 0.6 m along the path: floor within 25 cm of the level she stands on is fine; no floor or a step/drop stops her. If there is no floor under her at all (a scene without a floor) the check is skipped |
| speed | the set walking speed (default 1.2 m/s; 1.2-1.3 gave the least sliding) |

## Plugin controls (all saved with the scene)
- **Follow (dry run: only reports)** on/off. Actions for Timeline or other plugins: *Start follow (dry run)*, *Stop follow (dry run)*.
- **Start walking when farther than** (2.5 m), **stay put when closer than** (0.8 m), **walk to a point this far from you** (1.8 m, never beyond the first),
  **walking speed** (1.2 m/s), **allowed area radius** (6 m), **require ground ahead**, and the button **set the area centre here**.
- The **Follow report** box shows, every half second, for example:

      FOLLOW (dry run: nothing is sent, she does not move)
      would WALK 3.2 m ahead, 0.4 m to the right at 1.2 m/s: too far from the user
      user 5.0 m away (walks when over 2.5 m, stays put under 0.8 m)
      path: clear | ground: ok
      area: she is 1.2 m from its centre (limit 6.0 m)
      would send: {"cmd":"goto","forward":3.20,"right":0.40,"speed":1.2,"lease_s":3}

## The command (the contract with the stream)
    {"cmd":"goto","forward":3.20,"right":0.40,"speed":1.2,"lease_s":3}     walk to a point: metres ahead / to the right of her, at this speed
    {"cmd":"stand","lease_s":3}                                              stand still
The plugin will write it to a small file next to the request file; the stream reads it every chunk. Numbers always use a decimal dot.

## Try it in VaM (about 10 minutes)
1. Reload the Senses plugin (0.4.0). Switch **Follow (dry run)** on. Everything below is only read from the report box.
2. **Distance.** Stand 1.5 m away: "would STAND: within reach". Walk back to 5 m: "would WALK ... ahead". Walk to 0.5 m: "too close".
3. **Direction.** Stand to her left, right and behind her: the "m to the left / right" and "ahead" values (negative ahead = behind her) should match where
   you are.
4. **Obstacle.** With you 5 m away, add a Cube (or press *Spawn test props*) on the line between her and the point 1.8 m from you. The path line should
   name it with its distance (for example "'VaMRT Table [surface]' at 1.2 m"). Under 0.95 m she should "stand". Remove the cube: "path: clear". Then check
   that she is *not* blocked by her own body, and that things beyond the goal or behind you are ignored.
5. **Area.** Set the radius to 2 m and walk far away: the goal should stop at the edge ("walking to the edge of the allowed area"), then "at its edge".
6. **Ground.** In a scene with a floor the ground line should read "ok". Move her next to the floor's edge, or use a scene with a hole: "a step or drop at X m".
   With no floor at all it reads "no floor under her, not checked".
7. Tell me anything that is wrong. The physics checks (obstacles, ground) are the part that could not be tested outside VaM.

## Next
0. Typed moves in VaM (LIVE_TEST.md): real vs intended displacement, latency, physics, looks.
1. Verify the dry run in VaM (above) and tune the numbers.
2. The stream side: read the command file, check the lease, convert to the world frame with `Streamer.root_state()` and her heading from her hips,
   plan with `steer_plan`, switch the text between "walks forward" and "stands upright", with a fresh-command watchdog.
3. The plugin side: write the command, honour the lease, apply root travel to her base control (In Place off) and an emergency stop action.
4. Voxta: "walk with me" starts follow; "stop" or "stay here" ends it. Then moving targets (predicting the user's path to hide the 2 s lag).
