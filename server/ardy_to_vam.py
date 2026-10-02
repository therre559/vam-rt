"""ardy_to_vam.py - prompt in, VaM-ready BVH out.

Does in one step what you were doing by hand:
  generate (ARDY)  ->  ardy2bvh --scale 100  ->  rename joints to VaM bone names  ->  save

Run from the ARDY folder with the `ardy` conda environment active:

  One clip:
    python scripts/ardy_to_vam.py "A person waves." --duration 2.5

  Interactive (model stays loaded, so every clip after the first is fast):
    python scripts/ardy_to_vam.py
    > A person waves. | 2.5
    > A person sits down. | 4
    > quit

By default it uses the INT8 text encoder (pass --full-encoder to skip that).
Output goes to --out-dir as <prompt>_<time>_vam.bvh, and a copy is also written as
latest_vam.bvh (a fixed name, handy for automation later).
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_CONVERTER = r"C:\ARDY2BVH\ardy2bvh-main\ardy2bvh.py"
DEFAULT_OUT_DIR = r"C:\ARDY2BVH\out"
INT8_REPO = "voxta/Llama-3-8B-LLM2Vec-ARDY-INT8"

# ARDY (Mixamo-style) joint name -> VaM bone name that BVH Player looks up.
# Spine3 has no VaM equivalent and is left unmapped (the plugin ignores it).
VAM_NAMES = {
    "Hips": "hip",
    "Spine": "abdomen",
    "Spine1": "abdomen2",
    "Spine2": "chest",
    "Neck": "neck",
    "Head": "head",
    "RightShoulder": "rCollar", "RightArm": "rShldr", "RightForeArm": "rForeArm",
    "RightHand": "rHand", "RightHandThumb1": "rThumb1",
    "LeftShoulder": "lCollar", "LeftArm": "lShldr", "LeftForeArm": "lForeArm",
    "LeftHand": "lHand", "LeftHandThumb1": "lThumb1",
    "RightUpLeg": "rThigh", "RightLeg": "rShin", "RightFoot": "rFoot", "RightToeBase": "rToe",
    "LeftUpLeg": "lThigh", "LeftLeg": "lShin", "LeftFoot": "lFoot", "LeftToeBase": "lToe",
}

_JOINT_RE = re.compile(r"^(\s*)(ROOT|JOINT)(\s+)(\S+)")


# --------------------------------------------------------------------------- BVH helpers
def rename_bvh_text(text):
    """Rename joints in a BVH's HIERARCHY section. Returns (new_text, mapped, skipped)."""
    mapped, skipped, out = [], [], []
    in_motion = False
    for line in text.splitlines(keepends=True):
        if line.strip() == "MOTION":
            in_motion = True
        m = None if in_motion else _JOINT_RE.match(line)
        if m:
            name = m.group(4)
            if name in VAM_NAMES:
                line = m.group(1) + m.group(2) + m.group(3) + VAM_NAMES[name] + line[m.end():]
                mapped.append(name)
            else:
                skipped.append(name)
        out.append(line)
    return "".join(out), mapped, skipped


def slugify(text, limit=40):
    s = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return (s[:limit].rstrip("_")) or "clip"


