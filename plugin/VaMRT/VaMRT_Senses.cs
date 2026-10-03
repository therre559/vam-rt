// =============================================================================
// VaM-RT Senses  v0.4.1
// =============================================================================
// Part of the VaM-RT project: https://github.com/therre559/vam-rt
// License: to be decided before the first public release (see the repository).
//
// What it does
//   Load it on a Person atom. Several times per second it looks at the scene
//   (CPU only, no GPU model) and builds a SHORT text description of:
//     - her own pose (from her body controllers) and whether her legs are wide apart
//     - where the user is, whether she faces the user, whether the user looks at her
//     - the nearest atoms around her, with distance and direction
//   The text is shown in this plugin's panel and, if you switch it on, written to a
//   Voxta "Context (Slot N)" field so the LLM knows about her surroundings.
//   It only updates the slot when the description really changes.
//   It can also send events to Voxta (approach, leave, stare), run "reactions" (call an action of any
//   plugin when the user approaches, leaves or stares, e.g. play a Timeline clip), and read the mood
//   from the E-Motion plugin when it is loaded on the same atom.
//   Follow (dry run): checks the distance to the user, obstacles, ground and an allowed area, and REPORTS what she would
//   do to stay within reach. Nothing is sent and she does not move yet. Her position is measured at her HIPS (with In Place
//   off in the BVH Player the hips travel and the base control stays behind), and a position report shows how far she has moved.
//
// Tagging atoms (optional): put tags in square brackets in the atom's name, e.g.
//   "Armchair [sit]"   can be sat on        "Desk [surface]"  a surface
//   "Window [look]"    worth looking at     "Prop [ignore]"   never reported
//   Names containing chair/stool/sofa/couch/bench/seat/bed or table/desk/counter/shelf are tagged automatically.
//
// Credits: see CREDITS.md in the repository. The way a Voxta plugin is located
// (plugin manager on each atom, "State", "AudioAtom", "Context (Slot N)") follows the
// public behaviour of AcidBubbles' Voxta plugin; no code from it is included.
// =============================================================================

using System;
using System.Collections;
using System.Collections.Generic;
using System.Text;
using System.Text.RegularExpressions;
using UnityEngine;

namespace VaMRT
{
    // -------------------------------------------------------------------------
    // The VaM plugin (thin glue around SensesLogic)
    // IMPORTANT: VaM uses the FIRST class in the file as the plugin and refuses it unless it inherits MVRScript
    // ("must inherit from MVRScript"). Keep the plugin class first and put helper classes after it.
    // -------------------------------------------------------------------------
    public class Senses : MVRScript
    {
        private const string VERSION = "0.4.1";
        private const string DeliverySlot = "Context slot";
        private const string DeliverySecret = "Hidden chat message";

        // settings (saved with the scene)
        private JSONStorableBool _enabled, _sendToVoxta, _onlyTagged, _sendEvents;
        private JSONStorableStringChooser _slot, _delivery;
        private JSONStorableFloat _radius, _maxObjects, _interval, _gazeCone, _wideSpread;
        private JSONStorableFloat _approach, _leave, _stare, _eventCooldown, _quietSeconds;
        private float _lastBusyTime = -100f;
        private bool _voxtaWasReady;
        private readonly Presence _presence = new Presence();
        // reactions for scene creators (call a plugin action), and the optional E-Motion mood
        private const string NoneChoice = "(none)";
        private class Reaction
        {
            public string Key, Title;
            public JSONStorableStringChooser Atom, Receiver, Action;
        }
        private readonly List<Reaction> _reactions = new List<Reaction>();
        private JSONStorableBool _fireTriggers, _useEMotion;
        private JSONStorableFloat _triggerCooldown;
        private readonly Presence _presenceTrig = new Presence();
        private string _lastTriggerText = "none yet";
        private MVRScript _emotion;
        // follow (dry run)
        private JSONStorableBool _followOn, _followGround;
        private JSONStorableFloat _followMin, _followMax, _followPref, _followSpeed, _followArea;
        private JSONStorableString _followText, _odoText;
        private float _anchorX, _anchorZ;
        private bool _hasAnchor;
        private float _odoX, _odoZ;       // the odometer's origin: where she stood when it was zeroed
        private bool _hasOdo;
        private float _emotionCheckTime = -100f;
        private string _lastEventText = "none yet";
        // read-only displays
        private JSONStorableString _snapshotText, _statusText, _debugText, _errorText;

        // body controllers
        private FreeControllerV3 _hip, _chest, _head, _lThigh, _rThigh, _lFoot, _rFoot;
        private bool _resolved;
        private float _standHip = 0.9f;

        // state
        private bool _ready;
        private float _sampleTimer;
        private float _lastSendTime = -100f;
        private float _voxtaCheckTime = -100f;
        private string _candidateText = "";
        private float _candidateSince;
        private string _lastText = "";
        private string _lastSentText = "";
        private string _lastWrittenSlot = "";
        private MVRScript _voxta;
        private string _lastErrorShown = "";
        private bool _spawning;

        private static readonly string[] IgnoredTypeParts = new string[] { "CoreControl", "Light", "Camera", "Audio", "PluginManager", "SessionPlugin", "NavigationPanel" };

        private class PropSpec
        {
            public string Uid; public float Distance; public float Angle; public float Height;
            public PropSpec(string uid, float distance, float angle, float height) { Uid = uid; Distance = distance; Angle = angle; Height = height; }
        }
        private static readonly PropSpec[] TestProps = new PropSpec[]
        {
            new PropSpec("VaMRT Chair [sit]", 1.0f, -40f, 0.15f),
            new PropSpec("VaMRT Table [surface]", 1.6f, 55f, 0.15f),
            new PropSpec("VaMRT Marker [look]", 2.5f, 170f, 0.15f)
        };

        // ---------------------------------------------------------------- lifecycle

