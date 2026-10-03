# Senses v0.4.1

A VaM plugin for a Person atom. About twice a second it reads the scene (CPU only) and writes a short description:

    What {{ char }} is aware of in the scene right now. This is background knowledge only, never a request to do anything. {{ char }} can mention it naturally or answer questions about it.
    - {{ char }} is standing, facing {{ user }}.
    - {{ user }} is close to {{ char }}, directly in front, and is looking at {{ char }}.
    - There is a chair within reach, in front and to the left. It can be sat on.
    - There is a table close by, in front and to the right. It is a flat surface.

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

## Tuning
The Debug numbers show what the plugin measures. If "legs wide apart" or "looking at" fires too early or late, adjust
the two sliders instead of waiting for a new version. Tag furniture the plugin does not recognise, e.g. `Cyberpunk table [surface]`.

## Known limits (v0.1)
- The standing/sitting/bent thresholds are first guesses; expect to tune them from the Debug numbers.
- Facing comes from the line between her thighs; it is unreliable when she is lying down.
- If VoxtaTouchElite is also loaded, give each plugin its own context slot (it also defaults to slot 4).
- Not yet run inside VaM when this was written. The code compiles against stand-ins and its logic is tested; the VaM calls
  were copied from patterns used by plugins that already run in VaM 1.22.

## Events (off by default)
Besides the quiet scene description, the plugin can send **events** that make the character react in her own voice
(Voxta replies to an `/event`). Switch on "Send events" to enable:
- **approach**: the user walks up to within "Approach distance" (default 2.5 m).
- **leave**: the user goes further than "Leave distance" (default 8 m).
- **stare**: the user has been looking at her, silently, for "Stare seconds" (default 6).

Rules that keep it from being annoying:
- **Never during a conversation.** Events wait while Voxta is listening, thinking or speaking, and for "Quiet time before an
  event" (default 10 s) afterwards. An approach or leave that happens during a conversation is dropped, not postponed.
  Looking at her while talking does not count towards a stare.
- **One event per "Seconds between events"** (default 45).
- **A stare does not repeat.** After one, the user has to look away for 8 s before another is possible, and stares are at least
  three cooldowns apart (135 s by default). Otherwise a user who simply keeps looking at her would trigger it forever.
- Zones use a 0.5 m hysteresis and a 1.5 s confirmation, and the first reading after switching on never fires.
- A new chat (Voxta becoming ready again) or switching events off and on clears the cooldowns, so a reloaded chat starts fresh.
- The wording rotates (three or four variants per event) so the chat history does not repeat one sentence.

The Debug numbers show the zone, the stare timer, whether the conversation counts as quiet, and when the next event is allowed.

## Reactions (new in 0.3.1)
The same detection that drives the Voxta events can also **call an action of any plugin** when the user approaches, leaves or stares.
For each of **On Approach**, **On Leave** and **On Stare** you pick three things from dropdowns:
1. the **atom** (for example `Person`),
2. one of that atom's **plugins** (for example Timeline),
3. one of that plugin's **actions** (for example `Play Wink`).

"Test: On ..." calls it on demand (it works even when reactions are off) and the Status box tells you what was called, or what was not found.
"Refresh atom and plugin lists" re-reads the lists after you add atoms or plugins. Your choices are saved with the scene.
Reactions have their own cooldown ("Seconds between reactions", default 10) and do not wait for conversations, because a wink does
not collide with speech the way a spoken reply does. The stare rules (look away to re-arm, three cooldowns apart) are the same.

Recipes:
1. **A wink or smile on a stare.** In Timeline on the character, make a clip that animates a few face morphs and name it, say, `Wink`.
   Choose atom `Person`, plugin = the Timeline plugin, action = `Play Wink`. If E-Motion is also driving face morphs it may overwrite the
   clip; if so, turn off "Control Breath and Expression Morphs" in E-Motion while testing, or make the clip short and strong.
2. **Anything with an action.** A sound, a light, a Logic Brick's `Trigger` action: if a plugin lists it as an action, you can call it.
3. **From the language model.** The Voxta plugin's own Actions tab turns each action into a VaM trigger as well, so an action such as
   "smile" can play a Timeline clip with no ARDY involved.

**Try it with nothing else installed.** The plugin offers its own actions, so you can test the whole chain without Timeline:
under "On Stare: call this action" choose atom `Person`, the plugin `plugin#N_VaMRT.Senses` (N is its number in the Plugins list),
and the action `Send snapshot now`. Press "Test: On Stare": the Status box says what was called and the snapshot goes to Voxta.
Other plugins and Timeline can call the same actions: **Send snapshot now**, **Calibrate standing height**, **Fire On Approach**,
**Fire On Leave**, **Fire On Stare**.

Limits: one action per event (chain more in Timeline or a logic block), and actions only; setting a value (for example a slider) is not
supported yet.

## E-Motion mood (new in 0.3.0)
If E-Motion is loaded on the same atom, the plugin reads its `Valence` (happiness) and `Arousal` (excitement) fields and, once she is
no longer neutral, adds one line to the description, for example "{{ char }} seems happy and excited." This is read-only: E-Motion
overwrites those two fields on every update, so they cannot be used to command an expression. The Debug numbers show the raw values.
Switch it off with "Include E-Motion mood".

