using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System;
using UnityEngine;
using UnityEngine.Playables;
using UnityEngine.Animations;
using SimpleJSON;

namespace ElkVR {

/*
    BVH Player,

        Biovision Hierarchical Data file "importer". This plugin will load a bvh file and allow you to play it on a character within VaM.
        It also has a "bake" function that saves the animation data into the scene.

    Version: 1.1.3
    Author: ElkVR, VRAdultFun
    License: Creative Commons Attribution - https://creativecommons.org/licenses/by/3.0/
    Changelog:
     * 0.9.0 Initial release
     * 0.9.1 Bugfixes
      - Male support
      - Rotation order support
      - More translation modes (exposed in UI)
      - pause simulation when scrubbing/looping
      - don't play animation after baking
     * 1.0.0 Smooth
      - Additional bones
      - Interpolate animation
      - Ping pong
      - Remember previous folder
	 * 1.1.0 VRAdultFun
	  - Added Adjustment sliders for shoulders, arms, hands, chest, abdomen, head and neck
	  - Added Joint auto config
	 * 1.1.1 VRAdultFun
	  - Added Skip T Pose option
	  - Added Joint Hold slider
	  - Fixed issue with Baking caused by latest VAM update
	 * 1.1.2 VRAdultFun
	  - Added Elbow rotation control
	  - Modified Abdomen rotation to also effect the pelvis
	  - Added option to disable head and neck playback. Good for plugins like E-Motion
	 * 1.1.3 VRAdultFun
	  - Improved UI and split into sections for easier access
	  - Tweaked default custom hold strengths
	  - Added Variable playback speed based on proximity
	  - Split Hold strength into body, arms, legs, ankles and wrists with seperate sliders for Position and Rotation
	  - Added Custom Physics weight options
	 * Modified by the VaM-RT project (changes to ElkVR/VRAdultFun 1.1.3, see git history for details):
	  - Watch File + Auto Reload of a BVH that another program keeps rewriting
	  - Chain Continuous playback with Chunk Blend between files, In Place mode, Re-center
	  - Motion Request relay (writes a request file for the external motion server)
	*/

public class BVHPlayer : MVRScript {

    Dictionary<string, FreeControllerV3> controllerMap;
    Dictionary<string, MotionAnimationControl> macMap;
		private static Atom person;
        private static FreeControllerV3 personController;
        private static FreeControllerV3 lShoulderController;
        private static FreeControllerV3 rShoulderController;
        private static FreeControllerV3 lArmController;
        private static FreeControllerV3 rArmController;
        private static FreeControllerV3 lElbowController;
        private static FreeControllerV3 rElbowController;
        private static FreeControllerV3 lHandController;
        private static FreeControllerV3 rHandController;
        private static FreeControllerV3 abdomenController;
        private static FreeControllerV3 abdomenLowerController;
        private static FreeControllerV3 pelvisController;
        private static FreeControllerV3 hipController;
        private static FreeControllerV3 chestController;
        private static FreeControllerV3 neckController;
        private static FreeControllerV3 headController;
        private static FreeControllerV3 lBreastController;
        private static FreeControllerV3 rBreastController;
        private static FreeControllerV3 lHipController;
        private static FreeControllerV3 rHipController;
        private static FreeControllerV3 lKneeController;
        private static FreeControllerV3 rKneeController;
        private static FreeControllerV3 lFootController;
        private static FreeControllerV3 rFootController;
        private static FreeControllerV3 lToeController;
        private static FreeControllerV3 rToeController;
		
		private static int startFrame = 0;
		
		private static float footbaseheight = -1.0f;
		private static Vector3 basecontrolpos = new Vector3(0.0f,0.0f,0.0f);
		
		protected JSONStorableFloat uishoulderxrotate;
		protected JSONStorableFloat uishoulderzrotate;
		protected JSONStorableFloat uishoulderyrotate;
		protected JSONStorableFloat uiarmxrotate;
		protected JSONStorableFloat uiarmyrotate;
		protected JSONStorableFloat uiarmzrotate;
		protected JSONStorableFloat uielbowxrotate;
		protected JSONStorableFloat uihandxrotate;
		protected JSONStorableFloat uihandyrotate;
		protected JSONStorableFloat uihandzrotate;
		protected JSONStorableFloat uichestxrotate;
		protected JSONStorableFloat uiabdomenxrotate;
		protected JSONStorableFloat uipelvisxrotate;
		protected JSONStorableFloat uineckxrotate;
		protected JSONStorableFloat uiheadxrotate;
		protected JSONStorableFloat uihipxrotate;
		protected JSONStorableFloat uihipyrotate;
		protected JSONStorableFloat uihipzrotate;
		protected JSONStorableFloat uikneexrotate;
		protected JSONStorableFloat uifootxrotate;
		
		private static UIDynamicButton featureButton;
		private static UIDynamicButton jointButton;
		private static UIDynamicButton angleButton;
		protected static bool uiShowingFeatures = false;
		protected static bool uiShowingJointControl = false;
		protected static bool uiShowingAngleControl = false;
		

		protected JSONStorableBool uiconfigjoints;
		protected JSONStorableFloat uihipholdpower;
		protected JSONStorableFloat uijointpower;
		protected JSONStorableFloat uijointdamper;
		protected JSONStorableFloat uijointarmpower;
		protected JSONStorableFloat uijointrotpower;
		protected JSONStorableFloat uijointarmrotpower;
		protected JSONStorableFloat uijointhandrotpower;
		protected JSONStorableFloat uijointfootrotpower;
		protected JSONStorableBool uiskiptpose;
		protected JSONStorableBool uiemotionsupport;
		
		protected JSONStorableBool uicustomweights;
		protected JSONStorableFloat uicustombodyweight;
		protected JSONStorableFloat uicustomarmsweight;
		protected JSONStorableFloat uicustomlegsweight;

		protected JSONStorableBool uikeeponfloor;
		protected JSONStorableFloat uiflooradjustspeed;
		protected JSONStorableFloat uifloorheight;
		protected JSONStorableFloat uipostheightoffset;
		
		protected JSONStorableBool uispeeddist;
		protected JSONStorableFloat uichangespeed;
		protected JSONStorableFloat uiminspeed;
		protected JSONStorableFloat uimindist;
		protected JSONStorableFloat uimaxdist;
		protected JSONStorableBool uiskiphead;
		protected JSONStorableBool uiskiparms;
		protected JSONStorableBool uiskiplegs;
		
		protected JSONStorableStringChooser uifocustarget;
		
		private static Atom target;
        private static FreeControllerV3 targetController;
        private static FreeControllerV3 targetlHandController;
        private static FreeControllerV3 targetrHandController;
        private static FreeControllerV3 targetheadController;
        private static FreeControllerV3 targetpelvisController;
		
		private static float currentSpeed = -1.0f;

		private static Atom currentAtom;
		private static string currentAtomName;
		
		


    Dictionary<string, string> cnameToBname = new Dictionary<string, string>() {
        { "hipControl", "hip" },
        { "headControl", "head" },
        { "chestControl", "chest" },
        { "lHandControl", "lHand" },
        { "rHandControl", "rHand" },
        { "lFootControl", "lFoot" },
        { "rFootControl", "rFoot" },
        { "lKneeControl", "lShin" },
        { "rKneeControl", "rShin" },
        { "neckControl", "neck" },
        { "lElbowControl", "lForeArm" },
        { "rElbowControl", "rForeArm" },
        { "lArmControl", "lShldr" },
        { "rArmControl", "rShldr" },
        // Additional bones
        { "lShoulderControl", "lCollar" },
        { "rShoulderControl", "rCollar" },
        { "abdomenControl", "abdomen" },
        { "abdomen2Control", "abdomen2" },
        { "pelvisControl", "pelvis" },
        { "lThighControl", "lThigh" },
        { "rThighControl", "rThigh" },
        // { "lToeControl", "lToe" },
        // { "rToeControl", "rToe" },
    };

    JSONStorableString uiStatus;
    JSONStorableFloat uiAnimationPos, uiAnimationSpeed;
    Transform shadow = null;

    BvhFile bvh = null;
    float elapsed = 0;
    int frame = 0;
    bool playing = false;
    bool baking = false;
    bool reverse = false;
    bool isUpdating = false;
    bool loopPlay = false;
    bool loopBake = false;
    bool pingpongPlay = false;
    bool pingpongBake = false;
    bool onlyHipTranslation = true;
    bool translationIsDelta = false;
    float frameTime;

    // Apparently we shouldn't use enums because it causes a compiler crash
    const int translationModeOffsetPlusFrame = 0;
    const int translationModeFrameOnly = 1;
    const int translationModeInitialPlusFrameMinusOffset = 2;
    const int translationModeInitialPlusFrameMinusZero = 3;

    int translationMode = translationModeInitialPlusFrameMinusZero;


    void UpdateUI() {
        isUpdating = true;
        uiAnimationPos.SetVal(frame * 100f / bvh.nFrames);
        isUpdating = false;
    }

    void UpdateSpeed(float speed) {
        frameTime = bvh.frameTime / (speed * 0.01f);
    }

    void UpdateStatus() {
        if(bvh == null)
            uiStatus.SetVal("Select BVH File");
        else if(baking)
            uiStatus.SetVal("Recording now...");
        else
            uiStatus.SetVal(string.Format("Loaded {0}. {1} bones. {2} frames. {3} FPS. Duration {4:0.#}s. {5}.", bvh.path, bvh.bones.Length, bvh.nFrames,
                (int)Mathf.Round(1f / bvh.frameTime), bvh.nFrames * bvh.frameTime, bvh.isTranslationLocal ? "Local translation" : "Absolute Translation"));
    }

    string prevFolder = "";

    void UpdatePrevFolder(string path) {
        var parts = path.Split('\\');
        path = path.Substring(0, path.Length - parts[parts.Length - 1].Length);
        prevFolder = path;
        // SuperController.LogMessage("Prev Folder: " + prevFolder);
    }

    public void Load(string path) {
        bvh = new BvhFile(path);
        uiAnimationPos.SetVal(0);
        UpdateStatus();
        UpdateSpeed(uiAnimationSpeed.val);
        UpdatePrevFolder(path);
        // Not using automatic detection anymore, not reliable
        // if(! bvh.isTranslationLocal && tposeBoneOffsets == null) {
        //     // Ensure we have initial position offsets
        //     RecordOffsets();
        //     CreateControllerMap();  // Reset the controllers
        // }
    }

    bool discontinuity = false;

    // ---- Auto-reload / chaining (added for ARDY real-time use) ----
    JSONStorableString uiWatchFile;
    JSONStorableBool uiAutoReload, uiChain, uiChainWorld;
    JSONStorableFloat uiChainSkip;
    JSONStorableString uiWatchStatus;
    JSONStorableBool uiInPlace;
    // Motion requests (e.g. from Voxta): setting "Motion Request" writes a small JSON file that
    // motion_prompter.py --watch turns into an ARDY prompt.
    JSONStorableString uiMotionRequest;
    JSONStorableString uiRequestFile;
    int requestId = 0;
    float requestsOpenAt = 0f;   // ignore the value VaM restores when a scene loads
    string pendingRequest = null;
    JSONStorableString uiPluginIds;
    float pluginIdsTimer = 0f;
    float pendingRequestAt = 0f;
    JSONStorableFloat uiBlendTime;
    // Chunk boundary smoothing (see ActivatePending): the pose that was showing when the last file ended,
    // the offset that hides any mismatch with the next file, and how long that offset has been fading.
    BvhTransform[] blendFrom = null;
    Quaternion[] fadeRot = null;
    Vector3[] fadePos = null;
    float fadeT = 0f;
    int clipsLoaded = 0;
    string lastError = "";
    List<BvhFile> pendingQueue = new List<BvhFile>();
    const int maxQueue = 3;   // if playback falls this far behind, the oldest chunk is dropped
    string lastContent = null;
    float pollTimer = 0f;

    // Poll the watched file. A half-written file throws in the parser; we just retry next poll.
    void PollWatch() {
        if(uiAutoReload == null || !uiAutoReload.val) {
            SetWatchStatus("Auto Reload is OFF");
            return;
        }
        if(string.IsNullOrEmpty(uiWatchFile.val)) {
            SetWatchStatus("Auto Reload is ON, but no Watch File is selected");
            return;
        }
        pollTimer += Time.deltaTime;
        if(pollTimer >= 0.1f) {
            pollTimer = 0f;
            try {
                // ReadFileIntoString is what BvhFile itself uses, so it is known to work in VaM.
                string content = SuperController.singleton.ReadFileIntoString(uiWatchFile.val);
                if(string.IsNullOrEmpty(content))
                    lastError = "watch file is empty or unreadable";
                if(!string.IsNullOrEmpty(content) && content != lastContent) {
                    var nb = new BvhFile(uiWatchFile.val, content);
                    if(nb.nFrames > 0) {
                        lastContent = content;
                        clipsLoaded++;
                        lastError = "";
                        pendingQueue.Add(nb);
                        while(pendingQueue.Count > maxQueue)
                            pendingQueue.RemoveAt(0);
                    }
                }
            }
            catch(Exception e) { lastError = e.Message; /* retry on next poll */ }
        }
        // Swap in at the end of the current clip (or immediately if idle).
        if(pendingQueue.Count > 0 && (bvh == null || !playing || (!reverse && frame >= bvh.nFrames - 1)))
            ActivatePending();

        SetWatchStatus(string.Format("Clips loaded: {0} | queued: {1} | playing: {2}{3}", clipsLoaded, pendingQueue.Count,
            playing ? "yes" : "no", string.IsNullOrEmpty(lastError) ? "" : " | LAST ERROR: " + lastError));
    }

