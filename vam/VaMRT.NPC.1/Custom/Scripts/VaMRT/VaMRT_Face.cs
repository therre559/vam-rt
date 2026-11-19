using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using UnityEngine;

// VaMRT_Face 0.8 - her face and her eyes, driven by the mood script (Voxta) with no hand-made morph mapping.
//
//   Mood  (String storable "Mood",  e.g. "w=0.3 i=0 e=0.5 c=0.8 h=0 a=0.1 st=engage") -> a resting expression that is always there:
//          warmth smiles, irritation frowns, hurt sags, arousal parts the lips and softens the eyes, energy sets how lively it all is.
//   Cue   (String storable "Face Cue", e.g. "smiles warmly | bites her lip") -> a passing expression over the resting one, 1-4 s.
//          These come from her own *stage directions*; the model does not write them every turn, and it does not have to.
//   Gaze  her eyes look at the player (the camera, desktop or VR) with glances away; the head turns too, within limits, when
//          "Drive head" is on (then set "Skip Neck and Head" ON in the BVH Player, so the two do not fight).
//   Life  blinks are VaM's own (Auto Behaviours); this adds saccades, brow flickers and small smile changes, scaled by energy.
//
// The morphs it uses are the expression morphs every Genesis 2 character has (Smile Full Face, Frown, Flirting, Desire, Surprise ...),
// looked up by name; the status box lists any it could not find. Remove E-Motion from the atom first - two plugins writing the
// same morphs is a fight the character loses.
namespace VaMRT
{
    public class VaMRT_Face : MVRScript
    {
        // ---- storables set from Voxta (mood script v42) ----
        JSONStorableString _mood, _cue, _status, _debug;
        JSONStorableBool _speaking, _userSpeaking;
        JSONStorableBool _on, _driveEyes, _driveHead, _life;
        JSONStorableFloat _expressionAmount, _headWeight, _headSpeed, _glanceRate, _lookAtPlayer;

        // ---- mood state ----
        float w = 0.25f, irr = 0f, en = 0.5f, com = 0.8f, hurt = 0f, ar = 0.1f;
        string stance = "engage";
        float _moodT = -1e9f;

