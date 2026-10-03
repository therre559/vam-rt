Python side. These scripts import the `ardy` package, so run them in the environment where ARDY is installed.
- `ardy_stream.py`      continuous generation into a BVH the plugin watches (v20: duration guard, see docs/DURATIONS.md)
- `motion_prompter.py`  turns requests into validated ARDY prompts (fast path + LLM); gives every movement a lifetime
- `ardy_lab.py`         measures which wordings work and writes verified_prompts.json
- `ardy_to_vam.py`      one-shot generation + BVH joint renaming (also used by the stream)
- `Start_ARDY.bat`, `Start_Lab.bat`   launchers (edit the paths at the top for your machine)
- `tests/test_stream_guard.py`        tests for the duration guard (no GPU needed): `python tests/test_stream_guard.py`
Also: `python motion_prompter.py --selftest`.
verified_prompts.json is your own lab results; copy it here to keep it under version control.

Locomotion experiments (see docs/LOCOMOTION.md):
- `ardy_control.py`        plans for root-path constraints (velocity, go to a point and stop)
- `constraint_probe.py`    measures whether the Core model follows those plans: `python scripts/constraint_probe.py`
- `tests/test_control.py`, `tests/test_probe_logic.py`   tests for the above (no GPU needed)
- `gait_metrics.py`       facing versus travel, turning and foot skate (used by the probe); `tests/test_gait_metrics.py`
- `ardy_control.py` also has `steer_plan`: a heading-aware walk to a point (limited turn rate, slow while misaligned, brakes to stop)
- `constraint_probe.py` flags: `--postprocess` and `--pp-constraints` try ARDY's post-processing (see docs/LOCOMOTION.md)