    void SetWatchStatus(string text) {
        text = "[v5.5] storable ID: " + storeId + " | " + text;
        if(uiWatchStatus != null && uiWatchStatus.val != text)
            uiWatchStatus.SetVal(text);
    }

    // Treat wherever the character currently is as the new starting spot. Later clips inherit this
    // (Chain: ARDY World Coords), so the character stays near the origin instead of drifting away.
    // Works with the default translation mode ("Initial + Frame - Frame[0] (CMU)").
    void Recenter() {
        if(bvh == null || bvh.nFrames == 0) {
            SuperController.LogMessage("BVH Player: nothing loaded yet");
            return;
        }
        if(translationMode != translationModeInitialPlusFrameMinusZero) {
            SuperController.LogMessage("BVH Player: Re-center needs the default Translation Mode (Initial + Frame - Frame[0])");
            return;
        }
        var cur = bvh.ReadFrame(Mathf.Clamp(frame, 0, bvh.nFrames - 1));
        foreach(var t in cur) {
            if(t.bone.hasPosition && t.bone.isHipBone) {
                Vector3 z = t.bone.posZero;
                z.x = t.position.x;
                z.z = t.position.z;
                t.bone.posZero = z;
            }
        }
    }

    // Text fields update while you type, so wait until the value has stopped changing.
    void SendMotionRequest(string v) {
        if(string.IsNullOrEmpty(v) || Time.time < requestsOpenAt)
            return;
        pendingRequest = v;
        pendingRequestAt = Time.time + 0.1f;   // text boxes in plugin panels are read-only, so there is no typing to wait out
    }

    // Lists the "plugin#N_Name" IDs on this atom, so you can read the exact name a Voxta trigger must use.
    void UpdatePluginIds() {
        pluginIdsTimer += Time.deltaTime;
        if(pluginIdsTimer < 2f || uiPluginIds == null)
            return;
        pluginIdsTimer = 0f;
        string t = "Plugins on this atom:";
        foreach(string id in containingAtom.GetStorableIDs()) {
            if(id.StartsWith("plugin#"))
                t += "\n" + id;
        }
        if(uiPluginIds.val != t)
            uiPluginIds.SetVal(t);
    }

    void FlushRequest() {
        if(pendingRequest == null || Time.time < pendingRequestAt)
            return;
        string v = pendingRequest;
        pendingRequest = null;
        try {
            requestId++;
            var jc = new JSONClass();
            jc["request"] = v;
            jc["id"] = requestId.ToString() + "-" + DateTime.UtcNow.Ticks.ToString();
            SuperController.singleton.SaveJSON(jc, uiRequestFile.val);
            uiMotionRequest.valNoCallback = "";   // so an identical request later still counts as a change
        }
        catch(Exception e) {
            SuperController.LogError("BVH Player: could not write the motion request file: " + e.Message);
        }
    }

    void ActivatePending() {
        var nb = pendingQueue[0];
        pendingQueue.RemoveAt(0);
        int skip = Mathf.Clamp((int)uiChainSkip.val, 0, nb.nFrames - 1);
        bool seamless = uiChain.val && uiChainWorld.val && bvh != null && bvh.nFrames > 1;
        bool endOfRun = bvh != null && playing && !reverse && frame >= bvh.nFrames - 1;
        BvhTransform[] oldLast = null, oldPrev = null;
        if(seamless) {
            oldLast = bvh.ReadFrame(bvh.nFrames - 1);
            oldPrev = bvh.ReadFrame(bvh.nFrames - 2);
        }
        if(uiChain.val && bvh != null && bvh.nFrames > 0)
            ChainTranslation(bvh, nb, skip, uiChainWorld.val);
        bvh = nb;
        frame = skip;
        if(seamless) {
            // The old clip's last frame and the new clip's first frame are one frame apart in time.
            // Spend one frame interval moving from one to the other, so no motion is skipped and
            // every chunk plays for its full length. The time already elapsed carries over.
            blendFrom = oldLast;
            if(!endOfRun)
                elapsed = 0;
            PrepareFade(oldPrev, oldLast, nb.ReadFrame(skip));
        }
        else {
            blendFrom = null;
            fadeRot = null;
            fadePos = null;
            elapsed = 0;
        }
        UpdateStatus();
        UpdateSpeed(uiAnimationSpeed.val);
        reverse = false;
        playing = true;
        UpdateUI();
    }

    // If the new clip does not start exactly where the old one was heading, remember the mismatch
    // (compared with a straight-line continuation of the old clip's last two frames) and fade it out.
    void PrepareFade(BvhTransform[] a, BvhTransform[] b, BvhTransform[] n0) {
        fadeRot = null;
        fadePos = null;
        if(uiBlendTime == null || uiBlendTime.val <= 0f || a == null || b == null || n0 == null)
            return;
        if(a.Length != b.Length || b.Length != n0.Length)
            return;
        var rot = new Quaternion[b.Length];
        var pos = new Vector3[b.Length];
        for(int i = 0; i < b.Length; i++) {
            Quaternion expected = b[i].rotation * Quaternion.Inverse(a[i].rotation) * b[i].rotation;
            rot[i] = expected * Quaternion.Inverse(n0[i].rotation);
            if(b[i].bone.hasPosition)
                pos[i] = (b[i].position + (b[i].position - a[i].position)) - n0[i].position;
            else
                pos[i] = Vector3.zero;
        }
        fadeRot = rot;
        fadePos = pos;
        fadeT = 0f;
    }

    // Apply the remaining part of the mismatch to a pose from the new clip.
    BvhTransform[] Faded(BvhTransform[] d) {
        if(fadeRot == null)
            return d;
        float dur = uiBlendTime.val;
        if(dur <= 0f || fadeT >= dur || fadeRot.Length != d.Length) {
            fadeRot = null;
            fadePos = null;
            return d;
        }
        float u = fadeT / dur;
        float w = 1f - u * u * (3f - 2f * u);
        for(int i = 0; i < d.Length; i++) {
            d[i].rotation = Quaternion.Slerp(Quaternion.identity, fadeRot[i], w) * d[i].rotation;
            if(d[i].bone.hasPosition)
                d[i].position = d[i].position + fadePos[i] * w;
        }
        return d;
    }

    // Keep root translation continuous between clips.
    //  world = true : both files are in the same world frame (ARDY streaming). The new clip simply
    //                 inherits the previous clip's reference position, so the character keeps moving
    //                 through space exactly as generated.
    //  world = false: unrelated clips. The new clip starts wherever the previous one ended.
    void ChainTranslation(BvhFile prev, BvhFile next, int skip, bool world) {
        if(world) {
            var refs = new Dictionary<string, Vector3>();
            foreach(var b in prev.bones) {
                if(b.hasPosition)
                    refs[b.name] = b.posZero;
            }
            foreach(var b in next.bones) {
                Vector3 r;
                if(b.hasPosition && refs.TryGetValue(b.name, out r))
                    b.posZero = r;
            }
            return;
        }
        var last = prev.ReadFrame(prev.nFrames - 1);
        var first = next.ReadFrame(skip);
        var prevPos = new Dictionary<string, Vector3>();
        foreach(var t in last) {
            if(t.bone.hasPosition)
                prevPos[t.bone.name] = t.position - t.bone.posZero;
        }
        foreach(var t in first) {
            Vector3 d;
            if(t.bone.hasPosition && prevPos.TryGetValue(t.bone.name, out d))
                t.bone.posZero = t.position - d;
        }
    }

    public override void Init() {
        try {
    #region UI
	
				person = containingAtom;
				personController = person.GetStorableByID("control") as FreeControllerV3;
				
				basecontrolpos = personController.transform.position;
				
                headController = person.GetStorableByID("headControl") as FreeControllerV3;
                neckController = person.GetStorableByID("neckControl") as FreeControllerV3;
                chestController = person.GetStorableByID("chestControl") as FreeControllerV3;
                pelvisController = person.GetStorableByID("pelvisControl") as FreeControllerV3;
                hipController = person.GetStorableByID("hipControl") as FreeControllerV3;
                abdomenLowerController = person.GetStorableByID("abdomenControl") as FreeControllerV3;
                abdomenController = person.GetStorableByID("abdomen2Control") as FreeControllerV3;
                lShoulderController = person.GetStorableByID("lShoulderControl") as FreeControllerV3;
                rShoulderController = person.GetStorableByID("rShoulderControl") as FreeControllerV3;
                lBreastController = person.GetStorableByID("lNippleControl") as FreeControllerV3;
                rBreastController = person.GetStorableByID("rNippleControl") as FreeControllerV3;
                lArmController = person.GetStorableByID("lArmControl") as FreeControllerV3;
                rArmController = person.GetStorableByID("rArmControl") as FreeControllerV3;
                lElbowController = person.GetStorableByID("lElbowControl") as FreeControllerV3;
                rElbowController = person.GetStorableByID("rElbowControl") as FreeControllerV3;
                lHandController = person.GetStorableByID("lHandControl") as FreeControllerV3;
                rHandController = person.GetStorableByID("rHandControl") as FreeControllerV3;
                lHipController = person.GetStorableByID("lThighControl") as FreeControllerV3;
                rHipController = person.GetStorableByID("rThighControl") as FreeControllerV3;
                lKneeController = person.GetStorableByID("lKneeControl") as FreeControllerV3;
                rKneeController = person.GetStorableByID("rKneeControl") as FreeControllerV3;
                lFootController = person.GetStorableByID("lFootControl") as FreeControllerV3;
                rFootController = person.GetStorableByID("rFootControl") as FreeControllerV3;
                lToeController = person.GetStorableByID("lToeControl") as FreeControllerV3;
                rToeController = person.GetStorableByID("rToeControl") as FreeControllerV3;
				
			footbaseheight = lFootController.followWhenOff.position.y;

            CreateButton("Select BVH File").button.onClick.AddListener(() => {
                if(prevFolder == "")
                    prevFolder = SuperController.singleton.savesDir + "\\Animation";
                SuperController.singleton.GetMediaPathDialog((string path) => {
                    Load(path);
					footbaseheight = lFootController.followWhenOff.position.y;
                }, "bvh", prevFolder, false);
            });

            uiStatus = new JSONStorableString("Status:", "");
            CreateTextField(uiStatus, true);
            uiStatus.SetVal("Select a BVH file");

            var showSkeleton = new JSONStorableBool("Show Skeleton", false, (bool val) => {
                if(val)
                    ShowSkeleton();
                else
                    HideSkeleton();
            });
            RegisterBool(showSkeleton);
            CreateToggle(showSkeleton);
            // var uiOnlyHipTrans = new JSONStorableBool("Only hip translation", true, (bool val) => {
            //     onlyHipTranslation = val;
            // });
            // onlyHipTranslation = uiOnlyHipTrans.val;
            // RegisterBool(uiOnlyHipTrans);
            // CreateToggle(uiOnlyHipTrans);

            var modes = new List<string>();
            modes.Add("Offset + Frame (DAZ)");
            modes.Add("Frame only");
            modes.Add("Initial + Frame - Offset (MB)");
            modes.Add("Initial + Frame - Frame[0] (CMU)");

            var uiTranslationMode = new JSONStorableStringChooser("transmode", modes, modes[translationMode], "Translation Mode", (string val) => {
                translationMode = modes.FindIndex((string mode) => { return mode == val; });
                if((translationMode == translationModeInitialPlusFrameMinusOffset || translationMode == translationModeInitialPlusFrameMinusZero) && tposeBoneOffsets == null) {
                    // We need t-pose measurements, and don't have them yet
                    RecordOffsets();
                    CreateControllerMap();
                }
            });
            CreatePopup(uiTranslationMode);

            // var uiTransDelta = new JSONStorableBool("Translation is local", true, (bool val) => {
            //     translationIsDelta = val;
            //     if(! translationIsDelta && tposeBoneOffsets == null) {
            //         RecordOffsets();
            //         CreateControllerMap();
            //     }
            // });
            // translationIsDelta = uiTransDelta.val;
            // RegisterBool(uiTransDelta);
            // CreateToggle(uiTransDelta);

            var space = CreateSpacer(true);
            space.height = 20f;
            space = CreateSpacer();
            space.height = 10f;

            CreateButton("<<").button.onClick.AddListener(() => {
                uiAnimationPos.SetVal(0);
            });
            CreateButton(">>", true).button.onClick.AddListener(() => {
                uiAnimationPos.SetVal(100);
            });

            var playModes = new List<string>();
            playModes.Add("Once");
            playModes.Add("Loop");
            playModes.Add("PingPong Once");
            playModes.Add("PingPong Loop");

            var uiPlayMode = new JSONStorableStringChooser("playmode", playModes, playModes[0], "Play Mode", (string val) => {
                var i = playModes.IndexOf(val);
                loopPlay = (i & 1) == 1;
                pingpongPlay = i >= 2;
            });
            var uiBakeMode = new JSONStorableStringChooser("bakemode", playModes, playModes[0], "Bake Mode", (string val) => {
                var i = playModes.IndexOf(val);
                loopBake = (i & 1) == 1;
                pingpongBake = i >= 2;
            });

            uiAnimationPos = new JSONStorableFloat("Animation (%)", 0, (float value) => {
                if(bvh != null && !isUpdating) {
                    frame = (int)(bvh.nFrames * value * 0.01);
                    if(frame >= bvh.nFrames)
                        frame = bvh.nFrames - 1;
                    discontinuity = true;
                }
            }, 0, 100);
            CreateSlider(uiAnimationPos);
            uiAnimationSpeed = new JSONStorableFloat("Speed (%)", 100, UpdateSpeed, 1, 300);
            CreateSlider(uiAnimationSpeed, true);
            CreatePopup(uiPlayMode);

			uiskiptpose = new JSONStorableBool("Skip T Pose", false);
			RegisterBool(uiskiptpose);
			CreateToggle(uiskiptpose, false);

            CreateButton("Play").button.onClick.AddListener(() => {
                playing = true;
                reverse = false;
            });
            CreatePopup(uiBakeMode, true);
            CreateButton("Bake", true).button.onClick.AddListener(() => {
                Bake();
            });
            CreateButton("Stop", true).button.onClick.AddListener(() => {
                playing = false;
                if(baking)
                    BakeStop();
            });



            // ---- Auto-reload UI ----
            uiWatchFile = new JSONStorableString("Watch File", "");
            RegisterString(uiWatchFile);
            uiAutoReload = new JSONStorableBool("Auto Reload", false);
            RegisterBool(uiAutoReload);
            uiChain = new JSONStorableBool("Chain Continuous", true);
            RegisterBool(uiChain);
            uiChainWorld = new JSONStorableBool("Chain: ARDY World Coords", true);
            RegisterBool(uiChainWorld);
            uiChainSkip = new JSONStorableFloat("Chain Skip Frames", 0f, 0f, 60f, true, true);
            RegisterFloat(uiChainSkip);
            CreateButton("Select Watch File").button.onClick.AddListener(() => {
                if(prevFolder == "")
                    prevFolder = SuperController.singleton.savesDir + "\\Animation";
                SuperController.singleton.GetMediaPathDialog((string path) => {
                    uiWatchFile.val = path;
                    lastContent = null;
                }, "bvh", prevFolder, false);
            });
            CreateToggle(uiAutoReload, true);
            CreateToggle(uiChain);
            CreateToggle(uiChainWorld, true);
            CreateSlider(uiChainSkip, true);
            uiBlendTime = new JSONStorableFloat("Chunk Blend (s)", 0.15f, 0f, 0.5f, true, true);
            RegisterFloat(uiBlendTime);
            CreateSlider(uiBlendTime);
            uiInPlace = new JSONStorableBool("In Place (ignore horizontal travel)", true);
            RegisterBool(uiInPlace);
            CreateToggle(uiInPlace);
            CreateButton("Re-center", true).button.onClick.AddListener(() => {
                Recenter();
            });
            // Test buttons: a text field in a plugin panel only displays text, so these send fixed requests.
            CreateButton("Test: sit down").button.onClick.AddListener(() => { SendMotionRequest("sit down"); });
            CreateButton("Test: stand up", true).button.onClick.AddListener(() => { SendMotionRequest("stand up"); });
            CreateButton("Test: dance").button.onClick.AddListener(() => { SendMotionRequest("dance for me"); });
            CreateButton("Test: walk forward", true).button.onClick.AddListener(() => { SendMotionRequest("walk forward"); });
            // Not registered, so a saved scene can never override this path. VaM seems to let plugins write under
            // Saves/PluginData without asking; elsewhere it shows a "wants to save json" confirmation each time.
            uiRequestFile = new JSONStorableString("Request File", "Saves/PluginData/ardy_request.json");
            uiMotionRequest = new JSONStorableString("Motion Request", "", (string v) => { SendMotionRequest(v); });
            RegisterString(uiMotionRequest);
            CreateTextField(uiMotionRequest);
            CreateTextField(uiRequestFile, true);
            requestsOpenAt = Time.time + 3f;
            uiPluginIds = new JSONStorableString("Plugin IDs", "");
            CreateTextField(uiPluginIds);
            uiWatchStatus = new JSONStorableString("Watch Status", "");
            CreateTextField(uiWatchStatus, true);

			RegisterUIElements();
			CreateButtons();
			ColorButtons();
			
    #endregion

            // saveCollisionEnabled = containingAtom.collisionEnabledJSON.val;
            // containingAtom.collisionEnabledJSON.val = false;

            CreateShadowSkeleton();
            if(showSkeleton.val)
                ShowSkeleton();
            RecordOffsets();
            CreateControllerMap();
        }
        catch(Exception e) {
            SuperController.LogError("Init: " + e);
        }
    }