        // ---- morphs ----
        GenerateDAZMorphsControlUI _mc;
        readonly Dictionary<string, DAZMorph> _m = new Dictionary<string, DAZMorph>();
        readonly Dictionary<string, float> _cur = new Dictionary<string, float>();
        readonly Dictionary<string, float> _target = new Dictionary<string, float>();
        readonly List<string> _missing = new List<string>();
        readonly List<string> _keys = new List<string>();          // the morphs found, in order (VaM's compiler cannot enumerate a Dictionary)
        // a logical name -> the display names to try, in order. Ava's character carries AshAuryn's expression packs ("AA ..."), which are
        // complete, natural faces; the plain Genesis 2 names come after them for a character that lacks the packs.
        static readonly Dictionary<string, string[]> ALT = new Dictionary<string, string[]>() {
            // Lynn's pick on Ava (19 Nov): Parted Smile 1.0 with Patient Smile 0.5 - "smile2" always rides at half of "smile"
            { "smile", new[] { "asco - Parted Smile", "asco - Lovely Smile", "AA 2022 Smile Subtle ", "Smile Full Face", "Mouth Smile" } },
            { "smile2", new[] { "asco - Patient Smile", "asco - Closed Smile" } },
            { "smile_open", new[] { "asco - Joyful Smile", "asco - Open Smile", "Timbo Amazing Smile v10", "AA 2022 Big Smile", "Smile Open Full Face" } },
            { "smile_simple", new[] { "asco - Lovely Smile", "asco - Closed Smile", "AA 2022 Smile Confident", "Mouth Smile Simple" } },
            { "smirk", new[] { "AA 2022 Cocky Smile", "AA Brat 1", "Mouth Smile Simple Left" } },
            { "laugh", new[] { "AA 2022 Laughter Stifled", "AA 2022 Cheese Smile", "Smile Open Full Face" } },
            { "cute", new[] { "AA Cute 1", "AA Cute 2", "Pleased" } },
            { "silly", new[] { "AA - Silly 1", "AA 2022 Cheese Smile 2" } },
            { "pleased", new[] { "AA Cute 3", "AA - Smile 2", "Pleased" } },
            { "frown", new[] { "AA 2022 Unhappy", "Frown" } },
            { "displeased", new[] { "AA Displeased ", "AA Displeased", "AA - Annoyed 1", "Frown" } },
            { "annoyed", new[] { "AA - Annoyed 1", "AA 2022 Mistrust" } },
            { "brow_down", new[] { "Brow Down", "AAbrowlow", "Brow Inner Down" } },
            { "brow_up", new[] { "Brow Up", "AAbrowhigh", "Brow Inner Up" } },
            { "brow_up_l", new[] { "Brow Up Left", "AAbrowraiseL", "Brow Outer Up Left", "Brow Up" } },
            { "brow_up_r", new[] { "Brow Up Right", "AAbrowraiseR", "Brow Outer Up Right" } },
            { "flirt", new[] { "AA - Sexy 1", "Flirting" } },
            { "desire", new[] { "AA - Sexy 2", "Desire" } },
            { "pleasure_mm", new[] { "AA Pleasure MM 1", "AA Pleasure HU 1" } },
            { "pleasure_ah", new[] { "AA Pleasure AH 1", "AA Pleasure OH 1", "Mouth Open" } },
            { "excitement", new[] { "AA Excitement 1" } },
            { "sad", new[] { "AA - Sad 1", "Sad" } },
            { "anger", new[] { "AA 2022 Anger 1 Redone", "AA - Anger 1", "Anger" } },
            { "fear", new[] { "AA Fear 1", "Fear" } },
            { "nervous", new[] { "AA 2022 Nervous", "AA - Worry 1", "Fear" } },
            { "worry", new[] { "AA - Worry 1", "AA Trepidation 1 Rig Fix" } },
            { "surprise", new[] { "AA Surprise 1", "Surprise" } },
            { "happy_surprise", new[] { "AA 2022 Happy Surprise", "AA Surprise 1", "Surprise" } },
            { "gasp", new[] { "AA Gasp 1", "Surprise" } },
            { "shock", new[] { "AA Woah 1", "Shock", "Surprise" } },
            { "disgust", new[] { "AA 2022 Disgust", "Disgust" } },
            { "confused", new[] { "AA 2022 Incredulous Redone", "AA - Incredulous", "Confused" } },
            { "suspicious", new[] { "AA Suspicious", "AA 2022 Mistrust", "Concentrate" } },
            { "concentrate", new[] { "Concentrate" } },
            { "pain", new[] { "AA 2022 Pain 1 Redone", "Pain" } },
            { "mouth_open", new[] { "AA Mouth Open 2", "Mouth Open", "Mouth Open Wide" } },
            { "lips_part", new[] { "Lips Part", "Mouth Open" } },
            { "kiss", new[] { "AA Kiss 1 Rig Fix", "AA - Kiss 1", "Lips Pucker", "Kiss Lips" } },
            { "pucker", new[] { "Lips Pucker", "AA Kiss 2 Rig Fix" } },
            { "pout", new[] { "AA Pout 1", "Pout", "Lips Pucker" } },
            { "lip_bite", new[] { "Lip Bite", "AA 2022 Cute Lip Bite", "AA Lip Bite 1 Rig Fix" } },
            { "flirting_g2", new[] { "Flirting", "AA - Sexy 1" } },
            { "lip_bite_hot", new[] { "AA 2022 Excited Bite Lip", "AA Lip Bite 2 Rig Fix", "Lip Bite" } },
            { "tongue", new[] { "AA Lick 1", "AA - Tongue 1", "Tongue Out" } },
            { "exhale", new[] { "AA Exhale 1", "AA Gently Blow" } },
            { "eyes_closed", new[] { "AA Eyes Closed 2 Calm", "AA Eyes Closed 1", "Eyes Closed" } },
            { "eyes_closed_l", new[] { "AA Eyes Wink L", "AA Eyes Closed 1 L", "Eyes Closed Left" } },
            { "eyes_closed_r", new[] { "AA Eyes Wink R", "AA Eyes Closed 1 R", "Eyes Closed Right" } },
            { "squint", new[] { "Eyes Squint", "AA_basicsquint1" } },
            { "nose", new[] { "Nose Wrinkle" } },
        };
        static readonly string[] ORDER = { "smile", "smile2", "smile_open", "smile_simple", "smirk", "laugh", "cute", "silly", "pleased", "frown", "displeased", "annoyed",
            "brow_down", "brow_up", "brow_up_l", "brow_up_r", "flirt", "desire", "pleasure_mm", "pleasure_ah", "excitement", "sad", "anger", "fear", "nervous",
            "worry", "surprise", "happy_surprise", "gasp", "shock", "disgust", "confused", "suspicious", "concentrate", "pain", "mouth_open", "lips_part",
            "kiss", "pucker", "pout", "lip_bite", "flirting_g2", "lip_bite_hot", "tongue", "exhale", "eyes_closed", "eyes_closed_l", "eyes_closed_r", "squint", "nose" };

        // ---- cues ----
        class Cue {
            public List<string> mk = new List<string>(); public List<float> mv = new List<float>();
            public float hold, t0, inT = 0.25f, outT = 0.8f; public string gaze; public float tilt; public string name;
            public bool Has(string k) { return mk.IndexOf(k) >= 0; }
            public void Set(string k, float v) { int i = mk.IndexOf(k); if (i < 0) { mk.Add(k); mv.Add(v); } else if (mv[i] < v) mv[i] = v; }
        }
        readonly List<Cue> _cues = new List<Cue>();
        string _lastCueText = "";
        float _lastCueT = -1e9f;

        // ---- gaze / head ----
        FreeControllerV3 _eyeTarget, _head, _chest;
        JSONStorableStringChooser _lookMode;
        string _savedLookMode = null;
        Vector3 _gazeAim;                  // where the eyes are aimed now (world)
        Vector3 _saccade;                  // small offset, re-rolled often
        float _saccadeT, _glanceUntil = -1f, _nextGlance = 4f, _userSpokeT = -1e9f;
        string _glanceKind = "";
        float _glanceSide = 1f;
        Quaternion _headRot;
        bool _headInit = false;
        float _microT = 2f;
        string _microKey = null; float _microVal = 0f;
        float _microUntil = -1f;
        float _tiltNow = 0f, _tiltTarget = 0f;
        float _nodPhase = 0f;
        System.Random _rng = new System.Random();

