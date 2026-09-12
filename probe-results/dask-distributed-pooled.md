```
REPO: dask/distributed   pooled over 34 cells, 191 schedule runs on main
  run-cell job conclusions .... {'failure': 360, 'success': 6119, 'cancelled': 15}
  failed run-cells ............ 360: with test failures 319, INFRA (artifact, zero failing tests) 9, UNRESOLVED (no/unparseable artifact) 32
  parse failures .............. 0 {}
  roster samples .............. 102 artifacts over 34 cells; worst drift oldest->newest (removed, added, common): [('macos-latest-py314-test-ci-ci1', (0, 6, 1344)), ('ubuntu-24.04-arm-py310-test-ci-ci1', (0, 6, 1365)), ('ubuntu-24.04-arm-py311-test-ci-ci1', (0, 6, 1357))]
  observations ................ 12606094

  (test, sha) categories ...... {'pass': 63487, 'masked_flake': 168, 'platform_specific': 15}   (pass = never failed at that commit; fails_always = p_hat 1.0)
  Q2(a) pairs with both fail and pass (any category) ...... 183   <- need >= 5
  Q2(b) tests with spread recoveries across >= 3 commits .. 19   <- need >= 1
      9 commits  distributed.tests.test_jupyter::test_shutdowns_cleanly
      7 commits  distributed.shuffle.tests.test_shuffle::test_handle_null_partitions_2
      6 commits  distributed.tests.test_gc::test_gc_diagnosis_cpu_time
      5 commits  distributed.tests.test_tls_functional::test_retire_workers
      4 commits  distributed.tests.test_nanny::test_failure_during_worker_initialization
      4 commits  distributed.cli.tests.test_dask_worker::test_error_during_startup[--no-nanny]
      4 commits  distributed.cli.tests.test_tls_cli::test_use_config_file
      4 commits  distributed.diagnostics.tests.test_scheduler_plugin::test_failing_sync_add_remove_worker
      4 commits  distributed.tests.test_tls_functional::test_nanny
      3 commits  distributed.dashboard.tests.test_components::test_profile_time_plot

  top 10 by pooled p_hat at 40fcd99a8c (per-cell dispersion shown):
       p_hat fail     n        wilson95   cells topcell topOS  category           test
       0.025    8   317 [0.013, 0.049]   5/9      0.25  0.62  masked_flake       distributed.shuffle.tests.test_shuffle::test_handle_null_partitions_2
             failing cells: {'windows-latest-py314-test-ci-notci1': 2, 'windows-latest-py313-test-ci-notci1': 2, 'ubuntu-latest-py313-test-ci-notci1': 2, 'ubuntu-latest-py311-test-ci-notci1': 1, 'windows-latest-py312-test-ci-notci1': 1}
       0.022   20   925 [0.014, 0.033]   7/12     0.40  0.55  masked_flake       distributed.tests.test_jupyter::test_shutdowns_cleanly
             failing cells: {'ubuntu-24.04-arm-py312-test-ci-notci1': 8, 'ubuntu-latest-py310-test-noqueue-notci1': 3, 'ubuntu-24.04-arm-py310-test-ci-notci1': 2, 'ubuntu-latest-py313-test-ci-notci1': 2, 'ubuntu-latest-py310-test-ci-notci1': 2, 'ubuntu-latest-py312-test-ci-notci1': 2, 'ubuntu-24.04-arm-py311-test-ci-notci1': 1}
       0.008   11  1313 [0.005, 0.015]   3/17     0.45  1.00  platform_specific  distributed.tests.test_gc::test_gc_diagnosis_cpu_time
             failing cells: {'windows-latest-py313-test-ci-notci1': 5, 'windows-latest-py310-test-ci-notci1': 4, 'windows-latest-py311-test-ci-notci1': 2}
       0.006    8  1313 [0.003, 0.012]   1/17     1.00  1.00  platform_specific  distributed.shuffle.tests.test_shuffle::test_restarting_during_transfer_raises_killed_worker
             failing cells: {'ubuntu-latest-py310-test-noqueue-notci1': 8}
       0.005    7  1313 [0.003, 0.011]   2/17     0.86  1.00  platform_specific  distributed.dashboard.tests.test_scheduler_bokeh::test_https_support
             failing cells: {'windows-latest-py310-test-ci-notci1': 6, 'windows-latest-py313-test-ci-notci1': 1}
       0.005    6  1313 [0.002, 0.010]   2/17     0.50  0.50  masked_flake       distributed.tests.test_active_memory_manager::test_RetireWorker_with_actor[True]
             failing cells: {'ubuntu-24.04-arm-py314-test-ci-notci1': 3, 'ubuntu-latest-py314-test-ci-notci1': 3}
       0.005    6  1317 [0.002, 0.010]   3/17     0.50  1.00  platform_specific  distributed.tests.test_stress::test_close_connections
             failing cells: {'windows-latest-py311-test-ci-ci1': 3, 'windows-latest-py312-test-ci-ci1': 2, 'windows-latest-py313-test-ci-ci1': 1}
       0.004    5  1317 [0.002, 0.009]   3/17     0.40  0.40  masked_flake       distributed.tests.test_failed_workers::test_restart_during_computation
             failing cells: {'windows-latest-py312-test-ci-ci1': 2, 'ubuntu-24.04-arm-py310-test-ci-ci1': 2, 'ubuntu-latest-py311-test-ci-ci1': 1}
       0.003    4  1313 [0.001, 0.008]   4/17     0.25  0.50  masked_flake       distributed.cli.tests.test_tls_cli::test_basic
             failing cells: {'ubuntu-24.04-arm-py313-test-ci-notci1': 1, 'ubuntu-24.04-arm-py314-test-ci-notci1': 1, 'ubuntu-latest-py310-test-ci-notci1': 1, 'ubuntu-latest-py314-test-ci-notci1': 1}
       0.002    3  1313 [0.001, 0.007]   2/17     0.67  0.67  masked_flake       distributed.cli.tests.test_tls_cli::test_nanny
             failing cells: {'ubuntu-latest-py314-test-ci-notci1': 2, 'ubuntu-24.04-arm-py313-test-ci-notci1': 1}

  artifact downloads this run .. 415 (cache total 793)
  requests consumed ............ 419

  VERDICT: suitable - Source A pooled across cells with per-cell stratification
```