    void CreateControllerMap() {
        controllerMap = new Dictionary<string, FreeControllerV3>();
        foreach(FreeControllerV3 controller in containingAtom.freeControllers)
            controllerMap[controller.name] = controller;

        foreach(var item in cnameToBname) {
            var c = controllerMap[item.Key];
			if ((item.Key != "headControl" && item.Key != "neckControl") || uiemotionsupport.val == false)
			{
				c.currentRotationState = FreeControllerV3.RotationState.On;
				c.currentPositionState = FreeControllerV3.PositionState.On;
			}
        }

        macMap = new Dictionary<string, MotionAnimationControl>();
        foreach(var mac in containingAtom.motionAnimationControls) {
            macMap[mac.name] = mac;
        }
    }

    Transform CreateMarker(Transform parent) {
        var go = GameObject.CreatePrimitive(PrimitiveType.Cube).transform;
        go.parent = parent;
        go.localScale = new Vector3(0.1f, 0.1f, 0.1f);
        go.localPosition = Vector3.zero;
        go.localRotation = Quaternion.identity;
        Destroy(go.GetComponent<BoxCollider>());
        return go;
    }

    List<Transform> markers = null;

    void ShowSkeleton() {
        if(markers != null)
            HideSkeleton();
        markers = new List<Transform>();
        foreach(var bone in bones)
            markers.Add(CreateMarker(bone.Value));
    }

    void HideSkeleton() {
        foreach(var marker in markers)
            Destroy(marker.gameObject);
        markers = null;
    }

    Dictionary<string, Transform> bones;
    Dictionary<string, Vector3> tposeBoneOffsets = null;

    void RecordOffsets() {
        containingAtom.ResetPhysical();
        CreateShadowSkeleton();     // re-create
        tposeBoneOffsets = new Dictionary<string, Vector3>();
        foreach(var item in bones)
            tposeBoneOffsets[item.Key] = item.Value.localPosition;
    }

    public void CreateShadow(Transform skeleton, Transform shadow) {
        bones[shadow.gameObject.name] = shadow;
        shadow.localPosition = skeleton.localPosition;
        shadow.localRotation = skeleton.localRotation;
        // SuperController.LogMessage(string.Format("{0} {1} {2},{3},{4}", skeleton.gameObject.name, shadow.gameObject.name, shadow.position.x, shadow.position.y, shadow.position.z));
        // CreateMarker(shadow);
        for(var i = 0; i < skeleton.childCount; i++) {
            var child = skeleton.GetChild(i);
            if(child.gameObject.GetComponent<DAZBone>() != null) {
                var n = new GameObject(child.gameObject.name).transform;
                n.parent = shadow;
                CreateShadow(child, n);
            }
        }
    }

    void CreateShadowSkeleton() {
        foreach(var parent in containingAtom.gameObject.GetComponentsInChildren<DAZBones>()) {
            // SuperController.LogMessage(string.Format("{0}", parent.gameObject.name));
            if(parent.gameObject.name == "Genesis2Female" || parent.gameObject.name == "Genesis2Male") {
                // SuperController.LogMessage(parent.gameObject.name);
                if(shadow != null)
                    GameObject.Destroy(shadow.gameObject);
                bones = new Dictionary<string, Transform>();
                shadow = new GameObject("Shadow").transform;
                shadow.position = parent.transform.position;
                CreateShadow(parent.gameObject.transform, shadow);
            }
        }
    }

    BvhTransform[] prevFrame, nextFrame;

    BvhTransform[] Interpolate(BvhTransform[] a, BvhTransform[] b, float t) {
        var ret = new BvhTransform[a.Length];
        for(var i = 0; i < a.Length; i++) {
            var at = a[i];
            var bt = b[i];
            
            var res = new BvhTransform();
            res.bone = at.bone;
            res.position = Vector3.Lerp(at.position, bt.position, t);
            res.rotation = Quaternion.Lerp(at.rotation, bt.rotation, t);
            ret[i] = res;
        }
        return ret;
    }

    void UpdateModel(BvhTransform[] data) {
		foreach(var item in data) {
			// Copy on to model
			if(bones.ContainsKey(item.bone.name)) {
				bones[item.bone.name].localRotation = item.rotation;
				if(item.bone.hasPosition) {
                    if(item.bone.isHipBone || ! onlyHipTranslation) {
                        Vector3 pos;
                        if(translationMode == translationModeFrameOnly)
                            pos = item.position;
                        else if(translationMode == translationModeOffsetPlusFrame)
                            pos = item.position + item.bone.offset;
                        else if(translationMode == translationModeInitialPlusFrameMinusOffset)
                            pos = tposeBoneOffsets[item.bone.name] + item.position - item.bone.offset;
                        else //if(translationMode == translationModeInitialPlusFrameMinusZero)
                            pos = tposeBoneOffsets[item.bone.name] + item.position - item.bone.posZero;
                        if(uiInPlace != null && uiInPlace.val && item.bone.isHipBone && tposeBoneOffsets != null) {
                            // In Place: ignore horizontal travel, keep the height bob
                            Vector3 rest;
                            if(tposeBoneOffsets.TryGetValue(item.bone.name, out rest)) {
                                pos.x = rest.x;
                                pos.z = rest.z;
                            }
                        }
                        bones[item.bone.name].localPosition = pos;
                    }
                }
			}
		}
    }