        public override void Init()
        {
            try
            {
                if (containingAtom == null || containingAtom.type != "Person") { SuperController.LogError("VaMRT_Face: put this on a Person atom"); return; }
                _on = new JSONStorableBool("On", true); RegisterBool(_on); CreateToggle(_on);
                _driveEyes = new JSONStorableBool("Drive eyes (look at the player, glances)", true); RegisterBool(_driveEyes); CreateToggle(_driveEyes);
                _driveHead = new JSONStorableBool("Drive head (needs BVH Player: Skip Neck and Head ON)", true); RegisterBool(_driveHead); CreateToggle(_driveHead);
                _life = new JSONStorableBool("Small movements (brows, smile, saccades)", true); RegisterBool(_life); CreateToggle(_life);
                _expressionAmount = new JSONStorableFloat("Expression amount", 1.2f, 0f, 2f, true, true); RegisterFloat(_expressionAmount); CreateSlider(_expressionAmount);
                _headWeight = new JSONStorableFloat("Head turn amount", 0.7f, 0f, 1f, true, true); RegisterFloat(_headWeight); CreateSlider(_headWeight);
                _headSpeed = new JSONStorableFloat("Head turn speed", 3.0f, 0.5f, 10f, true, true); RegisterFloat(_headSpeed); CreateSlider(_headSpeed);
                _lookAtPlayer = new JSONStorableFloat("Looks at the player (share of the time)", 0.75f, 0f, 1f, true, true); RegisterFloat(_lookAtPlayer); CreateSlider(_lookAtPlayer);
                _glanceRate = new JSONStorableFloat("Glances away every (s)", 7f, 2f, 30f, true, true); RegisterFloat(_glanceRate); CreateSlider(_glanceRate);

                _mood = new JSONStorableString("Mood", "", OnMood); RegisterString(_mood);
                _cue = new JSONStorableString("Face Cue", "", OnCue); RegisterString(_cue);
                _speaking = new JSONStorableBool("Speaking", false); RegisterBool(_speaking);
                _userSpeaking = new JSONStorableBool("User Speaking", false, OnUserSpeaking); RegisterBool(_userSpeaking);
                _status = new JSONStorableString("Status", ""); CreateTextField(_status, true).height = 260f;
                _debug = new JSONStorableString("Now", ""); CreateTextField(_debug, true).height = 200f;

                // test buttons (a text box in a plugin panel cannot be typed into)
                CreateButton("Test cue: smiles warmly").button.onClick.AddListener(() => { OnCue("smiles warmly"); });
                CreateButton("Test cue: bites her lip, looks away", true).button.onClick.AddListener(() => { OnCue("bites her lip | looks away"); });
                CreateButton("Test cue: frowns").button.onClick.AddListener(() => { OnCue("frowns"); });
                CreateButton("Test cue: winks", true).button.onClick.AddListener(() => { OnCue("winks"); });
                CreateButton("Test mood: warm").button.onClick.AddListener(() => { OnMood("w=0.8 i=0 e=0.6 c=0.9 h=0 a=0.2 st=engage"); });
                CreateButton("Test mood: cross", true).button.onClick.AddListener(() => { OnMood("w=-0.3 i=0.8 e=0.5 c=0.5 h=0.1 a=0 st=guarded"); });
                CreateButton("Test mood: aroused").button.onClick.AddListener(() => { OnMood("w=0.6 i=0 e=0.6 c=0.9 h=0 a=0.8 st=playful"); });
                CreateButton("Test mood: reset", true).button.onClick.AddListener(() => { OnMood("w=0.25 i=0 e=0.5 c=0.8 h=0 a=0.1 st=engage"); });
                CreateButton("Write morph names to Saves/PluginData/vamrt_face_morphs.txt").button.onClick.AddListener(() => { DumpMorphNames(); });

                DAZCharacterSelector dcs = containingAtom.GetStorableByID("geometry") as DAZCharacterSelector;
                if (dcs != null) _mc = dcs.morphsControlUI;
                if (_mc == null) { SuperController.LogError("VaMRT_Face: no morph control on this atom"); }
                else for (int i = 0; i < ORDER.Length; i++) Resolve(ORDER[i], ALT[ORDER[i]]);

                _eyeTarget = containingAtom.GetStorableByID("eyeTargetControl") as FreeControllerV3;
                _head = containingAtom.GetStorableByID("headControl") as FreeControllerV3;
                _chest = containingAtom.GetStorableByID("chestControl") as FreeControllerV3;
                JSONStorable eyes = containingAtom.GetStorableByID("Eyes");
                if (eyes != null) { _lookMode = eyes.GetStringChooserJSONParam("lookMode"); if (_lookMode != null) _savedLookMode = _lookMode.val; }
                if (_head != null) { _headRot = _head.transform.rotation; _headInit = true; }
                _gazeAim = CameraPos();
                UpdateStatus();
            }
            catch (Exception e) { SuperController.LogError("VaMRT_Face Init: " + e); }
        }

        readonly List<string> _resolved = new List<string>();    // "smile <- Smile Full Face", for the status box
        readonly Dictionary<string, float> _written = new Dictionary<string, float>();   // what this plugin wrote last frame
        readonly Dictionary<string, int> _fought = new Dictionary<string, int>();        // frames another writer changed it since
        float _fightReportT = 0f;
        string _fightLine = "";
        List<string> _allNames = null;

        List<string> AllNames()
        {
            if (_allNames != null) return _allNames;
            _allNames = new List<string>();
            try { var l = _mc.GetMorphDisplayNames(); if (l != null) for (int i = 0; i < l.Count; i++) _allNames.Add(l[i]); } catch (Exception) { }
            return _allNames;
        }