        public override void Init()
        {
            try
            {
                if (containingAtom == null || containingAtom.type != "Person")
                {
                    SuperController.LogError("VaM-RT Senses: load this plugin on a Person atom.");
                    return;
                }

                _enabled = new JSONStorableBool("Enabled", true);
                RegisterBool(_enabled);
                _sendToVoxta = new JSONStorableBool("Send to Voxta context", false);
                RegisterBool(_sendToVoxta);
                _slot = new JSONStorableStringChooser("Context slot", new List<string> { "1", "2", "3", "4" }, "4", "Context slot");
                RegisterStringChooser(_slot);
                _delivery = new JSONStorableStringChooser("Delivery", new List<string> { DeliverySlot, DeliverySecret }, DeliverySlot, "Delivery");
                RegisterStringChooser(_delivery);
                _radius = new JSONStorableFloat("Radius (m)", 6f, 1f, 20f);
                RegisterFloat(_radius);
                _maxObjects = new JSONStorableFloat("Max objects reported", 6f, 1f, 12f);
                RegisterFloat(_maxObjects);
                _interval = new JSONStorableFloat("Min seconds between sends", 3f, 1f, 30f);
                RegisterFloat(_interval);
                _onlyTagged = new JSONStorableBool("Only report tagged objects and people", false);
                RegisterBool(_onlyTagged);
                _gazeCone = new JSONStorableFloat("Looking-at cone (degrees)", 12f, 3f, 45f);
                RegisterFloat(_gazeCone);
                _wideSpread = new JSONStorableFloat("Wide-stance foot spread (m)", 0.55f, 0.3f, 1.2f);
                RegisterFloat(_wideSpread);
                _sendEvents = new JSONStorableBool("Send events (approach, leave, stare)", false);
                RegisterBool(_sendEvents);
                _approach = new JSONStorableFloat("Approach distance (m)", 2.5f, 1f, 6f);
                RegisterFloat(_approach);
                _leave = new JSONStorableFloat("Leave distance (m)", 8f, 3f, 20f);
                RegisterFloat(_leave);
                _stare = new JSONStorableFloat("Stare seconds", 6f, 2f, 30f);
                RegisterFloat(_stare);
                _eventCooldown = new JSONStorableFloat("Seconds between events", 45f, 10f, 300f);
                RegisterFloat(_eventCooldown);
                _quietSeconds = new JSONStorableFloat("Quiet time before an event (s)", 10f, 3f, 60f);
                RegisterFloat(_quietSeconds);

                _fireTriggers = new JSONStorableBool("Run reactions (approach, leave, stare)", true);
                RegisterBool(_fireTriggers);
                _triggerCooldown = new JSONStorableFloat("Seconds between reactions", 10f, 2f, 120f);
                RegisterFloat(_triggerCooldown);
                _useEMotion = new JSONStorableBool("Include E-Motion mood", true);
                RegisterBool(_useEMotion);

                _followOn = new JSONStorableBool("Follow (dry run: only reports)", false);
                RegisterBool(_followOn);
                _followOn.setCallbackFunction += (bool v) => { if (!v) _hasAnchor = false; };
                _followMax = new JSONStorableFloat("Follow: start walking when farther than (m)", 2.5f, 1f, 8f);
                RegisterFloat(_followMax);
                _followMin = new JSONStorableFloat("Follow: stay put when closer than (m)", 0.8f, 0.3f, 3f);
                RegisterFloat(_followMin);
                _followPref = new JSONStorableFloat("Follow: walk to a point this far from you (m)", 1.8f, 0.5f, 4f);
                RegisterFloat(_followPref);
                _followSpeed = new JSONStorableFloat("Follow: walking speed (m/s)", 1.2f, 0.5f, 1.6f);
                RegisterFloat(_followSpeed);
                _followArea = new JSONStorableFloat("Follow: allowed area radius (m)", 6f, 1f, 30f);
                RegisterFloat(_followArea);
                _followGround = new JSONStorableBool("Follow: require ground ahead", true);
                RegisterBool(_followGround);
                _followText = new JSONStorableString("Follow report", "Follow is off.");
                _odoText = new JSONStorableString("Position report", "(waiting for the first reading)");   // not saved: it is a live readout

                _snapshotText = new JSONStorableString("Snapshot", "(waiting for the first reading)");
                _statusText = new JSONStorableString("Status", "");
                _debugText = new JSONStorableString("Debug numbers", "");
                _errorText = new JSONStorableString("Last error", "none");

                _enabled.setCallbackFunction += (bool v) => { if (!v) ClearSlot(); };
                _sendToVoxta.setCallbackFunction += (bool v) => { if (!v) ClearSlot(); else _lastSentText = ""; };
                _slot.setCallbackFunction += (string s) => { ClearSlot(); };
                _delivery.setCallbackFunction += (string s) => { ClearSlot(); };
                _sendEvents.setCallbackFunction += (bool v) => { _presence.ResetAll(); };

                // actions other plugins (and our own reactions) can call
                RegisterAction(new JSONStorableAction("Send snapshot now", ForceSend));
                RegisterAction(new JSONStorableAction("Calibrate standing height", Calibrate));
                RegisterAction(new JSONStorableAction("Start follow (dry run)", delegate { _followOn.val = true; }));
                RegisterAction(new JSONStorableAction("Stop follow (dry run)", delegate { _followOn.val = false; }));
                RegisterAction(new JSONStorableAction("Fire On Approach", delegate { FireTrigger("approach"); }));
                RegisterAction(new JSONStorableAction("Fire On Leave", delegate { FireTrigger("leave"); }));
                RegisterAction(new JSONStorableAction("Fire On Stare", delegate { FireTrigger("stare"); }));

                // reactions: for each event pick an atom, one of its plugins and one of that plugin's actions
                AddReaction("approach", "On Approach");
                AddReaction("leave", "On Leave");
                AddReaction("stare", "On Stare");

                BuildUI();
                _ready = true;
            }
            catch (Exception e)
            {
                SuperController.LogError("VaM-RT Senses init failed: " + e.Message);
            }
        }

        public void OnDestroy()
        {
            try { ClearSlot(); } catch (Exception) { }
        }

        public void Update()
        {
            if (!_ready || !_enabled.val) return;
            _sampleTimer -= Time.deltaTime;
            if (_sampleTimer > 0f) return;
            _sampleTimer = 0.5f;
            try
            {
                Sample();
            }
            catch (Exception e)
            {
                ShowError("sample", e);
            }
        }

        // ---------------------------------------------------------------- UI

        private void BuildUI()
        {
            JSONStorableString title = new JSONStorableString("Title",
                "VaM-RT Senses v" + VERSION + "\nDescribes the world around this character in a few lines of text and can send it to the Voxta context. " +
                "Runs on the CPU only. Tip: turn on 'Send to Voxta context' only after the snapshot on the right looks right.");
            UIDynamicTextField t = CreateTextField(title, false);
            t.height = 150f;

            CreateToggle(_enabled, false).height = 50f;
            CreateToggle(_sendToVoxta, false).height = 50f;
            CreateScrollablePopup(_delivery, false);
            CreateScrollablePopup(_slot, false);
            CreateSlider(_radius, false);
            CreateSlider(_maxObjects, false);
            CreateSlider(_interval, false);
            CreateToggle(_onlyTagged, false).height = 50f;
            CreateSlider(_gazeCone, false);
            CreateSlider(_wideSpread, false);
            CreateSpacer(false).height = 10f;
            CreateToggle(_sendEvents, false).height = 50f;
            CreateSlider(_approach, false);
            CreateSlider(_leave, false);
            CreateSlider(_stare, false);
            CreateSlider(_eventCooldown, false);
            CreateSlider(_quietSeconds, false);
            CreateSpacer(false).height = 10f;
            CreateToggle(_fireTriggers, false).height = 50f;
            CreateSlider(_triggerCooldown, false);
            CreateButton("Refresh atom and plugin lists", false).button.onClick.AddListener(delegate { RefreshAllReactions(); });
            foreach (Reaction r in _reactions)
            {
                Reaction rr = r;
                JSONStorableString label = new JSONStorableString(rr.Title + " label", rr.Title + ": call this action");
                CreateTextField(label, false).height = 40f;
                CreateScrollablePopup(rr.Atom, false);
                CreateScrollablePopup(rr.Receiver, false);
                CreateScrollablePopup(rr.Action, false);
                CreateButton("Test: " + rr.Title, false).button.onClick.AddListener(delegate { FireTrigger(rr.Key); });
            }
            CreateToggle(_useEMotion, false).height = 50f;
            CreateSpacer(false).height = 10f;
            CreateToggle(_followOn, false).height = 50f;
            CreateSlider(_followMax, false);
            CreateSlider(_followMin, false);
            CreateSlider(_followPref, false);
            CreateSlider(_followSpeed, false);
            CreateSlider(_followArea, false);
            CreateToggle(_followGround, false).height = 50f;
            CreateButton("Set origin here (follow area centre and position report)", false).button.onClick.AddListener(delegate { SetAnchor(); });
            CreateSpacer(false).height = 10f;

            UIDynamicButton sendBtn = CreateButton("Send snapshot now", false);
            sendBtn.button.onClick.AddListener(delegate { ForceSend(); });
            UIDynamicButton calBtn = CreateButton("Calibrate: she is standing now", false);
            calBtn.button.onClick.AddListener(delegate { Calibrate(); });
            CreateSpacer(false).height = 10f;
            UIDynamicButton spawnBtn = CreateButton("Spawn test props (3 cubes)", false);
            spawnBtn.button.onClick.AddListener(delegate { StartSpawn(); });
            UIDynamicButton removeBtn = CreateButton("Remove test props", false);
            removeBtn.button.onClick.AddListener(delegate { RemoveProps(); });

            UIDynamicTextField snap = CreateTextField(_snapshotText, true);
            snap.height = 330f;
            UIDynamicTextField status = CreateTextField(_statusText, true);
            status.height = 110f;
            UIDynamicTextField odo = CreateTextField(_odoText, true);
            odo.height = 130f;
            UIDynamicTextField follow = CreateTextField(_followText, true);
            follow.height = 230f;
            UIDynamicTextField debug = CreateTextField(_debugText, true);
            debug.height = 200f;
            UIDynamicTextField err = CreateTextField(_errorText, true);
            err.height = 110f;
        }

        // ---------------------------------------------------------------- sensing

        private FreeControllerV3 Ctl(string id)
        {
            try { return containingAtom.GetStorableByID(id) as FreeControllerV3; }
            catch (Exception) { return null; }
        }

        private void ResolveControllers()
        {
            _hip = Ctl("hipControl");
            _chest = Ctl("chestControl");
            _head = Ctl("headControl");
            _lThigh = Ctl("lThighControl");
            _rThigh = Ctl("rThighControl");
            _lFoot = Ctl("lFootControl");
            _rFoot = Ctl("rFootControl");
            _resolved = _hip != null;
        }

        // Which way she faces on the ground, from the line between her thighs (follows BVH turns, which rotate the hips
        // but not her base control).
        private Vector3 Facing()
        {
            if (_lThigh != null && _rThigh != null)
            {
                Vector3 r = _rThigh.transform.position - _lThigh.transform.position;
                r.y = 0f;
                if (r.sqrMagnitude > 0.0004f)
                {
                    Vector3 f = new Vector3(-r.z, 0f, r.x);   // forward = cross(right, up) in Unity's left-handed axes
                    return f.normalized;
                }
            }
            Vector3 m = containingAtom.mainController != null ? containingAtom.mainController.transform.forward : new Vector3(0f, 0f, 1f);
            m.y = 0f;
            if (m.sqrMagnitude < 0.0001f) m = new Vector3(0f, 0f, 1f);
            return m.normalized;
        }