    void FixedUpdate() {
        try {
			if (currentSpeed == -1.0f)
			{
				currentSpeed = uiAnimationSpeed.val;
			}
			if (uiskiptpose.val)
			{
				startFrame = 1;
			}
			else
			{
				startFrame = 0;
			}
			if (uiconfigjoints.val)
			{
				if (uiemotionsupport.val == false)
				{
					headController.currentPositionState = FreeControllerV3.PositionState.On;
					neckController.currentPositionState = FreeControllerV3.PositionState.On;

					headController.RBHoldPositionSpring = 454.0f * uijointpower.val;
					headController.RBHoldPositionDamper = 5.92f * uijointdamper.val;
					headController.RBHoldRotationSpring = 30.0f * uijointrotpower.val;
					headController.RBHoldRotationDamper = 12.66f * uijointrotpower.val;
					headController.jointRotationDriveSpring = 11.72f * uijointrotpower.val;
					headController.jointRotationDriveDamper = 1.0f * uijointrotpower.val;
					headController.jointRotationDriveXTarget = 0.0f;
					headController.jointRotationDriveYTarget = 0.0f;
					headController.jointRotationDriveZTarget = 0.0f;

					neckController.RBHoldPositionSpring = 16.0f * uijointpower.val;
					neckController.RBHoldPositionDamper = 7.72f * uijointdamper.val;
					neckController.RBHoldRotationSpring = 30.0f * uijointrotpower.val;
					neckController.RBHoldRotationDamper = 3.86f * uijointrotpower.val;
					neckController.jointRotationDriveSpring = 23.0f * uijointrotpower.val;
					neckController.jointRotationDriveDamper = 40.0f * uijointrotpower.val;
					neckController.jointRotationDriveXTarget = 0.0f;
					neckController.jointRotationDriveYTarget = 0.0f;
					neckController.jointRotationDriveZTarget = 0.0f;
				}
				else
				{
					headController.currentPositionState = FreeControllerV3.PositionState.Off;
					neckController.currentPositionState = FreeControllerV3.PositionState.Off;
				}

				chestController.RBHoldPositionSpring = 232.0f * uijointpower.val;
				chestController.RBHoldPositionDamper = 75.0f * uijointdamper.val;
				chestController.RBHoldRotationSpring = 574.0f * uijointrotpower.val;
				chestController.RBHoldRotationDamper = 1.0f * uijointrotpower.val;
				chestController.jointRotationDriveSpring = 410.0f * uijointrotpower.val;
				chestController.jointRotationDriveDamper = 235.0f * uijointrotpower.val;
				chestController.jointRotationDriveXTarget = 0.0f;
				chestController.jointRotationDriveYTarget = 0.0f;
				chestController.jointRotationDriveZTarget = 0.0f;

				abdomenController.RBHoldPositionSpring = 334.0f * uijointpower.val;
				abdomenController.RBHoldPositionDamper = 135.0f * uijointdamper.val;
				abdomenController.RBHoldRotationSpring = 500.0f * uijointrotpower.val;
				abdomenController.RBHoldRotationDamper = 1.0f * uijointrotpower.val;
				abdomenController.jointRotationDriveSpring = 271.0f * uijointrotpower.val;
				abdomenController.jointRotationDriveDamper = 1.0f * uijointrotpower.val;
				abdomenController.jointRotationDriveXTarget = 4.64f;
				abdomenController.jointRotationDriveYTarget = 0.0f;
				abdomenController.jointRotationDriveZTarget = 0.0f;

				abdomenLowerController.RBHoldPositionSpring = 334.0f * uijointpower.val;
				abdomenLowerController.RBHoldPositionDamper = 135.0f * uijointdamper.val;
				abdomenLowerController.RBHoldRotationSpring = 500.0f * uijointrotpower.val;
				abdomenLowerController.RBHoldRotationDamper = 1.0f * uijointrotpower.val;
				abdomenLowerController.jointRotationDriveSpring = 0.0f;
				abdomenLowerController.jointRotationDriveDamper = 0.5f;
				abdomenLowerController.jointRotationDriveXTarget = 0.0f;
				abdomenLowerController.jointRotationDriveYTarget = 0.0f;
				abdomenLowerController.jointRotationDriveZTarget = 0.0f;

				pelvisController.RBHoldPositionSpring = 734.0f * uijointpower.val;
				pelvisController.RBHoldPositionDamper = 135.0f * uijointdamper.val;
				pelvisController.RBHoldRotationSpring = 700.0f * uijointrotpower.val;
				pelvisController.RBHoldRotationDamper = 1.0f * uijointrotpower.val;
				pelvisController.jointRotationDriveSpring = 0.0f;
				pelvisController.jointRotationDriveDamper = 0.5f;
				pelvisController.jointRotationDriveXTarget = 0.0f;
				pelvisController.jointRotationDriveYTarget = 0.0f;
				pelvisController.jointRotationDriveZTarget = 0.0f;

				hipController.RBHoldPositionSpring = 1500.0f * uihipholdpower.val;
				hipController.RBHoldPositionDamper = 650.0f * uihipholdpower.val * uijointdamper.val;
				hipController.RBHoldRotationSpring = 500.0f * uijointrotpower.val;
				hipController.RBHoldRotationDamper = 1.0f * uijointrotpower.val;
				hipController.jointRotationDriveSpring = 0.0f;
				hipController.jointRotationDriveDamper = 0.5f;
				hipController.jointRotationDriveXTarget = 0.0f;
				hipController.jointRotationDriveYTarget = 0.0f;
				hipController.jointRotationDriveZTarget = 0.0f;

				lShoulderController.RBHoldPositionSpring = 45.0f * uijointpower.val;
				lShoulderController.RBHoldPositionDamper = 35.0f * uijointdamper.val;
				lShoulderController.RBHoldRotationSpring = 500.0f * uijointrotpower.val;
				lShoulderController.RBHoldRotationDamper = 1.0f * uijointrotpower.val;
				lShoulderController.jointRotationDriveSpring = 102.5f * uijointrotpower.val;
				lShoulderController.jointRotationDriveDamper = 28.75f * uijointrotpower.val;
				lShoulderController.jointRotationDriveXTarget = 15.0f;
				lShoulderController.jointRotationDriveYTarget = 1.45f;
				lShoulderController.jointRotationDriveZTarget = -10.0f;

				rShoulderController.RBHoldPositionSpring = 45.0f * uijointpower.val;
				rShoulderController.RBHoldPositionDamper = 35.0f * uijointdamper.val;
				rShoulderController.RBHoldRotationSpring = 500.0f * uijointrotpower.val;
				rShoulderController.RBHoldRotationDamper = 1.0f * uijointrotpower.val;
				rShoulderController.jointRotationDriveSpring = 102.5f * uijointrotpower.val;
				rShoulderController.jointRotationDriveDamper = 28.75f * uijointrotpower.val;
				rShoulderController.jointRotationDriveXTarget = -15.0f;
				rShoulderController.jointRotationDriveYTarget = -1.45f;
				rShoulderController.jointRotationDriveZTarget = -10.0f;


				lArmController.RBHoldPositionSpring = 182.0f * uijointarmpower.val;
				lArmController.RBHoldPositionDamper = 35.0f * uijointarmpower.val * uijointdamper.val;
				lArmController.RBHoldRotationSpring = 700.0f * uijointarmrotpower.val;
				lArmController.RBHoldRotationDamper = 1.0f * uijointarmrotpower.val;
				lArmController.jointRotationDriveSpring = 262.5f * uijointarmrotpower.val;
				lArmController.jointRotationDriveDamper = 2.0f * uijointarmrotpower.val;
				lArmController.jointRotationDriveXTarget = -70.5f;
				lArmController.jointRotationDriveYTarget = -49.63f;
				lArmController.jointRotationDriveZTarget = 70.0f;

				rArmController.RBHoldPositionSpring = 182.0f * uijointarmpower.val;
				rArmController.RBHoldPositionDamper = 35.0f * uijointarmpower.val * uijointdamper.val;
				rArmController.RBHoldRotationSpring = 700.0f * uijointarmrotpower.val;
				rArmController.RBHoldRotationDamper = 1.0f * uijointarmrotpower.val;
				rArmController.jointRotationDriveSpring = 262.5f * uijointarmrotpower.val;
				rArmController.jointRotationDriveDamper = 2.0f * uijointarmrotpower.val;
				rArmController.jointRotationDriveXTarget = 70.5f;
				rArmController.jointRotationDriveYTarget = 49.63f;
				rArmController.jointRotationDriveZTarget = 70.0f;

				lElbowController.RBHoldPositionSpring = 100.0f * uijointarmpower.val;
				lElbowController.RBHoldPositionDamper = 35.0f * uijointarmpower.val * uijointdamper.val;
				lElbowController.RBHoldRotationSpring = 280.0f * uijointarmrotpower.val;
				lElbowController.RBHoldRotationDamper = 1.0f * uijointarmrotpower.val;
				lElbowController.jointRotationDriveSpring = 0.0f;
				lElbowController.jointRotationDriveDamper = 0.5f;
				lElbowController.jointRotationDriveXTarget = 0.0f;
				lElbowController.jointRotationDriveYTarget = 0.0f;
				lElbowController.jointRotationDriveZTarget = 0.0f;

				rElbowController.RBHoldPositionSpring = 100.0f * uijointarmpower.val;
				rElbowController.RBHoldPositionDamper = 35.0f * uijointarmpower.val * uijointdamper.val;
				rElbowController.RBHoldRotationSpring = 280.0f * uijointarmrotpower.val;
				rElbowController.RBHoldRotationDamper = 1.0f * uijointarmrotpower.val;
				rElbowController.jointRotationDriveSpring = 0.0f;
				rElbowController.jointRotationDriveDamper = 0.5f;
				rElbowController.jointRotationDriveXTarget = 0.0f;
				rElbowController.jointRotationDriveYTarget = 0.0f;
				rElbowController.jointRotationDriveZTarget = 0.0f;

				lHandController.RBHoldPositionSpring = 250.0f * uijointarmpower.val;
				lHandController.RBHoldPositionDamper = 1.0f * uijointarmpower.val * uijointdamper.val;
				lHandController.RBHoldRotationSpring = 450.0f * uijointhandrotpower.val;
				lHandController.RBHoldRotationDamper = 0.5f * uijointhandrotpower.val;
				lHandController.jointRotationDriveSpring = 0.0f;
				lHandController.jointRotationDriveDamper = 0.0f;
				lHandController.jointRotationDriveXTarget = 0.0f;
				lHandController.jointRotationDriveYTarget = 0.0f;
				lHandController.jointRotationDriveZTarget = 0.0f;


				rHandController.RBHoldPositionSpring = 250.0f * uijointarmpower.val;
				rHandController.RBHoldPositionDamper = 1.0f * uijointarmpower.val * uijointdamper.val;
				rHandController.RBHoldRotationSpring = 450.0f * uijointhandrotpower.val;
				rHandController.RBHoldRotationDamper = 0.5f * uijointhandrotpower.val;
				rHandController.jointRotationDriveSpring = 0.0f;
				rHandController.jointRotationDriveDamper = 0.0f;
				rHandController.jointRotationDriveXTarget = 0.0f;
				rHandController.jointRotationDriveYTarget = 0.0f;
				rHandController.jointRotationDriveZTarget = 0.0f;
				
				lHipController.RBHoldPositionSpring = 2000.0f * uijointpower.val;
				lHipController.RBHoldPositionDamper = 435.0f * uijointdamper.val;
				lHipController.RBHoldRotationSpring = 500.0f * uijointrotpower.val;
				lHipController.RBHoldRotationDamper = 1.0f * uijointrotpower.val;
				lHipController.jointRotationDriveSpring = 0.0f;
				lHipController.jointRotationDriveDamper = 0.5f;
				lHipController.jointRotationDriveXTarget = 0.0f;
				lHipController.jointRotationDriveYTarget = 0.0f;
				lHipController.jointRotationDriveZTarget = 0.0f;

				rHipController.RBHoldPositionSpring = 2000.0f * uijointpower.val;
				rHipController.RBHoldPositionDamper = 435.0f * uijointdamper.val;
				rHipController.RBHoldRotationSpring = 500.0f * uijointrotpower.val;
				rHipController.RBHoldRotationDamper = 1.0f * uijointrotpower.val;
				rHipController.jointRotationDriveSpring = 0.0f;
				rHipController.jointRotationDriveDamper = 0.5f;
				rHipController.jointRotationDriveXTarget = 0.0f;
				rHipController.jointRotationDriveYTarget = 0.0f;
				rHipController.jointRotationDriveZTarget = 0.0f;

				lKneeController.RBHoldPositionSpring = 500.0f * uijointpower.val;
				lKneeController.RBHoldPositionDamper = 3.0f * uijointdamper.val;
				lKneeController.RBHoldRotationSpring = 500.0f * uijointrotpower.val;
				lKneeController.RBHoldRotationDamper = 1.0f * uijointrotpower.val;
				lKneeController.jointRotationDriveSpring = 0.0f;
				lKneeController.jointRotationDriveDamper = 0.5f;
				lKneeController.jointRotationDriveXTarget = 0.0f;
				lKneeController.jointRotationDriveYTarget = 0.0f;
				lKneeController.jointRotationDriveZTarget = 0.0f;

				rKneeController.RBHoldPositionSpring = 500.0f * uijointpower.val;
				rKneeController.RBHoldPositionDamper = 3.0f * uijointdamper.val;
				rKneeController.RBHoldRotationSpring = 500.0f * uijointrotpower.val;
				rKneeController.RBHoldRotationDamper = 1.0f * uijointrotpower.val;
				rKneeController.jointRotationDriveSpring = 0.0f;
				rKneeController.jointRotationDriveDamper = 0.5f;
				rKneeController.jointRotationDriveXTarget = 0.0f;
				rKneeController.jointRotationDriveYTarget = 0.0f;
				rKneeController.jointRotationDriveZTarget = 0.0f;

				lFootController.RBHoldPositionSpring = 1000.0f * uijointpower.val;
				lFootController.RBHoldPositionDamper = 2.0f * uijointdamper.val;
				lFootController.RBHoldRotationSpring = 450.0f * uijointfootrotpower.val;
				lFootController.RBHoldRotationDamper = 1.0f * uijointfootrotpower.val;
				lFootController.jointRotationDriveSpring = 0.0f;
				lFootController.jointRotationDriveDamper = 0.5f;
				lFootController.jointRotationDriveXTarget = 0.0f;
				lFootController.jointRotationDriveYTarget = 0.0f;
				lFootController.jointRotationDriveZTarget = 0.0f;

				rFootController.RBHoldPositionSpring = 1000.0f * uijointpower.val;
				rFootController.RBHoldPositionDamper = 2.0f * uijointdamper.val;
				rFootController.RBHoldRotationSpring = 450.0f * uijointfootrotpower.val;
				rFootController.RBHoldRotationDamper = 1.0f * uijointfootrotpower.val;
				rFootController.jointRotationDriveSpring = 0.0f;
				rFootController.jointRotationDriveDamper = 0.5f;
				rFootController.jointRotationDriveXTarget = 0.0f;
				rFootController.jointRotationDriveYTarget = 0.0f;
				rFootController.jointRotationDriveZTarget = 0.0f;
			}
			if (uicustomweights.val)
			{
				headController.RBMass = 1.25f * uicustombodyweight.val;
				neckController.RBMass = 0.325f * uicustombodyweight.val;
				chestController.RBMass = 3.75f * uicustombodyweight.val;
				abdomenController.RBMass = 3.35f * uicustombodyweight.val;
				abdomenLowerController.RBMass = 1.75f * uicustombodyweight.val;
				pelvisController.RBMass = 1.75f * uicustombodyweight.val;
				hipController.RBMass = 3.75f * uicustombodyweight.val;
				lShoulderController.RBMass = 1.25f * uicustombodyweight.val;
				rShoulderController.RBMass = 1.25f * uicustombodyweight.val;
				lArmController.RBMass = 1.25f * uicustombodyweight.val;
				rArmController.RBMass = 1.25f * uicustombodyweight.val;
				lElbowController.RBMass = 0.625f * uicustomarmsweight.val;
				rElbowController.RBMass = 0.625f * uicustomarmsweight.val;
				lHandController.RBMass = 0.375f * uicustomarmsweight.val;
				rHandController.RBMass = 0.375f * uicustomarmsweight.val;
				lHipController.RBMass = 2.5f * uicustombodyweight.val;
				rHipController.RBMass = 2.5f * uicustombodyweight.val;
				lKneeController.RBMass = 1.25f * uicustomlegsweight.val;
				rKneeController.RBMass = 1.25f * uicustomlegsweight.val;
				lFootController.RBMass = 1.0f * uicustomlegsweight.val;
				rFootController.RBMass = 1.0f * uicustomlegsweight.val;
			}
				
				if (uikeeponfloor.val)
				{
					personController.transform.position = basecontrolpos;
					//float loffset = lToeController.followWhenOff.position.y;
					//float roffset = rToeController.followWhenOff.position.y;
					float lowestoffset = Mathf.Min(
												lToeController.followWhenOff.position.y - 0.02f - uifloorheight.val,
												rToeController.followWhenOff.position.y - 0.02f - uifloorheight.val,
												lFootController.followWhenOff.position.y - 0.045f - uifloorheight.val,
												rFootController.followWhenOff.position.y - 0.045f - uifloorheight.val,
												lHipController.followWhenOff.position.y - 0.07f - uifloorheight.val,
												rHipController.followWhenOff.position.y - 0.07f - uifloorheight.val,
												lKneeController.followWhenOff.position.y - 0.025f - uifloorheight.val,
												rKneeController.followWhenOff.position.y - 0.025f - uifloorheight.val,
												lShoulderController.followWhenOff.position.y - 0.04f - uifloorheight.val,
												rShoulderController.followWhenOff.position.y - 0.04f - uifloorheight.val,
												chestController.followWhenOff.position.y - 0.05f - uifloorheight.val,
												headController.followWhenOff.position.y - 0.03f - uifloorheight.val
												);
												
												
					if (lHandController.followWhenOff.position.y - 0.015f < uifloorheight.val)
					{
						lHandController.RBHoldPositionSpring = 75.0f * uijointpower.val;
						lHandController.RBHoldPositionDamper = 1.0f * uijointpower.val;
						//lHandController.RBHoldRotationSpring = 24.5f * uijointpower.val;
						//lHandController.RBHoldRotationDamper = 0.5f * uijointpower.val;
					}
					
					if (rHandController.followWhenOff.position.y - 0.015f < uifloorheight.val)
					{
						rHandController.RBHoldPositionSpring = 75.0f * uijointpower.val;
						rHandController.RBHoldPositionDamper = 1.0f * uijointpower.val;
						//rHandController.RBHoldRotationSpring = 24.5f * uijointpower.val;
						//rHandController.RBHoldRotationDamper = 0.5f * uijointpower.val;
					}
/*
					if (lFootController.followWhenOff.position.y - 0.055f < uifloorheight.val)
					{
						lFootController.RBHoldPositionSpring = 175.0f * uijointpower.val;
						lFootController.RBHoldPositionDamper = 1.0f * uijointpower.val;
						//lFootController.RBHoldRotationSpring = 24.5f * uijointpower.val;
						//lFootController.RBHoldRotationDamper = 0.5f * uijointpower.val;
					}
					if (rFootController.followWhenOff.position.y - 0.055f < uifloorheight.val)
					{
						rFootController.RBHoldPositionSpring = 175.0f * uijointpower.val;
						rFootController.RBHoldPositionDamper = 1.0f * uijointpower.val;
						//rFootController.RBHoldRotationSpring = 24.5f * uijointpower.val;
						//rFootController.RBHoldRotationDamper = 0.5f * uijointpower.val;
					}
					if (lHipController.followWhenOff.position.y - 0.105f < uifloorheight.val)
					{
						lHipController.RBHoldPositionSpring = 75.0f * uijointpower.val;
						lHipController.RBHoldPositionDamper = 1.0f * uijointpower.val;
						//lHipController.RBHoldRotationSpring = 24.5f * uijointpower.val;
						//lHipController.RBHoldRotationDamper = 0.5f * uijointpower.val;
					}
					if (rHipController.followWhenOff.position.y - 0.105f < uifloorheight.val)
					{
						rHipController.RBHoldPositionSpring = 75.0f * uijointpower.val;
						rHipController.RBHoldPositionDamper = 1.0f * uijointpower.val;
						//rHipController.RBHoldRotationSpring = 24.5f * uijointpower.val;
						//rHipController.RBHoldRotationDamper = 0.5f * uijointpower.val;
					}
					if (lKneeController.followWhenOff.position.y - 0.035f < uifloorheight.val)
					{
						lKneeController.RBHoldPositionSpring = 15.0f * uijointpower.val;
						lKneeController.RBHoldPositionDamper = 25.0f * uijointpower.val;
						//lKneeController.RBHoldRotationSpring = 4.5f * uijointpower.val;
						//lKneeController.RBHoldRotationDamper = 0.5f * uijointpower.val;
					}
					if (rKneeController.followWhenOff.position.y - 0.035f < uifloorheight.val)
					{
						rKneeController.RBHoldPositionSpring = 15.0f * uijointpower.val;
						rKneeController.RBHoldPositionDamper = 25.0f * uijointpower.val;
						//rKneeController.RBHoldRotationSpring = 24.5f * uijointpower.val;
						//rKneeController.RBHoldRotationDamper = 0.5f * uijointpower.val;
					}
					if (lShoulderController.followWhenOff.position.y - 0.025f < uifloorheight.val)
					{
						lShoulderController.RBHoldPositionSpring = 75.0f * uijointpower.val;
						lShoulderController.RBHoldPositionDamper = 1.0f * uijointpower.val;
						//lShoulderController.RBHoldRotationSpring = 24.5f * uijointpower.val;
						//lShoulderController.RBHoldRotationDamper = 0.5f * uijointpower.val;
					}
					if (rShoulderController.followWhenOff.position.y - 0.025f < uifloorheight.val)
					{
						rShoulderController.RBHoldPositionSpring = 75.0f * uijointpower.val;
						rShoulderController.RBHoldPositionDamper = 1.0f * uijointpower.val;
						//rShoulderController.RBHoldRotationSpring = 24.5f * uijointpower.val;
						//rShoulderController.RBHoldRotationDamper = 0.5f * uijointpower.val;
					}

					if (uiemotionsupport.val == false)
					{
						if (headController.followWhenOff.position.y - 0.035f < uifloorheight.val)
						{
							headController.RBHoldPositionSpring = 75.0f * uijointpower.val;
							headController.RBHoldPositionDamper = 1.0f * uijointpower.val;
							//headController.RBHoldRotationSpring = 24.5f * uijointpower.val;
							//headController.RBHoldRotationDamper = 0.5f * uijointpower.val;
						}
						if (neckController.followWhenOff.position.y - 0.035f < uifloorheight.val)
						{
							neckController.RBHoldPositionSpring = 75.0f * uijointpower.val;
							neckController.RBHoldPositionDamper = 1.0f * uijointpower.val;
							//neckController.RBHoldRotationSpring = 24.5f * uijointpower.val;
							//neckController.RBHoldRotationDamper = 0.5f * uijointpower.val;
						}
					}
					*/
					//SuperController.singleton.ClearErrors();
					//SuperController.LogError("Left " + loffset + " Right " + roffset + "(" + footbaseheight);
					Vector3 tempvector = new Vector3(0.0f,0.0f,0.0f);
					if (Mathf.Abs(lowestoffset) < 0.0001f)
					{
						lowestoffset = 0.0f;
					}
					
					if (Mathf.Abs(lowestoffset) > 0.0001f)
					{
						if (lowestoffset > uifloorheight.val - 0.001f)//loffset > 0.0f && roffset > 0.0f)
						{
							tempvector.y = lowestoffset * (uiflooradjustspeed.val * 0.7f); //Mathf.Min(loffset,roffset) * 0.05f;
							//SuperController.LogError("Down " + tempvector.y);
							personController.transform.position = personController.transform.position - tempvector;
						}
						if (lowestoffset < uifloorheight.val + 0.005f)//loffset > 0.0f && roffset > 0.0f)
						{
							tempvector.y = (lowestoffset + 0.005f) * (uiflooradjustspeed.val); //Mathf.Min(loffset,roffset) * 0.05f;
							//SuperController.LogError("Up " + tempvector.y);
							personController.transform.position = personController.transform.position - tempvector;
						}
					}
					tempvector = personController.transform.position;
					if (tempvector.y > uifloorheight.val)
					{
						tempvector.y = uifloorheight.val;
						personController.transform.position = tempvector;
					}
					basecontrolpos = personController.transform.position;
					personController.transform.position = personController.transform.position + new Vector3(0.0f, uipostheightoffset.val, 0.0f);
				}
				
					
            UpdatePluginIds();
            FlushRequest();
            PollWatch();

            if(bvh == null || bvh.nFrames == 0)
                return;

            if(playing) {
                elapsed += Time.deltaTime;
                if(elapsed >= frameTime) {
                    // Auto Reload: carry the remainder so playback runs at true speed (resetting to 0 makes
                    // each frame last a whole number of physics steps, i.e. slightly slow playback).
                    elapsed = (uiAutoReload != null && uiAutoReload.val) ? Mathf.Max(0f, elapsed - frameTime) : 0;
                    if(blendFrom != null)
                        blendFrom = null;   // finished the interval between two files; stay on the new clip's first frame
                    else if(reverse)
                        frame--;
                    else
                        frame++;
                    UpdateUI();
                }
                if(blendFrom == null)
                    fadeT += Time.deltaTime;
            }

            if(frame < startFrame) {
                reverse = false;
                frame = startFrame;
                if(baking) {
                    if(! loopBake)
                        BakeStop();
                }
                else {
                    if(! loopPlay)
                        playing = false;
                }
            }

            if(frame >= bvh.nFrames) {
                if(baking) {
                    if(pingpongBake) {
                        reverse = true;
                        frame--;
                    }
                    else if(loopBake)
                        frame = startFrame;
                    else {
                        BakeStop();
                        return;
                    }
                }
                else {
                    if(pingpongPlay) {
                        reverse = true;
                        frame--;
                    }
                    else if(loopPlay)
                        frame = startFrame;
                    else {
                        playing = false;
                        return;
                    }
                }
            }

            if(blendFrom != null && !reverse) {
                // between two files: move from the old clip's last pose to the new clip's first pose
                var nf = Faded(bvh.ReadFrame(frame));
                if(blendFrom.Length == nf.Length)
                    UpdateModel(Interpolate(blendFrom, nf, Mathf.Clamp01(elapsed / frameTime)));
                else
                    blendFrom = null;
            }
            else if(reverse) {
                if(frame == startFrame)
                    UpdateModel(bvh.ReadFrame(frame));
                else {
                    // Interpolate in reverse
                    var frm = bvh.ReadFrame(frame);
                    var to = bvh.ReadFrame(frame - 1);
                    float t = elapsed / frameTime;
                    UpdateModel(Interpolate(frm, to, t));
                }
            }
            else {
                if(frame >= bvh.nFrames - 1) {
                    // Last frame
                    UpdateModel(Faded(bvh.ReadFrame(frame)));
                }
                else {
                    // Interpolate
                    var frm = bvh.ReadFrame(frame);
                    var to = bvh.ReadFrame(frame + 1);
                    float t = elapsed / frameTime;
                    UpdateModel(Faded(Interpolate(frm, to, t)));
                }
            }

            if(discontinuity)
                BeginRestore();

            Vector3 pivotPos = containingAtom.transform.position;
            foreach(var item in cnameToBname) {
				if ((item.Key != "headControl" && item.Key != "neckControl") || uiemotionsupport.val == false)
				{
					controllerMap[item.Key].transform.localPosition = bones[item.Value].position - pivotPos;
					controllerMap[item.Key].transform.localRotation = bones[item.Value].rotation;
				}
            }

            if(discontinuity)
                EndRestore();

			if (uispeeddist.val)
			{
				if (uifocustarget.val != "None")
				{
					if (currentAtomName != uifocustarget.val)
					{
						currentAtom = SuperController.singleton.GetAtomByUid(uifocustarget.val);
						if (currentAtom != null)
						{
							currentAtomName = uifocustarget.val;
							target = currentAtom;
							targetheadController = target.GetStorableByID("headControl") as FreeControllerV3;
							targetlHandController = target.GetStorableByID("lHandControl") as FreeControllerV3;
							targetrHandController = target.GetStorableByID("rHandControl") as FreeControllerV3;
							targetpelvisController = target.GetStorableByID("pelvisControl") as FreeControllerV3;
						}
						else
						{
							uifocustarget.val = "None";
							currentAtomName = uifocustarget.val;
							target = null;
							targetheadController = null;
							targetlHandController = null;
							targetrHandController = null;
							targetpelvisController = null;
						}
					}
				}
				if (targetheadController != null && targetlHandController != null && targetrHandController != null && targetpelvisController != null)
				{
					//float temp = Vector3.Distance(targetheadController.followWhenOff.position, headController.followWhenOff.position);
					
					float headdist = 99999.0f;
					float lhanddist = 99999.0f;
					float rhanddist = 99999.0f;
					float pelvisdist = 99999.0f;
					headdist   = Mathf.Min( Vector3.Distance(targetheadController.followWhenOff.position, chestController.followWhenOff.position),
											Vector3.Distance(targetheadController.followWhenOff.position, abdomenController.followWhenOff.position),
											Vector3.Distance(targetheadController.followWhenOff.position, lHipController.followWhenOff.position),
											Vector3.Distance(targetheadController.followWhenOff.position, rHipController.followWhenOff.position)
											);
					lhanddist  = Mathf.Min( Vector3.Distance(targetlHandController.followWhenOff.position, chestController.followWhenOff.position),
											Vector3.Distance(targetlHandController.followWhenOff.position, abdomenController.followWhenOff.position),
											Vector3.Distance(targetlHandController.followWhenOff.position, lHipController.followWhenOff.position),
											Vector3.Distance(targetlHandController.followWhenOff.position, rHipController.followWhenOff.position)
											);
					rhanddist  = Mathf.Min( Vector3.Distance(targetrHandController.followWhenOff.position, chestController.followWhenOff.position),
											Vector3.Distance(targetrHandController.followWhenOff.position, abdomenController.followWhenOff.position),
											Vector3.Distance(targetrHandController.followWhenOff.position, lHipController.followWhenOff.position),
											Vector3.Distance(targetrHandController.followWhenOff.position, rHipController.followWhenOff.position)
											);
					pelvisdist = Mathf.Min( Vector3.Distance(targetpelvisController.followWhenOff.position, chestController.followWhenOff.position),
											Vector3.Distance(targetpelvisController.followWhenOff.position, abdomenController.followWhenOff.position),
											Vector3.Distance(targetpelvisController.followWhenOff.position, lHipController.followWhenOff.position),
											Vector3.Distance(targetpelvisController.followWhenOff.position, rHipController.followWhenOff.position)
											);
					if (uiskiphead.val == false)
					{
						headdist   = Mathf.Min( headdist,
												Vector3.Distance(targetheadController.followWhenOff.position, headController.followWhenOff.position),
												Vector3.Distance(targetheadController.followWhenOff.position, neckController.followWhenOff.position)
												);
						lhanddist  = Mathf.Min( lhanddist,
												Vector3.Distance(targetlHandController.followWhenOff.position, headController.followWhenOff.position),
												Vector3.Distance(targetlHandController.followWhenOff.position, neckController.followWhenOff.position)
												);
						rhanddist  = Mathf.Min( rhanddist,
												Vector3.Distance(targetrHandController.followWhenOff.position, headController.followWhenOff.position),
												Vector3.Distance(targetrHandController.followWhenOff.position, neckController.followWhenOff.position)
												);
						pelvisdist = Mathf.Min( pelvisdist,
												Vector3.Distance(targetpelvisController.followWhenOff.position, headController.followWhenOff.position),
												Vector3.Distance(targetpelvisController.followWhenOff.position, neckController.followWhenOff.position)
												);
					}
					if (uiskiparms.val == false)
					{
						headdist   = Mathf.Min( headdist,
												Vector3.Distance(targetheadController.followWhenOff.position, lArmController.followWhenOff.position),
												Vector3.Distance(targetheadController.followWhenOff.position, rArmController.followWhenOff.position),
												Vector3.Distance(targetheadController.followWhenOff.position, lElbowController.followWhenOff.position),
												Vector3.Distance(targetheadController.followWhenOff.position, rElbowController.followWhenOff.position),
												Vector3.Distance(targetheadController.followWhenOff.position, lHandController.followWhenOff.position),
												Vector3.Distance(targetheadController.followWhenOff.position, rHandController.followWhenOff.position)
												);
						lhanddist  = Mathf.Min( lhanddist,
												Vector3.Distance(targetlHandController.followWhenOff.position, lArmController.followWhenOff.position),
												Vector3.Distance(targetlHandController.followWhenOff.position, rArmController.followWhenOff.position),
												Vector3.Distance(targetlHandController.followWhenOff.position, lElbowController.followWhenOff.position),
												Vector3.Distance(targetlHandController.followWhenOff.position, rElbowController.followWhenOff.position),
												Vector3.Distance(targetlHandController.followWhenOff.position, lHandController.followWhenOff.position),
												Vector3.Distance(targetlHandController.followWhenOff.position, rHandController.followWhenOff.position)
												);
						rhanddist  = Mathf.Min( rhanddist,
												Vector3.Distance(targetrHandController.followWhenOff.position, lArmController.followWhenOff.position),
												Vector3.Distance(targetrHandController.followWhenOff.position, rArmController.followWhenOff.position),
												Vector3.Distance(targetrHandController.followWhenOff.position, lElbowController.followWhenOff.position),
												Vector3.Distance(targetrHandController.followWhenOff.position, rElbowController.followWhenOff.position),
												Vector3.Distance(targetrHandController.followWhenOff.position, lHandController.followWhenOff.position),
												Vector3.Distance(targetrHandController.followWhenOff.position, rHandController.followWhenOff.position)
												);
						pelvisdist = Mathf.Min( pelvisdist,
												Vector3.Distance(targetpelvisController.followWhenOff.position, lArmController.followWhenOff.position),
												Vector3.Distance(targetpelvisController.followWhenOff.position, rArmController.followWhenOff.position),
												Vector3.Distance(targetpelvisController.followWhenOff.position, lElbowController.followWhenOff.position),
												Vector3.Distance(targetpelvisController.followWhenOff.position, rElbowController.followWhenOff.position),
												Vector3.Distance(targetpelvisController.followWhenOff.position, lHandController.followWhenOff.position),
												Vector3.Distance(targetpelvisController.followWhenOff.position, rHandController.followWhenOff.position)
												);
					}
					if (uiskiplegs.val == false)
					{
						headdist   = Mathf.Min( headdist,
												Vector3.Distance(targetheadController.followWhenOff.position, lKneeController.followWhenOff.position),
												Vector3.Distance(targetheadController.followWhenOff.position, rKneeController.followWhenOff.position),
												Vector3.Distance(targetheadController.followWhenOff.position, lFootController.followWhenOff.position),
												Vector3.Distance(targetheadController.followWhenOff.position, rFootController.followWhenOff.position)
												);
						lhanddist  = Mathf.Min( lhanddist,
												Vector3.Distance(targetlHandController.followWhenOff.position, lKneeController.followWhenOff.position),
												Vector3.Distance(targetlHandController.followWhenOff.position, rKneeController.followWhenOff.position),
												Vector3.Distance(targetlHandController.followWhenOff.position, lFootController.followWhenOff.position),
												Vector3.Distance(targetlHandController.followWhenOff.position, rFootController.followWhenOff.position)
												);
						rhanddist  = Mathf.Min( rhanddist,
												Vector3.Distance(targetrHandController.followWhenOff.position, lKneeController.followWhenOff.position),
												Vector3.Distance(targetrHandController.followWhenOff.position, rKneeController.followWhenOff.position),
												Vector3.Distance(targetrHandController.followWhenOff.position, lFootController.followWhenOff.position),
												Vector3.Distance(targetrHandController.followWhenOff.position, rFootController.followWhenOff.position)
												);
						pelvisdist = Mathf.Min( pelvisdist,
												Vector3.Distance(targetpelvisController.followWhenOff.position, lKneeController.followWhenOff.position),
												Vector3.Distance(targetpelvisController.followWhenOff.position, rKneeController.followWhenOff.position),
												Vector3.Distance(targetpelvisController.followWhenOff.position, lFootController.followWhenOff.position),
												Vector3.Distance(targetpelvisController.followWhenOff.position, rFootController.followWhenOff.position)
												);
					}
					float closestDist = Mathf.Min(headdist, lhanddist, rhanddist, pelvisdist);
					float finalvalue = Mathf.Lerp(uiminspeed.val, uiAnimationSpeed.val, Mathf.Clamp(closestDist - uimindist.val, 0.0f, uimaxdist.val - uimindist.val)/(uimaxdist.val - uimindist.val));
					finalvalue = Mathf.Clamp(finalvalue,uiminspeed.val,uiAnimationSpeed.val);
					if (finalvalue > currentSpeed) { currentSpeed = Mathf.Min(currentSpeed + uichangespeed.val, finalvalue); }
					if (finalvalue < currentSpeed) { currentSpeed = Mathf.Max(currentSpeed - uichangespeed.val, finalvalue); }
					frameTime = bvh.frameTime / (currentSpeed * 0.01f);
				}
				else
				{
					frameTime = bvh.frameTime / (uiAnimationSpeed.val * 0.01f);
				}
			}

				lShoulderController.transform.Rotate(uishoulderxrotate.val, uishoulderyrotate.val, uishoulderzrotate.val, Space.Self);
				rShoulderController.transform.Rotate(uishoulderxrotate.val, -uishoulderyrotate.val, -uishoulderzrotate.val, Space.Self);
				lArmController.transform.Rotate(uiarmxrotate.val, uiarmyrotate.val, uiarmzrotate.val, Space.Self);
				rArmController.transform.Rotate(uiarmxrotate.val, -uiarmyrotate.val, -uiarmzrotate.val, Space.Self);
				lHandController.transform.Rotate(uihandxrotate.val, uihandyrotate.val, uihandzrotate.val, Space.Self);
				rHandController.transform.Rotate(uihandxrotate.val, -uihandyrotate.val, -uihandzrotate.val, Space.Self);
				lElbowController.transform.Rotate((uihandxrotate.val / 2.0f), uielbowxrotate.val, 0.0f, Space.Self);
				rElbowController.transform.Rotate((uihandxrotate.val / 2.0f), -uielbowxrotate.val, 0.0f, Space.Self);
				chestController.transform.Rotate(uichestxrotate.val, 0.0f, 0.0f, Space.Self);
				pelvisController.transform.Rotate(uiabdomenxrotate.val + uipelvisxrotate.val, 0.0f, 0.0f, Space.Self);
				abdomenLowerController.transform.Rotate(uiabdomenxrotate.val, 0.0f, 0.0f, Space.Self);
				abdomenController.transform.Rotate(uiabdomenxrotate.val, 0.0f, 0.0f, Space.Self);
				if (uiemotionsupport.val == false)
				{
					headController.transform.Rotate(uiheadxrotate.val, 0.0f, 0.0f, Space.Self);
					neckController.transform.Rotate(uineckxrotate.val, 0.0f, 0.0f, Space.Self);
				}
				lHipController.transform.Rotate(uihipxrotate.val, uihipyrotate.val, uihipzrotate.val, Space.Self);
				rHipController.transform.Rotate(uihipxrotate.val, -uihipyrotate.val, -uihipzrotate.val, Space.Self);
				lKneeController.transform.Rotate(uikneexrotate.val, 0.0f, 0.0f, Space.Self);
				rKneeController.transform.Rotate(uikneexrotate.val, 0.0f, 0.0f, Space.Self);
				lFootController.transform.Rotate(uifootxrotate.val, 0.0f, 0.0f, Space.Self);
				rFootController.transform.Rotate(uifootxrotate.val, 0.0f, 0.0f, Space.Self);
				

				
				
        }
        catch(Exception e) {
            SuperController.LogError("Fixed Update: " + e);
        }
		
    }