        void Resolve(string key, string[] names)
        {
            for (int i = 0; i < names.Length; i++)
            {
                DAZMorph m = _mc.GetMorphByDisplayName(names[i]);
                if (m != null) { Found(key, m, names[i]); return; }
            }
            // 0.2: no exact name - look for the closest display name this character has (case-insensitive, by the words of the first alternate)
            List<string> all = AllNames();
            string want = names[0].ToLower();
            string best = null; int bestScore = 0;
            for (int i = 0; i < all.Count; i++)
            {
                string n = all[i].ToLower();
                int score = 0;
                if (n.Length < 4) continue;                                           // "L", "ER", "T" are visemes, never a face
                if (n == want) score = 100;
                else if (n.Contains(want) || want.Contains(n)) score = 60 + (n.Length < want.Length ? 5 : 0);
                else
                {
                    string[] words = want.Split(' ');
                    int hit = 0; for (int w = 0; w < words.Length; w++) if (words[w].Length > 2 && n.Contains(words[w])) hit++;
                    if (hit == words.Length) score = 40; else if (hit > 0 && hit >= words.Length - 1 && words.Length > 1) score = 20;
                }
                if (n.Contains("left") || n.Contains("right")) score -= 15;          // one-sided variants only if nothing else
                if (score > bestScore) { bestScore = score; best = all[i]; }
            }
            if (best != null && bestScore >= 40)
            {
                DAZMorph m = _mc.GetMorphByDisplayName(best);
                if (m != null) { Found(key, m, best + " (closest match)"); return; }
            }
            _missing.Add(key + " (" + string.Join(" / ", names) + ")");
        }

        void Found(string key, DAZMorph m, string shown)
        {
            _m[key] = m; _cur[key] = 0f; _target[key] = 0f; _keys.Add(key); _resolved.Add(key + " <- " + shown);
        }

        // writes every morph display name this character has to Saves/PluginData/vamrt_face_morphs.txt (for tuning the mapping)
        void DumpMorphNames()
        {
            try
            {
                List<string> all = AllNames();
                var sb = new System.Text.StringBuilder();
                sb.Append("VaMRT_Face morph dump: ").Append(all.Count).Append(" morphs\n");
                sb.Append("resolved:\n");
                for (int i = 0; i < _resolved.Count; i++) sb.Append("  ").Append(_resolved[i]).Append("\n");
                sb.Append("missing:\n");
                for (int i = 0; i < _missing.Count; i++) sb.Append("  ").Append(_missing[i]).Append("\n");
                sb.Append("all display names:\n");
                for (int i = 0; i < all.Count; i++) sb.Append(all[i]).Append("\n");
                string path = "Saves/PluginData/vamrt_face_morphs.txt";
                MVR.FileManagementSecure.FileManagerSecure.WriteAllText(path, sb.ToString());
                SuperController.LogMessage("VaMRT_Face: wrote " + path + " (" + all.Count + " morph names)");
            }
            catch (Exception e) { SuperController.LogError("VaMRT_Face: could not write the morph list: " + e.Message); }
        }

        void UpdateStatus()
        {
            string s = "VaMRT_Face 0.8 | faces found " + _keys.Count + " / " + ORDER.Length;
            if (_missing.Count > 0) s += "\nnot on this character: " + string.Join(", ", _missing.ToArray());
            int closest = 0; for (int i = 0; i < _resolved.Count; i++) if (_resolved[i].EndsWith("(closest match)")) closest++;
            if (closest > 0) s += "\n" + closest + " taken by closest name (see the morph names file)";
            s += "\neye target: " + (_eyeTarget != null ? "ok" : "MISSING") + ", head: " + (_head != null ? "ok" : "MISSING") + ", look mode: " + (_lookMode != null ? "ok" : "MISSING");
            if (_fightLine != "") s += "\nOVERWRITTEN by another plugin (Timeline morph track? Voxta expressions?): " + _fightLine;
            s += "\nmood " + (Time.time - _moodT < 600f ? _mood.val : "(none yet - the mood script sends it)") + "\nlast cue: " + (_lastCueText == "" ? "(none)" : _lastCueText);
            _status.val = s;
        }

        // ------------------------------------------------------------------ inputs
        static readonly Regex KV = new Regex(@"([a-z]+)=(-?[0-9.]+|[a-z]+)", RegexOptions.Compiled | RegexOptions.IgnoreCase);
        void OnMood(string v)
        {
            if (string.IsNullOrEmpty(v)) return;
            foreach (Match m in KV.Matches(v))
            {
                string k = m.Groups[1].Value.ToLower(); string val = m.Groups[2].Value; float f;
                bool num = float.TryParse(val, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out f);
                if (k == "w" && num) w = Mathf.Clamp(f, -1f, 1f);
                else if (k == "i" && num) irr = Mathf.Clamp01(f);
                else if (k == "e" && num) en = Mathf.Clamp01(f);
                else if (k == "c" && num) com = Mathf.Clamp01(f);
                else if (k == "h" && num) hurt = Mathf.Clamp01(f);
                else if (k == "a" && num) ar = Mathf.Clamp01(f);
                else if (k == "st") stance = val.ToLower();
            }
            _moodT = Time.time;
            if (_mood.val != v) _mood.valNoCallback = v;
            UpdateStatus();
        }

        void OnUserSpeaking(bool b) { if (b) _userSpokeT = Time.time; }

        // cue text -> passing expressions. Several clauses may come at once ("smiles | bites her lip"); at most two are taken.
        void OnCue(string text)
        {
            if (string.IsNullOrEmpty(text)) return;
            string low = text.ToLower();
            if (low == _lastCueText.ToLower() && Time.time - _lastCueT < 2f) return;
            _lastCueText = text; _lastCueT = Time.time;
            int n = 0;
            foreach (string raw in low.Split('|'))
            {
                string c = raw.Trim();
                if (c.Length == 0) continue;
                Cue cue = CueFor(c);
                if (cue == null) continue;
                cue.t0 = Time.time; cue.name = c;
                _cues.Add(cue);
                if (++n >= 2) break;
            }
            if (_cues.Count > 4) _cues.RemoveRange(0, _cues.Count - 4);
            _cue.valNoCallback = "";
            UpdateStatus();
        }

