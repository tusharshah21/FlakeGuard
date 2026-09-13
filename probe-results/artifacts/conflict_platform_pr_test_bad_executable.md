# FlakeGuard: `distributed.deploy.tests.test_local_env::test_bad_executable`

FlakeGuard classified test_bad_executable as a regression with low confidence. The episode data shows a lower bound of 0.133, falling short of the regression threshold, and all five failures are concentrated on windows-latest, which suggests platform-specific behavior. However, the pooled data across all cells shows seventeen of seventeen cells failing with a high rate that would typically indicate a regression. The correlation analysis found no plausible link between the failing commit—which only modifies pyproject.toml to suppress a pytest warning on Windows—and the test's executable validation logic. These conflicting signals leave the root cause ambiguous.

## Verdict
**regression** - confidence 0.40
Primary signal: episode wilson95 [0.133, 0.531] lower bound 0.133

## Evidence
Computed deterministically by `flakeguard/stats.py`; the classifier saw exactly this block.
```
TEST: distributed.deploy.tests.test_local_env::test_bad_executable
WINDOW: 2026-07-20 to 2026-07-22; runs 9; commits 9

TEST LEVEL (all commits pooled)
  n 148 = measured 148 + inferred 0; failures 92; p_hat 0.622; wilson95 [0.541, 0.696]
  cells_failed 17 of cells_present 17; top_cell_share 0.08; top_os windows-latest share 0.38; concentrated False
  recovery_commits 3; spread_recovery_commits 1; chronic False; max_consecutive_failing_runs 7
  largest_shift_between_commits: failure rate 82/85 before -> 10/63 after 3865fc878b (2026-07-21), shift -0.806; onset_sha None

EPISODE (most recent commit with a failure): fa0e193f7f, 2026-07-21 to 2026-07-21, runs 1
  n 17 = measured 17 + inferred 0; failures 5; p_hat 0.294; wilson95 [0.133, 0.531]
  cells_failed 5 of cells_present 17; top_cell_share 0.20; top_os windows-latest share 1.00; concentrated True; recovery True
  failing cells (failures/observations): windows-latest-py310-test-ci-notci1 1/1, windows-latest-py311-test-ci-notci1 1/1, windows-latest-py312-test-ci-notci1 1/1, windows-latest-py313-test-ci-notci1 1/1, windows-latest-py314-test-ci-notci1 1/1
  within_commit_over_time: not computable (fewer than two groups)

PER COMMIT (chronological): sha, first_run, runs, n, measures, failures, p_hat, wilson95, cells_failed/cells_present
  4c1ce6daef 2026-07-20 1 17 17 17 1.000 [0.816, 1.000] 17/17
  afecbab9c2 2026-07-20 1 17 17 17 1.000 [0.816, 1.000] 17/17
  1c5fa061b6 2026-07-20 1 17 17 17 1.000 [0.816, 1.000] 17/17
  c9af892796 2026-07-20 1 17 17 17 1.000 [0.816, 1.000] 17/17
  a0a5267140 2026-07-21 1 17 17 14 0.824 [0.590, 0.938] 14/17
  3865fc878b 2026-07-21 1 17 17 5 0.294 [0.133, 0.531] 5/17
  fa0e193f7f 2026-07-21 1 17 17 5 0.294 [0.133, 0.531] 5/17
  caa97054bc 2026-07-21 1 17 17 0 0.000 [0.000, 0.184] 0/17
  53dc38b5d8 2026-07-22 1 12 12 0 0.000 [0.000, 0.243] 0/12

THRESHOLDS (from flakeguard.toml; identical to the deterministic baseline)
  regression: episode wilson95 lower bound >= 0.5
  flaky: episode wilson95 upper bound <= 0.1
  concentrated: failures >= 3 and (top_cell_share >= 0.75 or top_os_share >= 0.8)
  chronic: spread_recovery_commits >= 3
  onset: shift between commits >= 0.2
```

## Reasoning
The episode wilson95 lower bound is 0.133, which does not meet the regression threshold of 0.5. However, the episode shows concentrated True with all 5 failures on windows-latest (top_os share 1.00), pointing toward platform_specific, though the pooled data shows widespread failure across all 17 cells and a high rate that would suggest regression if episode data supported it.

## Conflicting signals
Episode concentrated True and top_os windows-latest share 1.00 point toward platform_specific. The pooled wilson95 [0.541, 0.696] lower bound 0.541 meets regression threshold and cells_failed 17 of cells_present 17 shows full spread, but the episode fails the regression threshold (0.133 < 0.5) and shows concentration.

## Correlation
Failing commit `fa0e193f7f` (2026-07-21): Try ignoring PytestUnraisableExceptionWarning on Windows
- `pyproject.toml` (modified, +1/-0)

Plausible cause: **no**
The change only modifies pyproject.toml to ignore a specific pytest warning on Windows, which affects test reporting/filtering but not test execution logic. The test test_bad_executable exercises executable validation in distributed deployment, which cannot be affected by a warning suppression configuration change.

_Reasoned forward from this commit only; FlakeGuard was not shown any later commit._

## Recommended action
Open an issue naming the failing commit and the likely file. Do not quarantine: the test is doing its job.

Open an issue naming the failing commit and referencing the test. Do not quarantine the test, as it appears to be correctly detecting a problem. Investigate whether the Windows-specific configuration change in pyproject.toml has an indirect effect on test execution or whether a separate, undetected change is responsible for the failures. The concentration on windows-latest warrants platform-specific debugging to determine if this is a genuine regression or an environmental issue.

## How to override
FlakeGuard acted on statistics, not on knowledge of this code. If this is wrong:
- add the test id to `[overrides] ignore_tests` in `flakeguard.toml` to stop all future actions on it, or
- apply the label `flakeguard-override` to this issue or PR; the next sweep records the override and stops acting on this test.
Closing this issue or PR without either has no effect - the next sweep will recreate it once, then stop and record the disagreement.
