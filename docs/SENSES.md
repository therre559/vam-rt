# Senses v0.1.2

A VaM plugin for a Person atom. About twice a second it reads the scene (CPU only) and writes a short description:

    Physical situation of {{ char }} (live background information, not something to read out):
    - {{ char }} is standing, facing {{ user }}.
    - {{ user }} is close to {{ char }}, directly in front, and is looking at {{ char }}.
    - Nearby: a chair (within reach, ahead-left, can be sat on); a table (close, ahead-right, a surface).

It shows this in its panel and can write it to a Voxta "Context (Slot N)" field. A new description is only accepted
after it has stayed the same for about a second, and it is only sent when it differs from the last one sent.
Turning auto-send off, removing the plugin, or changing the slot clears the slot again.

## Install
1. Copy `plugin/VaMRT/VaMRT_Senses.cs` to `<VaM>/Custom/Scripts/VaMRT/VaMRT_Senses.cs` (`tools/deploy.bat` does this).
2. In VaM select the Person atom, open its Plugins tab, Add Plugin, pick that file, then open the plugin's settings.

## First-run checklist (what you should see)
1. No red error. Left: title, toggles, a slot dropdown, three sliders, buttons. Right: Snapshot, Status, Debug numbers, Last error.
2. Within about 2 s the Snapshot shows the lines above. Move the camera around her: the user line changes distance and direction.
3. Press **Spawn test props**: three small cubes appear (front-left, front-right, behind). Within 2 s they show in "Nearby"
   as a chair, a table and a marker. There is no physics floor in a bare scene, so they may fall; delete them or add a floor.
4. Have her stand wide, bend over, or sit. The pose line should follow. If it is wrong, copy the **Debug numbers**; they show
   exactly what the plugin measured. **Calibrate** sets her standing hip height if she was not standing when the plugin loaded.
5. With Voxta connected, press **Send snapshot now**. Status says "Voxta: found ..." and the Voxta plugin's Context tab shows
   the text in the chosen slot. Only then switch on **Send to Voxta context**.

## Tags
Put tags in square brackets in an atom's name: `[sit]`, `[surface]`, `[look]`, `[ignore]`.
Whole words like chair, sofa, stool, bench, table, desk are tagged automatically (so "bedroom lamp" is not a bed).

## Known limits (v0.1)
- The standing/sitting/bent thresholds are first guesses; expect to tune them from the Debug numbers.
- Facing comes from the line between her thighs; it is unreliable when she is lying down.
- If VoxtaTouchElite is also loaded, give each plugin its own context slot (it also defaults to slot 4).
- Not yet run inside VaM when this was written. The code compiles against stand-ins and its logic is tested; the VaM calls
  were copied from patterns used by plugins that already run in VaM 1.22.

## Changelog
- 0.1.2  Fixed "must inherit from MVRScript": VaM uses the first class in the file as the plugin, and a helper class came first.
         The plugin class is now first, and the test script checks the order.
- 0.1.1  Fixed "Security Check Failed (NamespaceRestriction): System.Reflection". An error label used `e.GetType().Name`,
         which compiles to a System.Reflection call that VaM prohibits. The test script now checks for this.
- 0.1.0  First version.