        private static Vector3 Flat(Vector3 v) { v.y = 0f; return v; }

        private void Sample()
        {
            if (!_resolved) ResolveControllers();
            FreeControllerV3 root = containingAtom.mainController;
            if (root == null || _hip == null)
            {
                _statusText.val = "Waiting for this character's body controllers.";
                return;
            }

            Vector3 rootPos = root.transform.position;
            Vector3 hipPos = _hip.transform.position;
            Vector3 headPos = _head != null ? _head.transform.position : hipPos + new Vector3(0f, 0.6f, 0f);
            Vector3 chestPos = _chest != null ? _chest.transform.position : headPos;
            Vector3 fwd = Facing();

            float hipH = hipPos.y - rootPos.y;
            float torso = Vector3.Angle(chestPos - hipPos, new Vector3(0f, 1f, 0f));
            if (torso < 25f && hipH > _standHip) _standHip = hipH;   // learn the standing hip height (upwards only)

            float spread = 0f;
            if (_lFoot != null && _rFoot != null) spread = Flat(_lFoot.transform.position - _rFoot.transform.position).magnitude;
            float scale = _standHip / 0.9f;

            SensesLogic.Data d = new SensesLogic.Data();
            d.Pose = SensesLogic.ClassifyPose(hipH, _standHip, torso);
            d.LegsWide = spread > _wideSpread.val * scale;

            // the user
            string userDebug = "no camera";
            var ct = SuperController.singleton.centerCameraTarget;
            Camera cam = ct != null ? ct.targetCamera : null;
            if (cam != null)
            {
                Vector3 camPos = cam.transform.position;
                Vector3 toUser = Flat(camPos - hipPos);
                d.HasUser = true;
                d.UserDistance = toUser.magnitude;
                d.UserAngle = SensesLogic.SignedAngleY(fwd, toUser);
                float gaze = Vector3.Angle(cam.transform.forward, headPos - camPos);
                d.UserLooking = gaze < _gazeCone.val;
                userDebug = "user " + d.UserDistance.ToString("0.0") + " m, angle " + d.UserAngle.ToString("0") + ", gaze off-target " + gaze.ToString("0") + " deg";
            }

            // the mood from E-Motion (read-only: its Valence and Arousal fields are outputs)
            string emotionDebug = "E-Motion: not used";
            if (_useEMotion.val)
            {
                MVRScript em = FindEMotion();
                if (em == null) emotionDebug = "E-Motion: not found on this atom";
                else
                {
                    JSONStorableFloat mv = em.GetFloatJSONParam("Valence");
                    JSONStorableFloat ma = em.GetFloatJSONParam("Arousal");
                    if (mv != null && ma != null)
                    {
                        d.HasMood = true; d.Valence = mv.val; d.Arousal = ma.val;
                        emotionDebug = "E-Motion: valence " + mv.val.ToString("0.0") + ", arousal " + ma.val.ToString("0.0") +
                                       " | controls: head " + OnOff(em.GetBoolJSONParam("Control Head")) +
                                       ", morphs " + OnOff(em.GetBoolJSONParam("Control Morphs")) +
                                       ", eyes " + OnOff(em.GetBoolJSONParam("Control Eye Target"));
                    }
                    else emotionDebug = "E-Motion found, but it has no Valence/Arousal fields";
                }
            }

            // VaM triggers: same detection as the Voxta events, but with their own cooldown and no waiting for conversations
            string triggerDebug = "reactions off";
            if (_fireTriggers.val && d.HasUser)
            {
                string tk = _presenceTrig.Update(Time.time, 0.5f, d.UserDistance, d.UserLooking, true, _approach.val, _leave.val, _stare.val, _triggerCooldown.val);
                if (tk != null) { FireTrigger(tk); _presenceTrig.Fired(tk, Time.time); }
                triggerDebug = _presenceTrig.DebugText(Time.time, _stare.val, _triggerCooldown.val);
            }
            else if (!_fireTriggers.val)
            {
                _presenceTrig.ResetAll();
            }

            // events: the user walking up, walking away, or staring (only while switched on)
            // a new chat (Voxta turning ready again) starts from a clean slate: no leftover cooldowns or wording counters
            bool voxtaReady = FindVoxta() != null;
            if (voxtaReady && !_voxtaWasReady) _presence.ResetAll();
            _voxtaWasReady = voxtaReady;

            string presenceDebug = "events off";
            if (_sendEvents.val && d.HasUser)
            {
                bool quiet = VoxtaQuiet();
                string kind = _presence.Update(Time.time, 0.5f, d.UserDistance, d.UserLooking, quiet, _approach.val, _leave.val, _stare.val, _eventCooldown.val);
                if (kind != null)
                {
                    string evText = _presence.TextFor(kind);
                    if (SendEvent(evText))
                    {
                        _presence.Fired(kind, Time.time);
                        _lastEventText = DateTime.Now.ToString("HH:mm:ss") + "  " + evText;
                    }
                }
                presenceDebug = _presence.DebugText(Time.time, _stare.val, _eventCooldown.val) + "\nconversation: " + (quiet ? "quiet" : "busy (events wait)");
            }
            else if (!_sendEvents.val)
            {
                _presence.Reset();
            }

            // nearby atoms
            List<SensesLogic.ObjectInfo> found = new List<SensesLogic.ObjectInfo>();
            List<Atom> atoms = SuperController.singleton.GetAtoms();
            for (int i = 0; i < atoms.Count; i++)
            {
                Atom a = atoms[i];
                if (a == null || a == containingAtom || !a.on) continue;
                if (IsIgnoredType(a.type)) continue;
                FreeControllerV3 c = a.mainController;
                if (c == null) continue;
                Vector3 p = c.transform.position;
                float dist = Vector3.Distance(rootPos, p);
                if (dist > _radius.val) continue;

                string clean = SensesLogic.CleanName(a.name, a.type);
                bool sit, surface, look, ignore;
                SensesLogic.ParseTags(a.name, clean, out sit, out surface, out look, out ignore);
                if (ignore) continue;
                bool isPerson = a.type == "Person";
                if (_onlyTagged.val && !isPerson && !sit && !surface && !look) continue;

                SensesLogic.ObjectInfo o = new SensesLogic.ObjectInfo();
                o.Name = clean;
                o.IsPerson = isPerson;
                o.Distance = dist;
                o.Angle = SensesLogic.SignedAngleY(fwd, Flat(p - rootPos));
                o.Sit = sit; o.Surface = surface; o.Look = look;
                found.Add(o);
            }
            found.Sort(delegate (SensesLogic.ObjectInfo x, SensesLogic.ObjectInfo y) { return x.Distance.CompareTo(y.Distance); });
            int max = (int)Math.Round(_maxObjects.val);
            for (int i = 0; i < found.Count && i < max; i++) d.Objects.Add(found[i]);

            UpdateFollow(rootPos, hipPos, fwd, cam != null, cam != null ? cam.transform.position : rootPos, scale);

            _debugText.val = "hip height " + hipH.ToString("0.00") + " m (standing reference " + _standHip.ToString("0.00") + ")\n" +
                             "torso angle " + torso.ToString("0") + " deg, foot spread " + spread.ToString("0.00") + " m\n" +
                             "facing x/z " + fwd.x.ToString("0.00") + " / " + fwd.z.ToString("0.00") + "\n" +
                             userDebug + "\n" +
                             "atoms in range " + found.Count + ", reported " + d.Objects.Count + "\n" +
                             emotionDebug + "\nvoxta events: " + presenceDebug + "\nlast voxta event: " + _lastEventText + "\n" +
                             "reactions: " + triggerDebug + "\nlast reaction: " + _lastTriggerText;

            // accept a new description only once it has been stable for a moment (avoids flicker while moving)
            string text = SensesLogic.Build(d);
            if (text == _lastText)
            {
                _candidateText = text;
            }
            else if (text == _candidateText)
            {
                if (Time.time - _candidateSince >= 1.0f)
                {
                    _lastText = text;
                    _snapshotText.val = text;
                }
            }
            else
            {
                _candidateText = text;
                _candidateSince = Time.time;
            }

            if (_sendToVoxta.val) TrySend(false);
            else _statusText.val = VoxtaStatus(null) + "\nAuto-send is OFF (use 'Send snapshot now' to test).";
        }

        private static string OnOff(JSONStorableBool b)
        {
            return b == null ? "?" : (b.val ? "on" : "off");
        }

        private static bool IsIgnoredType(string type)
        {
            if (string.IsNullOrEmpty(type)) return true;
            if (type.StartsWith("UI")) return true;   // UI buttons, text, sliders (e.g. the ones the Voxta plugin spawns)
            for (int i = 0; i < IgnoredTypeParts.Length; i++)
                if (type.IndexOf(IgnoredTypeParts[i], StringComparison.OrdinalIgnoreCase) >= 0) return true;
            return false;
        }

