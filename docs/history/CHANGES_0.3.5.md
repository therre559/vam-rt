# What to update for 0.3.5 (probe version 2; the Senses plugin and the stream are unchanged)
1. Unzip over the repo, then run tools\deploy.bat.
2. Close the stream window and VaM/Voxta if VRAM is tight, then run (about 3 minutes):
       cd "C:\Users\Todd Herre\Desktop\ardy-main\ardy-main"
       call "C:\Users\Todd Herre\Miniconda3\Scripts\activate.bat" ardy
       python scripts\constraint_probe.py --save-bvh --bvh-dir "C:\Users\Todd Herre\Desktop\New folder (4)\Saves\Animation\probe"
3. Send me the SUMMARY block.
4. Then watch probe_turn, probe_side and probe_goto in VaM (steps in docs/LOCOMOTION.md) and tell me what she does:
   turns around, walks backwards, sidesteps, or slides.
