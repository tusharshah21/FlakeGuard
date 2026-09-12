"""Deterministic statistics over observations. Pure functions, plain data, no thresholds of their own.

Input rows have the contract shape {run_id, head_sha, branch, event, started_at, cell, test_id, outcome, source}.
Every threshold is passed in (from flakeguard.toml [stats]) so this module and the classifier prompt cannot disagree.
"""
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field


def wilson(fails: int, n: int, z: float) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion. Honest at small n, unlike the normal approximation."""
    if n == 0:
        return 0.0, 1.0
    p = fails / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def os_of(cell: str) -> str:
    return cell.split("-py")[0]


@dataclass
class Thresholds:
    z: float
    min_onset_effect: float
    platform_min_fails: int
    platform_top_cell_share: float
    platform_top_os_share: float
    chronic_min_commits: int


@dataclass
class Split:
    """Failure rate before vs after a boundary. `shift` is signed: positive means failures rose after `at_sha`."""
    at_sha: str
    at_started_at: str
    before_n: int
    before_fails: int
    after_n: int
    after_fails: int
    shift: float


@dataclass
class CommitStats:
    head_sha: str
    first_started_at: str
    last_started_at: str
    runs: int
    n: int
    n_measured: int
    n_inferred: int
    fails: int
    p_hat: float
    ci_low: float
    ci_high: float
    cells_total: int
    cells_failed: int
    top_cell_share: float
    top_os: str | None
    top_os_share: float
    recovery: bool
    concentrated: bool
    per_cell: dict[str, list[int]]          # cell -> [fails, n]
    temporal: Split | None                  # largest within-commit shift over time; env-break signal


@dataclass
class TestHealth:
    test_id: str
    window_start: str
    window_end: str
    runs: int
    n: int
    n_measured: int
    n_inferred: int
    fails: int
    p_hat: float
    ci_low: float
    ci_high: float
    cells_total: int
    cells_failed: int
    top_cell_share: float                   # share of all failures in the single worst cell
    top_os: str | None
    top_os_share: float
    concentrated: bool                      # test-level dispersion rule, same thresholds as per commit
    max_consecutive_failing_runs: int
    recovery_commits: int                   # commits with both a fail and a pass
    spread_recovery_commits: int            # recoveries at commits where neither the commit nor the test is concentrated
    chronic: bool                           # spread_recovery_commits >= chronic_min_commits
    largest_shift: Split | None             # biggest change in failure rate between consecutive commits
    onset_sha: str | None                   # largest_shift.at_sha when the shift is a rise >= min_onset_effect
    commits: list[CommitStats] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _rate(fails, n):
    return fails / n if n else 0.0


def best_split(groups: list[tuple[str, str, int, int]]) -> Split | None:
    """groups: chronological (sha, started_at, fails, n). Returns the boundary with the largest |rate_after - rate_before|."""
    if len(groups) < 2:
        return None
    total_f = sum(g[2] for g in groups)
    total_n = sum(g[3] for g in groups)
    best, bf, bn = None, 0, 0
    for i in range(len(groups) - 1):
        bf, bn = bf + groups[i][2], bn + groups[i][3]
        af, an = total_f - bf, total_n - bn
        shift = _rate(af, an) - _rate(bf, bn)
        if best is None or abs(shift) > abs(best.shift):
            best = Split(groups[i + 1][0], groups[i + 1][1], bn, bf, an, af, shift)
    return best


def dispersion(fail_cells: dict[str, int], cells_present: int, t: Thresholds) -> tuple[float, str | None, float, bool]:
    """(top_cell_share, top_os, top_os_share, concentrated) from per-cell failure counts."""
    fails = sum(fail_cells.values())
    top_cell_share = max(fail_cells.values()) / fails if fails else 0.0
    os_fails = Counter()
    for c, k in fail_cells.items():
        os_fails[os_of(c)] += k
    top_os, top_os_fails = (os_fails.most_common(1)[0] if os_fails else (None, 0))
    top_os_share = top_os_fails / fails if fails else 0.0
    concentrated = (fails >= t.platform_min_fails and cells_present > 1
                    and (top_cell_share >= t.platform_top_cell_share or top_os_share >= t.platform_top_os_share))
    return top_cell_share, top_os, top_os_share, concentrated


def commit_stats(sha: str, rows: list[dict], t: Thresholds) -> CommitStats:
    per_cell = defaultdict(lambda: [0, 0])
    per_run = defaultdict(lambda: [0, 0])
    run_started = {}
    src = Counter()
    for r in rows:
        f = r["outcome"] == "fail"
        per_cell[r["cell"]][0] += f
        per_cell[r["cell"]][1] += 1
        per_run[r["run_id"]][0] += f
        per_run[r["run_id"]][1] += 1
        run_started[r["run_id"]] = r["started_at"]
        src[r["source"]] += 1
    n = len(rows)
    fails = sum(v[0] for v in per_cell.values())
    fail_cells = {c: v[0] for c, v in per_cell.items() if v[0]}
    top_cell_share, top_os, top_os_share, concentrated = dispersion(fail_cells, len(per_cell), t)
    lo, hi = wilson(fails, n, t.z)
    runs_chrono = sorted(per_run, key=run_started.get)
    temporal = best_split([(sha, run_started[rid], per_run[rid][0], per_run[rid][1]) for rid in runs_chrono])
    starts = sorted(run_started.values())
    return CommitStats(
        head_sha=sha, first_started_at=starts[0], last_started_at=starts[-1], runs=len(per_run),
        n=n, n_measured=src["artifact"], n_inferred=src["roster"], fails=fails, p_hat=_rate(fails, n),
        ci_low=lo, ci_high=hi, cells_total=len(per_cell), cells_failed=len(fail_cells),
        top_cell_share=top_cell_share, top_os=top_os, top_os_share=top_os_share,
        recovery=bool(fails) and fails < n, concentrated=concentrated,
        per_cell={c: list(v) for c, v in sorted(per_cell.items())}, temporal=temporal,
    )


def test_health(rows: list[dict], t: Thresholds) -> TestHealth:
    """All statistics for one test over the given observations. Rows may come from storage or a fixture."""
    if not rows:
        raise ValueError("no observations")
    test_id = rows[0]["test_id"]
    by_sha = defaultdict(list)
    for r in rows:
        by_sha[r["head_sha"]].append(r)
    commits = sorted((commit_stats(sha, v, t) for sha, v in by_sha.items()), key=lambda c: c.first_started_at)

    n = len(rows)
    fails = sum(c.fails for c in commits)
    lo, hi = wilson(fails, n, t.z)
    cells = {r["cell"] for r in rows}
    fail_cells = Counter(r["cell"] for r in rows if r["outcome"] == "fail")
    top_cell_share, top_os, top_os_share, concentrated = dispersion(fail_cells, len(cells), t)

    run_failed = defaultdict(bool)
    run_started = {}
    for r in rows:
        run_failed[r["run_id"]] |= r["outcome"] == "fail"
        run_started[r["run_id"]] = r["started_at"]
    streak = best = 0
    for rid in sorted(run_failed, key=run_started.get):
        streak = streak + 1 if run_failed[rid] else 0
        best = max(best, streak)

    recoveries = [c for c in commits if c.recovery]
    spread = [] if concentrated else [c for c in recoveries if not c.concentrated]
    shift = best_split([(c.head_sha, c.first_started_at, c.fails, c.n) for c in commits])
    onset = shift.at_sha if shift and shift.shift >= t.min_onset_effect else None
    return TestHealth(
        test_id=test_id, window_start=min(run_started.values()), window_end=max(run_started.values()),
        runs=len(run_failed), n=n, n_measured=sum(c.n_measured for c in commits), n_inferred=sum(c.n_inferred for c in commits),
        fails=fails, p_hat=_rate(fails, n), ci_low=lo, ci_high=hi,
        cells_total=len(cells), cells_failed=len(fail_cells), top_cell_share=top_cell_share, top_os=top_os,
        top_os_share=top_os_share, concentrated=concentrated, max_consecutive_failing_runs=best,
        recovery_commits=len(recoveries), spread_recovery_commits=len(spread),
        chronic=len(spread) >= t.chronic_min_commits, largest_shift=shift, onset_sha=onset, commits=commits,
    )