        private void Calibrate()
        {
            try
            {
                if (_hip == null || containingAtom.mainController == null) { _statusText.val = "Cannot calibrate yet: body controllers not found."; return; }
                _standHip = _hip.transform.position.y - containingAtom.mainController.transform.position.y;
                _statusText.val = "Standing hip height set to " + _standHip.ToString("0.00") + " m.";
            }
            catch (Exception e) { ShowError("calibrate", e); }
        }

        // ---------------------------------------------------------------- Voxta

        private static bool VoxtaReady(MVRScript p)
        {
            if (p == null) return false;
            JSONStorableStringChooser st = p.GetStringChooserJSONParam("State");
            return st != null && st.val != "off";
        }

        private MVRScript FindVoxta()
        {
            if (_voxta != null && VoxtaReady(_voxta)) return _voxta;
            _voxta = null;
            if (Time.time - _voxtaCheckTime < 2f) return null;   // do not search every frame
            _voxtaCheckTime = Time.time;

            MVRScript best = null;
            foreach (Atom atom in SuperController.singleton.GetAtoms())
            {
                MVRPluginManager mgr = atom.GetStorableByID("PluginManager") as MVRPluginManager;
                if (mgr == null) continue;
                Transform plugins = mgr.gameObject.transform.Find("Plugins");
                if (plugins == null) continue;
                foreach (Transform t in plugins)
                {
                    MVRScript p = t.gameObject.GetComponent<MVRScript>();
                    if (p == null || p.name == null || !p.name.EndsWith("Voxta") || !VoxtaReady(p)) continue;
                    if (best == null) best = p;
                    if (p.GetStringChooserParamValue("AudioAtom") == containingAtom.name) { best = p; break; }
                }
            }
            _voxta = best;
            return best;
        }

        private string VoxtaStatus(MVRScript v)
        {
            MVRScript p = v ?? FindVoxta();
            if (p == null) return "Voxta: not found, or not connected (its State is 'off').";
            return "Voxta: found (" + p.containingAtom.name + " > " + p.name + "), " +
                   (_delivery.val == DeliverySecret ? "delivery: hidden chat message." : "delivery: context slot " + _slot.val + ".");
        }

        private void ForceSend()
        {
            try { TrySend(true); }
            catch (Exception e) { ShowError("send", e); }
        }

        private void TrySend(bool force)
        {
            if (_lastText.Length == 0) { if (force) _statusText.val = "Nothing to send yet."; return; }
            if (!force)
            {
                if (_lastText == _lastSentText) return;
                if (Time.time - _lastSendTime < _interval.val) return;
            }
            MVRScript v = FindVoxta();
            if (v == null) { _statusText.val = VoxtaStatus(null); return; }
            if (_delivery.val == DeliverySecret)
            {
                // A hidden chat message ("/secret ..."): the AI sees it near the end of the conversation, the user does not,
                // and it does not trigger a reply. It stays in the chat history, so use a longer interval.
                JSONStorableString trig = v.GetStringJSONParam("TriggerMessage");
                if (trig == null) { _statusText.val = "Voxta found, but it has no 'TriggerMessage' field."; return; }
                trig.valNoCallback = "";
                trig.val = "/secret " + _lastText.Replace("\r", "").Replace("\n", " ");
                _lastSentText = _lastText;
                _lastSendTime = Time.time;
                _statusText.val = VoxtaStatus(v) + "\nSent as a hidden chat message at " + DateTime.Now.ToString("HH:mm:ss") + ".";
                return;
            }

            string slotName = "Context (Slot " + _slot.val + ")";
            JSONStorableString slot = v.GetStringJSONParam(slotName);
            if (slot == null) { _statusText.val = "Voxta found, but it has no field '" + slotName + "' (is a character loaded in the Voxta plugin?)."; return; }

            slot.valNoCallback = "";   // reset first so the plugin sees a change even if the text repeats
            slot.val = _lastText;
            _lastSentText = _lastText;
            _lastWrittenSlot = slotName;
            _lastSendTime = Time.time;
            _statusText.val = VoxtaStatus(v) + "\nLast sent at " + DateTime.Now.ToString("HH:mm:ss") + ".";
        }

        // Events wait while Voxta is listening, thinking or speaking, and for a quiet moment afterwards, so they never
        // interrupt a conversation. Voxta's plugin reports "off", "idle", "listening", "thinking" or "speaking".
        private bool VoxtaQuiet()
        {
            MVRScript v = FindVoxta();
            if (v == null) return false;
            JSONStorableStringChooser st = v.GetStringChooserJSONParam("State");
            if (st == null || st.val != "idle") { _lastBusyTime = Time.time; return false; }
            return Time.time - _lastBusyTime >= _quietSeconds.val;
        }

        // "/event ..." makes the character react in her own voice (it triggers a reply), unlike the quiet scene description.
        private bool SendEvent(string text)
        {
            MVRScript v = FindVoxta();
            if (v == null) return false;
            JSONStorableString trig = v.GetStringJSONParam("TriggerMessage");
            if (trig == null) return false;
            trig.valNoCallback = "";
            trig.val = "/event " + text;
            return true;
        }

        private void ClearSlot()
        {
            _lastSentText = "";
            if (_lastWrittenSlot.Length == 0) return;
            MVRScript v = FindVoxta();
            if (v != null)
            {
                JSONStorableString slot = v.GetStringJSONParam(_lastWrittenSlot);
                if (slot != null) { slot.valNoCallback = "clearing"; slot.val = ""; }
            }
            _lastWrittenSlot = "";
        }

        // ---------------------------------------------------------------- test props

        private void StartSpawn()
        {
            if (_spawning) return;
            if (containingAtom.mainController == null) { _statusText.val = "Cannot spawn: base control not found."; return; }
            StartCoroutine(SpawnProps());
        }

        private IEnumerator SpawnProps()
        {
            _spawning = true;
            try
            {
                Vector3 rootPos = containingAtom.mainController.transform.position;
                Vector3 fwd = Facing();
                for (int i = 0; i < TestProps.Length; i++)
                {
                    PropSpec s = TestProps[i];
                    Atom a = SuperController.singleton.GetAtomByUid(s.Uid);
                    if (a == null)
                    {
                        yield return SuperController.singleton.AddAtomByType("Cube", s.Uid);
                        a = SuperController.singleton.GetAtomByUid(s.Uid);
                        int guard = 0;
                        while (a == null && guard < 60) { guard++; yield return null; a = SuperController.singleton.GetAtomByUid(s.Uid); }
                    }
                    if (a == null) { SetError("spawn", "Could not create '" + s.Uid + "'."); continue; }
                    Vector3 dir = Quaternion.AngleAxis(s.Angle, new Vector3(0f, 1f, 0f)) * fwd;
                    PlaceAtom(a, rootPos + dir * s.Distance + new Vector3(0f, s.Height, 0f));
                }
                _statusText.val = "Test props placed. If they fall (there is no floor), give them a floor or turn their physics off.";
            }
            finally
            {
                _spawning = false;
            }
        }

        private void PlaceAtom(Atom a, Vector3 pos)
        {
            try { if (a.mainController != null) a.mainController.transform.position = pos; }
            catch (Exception e) { ShowError("place", e); }
        }

        private void RemoveProps()
        {
            try
            {
                int n = 0;
                for (int i = 0; i < TestProps.Length; i++)
                {
                    Atom a = SuperController.singleton.GetAtomByUid(TestProps[i].Uid);
                    if (a != null) { SuperController.singleton.RemoveAtom(a); n++; }
                }
                _statusText.val = "Removed " + n + " test prop(s).";
            }
            catch (Exception e) { ShowError("remove", e); }
        }

        // ---------------------------------------------------------------- reactions

        // A reaction calls one named action of one plugin on one atom, e.g. Person > Timeline > "Play Wink".
        // It uses only plain storable calls (GetStorableIDs, GetActionNames, CallAction), no trigger framework.
        private void AddReaction(string key, string title)
        {
            Reaction r = new Reaction();
            r.Key = key; r.Title = title;
            r.Atom = new JSONStorableStringChooser(title + ": atom", AtomChoices(), NoneChoice, title + ": atom");
            r.Receiver = new JSONStorableStringChooser(title + ": plugin", new List<string> { NoneChoice }, NoneChoice, title + ": plugin");
            r.Action = new JSONStorableStringChooser(title + ": action", new List<string> { NoneChoice }, NoneChoice, title + ": action");
            RegisterStringChooser(r.Atom);
            RegisterStringChooser(r.Receiver);
            RegisterStringChooser(r.Action);
            Reaction rr = r;
            // the callbacks only refill the lists below; they never change a saved choice (that would break loading a scene)
            r.Atom.setCallbackFunction += (string v) => { RefreshReceivers(rr); };
            r.Receiver.setCallbackFunction += (string v) => { RefreshActions(rr); };
            _reactions.Add(r);
        }

