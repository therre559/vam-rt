# Live movement test (typed moves)

She really moves, but only when you tell her to, only a bounded distance, and every move ends by itself. You type into the stream window; nothing
senses or follows you yet (see "Why typed moves first" below).

## What you need running
| Needed | Not needed |
|---|---|
| VaM with Ava in the scene, the **Senses plugin 0.4.1** and the **BVH Player** on her | Voxta, KoboldCpp, voice and speech tools |
| The ARDY **stream** (the stream window of `Start_ARDY.bat` is enough; the prompter window is optional) | |

## Setup (once)
1. Run `tools\deploy.bat`, then reload the Senses plugin in VaM (its title should say v0.4.1). Restart the stream: its first lines should say **ardy_stream v22**
   and list the moves.
2. **Clear space.** Keep at least 4 m free in every direction around her, with nothing she could walk into, trip over or push. The first move shows which way
   ARDY's +Z points in your scene, so do not assume.
3. **BVH Player settings** (all four matter): **In Place (ignore horizontal travel): OFF**, Auto Reload **ON**, Chain Continuous **ON**,
   Chain: ARDY World Coords **ON**. The Watch File is `Saves/Animation/ardy/latest_vam.bvh`.
4. Let her stand still, then press **Set origin here** in the Senses plugin. The **Position report** box (right column) now reads 0.00 m from the origin.
5. In the stream window type `/where`: it should say x 0.00 z 0.00, facing 0 deg.

## How to stop her
- Type **`/stop`** in the stream window: she brakes and stands (about 1-2 m of run-on, less if she is slow).
- Close the stream window (or press Ctrl+C in it): no new motion arrives and the BVH Player freezes on the last frame within about 2 seconds.
- Untick **Auto Reload** in the BVH Player: she finishes the current chunk, then freezes.
- A stream restart or `/reset` puts ARDY's origin back at (0, 0): she **snaps back** to where her atom is. That is expected.

## The test sequence
Give each move while she **stands still**, and wait until the stream prints "move finished" and then about 5 more seconds, because VaM plays the motion 2-4 s after the
stream generated it. After each step note the stream's `/where` and the Senses plugin's **Position report**.

| # | Type | What should happen | Look for |
|---|---|---|---|
| 1 | `/walk 1` | She takes a step or two forward and stands. Starts moving about 2 s after you type. | does she move at all? which way (ARDY +Z)? |
| 2 | `/walk 3` | She walks about 3 m straight and stops. | does she stop where she should? feet sliding? |
| 3 | `/home` | She walks back to where she started. | does she return to the origin (Position report near 0.00 m)? |
| 4 | `/goto 2 4` | A diagonal walk with a gentle turn on the way, then she stops. | turn natural? faces the way she walks? |
| 5 | `/goto 0 -3` | The goal is behind her: she should swing round on a curve, not walk backwards. | backwards walk? stumble? |
| 6 | `/speed 0.8`, then `/walk 3` | A slower walk (the default is 1.0). | more foot sliding at low speed? |
| 7 | `/speed 1.3`, then `/walk 4` | A brisker walk. | smoother? |
| 8 | `/walk 3` and, during the walk, `/stop` | She brakes and stands well short of 3 m. | how far does she run on? |
| 9 | `/home` | Back to the origin. | |

If something goes wrong, `/stop` first, then ask what you saw.

## What to send me
For each step: what you typed, the stream's `move:` lines and `/where` reply, the Senses plugin's Position report text, and a sentence on how it looked.
The three numbers I care about most:
1. **Real vs intended distance.** Position report "Since the origin" against the stream's distance from (0, 0). A mismatch means a scale problem between ARDY and the
   BVH Player, or physics that cannot keep up.
2. **Real vs intended direction.** The report's dx and dz against ARDY's x and z. If they differ by a fixed rotation, her atom is rotated relative to ARDY's axes.
3. **How it looks.** Sliding feet, snapping, drifting sideways, an unnatural turn, a wobble when she stops.

