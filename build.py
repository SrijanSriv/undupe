"""Find likely-duplicate open PRs for each tracked repo and write the site.

Usage:
  python3 build.py                 # every repo in repos.txt
  python3 build.py owner/name ...  # just these

Reads data/<owner>/<repo>/raw.json, writes site/<owner>/<repo>/data.json and
index.html (from templates/repo.html), and refreshes site/repos.json, the
list the home page shows.

Signals, strongest first:
  1. Both PRs say they fix the same issue ("Fixes #N", or "(#N)" in the title).
  2. Near-identical titles (word overlap, rare words weigh more).
  3. They change the same *uncommon* files. Each file is weighted by how few
     PRs touch it, so hot files like README.md or extract.py count for little.

  4. They share a very rare file (e.g. both create extractors/perl.py) and a
     rare title word ("perl"). Catches "add language X" PRs that also touch
     many other files, which dilutes signal 3.

PRs whose titles name different languages (php vs scala) are never paired on
files alone: they edit the same extractor files but do different work.
"""

import collections
import itertools
import json
import math
import os
import re
import shutil
import sys
from pathlib import Path
from datetime import datetime, timezone

CLOSES = re.compile(r"(?i)\b(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?)\s*:?\s+#(\d+)")
TITLE_REF = re.compile(r"#(\d+)")
STOP = set("a an the and or of to in for on with from by add adds fix fixes feat support use "
           "when is as not into graphify make allow new update improve handle".split())
LANGS = set("python javascript js typescript ts go golang rust java kotlin scala php ruby csharp c# "
            "cpp c++ swift dart lua perl sql tsql t-sql apex elixir haskell julia zig gdscript vb.net "
            "vbnet terraform hcl bash shell powershell ocaml clojure erlang fortran cobol solidity "
            "verilog vue svelte objc objective-c groovy nim crystal matlab pascal delphi r".split())

HIGH_TITLE = 0.8     # title similarity that counts as a match on its own
FILE_MIN = 0.4       # file similarity needed for a file-based match...
FILE_TITLE_MIN = 0.2  # ...together with at least this much title similarity
ISSUE_FILE_MIN = 0.2   # a shared issue is high confidence only with this much file overlap...
ISSUE_TITLE_MIN = 0.15  # ...or this much title overlap
RARE_FILE_MAX = 3     # a file touched by at most this many PRs is "very rare"...
RARE_WORD_MAX = 10    # ...and a title word used by at most this many PRs is "rare"
# Where "wrong match" reports go. In the GitHub workflow this is the repo it runs in.
UNDUPE_REPO = os.environ.get("GITHUB_REPOSITORY", "SrijanSriv/undupe")
GENERIC_FILES = (".lock", ".toml", ".md", ".txt", ".cfg")  # rare by chance, not by meaning


