"""ardy_lab.py - find out which wordings ARDY really performs, by watching them in VaM.

Instead of guessing how to phrase "a sexy dance" (or a shrug, a clap, a stretch...), this plays each candidate wording
through your live stream, measures how much she actually moves, and asks you how it looked. Wordings that produce no
movement are discarded automatically. What you rate good is saved to verified_prompts.json, which motion_prompter.py
uses from then on.

You need three things running (Start_Lab.bat opens the first two for you):
  1. the ARDY stream, launched with --metrics-file (this script reads the numbers it measures),
  2. this lab,
  3. VaM with the BVH Player, so you can see the result.

  python scripts/ardy_lab.py                         # the dance suite (styles: sexy, slow, energetic, ...)
  python scripts/ardy_lab.py --suite dance2          # round 2: dance genres and hip movements (belly dance, salsa...)
  python scripts/ardy_lab.py --suite poses           # held poses: wide stance, bent over, hands on hips, splits...
  python scripts/ardy_lab.py --suite walk            # walking styles: confident, stealthy, limp, runway...
  python scripts/ardy_lab.py --suite everyday        # drink, eat, pick something up, open a door (mimed)
  python scripts/ardy_lab.py --suite paper --seconds 12   # the authors' own example prompts: a sanity check for your setup
  python scripts/ardy_lab.py --suite idle            # small standing motions (ideas for making her feel alive)
  python scripts/ardy_lab.py --suite gestures        # wave, nod, clap, shrug, ...
  python scripts/ardy_lab.py --only dance.sexy       # just one group
  python scripts/ardy_lab.py --prompts my_list.txt   # your own: one 'group | wording' (or just 'wording') per line
  python scripts/ardy_lab.py --list                  # show what each suite contains

Ratings: g = good, o = ok, b = bad, r = replay it, s = skip, q = quit (everything so far is saved).

Results depend on the stream's settings (--history, --cfg-text, --steps, --model). The lab records them with every rating and
warns if you verified wordings under different settings than the stream is running now; --redo re-tests under the new ones.
"""

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

IDLE = "A person stands upright."
HERE = Path(__file__).resolve().parent