        private static List<string> AtomChoices()
        {
            List<string> ids = new List<string>();
            foreach (Atom a in SuperController.singleton.GetAtoms()) if (a != null) ids.Add(a.uid);
            ids.Sort();
            ids.Insert(0, NoneChoice);
            return ids;
        }

        private static List<string> WithNone(List<string> names, string keep)
        {
            names.Sort();
            names.Insert(0, NoneChoice);
            if (!string.IsNullOrEmpty(keep) && keep != NoneChoice && !names.Contains(keep)) names.Add(keep);   // a saved choice stays selectable
            return names;
        }

        private void RefreshReceivers(Reaction r)
        {
            List<string> ids = new List<string>();
            Atom a = r.Atom.val == NoneChoice ? null : SuperController.singleton.GetAtomByUid(r.Atom.val);
            if (a != null) ids.AddRange(a.GetStorableIDs());
            r.Receiver.choices = WithNone(ids, r.Receiver.val);
        }

        private void RefreshActions(Reaction r)
        {
            List<string> names = new List<string>();
            Atom a = r.Atom.val == NoneChoice ? null : SuperController.singleton.GetAtomByUid(r.Atom.val);
            JSONStorable st = (a == null || r.Receiver.val == NoneChoice) ? null : a.GetStorableByID(r.Receiver.val);
            if (st != null) foreach (string n in st.GetActionNames()) if (!string.IsNullOrEmpty(n)) names.Add(n);
            r.Action.choices = WithNone(names, r.Action.val);
        }

        private void RefreshAllReactions()
        {
            try
            {
                foreach (Reaction r in _reactions)
                {
                    List<string> atoms = AtomChoices();
                    if (r.Atom.val != NoneChoice && !atoms.Contains(r.Atom.val)) atoms.Add(r.Atom.val);
                    r.Atom.choices = atoms;
                    RefreshReceivers(r);
                    RefreshActions(r);
                }
                _statusText.val = "Atom and plugin lists refreshed.";
            }
            catch (Exception e) { ShowError("refresh", e); }
        }

        private string CallReaction(Reaction r)
        {
            if (r.Atom.val == NoneChoice || r.Receiver.val == NoneChoice || r.Action.val == NoneChoice) return "nothing chosen yet. Scroll down the left column and pick an atom, a plugin and an action under \"" + r.Title + ": call this action\".";
            Atom a = SuperController.singleton.GetAtomByUid(r.Atom.val);
            if (a == null) return "atom '" + r.Atom.val + "' not found";
            JSONStorable st = a.GetStorableByID(r.Receiver.val);
            if (st == null) return "plugin '" + r.Receiver.val + "' not found on " + a.uid;
            st.CallAction(r.Action.val);
            return "called " + a.uid + " > " + r.Receiver.val + " > " + r.Action.val;
        }

        private void FireTrigger(string kind)
        {
            try
            {
                string result = "no reaction defined";
                foreach (Reaction r in _reactions) if (r.Key == kind) result = CallReaction(r);
                _lastTriggerText = DateTime.Now.ToString("HH:mm:ss") + "  On " + kind + ": " + result;
                _statusText.val = "Reaction " + _lastTriggerText;
            }
            catch (Exception e) { ShowError("reaction", e); }
        }

        // ---------------------------------------------------------------- follow (dry run)

        private void SetAnchor()
        {
            if (_hip == null) { _statusText.val = "Cannot set the origin yet: body controllers not found."; return; }
            _anchorX = _hip.transform.position.x;       // her hips: with In Place off they are the part of her that travels
            _anchorZ = _hip.transform.position.z;
            _hasAnchor = true;
            _odoX = _anchorX; _odoZ = _anchorZ; _hasOdo = true;
            _statusText.val = "Origin set to where she stands now (follow area centre and position report).";
        }

        private void UpdateOdometer(Vector3 selfPos, Vector3 fwd)
        {
            if (!_hasOdo) { _odoX = selfPos.x; _odoZ = selfPos.z; _hasOdo = true; }
            float dx = selfPos.x - _odoX, dz = selfPos.z - _odoZ;
            float heading = (float)Math.Atan2(fwd.x, fwd.z) * 57.29578f;
            _odoText.val = "POSITION (her hips, VaM world metres): x " + selfPos.x.ToString("0.00") + ", z " + selfPos.z.ToString("0.00") + "\n" +
                           "Since the origin: " + FollowLogic.Dist(selfPos.x, selfPos.z, _odoX, _odoZ).ToString("0.00") + " m  (dx " +
                           dx.ToString("+0.00;-0.00") + ", dz " + dz.ToString("+0.00;-0.00") + ")\n" +
                           "Facing: " + heading.ToString("0") + " deg (0 = world +Z, positive towards +X)\n" +
                           "Press 'Set origin here' while she stands to zero it, then compare with the stream's /where";
        }

        private void UpdateFollow(Vector3 rootPos, Vector3 hipPos, Vector3 fwd, bool haveUser, Vector3 userPos, float scale)
        {
            // Her place on the floor is her HIPS, at the floor level of her base control.
            Vector3 selfPos = new Vector3(hipPos.x, rootPos.y, hipPos.z);
            UpdateOdometer(selfPos, fwd);
            if (!_followOn.val)
            {
                _followText.val = "Follow is off. When on it only REPORTS what she would do to stay within reach of you; nothing is sent and she does not move.";
                return;
            }
            if (!_hasAnchor) { _anchorX = selfPos.x; _anchorZ = selfPos.z; _hasAnchor = true; }
            if (!haveUser) { _followText.val = "FOLLOW (dry run): no camera, so she cannot see where you are."; return; }
            try
            {
                FollowLogic.Settings s = new FollowLogic.Settings();
                s.MaxDist = _followMax.val;
                s.MinDist = Mathf.Min(_followMin.val, s.MaxDist);
                s.PreferredDist = Mathf.Min(_followPref.val, s.MaxDist);   // never aim outside the band, or she would walk on forever
                s.Speed = _followSpeed.val;
                s.AreaRadius = _followArea.val;
                s.RequireGround = _followGround.val;

                FollowLogic.Input i = new FollowLogic.Input();
                i.SelfX = selfPos.x; i.SelfZ = selfPos.z; i.FacingX = fwd.x; i.FacingZ = fwd.z;
                i.UserX = userPos.x; i.UserZ = userPos.z; i.AnchorX = _anchorX; i.AnchorZ = _anchorZ;

                string pathNote = "not needed";
                string groundNote = "not needed";
                float gx, gz; bool clamped; string why;
                if (FollowLogic.Goal(s, i, out gx, out gz, out clamped, out why))
                {
                    Vector3 goal = new Vector3(gx, selfPos.y, gz);
                    string obstacle;
                    i.ObstacleDist = ProbePath(selfPos, goal, scale, out obstacle);
                    i.ObstacleName = obstacle;
                    string gnote; bool known;
                    bool ok = CheckGround(selfPos, goal, scale, out known, out gnote);
                    i.GroundKnown = known; i.GroundOk = ok; i.GroundNote = gnote;
                    pathNote = i.ObstacleDist < float.MaxValue ? (obstacle.Length > 0 ? "'" + obstacle + "'" : "obstacle") + " at " + i.ObstacleDist.ToString("0.0") + " m" : "clear";
                    groundNote = !known ? "no floor under her, not checked" : (ok ? "ok" : gnote);
                }

                FollowLogic.Decision r = FollowLogic.Decide(s, i);
                float fromCentre = FollowLogic.Dist(selfPos.x, selfPos.z, _anchorX, _anchorZ);
                _followText.val = "FOLLOW (dry run: nothing is sent, she does not move)\n" +
                                  FollowLogic.Describe(r) + "\n" +
                                  "user " + r.UserDist.ToString("0.0") + " m away (walks when over " + s.MaxDist.ToString("0.0") + " m, stays put under " + s.MinDist.ToString("0.0") + " m)\n" +
                                  "path: " + pathNote + " | ground: " + groundNote + "\n" +
                                  "area: she is " + fromCentre.ToString("0.0") + " m from its centre (limit " + s.AreaRadius.ToString("0.0") + " m)\n" +
                                  "would send: " + FollowLogic.CommandJson(r);
            }
            catch (Exception e) { ShowError("follow", e); }
        }

