"""Fetch all open PRs of each tracked repo into data/<owner>/<repo>/raw.json via the gh CLI.

Usage:
  python3 fetch.py                 # every repo in repos.txt
  python3 fetch.py owner/name ...  # just these

Only cheap fields are requested: asking for CI status or reviews on a
big page makes GitHub's GraphQL API time out (HTTP 504).
"""

import json
import subprocess
import sys
import time
from pathlib import Path

FIELDS = "number,title,body,files,createdAt,updatedAt,author,url,isDraft,baseRefName"


def tracked_repos() -> list[str]:
    lines = Path("repos.txt").read_text().splitlines()
    return [l.strip() for l in lines if l.strip() and not l.startswith("#")]


def fetch(repo: str) -> bool:
    for attempt in range(4):
        proc = subprocess.run(
            ["gh", "pr", "list", "-R", repo, "--state", "open", "--limit", "2000", "--json", FIELDS],
            capture_output=True, text=True, encoding="utf-8",
        )
        if proc.returncode == 0:
            prs = json.loads(proc.stdout)
            out = Path("data", repo, "raw.json")
            out.parent.mkdir(parents=True, exist_ok=True)
            json.dump({"repo": repo, "prs": prs}, open(out, "w"))
            print(f"{repo}: fetched {len(prs)} open PRs")
            return True
        print(f"{repo}: attempt {attempt + 1} failed: {proc.stderr.strip()[:200]}", file=sys.stderr)
        time.sleep(10 * (attempt + 1))
    return False


def main() -> None:
    repos = sys.argv[1:] or tracked_repos()
    failed = [r for r in repos if not fetch(r)]
    if failed:
        sys.exit(f"failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
