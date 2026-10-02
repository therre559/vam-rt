Python side. These scripts import the ardy package, so run them in the environment where ARDY is installed.
- ardy_stream.py      continuous generation into a BVH the plugin watches
- motion_prompter.py  turns requests into validated ARDY prompts (fast path + LLM)
- ardy_lab.py         measures which wordings work and writes verified_prompts.json
- ardy_to_vam.py      one-shot generation + BVH joint renaming (also used by the stream)
- Start_ARDY.bat, Start_Lab.bat   launchers (edit the paths at the top for your machine)
verified_prompts.json is your own lab results; copy it here to keep it under version control.
