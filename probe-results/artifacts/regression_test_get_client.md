# FlakeGuard: `distributed.tests.test_worker::test_get_client`

FlakeGuard identified a regression in test_get_client with high confidence. The test failed universally across all cells at commit 9ce93727b7 before passing completely at the subsequent commit, yielding an episode wilson95 lower bound of 0.816. Although a conflicting signal was detected—a largest_shift_between_commits analysis showing failures transitioning to success at commit 696800cc91—this shift occurred in the wrong direction for an environment break, with failures preceding success rather than the reverse. Correlation analysis found a plausible link to distributed/worker.py, which was modified in the implicated commit and directly affects the worker client functionality exercised by this test. The pattern indicates a genuine regression that was quickly fixed.

## Verdict
**regression** - confidence 0.95
Primary signal: episode wilson95 lower bound 0.816

## Evidence
Computed deterministically by `flakeguard/stats.py`; the classifier saw exactly this block.
```
TEST: distributed.tests.test_worker::test_get_client
WINDOW: 2026-08-04 to 2026-08-05; runs 2; commits 2

TEST LEVEL (all commits pooled)
  n 34 = measured 34 + inferred 0; failures 17; p_hat 0.500; wilson95 [0.341, 0.659]
  cells_failed 17 of cells_present 17; top_cell_share 0.06; top_os ubuntu-latest share 0.35; concentrated False
  recovery_commits 0; spread_recovery_commits 0; chronic False; max_consecutive_failing_runs 1
  largest_shift_between_commits: failure rate 17/17 before -> 0/17 after 696800cc91 (2026-08-05), shift -1.000; onset_sha None

EPISODE (most recent commit with a failure): 9ce93727b7, 2026-08-04 to 2026-08-04, runs 1
  n 17 = measured 17 + inferred 0; failures 17; p_hat 1.000; wilson95 [0.816, 1.000]
  cells_failed 17 of cells_present 17; top_cell_share 0.06; top_os ubuntu-latest share 0.35; concentrated False; recovery False
  failing cells (failures/observations): macos-latest-py314-test-ci-ci1 1/1, ubuntu-24.04-arm-py310-test-ci-ci1 1/1, ubuntu-24.04-arm-py311-test-ci-ci1 1/1, ubuntu-24.04-arm-py312-test-ci-ci1 1/1, ubuntu-24.04-arm-py313-test-ci-ci1 1/1, ubuntu-24.04-arm-py314-test-ci-ci1 1/1, ubuntu-latest-py310-test-ci-ci1 1/1, ubuntu-latest-py310-test-noqueue-ci1 1/1, ubuntu-latest-py311-test-ci-ci1 1/1, ubuntu-latest-py312-test-ci-ci1 1/1, ubuntu-latest-py313-test-ci-ci1 1/1, ubuntu-latest-py314-test-ci-ci1 1/1, windows-latest-py310-test-ci-ci1 1/1, windows-latest-py311-test-ci-ci1 1/1, windows-latest-py312-test-ci-ci1 1/1, windows-latest-py313-test-ci-ci1 1/1, windows-latest-py314-test-ci-ci1 1/1
  within_commit_over_time: not computable (fewer than two groups)

PER COMMIT (chronological): sha, first_run, runs, n, measures, failures, p_hat, wilson95, cells_failed/cells_present
  9ce93727b7 2026-08-04 1 17 17 17 1.000 [0.816, 1.000] 17/17
  696800cc91 2026-08-05 1 17 17 0 0.000 [0.000, 0.184] 0/17

THRESHOLDS (from flakeguard.toml; identical to the deterministic baseline)
  regression: episode wilson95 lower bound >= 0.5
  flaky: episode wilson95 upper bound <= 0.1
  concentrated: failures >= 3 and (top_cell_share >= 0.75 or top_os_share >= 0.8)
  chronic: spread_recovery_commits >= 3
  onset: shift between commits >= 0.2
```

## Reasoning
The episode wilson95 lower bound of 0.816 exceeds the regression threshold of 0.5, and failures occurred in all 17 of 17 cells_present with concentrated False, meeting the regression criteria. The test failed universally at commit 9ce93727b7 then passed completely at the next commit, indicating a true regression that was subsequently fixed.

## Conflicting signals
largest_shift_between_commits shows failure rate 17/17 before -> 0/17 after 696800cc91 with shift -1.000, which could suggest environment_break, but the shift is in the wrong direction (failures came first, then success)

## Correlation
Failing commit `9ce93727b7` (2026-08-04): Propagate task annotations during worker execution
- `distributed/tests/test_worker_client.py` (modified, +24/-0)
- `distributed/worker.py` (modified, +6/-7)

Plausible cause: **yes** - `distributed/worker.py`
The test `test_get_client` is in `distributed/tests/test_worker.py` and exercises worker client functionality. The commit modifies `distributed/worker.py` with 6 additions and 7 deletions, changing worker execution behavior which directly affects how workers handle client operations tested by `test_get_client`.

_Reasoned forward from this commit only; FlakeGuard was not shown any later commit._

## Recommended action
Open an issue naming the failing commit and the likely file. Do not quarantine: the test is doing its job.

Open an issue documenting the regression at the failing commit and highlighting distributed/worker.py as the likely cause. Do not quarantine the test; it correctly detected a real code defect that has since been resolved. The issue will serve as a record of the regression and help maintainers understand the relationship between changes to worker execution behavior and client operation handling.

## How to override
FlakeGuard acted on statistics, not on knowledge of this code. If this is wrong:
- add the test id to `[overrides] ignore_tests` in `flakeguard.toml` to stop all future actions on it, or
- apply the label `flakeguard-override` to this issue or PR; the next sweep records the override and stops acting on this test.
Closing this issue or PR without either has no effect - the next sweep will recreate it once, then stop and record the disagreement.
