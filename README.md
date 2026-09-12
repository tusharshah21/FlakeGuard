# FlakeGuard

Autonomous flaky-test triage agent for GitHub Actions + pytest, built on the Strands Agents SDK.

**The determinism boundary:** the LLM reasons; it never carries a fact or a number. All statistics
are computed in Python and pinned into prompts as ground truth. Scheduling, idempotency, deduplication
and rate limiting live in code, not in the model.

## Setup

```sh
uv sync
cp .env.example .env   # fill in GITHUB_TOKEN + AWS creds
uv run scripts/check_bedrock.py
```

`dry_run = true` in `flakeguard.toml` until you point it at a scratch repo you own.

## License

MIT — see [LICENSE](LICENSE).

## Design notes (from the Phase 0.5 probe)

The target repo, `dask/distributed`, never re-runs GitHub Actions workflows (`run_attempt` is always 1).
It retries failing tests in-process with `pytest-rerunfailures`, so the retry signal lives inside the
JUnit XML artifacts. That reshapes the product:

- **What FlakeGuard surfaces is the flakiness your reruns are hiding.** A flaky test usually ends with a
  green run; nobody sees it. FlakeGuard reads the reruns the CI swallowed.
- **Three-way classification** (Phase 3 prompt):
  - *masked flake* — fails, passes on rerun, same commit, run ends green
  - *regression* — fails all reruns, failures cluster after one commit
  - *chronic* — recovers repeatedly across many commits over a long period
- **Retry recovery** (Phase 2) = rerun-recoveries within a single run on a single commit. The commit is
  identical by construction, not by comparison.
- **Dedup key** (Phase 1) = `(run_id, test_id, rerun_index)`, where `rerun_index` is the testcase's
  position in its rerun sequence in the XML.
- **Artifact volume cap.** One canonical matrix cell is ingested across the full window; all cells are
  pulled for a handful of runs only, for a secondary cross-platform signal. The cell is config, not code.

### Per-commit failure probability (Phase 2)

dask's `Tests` workflow re-runs the full suite on `main` twice daily by cron, so a single commit accumulates
many independent runs of identical code. That makes per-test flakiness a measured probability, not a heuristic.
`stats.py` computes, per `(test_id, head_sha, cell)`: `n` (independent runs), `p_hat = failures / n`, and the
95% Wilson score interval on `p_hat`. Classification then rests on the interval:

- *regression* — lower bound close to 1.0 (fails essentially always)
- *masked flake* — interval strictly between 0 and 1
- *chronic* — flake interval excludes 0 across >= 3 distinct commits
- *environment break* — at a fixed commit, failures cluster in time rather than scatter (the code did not
  change; the runner image, transitive deps or an upstream service did)
- *platform-specific* — failures concentrated in one cell or OS across the matrix
- *unclear* — `n` too small for the interval to separate the cases

`n` and the bounds are pinned into the classifier prompt as evidence. The model interprets; it never computes.
Same-commit comparison is restricted to `event = schedule`, `branch = main`, one canonical matrix cell; trigger,
sha, branch and cell are first-class columns so the filter is explicit in every query.

### The matrix is a failure multiplier

Every one of dask/distributed's 34 test-matrix cells is ~98% green. Yet 162 of 191 scheduled runs go red. A
34-cell matrix amplifies rare per-cell flakiness into near-constant failure: each cell flips its own coin, and
the run fails when any one of them lands wrong. No single cell's history reveals this - restricted to one cell,
89 days of data surfaced six tests that ever failed. Pooled across cells, the same window shows 19 tests that
recover repeatedly across three or more commits. This is why per-cell dashboards miss the problem, and why
cross-cell pooling is the right unit of analysis.

Pooling has to be done carefully. Cells are not exchangeable (different OS, different Python), so a test that
fails on every Windows run and nowhere else would read as a tidy 9% flake if pooled blindly. FlakeGuard
stratifies first: per-cell counts are kept, a simple dispersion check (share of failures in the top cell / top
OS, number of cells with any failure) decides whether failures are spread or concentrated, and only spread
failures are pooled. Concentrated ones are a fifth category, *platform-specific*.

### Zero always-failing tests is itself a finding

Across 95 days of scheduled runs on `main` there were **zero** tests that failed at every run of a commit.
dask's problem is not broken tests. It is that a 34-cell matrix converts a ~2% per-test flake rate into an ~85%
run failure rate. The failures are real, reproducible in aggregate, and invisible in any single cell.

Regressions do exist - on PR branches, where they get fixed within hours and never reach `main`. The Phase 2
regression fixture (`fixtures/regression_test_server_listen.json`) is one such case: PR #9356 broke
`test_core::test_server_listen` in all 17 cells at one commit and fixed it in the next.

## Limitations

- **Test-level history is 89 days deep.** GitHub retains artifacts for 90 days; runs outlive them. Anything
  older is job-level only (which cell failed, not which test).
- GitHub Actions and pytest JUnit XML only. One workflow per repo.
- Rosters for passing cells come from sampled artifacts, not from every run; a test added mid-window is
  counted as passing from the nearest sampled roster onward.

## Prior art and how this differs

dask/distributed ships its own hand-rolled flaky-test report (`continuous_integration/scripts/test_report.py`).
FlakeGuard does not read or adapt that code. The difference is in kind: their script produces a static report a
human must go read; FlakeGuard triages, decides, and acts - a quarantine PR, an issue with the correlated onset
commit, and automatic un-quarantine when a test recovers. That the maintainers built a report at all is evidence
they want this problem solved.
