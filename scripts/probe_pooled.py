"""Phase 0.5, Q2 pooled across matrix cells with stratification.

    uv run scripts/probe_pooled.py

Jobs API gives per-cell conclusion for every schedule run (1 request/run). Artifacts are downloaded only for
cells whose job FAILED; a succeeded cell means every test in its roster passed, and rosters come from a small
sample of passing artifacts per cell. Failures are stratified per cell before pooling, so a test failing on one
platform reads as PLATFORM_SPECIFIC rather than a tidy pooled flake.
"""
import json
import sys
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from probe_cron_reruns import API, CACHE, S, artifacts_for, fetch, parse, rate_used, schedule_runs, wilson  # noqa: E402

EXCLUDE = ("ubuntu-latest-mindeps-",)
ROSTER_SAMPLES = 3
ANCHOR = "40fcd99a8c"


def cell_of(job_name):
    p = job_name.split(" ")
    return "-".join(p[:3] + ["".join(p[3:])]) if len(p) >= 4 else None


def jobs_for(run):
    f = CACHE / f"jobs_{run['id']}.json"
    if not f.exists():
        f.write_text(json.dumps(S.get(f"{API}/actions/runs/{run['id']}/jobs", params={"per_page": 100}).json()["jobs"]), encoding="utf-8")
    return json.loads(f.read_text(encoding="utf-8"))


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def os_of(cell):
    return cell.split("-py")[0]


def summarize(percell):
    fails = sum(c["fail"] for c in percell.values())
    n = sum(c["fail"] + c["pass"] for c in percell.values())
    fail_cells = {c: v["fail"] for c, v in percell.items() if v["fail"]}
    top_share = max(fail_cells.values()) / fails if fails else 0
    os_fails = Counter()
    for c, k in fail_cells.items():
        os_fails[os_of(c)] += k
    top_os_share = max(os_fails.values()) / fails if fails else 0
    return fails, n, len(fail_cells), top_share, top_os_share, len(percell)


def category(fails, n, ncells_fail, top_share, top_os_share, ncells_present):
    if fails == 0:
        return "pass"
    if fails == n:
        return "fails_always"
    # ponytail: explainable dispersion rule, not a test statistic. >=3 failures and >=75% in one cell,
    # or >=80% on one OS, is "concentrated"; refine in Phase 2 if it misfires on real cases.
    if fails >= 3 and ncells_present > 1 and (top_share >= 0.75 or top_os_share >= 0.8):
        return "platform_specific"
    return "masked_flake"


