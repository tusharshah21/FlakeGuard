```
REPO: dask/distributed
  runs sampled ............ 400 (2026-08-20 -> 2026-09-12, 22 days)
  conclusions ............. {'success': 247, 'failure': 117, 'skipped': 25, 'cancelled': 11}
  failure rate ............ 38%
  distinct workflows ...... 10
  Q1 pass (>=20% non-success, >=14 days) .. True
  retry attempts present .. 0 runs
  retry recoveries ........ 0   <- must be >= 5
  VERDICT: unsuitable - no retry recovery signal
```

## Notes (2026-09-12, unauthenticated probe)

- `run_attempt` distribution in the last 300 runs: dask/distributed `{1: 300}`, aio-libs/aiohttp `{1: 300}`,
  apache/airflow `{1: 296, 2: 4}`. The field works (airflow proves it); dask and aiohttp simply never
  re-run workflows. Q2 as specified (workflow-level retry recovery) fails for candidates 1 and 2.
- dask/distributed retries happen *inside* pytest via `pytest-rerunfailures`, so retry data lives in the
  JUnit XML, not in run attempts. Q2 needs re-asking at test level once artifacts can be downloaded.
- Artifacts: run 34568247988 (Tests, failure) has 30 live artifacts named `{os}-{py}-test-ci-{ci1|notci1}`,
  ~18-33 KB each, expiring 2026-12-10 (90-day retention). Download requires GITHUB_TOKEN - not yet available.