# group key -> candidate wordings. The keys are the ones motion_prompter.py looks up (dance.sexy, dance.slow, ...).
SUITES = {
    "dance": [
        ("dance.plain", ["A person dances."]),
        ("dance.sexy", [
            "A person dances sensually.",
            "A person dances sexily, moving their hips.",
            "A person dances seductively.",
            "A person does a sexy dance, swaying their hips from side to side.",
            "A person dances with smooth, flowing hip movements.",
            "A person dances slowly and sensually, swaying their hips.",   # the one that froze her: kept as a reference
        ]),
        ("dance.slow", [
            "A person dances slowly.",
            "A person sways slowly from side to side.",
            "A person dances to a slow song.",
        ]),
        ("dance.energetic", [
            "A person dances energetically.",
            "A person dances wildly.",
            "A person dances with fast, energetic movements.",
        ]),
        ("dance.playful", [
            "A person dances playfully.",
            "A person dances in a silly, playful way.",
        ]),
        ("dance.graceful", [
            "A person dances gracefully.",
            "A person dances with smooth, elegant movements.",
        ]),
    ],
    # Round 2. Every "sexy" wording above froze her or barely moved her, so mood words don't work. Try dance GENRES and
    # body movements instead (belly dance, salsa...), which describe what the body does rather than how it feels.
    "dance2": [
        ("dance.sexy", [
            "A person belly dances.",
            "A person dances, swinging their hips from side to side.",
            "A person dances, rolling their hips in circles.",
            "A person dances salsa, moving their hips.",
            "A person dances like a go-go dancer.",
            "A person dances to Latin music, moving their hips.",
            # the paper's own examples describe movements ("steps right and left", "a forward turn"), not moods: so try that
            "A person dances, moving their hips from side to side and raising their arms above their head.",
            "A person dances, stepping from side to side and turning around slowly.",
            "A person dances with their arms raised, rotating their hips.",
        ]),
        ("dance.belly", ["A person belly dances."]),
        ("dance.salsa", ["A person dances salsa."]),
        ("dance.hiphop", ["A person dances hip hop."]),
        ("dance.disco", ["A person dances disco."]),
        ("dance.waltz", ["A person dances a waltz."]),
        ("dance.ballet", ["A person dances ballet."]),
    ],
    # Held poses. Little movement is NORMAL here, so nothing is discarded automatically: judge by eye. Each wording is
    # played as a held state (the way the stream holds a pose), then she goes back to standing.
    # Careful with pose.splits: it may come out upside down, which the stream's guard blocks and recovers from.
    # Locomotion styles. The ARDY paper's own figures use manner words for walking and jogging ("stealthily", "unsteadily and
    # painfully", "a happy person"), so manner words are far more likely to work here than for dancing.
    "walk": [
        ("walk.confident", ["A person walks confidently.", "A person walks forward with long, confident strides."]),
        ("walk.stealth", ["A person walks stealthily at a slow pace.", "A person sneaks forward on tiptoe."]),
        ("walk.limp", ["A person walks with a limp.", "A person walks unsteadily and painfully."]),
        ("walk.runway", ["A person walks like a model on a runway.", "A person walks forward, swinging their hips with each step."]),
        ("walk.casual", ["A person strolls casually.", "A person walks slowly with their hands in their pockets."]),
    ],
    # Everyday actions are one of the categories ARDY was trained on (the paper lists locomotion, everyday activities,
    # gestures and combat). There is no object in VaM, so she will mime it.
    "everyday": [
        ("everyday.drink", ["A person drinks from a cup.", "A person lifts a glass to their mouth and drinks."]),
        ("everyday.eat", ["A person eats an apple.", "A person eats with their right hand."]),
        ("everyday.pickup", ["A person picks up an object from the floor.", "A person picks up an object from the front and places it down low."]),
        ("everyday.door", ["A person opens a door.", "A person opens a door and walks out."]),
        ("everyday.hair", ["A person brushes their hair back with their right hand.", "A person adjusts their hair with both hands."]),
        ("everyday.phone", ["A person talks on a phone, holding it to their ear."]),
    ],
    # The authors' own example prompts (paper, Fig. 1 and Fig. 6). They are in-distribution by construction, so they are a
    # sanity check for the setup: if these are dead, the problem is the settings, not the wording.
    "paper": [
        ("paper.jog", ["A happy person, leaning to the left, jogs in a fast circular arc to their left, then stops."]),
        ("paper.stealth", ["A person is stealthily walking sideways to their left at a slow pace."]),
        ("paper.door", ["A person opens a door and walks out the door before closing it behind."]),
        ("paper.multi", ["A person walks forward at a steady pace, then turns to face the left diagonal, jogs sideways to the right, and waves their right hand."]),
        ("paper.ballet", ["A ballet dancer performs a forward turn joining feet, in a repeating loop."]),
        ("paper.kick", ["Performing a front knee kick to the left."]),
        ("paper.pickup", ["A person picks up an object from the front at a high level in front, places it at a low level in front."]),
        ("paper.injured", ["A person walks and turns unsteadily and painfully in multiple directions with an injured torso."]),
    ],
    "poses": [
        ("pose.wide", [
            "A person stands with their legs wide apart.",
            "A person stands in a wide stance.",
            "A person stands with their feet wide apart and their hands on their hips.",
        ]),
        ("pose.bend", [
            "A person is bent over at the waist, touching their toes.",
            "A person stands bent forward with their hands on the floor.",
            "A person bends over and stays bent over.",
        ]),
        ("pose.bend_floor", [
            "A person stands bent forward with their hands on the floor.",
            "A person bends over and rests their palms flat on the floor.",
            "A person bends forward at the waist with their hands touching the ground.",
        ]),
        ("pose.wide_bend", [
            "A person is bent over at the waist with their legs wide apart.",
            "A person stands in a wide stance, bent forward at the waist.",
        ]),
        ("pose.wide_bend_floor", [
            "A person stands with their legs wide apart, bent over with their hands on the floor.",
            "A person stands in a wide stance and bends forward, placing both palms flat on the floor between their feet.",
        ]),
        ("pose.hands_hips", ["A person stands with their hands on their hips."]),
        ("pose.arms_crossed", ["A person stands with their arms crossed."]),
        ("pose.splits", [
            "A person sits on the floor in the splits position.",
            "A person lowers into a split on the floor with their legs stretched out to the sides.",
            "A person does the splits.",
        ]),
    ],
    "idle": [
        ("idle.shift", [
            "A person shifts their weight from one foot to the other.",
            "A person sways gently while standing.",
        ]),
        ("idle.look", [
            "A person looks around.",
            "A person looks to the left and then to the right.",
        ]),
        ("idle.arms", [
            "A person crosses their arms.",
            "A person puts their hands on their hips.",
            "A person adjusts their hair with one hand.",
        ]),
        ("idle.stretch", [
            "A person stretches their arms above their head.",
            "A person rolls their shoulders.",
        ]),
    ],
    "gestures": [
        ("gesture.wave", [
            "A person waves with their right hand.",
            "A person waves enthusiastically with both hands.",
            "A person waves shyly with their right hand.",
        ]),
        ("gesture.clap", ["A person claps their hands.", "A person claps their hands above their head."]),
        ("gesture.nod", ["A person nods their head.", "A person shakes their head."]),
        ("gesture.shrug", ["A person shrugs their shoulders."]),
        ("gesture.point", ["A person points forward with their right hand."]),
        ("gesture.kiss", ["A person blows a kiss with their right hand."]),
        ("gesture.bow", ["A person bows."]),
    ],
    "extras": [   # riskier: the stream's upside-down guard protects VaM, but expect some duds
        ("extra.spin", ["A person spins around.", "A person twirls with their arms out."]),
        ("extra.jump", ["A person jumps up and down.", "A person does jumping jacks."]),
        ("extra.hug", ["A person opens their arms for a hug."]),
    ],
}


