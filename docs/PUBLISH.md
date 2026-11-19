# Publishing (for the maintainer)

## GitHub (github.com/therre559/vam-rt)
Fresh checkout, replace everything, push. In Git Bash or a terminal on the PC:

    git clone https://github.com/therre559/vam-rt
    cd vam-rt
    git rm -r -q .                      # removes the old tree from the index (history is kept)
    # copy the CONTENTS of the VaMRT folder from the release zip into this folder (README.md at the root)
    git add -A
    git status                          # make sure pc/config.bat is NOT listed (only config.example.bat)
    git commit -m "VaMRT 1.0: ARDY stream, prompter, Senses, Face, BVH Player v5.9, Hub var"
    git push

Then on GitHub: Settings -> make the repository public (the Hub page and the var's meta.json link to it), and under
Releases -> Draft a new release, tag `v1.0`, attach `VaMRT.NPC.1.var` and the release zip, so people who do not use git have a
download button.

If GitHub Desktop is easier: File -> Clone repository -> therre559/vam-rt; delete every file in the folder it made (not the .git
folder); copy the VaMRT folder's contents in; GitHub Desktop lists the changes; write the summary; Commit to main; Push origin.

## Hub (hub.virtamate.com)
1. Resource Manager -> Add resource -> category *Plugins* (it is a plugin set with a demo scene; *Scenes* would hide it from
   the people it is for).
2. Title: `VaMRT - real-time AI-driven NPC (NVIDIA ARDY + Voxta)`. Tag line: one sentence from HUB_POST.md.
3. Upload `VaMRT.NPC.1.var` as the resource file. The Hub reads meta.json for the dependency list; check it shows Voxta,
   VoxtaTouchElite, AshAuryn 2022 pack 2, asco expressions and the NoStage3 hair, all as Hub-hosted.
4. Overview: paste HUB_POST.md (the Hub uses BBCode-ish formatting; headings become bold lines, links stay links).
5. Licence: CC BY (what meta.json says). External link: the GitHub repo. Mark it as a *prototype / work in progress* in the
   title or first line - that sets expectations and invites the people who like to fix things.
6. Media: at least one screenshot of the demo scene and, if you have it, a short clip of "come here" / "sit in that chair" from
   voice to seated. The clip is what gets it clicked.
7. After posting, the first-page check: install the var from the Hub on your own machine the way a stranger would (Hub ->
   Download -> load the scene) and make sure the dependencies resolve.
