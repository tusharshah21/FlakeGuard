# FlakeGuard: `distributed.shuffle.tests.test_shuffle::test_restarting_during_transfer_raises_killed_worker`

The test test_restarting_during_transfer_raises_killed_worker has been classified as platform_specific with confidence 0.95. All 14 failures across 3211 observations occurred in a single cell (ubuntu-latest-py310-test-noqueue-notci1), yielding a top_cell_share of 1.00 and top_os_share of 1.00, which meets the concentrated threshold. Although Episode wilson95 upper bound 0.015 suggests a flaky pattern, the concentration rules explicitly override the pooled rate analysis. FlakeGuard has decided to issue based on this evidence, as the verdict clears the action threshold of 0.75 with 191 runs in the window.

## Verdict
**platform_specific** - confidence 0.95
Primary signal: concentrated True (top_cell_share 1.00, top_os_share 1.00)

## Evidence
Computed deterministically by `flakeguard/stats.py`; the classifier saw exactly this block.
```
TEST: distributed.shuffle.tests.test_shuffle::test_restarting_during_transfer_raises_killed_worker
WINDOW: 2026-06-09 to 2026-09-12; runs 191; commits 16

TEST LEVEL (all commits pooled)
  n 3211 = measured 227 + inferred 2984; failures 14; p_hat 0.004; wilson95 [0.003, 0.007]
  cells_failed 1 of cells_present 17; top_cell_share 1.00; top_os ubuntu-latest share 1.00; concentrated True
  recovery_commits 5; spread_recovery_commits 0; chronic False; max_consecutive_failing_runs 2
  largest_shift_between_commits: failure rate 0/274 before -> 14/2937 after 2697a1ab46 (2026-06-17), shift +0.005; onset_sha None

EPISODE (most recent commit with a failure): dc182bda54, 2026-08-26 to 2026-09-12, runs 34
  n 577 = measured 37 + inferred 540; failures 3; p_hat 0.005; wilson95 [0.002, 0.015]
  cells_failed 1 of cells_present 17; top_cell_share 1.00; top_os ubuntu-latest share 1.00; concentrated True; recovery True
  failing cells (failures/observations): ubuntu-latest-py310-test-noqueue-notci1 3/34
  within_commit_over_time: failure rate 2/509 before -> 1/68 after dc182bda54 (2026-09-10), shift +0.011

PER COMMIT (chronological): sha, first_run, runs, n, measures, failures, p_hat, wilson95, cells_failed/cells_present
  8d598236df 2026-06-09 1 15 0 0 0.000 [0.000, 0.204] 0/15
  db3cb43a6f 2026-06-09 4 65 0 0 0.000 [0.000, 0.056] 0/17
  aa2ddc315e 2026-06-11 12 194 7 0 0.000 [0.000, 0.019] 0/17
  2697a1ab46 2026-06-17 4 68 10 1 0.015 [0.003, 0.079] 1/17
  3b0ba32760 2026-06-19 24 405 39 0 0.000 [0.000, 0.009] 0/17
  382f679088 2026-07-01 1 17 1 0 0.000 [0.000, 0.184] 0/17
  2d43f7f6f1 2026-07-02 1 17 3 0 0.000 [0.000, 0.184] 0/17
  ee15bd344e 2026-07-02 2 34 2 1 0.029 [0.005, 0.149] 1/17
  9e706be482 2026-07-03 1 17 0 0 0.000 [0.000, 0.184] 0/17
  edf67787a4 2026-07-04 5 85 5 0 0.000 [0.000, 0.043] 0/17
  cb17a3d008 2026-07-06 6 100 6 0 0.000 [0.000, 0.037] 0/17
  462a51ae3a 2026-07-09 6 102 5 1 0.010 [0.002, 0.053] 1/17
  40fcd99a8c 2026-07-12 78 1313 99 8 0.006 [0.003, 0.012] 1/17
  c88eb0b8c4 2026-08-20 9 151 13 0 0.000 [0.000, 0.025] 0/17
  0a341df478 2026-08-25 3 51 0 0 0.000 [0.000, 0.070] 0/17
  dc182bda54 2026-08-26 34 577 37 3 0.005 [0.002, 0.015] 1/17

THRESHOLDS (from flakeguard.toml; identical to the deterministic baseline)
  regression: episode wilson95 lower bound >= 0.5
  flaky: episode wilson95 upper bound <= 0.1
  concentrated: failures >= 3 and (top_cell_share >= 0.75 or top_os_share >= 0.8)
  chronic: spread_recovery_commits >= 3
  onset: shift between commits >= 0.2
```

## Reasoning
All 14 failures across 3211 observations occur in a single cell (ubuntu-latest-py310-test-noqueue-notci1), with top_cell_share 1.00 and top_os_share 1.00 meeting the concentrated threshold. The rules explicitly state that concentration overrides the pooled interval, making this platform_specific despite the low pooled rate.

## Conflicting signals
Episode wilson95 upper bound 0.015 suggests flaky pattern, but concentration overrides pooled rate per rules.

## Recommended action
**issue** - Verdict platform_specific at confidence 0.95 clears action_threshold = 0.75 with 191 runs in the window; FlakeGuard will issue.

FlakeGuard will open an issue (or comment on the existing one) with this evidence. It will not quarantine: a test that fails deterministically is doing its job.

FlakeGuard will open an issue or comment on the existing one to document this platform-specific failure pattern. No quarantine will be applied because a test that fails deterministically on a specific platform configuration is functioning as intended by surfacing a real environment-specific problem. Maintainers should investigate why this test fails exclusively on ubuntu-latest-py310-test-noqueue-notci1 to determine whether the issue lies in the test assumptions, the code under test, or the platform configuration itself.

## How to override
FlakeGuard acted on statistics, not on knowledge of this code. If this is wrong:
- add the test id to `[overrides] ignore_tests` in `flakeguard.toml` to stop all future actions on it, or
- apply the label `flakeguard-override` to this issue or PR; the next sweep records the override and stops acting on this test.
Closing this issue or PR without either has no effect - the next sweep will recreate it once, then stop and record the disagreement.
