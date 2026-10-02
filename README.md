# VaM-RT (working name)

Real-time, text-driven character motion for Virt-A-Mate, with the goal of NPCs that decide what to do instead of
playing fixed animations.

**Status: early prototype.** It works as a voice-driven puppet: Voxta turns what you say into an action request, a small
Python server turns that into a motion prompt for NVIDIA ARDY model, and a VaM plugin plays the generated BVH.
It is not yet autonomous. See docs/ARCHITECTURE.md for where it is going.

## Layout
- plugin/  the VaM side (C#). plugin/legacy/ holds the patched BVH Player we run today.
- server/  the generator side (Python): stream, prompt writer, lab, launchers.
- voxta/   the Voxta character card and scenario used for testing.
- docs/    design notes.
- tools/   helper scripts.

## Requirements (not included)
Virt-A-Mate, the Voxta server and its VaM plugin, NVIDIA ARDY with its model weights, a CUDA GPU, and an LLM endpoint
for the prompt writer (any OpenAI-compatible server, we use KoboldCpp).

See CREDITS.md for licenses and attribution.
