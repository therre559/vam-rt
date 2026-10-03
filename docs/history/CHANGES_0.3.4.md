# What to update for 0.3.4 (locomotion groundwork; the Senses plugin is unchanged)
1. Unzip over the repo, then run tools\deploy.bat (it copies the new scripts into your ARDY scripts folder).
2. Nothing changes in VaM, Voxta or the prompter. The stream behaves as before: the new constraint code only runs when a plan is passed.
3. Run the experiment (about 5 minutes) and send me the SUMMARY block:
       cd "C:\Users\Todd Herre\Desktop\ardy-main\ardy-main"
       python scripts\constraint_probe.py
4. Please also re-send `ardy/constraints.py`. Both of your files were called constraints.py, so only the demo's one arrived:
   copy ardy\constraints.py to ardy_constraints.py on your desktop first, then upload that.