# --------------------------------------------------------------------------- ARDY wrapper
class ArdyGenerator:
    """Loads ARDY once; generate() can then be called as many times as you like."""

    def __init__(self, model_name=None, checkpoints_dir=None):
        import torch
        from ardy.model import DEFAULT_MODEL, load_model
        from ardy.model.loading import get_env_var
        from ardy.model.registry import resolve_model_name
        from ardy.skeleton import SOMASkeleton30

        self.torch = torch
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
        ckpt = checkpoints_dir or get_env_var("CHECKPOINTS_DIR")
        self.resolved = resolve_model_name(model_name or DEFAULT_MODEL, checkpoints_dir=ckpt)
        low = self.resolved.lower()
        if "g1" in low or "soma" in low:
            raise SystemExit(f"This script only supports the Core skeleton (got {self.resolved}).")
        self.model = load_model(self.resolved, device=self.device, checkpoints_dir=ckpt)
        if isinstance(self.model.skeleton, SOMASkeleton30):
            raise SystemExit("SOMA skeleton is not supported by ardy2bvh yet.")
        self.fps = self.model.motion_rep.fps
        print(f"Loaded model: {self.resolved} ({self.fps} fps)")

    def _default_history_frames(self):
        # Same budget as scripts/generate.py: history + horizon must fit the 10 s trained window.
        patch = self.model.num_frames_per_token
        max_window = (int(10 * self.fps) // patch) * patch
        return ((max_window - self.model.gen_horizon_len) // patch) * patch

    def generate(self, prompt, duration, seed=None, cfg_weight=(2.0, 2.0)):
        """Returns the motion output dict (numpy), same as scripts/generate.py produces."""
        from ardy.motion_rep.tools import length_to_mask
        from ardy.postprocess import post_process_motion
        from ardy.tools import seed_everything, to_numpy

        torch, model, device = self.torch, self.model, self.device
        text = prompt.strip()
        num_frames = int(duration * self.fps)
        steps = int(model.diffusion.num_base_steps)
        history = self._default_history_frames()

        if seed is not None:
            seed_everything(seed)

        lengths = torch.tensor([num_frames], device=device)
        pad_mask = length_to_mask(lengths)
        first_heading = torch.zeros(1, device=device)  # facing +Z

        with torch.no_grad():
            motion = model(
                [text],
                num_frames,
                num_denoising_steps=steps,
                pad_mask=pad_mask,
                first_heading_angle=first_heading,
                motion_mask=None,
                observed_motion=None,
                cfg_weight=tuple(cfg_weight),
                crop_history_length=history,
            )
            output = model.motion_rep.inverse(motion, is_normalized=True)

        corrected = post_process_motion(
            output["local_rot_mats"],
            output["root_positions"],
            output["foot_contacts"],
            model.skeleton,
            constraint_lst=None,
        )
        output.update(corrected)
        return to_numpy(output), num_frames


def save_npz(path, output, fps, text):
    """Single-sample npz, matching scripts/generate.py's layout."""
    import numpy as np

    n = int(output["posed_joints"].shape[0])
    arrays = {}
    for k, v in output.items():
        if hasattr(v, "shape") and len(v.shape) > 0 and v.shape[0] == n:
            v = v[0]
        arrays[k] = np.asarray(v)
    arrays["fps"] = np.asarray(fps)
    arrays["text"] = np.asarray(text)
    np.savez(path, **arrays)


# --------------------------------------------------------------------------- pipeline
def make_vam_bvh(gen, prompt, duration, args):
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    output, num_frames = gen.generate(prompt, duration, seed=args.seed)
    t_gen = time.time() - t0

    stem = f"{slugify(prompt)}_{time.strftime('%H%M%S')}"
    with tempfile.TemporaryDirectory() as tmp:
        npz = Path(tmp) / "clip.npz"
        save_npz(npz, output, gen.fps, prompt)

        # ardy2bvh writes clip.bvh next to the npz when -o is not given.
        cmd = [sys.executable, args.converter, str(npz), "--scale", str(args.scale)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        bvh = npz.with_suffix(".bvh")
        if res.returncode != 0 or not bvh.exists():
            print("ardy2bvh failed:\n", res.stdout, res.stderr)
            raise SystemExit(1)

        if args.keep_npz:
            npz_dir = out_dir / "npz"
            npz_dir.mkdir(exist_ok=True)
            shutil.copy(npz, npz_dir / f"{stem}.npz")

        with open(bvh, newline="") as f:
            text = f.read()

    text, mapped, skipped = rename_bvh_text(text)
    final = out_dir / f"{stem}_vam.bvh"
    with open(final, "w", newline="") as f:
        f.write(text)
    shutil.copy(final, out_dir / "latest_vam.bvh")

    print(f"  {num_frames} frames ({duration}s) generated in {t_gen:.1f}s")
    print(f"  renamed {len(mapped)} joints, left unmapped: {', '.join(skipped) or 'none'}")
    print(f"  wrote {final}")
    return final


def parse_line(line, default_duration):
    """'A person waves. | 2.5'  ->  (prompt, 2.5)"""
    if "|" in line:
        prompt, _, dur = line.rpartition("|")
        try:
            return prompt.strip(), float(dur)
        except ValueError:
            return line.strip(), default_duration
    return line.strip(), default_duration


def main():
    p = argparse.ArgumentParser(description="ARDY prompt -> VaM-ready BVH")
    p.add_argument("prompt", nargs="?", help="Motion prompt. Omit for interactive mode.")
    p.add_argument("--duration", type=float, default=2.5, help="Seconds (default 2.5)")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    p.add_argument("--converter", default=DEFAULT_CONVERTER, help="Path to ardy2bvh.py")
    p.add_argument("--scale", type=float, default=100, help="Meters -> cm for BVH Player")
    p.add_argument("--model", default=None)
    p.add_argument("--checkpoints_dir", default=None)
    p.add_argument("--full-encoder", action="store_true", help="Use the full-precision encoder")
    p.add_argument("--keep-npz", action="store_true", help="Also keep the raw .npz files")
    args = p.parse_args()

    if not Path(args.converter).exists():
        raise SystemExit(f"Can't find ardy2bvh.py at {args.converter} (use --converter).")

    if not args.full_encoder:
        os.environ.setdefault("ARDY_TEXT_ENCODER_INT8", INT8_REPO)

    gen = ArdyGenerator(args.model, args.checkpoints_dir)

    if args.prompt:
        make_vam_bvh(gen, args.prompt, args.duration, args)
        return

    print("Interactive mode. Type a prompt, optionally '| seconds'. 'quit' to exit.")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line.lower() in ("quit", "exit", "q"):
            break
        prompt, dur = parse_line(line, args.duration)
        try:
            make_vam_bvh(gen, prompt, dur, args)
        except SystemExit:
            pass
        except Exception as e:  # keep the loop (and the loaded model) alive
            print("  error:", e)


if __name__ == "__main__":
    main()
