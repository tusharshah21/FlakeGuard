"""Phase 0.5, Q2 redefined: same-commit recovery across cron re-runs of dask/distributed's Tests workflow.

    uv run scripts/probe_cron_reruns.py

Downloads one canonical matrix cell per schedule-triggered run on main (cached to .cache/artifacts, gitignored),
plus every cell for a handful of runs, then reports per-(test, sha) pass/fail counts with Wilson intervals.
Read-only against GitHub; writes nothing but the cache and the probe report.
"""
import io
import json
import math
import os
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree

import requests

REPO = "dask/distributed"
CELL = "ubuntu-latest-py312-test-ci-notci1"
MULTI_CELL_RUNS = 5
DAYS = 95
CACHE = Path(".cache/artifacts")
CACHE.mkdir(parents=True, exist_ok=True)

S = requests.Session()
S.headers.update({"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json"})
API = f"https://api.github.com/repos/{REPO}"


def rate_used():
    # the /rate_limit JSON body lags; the header on any real call is accurate
    return int(S.get(f"{API}/actions/artifacts", params={"per_page": 1}).headers["X-RateLimit-Used"])


def schedule_runs():
    since = (datetime.now(timezone.utc) - timedelta(days=DAYS)).strftime("%Y-%m-%d")
    runs, page = [], 1
    while True:
        b = S.get(f"{API}/actions/workflows/tests.yaml/runs",
                  params={"per_page": 100, "page": page, "event": "schedule", "branch": "main", "created": f">={since}"}).json()["workflow_runs"]
        if not b:
            break
        runs += [r for r in b if r["status"] == "completed"]
        page += 1
    return sorted(runs, key=lambda r: r["created_at"])


def artifacts_for(run):
    f = CACHE / f"run_{run['id']}.json"
    if not f.exists():
        f.write_text(json.dumps(S.get(run["artifacts_url"], params={"per_page": 100}).json()["artifacts"]), encoding="utf-8")
    return json.loads(f.read_text(encoding="utf-8"))


def fetch(art):
    f = CACHE / f"{art['id']}.zip"
    if not f.exists():
        r = S.get(art["archive_download_url"])
        r.raise_for_status()
        f.write_bytes(r.content)
    return f.read_bytes()


def parse(blob):
    """-> (list of (test_id, outcome), None) or (None, reason). Outcome in {pass, fail}; skipped tests are excluded."""
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
        xmls = [n for n in z.namelist() if n.endswith(".xml")]
        if not xmls:
            return None, "no xml in zip"
        root = ElementTree.fromstring(z.read(xmls[0]))
    except zipfile.BadZipFile:
        return None, "bad zip"
    except ElementTree.ParseError:
        return None, "xml parse error"
    if root.find(".//testsuite") is None:
        return None, "no testsuite element"
    rows = []
    for tc in root.iter("testcase"):
        if tc.find("skipped") is not None:
            continue
        failed = tc.find("failure") is not None or tc.find("error") is not None
        rows.append((f"{tc.get('classname')}::{tc.get('name')}", "fail" if failed else "pass"))
    if not rows:
        return None, "zero testcases"
    return rows, None


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def main():
    used0 = rate_used()
    out = []
    p = lambda s="": (print(s), out.append(s))
    runs = schedule_runs()
    live = [(r, a) for r in runs for a in artifacts_for(r) if a["name"] == CELL and not a["expired"]]
    p(f"REPO: {REPO}   canonical cell: {CELL}")
    p(f"  schedule Tests runs on main ({DAYS}d) .. {len(runs)}; with live canonical artifact: {len(live)}")

    # observations: (run_id, head_sha, started_at, cell, test_id, outcome)
    obs, parse_fail = [], Counter()
    for r, a in live:
        rows, why = parse(fetch(a))
        if why:
            parse_fail[why] += 1
            continue
        obs += [(r["id"], r["head_sha"], r["run_started_at"], CELL, t, o) for t, o in rows]
    p(f"  canonical artifacts parsed ...... {len(live) - sum(parse_fail.values())}   parse failures: {sum(parse_fail.values())} {dict(parse_fail)}")
    p(f"  observations ..................... {len(obs)}")

    # per (test, sha): pass / fail counts
    tally = defaultdict(Counter)
    for _, sha, _, _, t, o in obs:
        tally[(t, sha)][o] += 1
    mixed = {k: c for k, c in tally.items() if c["fail"] and c["pass"]}
    per_test_shas = defaultdict(set)
    for (t, sha) in mixed:
        per_test_shas[t].add(sha)
    chronic = {t: s for t, s in per_test_shas.items() if len(s) >= 3}
    q2a, q2b = len(mixed), len(chronic)
    p(f"  Q2(a) (test, sha) pairs with both fail and pass .. {q2a}   <- need >= 5")
    p(f"  Q2(b) tests recovering across >= 3 commits ....... {q2b}   <- need >= 1")
    p(f"  distinct tests with any failure .................. {len({t for (t, _), c in tally.items() if c['fail']})}")
    for t, shas in sorted(chronic.items(), key=lambda kv: -len(kv[1]))[:10]:
        p(f"      {len(shas)} commits  {t}")

    anchor = Counter(sha for _, sha, *_ in obs).most_common(1)[0][0]
    n_runs = len({rid for rid, sha, *_ in obs if sha == anchor})
    p(f"\n  top 10 by p_hat at {anchor[:10]} ({n_runs} runs):")
    rows = []
    for (t, sha), c in tally.items():
        if sha == anchor and c["fail"]:
            n = c["fail"] + c["pass"]
            lo, hi = wilson(c["fail"], n)
            rows.append((c["fail"] / n, n, lo, hi, t))
    p(f"      {'p_hat':>6} {'n':>3} {'wilson95':>15}  test")
    for ph, n, lo, hi, t in sorted(rows, reverse=True)[:10]:
        p(f"      {ph:6.3f} {n:3d} [{lo:5.3f}, {hi:5.3f}]  {t}")

    # multi-cell secondary sample: every cell for the newest runs of the anchor commit
    anchor_runs = [r for r in runs if r["head_sha"] == anchor][-MULTI_CELL_RUNS:]
    cells, mc_fail = Counter(), Counter()
    for r in anchor_runs:
        for a in artifacts_for(r):
            if a["expired"] or a["name"].endswith("_cluster_dumps") or a["name"] == "Event File":
                continue
            rows, why = parse(fetch(a))
            if why:
                mc_fail[why] += 1
            else:
                cells[a["name"]] += 1
    mindeps = [c for c in cells if "mindeps" in c]
    p(f"\n  multi-cell sample .... {len(anchor_runs)} runs x {len(cells)} cells cached ({len(mindeps)} mindeps cells = distinct dependency env, "
      f"excluded from canonical series); parse failures: {sum(mc_fail.values())}")

    used = rate_used() - used0
    p(f"  requests consumed .... {used}")
    verdict = q2a >= 5 and q2b >= 1
    p(f"\n  VERDICT: {'suitable' if verdict else 'unsuitable'} - source A (junit artifacts, canonical cell {CELL}); "
      f"test-level window 89d; every observation stores run_started_at for the environment-drift check")
    Path("probe-results/dask-distributed-cron-reruns.md").write_text("```\n" + "\n".join(out) + "\n```\n", encoding="utf-8")


if __name__ == "__main__":
    main()
