// =============================================================================
// VaM-RT Senses  v0.1.2
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
        private const string VERSION = "0.1.2";

        // settings (saved with the scene)
        private JSONStorableBool _enabled, _sendToVoxta;
        private JSONStorableStringChooser _slot;
        private JSONStorableFloat _radius, _maxObjects, _interval;
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

        private static readonly string[] IgnoredTypeParts = new string[] { "CoreControl", "Light", "Camera", "Audio", "PluginManager", "SessionPlugin" };

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
                _radius = new JSONStorableFloat("Radius (m)", 6f, 1f, 20f);
                RegisterFloat(_radius);
                _maxObjects = new JSONStorableFloat("Max objects reported", 6f, 1f, 12f);
                RegisterFloat(_maxObjects);
                _interval = new JSONStorableFloat("Min seconds between sends", 3f, 1f, 30f);
                RegisterFloat(_interval);

                _snapshotText = new JSONStorableString("Snapshot", "(waiting for the first reading)");
                _statusText = new JSONStorableString("Status", "");
                _debugText = new JSONStorableString("Debug numbers", "");
                _errorText = new JSONStorableString("Last error", "none");

                _enabled.setCallbackFunction += (bool v) => { if (!v) ClearSlot(); };
                _sendToVoxta.setCallbackFunction += (bool v) => { if (!v) ClearSlot(); else _lastSentText = ""; };
                _slot.setCallbackFunction += (string s) => { ClearSlot(); };

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
            CreateScrollablePopup(_slot, false);
            CreateSlider(_radius, false);
            CreateSlider(_maxObjects, false);
            CreateSlider(_interval, false);

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
            d.LegsWide = spread > 0.55f * scale;

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
                d.UserLooking = gaze < 20f;
                userDebug = "user " + d.UserDistance.ToString("0.0") + " m, angle " + d.UserAngle.ToString("0") + ", gaze off-target " + gaze.ToString("0") + " deg";
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

                SensesLogic.ObjectInfo o = new SensesLogic.ObjectInfo();
                o.Name = clean;
                o.IsPerson = a.type == "Person";
                o.Distance = dist;
                o.Angle = SensesLogic.SignedAngleY(fwd, Flat(p - rootPos));
                o.Sit = sit; o.Surface = surface; o.Look = look;
                found.Add(o);
            }
            found.Sort(delegate (SensesLogic.ObjectInfo x, SensesLogic.ObjectInfo y) { return x.Distance.CompareTo(y.Distance); });
            int max = (int)Math.Round(_maxObjects.val);
            for (int i = 0; i < found.Count && i < max; i++) d.Objects.Add(found[i]);

            _debugText.val = "hip height " + hipH.ToString("0.00") + " m (standing reference " + _standHip.ToString("0.00") + ")\n" +
                             "torso angle " + torso.ToString("0") + " deg, foot spread " + spread.ToString("0.00") + " m\n" +
                             "facing x/z " + fwd.x.ToString("0.00") + " / " + fwd.z.ToString("0.00") + "\n" +
                             userDebug + "\n" +
                             "atoms in range " + found.Count + ", reported " + d.Objects.Count;

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
            return "Voxta: found (" + p.containingAtom.name + " > " + p.name + "), context slot " + _slot.val + ".";
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

        public static string ShortDirection(float a)
        {
            float abs = Math.Abs(a);
            string side = a >= 0f ? "right" : "left";
            if (abs < 22.5f) return "ahead";
            if (abs < 67.5f) return "ahead-" + side;
            if (abs < 112.5f) return side;
            if (abs < 157.5f) return "behind-" + side;
            return "behind";
        }

        // used as "{{ user }} is <phrase>"
        public static string DistancePhrase(float d)
        {
            if (d < 0.5f) return "very close to " + CHAR;
            if (d < 1.0f) return "within arm's reach of " + CHAR;
            if (d < 2.0f) return "close to " + CHAR;
            return "about " + Math.Round(d).ToString("0") + " m from " + CHAR;
        }

        // used inside parentheses for objects
        public static string DistanceShort(float d)
        {
            if (d < 0.5f) return "touching distance";
            if (d < 1.0f) return "within reach";
            if (d < 2.0f) return "close";
            return Math.Round(d).ToString("0") + " m away";
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
            lines.Add("Physical situation of " + CHAR + " (live background information, not something to read out):");

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

            if (d.HasUser)
            {
                string u = "- " + USER + " is " + DistancePhrase(d.UserDistance) + ", " + Direction(d.UserAngle);
                if (d.UserLooking) u += ", and is looking at " + CHAR;
                lines.Add(u + ".");
            }

            if (d.Objects.Count == 0)
            {
                lines.Add("- Nothing else is nearby.");
            }
            else
            {
                List<string> items = new List<string>();
                foreach (ObjectInfo o in d.Objects)
                {
                    string detail = DistanceShort(o.Distance) + ", " + ShortDirection(o.Angle);
                    if (o.Sit) detail += ", can be sat on";
                    if (o.Surface) detail += ", a surface";
                    if (o.Look) detail += ", worth looking at";
                    string label = o.IsPerson ? "another person, " + o.Name : WithArticle(o.Name);
                    items.Add(label + " (" + detail + ")");
                }
                lines.Add("- Nearby: " + string.Join("; ", items.ToArray()) + ".");
            }
            return string.Join("\n", lines.ToArray());
        }
    }
}