        // Distance along the way to the goal at which something solid is in the way (float.MaxValue = clear). Six rays: knee and
        // waist height, centre and 30 cm to each side, so a table edge or a thin pole is found as well as a wall. Her own
        // body is looked through; triggers are ignored.
        private float ProbePath(Vector3 from, Vector3 goal, float scale, out string name)
        {
            name = "";
            Vector3 dir = Flat(goal - from);
            float len = dir.magnitude;
            if (len < 0.05f) return float.MaxValue;
            dir = dir * (1f / len);
            Vector3 side = new Vector3(dir.z, 0f, -dir.x);
            float best = float.MaxValue;
            float[] heights = new float[] { 0.35f * scale, 1.0f * scale };
            float[] lateral = new float[] { -0.3f * scale, 0f, 0.3f * scale };
            for (int h = 0; h < heights.Length; h++)
            {
                for (int l = 0; l < lateral.Length; l++)
                {
                    Vector3 o = from + side * lateral[l];
                    o.y = from.y + heights[h];
                    float travelled = 0f;
                    for (int k = 0; k < 8; k++)
                    {
                        float room = len + 0.3f - travelled;
                        if (room <= 0f) break;
                        RaycastHit hit;
                        if (!Physics.Raycast(o, dir, out hit, room, Physics.DefaultRaycastLayers, QueryTriggerInteraction.Ignore)) break;
                        if (hit.collider == null) break;
                        if (hit.collider.transform.IsChildOf(containingAtom.transform))
                        {
                            o = hit.point + dir * 0.02f;           // her own body: look past it
                            travelled += hit.distance + 0.02f;
                            continue;
                        }
                        if (travelled + hit.distance < best)
                        {
                            best = travelled + hit.distance;
                            Atom owner = hit.collider.GetComponentInParent<Atom>();
                            name = owner != null ? owner.uid : hit.collider.name;
                        }
                        break;
                    }
                }
            }
            return best;
        }

        // 0 = no floor, 1 = walkable floor (within 25 cm of the level she stands on), 2 = a step or a drop
        private int GroundAt(Vector3 p, float scale, float baseY)
        {
            Vector3 o = new Vector3(p.x, baseY + 1.0f * scale, p.z);
            float room = 2.0f * scale;
            for (int k = 0; k < 8; k++)
            {
                RaycastHit hit;
                if (!Physics.Raycast(o, Vector3.down, out hit, room, Physics.DefaultRaycastLayers, QueryTriggerInteraction.Ignore)) return 0;
                if (hit.collider == null) return 0;
                if (hit.collider.transform.IsChildOf(containingAtom.transform))
                {
                    o = hit.point + Vector3.down * 0.02f;           // her own body: look past it
                    room -= hit.distance + 0.02f;
                    if (room <= 0f) return 0;
                    continue;
                }
                float dy = hit.point.y - baseY;
                return (dy > -0.25f && dy < 0.25f) ? 1 : 2;
            }
            return 0;
        }

        // Is there walkable floor all the way to the goal? known = false when there is no floor under her at all (a scene without
        // a floor: nothing to judge by, so the check is skipped rather than blocking her forever).
        private bool CheckGround(Vector3 from, Vector3 goal, float scale, out bool known, out string note)
        {
            note = "";
            known = GroundAt(from, scale, from.y) != 0;
            if (!known) return true;
            Vector3 dir = Flat(goal - from);
            float len = dir.magnitude;
            if (len < 0.05f) return true;
            dir = dir * (1f / len);
            int steps = (int)(len / 0.6f) + 1;
            if (steps > 10) steps = 10;
            for (int k = 1; k <= steps; k++)
            {
                float dist = Mathf.Min(len, k * 0.6f);
                int g = GroundAt(from + dir * dist, scale, from.y);
                if (g == 1) continue;
                note = (g == 0 ? "no floor" : "a step or drop") + " at " + dist.ToString("0.0") + " m";
                return false;
            }
            return true;
        }

        // ---------------------------------------------------------------- E-Motion

        // E-Motion (VRAdultFun) is a plugin on the same atom; its class is VRAdultFun.EmotionEngine.
        private MVRScript FindEMotion()
        {
            if (_emotion != null) return _emotion;
            if (Time.time - _emotionCheckTime < 3f) return null;
            _emotionCheckTime = Time.time;
            MVRPluginManager mgr = containingAtom.GetStorableByID("PluginManager") as MVRPluginManager;
            if (mgr == null) return null;
            Transform plugins = mgr.gameObject.transform.Find("Plugins");
            if (plugins == null) return null;
            foreach (Transform t in plugins)
            {
                MVRScript p = t.gameObject.GetComponent<MVRScript>();
                if (p != null && p.name != null && p.name.EndsWith("EmotionEngine")) { _emotion = p; return p; }
            }
            return null;
        }

        // ---------------------------------------------------------------- errors

        private void ShowError(string where, Exception e)
        {
            SetError(where, e.Message);
        }

        private void SetError(string where, string message)
        {
            string text = where + ": " + message;
            if (_errorText != null) _errorText.val = text;
            if (text != _lastErrorShown)
            {
                _lastErrorShown = text;
                SuperController.LogError("VaM-RT Senses " + text);
            }
        }
    }

    // -------------------------------------------------------------------------
    // Pure logic: no VaM types, so it can be unit-tested outside VaM.
    // -------------------------------------------------------------------------
    public static class SensesLogic
    {
        public const string CHAR = "{{ char }}";
        public const string USER = "{{ user }}";

        public class ObjectInfo
        {
            public string Name;
            public bool IsPerson;
            public float Distance;   // metres from the character
            public float Angle;      // degrees relative to where the character faces, positive = to her right
            public bool Sit, Surface, Look;
        }

        public class Data
        {
            public string Pose = "standing";
            public bool LegsWide;
            public bool HasUser;
            public float UserDistance;
            public float UserAngle;
            public bool UserLooking;
            public bool HasMood;
            public float Valence;   // E-Motion's happiness, 0..10
            public float Arousal;   // E-Motion's excitement, 0..10
            public List<ObjectInfo> Objects = new List<ObjectInfo>();
        }

        // ---- wording helpers ------------------------------------------------

        public static string Direction(float a)
        {
            float abs = Math.Abs(a);
            string side = a >= 0f ? "right" : "left";
            if (abs < 22.5f) return "directly in front";
            if (abs < 67.5f) return "in front and to the " + side;
            if (abs < 112.5f) return "to the " + side;
            if (abs < 157.5f) return "behind and to the " + side;
            return "directly behind";
        }

        // used as "{{ user }} is <phrase>"
        public static string DistancePhrase(float d)
        {
            if (d < 0.5f) return "very close to " + CHAR;
            if (d < 1.0f) return "within arm's reach of " + CHAR;
            if (d < 2.0f) return "close to " + CHAR;
            return "about " + Math.Round(d).ToString("0") + " m from " + CHAR;
        }

        // where an object is, as a phrase: "within reach", "close by", "about 3 m away"
        public static string ObjectDistance(float d)
        {
            if (d < 0.5f) return "right beside " + CHAR;
            if (d < 1.0f) return "within reach";
            if (d < 2.0f) return "close by";
            return "about " + Math.Round(d).ToString("0") + " m away";
        }

        // one plain sentence per object (not a bracketed list, which a small action model can mistake for a request)
        public static string ObjectSentence(ObjectInfo o)
        {
            string where = ObjectDistance(o.Distance) + ", " + Direction(o.Angle);
            string t = o.IsPerson ? "Another person, " + o.Name + ", is " + where + "." : "There is " + WithArticle(o.Name) + " " + where + ".";
            if (!o.IsPerson)
            {
                if (o.Sit) t += " It can be sat on.";
                if (o.Surface) t += " It is a flat surface.";
                if (o.Look) t += " It is worth looking at.";
            }
            return t;
        }

        // hipHeight: hip above her base control; standHip: learned standing hip height; torsoAngle: degrees from vertical
        public static string ClassifyPose(float hipHeight, float standHip, float torsoAngle)
        {
            if (standHip < 0.3f) standHip = 0.3f;
            float ratio = hipHeight / standHip;
            if (ratio > 0.8f && torsoAngle < 40f) return "standing";
            if (torsoAngle >= 50f && ratio >= 0.6f) return "bent over";
            if (ratio < 0.35f && torsoAngle >= 55f) return "lying down";
            if (ratio >= 0.35f && ratio <= 0.8f && torsoAngle < 50f) return "sitting or crouching";
            return "in an unclear pose";
        }

        // "happy and excited" from E-Motion's two numbers; empty while she is neutral, so the description stays short
        public static string MoodPhrase(float valence, float arousal)
        {
            string mood = valence < 1.5f ? "" : (valence < 3.5f ? "pleased" : (valence < 6f ? "happy" : "delighted"));
            string energy = arousal < 2f ? "" : (arousal < 5f ? "interested" : (arousal < 8f ? "excited" : "very excited"));
            if (mood.Length > 0 && energy.Length > 0) return mood + " and " + energy;
            return mood.Length > 0 ? mood : energy;
        }