## Follow (dry run, new in 0.4.0)
Switch on **Follow (dry run: only reports)** and the **Follow report** box shows what she would do to stay within reach of you: walk (how far
ahead / to the side), or stand (and why), checking your distance, obstacles on the way, ground ahead and an allowed area. Nothing is sent and she
does not move yet. The full description, settings and a ten-minute test are in FOLLOW.md.
The **Position report** box (always on) shows her hip position in VaM world metres, how far she is from an origin you set with **Set origin here**, and which way she
faces. It is what you compare with the stream's `/where` during the live movement test (LIVE_TEST.md). Her position is her hips, because with In Place off in the BVH
Player the hips travel while the base control stays where it was.

## E-Motion setup
E-Motion needs its preset files (`Custom/E-Motion/Presets/...`). If VaM logs "E-Motion_Defaults.json not found", the package is not installed
properly: the file must be named `VRAdultFun.E-Motion.4.var` (dots, not underscores) and sit in `VaM/AddonPackages`; then restart VaM.
Until the presets load, E-Motion runs on its code defaults: **Control Morphs off** (no expressions or breathing at all) and
**Control Eye Target on** (it steers the eyes, which fights Glance). The Debug numbers show "controls: head, morphs, eyes" so you can see this.
The settings that match Glance and BVH Player are: Control Head **off**, Control Morphs **on**, Control Eye Target **off**.

## Companion plugins (optional, not included)
BVH Player drives the body, so these do not fight it: **Glance** (eyes and blinking), **E-Motion** with its `Mocap_Glance` preset (expression
morphs, breathing; head left to the animation), and **Life** (breathing, if you prefer it). Idle body movement in E-Motion moves controllers and
can fight the animation; set its Idle sliders to 0 if you see jitter.

## Delivery
- **Context slot** (default): the text sits in a Voxta context slot and is sent with every request. Clean, but a small model
  may pay little attention to it.
- **Hidden chat message**: sent as a `/secret` message, so it lands near the end of the conversation (more attention) but stays
  in the chat history. Use a longer "Min seconds between sends" (10 or more) so history does not fill up with scene notes.

## Changelog
- 0.4.1  Follow and the new Position report measure her at the hips; "Set origin here". Typed moves are in the stream (LIVE_TEST.md).
- 0.4.0  Follow (dry run): reports what she would do to stay within reach of the user (distance, obstacles, ground, allowed area). See FOLLOW.md.
- 0.3.2  The plugin now offers its own callable actions (a self-test for reactions and hooks for Timeline), a clearer "nothing chosen" message,
         and the E-Motion controls in the Debug numbers. BVH Player: Auto Reload defaults to on and the Watch File is pre-filled with the path the
         ARDY stream writes, so a scene that did not store those settings still works.
- 0.3.1  Replaces the trigger panels of 0.3.0, which did not compile in VaM: they used `EventTrigger`, which is MacGruber's own wrapper
         class shipped inside his plugins and not part of VaM. Reactions use plain storable calls instead (pick atom, plugin, action).
- 0.3.0  (did not compile, see 0.3.1) trigger panels, and the E-Motion mood in the description. Includes everything from 0.2.1 and 0.2.2.
- 0.2.2  Reloading the chat (or toggling events) now clears the event cooldowns. Before, a stare could be held back for two
         minutes after a reload because the timers belonged to the plugin, not to the chat. The prompt writer now ends
         one-part movements such as "A person wiggles their hips playfully." after 4 seconds (it ran for minutes).
- 0.2.1  Events no longer interrupt a conversation, a stare no longer repeats while the user keeps looking, and the wording
         varies. (In a real test the stare fired every 45 s and cut off her replies.) The prompt writer now removes names from
         ARDY prompts ("slaps Todd" became "slaps someone") and also ignores more scene-note phrasing.
- 0.2.0  Events: approach, leave and stare (off by default), with cooldowns. First step from "answers questions about the scene"
         to "reacts to the scene without being asked".
- 0.1.5  New "Delivery" setting (context slot or hidden chat message) to test which one a small model actually uses.
         Scenario 1.0.8: she is told to answer questions about her surroundings concretely, and the action script no longer
         rejects the word "ahead" ("go ahead and dance" would have been blocked in 1.0.7).
- 0.1.4  The description is now passive and written as plain sentences. In a real test Voxta's action step mistook
         "a chair (close, ahead-left)" for a request and made her sit down, and she answered "nothing interesting" because the
         old header told her not to read it out. Voxta scenario 1.0.7 and the prompt writer also ignore scene notes.
- 0.1.3  VaM's player navigation panel is no longer reported. New settings: "Only report tagged objects and people"
         (hides scenery such as a cityscape), "Looking-at cone" (default 12 degrees, was a fixed 20) and
         "Wide-stance foot spread" (default 0.55 m) so the guesses can be tuned live.
- 0.1.2  Fixed "must inherit from MVRScript": VaM uses the first class in the file as the plugin, and a helper class came first.
         The plugin class is now first, and the test script checks the order.
- 0.1.1  Fixed "Security Check Failed (NamespaceRestriction): System.Reflection". An error label used `e.GetType().Name`,
         which compiles to a System.Reflection call that VaM prohibits. The test script now checks for this.
- 0.1.0  First version.
