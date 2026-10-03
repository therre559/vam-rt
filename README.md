# VaM-RT (working name)

Real-time, text-driven character motion for Virt-A-Mate, with the goal of NPCs that decide what to do instead of playing fixed animations.

**Status: working prototype, moving towards autonomy.** Voxta turns what you say into an action request, a small Python server turns that into a motion
prompt for NVIDIA's ARDY model, and a VaM plugin plays the generated BVH. A second plugin (Senses) tells the character about her surroundings and
reports what she would do to stay near you. See docs/ARCHITECTURE.md for the whole picture and where it is going.

## What works today
- **Voice-driven body motion:** Voxta action -> motion prompter (fast path or LLM, every movement gets a lifetime) -> ARDY stream -> BVH Player.
- **Senses plugin:** a short text description of the world (her pose, you, nearby chairs and tables) written to Voxta's context; events (you approach,
  leave, stare) sent to Voxta without interrupting conversations; reactions that call any plugin action (for example a Timeline clip); optional
  E-Motion mood. Docs: docs/SENSES.md.
- **Nothing runs forever:** durations are enforced in the prompter, the stream and the player. Docs: docs/DURATIONS.md.
- **Locomotion groundwork:** ARDY follows root paths almost exactly; a steering planner makes her turn and walk forward to any goal; a standalone
  probe measures it. Docs: docs/LOCOMOTION.md.
- **Follow (dry run):** reports what she would do to stay within reach of you (distance, obstacles, ground, allowed area). She does not move yet.
  Docs: docs/FOLLOW.md.

## Layout
- plugin/   the VaM side (C#). plugin/VaMRT is the Senses plugin; plugin/legacy holds the patched BVH Player we run today; plugin/tests compile-checks the plugin outside VaM.
- server/   the generator side (Python): stream, prompter, lab, planners, probe, launchers, tests.
- voxta/    the Voxta character card and scenario used for testing.
- docs/     design notes and findings.
- tools/    helper scripts (deploy.bat copies the files into VaM and ARDY).
- CHANGELOG.md, CREDITS.md

## Requirements (not included)
Virt-A-Mate, the Voxta server and its VaM plugin, NVIDIA ARDY with its model weights, a CUDA GPU, and an LLM endpoint for the prompt writer (any
OpenAI-compatible server; we use KoboldCpp). Optional: the E-Motion, Glance and Timeline plugins.

## Install and update
1. Edit the two paths at the top of tools/deploy.bat for your machine, then run it. It copies the plugins into VaM and the scripts into ARDY's scripts folder.
2. Restart the stream and the prompter (the launchers in server/), and reload the plugins in VaM.

## Tests
Offline, no GPU and no VaM needed (the plugin check needs Mono). See docs/TESTING.md for the commands; each ends with "ALL GOOD".

See CREDITS.md for licenses and attribution.