def norm(text):
    return " ".join(text.split())


def write_prompt(path, line):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(line + "\n")
    os.replace(tmp, path)


class Metrics:
    """Reads the per-chunk lines the stream appends (--metrics-file): time, motion m/s, root y, hold, prompt."""

    def __init__(self, path):
        self.path = Path(path)

    def size(self):
        return self.path.stat().st_size if self.path.exists() else 0

    def settings(self):
        """The '# settings ...' line the stream writes when it starts (the last one), or ''."""
        last = ""
        try:
            with open(self.path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("# settings"):
                        last = line[len("# settings"):].strip()
        except OSError:
            pass
        return last

    def read_from(self, offset):
        rows = []
        if not self.path.exists():
            return rows, offset
        with open(self.path, "rb") as f:
            f.seek(offset)
            data = f.read()
        end = data.rfind(b"\n")
        if end < 0:
            return rows, offset
        for line in data[: end + 1].decode("utf-8", "ignore").splitlines():
            parts = line.split("\t", 4)
            if len(parts) != 5:
                continue
            try:
                rows.append({"t": float(parts[0]), "speed": float(parts[1]), "y": float(parts[2]),
                             "hold": parts[3] == "1", "prompt": norm(parts[4])})
            except ValueError:
                pass
        return rows, offset + end + 1


def stats(rows, dead_speed):
    speeds = [r["speed"] for r in rows if not math.isnan(r["speed"])]
    ys = [r["y"] for r in rows if not math.isnan(r["y"])]
    if not speeds:
        return {"n": len(rows), "avg": 0.0, "max": 0.0, "min_y": min(ys) if ys else 0.0, "dead": len(rows)}
    return {"n": len(rows), "avg": sum(speeds) / len(speeds), "max": max(speeds),
            "min_y": min(ys) if ys else 0.0, "dead": sum(1 for s in speeds if s < dead_speed)}


def measure(args, metrics, wording, static=False):
    """Play one wording for args.seconds, then return its stats (None if the stream never answered).
    A static (held-pose) wording is played as the final held state, like the stream holds a pose."""
    n_want = max(1, math.ceil(args.seconds / 2.0))
    offset = metrics.size()
    write_prompt(args.prompt_file, wording if static else f"{wording} @{args.seconds:g} >> {IDLE}")
    t0, got, want = time.time(), [], norm(wording)
    while time.time() - t0 < args.seconds + args.timeout:
        time.sleep(0.2)
        rows, offset = metrics.read_from(offset)
        got += [r for r in rows if r["prompt"] == want]
        if len(got) >= n_want:
            break
        if not got and time.time() - t0 > args.first_wait:
            return None
    return stats(got, args.dead_speed) if got else None


def settle(args):
    write_prompt(args.prompt_file, IDLE)
    time.sleep(args.pause)


def ask(text):
    try:
        return input(text).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return "q"


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_json(path, data):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True, sort_keys=True)
    os.replace(tmp, path)


def groups_from_file(path):
    groups, order = {}, []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, wording = ("custom", line)
        if "|" in line:
            key, _, wording = line.partition("|")
            key, wording = key.strip() or "custom", wording.strip()
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(wording)
    return [(k, groups[k]) for k in order]


