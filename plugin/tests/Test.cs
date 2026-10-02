using System;
using System.Collections.Generic;
using UnityEngine;
using VaMRT;
class T {
    static int bad = 0;
    static void Eq(string what, object got, object want) { bool ok = Equals(got, want); if (!ok) bad++; Console.WriteLine((ok ? "ok  " : "BAD ") + what + " -> " + got + (ok ? "" : "   (wanted " + want + ")")); }
    static void Has(string what, string text, string frag) { bool ok = text.Contains(frag); if (!ok) bad++; Console.WriteLine((ok ? "ok  " : "BAD ") + what + " contains '" + frag + "'"); }
    static void Not(string what, string text, string frag) { bool ok = !text.Contains(frag); if (!ok) bad++; Console.WriteLine((ok ? "ok  " : "BAD ") + what + " lacks '" + frag + "'"); }
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
        Eq("short dir 30", SensesLogic.ShortDirection(30), "ahead-right");
        Eq("dist 0.3", SensesLogic.DistanceShort(0.3f), "touching distance");
        Eq("dist 3.4", SensesLogic.DistanceShort(3.4f), "3 m away");
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
        Has("s1 chair", t1, "a chair (within reach, ahead-left, can be sat on)"); Has("s1 table", t1, "a table (close, ahead-right, a surface)");

        d = new SensesLogic.Data(); d.Pose = "standing"; d.LegsWide = true; d.HasUser = true; d.UserDistance = 3.2f; d.UserAngle = 170f; d.UserLooking = false;
        string t2 = SensesLogic.Build(d); Console.WriteLine("--- scenario 2 ---\n" + t2 + "\n");
        Has("s2 legs wide", t2, "standing with their legs wide apart"); Has("s2 back to user", t2, "with their back to {{ user }}"); Not("s2 not looking", t2, "looking at"); Has("s2 nothing nearby", t2, "Nothing else is nearby.");

        d = new SensesLogic.Data(); d.Pose = "bent over"; d.LegsWide = true; d.HasUser = false;
        d.Objects.Add(new SensesLogic.ObjectInfo { Name = "Eve", IsPerson = true, Distance = 2.4f, Angle = 100f });
        string t3 = SensesLogic.Build(d); Console.WriteLine("--- scenario 3 ---\n" + t3 + "\n");
        Not("s3 legs-wide only while standing", t3, "legs wide apart"); Has("s3 other person", t3, "another person, Eve (2 m away, right)");
        Not("s3 no user line", t3, "{{ user }} is");

        // stability: identical input must give identical text (no spurious sends)
        Eq("deterministic", SensesLogic.Build(d), t3);
        Console.WriteLine(bad == 0 ? "\nALL GOOD" : "\nFAILURES: " + bad);
        Environment.Exit(bad == 0 ? 0 : 1);
    }
}
