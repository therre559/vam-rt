# VaMRT — a real-time, AI-driven NPC for Virt-a-Mate

Repo: https://github.com/therre559/vam-rt · Hub package: `VaMRT.NPC` by Gingersnap

**Prototype.** She listens (Voxta), decides what to do (an LLM), and *moves* — not from canned animations but from a motion model
generating her body live, 20 frames a second, from the words of the conversation. She knows what is in the room, walks to the
chair you point at and sits in it the right way round, holds a pose when asked, lies down on the bed, looks at you, and her face
follows her mood. It is rough in places (see KNOWN_ISSUES.md). It is published so people who know VaM's internals better than we
do can take it further.

## What is in the box
```
Voxta (chat, voice, mood script) ──► motion prompter ──► ARDY stream ──► BVH ──► BVH Player (VaM)
       ▲          │ mood / face cues                         ▲ world file (what is where)
       │          ▼                                          │
  VoxtaTouchElite  VaMRT_Face (expression, gaze)        VaMRT_Senses (room, objects, you)
```
- **NVIDIA ARDY** — the motion model. Text in, skeleton out, real time ([paper](https://research.nvidia.com/labs/sil/projects/ardy/), [code](https://github.com/nv-tlabs/ardy), NVIDIA Open Model Agreement).
- **ardy2bvh** ([iremoztrk/ardy2bvh](https://github.com/iremoztrk/ardy2bvh), Apache-2.0) — ARDY's `.npz` to BVH; and the Voxta team's [8-bit text encoder](https://huggingface.co/voxta/Llama-3-8B-LLM2Vec-ARDY-INT8) (8 GB instead of 15, no gated repo).
- **ARDY stream** (`pc/scripts/ardy_stream.py`) — runs ARDY as a receding-horizon stream, 0.9 s chunks, and writes BVH VaM can play. Freeze-holds poses ("bend over and hold it"), walks her to points in VaM coordinates with a learned frame link, turns before walking, keeps her on the floor, lifts her onto a bed.
- **Motion prompter** (`motion_prompter.py` + `world_moves.py`, `mood_style.py`, `idle_life.py`) — turns Voxta's action requests and her own *stage directions* into motion prompts; plans walks round furniture; idle life between requests.
- **BVH Player (VaMRT build)** — ElkVR/VRAdultFun's player with auto-reload of a stream, chunk blending, in-place / world travel, a root control that follows her, a bounded stay-on-floor.
- **VaMRT_Senses** — tells Voxta (and the stream) what is in the room: tagged objects (`[sit]`, `[lie]`), where you are, where she is.
- **VaMRT_Face** — her resting expression from six mood axes, passing expressions from her own words, eye contact and head turns.
- **Voxta scenario script** — the mood model (warmth, irritation, energy, comfort, hurt, arousal), action inference, voice-style tags, narration parsing.

## Requirements
- Windows, VaM 1.22, Voxta (with the VaM plugin), an NVIDIA GPU: **24 GB** on one PC, or 8 GB + a second PC/GPU with 10 GB for the text encoder.
- An LLM endpoint for the prompter (OpenRouter key, or a local KoboldCpp / LM Studio). Voxta brings its own LLM and TTS.
- Miniconda and Git. No compiler, no Hugging Face account.

## Install
See [docs/INSTALL.md](docs/INSTALL.md). Short version: `pc\setup.bat` → install `VaMRT.NPC.1.var` → import the Voxta scenario →
load the demo scene → `pc\Start_VaMRT.bat`.

## Credits and licences
Scripts and plugins in this repo: MIT (see LICENSE). BVH Player: based on ElkVR / VRAdultFun 1.1.3, CC BY. ARDY: NVIDIA.
Expressions in the demo: AshAuryn, ascorad (VaM Hub). Built with a lot of help from Claude.
