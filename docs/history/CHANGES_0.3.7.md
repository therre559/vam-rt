# What to update for 0.3.7 (planner fix; the Senses plugin and the stream are unchanged)
1. Unzip over the repo, then run tools\deploy.bat.
2. Rerun the probe (10-15 seconds) and send me the SUMMARY block:
       cd "C:\Users\Todd Herre\Desktop\ardy-main\ardy-main"
       call "C:\Users\Todd Herre\Miniconda3\Scripts\activate.bat" ardy
       python scripts\constraint_probe.py --save-bvh --bvh-dir "C:\Users\Todd Herre\Desktop\New folder (4)\Saves\Animation\probe"
   Look at TURN2, TURN3 and SIDE2: the error should now be under 0.1 m and "at the end" about 0.0 m/s (before: 0.2-0.35 m and 0.3 m/s).
3. Watch probe_turn2.bvh and probe_side2.bvh in VaM (In Place off; steps in docs/LOCOMOTION.md) and tell me what she does.