def main():
    used0 = rate_used()
    downloaded_before = len(list(CACHE.glob("*.zip")))
    out = []
    p = lambda s="": (print(s), out.append(s))
    runs = schedule_runs()

    status = {}  # (run_id, cell) -> job conclusion
    for r in runs:
        for j in jobs_for(r):
            c = cell_of(j["name"])
            if c and "-test-" in c and not c.startswith(EXCLUDE):
                status[(r["id"], c)] = j["conclusion"]
    cells = sorted({c for _, c in status})
    concl = Counter(status.values())
    p(f"REPO: dask/distributed   pooled over {len(cells)} cells, {len(runs)} schedule runs on main")
    p(f"  run-cell job conclusions .... {dict(concl)}")

    run_by_id = {r["id"]: r for r in runs}
    arts = {r["id"]: {a["name"]: a for a in artifacts_for(r) if not a["expired"]} for r in runs}

    # exact outcomes for failed cells
    obs = []  # (run_id, sha, started_at, cell, test_id, outcome)
    infra, unresolved, parse_fail = [], [], Counter()
    for (rid, c), s in status.items():
        if s != "failure":
            continue
        a = arts[rid].get(c)
        if a is None:
            unresolved.append((rid, c))
            continue
        rows, why = parse(fetch(a))
        if why:
            parse_fail[why] += 1
            unresolved.append((rid, c))
            continue
        if not any(o == "fail" for _, o in rows):
            infra.append((rid, c))
            continue
        r = run_by_id[rid]
        obs += [(rid, r["head_sha"], r["run_started_at"], c, t, o) for t, o in rows]

    # rosters for succeeded cells: sampled passing artifacts spread across the window, nearest-in-time lookup
    rosters = defaultdict(list)  # cell -> [(started_at, set(test_id))] sorted by time
    drift = {}
    for c in cells:
        passing = sorted((rid for (rid, cc), s in status.items() if cc == c and s == "success" and c in arts[rid]),
                         key=lambda rid: run_by_id[rid]["run_started_at"])
        if not passing:
            continue
        for i in sorted({0, len(passing) // 2, len(passing) - 1}):
            rid = passing[i]
            rows, why = parse(fetch(arts[rid][c]))
            if why:
                parse_fail[why] += 1
                continue
            rosters[c].append((ts(run_by_id[rid]["run_started_at"]), {t for t, o in rows if o == "pass"}))
        if len(rosters[c]) >= 2:
            old, new = rosters[c][0][1], rosters[c][-1][1]
            drift[c] = (len(old - new), len(new - old), len(old & new))
    for (rid, c), s in status.items():
        if s != "success" or c not in rosters:
            continue
        r = run_by_id[rid]
        keys = [t0 for t0, _ in rosters[c]]
        i = min(bisect_left(keys, ts(r["run_started_at"])), len(keys) - 1)
        obs += [(rid, r["head_sha"], r["run_started_at"], c, t, "pass") for t in rosters[c][i][1]]
    worst = sorted(drift.items(), key=lambda kv: -(kv[1][0] + kv[1][1]))[:3]
    p(f"  failed run-cells ............ {concl['failure']}: with test failures {concl['failure'] - len(infra) - len(unresolved)}, "
      f"INFRA (artifact, zero failing tests) {len(infra)}, UNRESOLVED (no/unparseable artifact) {len(unresolved)}")
    p(f"  parse failures .............. {sum(parse_fail.values())} {dict(parse_fail)}")
    p(f"  roster samples .............. {sum(len(v) for v in rosters.values())} artifacts over {len(rosters)} cells; "
      f"worst drift oldest->newest (removed, added, common): {worst}")
    p(f"  observations ................ {len(obs)}")

    tally = defaultdict(lambda: defaultdict(Counter))  # (test, sha) -> cell -> Counter(fail/pass)
    for _, sha, _, c, t, o in obs:
        tally[(t, sha)][c][o] += 1

    cats = Counter()
    mixed_by_test = defaultdict(set)
    q2a = 0
    for (t, sha), percell in tally.items():
        s = summarize(percell)
        cat = category(*s)
        cats[cat] += 1
        if s[0] and s[0] < s[1]:
            q2a += 1
            if cat == "masked_flake":
                mixed_by_test[t].add(sha)
    chronic = {t: s for t, s in mixed_by_test.items() if len(s) >= 3}
    p(f"\n  (test, sha) categories ...... {dict(cats)}   (pass = never failed at that commit; fails_always = p_hat 1.0)")
    p(f"  Q2(a) pairs with both fail and pass (any category) ...... {q2a}   <- need >= 5")
    p(f"  Q2(b) tests with spread recoveries across >= 3 commits .. {len(chronic)}   <- need >= 1")
    for t, shas in sorted(chronic.items(), key=lambda kv: -len(kv[1]))[:10]:
        p(f"      {len(shas)} commits  {t}")

    anchor = next(sha for sha in {s for _, s in tally} if sha.startswith(ANCHOR))
    p(f"\n  top 10 by pooled p_hat at {ANCHOR} (per-cell dispersion shown):")
    p(f"      {'p_hat':>6} {'fail':>4} {'n':>5} {'wilson95':>15} {'cells':>7} {'topcell':>7} {'topOS':>5}  category           test")
    rows = []
    for (t, sha), percell in tally.items():
        if sha != anchor:
            continue
        fails, n, nc, top, topos, present = summarize(percell)
        if fails:
            rows.append((fails / n, fails, n, wilson(fails, n), nc, present, top, topos, category(fails, n, nc, top, topos, present), t, percell))
    for ph, f, n, (lo, hi), nc, present, top, topos, cat, t, percell in sorted(rows, key=lambda r: (-r[0], -r[1]))[:10]:
        p(f"      {ph:6.3f} {f:4d} {n:5d} [{lo:5.3f}, {hi:5.3f}] {nc:3d}/{present:<3d} {top:7.2f} {topos:5.2f}  {cat:<18} {t}")
        p(f"             failing cells: {dict(sorted(((c, v['fail']) for c, v in percell.items() if v['fail']), key=lambda kv: -kv[1]))}")

    downloads = len(list(CACHE.glob("*.zip"))) - downloaded_before
    p(f"\n  artifact downloads this run .. {downloads} (cache total {downloaded_before + downloads})")
    p(f"  requests consumed ............ {rate_used() - used0}")
    ok = q2a >= 5 and len(chronic) >= 1
    p(f"\n  VERDICT: {'suitable - Source A pooled across cells with per-cell stratification' if ok else 'Q2(b) still 0 -> pre-committed fallback: Source C (job-level, test_id = cell)'}")
    Path("probe-results/dask-distributed-pooled.md").write_text("```\n" + "\n".join(out) + "\n```\n", encoding="utf-8")


if __name__ == "__main__":
    main()
