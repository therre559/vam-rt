# Testing checklist
Run in order. Each layer depends on the one before it. For every test copy the **Debug numbers**, **Status** and **Last error** boxes.

1. **It loads.** Reload the plugin: no red error, the panel appears.
2. **Reactions.** Under "On Stare: call this action" pick atom, plugin, action (for example `Person` > this plugin > `Send snapshot now`),
   press "Test: On Stare". Status should say what was called. Save the scene, reload it, check the choices are still there.
3. **Presence, no Voxta.** Switch on "Run reactions". Start about 5 m away, walk up, walk away, stare silently for 10 s.
   The Debug numbers (`reactions:` and `last reaction:`) should show each trigger.
4. **Voxta events.** Switch on "Send events". Stare silently: one event in the Voxta log ("Event (Requested)"). Talk while staring: nothing
   during the conversation or the quiet time after it. Reload the chat: the first stare works at once.
5. **Prompter.** Let a stare produce a motion (or type "tease me"). It should end after about 4 s and contain no names.
6. **E-Motion and Glance.** See "E-Motion setup". Does she blink, keep eye contact, breathe, without jitter or broken lip-sync?

## Are my settings saved with the scene?
Set "Radius" to 8, save the scene, then open `Saves/scene/<name>.json` in a text editor and search for `VaMRT.Senses`.
The block should list the plugin's settings (Radius 8). If it is missing, the scene was saved before the change or under another
name. Do the same for `Watch File` to check the BVH Player.

## What a failure tells us
- 1 fails: a VaM call is not what the code assumes (the compile error says which).
- 2 lists stay empty: how the dropdown callbacks fire is different from what the code assumes.
- 3 shows nothing moving: the user-position reading is off.
- 4 fires during conversation: Voxta's `State` field is not what the code assumes.
- 6 jitters: E-Motion's idle movement fights the animation.

## Follow (dry run) and the offline tests
- **Follow in VaM:** the ten-minute checklist in FOLLOW.md. The distance, direction and area rules are tested offline; the obstacle and ground
  probes use VaM's physics and can only be checked in VaM.
- **Offline tests (no VaM, no GPU).** From the repo root:

      cd plugin\tests && sh run_tests.sh              (needs Mono: compiles the plugin against stand-ins, checks the namespaces, runs the logic tests)
      cd server && python tests\test_control.py         (planners, 720-start steering check)
      cd server && python tests\test_gait_metrics.py
      cd server && python tests\test_probe_logic.py
      cd server && python tests\test_stream_guard.py
      cd server && python tests\test_move_control.py
      cd server && python tests\test_stream_moves.py
      cd server && python motion_prompter.py --selftest

  Every one ends with "ALL GOOD" (the selftest with "all good").
- **Real model, standalone (10-15 s):** `constraint_probe.py`, see LOCOMOTION.md.
- **Real movement in VaM:** typed moves, see LIVE_TEST.md.