    // JSONClass jSONClasses;

    // Restore / Teleport is difficult to achieve because while we know where the control points should be, we don't know where all the rigid
    // bodies should be. We would need to turn off the atom, move all rigid bodies into place, then turn the atom back on. This feels a little
    // fragile, unless we went for an approximate solution, and rely on parenting by moving the parent(s) of the rigid bodies *close* to where
    // they should be, then the physics upset would be minimal. Pushed to a later version...
    // bool saveCollisionEnabled;
    void BeginRestore() {
        // var a = containingAtom;
        // a.SetOn(false);
        // jSONClasses = new JSONClass();
        // a.PreRestore();
        // a.RestoreTransform(jSONClasses);
        // a.RestoreParentAtom(jSONClasses);
        // containingAtom.ResetPhysical();
        // discontinuity = false;
    }

    void EndRestore() {
        var a = containingAtom;
        // a.Restore(jSONClasses, true, false, false, null, true);
        // a.Restore(jSONClasses, true, false, false, null, false);
        // a.LateRestore(jSONClasses, true, false, false);
        // a.PostRestore();
        // a.SetOn(true);
        // a.collisionEnabledJSON.val = saveCollisionEnabled;
        SuperController.singleton.PauseSimulation(5, string.Concat("Restore Animation ", a.uid));
        discontinuity = false;
    }

