"""Walk through unchecked duplicate groups and record verdicts in verdicts.json.

Usage:
  python3 review.py                  # first repo in repos.txt
  python3 review.py owner/name
  python3 review.py owner/name --all # include "possible" groups (default: likely only)

For each group it shows the PRs (title, author, date, start of the
description, files) and asks:
  d = duplicate   n = not a duplicate   s = skip   o = open in browser   q = save and quit

A verdict applies to every pair of PRs in the group. Run build.py afterwards
(or push; the workflow rebuilds) so the site picks it up.
"""

import json
import sys
import textwrap
import webbrowser
from datetime import date
from pathlib import Path

from build import EVIDENCE_LEVELS, load_verdicts, pair_key
from fetch import tracked_repos


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    repo = args[0] if args else tracked_repos()[0]
    include_possible = "--all" in sys.argv

    site = json.load(open(Path("site", repo, "data.json")))
    raw_path = Path("data", repo, "raw.json")
    bodies = {p["number"]: p.get("body") or "" for p in json.load(open(raw_path))["prs"]} if raw_path.exists() else {}

    all_verdicts = load_verdicts()
    verdicts = all_verdicts.setdefault(repo, {})

    todo = [g for g in site["groups"]
            if (g["high"] or include_possible)
            and any(pair_key(p["a"], p["b"]) not in verdicts for p in g["pairs"])]
    print(f"{repo}: {len(todo)} group(s) to check\n")

    def save() -> None:
        json.dump(all_verdicts, open("verdicts.json", "w"), indent=1, sort_keys=True)

    for i, g in enumerate(todo, 1):
        reasons = sorted({r for p in g["pairs"] for r in p["reasons"]})
        print("=" * 78)
        print(f"[{i}/{len(todo)}] {'LIKELY' if g['high'] else 'POSSIBLE'}  " + " · ".join(reasons))
        for n in g["prs"]:
            p = site["prs"][str(n)]
            print(f"\n  #{n}  {p['t']}")
            print(f"        @{p['a']} · opened {p['c']} · {len(p['f'])} files")
            desc = " ".join(bodies.get(n, "").split())[:300]
            if desc:
                print(textwrap.indent(textwrap.fill(desc, 70), "        "))
        shared = sorted({f for p in g["pairs"] for f in p["shared"]})
        if shared:
            print(f"\n  shared files: {', '.join(shared[:6])}{' …' if len(shared) > 6 else ''}")

        while True:
            ans = input("\n  [d]uplicate  [n]ot  [s]kip  [o]pen  [q]uit > ").strip().lower()
            if ans == "o":
                for n in g["prs"]:
                    webbrowser.open(f"https://github.com/{repo}/pull/{n}/files")
                continue
            break
        if ans == "q":
            break
        if ans not in ("d", "n"):
            continue
        by = input("  reviewer (your name/handle) > ").strip()
        levels = list(EVIDENCE_LEVELS)
        print("  evidence level: " + "  ".join(f"[{i}] {k} ({v})" for i, (k, v) in enumerate(EVIDENCE_LEVELS.items(), 1)))
        pick = input("  level (default 1) > ").strip() or "1"
        evidence = levels[int(pick) - 1] if pick.isdigit() and 1 <= int(pick) <= len(levels) else levels[0]
        checked = input("  what did you check? > ").strip()
        links = input("  evidence links (space-separated URLs, optional) > ").split()
        note = input("  note (optional) > ").strip()
        for p in g["pairs"]:
            verdicts[pair_key(p["a"], p["b"])] = {
                "verdict": "duplicate" if ans == "d" else "not-duplicate",
                "prs": g["prs"],
                "note": note,
                "by": by,
                "evidence": evidence,
                "checked": checked,
                "links": links or [f"https://github.com/{repo}/pull/{n}" for n in g["prs"]],
                "date": date.today().isoformat(),
            }
        save()  # after every answer, so quitting never loses work

    save()
    print("\nSaved verdicts.json. Run `python3 build.py` to update the site.")


if __name__ == "__main__":
    main()
