[B]VaMRT - a real-time, AI-driven NPC for VaM (NVIDIA ARDY + Voxta). Prototype.[/B]

She listens (Voxta), decides what to do (an LLM), and moves - not from canned animations but from a motion model that generates
her body live, 0.9 s at a time: "come here" and she walks over, "sit in that chair" and she walks round it, turns and sits,
"bend over and hold it" and she holds it. Her face follows her mood from the conversation; her eyes find you.

[B]What is in the var[/B]
- BVH Player (VaMRT build) - ElkVR/VRAdultFun's player with streaming reload, chunk blending, world travel, a root control that
  follows her and a bounded stay-on-floor.
- VaMRT_Senses - tells the AI what is in the room (tag furniture [sit] / [lie] in the atom name), where you are, where she is.
- VaMRT_Face - resting expression from six mood axes, passing expressions from her own stage directions, eye contact, head turns.
  No morph mapping to do: it finds the expression morphs the character has.
- A demo scene with everything wired, a Voxta scenario (mood model + action inference), a VoxtaTouchElite message pack.

[B]What is NOT in the var (the PC side)[/B]
The motion model runs outside VaM: NVIDIA ARDY (free weights) plus the VaMRT stream and prompter scripts. One setup.bat installs
it: [URL]https://github.com/therre559/vam-rt[/URL]. Needs an NVIDIA GPU - 24 GB on one PC, or ~6 GB on the VaM PC plus a second
PC with 10 GB for the text encoder - Miniconda, Git, Voxta, and an OpenRouter key (or a local LLM) for the prompter.

[B]Honest state of things[/B]
This is one person's working rig, cleaned up so others can run it and, I hope, improve it. Walking, sitting on a chair, holding
poses, mood-driven expression and gaze work; lying on a bed is rough; seated pose quality depends on the chair; the install has
only been run on the machine it was built on. KNOWN_ISSUES.md in the repo lists where help is wanted. If this interests people
who write real VaM plugins, that is exactly the point of posting it.

[B]Credits[/B]
ElkVR / VRAdultFun (BVH Player 1.1.3, CC BY), NVIDIA (ARDY, Apache-2.0 code / Open Model weights), iremoztrk (ardy2bvh),
AcidBubbles (Voxta, Timeline), FutureStorm (VoxtaTouchElite), AshAuryn and ascorad (expressions), the Voxta team (the 8-bit
text encoder).
