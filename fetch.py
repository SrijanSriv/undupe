"""Fetch PRs of each tracked repo via the gh CLI.

Writes data/<owner>/<repo>/raw.json (open PRs) and closed.json (closed PRs,
used to spot open PRs that redo work already done).

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
CLOSED_FIELDS = "number,title,body,files,createdAt,closedAt,mergedAt,author"
CLOSED_LIMIT = 3000


def tracked_repos() -> list[str]:
    lines = Path("repos.txt").read_text().splitlines()
    return [l.strip() for l in lines if l.strip() and not l.startswith("#")]


def fetch_list(repo: str, state: str, fields: str, limit: int, out_name: str) -> bool:
    for attempt in range(4):
        proc = subprocess.run(
            ["gh", "pr", "list", "-R", repo, "--state", state, "--limit", str(limit), "--json", fields],
            capture_output=True, text=True, encoding="utf-8",
        )
        if proc.returncode == 0:
            prs = json.loads(proc.stdout)
            out = Path("data", repo, out_name)
            out.parent.mkdir(parents=True, exist_ok=True)
            json.dump({"repo": repo, "prs": prs}, open(out, "w"))
            print(f"{repo}: fetched {len(prs)} {state} PRs")
            return True
        print(f"{repo} ({state}): attempt {attempt + 1} failed: {proc.stderr.strip()[:200]}", file=sys.stderr)
        time.sleep(10 * (attempt + 1))
    return False


def fetch(repo: str) -> bool:
    if not fetch_list(repo, "open", FIELDS, 2000, "raw.json"):
        return False
    # Closed PRs are extra: if they fail, the site still builds without the
    # "already done" comparison.
    if not fetch_list(repo, "closed", CLOSED_FIELDS, CLOSED_LIMIT, "closed.json"):
        print(f"{repo}: skipping closed PRs", file=sys.stderr)
    return True


def main() -> None:
    repos = sys.argv[1:] or tracked_repos()
    failed = [r for r in repos if not fetch(r)]
    if failed:
        sys.exit(f"failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