        public static float SignedAngleY(Vector3 forward, Vector3 to)
        {
            float ang = Vector3.Angle(forward, to);
            float sign = Vector3.Cross(forward, to).y >= 0f ? 1f : -1f;   // Unity is left-handed: +y means "to the right"
            return ang * sign;
        }

        private static readonly Regex BracketRx = new Regex(@"\[([^\]]*)\]", RegexOptions.Compiled);
        private static readonly Regex DupSuffixRx = new Regex(@"#\d+$", RegexOptions.Compiled);

        public static string CleanName(string raw, string type)
        {
            string s = raw ?? "";
            s = BracketRx.Replace(s, "");
            s = DupSuffixRx.Replace(s.Trim(), "");
            if (s.StartsWith("VaMRT ")) s = s.Substring(6);
            s = Regex.Replace(s, @"\s+", " ").Trim().ToLowerInvariant();
            if (s.Length == 0) s = (type ?? "object").ToLowerInvariant();
            return s;
        }

        public static void ParseTags(string raw, string cleanedName, out bool sit, out bool surface, out bool look, out bool ignore)
        {
            sit = surface = look = ignore = false;
            foreach (Match m in BracketRx.Matches(raw ?? ""))
            {
                foreach (string part in m.Groups[1].Value.Split(new char[] { ',', ' ', ';' }, StringSplitOptions.RemoveEmptyEntries))
                {
                    string t = part.Trim().ToLowerInvariant();
                    if (t == "sit") sit = true;
                    else if (t == "surface") surface = true;
                    else if (t == "look") look = true;
                    else if (t == "ignore") ignore = true;
                }
            }
            if (!sit && !surface)
            {
                string[] words = Regex.Split(cleanedName ?? "", @"[^a-z]+");
                if (HasWord(words, new string[] { "chair", "stool", "sofa", "couch", "bench", "seat", "bed" }, new string[] { "chair", "sofa", "couch", "stool", "bench" })) sit = true;
                else if (HasWord(words, new string[] { "table", "desk", "counter", "shelf" }, new string[0])) surface = true;
            }
        }

        // whole-word match (plural allowed), plus compounds that end in a safe word ("armchair"), so "bedroom" or "vegetable" never match
        private static bool HasWord(string[] words, string[] whole, string[] endings)
        {
            for (int i = 0; i < words.Length; i++)
            {
                string w = words[i];
                if (w.Length == 0) continue;
                for (int j = 0; j < whole.Length; j++)
                    if (w == whole[j] || w == whole[j] + "s") return true;
                for (int j = 0; j < endings.Length; j++)
                    if (w.EndsWith(endings[j], StringComparison.Ordinal)) return true;
            }
            return false;
        }

        public static string WithArticle(string name)
        {
            if (string.IsNullOrEmpty(name)) return "an object";
            char c = name[0];
            bool vowel = "aeiou".IndexOf(c) >= 0;
            return (vowel ? "an " : "a ") + name;
        }

        // ---- the description --------------------------------------------------

        public static string Build(Data d)
        {
            List<string> lines = new List<string>();
            lines.Add("What " + CHAR + " is aware of in the scene right now. This is background knowledge only, never a request to do anything. " +
                      CHAR + " can mention it naturally or answer questions about it.");

            StringBuilder self = new StringBuilder("- " + CHAR + " is " + d.Pose);
            if (d.LegsWide && d.Pose == "standing") self.Append(" with their legs wide apart");
            if (d.HasUser)
            {
                float abs = Math.Abs(d.UserAngle);
                if (abs < 35f) self.Append(", facing " + USER);
                else if (abs > 130f) self.Append(", with their back to " + USER);
            }
            self.Append(".");
            lines.Add(self.ToString());

            if (d.HasMood)
            {
                string mood = MoodPhrase(d.Valence, d.Arousal);
                if (mood.Length > 0) lines.Add("- " + CHAR + " seems " + mood + ".");
            }

            if (d.HasUser)
            {
                string u = "- " + USER + " is " + DistancePhrase(d.UserDistance) + ", " + Direction(d.UserAngle);
                if (d.UserLooking) u += ", and is looking at " + CHAR;
                lines.Add(u + ".");
            }

            if (d.Objects.Count == 0)
            {
                lines.Add("- There is nothing else around " + CHAR + ".");
            }
            else
            {
                foreach (ObjectInfo o in d.Objects) lines.Add("- " + ObjectSentence(o));
            }
            return string.Join("\n", lines.ToArray());
        }
    }

    // -------------------------------------------------------------------------
    // Decides when the user's behaviour is worth reacting to. Pure logic (no VaM types) so it can be tested.
    // Zones use hysteresis and a short confirmation, so walking around the edge of a zone does not spam events.
    // Idea (not code) from the glance/gaze/stare accumulation in VoxtaTouchElite.
    // -------------------------------------------------------------------------
    public class Presence
    {
        private const int NEAR = 0, MID = 1, GONE = 2;
        private const float RearmAfterLookingAway = 8f;   // a stare needs the user to look away before the next one
        private const float StareSpacing = 3f;            // minimum time between stares, in cooldowns
        private int _zone = -1;
        private int _candidate = -1;
        private float _candidateSince;
        private float _lookSeconds;
        private float _notLooking;
        private bool _stareArmed = true;
        private float _lastEventTime = -1000f;
        private float _lastStareTime = -1000f;
        private int _approachCount, _leaveCount, _stareCount;

        private static readonly string[] ApproachText = new string[] {
            SensesLogic.USER + " walks up to " + SensesLogic.CHAR + ".",
            SensesLogic.USER + " comes closer to " + SensesLogic.CHAR + ".",
            SensesLogic.USER + " steps up next to " + SensesLogic.CHAR + "." };
        private static readonly string[] LeaveText = new string[] {
            SensesLogic.USER + " walks away from " + SensesLogic.CHAR + ".",
            SensesLogic.USER + " wanders off, away from " + SensesLogic.CHAR + ".",
            SensesLogic.USER + " moves further away from " + SensesLogic.CHAR + "." };
        private static readonly string[] StareText = new string[] {
            SensesLogic.USER + " has been looking at " + SensesLogic.CHAR + " for a while.",
            SensesLogic.USER + " keeps watching " + SensesLogic.CHAR + " without a word.",
            SensesLogic.USER + "'s eyes are fixed on " + SensesLogic.CHAR + ".",
            SensesLogic.USER + " has not looked away from " + SensesLogic.CHAR + " in a while." };

        public void Reset()
        {
            _zone = -1; _candidate = -1; _lookSeconds = 0f; _notLooking = 0f; _stareArmed = true;
        }

        // Also forgets cooldowns and wording counters (new chat, or the user toggling events).
        public void ResetAll()
        {
            Reset();
            _lastEventTime = -1000f; _lastStareTime = -1000f;
            _approachCount = 0; _leaveCount = 0; _stareCount = 0;
        }

        // Different wording each time, so the chat history does not fill with one repeated sentence.
        public static string EventText(string kind, int n)
        {
            string[] t = kind == "approach" ? ApproachText : (kind == "leave" ? LeaveText : StareText);
            return t[n % t.Length];
        }

        public string TextFor(string kind)
        {
            return EventText(kind, kind == "approach" ? _approachCount : (kind == "leave" ? _leaveCount : _stareCount));
        }

        // Returns "approach", "leave", "stare" or null. Call Fired() once the event was really sent.
        // quiet = nobody is talking right now. Zone changes during a conversation are dropped, and looking at her while
        // talking does not count as a stare (it is the normal thing to do).
        public string Update(float now, float dt, float dist, bool looking, bool quiet, float approach, float leave, float stare, float cooldown)
        {
            int z = _zone;
            if (z < 0)
            {
                z = dist < approach ? NEAR : (dist > leave ? GONE : MID);   // the first reading never fires an event
            }
            else
            {
                if (z != NEAR && dist < approach) z = NEAR;
                else if (z == NEAR && dist > approach + 0.5f) z = MID;
                if (z != GONE && dist > leave) z = GONE;
                else if (z == GONE && dist < leave - 0.5f) z = MID;
            }

            string ev = null;
            if (_zone < 0)
            {
                _zone = z; _candidate = z; _candidateSince = now;
            }
            else if (z != _zone)
            {
                if (z != _candidate) { _candidate = z; _candidateSince = now; }
                else if (now - _candidateSince >= 1.5f)
                {
                    _zone = z;
                    if (z == NEAR) ev = "approach";
                    else if (z == GONE) ev = "leave";
                }
            }
            else
            {
                _candidate = _zone;
            }

            if (looking) _notLooking = 0f;
            else { _notLooking += dt; if (_notLooking >= RearmAfterLookingAway) _stareArmed = true; }

            if (looking && quiet) _lookSeconds = Math.Min(_lookSeconds + dt, stare * 1.5f);
            else if (looking) _lookSeconds = 0f;
            else _lookSeconds = Math.Max(0f, _lookSeconds - dt * 0.5f);

            if (ev == null && _stareArmed && _lookSeconds >= stare && _zone != GONE) ev = "stare";

            if (ev != null && !quiet) return null;                                   // never interrupt a conversation
            if (ev != null && now - _lastEventTime < cooldown) return null;          // too soon after the last event
            if (ev == "stare" && now - _lastStareTime < cooldown * StareSpacing) return null;
            return ev;
        }

