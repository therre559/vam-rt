# Credits and licenses

This project stands on other people work. If you copy code from here, keep these credits.

## Included or derived
- **BVH Player** by **ElkVR** and **VRAdultFun** (CC BY 3.0, https://creativecommons.org/licenses/by/3.0/).
  plugin/legacy/BVHPlayer_autoreload.cs is a modified copy. The original header is kept and our changes are listed in it.

## Used but not included (users install these themselves)
- **ARDY** by **NVIDIA** (code: Apache License 2.0, Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES).
  Includes **LLM2Vec** (MIT, Copyright (c) 2024 McGill NLP). Model weights are not part of this repository;
  check the weights own license before any use beyond personal experiments.
- NVIDIA's ARDY **interactive demo** (Apache-2.0): the way we turn a root plan into the model's constraint tensors, and the idea of a
  "target velocity" as a list of integrated future positions, follow `scripts/interactive_demo/gen_constraints.py`. Our code is a
  small independent implementation.
- **Voxta** and the **Voxta VaM plugin** by **AcidBubbles** (CC BY-ND). We only talk to the plugin through its public
  fields; none of its code is copied here.
- **SmartWardrobe** by **Bplus** (optional integration for outfit presets).
- **E-Motion** by **VRAdultFun** (CC BY, the same author as the BVH Player): the Senses plugin reads its `Valence` and `Arousal`
  fields (read-only) when it is loaded on the same atom.
- **Glance** by **AcidBubbles** (CC BY-SA) and **Life** by **MacGruber** (CC BY-SA): recommended companions for eye contact,
  blinking and breathing next to the animation. We do not touch them; they only appear in the docs.
- **Timeline** by **AcidBubbles**: a good target for the Senses reactions (a Timeline clip can play a facial expression).
- **KoboldCpp**, **Chatterbox TTS**, **Whisper**, and **Virt-A-Mate** itself.

## Inspiration (ideas only, no code copied)
- **LogicBricks** and **IdlePoser** by **MacGruber**, **Scripter** by **AcidBubbles** (CC BY-ND), **Essentials** (CC BY-SA),
  **ColliderEditor** (CC BY-SA). LogicBricks and IdlePoser are marked "PC EA" in their package metadata (IdlePoser's own text says it became
  CC BY-SA after early access); until the author confirms, treat them as no-copy. The Voxta plugin's `TimelineIntegration` and `TriggerInvoker` were read to learn the plain storable calls that work in VaM
  (`GetStorableIDs`, `GetActionNames`, `CallAction`); our code is written fresh. MacGruber's `EventTrigger` is his own wrapper class
  (inside his Utils file, CC BY-SA) and is not used here.
- **VoxtaTouchElite** by **FutureStorm** (CC BY-SA), built on work by JayJayWon (VoxtaTouch), Milines, Dlesser,
  Dragontales, TBD, MacGruber and AcidBubbles. Its approach to touch, gaze, pose and clothing awareness shaped our design.

## Rule for contributors
Do not copy code from CC BY-ND or CC BY-SA packages into this repository without checking the license first.
Add every new third-party source to this file in the same commit.