## What the odd things usually mean
| You see | Likely cause |
|---|---|
| She marches on the spot | In Place is still ON, or Auto Reload is off |
| She walks, then jumps back to the start | the stream restarted or `/reset`; or Chain Continuous / Chain: ARDY World Coords is off |
| The Position report shows much less distance than ARDY | scale mismatch, or her feet are blocked (physics) |
| Position report and ARDY agree in length but differ in direction | her atom is rotated (ARDY +Z is the atom's own forward) |
| She stops short of a typed goal | a move counts as done within 10 cm; larger gaps mean she lags the plan (physics) |
| She falls or crumples | physics could not follow the hips: `/stop`, lower `/speed`, tell me |
| The stream says "constraint not applied" | the constraint was rejected; send me the line |
| `refused: ... farther than the limit` | one move may go at most `--max-move` metres (8) |

## Why typed moves first
ARDY's idea of where she is (`/where`) is the end of the chunk it just generated, which VaM plays 2-4 seconds later. While she walks at a stroll that is about 3 m
ahead of what is on screen. A follower that says "go N metres ahead of her" would overshoot and oscillate. Typed moves avoid the problem (she stands when you give
them) and give us the measurements the follower needs: the real displacement against ARDY's, the true latency, and how the physics body copes with travel.
The next step is a live follower that uses those numbers (commands in a frame that does not depend on the lag, plus a feedback file from the stream).

## Settings
On the stream: `--max-move 8` (the farthest one move may go; 0 turns typed moves off), `--move-speed 1.0` (starting speed; `/speed` changes it) and
`--move-accel 1.0` (how hard she speeds up and brakes, m/s^2; lower is gentler; `/accel` changes it).

## First results (2026-10-03)
**ARDY side:** every move ended within 2-3 cm of its goal (`/walk 3` aimed at (-1.19, 3.75), ended at (-1.18, 3.77); both `/home` runs returned to (-0.01, -0.01)).
**In VaM:** she really walks; she turns on the way to a goal behind or beside her and faces the way she walks; `/speed` changes look like natural changes of stride and pace
and persist until changed. What it also showed:
- **1.2 m/s looks like a jog on Ava; 0.8 looked natural.** The default is now 1.0.
- **VaM's physics does not stop her.** She walked into a chair and through it. The hip controllers are driven straight to where the animation says, so obstacle avoidance has
  to come from us (the Senses plugin's obstacle probes exist for exactly this).
- **She ends facing the way she walked** (away from the user, after walking away from them). Position constraints cannot turn her on the spot; facing the user on arrival needs
  a separate step.
- **The first, short move (`/walk 1`) was followed by a few seconds of crouching** (hip height 0.77-0.87 m against 0.93 standing, and two "anchor released" messages; no other move
  did this). Two likely causes, both addressed: the "walks forward" text had never been encoded before, so the first move paid ~0.5 s for it and the playback ran dry (the texts are now
  encoded at startup), and a 1 m move at 1.5 m/s^2 means 0 to 1.2 m/s and back to 0 in 1.6 s (now 1.0 m/s^2 and adjustable). Not proven which mattered more: if `/walk 1` still crouches,
  tell me.
- **The safety limits work:** a move beyond 8 m was refused (8.8 m and 13.1 m), `/speed 1.8` was clamped to 1.6, and consecutive 3 m walks each covered exactly 3 m.
- **A shuffle at the end of a move** (second `/goto 2 4` run): "0.4 m to go (stands)", then 0.2, then 0.3, her position going 1.59, 1.97, 1.72, 1.98 (about 25 cm back and forth for six seconds, facing
  flipping between -50 and 0 deg). The text switched to "stands upright" within 0.5 m while the plan still asked her to creep the last few centimetres, and ARDY cannot translate by less than about
  one step. Fixed in 0.4.3: a move now finishes within 25 cm and the text stays "walks forward" until it is done. This cannot be reproduced offline; look at the end of each move in your next run
  (no wobble, the last line before "settled" still says "to go" with a walking chunk).
- **Sitting:** "sit down on the chair within reach" made her sit where she stood (hip height 0.51-0.55 m) with no chair under her, which Voxta's chat rightly called out ("you are sitting on nothing").
  She cannot go to a chair yet; that is the next feature (walk to the chair, turn, sit).
- The perceived delay between typing and the first steps was short (about 1-2 s) because she was standing with nothing queued.

Not yet measured: the Position report numbers (real distance and direction against ARDY's). To get them: stand still, press **Set origin here**, type `/goto 2 4`, wait about 8 s after
"move finished", then copy the Position report; then `/home` and copy it again.