        static bool Has(string c, string rx) { return Regex.IsMatch(c, rx); }
        Cue CueFor(string c)
        {
            Cue q = new Cue(); q.hold = 2.5f;
            bool any = false;
            Action<string, float> set = (k, v) => { q.Set(k, v); any = true; };
            if (Has(c, @"\b(?:laugh|giggl|chuckl|bursts? out)")) { set("laugh", 0.8f); set("smile_open", 0.3f); q.hold = 2.5f; q.tilt = -6f; }
            else if (Has(c, @"\b(?:grin|beam)")) { set("smile_open", 0.7f); q.hold = 3f; }
            else if (Has(c, @"\bsmirk")) { set("smirk", 0.7f); q.hold = 3f; }
            else if (Has(c, @"\bsmil")) { bool soft = Has(c, @"\b(?:soft|faint|small|slight|shy|gentl|warm)"); set(soft ? "smile" : "smile_simple", soft ? 0.7f : 0.65f); if (!soft) set("smile", 0.3f); q.hold = 3f; }
            if (Has(c, @"\bwink")) { set("eyes_closed_l", 1f); set("smirk", 0.35f); q.hold = 0.45f; q.inT = 0.1f; q.outT = 0.25f; }
            if (Has(c, @"\b(?:bit(?:e|es|ing)|nibbl\w*|chew\w*) (?:on )?(?:her )?(?:lower |bottom )?lip")) { if (Has(c, @"\b(?:hard|excit|hungr|needy)")) set("lip_bite_hot", 0.6f); else { set("lip_bite", 0.5f); set("flirting_g2", 0.25f); } set("smile_simple", 0.45f); set("smile", 0.2f); q.hold = 2.5f; }   // tuned at Expression amount 1.2 (19 Nov): any more lip bite shows teeth
            if (Has(c, @"\blick\w* (?:her )?lips")) { set("tongue", 0.6f); q.hold = 1.2f; }
            if (Has(c, @"\b(?:frown|scowl|glare|glower|narrow\w* (?:her )?eyes|scrunch)")) { set(Has(c, @"glare|glower") ? "anger" : "displeased", 0.65f); if (Has(c, @"narrow")) set("squint", 0.5f); q.hold = 2.5f; }
            if (Has(c, @"\bpout")) { set("pout", 0.75f); q.hold = 2.5f; }
            if (Has(c, @"\b(?:rais|arch|cock|lift)\w* (?:an |a |her |one )?(?:eye)?brow")) { set("brow_up_l", 0.9f); set("suspicious", 0.25f); q.hold = 2f; q.tilt = 4f; }
            if (Has(c, @"\broll\w* (?:her )?eyes")) { q.gaze = "up"; set("annoyed", 0.4f); q.hold = 0.8f; }
            if (Has(c, @"\b(?:look|glanc|gaz|turn|avert)\w* (?:away|aside|down|off|elsewhere|at the (?:floor|ground))|avoids? (?:his|your) (?:eyes|gaze)|casts? (?:her )?eyes down")) { q.gaze = Has(c, @"down|floor|ground") ? "down" : "away"; q.hold = 2.2f; }
            if (Has(c, @"\b(?:gasp|catch\w* (?:her )?breath|breath catches)")) { set("gasp", 0.75f); q.hold = 1.4f; q.inT = 0.1f; }
            else if (Has(c, @"\b(?:surpris|startl|eyes (?:go |grow |open )?wide|widen)")) { set(w > 0.2f ? "happy_surprise" : "surprise", 0.75f); q.hold = 1.8f; q.inT = 0.12f; }
            if (Has(c, @"\b(?:shock|stunn|jaw drop)")) { set("shock", 0.75f); q.hold = 2f; }
            if (Has(c, @"\b(?:blush|flush|shy|bashful|sheepish|cheeks (?:go|turn|burn))")) { set("cute", 0.6f); if (q.gaze == null) q.gaze = "down"; q.hold = 2f; }
            if (Has(c, @"\bsigh")) { set("exhale", 0.6f); set("eyes_closed", 0.4f); q.hold = 1.1f; }
            if (Has(c, @"\b(?:clos|shut)\w* (?:her )?eyes|eyes (?:flutter|drift) (?:closed|shut)")) { set("eyes_closed", 1f); q.hold = 3f; }
            if (Has(c, @"\b(?:moan|whimper|mewl|shudder|trembl|gasps? softly|cries? out)")) { set("pleasure_ah", 0.6f); set("eyes_closed", 0.5f); q.hold = 2f; }
            if (Has(c, @"\b(?:hum|purr|mm+)\b")) { set("pleasure_mm", 0.6f); set("eyes_closed", 0.3f); q.hold = 1.8f; }
            if (Has(c, @"\b(?:pleased|content|satisf|smug)")) { set(Has(c, @"smug") ? "smirk" : "pleased", 0.6f); q.hold = 3f; }
            if (Has(c, @"\b(?:sad|tear|cry|cries|sniff|lip (?:trembl|quiver)|crestfallen|hurt)")) { set("sad", 0.75f); q.hold = 3f; }
            if (Has(c, @"\b(?:disgust|wrinkl\w* (?:her )?nose|grimac|revuls)")) { set("disgust", 0.7f); q.hold = 2f; }
            if (Has(c, @"\b(?:confus|puzzl|perplex|quizzical|incredul|tilt\w* (?:her )?head)")) { set("confused", 0.6f); q.hold = 2.5f; q.tilt = 10f; }
            if (Has(c, @"\b(?:concentrat|focus|thought|ponder|consider|hesitat|chew\w* (?:on )?(?:that|it)|studies|scrutin)")) { set("concentrate", 0.5f); if (q.gaze == null && Has(c, @"thought|ponder")) q.gaze = "up"; q.hold = 2.5f; }
            if (Has(c, @"\b(?:suspic|wary|mistrust|eyes? (?:him|you) warily|sceptic|skeptic|doubt)")) { set("suspicious", 0.65f); q.hold = 2.5f; }
            if (Has(c, @"\b(?:desire|hungr|lust|sultry|smolder|heat in her|wanting|needy|eyes (?:dark|heavy|hooded))")) { set("desire", 0.5f); set("eyes_closed", 0.3f); q.hold = 3f; }
            if (Has(c, @"\b(?:flirt|coy|coquett|teas|mischie|playful|wicked (?:smile|grin|look)|brat)")) { set(Has(c, @"brat|mischie|wicked") ? "smirk" : "flirt", 0.6f); q.hold = 3f; }
            if (Has(c, @"\b(?:silly|goof|tongue out|sticks? (?:out )?(?:her )?tongue|crosses? (?:her )?eyes)")) { set("silly", 0.7f); q.hold = 2f; }
            if (Has(c, @"\b(?:excit|thrill|delight|lights? up|eager)")) { set("excitement", 0.6f); q.hold = 2.5f; }
            if (Has(c, @"\b(?:angr|anger|fur(?:y|ious)|rage|snap|snarl|seeth|clench\w* (?:her )?jaw|grit\w* (?:her )?teeth)")) { set("anger", 0.75f); q.hold = 3f; }
            if (Has(c, @"\b(?:annoy|irritat|huff|exasperat|tut)")) { set("annoyed", 0.65f); q.hold = 2.5f; }
            if (Has(c, @"\b(?:fear|afraid|scared|terrif|frighten)")) { set("fear", 0.6f); q.hold = 2.5f; }
            if (Has(c, @"\b(?:nervous|anxious|worr|uneas|fidget|swallow\w* hard)")) { set("nervous", 0.6f); q.hold = 2.5f; }
            if (Has(c, @"\b(?:pain|winc|flinch|ouch|hiss\w* (?:in|through))")) { set("pain", 0.6f); q.hold = 1.5f; q.inT = 0.1f; }
            if (Has(c, @"\b(?:kiss|pucker|blows? (?:him |you )?a kiss)") && !Has(c, @"\bkiss(?:es|ed|ing)? (?:him|you|his)")) { set("kiss", 0.75f); q.hold = 1.3f; }
            if (Has(c, @"\b(?:nod)")) { q.tilt = 0f; any = true; q.hold = 1.2f; q.gaze = "player"; }
            if (Has(c, @"\b(?:lock\w* eyes|meets? (?:his|your) (?:eyes|gaze)|stares? (?:at|into)|looks? (?:him|you) (?:in the eye|up and down|over)|holds? (?:his|your) gaze)")) { q.gaze = "player"; any = true; q.hold = 3f; }
            return any || q.gaze != null ? q : null;
        }

