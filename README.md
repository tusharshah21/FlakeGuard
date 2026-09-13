# FlakeGuard

Autonomous flaky-test triage agent for GitHub Actions + pytest, built on the Strands Agents SDK.

**The determinism boundary:** the LLM reasons; it never carries a fact or a number. All statistics
are computed in Python and pinned into prompts as ground truth. Scheduling, idempotency, deduplication
and rate limiting live in code, not in the model.

## Why now

On 2026-08-04, dask/distributed PR #9340, titled "[unsupervised AI] fix: propagate task annotations during
worker execution", changed `distributed/worker.py`. At that commit three pre-existing tests in other modules -
`test_worker::test_get_client`, `test_client::test_secede_balances`, `test_actor::test_serialize_with_pickle` -
failed in 17 of 17 cells each, across both matrix partitions, all four operating systems and all five Python
versions. The next commit changed `worker.py` again and all three passed 17/17. None of the three test files
were edited. Runs [30925383561](https://github.com/dask/distributed/actions/runs/30925383561) and
[30970740435](https://github.com/dask/distributed/actions/runs/30970740435).

The volume of machine-generated changes is rising faster than review capacity. Triage that is automatic,
evidence-based and reversible is how a CI signal stays trustworthy under that load.

## Setup

```sh
uv sync
cp .env.example .env              # GITHUB_TOKEN (classic, public_repo scope) + Bedrock creds
uv run scripts/check_bedrock.py   # one Bedrock call must succeed
uv run python -m flakeguard ingest   # ~90 days of dask/distributed CI into flakeguard.db (~650 requests first time, cached after)
uv run pytest                     # fixture <-> storage contract, JUnit collapse rule, stats over the three fixtures
uv run python -m flakeguard health fixtures/regression_test_get_client.json   # or a test_id, read from storage
uv run scripts/reconcile.py       # storage must reproduce the probe's headline numbers exactly
```

`dry_run = true` in `flakeguard.toml` until you point it at a scratch repo you own.

## Data contract

Every observation, whether read from storage or loaded from `fixtures/*.json`, has exactly this shape:

```
{run_id, head_sha, branch, event, started_at, cell, test_id, outcome, source}
```

`outcome` is `pass` or `fail` (skipped tests are not observations). `source` is `artifact` when the outcome was
read from a JUnit file, `roster` when it is a pass inferred from a succeeded job plus the cell's nearest-in-time
roster; inferred rows are derived at read time and never stored. The dedup key is `(run_id, test_id, cell)`.

A test id can appear twice in one JUnit file: pytest emits a second `<testcase>` when teardown errors after the
call. Duplicates collapse with an explicit precedence, `fail > pass`, so the stored outcome does not depend on
parse order; every collapse is counted by `(first, second)` pair and reported by the ingest. **Known
simplification:** a pass-then-teardown-error is a distinct phenomenon - usually a resource leak, not flakiness -
and today it is collapsed to `fail`. In the current data all 3 collapses are `(fail, fail)`.

Per run-cell, ingestion records one of: `parsed` (artifact with failures), `roster` (job succeeded), `infra`
(job failed, artifact has zero failing tests), `unresolved` (job failed, no usable artifact), `skipped`
(cancelled). Nothing is dropped silently; `scripts/reconcile.py` prints the counts.

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

`flakeguard/stats.py` (no `strands` import, enforced by a test) computes per test and per commit: `n` split into
`n_measured` (read from a JUnit file) and `n_inferred` (roster), `p_hat`, the Wilson interval, `cells_failed /
cells_total`, per-cell counts, top-cell and top-OS failure share, recovery commits (both a fail and a pass at one
commit), spread recoveries (not concentrated in one cell or OS), the chronic flag, the largest shift in failure
rate between consecutive commits (an onset when it is a rise), and the largest within-commit shift over time (the
environment-break signal). Every threshold comes from `[stats]` in `flakeguard.toml`; the module has none of its
own. `n` and the bounds are pinned into the classifier prompt as evidence. The model interprets; it never computes.

**Causal direction is guarded.** The correlation agent (Phase 4) receives only the *failing* commit's metadata and
file list - never the fix commit's. A test asserts that `fix_sha` and `fix_commit_files` are absent from
everything the agent is shown. If they ever leak, the agent is reasoning backward from the answer.
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

Regressions do exist - on PR branches, where they get fixed within hours and never reach `main`. The two
regression fixtures come from there:

- `fixtures/regression_test_get_client.json` (primary): PR #9340 changed `distributed/worker.py` and broke three
  unrelated pre-existing tests in every cell of their partition; the fix changed `worker.py` again and touched
  none of the broken tests. The tests recovered purely because the source changed back.
- `fixtures/regression_test_server_listen.json`: PR #9356 changed `distributed/comm/inproc.py` and broke
  `test_core::test_server_listen` in all 17 cells; the fix changed `inproc.py` and, legitimately, the test's
  expectation. The interesting second case: the agent must still point at the source file.

### Regressions fail a partition; flakes fail a cell or three

Found while searching for the fixtures, and a structural property of the data: every 17/17 failure in 113 failed
PR runs was a regression, and every masked flake on `main` failed in 1-3 cells. `cells_failed / cells_total` at a
commit is therefore a strong prior on category before any probability is computed, and `stats.py` reports it as a
first-class statistic.

## Why a model - measured, not asserted

A threshold rule on the Wilson interval (`flakeguard/baseline.py`) classifies the three primary fixtures correctly.
So does the model. The question is what happens where a single signal is misleading. We built a conflict set of
four real cases from the data - **three are the same failure mode (failures concentrated in one cell or one OS)
and one is a `cells_present` trap**, so a good score here demonstrates cell-concentration reasoning specifically,
not multi-signal reasoning in general - and ran baseline and classifier over every fixture ten times at
temperature 0 (`scripts/eval_classifier.py --runs 10`, Claude Sonnet 4.5 on Bedrock, raw output in
`probe-results/eval-phase3-sonnet45-10runs.txt`).

| fixture | truth | baseline | classifier (10 runs) | confidence |
|---|---|---|---|---|
| regression `test_get_client` | regression | regression | regression x10 | 0.95 |
| regression `test_server_listen` | regression | regression | regression x10 | 0.95 |
| flake `test_shutdowns_cleanly` | flaky / chronic | flaky | chronic x10 | 0.85 |
| ambiguous `test_handle_null_partitions_2` | unclear | unclear | unclear x10 | 0.40 |
| conflict: all 14 failures in one cell | platform_specific | flaky | **platform_specific x10** | 0.95 |
| conflict: all 22 failures on Windows, 4 cells | platform_specific | flaky | **platform_specific x10** | 0.92 |
| conflict: PR branch, episode 5/17 all Windows | platform_specific | unclear | **regression x10** (wrong) | 0.40-0.75 |
| trap: 9/9 in the 9 cells where the test exists | regression | regression | **environment_break x10** (wrong) | 0.95 |

**Primary set: baseline 4/4, classifier 4/4. Conflict set: baseline 1/4, classifier 2/4.** Zero verdict flips
across the ten runs; zero invented numbers in 80 outputs (every numeric token in the model's prose was checked
against the evidence it was given).

### The classifier's most instructive failure

The PR-branch case is kept as a permanent miss. The branch (`venv_cluster`) had a real regression first - four
commits at 17/17 - then two commits where only the five Windows cells still failed. The model saw both and, ten
times out of ten, wrote this in `conflicting_signals` before choosing `regression` at 0.40:

> "The episode is concentrated (top_os windows-latest share 1.00) pointing toward platform_specific. The pooled
> wilson95 [0.541, 0.696] lower bound 0.541 meets regression threshold and cells_failed 17 of cells_present 17
> shows broad impact. The largest shift -0.806 shows improvement rather than degradation."

Every number in that sentence is real, and every signal it names is the right one; it then weighed the pooled
history over the episode. That is a defensible wrong answer on the hardest case in the set, at a confidence the
action gate would never act on, and it is the clearest demonstration we have that `conflicting_signals` does its
job: a reviewer reading it knows exactly what to check. We have not tuned it away.

### The trap case: a prompt fix that was tried, measured, and reverted

The trap miss looked like an underspecified definition: the prompt said an environment break is failures beginning
"after a period of none" and the evidence block shows a 0/9 to 9/9 jump *between* commits without saying that the
definition means *within* one. We added one sentence - "The boundary must fall WITHIN one commit's runs; a jump
from 0/n to n/n BETWEEN commits is a regression signature, not an environment break" - and re-ran the full set ten
times (`probe-results/eval-phase3-sonnet45-10runs-postfix.txt`).

| case | before (10 runs) | after (10 runs) |
|---|---|---|
| trap: 9/9 of 9 present cells | environment_break x10, 0.95 | **regression x10, 0.95** - fixed, reasoning correct |
| ambiguous | unclear x10, 0.40 | unclear x6, **flaky x4 at 0.75** - reasoning self-contradictory |
| PR-branch platform case | regression x10, 0 invented numbers | regression x10, **invented numbers in 7 of 10** (`100` as a percentage; once `0.159`, `0.965`) |
| other five | unchanged | unchanged |
| conflict score | 2/4 | 3/4 |
| invented numbers, 80 outputs | 0 | 9 |

The rule we set beforehand was: if the change perturbs any other case it was not a clarification. It perturbed
two, one of them onto the action threshold. **Reverted. The headline stays 2/4 and 0 invented numbers.** The
attempt is kept in the repo because it is itself a finding: at temperature 0, one sentence added to one verdict's
definition changed an unrelated verdict and broke number discipline elsewhere. That brittleness is the reason the
action gate is plain Python and not a prompt.

What the model adds over the rule, on this evidence: it catches concentration the pooled rate hides (2 of 3
platform cases), it never fabricates a statistic, and every verdict carries a `conflicting_signals` line that
says what pointed the other way - which is the part a human reviewer reads. The action gate in Phase 5 sits
on top of both, so a 0.40 verdict never touches the repository regardless of who produced it.

### Two findings from looking for hard cases

**dask's CI environment was stable for the whole window.** An environment break - a fixed commit whose failures
start on a date because a runner image, a transitive dependency or an upstream service moved - leaves a signature:
zero failures before a boundary, a material rate after, across cells. We searched both long-lived commits
(`40fcd99a8c`, 78 runs over 39 days; `dc182bda54`, 34 runs over 17 days). Failures run flat at ~3.5 per day, no
day spikes, and no test's failures begin on a date. The statistic (`within_commit_over_time`) and the category
(`environment_break`) are implemented; the data contains no instance; we did not fabricate one.

## The denominator under every interval is validated

Most of any test's observations are inferred passes: the job succeeded, and the cell's nearest sampled roster
says the test runs there. Every Wilson interval in the system rests on that inference, so we checked it against
the data that does not depend on it. For every test that ever failed, and every cell in its roster, we asked: in
the artifacts we actually parsed for that cell, is the test always present?

**1,380 of 1,401 (test, cell) pairs: always present - 98.5%.** The 21 exceptions are not scattered. All 21 come
from a single artifact: run `28571672400`, cell `windows-latest-py310-test-ci-notci1`, 2026-07-02 07:00 UTC, a
`pytest.xml` holding 1,152 testcases against the cell's usual ~2,700 - pytest died mid-session and the tests
simply never ran. No disagreement clusters by date, by test, or by any other cell, and none is a test that was
conditionally skipped where the roster expected it. A truncated artifact also fails safe: absent tests produce no
observation at all, never a false pass. This is why the "mostly inferred" denominator is sound here, and why we
could not honestly build a conflict fixture where it misleads.

## Limitations

- **Test-level history is 89 days deep.** GitHub retains artifacts for 90 days; runs outlive them. Anything
  older is job-level only (which cell failed, not which test).
- GitHub Actions and pytest JUnit XML only. One workflow per repo.
- **Inferred denominators inherit the roster assumption.** A pass in a succeeded cell is inferred from "the job
  succeeded and the cell's nearest sampled roster contains this test", not read from a file. Most of any test's
  `n` is inferred - the flake fixture is 156 measured / 2111 inferred - so its Wilson interval is only as sound as
  that inference. Roster drift over the window is <= 6 tests added and 0 removed per cell, which is why the
  assumption holds here; `n_measured` and `n_inferred` are carried separately into every piece of evidence so the
  classifier can weigh it.

## Prior art and how this differs

dask/distributed ships its own hand-rolled flaky-test report (`continuous_integration/scripts/test_report.py`).
FlakeGuard does not read or adapt that code. The difference is in kind: their script produces a static report a
human must go read; FlakeGuard triages, decides, and acts - a quarantine PR, an issue with the correlated onset
commit, and automatic un-quarantine when a test recovers. That the maintainers built a report at all is evidence
they want this problem solved.