	void OnDestroy() {
        if(shadow != null)
            Destroy(shadow.gameObject);
        // containingAtom.collisionEnabledJSON.val = saveCollisionEnabled;
	}

    public void Bake() {
		//SuperController.LogError("Bake Start");
        var mam = SuperController.singleton.motionAnimationMaster;
        foreach(var item in controllerMap) {
			if (item.Value.name != "hairTool1" &&
				item.Value.name != "hairTool1UI" &&
				item.Value.name != "hairTool2" &&
				item.Value.name != "hairTool2UI" &&
				item.Value.name != "hairTool3" &&
				item.Value.name != "hairTool3UI" &&
				item.Value.name != "hairTool4" &&
				item.Value.name != "hairTool4UI" &&
				item.Value.name != "hairScalpMaskTool" &&
				item.Value.name != "hairScalpMaskToolUI")
			{
				//SuperController.LogError("Set " + item.Value.name);
				var mac = macMap[item.Value.name];
				mac.armedForRecord = true;
			}
        }
		//SuperController.LogError("Set for Record");
        baking = true;
        playing = true;
        reverse = false;
        mam.autoRecordStop = false;
        mam.showRecordPaths = false;
        mam.showStartMarkers = false;
		//SuperController.LogError("Start Record");
        mam.StartRecord();
		//SuperController.LogError("Update Status");
        UpdateStatus();
    }