        // ------------------------------------------------------------------ per frame
        public void Update()
        {
            try
            {
                if (_on == null || !_on.val || _mc == null) return;
                float dt = Time.deltaTime, now = Time.time;
                // 1. the resting expression from the mood (AshAuryn expressions are whole faces: small weights, and they cross-fade)
                for (int i = 0; i < _keys.Count; i++) _target[_keys[i]] = 0f;
                float amp = _expressionAmount.val;
                float wp = Mathf.Max(0f, w), live = 0.6f + 0.8f * en;
                float warm = Mathf.Max(0f, 0.15f + 0.6f * wp - 0.6f * irr - 0.5f * hurt);
                Add("smile", warm * 0.7f * live);                                     // Smile Subtle
                Add("smile_simple", (warm - 0.35f) * 0.5f * live);                    // Smile Confident once she is really warm
                Add("cute", 0.25f * wp * com);
                Add("smile_open", 0.3f * wp * Mathf.Max(0f, en - 0.6f) / 0.4f);
                // arousal: Sexy 1 first, heavy lids, a closed-mouth "mm" - never the open-mouth faces at rest
                float arz = Mathf.Max(0f, ar - 0.3f) / 0.7f;
                Add("flirt", 0.45f * arz * (w > -0.2f ? 1f : 0.4f));
                Add("pleasure_mm", 0.3f * Mathf.Max(0f, ar - 0.55f) / 0.45f);
                Add("desire", 0.25f * Mathf.Max(0f, ar - 0.7f) / 0.3f);
                Add("eyes_closed", 0.25f * arz);
                Add("lips_part", 0.15f * Mathf.Max(0f, ar - 0.5f) / 0.5f);
                // irritation, hurt, unease
                Add("displeased", 0.55f * irr - 0.2f * wp);
                Add("anger", irr > 0.65f ? 0.5f * (irr - 0.65f) / 0.35f : 0f);
                Add("sad", 0.55f * hurt - 0.3f * wp);
                Add("nervous", 0.35f * (1f - com) + 0.15f * hurt);
                Add("suspicious", stance == "guarded" ? 0.25f : (stance == "withdrawn" ? 0.12f : 0f));
                Add("squint", 0.1f * irr);
                // 2. small movements
                if (_life.val)
                {
                    if (now > _microT)
                    {
                        _microKey = null; _microVal = 0f;
                        int pick = _rng.Next(6);
                        float a = (0.5f + en) * 0.5f;
                        if (pick == 0) { _microKey = "brow_up"; _microVal = 0.2f * a; }
                        else if (pick == 1) { _microKey = "smile"; _microVal = 0.15f * a * (w > -0.2f ? 1f : 0f); }
                        else if (pick == 2) { _microKey = "brow_up_l"; _microVal = 0.25f * a; }
                        else if (pick == 3) { _microKey = "squint"; _microVal = 0.12f * a; }
                        else if (pick == 4) { _microKey = "lips_part"; _microVal = 0.1f * a; }
                        else _tiltTarget = (float)(_rng.NextDouble() * 8.0 - 4.0);
                        _microUntil = now + 0.6f + (float)_rng.NextDouble() * 1.2f;
                        _microT = now + 3f + (float)_rng.NextDouble() * 6f / Mathf.Max(0.3f, live);
                    }
                    if (now < _microUntil && _microKey != null) Add(_microKey, _microVal);
                    if (_speaking.val) { _nodPhase += dt * 2.2f; Add("brow_up", 0.12f + 0.1f * Mathf.Sin(_nodPhase * 1.7f)); }
                }
                // 3. cues over the top
                string gazeCue = null; float tiltCue = 0f;
                for (int i = _cues.Count - 1; i >= 0; i--)
                {
                    Cue q = _cues[i];
                    float t = now - q.t0, env;
                    if (t < q.inT) env = t / q.inT;
                    else if (t < q.inT + q.hold) env = 1f;
                    else if (t < q.inT + q.hold + q.outT) env = 1f - (t - q.inT - q.hold) / q.outT;
                    else { _cues.RemoveAt(i); continue; }
                    env = env * env * (3f - 2f * env);
                    // a cross cue takes the resting smile away while it lasts, and a smile takes the resting frown away
                    bool neg = false, pos = false;
                    for (int j = 0; j < q.mk.Count; j++) { if (Array.IndexOf(NEG, q.mk[j]) >= 0) neg = true; if (Array.IndexOf(POS, q.mk[j]) >= 0) pos = true; }
                    if (neg) Damp(POS, 1f - 0.9f * env);
                    if (pos && !neg) Damp(NEG, 1f - 0.9f * env);
                    for (int j = 0; j < q.mk.Count; j++) Blend(q.mk[j], q.mv[j] * env);
                    if (q.gaze != null && env > 0.5f) gazeCue = q.gaze;
                    if (q.tilt != 0f) tiltCue += q.tilt * env;
                }
                // the second half of the smile pair
                if (_target.ContainsKey("smile2") && _target.ContainsKey("smile")) _target["smile2"] = Mathf.Max(_target["smile2"], 0.5f * _target["smile"]);
                // 4. write the morphs, smoothed
                float k1 = 1f - Mathf.Exp(-dt * 7f);
                for (int i = 0; i < _keys.Count; i++)
                {
                    string key = _keys[i];
                    // did something else (Timeline, Voxta's own expressions, another face plugin) move this morph since we set it?
                    float wrote;
                    if (_written.TryGetValue(key, out wrote) && Mathf.Abs(_m[key].morphValue - wrote) > 0.03f && Mathf.Abs(wrote) > 0.05f)
                        _fought[key] = (_fought.ContainsKey(key) ? _fought[key] : 0) + 1;
                    float tgt = Mathf.Clamp(_target[key] * amp, -0.2f, 1.5f);     // a few looks want a morph past 1 (the lip-bite smile at 1.25)
                    float c = _cur[key] + (tgt - _cur[key]) * k1;
                    _cur[key] = c;
                    _m[key].morphValue = c;
                    _written[key] = c;
                }
                if (now > _fightReportT)
                {
                    _fightReportT = now + 2f;
                    string f = "";
                    for (int i = 0; i < _keys.Count; i++) if (_fought.ContainsKey(_keys[i]) && _fought[_keys[i]] > 20) f += (f == "" ? "" : ", ") + _keys[i];
                    if (f != _fightLine) { _fightLine = f; UpdateStatus(); }
                }
                // 5. eyes and head
                Gaze(dt, now, gazeCue, tiltCue);
                if (Time.frameCount % 15 == 0) _debug.val = DebugLine(gazeCue);
            }
            catch (Exception e) { if (Time.frameCount % 300 == 0) SuperController.LogError("VaMRT_Face Update: " + e); }
        }

