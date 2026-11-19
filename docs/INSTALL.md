# Install

## 0. Before you start
- VaM 1.22 with **Voxta** working (the Voxta VaM plugin talks to a character; test that first).
- **VoxtaTouchElite** (FutureStorm) from the Hub — optional but the demo scene references it.
- Miniconda (default location) and Git for Windows. No Visual Studio, no CMake, no Hugging Face account: the setup skips ARDY's
  optional C++ extension and uses the Voxta team's 8-bit text encoder (not gated) instead of the gated Meta Llama one.
- An NVIDIA card: 24 GB runs everything on one PC (ARDY ~6 GB + the encoder ~8.5 GB + VaM); with less, run the encoder on a second
  PC that has 10 GB or more (`Start_Encoder.bat`), and the VaM PC needs ~6 GB on top of VaM.
- An **OpenRouter key** (or any OpenAI-compatible local server) for the motion prompter's small translation calls.

## 1. PC side
1. Download or clone this repo somewhere short, e.g. `C:\VaMRT`.
2. Run `pc\setup.bat`. It clones ARDY (pinned to the commit VaMRT was built against) and the `ardy2bvh` converter, builds the `ardy`
   conda environment (PyTorch CUDA 12.6 build, ARDY without its C++ extension, bitsandbytes), applies the small 8-bit-encoder patch
   (`tools\patch_ardy_int8.py`), copies the scripts, and asks for your VaM folder and key. It writes `pc\config.bat` — your settings
   live there (never share it; it holds your key). Run it again any time; it skips what is already done.
3. Single PC (24 GB): leave `TEXT_ENCODER_URL` empty. Two PCs: copy the repo to the second one, run `setup.bat` there too, run
   `Start_Encoder.bat` there, and put `http://<its IP>:9550` into `TEXT_ENCODER_URL` on the VaM PC.
4. `pc\Start_VaMRT.bat`. Two windows open; the stream is ready when it prints *Type a prompt to change what the character does*.
   First run downloads the models (ARDY ~1 GB, the encoder ~8.5 GB) into the Hugging Face cache.

## 2. VaM side
1. Put `VaMRT.NPC.1.var` in `AddonPackages`.
2. Load `VaMRT/VaMRT Demo.json`. It has a stock female, a chair and a bed (plain cubes tagged `[sit]` and `[lie]` — replace them
   with any furniture you like, keep the tags in the atom names), and the plugins wired: Voxta, BVH Player (VaMRT), Senses, Face, VTE.
3. Voxta plugin on the Person: pick your character / scenario as you normally do.
4. BVH Player panel: Watch Status should say `[v5.9]` and *Clips loaded* should count up once the stream runs.
5. Apply whatever look you want to the Person (Appearance Preset). The Face plugin's Status box lists any expression morphs the
   character lacks; the demo expects AshAuryn's 2022 pack 2 and asco's expressions from the Hub.

## 3. Voxta side
1. Import `voxta/scenario mood v43.json` as a scenario (or paste the `mood` script into your own scenario's Scripts).
2. In the script, near the top: `facePlugin: 'plugin#3_VaMRT.VaMRT_Face'` and `bvhPlugin: 'plugin#1_ElkVR.BVHPlayer'` — these are the
   ids in the demo scene. If you add or remove plugins on the Person the numbers shift; the BVH Player's *Plugin IDs* box shows the
   current ones.
3. If VaM logs `OnReplyChunk: chunk has audioUrl but skipped playback (no narrator AudioSource)`: the scenario's *Narrator*
   has a voice, so Voxta synthesises narration that VaM has nowhere to play. Harmless, but wasteful on a paid TTS: in the
   scenario's Characters list set the Narrator's voice to none (narration in this setup is meant to be silent anyway).
4. VTE: Messages tab → load `voxta/VTE message pack - Narration.json` (events arrive as `*narration*`, so an echoed event is not
   spoken). The demo scene already carries these templates, so this is only needed for your own scenes.

## 4. First test
What a good run looks like in the prompter window (19 Nov, from voice): `sit down in that chair` → walks round to the front of
the chair via a staging point, turns, sits, `hold: her hips are down at the chair (0.57 m)`; `come here` from the chair →
`stands up first, then walks up to you`, a second leg if you were farther than one move; `bend over and hold that position` →
held until the next request.
Say: *"come here"*, *"sit down in that chair"*, *"bend over and hold that position"*, *"lie on the bed"*. Watch the prompter
window: `(move: walks round to the front of the Chair, up to it, turns her back to it, then sits)`. Press the Face plugin's test
buttons to see the expression layer without Voxta.