## Notes (2026-09-12)

- Cost: 191 jobs requests + 415 artifact downloads (319 failed cells with test failures + 9 INFRA + 102 roster
  samples) = **419 requests**, versus ~6,000 for the naive all-cells download. Cache now 793 zips.
- UNRESOLVED 32 = failed cells on the 13 runs older than the 89-day artifact horizon (191 - 178). Expected, not a
  bug; they are excluded from numerator and denominator and counted here.
- INFRA 9 = job failed, artifact parsed, zero failing testcases (hard timeout / runner death). Excluded, counted.
- Roster drift over 89 days: at most 6 tests added, 0 removed, per cell. Nearest-in-time roster lookup covers it.
- `fails_always` = 0: no regression on `main` during the window in scheduled runs. Expected for a stable trunk;
  the regression fixture for Phase 2 will need to come from a PR branch or be found on a wider window.
- Q2(a) = 183, Q2(b) = 19. **Suitable. Source A, pooled across cells, stratified per cell.**

## Window boundary (stated plainly)

The 32 UNRESOLVED run-cells are all on the 13 scheduled runs older than 2026-06-14, past the 90-day artifact
retention. **Test-level window = 89 days. Older than that is job-level only.** Recorded in README limitations.

## Regression fixture (2026-09-12) - approach B, PR branches

Ranked 113 failed PR runs by failed-cell count. Regressions fail a whole partition (17 cells); flakes fail 1-3.
Chosen: `distributed.tests.test_core::test_server_listen`, PR #9356 "Avoid external IP lookup for inproc addresses"
(branch `mmaxjr:fix-localcluster-offline-warning`).

| sha | run | fail | pass | n | Wilson 95% |
|---|---|---|---|---|---|
| `25eb507474` (changed `comm/inproc.py`) | 33311351646 | 17 | 0 | 17 | [0.816, 1.000] |
| `a4b5b644ac` (fix, +`tests/test_core.py`) | 33315565877 | 0 | 17 | 17 | [0.000, 0.184] |

Test pre-exists on main and passes there. Failing cells: every cell of the `notci1` partition, all 4 OSes, all 5
Pythons. The other two failures at the fix sha (`test_web_preload_worker` on arm-py311, `test_clear_events_worker_removal`
on windows-py310) are single-cell flakes, not related. Lower bound 0.816 vs masked-flake upper bounds <= 0.05.

Other clean candidates seen, kept for reserve: `test_client::test_scatter_namedtuple` (9bb1b25092, 17/17),
`test_local_env::test_bad_executable` + `test_job_submission` (c9af892796, 17/17 each),
`test_actor::test_serialize_with_pickle` + 2 more (9ce93727b7, 17/17 each, both partitions).