        void Add(string key, float v) { if (!_target.ContainsKey(key) || v <= 0f) return; _target[key] = _target[key] + v; }
        void Blend(string key, float v) { if (!_target.ContainsKey(key)) return; if (v > _target[key]) _target[key] = v; }
        static readonly string[] NEG = { "frown", "displeased", "annoyed", "anger", "sad", "disgust", "fear", "nervous", "worry", "shock", "suspicious", "concentrate", "brow_down", "pain" };
        static readonly string[] POS = { "smile", "smile2", "smile_open", "smile_simple", "smirk", "laugh", "cute", "silly", "pleased", "flirt", "excitement" };
        void Damp(string[] keys, float f) { for (int i = 0; i < keys.Length; i++) if (_target.ContainsKey(keys[i])) _target[keys[i]] = _target[keys[i]] * f; }

        Vector3 CameraPos()
        {
            var ct = SuperController.singleton.centerCameraTarget;
            Camera cam = ct != null ? ct.targetCamera : null;
            if (cam != null) return cam.transform.position;
            return _head != null ? _head.transform.position + _head.transform.forward * 2f : Vector3.forward * 2f;
        }

        void Gaze(float dt, float now, string gazeCue, float tiltCue)
        {
            Vector3 headPos = _head != null ? _head.transform.position : containingAtom.transform.position + Vector3.up * 1.6f;
            Vector3 player = CameraPos();
            Vector3 toPlayer = player - headPos;
            // the mood decides how much eye contact there is; a cue overrides for its duration
            bool avoid = com < 0.45f || irr > 0.6f || hurt > 0.5f;
            float share = _lookAtPlayer.val * (avoid ? 0.4f : 1f);
            if (_speaking.val || now - _userSpokeT < 4f) share = Mathf.Max(share, avoid ? 0.6f : 0.95f);
            if (now > _nextGlance && gazeCue == null)
            {
                bool away = (float)_rng.NextDouble() > share;
                if (away)
                {
                    _glanceKind = _rng.Next(3) == 0 ? "down" : "away";
                    _glanceSide = _rng.Next(2) == 0 ? 1f : -1f;
                    _glanceUntil = now + 0.6f + (float)_rng.NextDouble() * (avoid ? 2.5f : 1.4f);
                }
                _nextGlance = now + _glanceRate.val * (0.5f + (float)_rng.NextDouble()) * (avoid ? 0.6f : 1f);
            }
            string kind = gazeCue ?? (now < _glanceUntil ? _glanceKind : "player");
            Vector3 aim;
            Vector3 side = Vector3.Cross(Vector3.up, toPlayer.normalized);
            if (kind == "down") aim = headPos + toPlayer.normalized * 1.2f + Vector3.down * 0.9f + side * 0.3f;
            else if (kind == "up") aim = headPos + toPlayer.normalized * 1.0f + Vector3.up * 0.9f + side * 0.4f;
            else if (kind == "away") aim = headPos + toPlayer.normalized * 1.5f + side * 1.2f * _glanceSide + Vector3.up * 0.1f;
            else aim = player;
            if (now > _saccadeT) { _saccade = new Vector3((float)_rng.NextDouble() - 0.5f, (float)_rng.NextDouble() - 0.5f, 0f) * 0.06f; _saccadeT = now + 0.25f + (float)_rng.NextDouble() * 1.2f; }
            float ke = 1f - Mathf.Exp(-dt * 12f);
            _gazeAim += (aim + _saccade * Mathf.Max(0.5f, toPlayer.magnitude) - _gazeAim) * ke;
            if (_driveEyes.val && _eyeTarget != null)
            {
                if (_lookMode != null && _lookMode.val != "Target") _lookMode.val = "Target";
                _eyeTarget.transform.position = _gazeAim;
            }
            // the head follows the eyes part of the way, within what a neck can do, measured against the chest
            if (_driveHead.val && _head != null && _headInit)
            {
                Transform chest = _chest != null ? _chest.transform : containingAtom.transform;
                Vector3 dir = (_gazeAim - headPos).normalized;
                Vector3 local = Quaternion.Inverse(chest.rotation) * dir;
                float yaw = Mathf.Atan2(local.x, local.z) * Mathf.Rad2Deg;
                float pitch = -Mathf.Asin(Mathf.Clamp(local.y, -1f, 1f)) * Mathf.Rad2Deg;
                float wgt = _headWeight.val * (kind == "player" ? 1f : 0.5f);
                yaw = Mathf.Clamp(yaw * wgt, -60f, 60f);
                pitch = Mathf.Clamp(pitch * wgt, -25f, 30f);
                _tiltNow += (_tiltTarget + tiltCue - _tiltNow) * (1f - Mathf.Exp(-dt * 2f));
                if (_rng.Next(600) == 0) _tiltTarget = 0f;
                float nod = _speaking.val && _life.val ? 2.5f * Mathf.Sin(_nodPhase) : 0f;
                Quaternion want = chest.rotation * Quaternion.Euler(pitch + nod, yaw, _tiltNow);
                float ks = 1f - Mathf.Exp(-dt * _headSpeed.val);
                _headRot = Quaternion.Slerp(_headRot, want, ks);
                if (_head.currentRotationState != FreeControllerV3.RotationState.On) _head.currentRotationState = FreeControllerV3.RotationState.On;
                _head.transform.rotation = _headRot;
            }
        }

