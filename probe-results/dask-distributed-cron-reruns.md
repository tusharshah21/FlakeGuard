```
REPO: dask/distributed   canonical cell: ubuntu-latest-py312-test-ci-notci1
  schedule Tests runs on main (95d) .. 191; with live canonical artifact: 178
  canonical artifacts parsed ...... 178   parse failures: 0 {}
  observations ..................... 460665
  Q2(a) (test, sha) pairs with both fail and pass .. 6   <- need >= 5
  Q2(b) tests recovering across >= 3 commits ....... 0   <- need >= 1
  distinct tests with any failure .................. 6

  top 10 by p_hat at 40fcd99a8c (76 runs):
       p_hat   n        wilson95  test
       0.026  76 [0.007, 0.091]  distributed.tests.test_jupyter::test_shutdowns_cleanly
       0.013  76 [0.002, 0.071]  distributed.cli.tests.test_dask_worker::test_timeout[--no-nanny]
       0.013  76 [0.002, 0.071]  distributed.cli.tests.test_dask_worker::test_timeout[--nanny]

  multi-cell sample .... 5 runs x 40 cells cached (6 mindeps cells = distinct dependency env, excluded from canonical series); parse failures: 0
  requests consumed .... 4

  VERDICT: unsuitable - source A (junit artifacts, canonical cell ubuntu-latest-py312-test-ci-notci1); test-level window 89d; every observation stores run_started_at for the environment-drift check
```

## Notes (2026-09-12)

- Requests consumed by the full download: **635** (header `X-RateLimit-Used`; the `/rate_limit` JSON body lags and
  read 0). Cache: 378 zips, 17 MB, under `.cache/artifacts/` (gitignored). Re-parse costs ~4 requests.
- Parse failures: **0** on 178 canonical + 195 multi-cell artifacts, once the `Event File` artifact (not a test
  result) is excluded. Every canonical artifact had a `testsuite` and > 0 testcases.
- **The canonical-cell restriction is the bottleneck, not the repo.** 162/191 runs fail, but across 5 runs x 40
  cells only ~7 testcases failed in total, each in a different cell. Flakiness is diffuse across the matrix:
  any single cell sees roughly 1 failure per 5 runs, so 178 runs of one cell yield 6 tests that ever failed.
  Per-cell failure counts (anchor commit, 5 runs): mindeps-notci1 2, py310-noqueue-notci1 1, py311-notci1 1,
  arm-py312-notci1 1, py314-notci1 1, arm-py312-ci1 1, all 34 others 0.
- Q2(a)=6 passes; Q2(b)=0 fails - at one cell, no test recovered across >= 3 commits in 89 days.
