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

## STEP 1 result (2026-09-12, authenticated, `public_repo` token)

Artifact `pytest.xml` structure (run 34568247988, all 30 cells inspected):

```xml
<testsuites name="pytest tests">
  <testsuite name="pytest" errors="0" failures="1" skipped="130" tests="2719" time="1420.653" timestamp="..." hostname="...">
    <testcase classname="distributed.cli.tests.test_tls_cli" name="test_use_config_file" time="1.192">
      <failure message="distributed.comm.core.CommClosedError: ...">traceback</failure>
    </testcase>
    <testcase classname="" name="distributed.diagnostics.tests.test_cudf_diagnostics" time="0.000">
      <skipped message="collection skipped">...</skipped>
    </testcase>
    <testcase classname="distributed.tests.test_x" name="test_y" time="0.05"/>   <!-- pass -->
```

- Child tags seen across 30 artifacts: `failure`, `skipped` only. **Zero `rerun`/`flaky` elements, zero
  duplicate `(classname, name)` entries.** Collection-skips have empty `classname`.
- Cause: `pytest-rerunfailures` is installed but `test-ci` passes no `--reruns`. Only ~10 test files use
  `@pytest.mark.flaky`. In-process reruns are rare and did not fire in this run. The premise that dask
  reruns in-process at scale is wrong.
- **The real same-commit signal is the cron.** `tests.yaml` reruns the full suite at 06:00 and 18:00 UTC
  on `main` ("Rerun CI in order to detect flaky tests"). In 400 runs: 76 `Tests` runs, 46 of them
  `schedule`. Commit `dc182bda54` ran **35 times**: 5 success / 30 failure. Identical code, 35 samples.
- dask maintains `continuous_integration/scripts/test_report.py` - their own flaky-test report. Prior art
  and pitch validation in one.

## Adjustments 1 & 2 (2026-09-12) - pre-bulk-download check

Schedule-triggered `Tests` runs on `main`, last 95 days: **191 runs, 16 commits** (162 failure / 28 success / 1 cancelled).

Runs per commit (desc): `78, 34, 24, 12, 9, 6, 6, 5, 4, 4, 3, 2, 1, 1, 1, 1`
- >=2 runs: 12 commits   >=3: 11   >=5: 8   >=10: 4

Not a spike plus singletons: four commits with n>=10 (78, 34, 24, 12) and eight with n>=5. Enough for Q2(b).

Artifact horizon: oldest run with live artifacts is `27507912696` (2026-06-14T18:22Z) -> **test-level window = 89 days**,
180 schedule Tests runs with live artifacts. Canonical cell `ubuntu-latest-py312-test-ci-notci1` is present in that
oldest run and in the newest (`34677067059`). Runs carry 41 artifacts, not 30: the extra are `*_cluster_dumps` and
`ubuntu-latest-mindeps-*` cells.
