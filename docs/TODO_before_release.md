# Open items before the first Hub post (19 Nov 2026)

Done since the skeleton: v5.9 player is in the var; ardy2bvh is iremoztrk/ardy2bvh (Apache-2.0) and setup.bat clones it; the
ARDY install is pinned (nv-tlabs/ardy e706e27) with `ARDY_SKIP_MOTION_CORRECTION=1` (no compiler needed); the 8-bit encoder is
handled by `pc/tools/patch_ardy_int8.py`; Start_Encoder.bat carries the working settings; VTE licence filled in (CC BY-SA);
the scenario's plugin ids read plugin#3 / plugin#1 (the demo scene's).

Still needed from Lynn:
1. Done. The 8-bit encoder WITH the Llama 3 prompt header (what `patch_ardy_int8.py` installs) was tested on Lynn's rig 19 Nov:
   works, nothing broken. `ARDY_TEXT_ENCODER_INT8_RAW=1` keeps the older no-header behaviour available.
2. Done: creator Gingersnap559 (the Hub username; VaM's builder uses the creator name from User Preferences), repo github.com/therre559/vam-rt (create the repo and push this tree; README links point there).
3. Done: the demo scene is Lynn's VaM-saved copy (19 Nov) with her Voxta character/scenario ids stripped and the release defaults
   re-applied. Root cause of the settings not restoring: VaM's storable id for Senses is `plugin#N_VaMRT.Senses` (class name),
   not `VaMRT_Senses` (file name); the first scene used the wrong id.
4. A fresh Voxta export (.voxpak) of the scenario with the plugin ids at plugin#3 / plugin#1, for people who prefer importing a pak
   (the JSON import works without it).
5. `setup.bat` has NOT been run on a clean PC (no second machine available). Say so in the Hub post and ask the first installer to
   report; KNOWN_ISSUES.md carries the fallback.
6. ROTATE the OpenRouter key that was in Start_ARDY_rh.bat.
