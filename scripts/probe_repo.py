"""Phase 0.5: read-only probe of a candidate repo's Actions history.

    uv run scripts/probe_repo.py --repo dask/distributed --runs 60

Answers: readable+failing history? retry data? junit artifacts? how far back? Writes nothing but the report.
"""
import argparse
import io
import os
import re
import sys
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

import requests

API = "https://api.github.com"
S = requests.Session()
S.headers["Accept"] = "application/vnd.github+json"
if tok := os.environ.get("GITHUB_TOKEN"):
    S.headers["Authorization"] = f"Bearer {tok}"
LAST = {}


def get(path, **params):
    r = S.get(path if path.startswith("http") else API + path, params=params, timeout=60)
    LAST.update({k: r.headers.get(k) for k in ("X-RateLimit-Remaining", "X-RateLimit-Limit")})
    r.raise_for_status()
    return r


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--runs", type=int, default=60)
    a = ap.parse_args()
    repo = a.repo
    out = []
    p = lambda s="": (print(s), out.append(s))

    # ---- Q1: readable history with failures
    runs = []
    page = 1
    while len(runs) < a.runs:
        batch = get(f"/repos/{repo}/actions/runs", per_page=min(100, a.runs - len(runs)), page=page).json()["workflow_runs"]
        if not batch:
            break
        runs += [r for r in batch if r["status"] == "completed"]
        page += 1
    runs = runs[: a.runs]
    if not runs:
        sys.exit("no completed runs")
    concl = Counter(r["conclusion"] for r in runs)
    dates = sorted(ts(r["created_at"]) for r in runs)
    span_days = (dates[-1] - dates[0]).days
    fail_rate = 1 - concl.get("success", 0) / len(runs)
    p(f"REPO: {repo}")
    p(f"  runs sampled ............ {len(runs)} ({dates[0]:%Y-%m-%d} -> {dates[-1]:%Y-%m-%d}, {span_days} days)")
    p(f"  conclusions ............. {dict(concl)}")
    p(f"  failure rate ............ {fail_rate:.0%}")
    p(f"  distinct workflows ...... {len({r['name'] for r in runs})}")
    q1 = fail_rate >= 0.20 and span_days >= 14
    p(f"  Q1 pass (>=20% non-success, >=14 days) .. {q1}")

    # ---- Q2: retry recoveries
    retried = [r for r in runs if r["run_attempt"] > 1]
    recoveries = []
    for r in retried:
        attempts = []
        for n in range(1, r["run_attempt"]):
            attempts.append(get(f"/repos/{repo}/actions/runs/{r['id']}/attempts/{n}").json()["conclusion"])
        attempts.append(r["conclusion"])
        if r["conclusion"] == "success" and any(c in ("failure", "timed_out") for c in attempts[:-1]):
            recoveries.append((r, attempts))
    p(f"  retry attempts present .. {len(retried)} runs")
    p(f"  retry recoveries ........ {len(recoveries)}   <- must be >= 5")
    for r, attempts in recoveries[:5]:
        p(f"      run {r['id']} sha {r['head_sha'][:10]} attempts {attempts}  {r['html_url']}")
    if not recoveries:
        p("  VERDICT: unsuitable - no retry recovery signal")
        write(repo, out)
        return

    # ---- Q3: junit artifacts
    pat = re.compile(r"test|junit|pytest|report|\.xml", re.I)
    names, oldest_with_artifact, sample = Counter(), None, None
    for r in sorted(runs, key=lambda r: r["created_at"], reverse=True):
        arts = get(f"/repos/{repo}/actions/runs/{r['id']}/artifacts").json()["artifacts"]
        live = [x for x in arts if not x["expired"]]
        for x in arts:
            names[x["name"]] += 1
        if live:
            oldest_with_artifact = r
        match = [x for x in live if pat.search(x["name"])]
        if match and sample is None and tok:
            sample = inspect(match[0])
    p(f"  artifact names seen ..... {dict(names.most_common(15))}")
    matching = [n for n in names if pat.search(n)]
    p(f"  junit artifacts ......... {'yes' if matching else 'no'} (names: {matching[:5]})")
    if sample:
        p(f"  sample artifact ......... {sample}")
    elif matching and not tok:
        p("  sample artifact ......... skipped (GITHUB_TOKEN required to download)")

    # ---- Q4: windows
    oldest_run = dates[0]
    now = datetime.now(timezone.utc)
    job_days = (now - oldest_run).days
    test_days = (now - ts(oldest_with_artifact["created_at"])).days if oldest_with_artifact else 0
    p(f"  test-level window ....... {test_days} days (oldest run with live artifact, within sample)")
    p(f"  job-level window ........ {job_days}+ days (oldest run in sample; runs outlive artifacts)")
    p(f"  rate limit remaining .... {LAST['X-RateLimit-Remaining']} / {LAST['X-RateLimit-Limit']}")
    src = "A (junit artifacts), fall back to C on old runs" if sample and sample.get("testcases") else "C (job/step level)"
    p(f"\n  VERDICT: {'suitable' if q1 else 'weak on Q1 but retry signal present'} - source {src}")
    write(repo, out)


def inspect(art):
    z = zipfile.ZipFile(io.BytesIO(get(art["archive_download_url"]).content))
    xmls = [n for n in z.namelist() if n.lower().endswith(".xml")]
    info = {"name": art["name"], "files": len(z.namelist()), "xml_files": len(xmls)}
    for n in xmls:
        try:
            root = ElementTree.fromstring(z.read(n))
        except ElementTree.ParseError:
            continue
        cases = root.iter("testcase")
        first = None
        count = 0
        for c in cases:
            count += 1
            if first is None and (c.find("failure") is not None or c.find("error") is not None):
                first = c
        if count:
            c = first or next(root.iter("testcase"))
            info.update(testcases=count, sample_test_id=f"{c.get('file') or c.get('classname')}::{c.get('name')}", sample_failed=first is not None)
            return info
    return info


def write(repo, lines):
    path = Path("probe-results") / (repo.replace("/", "-") + ".md")
    path.write_text("```\n" + "\n".join(lines) + "\n```\n", encoding="utf-8")
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
