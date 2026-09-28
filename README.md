# undupe

Finds open pull requests on busy GitHub repos that look like the same work, so maintainers can close the extras and contributors can check before they start.

Every tracked repo gets a page at the same path it has on GitHub:
`github.com/Graphify-Labs/graphify` → `<site>/Graphify-Labs/graphify/`

## Run it

```bash
python3 fetch.py      # pull open PRs for every repo in repos.txt (needs gh logged in)
python3 build.py      # find duplicate groups, write site/
python3 -m http.server 8765 -d site   # open http://localhost:8765
```

Both scripts also take repos directly: `python3 fetch.py owner/name`.

To track a new repo, add a line to `repos.txt` and run both scripts.

## Checking matches by hand

```bash
python3 review.py            # walk through unchecked likely groups
python3 review.py --all      # include "possible" groups too
```

For each group it shows the PRs and asks duplicate / not / skip / open in browser. Answers go into `verdicts.json` (commit it). On the site, confirmed groups get a "✓ Checked" badge and rejected pairs disappear. Reports from the site's "Not a duplicate? / Confirm" links arrive as issues on this repo; record them the same way.

## Deploy

`.github/workflows/update.yml` runs daily (and on every push to `main`): it fetches, builds and publishes `site/` to GitHub Pages. Run it by hand from the Actions tab ("Update and deploy" → Run workflow). Generated files are not committed.

## Layout

- `repos.txt`: the repos undupe tracks
- `fetch.py`: downloads open PRs to `data/<owner>/<repo>/raw.json` and closed PRs to `closed.json` (not committed). Cheap fields only; asking for CI status or reviews makes GitHub time out.
- `review.py`: record hand-checked verdicts in `verdicts.json`
- `build.py`: scoring and grouping (thresholds are constants at the top). Writes `site/<owner>/<repo>/data.json` and `index.html`, plus `site/repos.json`.
- `templates/repo.html`: the per-repo page, copied into each repo folder
- `site/index.html`: home page
- `site/404.html`: on GitHub Pages, sends a wrongly-capitalised repo path to the right page, or says the repo isn't tracked

## How matching works

Two PRs are paired when:

1. they say they fix the same issue ("Fixes #N", or "(#N)" in the title) **and** their titles or files also agree. A shared issue alone is shown as "possible", since big issues get split into parts;
2. their titles are near-identical; or
3. they change the same uncommon files. Each file is weighted by how few PRs touch it, so README.md or core modules count for little.

4. they share a very rare file (e.g. both create `extractors/perl.py`) and a rare title word, and have different authors.

Each open PR is also compared with closed PRs the same way, to find open PRs that redo work already done (the "Already done before?" tab). Many maintainers ship a PR's code in another commit and close it, so "closed" doesn't mean "rejected".

PRs naming different languages (PHP vs Scala) are never paired on files alone. Groups where every PR has the same author are labelled "Same author" (a resubmission, not two people duplicating effort).

It reads titles, descriptions and file lists only, not the code. Treat matches as leads to check, not verdicts.
