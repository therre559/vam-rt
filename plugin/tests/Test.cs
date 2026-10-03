using System;
using System.Collections.Generic;
using UnityEngine;
using VaMRT;
class T {
    static int bad = 0;
    static void Eq(string what, object got, object want) { bool ok = Equals(got, want); if (!ok) bad++; Console.WriteLine((ok ? "ok  " : "BAD ") + what + " -> " + got + (ok ? "" : "   (wanted " + want + ")")); }
    static void Has(string what, string text, string frag) { bool ok = text.Contains(frag); if (!ok) bad++; Console.WriteLine((ok ? "ok  " : "BAD ") + what + " contains '" + frag + "'"); }
    static void Not(string what, string text, string frag) { bool ok = !text.Contains(frag); if (!ok) bad++; Console.WriteLine((ok ? "ok  " : "BAD ") + what + " lacks '" + frag + "'"); }
    static string Run(Presence p, ref float t, float dist, bool look, float seconds, bool quiet = true) {
        string first = null;
        for (float s = 0; s < seconds - 1e-4f; s += 0.5f) {
            t += 0.5f;
            string k = p.Update(t, 0.5f, dist, look, quiet, 2.5f, 7f, 6f, 45f);
            if (k != null) { if (first == null) first = k; p.Fired(k, t); }
        }
        return first;
    }
    static void PresenceTests() {
        var p = new Presence(); float t = 0f;
        Eq("events: first reading is silent", Run(p, ref t, 9f, false, 5f), null);
        Eq("events: walks up -> approach", Run(p, ref t, 1.5f, false, 3f), "approach");
        Eq("events: staying near is silent", Run(p, ref t, 1.5f, false, 20f), null);
        Eq("events: leaving during the cooldown is suppressed", Run(p, ref t, 9f, false, 5f), null);
        Eq("events: still far, nothing happens", Run(p, ref t, 9f, false, 30f), null);
        Eq("events: walks up again after the cooldown -> approach", Run(p, ref t, 1.5f, false, 3f), "approach");
        Run(p, ref t, 1.5f, false, 50f);   // stay near until the cooldown is over
        Eq("events: leaves after the cooldown -> leave", Run(p, ref t, 9f, false, 5f), "leave");
        Eq("events: approaching right after an event is suppressed, not delayed", Run(p, ref t, 1.5f, false, 3f), null);
        // jitter on the boundary must not fire anything
        var j = new Presence(); float tj = 0f; Run(j, ref tj, 3.0f, false, 3f);
        string any = null; for (int i = 0; i < 20; i++) { string a = Run(j, ref tj, i % 2 == 0 ? 2.4f : 2.7f, false, 0.5f); if (a != null) any = a; }
        Eq("events: jitter around the approach distance is silent", any, null);

        // staring
        var q = new Presence(); float tq = 0f;
        Eq("stare: 5 s of looking is not yet a stare", Run(q, ref tq, 3f, true, 5f), null);
        Eq("stare: 7 s of looking -> stare", Run(q, ref tq, 3f, true, 2f), "stare");
        Eq("stare: it does NOT repeat while the user keeps looking", Run(q, ref tq, 3f, true, 300f), null);
        Run(q, ref tq, 3f, false, 10f);   // looks away long enough to re-arm
        Eq("stare: after looking away and back it can fire again", Run(q, ref tq, 3f, true, 8f), "stare");
        var q2 = new Presence(); float tq2 = 0f;
        Run(q2, ref tq2, 3f, true, 8f);   // first stare fires
        Run(q2, ref tq2, 3f, false, 10f);
        Eq("stare: re-armed but still inside the longer stare spacing -> silent", Run(q2, ref tq2, 3f, true, 20f), null);
        var r = new Presence(); float tr = 0f;
        Run(r, ref tr, 3f, true, 5f); Run(r, ref tr, 3f, false, 6f);
        Eq("stare: looking away lets the timer fade", Run(r, ref tr, 3f, true, 3f), null);
        var g = new Presence(); float tg = 0f;
        Eq("stare: none when the user is far away", Run(g, ref tg, 12f, true, 20f), null);

        // conversations: events must wait
        var c = new Presence(); float tc = 0f;
        Run(c, ref tc, 9f, false, 5f);
        Eq("busy: walking up during a conversation is dropped", Run(c, ref tc, 1.5f, false, 4f, false), null);
        Eq("busy: and it is not delivered later either", Run(c, ref tc, 1.5f, false, 10f, true), null);
        var c2 = new Presence(); float tc2 = 0f;
        Eq("busy: 30 s of looking while talking is not a stare", Run(c2, ref tc2, 3f, true, 30f, false), null);
        Eq("busy: the stare timer starts only once it is quiet (5 s: not yet)", Run(c2, ref tc2, 3f, true, 5f, true), null);
        Eq("busy: 3 more quiet seconds -> stare", Run(c2, ref tc2, 3f, true, 3f, true), "stare");

        // a fresh start (new chat, or events toggled) forgets the old cooldowns
        var f = new Presence(); float tf = 0f;
        Run(f, ref tf, 3f, true, 8f);                       // a stare fires and starts the long spacing
        f.ResetAll(); tf += 1f;
        Eq("reset: after ResetAll the first reading is silent again", Run(f, ref tf, 3f, true, 2f), null);
        Eq("reset: and a stare is possible without waiting out the old spacing", Run(f, ref tf, 3f, true, 8f), "stare");

        // wording varies
        var w = new Presence();
        string w0 = w.TextFor("approach"); w.Fired("approach", 0f); string w1 = w.TextFor("approach");
        Eq("wording: the second approach text differs from the first", w0 != w1, true);
        Eq("wording: first approach text", w0, "{{ user }} walks up to {{ char }}.");
        Eq("wording: leave text", Presence.EventText("leave", 0), "{{ user }} walks away from {{ char }}.");
        Eq("wording: stare text", Presence.EventText("stare", 0), "{{ user }} has been looking at {{ char }} for a while.");
        Eq("wording: it cycles", Presence.EventText("stare", 4), Presence.EventText("stare", 0));
    }
    static FollowLogic.Input Fin(float ux, float uz, float sx = 0f, float sz = 0f) {
        var i = new FollowLogic.Input(); i.SelfX = sx; i.SelfZ = sz; i.UserX = ux; i.UserZ = uz; return i;
    }
    static void FollowTests() {
        var s = new FollowLogic.Settings();   // band 0.8-2.5 m, walks to 1.8 m from the user, 1.2 m/s, area radius 6 m
        var r = FollowLogic.Decide(s, Fin(0f, 1.5f));
        Eq("follow: user within reach -> stand", r.Walk, false); Has("follow: ... says why", r.Why, "within reach");
        r = FollowLogic.Decide(s, Fin(0f, 0.5f));
        Eq("follow: user too close -> stand", r.Walk, false); Has("follow: ... says why", r.Why, "too close");
        r = FollowLogic.Decide(s, Fin(0f, 2.5f));
        Eq("follow: exactly at the edge of the band -> stand", r.Walk, false);

        r = FollowLogic.Decide(s, Fin(0f, 5f));
        Eq("follow: user 5 m ahead -> walk", r.Walk, true);
        Eq("follow: goal is 1.8 m short of the user (3.2 m ahead)", Math.Round(r.Forward, 2), 3.2);
        Eq("follow: ... and straight on", Math.Round(r.Right, 2), 0.0);
        Eq("follow: ... at the set speed", r.Speed, 1.2f);
        r = FollowLogic.Decide(s, Fin(5f, 0f));
        Eq("follow: user to her right: goal is on her right", Math.Round(r.Right, 2), 3.2); Eq("follow: ... none ahead", Math.Round(r.Forward, 2), 0.0);
        r = FollowLogic.Decide(s, Fin(-5f, 0f));
        Eq("follow: user to her left: negative right", Math.Round(r.Right, 2), -3.2);
        r = FollowLogic.Decide(s, Fin(0f, -5f));
        Eq("follow: user behind her: negative forward", Math.Round(r.Forward, 2), -3.2);
        var turned = Fin(0f, 5f); turned.FacingX = 1f; turned.FacingZ = 0f;      // she faces +X: the goal at +Z is on her LEFT
        r = FollowLogic.Decide(s, turned);
        Eq("follow: the goal is expressed in HER frame (facing +X, goal at +Z = to her left)", Math.Round(r.Right, 2) == -3.2 && Math.Round(r.Forward, 2) == 0.0, true);
        var diag = Fin(4f, 4f); r = FollowLogic.Decide(s, diag);
        Eq("follow: a diagonal user: goal is 1.8 m from the user on the line to her",
           Math.Round(FollowLogic.Dist(r.GoalX, r.GoalZ, 4f, 4f), 2), 1.8);

        // allowed area
        var small = new FollowLogic.Settings(); small.AreaRadius = 2f;
        r = FollowLogic.Decide(small, Fin(0f, 5f));
        Eq("follow: the goal is clamped to the allowed area", r.Clamped && Math.Round(r.Forward, 2) == 2.0, true);
        var edge = Fin(0f, 9f, 0f, 1.9f);
        r = FollowLogic.Decide(small, edge);
        Eq("follow: already at the edge of the area while the user is outside -> stand", r.Walk, false); Has("follow: ... says why", r.Why, "edge");
        var outside = Fin(0f, 9f, 0f, 3f);
        r = FollowLogic.Decide(small, outside);
        Eq("follow: outside the area she is brought back to its edge (never farther out)", r.Walk && Math.Round(r.GoalZ, 2) == 2.0, true);
        var centred = Fin(0f, 8f, 10f, 10f); centred.AnchorX = 10f; centred.AnchorZ = 10f;
        r = FollowLogic.Decide(s, centred);
        Eq("follow: the area is centred on the anchor, not the origin", r.Walk, true);

        // obstacles
        var obs = Fin(0f, 6f); obs.ObstacleDist = 1.0f; obs.ObstacleName = "Cube";
        r = FollowLogic.Decide(s, obs);
        Eq("follow: an obstacle 1.0 m ahead: she walks up to it and stops 0.6 m short", r.Walk && r.Shortened && Math.Round(r.Forward, 2) == 0.4, true);
        Has("follow: ... naming it", r.Why, "'Cube'");
        obs.ObstacleDist = 0.8f;
        r = FollowLogic.Decide(s, obs);
        Eq("follow: an obstacle 0.8 m ahead: she stays put", r.Walk, false); Has("follow: ... says which", r.Why, "'Cube' is 0.8 m ahead");
        obs.ObstacleDist = 5.0f;   // beyond the goal (4.2 m): irrelevant
        r = FollowLogic.Decide(s, obs);
        Eq("follow: an obstacle beyond the goal is ignored", r.Walk && !r.Shortened, true);
        obs.ObstacleDist = 1.0f; obs.ObstacleName = "";
        r = FollowLogic.Decide(s, obs);
        Has("follow: an unnamed obstacle", r.Why, "an obstacle");

        // ground
        var gnd = Fin(0f, 6f); gnd.GroundKnown = true; gnd.GroundOk = false; gnd.GroundNote = "drop at 1.2 m";
        r = FollowLogic.Decide(s, gnd);
        Eq("follow: no safe ground ahead -> stand", r.Walk, false); Has("follow: ... with the note", r.Why, "drop at 1.2 m");
        gnd.GroundKnown = false;
        r = FollowLogic.Decide(s, gnd);
        Eq("follow: when there is no floor at all the check is skipped (nothing to judge by)", r.Walk, true);
        gnd.GroundKnown = true;
        var lax = new FollowLogic.Settings(); lax.RequireGround = false;
        r = FollowLogic.Decide(lax, gnd);
        Eq("follow: the ground check can be switched off", r.Walk, true);

        // what the status box and the motion stream get
        r = FollowLogic.Decide(s, Fin(0f, 5f));
        Eq("follow: status text", FollowLogic.Describe(r), "would WALK 3.2 m ahead, 0.0 m to the right at 1.2 m/s: too far from the user");
        Eq("follow: command for the stream", FollowLogic.CommandJson(r), "{\"cmd\":\"goto\",\"forward\":3.20,\"right\":0.00,\"speed\":1.2,\"lease_s\":3}");
        r = FollowLogic.Decide(s, Fin(0f, 1.5f));
        Eq("follow: stand command", FollowLogic.CommandJson(r), "{\"cmd\":\"stand\",\"lease_s\":3}");
        System.Threading.Thread.CurrentThread.CurrentCulture = new System.Globalization.CultureInfo("de-DE");
        Eq("follow: the command keeps its decimal dots under a comma-decimal region",
           FollowLogic.CommandJson(FollowLogic.Decide(s, Fin(0f, 5f))), "{\"cmd\":\"goto\",\"forward\":3.20,\"right\":0.00,\"speed\":1.2,\"lease_s\":3}");
        System.Threading.Thread.CurrentThread.CurrentCulture = System.Globalization.CultureInfo.InvariantCulture;
    }
    static void Main() {
        // geometry
        Eq("angle: target on the right", Math.Round(SensesLogic.SignedAngleY(new Vector3(0,0,1), new Vector3(1,0,0))), 90.0);
        Eq("angle: target on the left", Math.Round(SensesLogic.SignedAngleY(new Vector3(0,0,1), new Vector3(-1,0,0))), -90.0);
        Eq("angle: target behind", Math.Abs(Math.Round(SensesLogic.SignedAngleY(new Vector3(0,0,1), new Vector3(0,0,-1)))), 180.0);
        Eq("angle: facing +X, target at +Z is on the left", Math.Round(SensesLogic.SignedAngleY(new Vector3(1,0,0), new Vector3(0,0,1))), -90.0);
        // wording
        Eq("dir 0", SensesLogic.Direction(0), "directly in front");
        Eq("dir 45 right", SensesLogic.Direction(45), "in front and to the right");
        Eq("dir -90", SensesLogic.Direction(-90), "to the left");
        Eq("dir -135", SensesLogic.Direction(-135), "behind and to the left");
        Eq("dir 170", SensesLogic.Direction(170), "directly behind");
        Eq("dist 0.3", SensesLogic.ObjectDistance(0.3f), "right beside {{ char }}");
        Eq("dist 0.9", SensesLogic.ObjectDistance(0.9f), "within reach");
        Eq("dist 3.4", SensesLogic.ObjectDistance(3.4f), "about 3 m away");
        // pose
        Eq("pose standing", SensesLogic.ClassifyPose(0.95f, 0.95f, 10f), "standing");
        Eq("pose sitting", SensesLogic.ClassifyPose(0.55f, 0.95f, 20f), "sitting or crouching");
        Eq("pose bent over", SensesLogic.ClassifyPose(0.85f, 0.95f, 80f), "bent over");
        Eq("pose lying", SensesLogic.ClassifyPose(0.2f, 0.95f, 85f), "lying down");
        // names and tags
        Eq("clean 'VaMRT Chair [sit]'", SensesLogic.CleanName("VaMRT Chair [sit]", "Cube"), "chair");
        Eq("clean 'Cube#3'", SensesLogic.CleanName("Cube#3", "Cube"), "cube");
        Eq("clean '[sit]' falls back to type", SensesLogic.CleanName("[sit]", "Sphere"), "sphere");
        bool sit, surf, look, ign;
        SensesLogic.ParseTags("Armchair [look]", "armchair", out sit, out surf, out look, out ign); Eq("armchair auto-sit", sit, true); Eq("explicit [look]", look, true);
        SensesLogic.ParseTags("Dining Table", "dining table", out sit, out surf, out look, out ign); Eq("table auto-surface", surf, true);
        SensesLogic.ParseTags("Bedroom lamp", "bedroom lamp", out sit, out surf, out look, out ign); Eq("bedroom is NOT a bed", sit, false);
        SensesLogic.ParseTags("Vegetable crate", "vegetable crate", out sit, out surf, out look, out ign); Eq("vegetable is NOT a table", surf, false);
        SensesLogic.ParseTags("Stools", "stools", out sit, out surf, out look, out ign); Eq("plural stools", sit, true);
        SensesLogic.ParseTags("Prop [ignore]", "prop", out sit, out surf, out look, out ign); Eq("[ignore]", ign, true);
        Eq("article an", SensesLogic.WithArticle("armchair"), "an armchair");
        Eq("article a", SensesLogic.WithArticle("table"), "a table");

        // full descriptions
        var d = new SensesLogic.Data(); d.Pose = "standing"; d.HasUser = true; d.UserDistance = 1.7f; d.UserAngle = 10f; d.UserLooking = true;
        d.Objects.Add(new SensesLogic.ObjectInfo { Name = "chair", Distance = 0.9f, Angle = -40f, Sit = true });
        d.Objects.Add(new SensesLogic.ObjectInfo { Name = "table", Distance = 1.6f, Angle = 55f, Surface = true });
        string t1 = SensesLogic.Build(d); Console.WriteLine("\n--- scenario 1 ---\n" + t1 + "\n");
        Has("s1 facing user", t1, "standing, facing {{ user }}."); Has("s1 looking", t1, "and is looking at {{ char }}");
        Has("s1 chair", t1, "- There is a chair within reach, in front and to the left. It can be sat on."); Has("s1 table", t1, "- There is a table close by, in front and to the right. It is a flat surface.");
        Has("s1 header is passive", t1, "never a request to do anything"); Not("s1 no bracketed list", t1, "(");

        d = new SensesLogic.Data(); d.Pose = "standing"; d.LegsWide = true; d.HasUser = true; d.UserDistance = 3.2f; d.UserAngle = 170f; d.UserLooking = false;
        string t2 = SensesLogic.Build(d); Console.WriteLine("--- scenario 2 ---\n" + t2 + "\n");
        Has("s2 legs wide", t2, "standing with their legs wide apart"); Has("s2 back to user", t2, "with their back to {{ user }}"); Not("s2 not looking", t2, "looking at"); Has("s2 nothing nearby", t2, "There is nothing else around {{ char }}.");

        d = new SensesLogic.Data(); d.Pose = "bent over"; d.LegsWide = true; d.HasUser = false;
        d.Objects.Add(new SensesLogic.ObjectInfo { Name = "Eve", IsPerson = true, Distance = 2.4f, Angle = 100f });
        string t3 = SensesLogic.Build(d); Console.WriteLine("--- scenario 3 ---\n" + t3 + "\n");
        Not("s3 legs-wide only while standing", t3, "legs wide apart"); Has("s3 other person", t3, "- Another person, Eve, is about 2 m away, to the right.");
        Not("s3 no user line", t3, "{{ user }} is");

        // mood from E-Motion
        Eq("mood: neutral is silent", SensesLogic.MoodPhrase(1.0f, 1.0f), "");
        Eq("mood: pleased", SensesLogic.MoodPhrase(2.5f, 1.0f), "pleased");
        Eq("mood: happy and interested", SensesLogic.MoodPhrase(4f, 3f), "happy and interested");
        Eq("mood: only energy", SensesLogic.MoodPhrase(1f, 6f), "excited");
        Eq("mood: delighted and very excited", SensesLogic.MoodPhrase(8f, 9f), "delighted and very excited");
        var dm = new SensesLogic.Data(); dm.HasMood = true; dm.Valence = 4f; dm.Arousal = 6f;
        string tm = SensesLogic.Build(dm); Console.WriteLine("--- mood ---\n" + tm + "\n");
        Has("mood line in the description", tm, "- {{ char }} seems happy and excited.");
        var dn = new SensesLogic.Data(); dn.HasMood = true; dn.Valence = 1f; dn.Arousal = 1f;
        Not("no mood line while neutral", SensesLogic.Build(dn), "seems");
        var dx = new SensesLogic.Data(); dx.HasMood = false; dx.Valence = 9f; dx.Arousal = 9f;
        Not("no mood line without E-Motion", SensesLogic.Build(dx), "seems");

        // presence / events
        PresenceTests();
        FollowTests();

        // stability: identical input must give identical text (no spurious sends)
        Eq("deterministic", SensesLogic.Build(d), t3);
        Console.WriteLine(bad == 0 ? "\nALL GOOD" : "\nFAILURES: " + bad);
        Environment.Exit(bad == 0 ? 0 : 1);
    }
}