def choose_groups(args):
    if args.prompts:
        return groups_from_file(args.prompts)
    names = list(SUITES) if args.suite == "all" else [s.strip() for s in args.suite.split(",")]
    out = []
    for n in names:
        if n not in SUITES:
            raise SystemExit(f"Unknown suite '{n}'. Choose from: {', '.join(SUITES)}, all.")
        out += SUITES[n]
    if args.only:
        wanted = {x.strip() for x in args.only.split(",")}
        out = [g for g in out if g[0] in wanted]
        if not out:
            raise SystemExit(f"Nothing matches --only {args.only}. Use --list to see the group names.")
    return out


def pick_for_group(key, candidates, verified, args, results=None, settings=""):
    """candidates: [(wording, result)]. Let the user choose which good/ok wording becomes the verified one.
    Wordings rated for this group in earlier sessions compete too; a pick that barely moves needs confirmation."""
    seen = {w for w, _ in candidates}
    candidates = list(candidates) + [(w, r) for w, r in (results or {}).items()
                                      if r.get("group") == key and w not in seen
                                      and (not settings or r.get("settings", settings) == settings)]
    usable = [(w, r) for w, r in candidates if r.get("rating") in ("good", "ok")]
    if not usable:
        print(f"  {key}: nothing worked well enough to use.\n")
        return
    usable.sort(key=lambda x: (x[1]["rating"] != "good", -x[1].get("avg", 0.0)))
    chosen = None
    if len(usable) == 1 or args.no_pick:
        chosen = usable[0]
    else:
        print(f"\n  {key}: which should she use?")
        for i, (w, r) in enumerate(usable, 1):
            weak = "   (weak: barely moves)" if r.get("avg", 0) < args.weak_speed and not key.startswith("pose.") else ""
            print(f"    {i}. [{r['rating']}] {w}   (avg {r.get('avg', 0):.2f} m/s){weak}")
        ans = ask("  number, Enter = 1, n = none > ")
        if ans == "n":
            print()
            return
        try:
            chosen = usable[int(ans) - 1 if ans else 0]
        except (ValueError, IndexError):
            chosen = usable[0]
    w, r = chosen
    if r.get("avg", 0) < args.weak_speed and not key.startswith("pose."):
        print(f"  NOTE: '{w}' moves very little (avg {r.get('avg', 0):.2f} m/s; a plain dance is about 0.5).")
        if ask("  use it anyway? y = yes, anything else = no (the current setting stays) > ") != "y":
            print()
            return
    verified[key] = w
    print(f"  {key}: using '{w}'\n")