    public void BakeStop() {
        var mam = SuperController.singleton.motionAnimationMaster;
        float pos = mam.playbackCounter;
        mam.StopRecord();
        // StopRecord already disarms the animation controllers
        // foreach(var item in controllerMap) {
        //     var mac = macMap[item.Value.name];
        //     mac.armedForRecord = false;
        // }
        baking = false;
        playing = false;
        mam.showRecordPaths = false;
        mam.showStartMarkers = false;
        mam.StopPlayback();
        mam.playbackCounter = pos;  // StopRecord winds back to where recording started; undo this
        UpdateStatus();
		SuperController.LogError("Bake Stop");
    }

	public void RegisterUIElements()
	{
		uikeeponfloor = new JSONStorableBool("Attempt To Stay On Floor", false);
		RegisterBool(uikeeponfloor);

		uiflooradjustspeed = new JSONStorableFloat("Floor Adjustment Speed", 0.1f, 0.0f, 1.0f, true, true);
		RegisterFloat(uiflooradjustspeed);

		uifloorheight = new JSONStorableFloat("Height of Floor", 0.01f, -10.0f, 10.0f, true, true);
		RegisterFloat(uifloorheight);

		uipostheightoffset = new JSONStorableFloat("Post Height Offset", 0.0f, -1.0f, 1.0f, true, true);
		RegisterFloat(uipostheightoffset);

		uishoulderxrotate = new JSONStorableFloat("Shoulder X Rotation", 0.0f, -90.0f, 90.0f, true, true);
		RegisterFloat(uishoulderxrotate);

		uishoulderyrotate = new JSONStorableFloat("Shoulder Y Rotation", 0.0f, -90.0f, 90.0f, true, true);
		RegisterFloat(uishoulderyrotate);

		uishoulderzrotate = new JSONStorableFloat("Shoulder Z Rotation", 0.0f, -90.0f, 90.0f, true, true);
		RegisterFloat(uishoulderzrotate);

		uiarmxrotate = new JSONStorableFloat("Arm X Rotation", 0.0f, -90.0f, 90.0f, true, true);
		RegisterFloat(uiarmxrotate);

		uiarmyrotate = new JSONStorableFloat("Arm Y Rotation", 0.0f, -90.0f, 90.0f, true, true);
		RegisterFloat(uiarmyrotate);

		uiarmzrotate = new JSONStorableFloat("Arm Z Rotation", 0.0f, -90.0f, 90.0f, true, true);
		RegisterFloat(uiarmzrotate);

		uielbowxrotate = new JSONStorableFloat("Elbow X Rotation", 0.0f, -90.0f, 90.0f, true, true);
		RegisterFloat(uielbowxrotate);

		uihandxrotate = new JSONStorableFloat("Hand X Rotation", 0.0f, -180.0f, 180.0f, true, true);
		RegisterFloat(uihandxrotate);

		uihandyrotate = new JSONStorableFloat("Hand Y Rotation", 0.0f, -180.0f, 180.0f, true, true);
		RegisterFloat(uihandyrotate);

		uihandzrotate = new JSONStorableFloat("Hand Z Rotation", 0.0f, -180.0f, 180.0f, true, true);
		RegisterFloat(uihandzrotate);

		uiemotionsupport = new JSONStorableBool("Skip Neck and Head (for E-Motion)", false);
		RegisterBool(uiemotionsupport);

		uiconfigjoints = new JSONStorableBool("Configure Joints Automatically", false);
		RegisterBool(uiconfigjoints);
		
		uicustomweights = new JSONStorableBool("Use Custom Physics Weight", false);
		RegisterBool(uicustomweights);

		uicustombodyweight = new JSONStorableFloat("Custom Body Weight Mult", 1.0f, 0.01f, 10.0f, true, true);
		RegisterFloat(uicustombodyweight);
		
		uicustomarmsweight = new JSONStorableFloat("Custom Arms Weight Mult", 1.0f, 0.01f, 10.0f, true, true);
		RegisterFloat(uicustomarmsweight);

		uicustomlegsweight = new JSONStorableFloat("Custom Legs Weight Mult", 1.0f, 0.01f, 10.0f, true, true);
		RegisterFloat(uicustomlegsweight);

		uihipholdpower = new JSONStorableFloat("Hip Pos Hold Power", 1.0f, 0.0f, 10.0f, true, true);
		RegisterFloat(uihipholdpower);

		uijointdamper = new JSONStorableFloat("Joint Pos Dampening Power", 1.0f, 0.0f, 10.0f, true, true);
		RegisterFloat(uijointdamper);

		uijointpower = new JSONStorableFloat("Joint Pos Hold Power", 1.0f, 0.0f, 10.0f, true, true);
		RegisterFloat(uijointpower);

		uijointrotpower = new JSONStorableFloat("Joint Rot Hold Power", 1.0f, 0.0f, 10.0f, true, true);
		RegisterFloat(uijointrotpower);

		uijointarmpower = new JSONStorableFloat("Arm Joints Pos Hold Power", 1.0f, 0.0f, 10.0f, true, true);
		RegisterFloat(uijointarmpower);

		uijointfootrotpower = new JSONStorableFloat("Ankle Rot Hold Power", 1.0f, 0.0f, 10.0f, true, true);
		RegisterFloat(uijointfootrotpower);

		uijointarmrotpower = new JSONStorableFloat("Arm Joints Rot Hold Power", 1.0f, 0.0f, 10.0f, true, true);
		RegisterFloat(uijointarmrotpower);

		uijointhandrotpower = new JSONStorableFloat("Wrist Joints Rot Hold Power", 1.0f, 0.0f, 10.0f, true, true);
		RegisterFloat(uijointhandrotpower);

		uiheadxrotate = new JSONStorableFloat("Head X Rotation", 0.0f, -90.0f, 90.0f, true, true);
		RegisterFloat(uiheadxrotate);

		uineckxrotate = new JSONStorableFloat("Neck X Rotation", 0.0f, -90.0f, 90.0f, true, true);
		RegisterFloat(uineckxrotate);

		uichestxrotate = new JSONStorableFloat("Chest X Rotation", 0.0f, -180.0f, 180.0f, true, true);
		RegisterFloat(uichestxrotate);

		uiabdomenxrotate = new JSONStorableFloat("Abdomen X Rotation", 0.0f, -90.0f, 90.0f, true, true);
		RegisterFloat(uiabdomenxrotate);
		
		uipelvisxrotate = new JSONStorableFloat("Pelvis X Rotation", 0.0f, -90.0f, 90.0f, true, true);
		RegisterFloat(uipelvisxrotate);

		uihipxrotate = new JSONStorableFloat("hip X Rotation", 0.0f, -90.0f, 90.0f, true, true);
		RegisterFloat(uihipxrotate);

		uihipyrotate = new JSONStorableFloat("hip Y Rotation", 0.0f, -90.0f, 90.0f, true, true);
		RegisterFloat(uihipyrotate);

		uihipzrotate = new JSONStorableFloat("hip Z Rotation", 0.0f, -90.0f, 90.0f, true, true);
		RegisterFloat(uihipzrotate);
		
		uikneexrotate = new JSONStorableFloat("Knee X Rotation", 0.0f, -90.0f, 90.0f, true, true);
		RegisterFloat(uikneexrotate);

		uifootxrotate = new JSONStorableFloat("Foot X Rotation", 0.0f, -90.0f, 90.0f, true, true);
		RegisterFloat(uifootxrotate);
		
		uispeeddist = new JSONStorableBool("Distance Based Playback", false);
		RegisterBool(uispeeddist);

		uichangespeed = new JSONStorableFloat("Speed Change Rate", 0.2f, 0.01f, 5.0f, true, true);
		RegisterFloat(uichangespeed);

		uiminspeed = new JSONStorableFloat("Speed at Min Dist", 10.0f, 1.0f, 100.0f, true, true);
		RegisterFloat(uiminspeed);

		uimindist = new JSONStorableFloat("Min Distance", 0.1f, 0.0f, 1.0f, true, true);
		RegisterFloat(uimindist);

		uimaxdist = new JSONStorableFloat("Max Distance", 0.35f, 0.0f, 5.0f, true, true);
		RegisterFloat(uimaxdist);
		

		uiskiphead = new JSONStorableBool("Skip Head", false);
		RegisterBool(uiskiphead);

		uiskiparms = new JSONStorableBool("Skip Arms", false);
		RegisterBool(uiskiparms);

		uiskiplegs = new JSONStorableBool("Skip Legs", false);
		RegisterBool(uiskiplegs);

		List<string> targetChoices = new List<string>();
		foreach (string atomUID in SuperController.singleton.GetAtomUIDs())
		{
			currentAtom = SuperController.singleton.GetAtomByUid(atomUID);
			if (currentAtom != containingAtom && atomUID != null && currentAtom.type == "Person")
			{
				targetChoices.Add(atomUID);
			}
		}
		uifocustarget = new JSONStorableStringChooser("Target Selector", targetChoices, "None", "Choose Person");
		RegisterStringChooser(uifocustarget);

	}
	public void CreateButtons()
	{
		featureButton = CreateButton("Feature Controls", false);
		featureButton.button.onClick.AddListener(() => 
			{
				if (uiShowingFeatures)
				{
					RemoveFeatureControlUI();
				}
				else
				{
					CreateFeatureControlUI();
				}
			});
			
		UIDynamic spacer = CreateSpacer(false);
		spacer.height = 49f;

		jointButton = CreateButton("Joint Hold Controls", true);
		jointButton.button.onClick.AddListener(() => 
			{
				if (uiShowingJointControl)
				{
					RemoveJointControlUI();
				}
				else
				{
					CreateJointControlUI();
				}
			});
		angleButton = CreateButton("Joint Angle Controls", true);
		angleButton.button.onClick.AddListener(() => 
			{
				if (uiShowingAngleControl)
				{
					RemoveAngleControlUI();
				}
				else
				{
					CreateAngleControlUI();
				}
			});
	}
	public void ColorButtons()
	{
		if (uiShowingFeatures)
		{featureButton.buttonColor = Color.green;}
		else
		{featureButton.buttonColor = Color.gray;}
		if (uiShowingJointControl)
		{jointButton.buttonColor = Color.green;}
		else
		{jointButton.buttonColor = Color.gray;}
		if (uiShowingAngleControl)
		{angleButton.buttonColor = Color.green;}
		else
		{angleButton.buttonColor = Color.gray;}
	}
	
