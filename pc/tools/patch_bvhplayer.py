"""patch_bvhplayer.py - BVH Player (VaM-RT build, v5.6): a big jump between two chunks is a hard cut, never a blend.

    python patch_bvhplayer.py "<VaM>\\Custom\\Scripts\\...\\BVHPlayer.cs"      (or BVHPlayer_autoreload.cs; the original is kept as .bak)

Why: when the ARDY stream is restarted (or /reset) its first chunk is back at ARDY's origin. With "Chain: ARDY World Coords" the
player maps that to the spot where the chain started, so if she had walked 17 m away in the previous session, the next chunk puts
every body controller 17 m from where her body is. The chunk blend then sweeps the controllers across the room in ~0.2 s, the
rigidbodies chase them at 80+ m/s and VaM logs "physics corruption ... invalid joint position / DAZBone Matrix hip" until she is
a tangle (the 31 Oct evening test). The player already has a teleport path for scrubbing the animation slider (discontinuity ->
EndRestore -> PauseSimulation for 5 frames): a jump of more than 1 m between the old clip's last hip position and the new clip's
first one now takes that path instead of the blend. Status line shows [v5.7].
"""
import shutil
import sys
from pathlib import Path

EDITS = [
    ("cut", "        if(uiChain.val && bvh != null && bvh.nFrames > 0)\n            ChainTranslation(bvh, nb, skip, uiChainWorld.val);\n        bvh = nb;\n        frame = skip;\n        if(seamless) {\n",
     "        if(uiChain.val && bvh != null && bvh.nFrames > 0)\n            ChainTranslation(bvh, nb, skip, uiChainWorld.val);\n"
     "        // A jump of more than a metre between the old clip's last hip position and the new clip's first (the stream was\n"
     "        // restarted or /reset: its next chunk is back at ARDY's origin) is never blended. Blending sweeps every controller\n"
     "        // across the room in a fraction of a second and the physics body explodes (\"physics corruption\" in the VaM log).\n"
     "        // It is treated like scrubbing the slider instead: a hard cut with the simulation paused for a few frames.\n"
     "        if(seamless && oldLast != null) {\n"
     "            float jump = HipJump(oldLast, nb.ReadFrame(skip));\n"
     "            if(jump > 1.0f) {\n"
     "                seamless = false;\n"
     "                discontinuity = true;\n"
     "                SuperController.LogMessage(string.Format(\"BVH Player: the next chunk starts {0:0.0} m away (stream restarted or reset?): hard cut, physics paused briefly\", jump));\n"
     "            }\n"
     "        }\n"
     "        bvh = nb;\n        frame = skip;\n        if(seamless) {\n"),
    ("helper", "    // If the new clip does not start exactly where the old one was heading, remember the mismatch\n",
     "    // Horizontal distance between the hip of pose a and the hip of pose b, as the player will place them (both clips share\n"
     "    // the chain's reference position after ChainTranslation, so the raw hip positions compare directly).\n"
     "    static float HipJump(BvhTransform[] a, BvhTransform[] b) {\n"
     "        Vector3 pa = Vector3.zero, pb = Vector3.zero;\n"
     "        bool fa = false, fb = false;\n"
     "        foreach(var t in a) { if(t.bone.hasPosition && t.bone.isHipBone) { pa = t.position - t.bone.posZero; fa = true; break; } }\n"
     "        foreach(var t in b) { if(t.bone.hasPosition && t.bone.isHipBone) { pb = t.position - t.bone.posZero; fb = true; break; } }\n"
     "        if(!fa || !fb)\n"
     "            return 0f;\n"
     "        Vector3 d = pb - pa;\n"
     "        d.y = 0f;\n"
     "        return d.magnitude;\n"
     "    }\n\n"
     "    // If the new clip does not start exactly where the old one was heading, remember the mismatch\n"),
    ("version", "        text = \"[v5.6] storable ID: \" + storeId + \" | \" + text;\n",
     "        text = \"[v5.7] storable ID: \" + storeId + \" | \" + text;\n"),
]


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    path = Path(sys.argv[1])
    raw = path.read_bytes()
    crlf = b"\r\n" in raw
    src = raw.decode("utf-8-sig").replace("\r\n", "\n")
    if "HipJump(" in src:
        raise SystemExit("already patched (v5.7).")
    for name, anchor, _ in EDITS:
        n = src.count(anchor)
        if n != 1:
            raise SystemExit(f"cannot patch: anchor '{name}' found {n} times (expected 1). Is this the VaM-RT build v5.6 of the player? Nothing changed.")
    for _, anchor, repl in EDITS:
        src = src.replace(anchor, repl, 1)
    shutil.copy2(path, str(path) + ".bak")
    path.write_bytes((src.replace("\n", "\r\n") if crlf else src).encode("utf-8"))
    print(f"patched {path} (original kept as {path.name}.bak). In VaM: reload the plugin (or the scene).")


if __name__ == "__main__":
    main()
