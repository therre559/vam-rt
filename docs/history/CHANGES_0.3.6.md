# What to update for 0.3.6 (probe version 3; the Senses plugin and the stream are unchanged)
1. Unzip over the repo, then run tools\deploy.bat.
2. Close the stream window, then run (the whole thing takes 10-15 seconds):
       cd "C:\Users\Todd Herre\Desktop\ardy-main\ardy-main"
       call "C:\Users\Todd Herre\Miniconda3\Scripts\activate.bat" ardy
       python scripts\constraint_probe.py --save-bvh --bvh-dir "C:\Users\Todd Herre\Desktop\New folder (4)\Saves\Animation\probe"
3. Send me the SUMMARY block. Look especially at TURN2, TURN3 and SIDE2 against TURN and SIDE.
4. Watch probe_turn2, probe_turn3 and probe_side2 in VaM (In Place off, steps in docs/LOCOMOTION.md) and tell me what she does.
