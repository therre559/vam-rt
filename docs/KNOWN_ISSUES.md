# Known issues and where help is wanted

- **Seated pose quality.** The sit is stopped at seat height, which is a mid-descent frame: she perches forward. The right fix is
  a root-height *constraint* on "sits in a chair" so the model settles her back (ARDY supports constraints; `constraint_probe.py`).
- **Lying down** is raised onto the bed by lifting the floor pose; alignment with the bed's long axis is approximate (`LIE_HALF`,
  `LIE_STAND` in `world_moves.py`). Furniture collision must be off while she sits or lies.
- **Plugin ids are slot numbers.** The Voxta script addresses the BVH Player and the Face plugin by `plugin#N_...`; add a plugin in
  front of them and the numbers change. A stable addressing scheme would be very welcome.
- **No lip-sync of its own.** Voxta's plugin (or SpeechBlend) does the mouth; Face owns everything else.
- **Pose wordings** come from a lab (`ardy_lab.py`, `verified_prompts.json`); many poses the model can do are not verified yet.
- **Gaze** looks at the player only; Senses knows where objects are, so looking at what she talks about is a small addition.
- **Latency** is ~1.3 s from request to visible motion (0.9 s chunks + player buffer). The 8-frame ARDY model halves it at some
  quality cost (`--model core8`).
- **E-Motion** conflicts with Face (both write morphs) and crashes on this stack; it is not used.
- **The character echoing event lines** as speech is a model behaviour; the narration pack makes it silent, not gone.

## Install
- `setup.bat` has not yet been run on a machine that never had ARDY. The 8-bit text encoder patch (`tools/patch_ardy_int8.py`)
  was written against nv-tlabs/ardy e706e27 and compile-checked; the header path is the tested one (19 Nov); if the stream fails while loading the encoder, run it with
  `--full-encoder` in STREAM_OPTS (NVIDIA's bf16 encoder: 15 GB VRAM and a Hugging Face token with Llama 3 access) and report it.
- ARDY is pinned to one commit. A newer ARDY may rename the loader internals the VaMRT scripts import (`ardy.model.loading`,
  `ardy.model.registry`); move the pin only after a test.
