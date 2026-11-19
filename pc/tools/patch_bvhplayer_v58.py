"""patch_bvhplayer_v58.py - BVH Player (VaM-RT build v5.7): the root control follows her.

With In Place OFF the hip travels and every controller is placed relative to the atom; the atom's own "control" stays where the
scene left it. After a walk the control (and so the saved position, the atom's place for every plugin that reads it, and the
rotation gizmo) is metres away from the body. This patch re-bases once every half second: the control is moved to where her hips
are and the same offset is taken off every controller, so nothing on screen moves - the control simply catches up with her.
Toggle "Root control follows her" (on by default). Status line shows [v5.8]. Re-center keeps her where she is (the control is already with her).

    python patch_bvhplayer_v58.py "<VaM>\\Custom\\Scripts\\...\\BVHPlayer.cs"

Works on the v5.6 build or the v5.7 one (patch_bvhplayer.py applied); the original is kept as <file>.bak58.
"""
import re
import shutil
import sys
from pathlib import Path

EDITS = [
    ("fields", "    bool discontinuity = false;\n",
     "    bool discontinuity = false;\n"
     "    // v5.8: the root control follows her (re-based every half second, see RebaseRoot)\n"
     "    JSONStorableBool uiFollowRoot;\n"
     "    Vector3 rebase = Vector3.zero;\n"
     "    Vector3 rootRest = Vector3.zero;\n"
     "    bool rootRestSet = false;\n"
     "    float rebaseTimer = 0f;\n"),
    ("ui", "            CreateButton(\"Re-center\", true).button.onClick.AddListener(() => {\n                Recenter();\n            });\n",
     "            CreateButton(\"Re-center\", true).button.onClick.AddListener(() => {\n                Recenter();\n            });\n"
     "            uiFollowRoot = new JSONStorableBool(\"Root control follows her\", true);\n"
     "            RegisterBool(uiFollowRoot);\n"
     "            CreateToggle(uiFollowRoot);\n"),
    ("rest", "        tposeBoneOffsets = new Dictionary<string, Vector3>();\n        foreach(var item in bones)\n            tposeBoneOffsets[item.Key] = item.Value.localPosition;\n",
     "        tposeBoneOffsets = new Dictionary<string, Vector3>();\n        foreach(var item in bones)\n            tposeBoneOffsets[item.Key] = item.Value.localPosition;\n"
     "        if(bones.ContainsKey(\"hip\")) {\n"
     "            rootRest = bones[\"hip\"].position - containingAtom.transform.position;   // where the hip sits over the control at rest\n"
     "            rootRestSet = true;\n"
     "        }\n"
     "        rebase = Vector3.zero;\n"),
    ("place", "\t\t\t\t\tcontrollerMap[item.Key].transform.localPosition = bones[item.Value].position - pivotPos;\n"
              "\t\t\t\t\tcontrollerMap[item.Key].transform.localRotation = bones[item.Value].rotation;\n"
              "\t\t\t\t}\n\t\t\t\telse\n\t\t\t\t{\n"
              "\t\t\t\t\t// E-Motion owns head/neck ROTATION, but the position must still travel with the body, or the neck stretches when she walks\n"
              "\t\t\t\t\tcontrollerMap[item.Key].transform.localPosition = bones[item.Value].position - pivotPos;\n",
     "\t\t\t\t\tcontrollerMap[item.Key].transform.localPosition = bones[item.Value].position - pivotPos - rebase;\n"
     "\t\t\t\t\tcontrollerMap[item.Key].transform.localRotation = bones[item.Value].rotation;\n"
     "\t\t\t\t}\n\t\t\t\telse\n\t\t\t\t{\n"
     "\t\t\t\t\t// E-Motion owns head/neck ROTATION, but the position must still travel with the body, or the neck stretches when she walks\n"
     "\t\t\t\t\tcontrollerMap[item.Key].transform.localPosition = bones[item.Value].position - pivotPos - rebase;\n"),
    ("rebase", "            if(discontinuity)\n                EndRestore();\n",
     "            if(discontinuity)\n                EndRestore();\n"
     "            RebaseRoot(pivotPos);\n"),
    ("helper", "    void BeginRestore() {\n",
     "    // v5.8: move the root control to where her hips are and take the same offset off every controller, so nothing on screen\n"
     "    // moves. Horizontal only; the floor logic keeps the height. basecontrolpos moves with it (the stay-on-floor code puts the\n"
     "    // control back there every physics step).\n"
     "    void RebaseRoot(Vector3 pivotPos) {\n"
     "        if(uiFollowRoot == null || !uiFollowRoot.val || !rootRestSet || personController == null || !bones.ContainsKey(\"hip\"))\n"
     "            return;\n"
     "        rebaseTimer += Time.fixedDeltaTime;\n"
     "        if(rebaseTimer < 0.5f)\n"
     "            return;\n"
     "        rebaseTimer = 0f;\n"
     "        Vector3 hipLocal = bones[\"hip\"].position - pivotPos - rebase;      // where the hip controller is, in the control's frame\n"
     "        Vector3 d = hipLocal - rootRest;\n"
     "        d.y = 0f;\n"
     "        if(d.sqrMagnitude < 0.05f * 0.05f)\n"
     "            return;\n"
     "        Vector3 world = personController.transform.rotation * d;\n"
     "        personController.transform.position = personController.transform.position + world;\n"
     "        basecontrolpos = basecontrolpos + world;\n"
     "        rebase = rebase + d;\n"
     "        // the controllers were placed a moment ago without this offset: take it off now, in the same physics step, so the\n"
     "        // body never sees the control's jump (0.4 m after half a second of walking)\n"
     "        foreach(var item in cnameToBname) {\n"
     "            FreeControllerV3 c;\n"
     "            if(controllerMap.TryGetValue(item.Key, out c))\n"
     "                c.transform.localPosition = c.transform.localPosition - d;\n"
     "        }\n"
     "    }\n\n"
     "    void BeginRestore() {\n"),
    ("recenter", "                t.bone.posZero = z;\n            }\n        }\n    }\n",
     "                t.bone.posZero = z;\n            }\n        }\n"
     "        rebase = Vector3.zero;   // v5.8: the control has already followed her, so with the BVH origin moved to her she stays put\n"
     "    }\n"),
]
VERSION_RX = re.compile(r'\[v5\.[67]\] storable ID')


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    path = Path(sys.argv[1])
    raw = path.read_bytes()
    crlf = b"\r\n" in raw
    src = raw.decode("utf-8-sig").replace("\r\n", "\n")
    if "RebaseRoot(" in src:
        raise SystemExit("already patched (v5.8).")
    for name, anchor, _ in EDITS:
        n = src.count(anchor)
        if n != 1:
            raise SystemExit(f"cannot patch: anchor '{name}' found {n} times (expected 1). Is this the VaM-RT build of the player "
                             f"(BVHPlayer_autoreload.cs, v5.6 or v5.7)? Nothing changed.")
    if len(VERSION_RX.findall(src)) != 1:
        raise SystemExit("cannot patch: the '[v5.6]/[v5.7] storable ID' status line was not found. Nothing changed.")
    for _, anchor, repl in EDITS:
        src = src.replace(anchor, repl, 1)
    src = VERSION_RX.sub("[v5.8] storable ID", src)
    shutil.copy2(path, str(path) + ".bak58")
    path.write_bytes((src.replace("\n", "\r\n") if crlf else src).encode("utf-8"))
    print(f"patched {path} (original kept as {path.name}.bak58). In VaM: reload the plugin (or the scene); the Watch Status line says [v5.8].")


if __name__ == "__main__":
    main()