	public void CreateFeatureControlUI()
	{
		if (uiShowingAngleControl)
		{
			RemoveAngleControlUI();
		}
		if (uiShowingJointControl)
		{
			RemoveJointControlUI();
		}
		CreateToggle(uiemotionsupport, false);
		CreateToggle(uikeeponfloor, false);
		CreateSlider(uiflooradjustspeed, false);
		CreateSlider(uifloorheight, false);
		CreateSlider(uipostheightoffset, false);
				
		CreateToggle(uicustomweights, true);
		CreateSlider(uicustombodyweight, true);
		CreateSlider(uicustomarmsweight, true);
		CreateSlider(uicustomlegsweight, true);
		CreateToggle(uispeeddist, true);
		CreateSlider(uichangespeed, true);
		UIDynamicPopup udp = CreatePopup(uifocustarget, true);
		CreateSlider(uiminspeed, true);
		CreateSlider(uimindist, true);
		CreateSlider(uimaxdist, true);
		CreateToggle(uiskiphead, true);
		CreateToggle(uiskiparms, true);
		CreateToggle(uiskiplegs, true);

		uiShowingFeatures = true;
		ColorButtons();
	}
	public void RemoveFeatureControlUI()
	{
		RemoveToggle(uiemotionsupport);
		RemoveToggle(uikeeponfloor);
		RemoveSlider(uiflooradjustspeed);
		RemoveSlider(uifloorheight);
		RemoveSlider(uipostheightoffset);
		RemoveToggle(uiskiphead);
		RemoveToggle(uiskiparms);
		RemoveToggle(uiskiplegs);
		RemoveToggle(uispeeddist);
		RemoveSlider(uichangespeed);
		RemoveSlider(uiminspeed);
		RemoveSlider(uimindist);
		RemoveSlider(uimaxdist);
		RemovePopup(uifocustarget);
		RemoveToggle(uicustomweights);
		RemoveSlider(uicustombodyweight);
		RemoveSlider(uicustomarmsweight);
		RemoveSlider(uicustomlegsweight);
		uiShowingFeatures = false;
		ColorButtons();
	}
	public void CreateJointControlUI()
	{
		if (uiShowingAngleControl)
		{
			RemoveAngleControlUI();
		}
		if (uiShowingFeatures)
		{
			RemoveFeatureControlUI();
		}
		CreateToggle(uiconfigjoints, false);
		CreateSlider(uijointdamper, false);
		CreateSlider(uihipholdpower, false);
		CreateSlider(uijointpower, false);
		CreateSlider(uijointrotpower, false);
		CreateSlider(uijointarmpower, true);
		CreateSlider(uijointarmrotpower, true);
		CreateSlider(uijointhandrotpower, true);
		CreateSlider(uijointfootrotpower, true);
		uiShowingJointControl = true;
		ColorButtons();
	}
	public void RemoveJointControlUI()
	{
		RemoveToggle(uiconfigjoints);
		RemoveSlider(uijointdamper);
		RemoveSlider(uihipholdpower);
		RemoveSlider(uijointpower);
		RemoveSlider(uijointrotpower);
		RemoveSlider(uijointarmpower);
		RemoveSlider(uijointarmrotpower);
		RemoveSlider(uijointfootrotpower);
		RemoveSlider(uijointhandrotpower);
		uiShowingJointControl = false;
		ColorButtons();
	}
	public void CreateAngleControlUI()
	{
		if (uiShowingFeatures)
		{
			RemoveFeatureControlUI();
		}
		if (uiShowingJointControl)
		{
			RemoveJointControlUI();
		}
		CreateSlider(uishoulderxrotate, false);
		CreateSlider(uishoulderyrotate, false);
		CreateSlider(uishoulderzrotate, false);
		CreateSlider(uiarmxrotate, false);
		CreateSlider(uiarmyrotate, false);
		CreateSlider(uiarmzrotate, false);
		CreateSlider(uielbowxrotate, false);
		CreateSlider(uihandxrotate, false);
		CreateSlider(uihandyrotate, false);
		CreateSlider(uihandzrotate, false);
		CreateSlider(uiheadxrotate, true);
		CreateSlider(uineckxrotate, true);
		CreateSlider(uichestxrotate, true);
		CreateSlider(uiabdomenxrotate, true);
		CreateSlider(uipelvisxrotate, true);
		CreateSlider(uihipxrotate, true);
		CreateSlider(uihipyrotate, true);
		CreateSlider(uihipzrotate, true);
		CreateSlider(uikneexrotate, true);
		CreateSlider(uifootxrotate, true);
		uiShowingAngleControl = true;
		ColorButtons();
	}
	public void RemoveAngleControlUI()
	{
		RemoveSlider(uishoulderxrotate);
		RemoveSlider(uishoulderyrotate);
		RemoveSlider(uishoulderzrotate);
		RemoveSlider(uiarmxrotate);
		RemoveSlider(uiarmyrotate);
		RemoveSlider(uiarmzrotate);
		RemoveSlider(uielbowxrotate);
		RemoveSlider(uihandxrotate);
		RemoveSlider(uihandyrotate);
		RemoveSlider(uihandzrotate);
		RemoveSlider(uiheadxrotate);
		RemoveSlider(uineckxrotate);
		RemoveSlider(uichestxrotate);
		RemoveSlider(uiabdomenxrotate);
		RemoveSlider(uipelvisxrotate);
		RemoveSlider(uihipxrotate);
		RemoveSlider(uihipyrotate);
		RemoveSlider(uihipzrotate);
		RemoveSlider(uikneexrotate);
		RemoveSlider(uifootxrotate);
		uiShowingAngleControl = false;
		ColorButtons();
	}
}

public class BvhTransform {
	public BvhBone bone;
	public Vector3 position;
	public Quaternion rotation;
}

// enums are not allowed in scripts (they crash VaM)
public class RotationOrder {
    public const int XYZ = 0, XZY = 1;
    public const int YXZ = 2, YZX = 3;
    public const int ZXY = 4, ZYX = 5;
}

public class BvhBone {
	public string name;
	public BvhBone parent;
	public bool hasPosition, hasRotation;
	public int frameOffset;
	public Vector3 offset, posZero = Vector3.zero;
    public bool isHipBone = false;
    public int rotationOrder = RotationOrder.ZXY;

	public string ToDebugString() {
		return string.Format("{0} {1} {2} fo:{3} par:{4}", name, hasPosition ? "position" : "", hasRotation ? "rotation": "", frameOffset, parent != null ? parent.name : "(null)");
	}
}

public class BvhFile {
    string[] raw;
	int posMotion;
	public BvhBone[] bones;
	float[][] frames;
	public int nFrames;
    public float frameTime;
    public string path;
    public bool isTranslationLocal;

	public BvhFile(string _path) {
        path = _path;
		Load(path);
	}

	// Parse text that was already read (avoids reading the file a second time).
	public BvhFile(string _path, string content) {
        path = _path;
        char[] delims = { '\r', '\n' };
        var raw = content.Split(delims, System.StringSplitOptions.RemoveEmptyEntries);
		bones = ReadHierarchy(raw);
		frames = ReadMotion(raw);
        frameTime = ReadFrameTime(raw);
		nFrames = frames.Length;
        isTranslationLocal = IsEstimatedLocalTranslation();
        ReadZeroPos();
	}

	public void Load(string path) {
        char[] delims = { '\r', '\n' };
        var raw = SuperController.singleton.ReadFileIntoString(path).Split(delims, System.StringSplitOptions.RemoveEmptyEntries);
		bones = ReadHierarchy(raw);
		frames = ReadMotion(raw);
        frameTime = ReadFrameTime(raw);
		nFrames = frames.Length;
        isTranslationLocal = IsEstimatedLocalTranslation();
        ReadZeroPos();
	}

    void ReadZeroPos() {
        if(nFrames > 0) {
            foreach(var tf in ReadFrame(0)) {
                if(tf.bone.hasPosition)
                    tf.bone.posZero = tf.position;
            }
        }
    }

    bool IsEstimatedLocalTranslation() {
        BvhBone hip = null;
        foreach(var bone in bones)
            if(bone.isHipBone)
                hip = bone;
        if(hip == null)
            return true;    // best estimate without a hip bone
        var index = hip.frameOffset + 1;
        // Use hip 'y' to estimate the translation mode (local or "absolute")
        float sum = 0;
        for(var i = 0; i < nFrames; i++) {
    		var data = frames[i];
            sum += data[index];
        }
        float average = sum / nFrames;
        float absScore = Mathf.Abs(hip.offset.y - average);    // absolute will have average close to offset
        float locScore = Mathf.Abs(average);    // lowest score wins
        return locScore < absScore;
    }

	public void LogHierarchy() {
		foreach(var bone in bones) {
			Debug.Log(bone.ToDebugString());
		}
	}

    float ReadFrameTime(string[] lines) {
        foreach(var line in lines) {
            if(line.StartsWith("Frame Time:")) {
                var parts = line.Split(':');
                return float.Parse(parts[1]);
            }
        }
        return (1f / 30);   // default to 30 FPS
    }

    int GetRotationOrder(string c1, string c2, string c3) {
        c1 = c1.ToLower().Substring(0, 1); c2 = c2.ToLower().Substring(0, 1); c3 = c3.ToLower().Substring(0, 1);
        if(c1 == "x" && c2 == "y" && c3 == "z") return RotationOrder.XYZ;
        if(c1 == "x" && c2 == "z" && c3 == "y") return RotationOrder.XZY;
        if(c1 == "y" && c2 == "x" && c3 == "z") return RotationOrder.YXZ;
        if(c1 == "y" && c2 == "z" && c3 == "x") return RotationOrder.YZX;
        if(c1 == "z" && c2 == "x" && c3 == "y") return RotationOrder.ZXY;
        if(c1 == "z" && c2 == "y" && c3 == "x") return RotationOrder.ZYX;
        return RotationOrder.ZXY;
    }

	BvhBone[] ReadHierarchy(string[] lines) {
        char[] delims = {' ', '\t'};
        var boneList = new List<BvhBone>();
		BvhBone current = null;
		int frameOffset = 0;
        for(var i = 0; i < lines.Length; i++) {
            if(lines[i] == "MOTION")
				break;
            var parts = lines[i].Split(delims, System.StringSplitOptions.RemoveEmptyEntries);
            if(parts.Length >= 2 && (parts[0] == "JOINT" || parts[0] == "ROOT")) {
				current = new BvhBone();
				current.name = parts[1];
				current.offset = Vector3.zero;
				current.frameOffset = frameOffset;
                if(current.name == "hip")
                    current.isHipBone = true;
                boneList.Add(current);
            }
			if(parts.Length >= 4 && parts[0] == "OFFSET" && current != null)
				current.offset = new Vector3(-float.Parse(parts[1]), float.Parse(parts[2]), float.Parse(parts[3])) * 0.01f;
			if(parts.Length >= 2 && parts[0] == "CHANNELS" && current != null) {
				var nChannels = int.Parse(parts[1]);
				frameOffset += nChannels;
				// XXX: examples may exist that are not covered here (but I think they're rare) -- Found some!
                // We now support 6 channels with X,Y,Zpos in first 3 and any rotation order
                // Or 3 channels with any rotation order
				if(nChannels == 3) {
					current.hasPosition = false;
					current.hasRotation = true;
                    current.rotationOrder = GetRotationOrder(parts[2], parts[3], parts[4]);
				}
				else if(nChannels == 6) {
					current.hasPosition = true;
					current.hasRotation = true;
                    current.rotationOrder = GetRotationOrder(parts[5], parts[6], parts[7]);
				}
				else
                    SuperController.LogError(string.Format("Unexpect number of channels in BVH Hierarchy {1} {0}", nChannels, current.name));
			}
			if(parts.Length >= 2 && parts[0] == "End" && parts[1] == "Site")
				current = null;
        }
		return boneList.ToArray();
	}

	float[][] ReadMotion(string[] lines) {
        char[] delims = {' ', '\t'};
		var output = new List<float[]>();
		var i = 0;
        for(; i < lines.Length; i++) {
            if(lines[i] == "MOTION")
				break;
		}
		i++;
		for(; i < lines.Length; i++) {
			var raw = lines[i].Split(delims, System.StringSplitOptions.RemoveEmptyEntries);
			if(raw[0].StartsWith("F"))	// Frame Time: and Frames:
				continue;
			var frame = new float[raw.Length];
			for(var j = 0; j < raw.Length; j++)
				frame[j] = float.Parse(raw[j]);
			output.Add(frame);
		}
		return output.ToArray();
	}

	public BvhTransform[] ReadFrame(int frame) {
		var data = frames[frame];
		var ret = new BvhTransform[bones.Length];
		for(var i = 0; i < bones.Length; i++) {
			var tf = new BvhTransform();
			var bone = bones[i];
			tf.bone = bone;
			var offset = bone.frameOffset;
			if(bone.hasPosition) {
				// Use -'ve X to convert RH->LH
				tf.position = new Vector3(-data[offset], data[offset + 1], data[offset + 2]) * 0.01f;
				offset += 3;
			}
            float v1 = data[offset], v2 = data[offset + 1], v3 = data[offset + 2];

            Quaternion qx, qy, qz;
            switch(bone.rotationOrder) {
                case RotationOrder.XYZ:
                    qx = Quaternion.AngleAxis(-v1, Vector3.left);
                    qy = Quaternion.AngleAxis(-v2, Vector3.up);
                    qz = Quaternion.AngleAxis(-v3, Vector3.forward);
                    tf.rotation = qx * qy * qz;
                break;
                case RotationOrder.XZY:
                    qx = Quaternion.AngleAxis(-v1, Vector3.left);
                    qy = Quaternion.AngleAxis(-v3, Vector3.up);
                    qz = Quaternion.AngleAxis(-v2, Vector3.forward);
                    tf.rotation = qx * qz * qy;
                break;
                case RotationOrder.YXZ:
                    qx = Quaternion.AngleAxis(-v2, Vector3.left);
                    qy = Quaternion.AngleAxis(-v1, Vector3.up);
                    qz = Quaternion.AngleAxis(-v3, Vector3.forward);
                    tf.rotation = qy * qx * qz;
                break;
                case RotationOrder.YZX:
                    qx = Quaternion.AngleAxis(-v3, Vector3.left);
                    qy = Quaternion.AngleAxis(-v1, Vector3.up);
                    qz = Quaternion.AngleAxis(-v2, Vector3.forward);
                    tf.rotation = qy * qz * qx;
                break;
                case RotationOrder.ZXY:
                    qx = Quaternion.AngleAxis(-v2, Vector3.left);
                    qy = Quaternion.AngleAxis(-v3, Vector3.up);
                    qz = Quaternion.AngleAxis(-v1, Vector3.forward);
                    tf.rotation = qz * qx * qy;
                break;
                case RotationOrder.ZYX:
                    qx = Quaternion.AngleAxis(-v3, Vector3.left);
                    qy = Quaternion.AngleAxis(-v2, Vector3.up);
                    qz = Quaternion.AngleAxis(-v1, Vector3.forward);
                    tf.rotation = qz * qy * qx;
                break;
            }

			ret[i] = tf;
		}
		return ret;
	}
}


}