        string DebugLine(string gazeCue)
        {
            string top = "";
            float best = 0.05f;
            for (int i = 0; i < _keys.Count; i++) if (_cur[_keys[i]] > best) { best = _cur[_keys[i]]; top = _keys[i]; }
            string all = "";
            for (int i = 0; i < _keys.Count; i++) if (_cur[_keys[i]] > 0.05f) all += _keys[i] + " " + _cur[_keys[i]].ToString("0.00") + "  ";
            return "stance " + stance + "  w " + w.ToString("0.00") + " i " + irr.ToString("0.00") + " e " + en.ToString("0.00") + " c " + com.ToString("0.00") + " h " + hurt.ToString("0.00") + " a " + ar.ToString("0.00")
                 + "\nstrongest: " + (top == "" ? "neutral" : top) + "\n" + all
                 + "\ncues active: " + _cues.Count + (gazeCue != null ? ", gaze cue " + gazeCue : "") + "  speaking " + (_speaking.val ? "yes" : "no");
        }

        public void OnDisable() { Release(); }
        public void OnDestroy() { Release(); }
        void Release()
        {
            try
            {
                for (int i = 0; i < _keys.Count; i++) _m[_keys[i]].morphValue = 0f;
                if (_lookMode != null && _savedLookMode != null) _lookMode.val = _savedLookMode;
            }
            catch (Exception) { }
        }
    }
}