        public void Fired(string kind, float now)
        {
            _lastEventTime = now;
            if (kind == "approach") _approachCount++;
            else if (kind == "leave") _leaveCount++;
            else
            {
                _stareCount++; _lookSeconds = 0f; _stareArmed = false; _notLooking = 0f; _lastStareTime = now;
            }
        }

        public string DebugText(float now, float stare, float cooldown)
        {
            string zone = _zone == NEAR ? "near" : (_zone == GONE ? "far away" : (_zone == MID ? "mid distance" : "unknown"));
            float wait = cooldown - (now - _lastEventTime);
            return "presence: " + zone + ", looking " + _lookSeconds.ToString("0.0") + "/" + stare.ToString("0") + " s" +
                   (_stareArmed ? "" : " (stare waits for a look away)") + ", " +
                   (wait > 0f ? "next event allowed in " + wait.ToString("0") + " s" : "ready for an event");
        }
    }

    // ------------------------------------------------------------------------------------------------------
    // Follow: what should she do to stay within reach of the user? Pure logic (no VaM calls), so it can be tested.
    // The plugin measures (positions, obstacles, ground), this class decides, and the answer is a short "lease"
    // command in HER OWN frame (metres ahead / to the right), which is what the motion stream will consume later.
    // In this version the plugin only REPORTS what it would do (dry run); nothing is sent and she does not move.
    // ------------------------------------------------------------------------------------------------------
    public static class FollowLogic
    {
        public const float ArriveRadius = 0.35f;   // within this of the goal she simply stands (matches the motion planner)
        public const float StopMargin = 0.6f;      // she stops this far in front of an obstacle
        public const float LeaseSeconds = 3f;      // a command is only valid this long; no renewal = she stops

        public class Settings
        {
            public float MinDist = 0.8f;        // closer than this to the user: she stays put
            public float MaxDist = 2.5f;        // farther than this: she walks towards the user
            public float PreferredDist = 1.8f;  // she walks to a point this far from the user (on the line towards her)
            public float Speed = 1.2f;          // m/s
            public float AreaRadius = 6f;       // she never goes farther than this from the area centre
            public bool RequireGround = true;
        }

        public class Input
        {
            public float SelfX, SelfZ;
            public float FacingX = 0f, FacingZ = 1f;   // unit vector: where she faces
            public float UserX, UserZ;
            public float AnchorX, AnchorZ;             // centre of the allowed area
            public float ObstacleDist = float.MaxValue;  // distance along the way to the nearest obstacle
            public string ObstacleName = "";
            public bool GroundKnown;                   // false when there is no floor under her at all (nothing to judge by)
            public bool GroundOk = true;
            public string GroundNote = "";
        }

        public class Decision
        {
            public bool Walk;                 // true = she would walk, false = she would stand
            public string Why = "";           // short reason, for the status text
            public float GoalX, GoalZ;        // world position she would walk to
            public float Forward, Right;      // the same goal in her own frame, metres ahead / to the right
            public float Speed;
            public float UserDist;
            public bool Shortened, Clamped;
        }

        public static float Dist(float ax, float az, float bx, float bz)
        {
            float dx = ax - bx, dz = az - bz;
            return (float)Math.Sqrt(dx * dx + dz * dz);
        }

        // Where would she like to be? Returns false (and a reason) when she is already fine where she is.
        // The goal is already clamped to the allowed area (clamped = true when that changed it).
        public static bool Goal(Settings s, Input i, out float gx, out float gz, out bool clamped, out string why)
        {
            gx = i.SelfX; gz = i.SelfZ; why = ""; clamped = false;
            float d = Dist(i.SelfX, i.SelfZ, i.UserX, i.UserZ);
            if (d < s.MinDist) { why = "too close to the user, staying put"; return false; }
            if (d <= s.MaxDist) { why = "within reach of the user"; return false; }
            // a point PreferredDist from the user, on the line from the user towards her
            float ux = (i.SelfX - i.UserX) / d, uz = (i.SelfZ - i.UserZ) / d;
            gx = i.UserX + ux * s.PreferredDist;
            gz = i.UserZ + uz * s.PreferredDist;
            float fromCentre = Dist(gx, gz, i.AnchorX, i.AnchorZ);       // stay inside the allowed area
            if (fromCentre > s.AreaRadius)
            {
                float k = s.AreaRadius / fromCentre;
                gx = i.AnchorX + (gx - i.AnchorX) * k;
                gz = i.AnchorZ + (gz - i.AnchorZ) * k;
                clamped = true;
            }
            return true;
        }

        public static Decision Decide(Settings s, Input i)
        {
            Decision r = new Decision();
            r.Speed = s.Speed;
            r.UserDist = Dist(i.SelfX, i.SelfZ, i.UserX, i.UserZ);
            float gx, gz; bool clamped; string why;
            if (!Goal(s, i, out gx, out gz, out clamped, out why)) { r.Why = why; return r; }
            r.Clamped = clamped;
            // (If she is outside the area, the clamped goal is inside it, so she is simply brought back to its edge.)

            float dx = gx - i.SelfX, dz = gz - i.SelfZ;
            float len = (float)Math.Sqrt(dx * dx + dz * dz);
            if (len <= ArriveRadius)
            { r.Why = r.Clamped ? "the user is outside the allowed area; she is at its edge" : "already at the goal"; return r; }

            if (s.RequireGround && i.GroundKnown && !i.GroundOk)
            { r.Why = "no safe ground ahead" + (i.GroundNote.Length > 0 ? " (" + i.GroundNote + ")" : ""); return r; }

            // obstacles: stop short of them
            if (i.ObstacleDist < len + 0.1f)
            {
                float safe = i.ObstacleDist - StopMargin;
                string what = i.ObstacleName.Length > 0 ? "'" + i.ObstacleName + "' " : "an obstacle ";
                if (safe <= ArriveRadius) { r.Why = what + "is " + i.ObstacleDist.ToString("0.0") + " m ahead"; return r; }
                float k = safe / len;
                gx = i.SelfX + dx * k; gz = i.SelfZ + dz * k;
                dx *= k; dz *= k;
                r.Shortened = true;
                r.Why = "walking up to " + what + "(" + i.ObstacleDist.ToString("0.0") + " m ahead), stopping " + StopMargin.ToString("0.0") + " m short";
            }

            r.Walk = true;
            r.GoalX = gx; r.GoalZ = gz;
            // the goal in her own frame: ahead = along her facing, right = to her right (Unity: right of +Z is +X)
            r.Forward = dx * i.FacingX + dz * i.FacingZ;
            r.Right = dx * i.FacingZ - dz * i.FacingX;
            if (r.Why.Length == 0) r.Why = r.Clamped ? "walking to the edge of the allowed area" : "too far from the user";
            return r;
        }

        // One line each, for the plugin's status box.
        public static string Describe(Decision r)
        {
            if (!r.Walk) return "would STAND: " + r.Why;
            return "would WALK " + r.Forward.ToString("0.0") + " m ahead, " + Math.Abs(r.Right).ToString("0.0") + " m to the " +
                   (r.Right >= 0f ? "right" : "left") + " at " + r.Speed.ToString("0.0") + " m/s: " + r.Why;
        }

        // The command the motion stream would receive (in her own frame, with a short lease).
        public static string CommandJson(Decision r)
        {
            System.Globalization.CultureInfo inv = System.Globalization.CultureInfo.InvariantCulture;   // JSON needs a dot, whatever the PC's region
            if (!r.Walk) return "{\"cmd\":\"stand\",\"lease_s\":" + LeaseSeconds.ToString("0.#", inv) + "}";
            return "{\"cmd\":\"goto\",\"forward\":" + r.Forward.ToString("0.00", inv) + ",\"right\":" + r.Right.ToString("0.00", inv) +
                   ",\"speed\":" + r.Speed.ToString("0.0", inv) + ",\"lease_s\":" + LeaseSeconds.ToString("0.#", inv) + "}";
        }
    }
}