def words(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9_.+#-]{2,}", title.lower()) if w not in STOP and len(w) > 2 or w in LANGS}


def langs(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9_.+#-]+", title.lower()) if w in LANGS}


def weighted_overlap(a: set, b: set, weight) -> float:
    union = sum(weight(x) for x in a | b)
    return sum(weight(x) for x in a & b) / union if union else 0.0


def build(repo: str) -> dict:
    raw = json.load(open(Path("data", repo, "raw.json")))
    prs = raw["prs"]
    for p in prs:
        p["F"] = {f["path"] for f in p.get("files") or []}
        p["I"] = set(CLOSES.findall(p.get("body") or "")) | set(TITLE_REF.findall(p["title"]))
        p["I"].discard(str(p["number"]))
        p["W"] = words(p["title"])
        p["L"] = langs(p["title"])

    n = len(prs)
    file_df = collections.Counter(f for p in prs for f in p["F"])
    word_df = collections.Counter(w for p in prs for w in p["W"])
    fw = lambda f: math.log(n / file_df[f])
    ww = lambda w: math.log(n / word_df[w])

    # Current base branch = the one most recent PRs target.
    recent = sorted(prs, key=lambda p: p["createdAt"])[-100:]
    base = collections.Counter(p["baseRefName"] for p in recent).most_common(1)[0][0]

    pairs = []
    for a, b in itertools.combinations(prs, 2):
        same_issue = sorted(a["I"] & b["I"], key=int)
        fs = weighted_overlap(a["F"], b["F"], fw)
        ts = weighted_overlap(a["W"], b["W"], ww)
        different_lang = a["L"] and b["L"] and not (a["L"] & b["L"])
        same_author = a["author"] and b["author"] and a["author"].get("login") == b["author"].get("login")
        file_match = fs >= FILE_MIN and ts >= FILE_TITLE_MIN and not different_lang
        # Same-author pairs are skipped here: one person's series of PRs on a
        # feature shares its test files and topic word by design.
        rare_files = [f for f in a["F"] & b["F"] if file_df[f] <= RARE_FILE_MAX and not f.endswith(GENERIC_FILES)]
        rare_words = [w for w in a["W"] & b["W"] if word_df[w] <= RARE_WORD_MAX]
        rare_match = bool(rare_files and rare_words) and not different_lang and not same_author
        if not (same_issue or ts >= HIGH_TITLE or file_match or rare_match):
            continue
        # A shared issue alone is not proof: big issues get split into parts,
        # so it only counts as high confidence when titles or files also agree.
        corroborated = (fs >= ISSUE_FILE_MIN or ts >= ISSUE_TITLE_MIN) and not different_lang
        reasons = []
        if same_issue:
            reasons.append("Both fix " + ", ".join(f"#{i}" for i in same_issue)
                           + ("" if corroborated else " (but look different, may fix separate parts)"))
        if ts >= HIGH_TITLE:
            reasons.append("Near-identical titles")
        shared = sorted(a["F"] & b["F"], key=lambda f: file_df[f])
        if fs >= FILE_MIN:
            reasons.append(f"Change the same uncommon files ({round(fs * 100)}% weighted overlap)")
        elif rare_match:
            reasons.append(f"Both touch {sorted(rare_files)[0]}, which almost no other PR does")
        pairs.append({
            "a": a["number"], "b": b["number"],
            "high": bool(same_issue) and corroborated or ts >= HIGH_TITLE,
            "sameAuthor": bool(same_author),
            "score": round((1 if same_issue else 0) + fs + ts, 3),
            "reasons": reasons,
            "shared": shared[:8],
        })

    # Group pairs into clusters (union-find).
    parent: dict[int, int] = {}
    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    # Link strong pairs first. A weak pair may add a lone PR to a group, but
    # never merges two groups, so one loose match cannot chain them together.
    for p in sorted(pairs, key=lambda p: (not p["high"], -p["score"])):
        ra, rb = find(p["a"]), find(p["b"])
        size = lambda r: sum(find(x) == r for x in list(parent))
        if p["high"] or size(ra) == 1 or size(rb) == 1:
            parent[ra] = rb
    clusters: dict[int, dict] = {}
    for p in pairs:
        if find(p["a"]) != find(p["b"]):
            continue  # weak pair that was not allowed to join groups
        c = clusters.setdefault(find(p["a"]), {"prs": set(), "pairs": []})
        c["prs"] |= {p["a"], p["b"]}
        c["pairs"].append(p)

    by_num = {p["number"]: p for p in prs}
    groups = []
    for c in clusters.values():
        members = sorted(c["prs"], key=lambda x: by_num[x]["createdAt"])
        groups.append({
            "prs": members,
            "high": any(p["high"] for p in c["pairs"]),
            # Same person twice is a resubmission (clutter), not two people
            # duplicating each other's effort.
            "resubmit": len({by_num[x]["author"]["login"] for x in c["prs"] if by_num[x]["author"]}) == 1,
            "score": max(p["score"] for p in c["pairs"]),
            "pairs": sorted(c["pairs"], key=lambda p: -p["score"]),
        })
    groups.sort(key=lambda g: (not g["high"], -g["score"]))

    claims = collections.defaultdict(list)
    for p in prs:
        for i in p["I"]:
            claims[i].append(p["number"])
    contested = sorted(
        ({"issue": int(i), "prs": sorted(v)} for i, v in claims.items() if len(v) > 1),
        key=lambda x: (-len(x["prs"]), -x["issue"]),
    )

    high = [g for g in groups if g["high"]]
    out = {
        "repo": raw["repo"],
        "undupeRepo": UNDUPE_REPO,
        "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "base": base,
        "stats": {
            "open": n,
            "groups": len(groups),
            "highGroups": len(high),
            "prsInGroups": sum(len(g["prs"]) for g in groups),
            "extraHigh": sum(len(g["prs"]) - 1 for g in high),
            "extraAll": sum(len(g["prs"]) - 1 for g in groups),
            "highPeople": sum(1 for g in high if not g["resubmit"]),
            "extraHighPeople": sum(len(g["prs"]) - 1 for g in high if not g["resubmit"]),
            "contested": len(contested),
        },
        "groups": groups,
        "contested": contested,
        "prs": {
            p["number"]: {
                "t": p["title"],
                "a": (p.get("author") or {}).get("login", "?"),
                "c": p["createdAt"][:10],
                "u": p["updatedAt"][:10],
                "b": p["baseRefName"],
                "d": p.get("isDraft", False),
                "i": sorted(p["I"], key=int),
                "f": sorted(p["F"]),
            }
            for p in prs
        },
    }
    out_dir = Path("site", repo)
    out_dir.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(out_dir / "data.json", "w"), separators=(",", ":"))
    shutil.copy("templates/repo.html", out_dir / "index.html")
    s = out["stats"]
    print(f"{repo}: {s['open']} open PRs -> {s['groups']} groups ({s['highGroups']} high confidence), "
          f"{s['prsInGroups']} PRs involved, {s['extraHigh']} extra PRs in high-confidence groups, "
          f"{s['contested']} issues with >1 PR")
    return {"repo": repo, "generated": out["generated"], **s}


def main() -> None:
    from fetch import tracked_repos
    repos = sys.argv[1:] or tracked_repos()
    index_path = Path("site/repos.json")
    index = {r["repo"]: r for r in json.load(open(index_path))} if index_path.exists() else {}
    for repo in repos:
        index[repo] = build(repo)
    # Keep only repos that are still tracked and built.
    keep = set(tracked_repos()) | set(repos)
    rows = sorted((r for r in index.values() if r["repo"] in keep), key=lambda r: r["repo"].lower())
    json.dump(rows, open(index_path, "w"), indent=1)


if __name__ == "__main__":
    main()
