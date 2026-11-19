"""patch_bvhplayer_v59.py - BVH Player (VaM-RT build v5.8): "Attempt To Stay On Floor" can no longer lower her without limit.

The floor logic reads the PHYSICAL joints (followWhenOff) and lowers the root control while the lowest one is above the floor.
Seated on a chair with collisions on, the cushion holds her body up, so her feet never reach the floor, so the control is lowered
again every physics step, so she is pushed deeper into the chair ... until the physics gives up (7 Nov). Now the control may go at
most "Floor: max lowering (m)" below Height of Floor (default 0.08) - enough for a normal stand, never a runaway. Status [v5.9].

    python patch_bvhplayer_v59.py BVHPlayer_autoreload.cs        (run from Custom\\Scripts; needs v5.8 = patch_bvhplayer_v58.py applied)
"""
import re
import shutil
import sys
from pathlib import Path

EDITS = [
    ("field", "    JSONStorableBool uiFollowRoot;\n",
     "    JSONStorableBool uiFollowRoot;\n"
     "    JSONStorableFloat uiFloorMaxDown;   // v5.9: how far below Height of Floor the stay-on-floor logic may push the control\n"),
    ("register", "\t\tuipostheightoffset = new JSONStorableFloat(\"Post Height Offset\", 0.0f, -1.0f, 1.0f, true, true);\n\t\tRegisterFloat(uipostheightoffset);\n",
     "\t\tuipostheightoffset = new JSONStorableFloat(\"Post Height Offset\", 0.0f, -1.0f, 1.0f, true, true);\n\t\tRegisterFloat(uipostheightoffset);\n"
     "\t\tuiFloorMaxDown = new JSONStorableFloat(\"Floor: max lowering (m)\", 0.08f, 0.0f, 0.5f, true, true);\n\t\tRegisterFloat(uiFloorMaxDown);\n"),
    ("ui_create", "\t\tCreateSlider(uipostheightoffset, false);\n", "\t\tCreateSlider(uipostheightoffset, false);\n\t\tCreateSlider(uiFloorMaxDown, false);\n"),
    ("ui_remove", "\t\tRemoveSlider(uipostheightoffset);\n", "\t\tRemoveSlider(uipostheightoffset);\n\t\tRemoveSlider(uiFloorMaxDown);\n"),
    ("clamp", "\t\t\t\t\ttempvector = personController.transform.position;\n\t\t\t\t\tif (tempvector.y > uifloorheight.val)\n\t\t\t\t\t{\n"
              "\t\t\t\t\t\ttempvector.y = uifloorheight.val;\n\t\t\t\t\t\tpersonController.transform.position = tempvector;\n\t\t\t\t\t}\n",
     "\t\t\t\t\ttempvector = personController.transform.position;\n\t\t\t\t\tif (tempvector.y > uifloorheight.val)\n\t\t\t\t\t{\n"
     "\t\t\t\t\t\ttempvector.y = uifloorheight.val;\n\t\t\t\t\t\tpersonController.transform.position = tempvector;\n\t\t\t\t\t}\n"
     "\t\t\t\t\tif (uiFloorMaxDown != null && tempvector.y < uifloorheight.val - uiFloorMaxDown.val)\n\t\t\t\t\t{\n"
     "\t\t\t\t\t\t// v5.9: a body held up by furniture (seated, collisions on) never gets its feet down; without this bound the control\n"
     "\t\t\t\t\t\t// was lowered every step until the physics broke\n"
     "\t\t\t\t\t\ttempvector.y = uifloorheight.val - uiFloorMaxDown.val;\n\t\t\t\t\t\tpersonController.transform.position = tempvector;\n\t\t\t\t\t}\n"),
]
VERSION_RX = re.compile(r"\[v5\.8\] storable ID")


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    path = Path(sys.argv[1])
    raw = path.read_bytes()
    crlf = b"\r\n" in raw
    src = raw.decode("utf-8-sig").replace("\r\n", "\n")
    if "uiFloorMaxDown" in src:
        raise SystemExit("already patched (v5.9).")
    if "RebaseRoot(" not in src:
        raise SystemExit("this file is not v5.8 yet: run patch_bvhplayer_v58.py first. Nothing changed.")
    for name, anchor, _ in EDITS:
        n = src.count(anchor)
        if n != 1:
            raise SystemExit(f"cannot patch: anchor '{name}' found {n} times (expected 1). Nothing changed.")
    if len(VERSION_RX.findall(src)) != 1:
        raise SystemExit("cannot patch: the '[v5.8] storable ID' status line was not found. Nothing changed.")
    for _, anchor, repl in EDITS:
        src = src.replace(anchor, repl, 1)
    src = VERSION_RX.sub("[v5.9] storable ID", src)
    shutil.copy2(path, str(path) + ".bak59")
    path.write_bytes((src.replace("\n", "\r\n") if crlf else src).encode("utf-8"))
    print(f"patched {path} (original kept as {path.name}.bak59). Reload the plugin on Ava; the Watch Status line says [v5.9]. "
          f"The new slider is under Feature Controls: 'Floor: max lowering (m)'.")


if __name__ == "__main__":
    main()