def main():
    ap = argparse.ArgumentParser(description="Find out which wordings ARDY really performs (watch them in VaM and rate them)")
    ap.add_argument("--prompt-file", default=os.environ.get("VAMRT_PROMPT_FILE", r"C:\ARDY2BVH\prompt.txt"), help="The prompt file the stream watches")
    ap.add_argument("--metrics-file", default=os.environ.get("VAMRT_METRICS_FILE", r"C:\ARDY2BVH\metrics.tsv"), help="The file the stream writes with --metrics-file")
    ap.add_argument("--results", default=str(HERE / "lab_results.json"), help="Every rating, so a session can be resumed")
    ap.add_argument("--verified", default=str(HERE / "verified_prompts.json"), help="Output read by motion_prompter.py")
    ap.add_argument("--suite", default="dance", help="dance, dance2, walk, everyday, paper, poses, idle, gestures, extras (comma separated) or all")
    ap.add_argument("--only", default=None, help="Only these group names, e.g. dance.sexy,dance.slow")
    ap.add_argument("--prompts", default=None, help="Your own list: 'group | wording' or just 'wording' per line")
    ap.add_argument("--seconds", type=float, default=8.0, help="How long to play each wording")
    ap.add_argument("--lag", type=float, default=3.0, help="Seconds to wait before asking, so playback has caught up")
    ap.add_argument("--pause", type=float, default=5.0, help="Seconds of standing between candidates")
    ap.add_argument("--timeout", type=float, default=25.0, help="Extra seconds to wait for the stream's numbers")
    ap.add_argument("--first-wait", type=float, default=20.0, help="Give up if the stream shows nothing after this long")
    ap.add_argument("--start-wait", type=float, default=20.0,
                    help="How long to wait for the stream to start answering when the lab begins (it loads for ~1 minute)")
    ap.add_argument("--dead-speed", type=float, default=0.05, help="Average motion (m/s) below this = 'no movement'")
    ap.add_argument("--redo", action="store_true", help="Test wordings again even if they already have a rating")
    ap.add_argument("--no-pick", action="store_true", help="Don't ask which wording to use; take the best rated one")
    ap.add_argument("--weak-speed", type=float, default=0.2,
                    help="A pick that averages less movement than this (m/s) asks for confirmation (plain dancing is ~0.5)")
    ap.add_argument("--list", action="store_true", help="List the suites and exit")
    args = ap.parse_args()

    if args.list:
        for name, groups in SUITES.items():
            print(f"{name}:")
            for key, ws in groups:
                print(f"  {key}")
                for w in ws:
                    print(f"      {w}")
        return 0

    groups = choose_groups(args)
    total = sum(len(ws) for _, ws in groups)
    metrics = Metrics(args.metrics_file)
    results, verified = load_json(args.results), load_json(args.verified)

    print("ARDY motion lab")
    print(f"  {len(groups)} group(s), {total} wording(s); about {args.seconds + args.lag + args.pause + 4:.0f} s each")
    print("  Keep VaM in view. The stream must be running with:  --metrics-file " + args.metrics_file)
    offset = metrics.size()
    write_prompt(args.prompt_file, IDLE)
    t0, alive = time.time(), False
    while time.time() - t0 < args.start_wait:
        time.sleep(0.5)
        rows, offset = metrics.read_from(offset)
        if rows:
            alive = True
            break
    if not alive:
        print("\n  No numbers are coming from the stream. Is it running with --metrics-file "
              f"{args.metrics_file} and watching {args.prompt_file}?")
        return 2
    settings = metrics.settings()
    if settings:
        print(f"  Stream settings: {settings}")
        made_under = verified.get("_settings", "")
        if made_under and made_under != settings:
            print("  NOTE: your verified wordings were made under different settings:")
            print(f"        then: {made_under}")
            print(f"        now:  {settings}")
            print("        They may behave differently now. Wordings already rated are skipped; add --redo to re-test them under")
            print("        the new settings (earlier ratings from other settings are not mixed into the pick).")
    print("  The stream is answering. Starting.\n")

    done, quit_now = 0, False
    for key, wordings in groups:
        if quit_now:
            break
        print(f"== {key}")
        candidates = []
        for w in wordings:
            old = results.get(w)
            if old and not args.redo and (not settings or old.get("settings", settings) == settings):
                print(f"  (already rated: {old['rating']})  {w}")
                candidates.append((w, old))
                continue
            while True:
                done += 1
                print(f"  [{done}/{total}] {w}")
                static = key.startswith("pose.")
                st = measure(args, metrics, w, static)
                if st is None:
                    print("  The stream stopped answering; check its window. Saved what we have so far.")
                    save_json(args.results, results)
                    save_json(args.verified, verified)
                    return 2
                line = (f"      measured: avg {st['avg']:.2f} m/s, peak {st['max']:.2f}, lowest hips {st['min_y']:.2f}, "
                        f"{st['dead']} of {st['n']} chunks still")
                print(line)
                if static:
                    print("      (a held pose: little movement is normal here. Judge by eye: did she take the pose?)")
                elif st["avg"] < args.dead_speed or st["dead"] >= st["n"]:
                    print("      no movement: she just stood there. Marked dead (never used).")
                    rating = "dead"
                    break
                time.sleep(args.lag)
                ans = ask("      rate:  g good | o ok | b bad | r replay | s skip | q quit > ")
                if ans == "r":
                    done -= 1
                    settle(args)
                    continue
                if ans == "q":
                    quit_now = True
                    rating = None
                    break
                rating = {"g": "good", "o": "ok", "b": "bad"}.get(ans)
                break
            if rating:
                results[w] = {"group": key, "rating": rating, "avg": round(st["avg"], 3), "max": round(st["max"], 3),
                              "min_y": round(st["min_y"], 3), "when": time.strftime("%Y-%m-%d %H:%M"), "settings": settings}
                candidates.append((w, results[w]))
                save_json(args.results, results)
            if quit_now:
                break
            settle(args)
        if candidates:
            pick_for_group(key, candidates, verified, args, results, settings)
            if settings:
                verified["_settings"] = settings
            save_json(args.verified, verified)

    write_prompt(args.prompt_file, IDLE)
    save_json(args.results, results)
    save_json(args.verified, verified)
    print("\nDone." if not quit_now else "\nStopped.")
    shown = {k: v for k, v in verified.items() if not k.startswith("_")}
    if shown:
        print(f"Verified wordings saved to {args.verified}:")
        for k, v in sorted(shown.items()):
            print(f"  {k:18} {v}")
        print("Restart the motion prompter (or the launcher) and it will use them.")
    else:
        print("No wording was rated good or ok yet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
