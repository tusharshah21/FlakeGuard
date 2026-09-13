# FlakeGuard

**Autonomous flaky-test triage for GitHub Actions and pytest, built on the [Strands Agents SDK](https://strandsagents.com/).**

Once a test suite is unreliable, people stop trusting every failure, including the real ones. FlakeGuard reads a
repository's CI history, works out for each failing test whether it is flaky, a real regression, confined to one
platform, or not yet decidable — and acts only when the evidence is strong enough. It opens an issue naming the
likely commit, a pull request quarantining a flake, and, when the test recovers, a pull request reversing that
quarantine. When the evidence is weak it does nothing and says why.

**The determinism boundary.** The model reasons; it never carries a number. Every statistic is computed in Python
and pinned into the prompt as ground truth. Scheduling, idempotency, rate limiting and the decision to write are
code. Most of this document is the evidence for that claim.

The landing page in [`site/`](site/) explains the idea in one screen.

Demonstrated against [`dask/distributed`](https://github.com/dask/distributed) — real, active, public, 89 days of
messy CI history. FlakeGuard never writes to it; artifacts go to this repository's `scratch` branch instead.

## Why now

On 2026-08-04, dask/distributed PR #9340 — "[unsupervised AI] fix: propagate task annotations during worker
execution" — changed `distributed/worker.py`. Three pre-existing tests in unrelated modules (`test_get_client`,
`test_secede_balances`, `test_serialize_with_pickle`) then failed in **17 of 17 cells each**, across four operating
systems and five Python versions. The next commit changed `worker.py` again and all three passed. None of the test
files were touched. (Runs [30925383561](https://github.com/dask/distributed/actions/runs/30925383561) and
[30970740435](https://github.com/dask/distributed/actions/runs/30970740435).)

Machine-generated changes are arriving faster than review capacity. Triage that is automatic, evidence-based and
reversible is how a CI signal survives that.

## The finding: a test matrix is a failure multiplier

**An individual matrix-cell run passes 94.4% of the time** (6,119 of 6,479 cell-runs; per-cell range 77.9%–99.5%).
**Yet 162 of 191 scheduled runs go red.** Both are true at once: 34 cells each flip their own coin, and the run
fails when any one lands wrong. If the cells were independent, 0.944³⁴ predicts 86% of runs red — close to the 85%
observed.

No single cell's history shows this. Restricted to one cell, 89 days of data surfaces six tests that ever failed.
Pooled across all 34, the same window shows nineteen tests failing and recovering repeatedly.

Pooling has to be careful. Cells are not exchangeable, so a test failing on every Windows run would read as a tidy
9% flake if pooled blindly. FlakeGuard keeps per-cell counts and runs a dispersion check first; concentrated
failures get their own verdict, `platform_specific`.

Two related results: **zero tests failed at every run of a commit** in 95 days — dask's problem is not broken
tests. And every 17/17 failure across 113 failed PR runs was a regression, while flakes failed in 1–3 cells, which
makes `cells_failed / cells_present` a strong prior before any probability is computed.

## Architecture

![FlakeGuard architecture](docs/architecture.svg)

_Source: [`docs/architecture.md`](docs/architecture.md). Blue is deterministic Python, orange is an LLM call, red is
the gate._

Every orange box sits inside a blue path: a model never touches the API, the database, or the decision to write.
The first gate disposes of cases before any model is called; the second decides whether a verdict becomes an
artifact.

[`flakeguard/stats.py`](flakeguard/stats.py) imports nothing from `strands` (a test parses its AST to enforce it)
and computes per test and per commit: `n` split into `n_measured` and `n_inferred`, `p_hat`, the 95% Wilson score
interval, `cells_failed / cells_present`, per-cell counts, top-cell and top-OS failure share, recovery commits,
onset, and the largest within-commit shift over time. Thresholds live in `[stats]` in
[`flakeguard.toml`](flakeguard.toml), so the code and the prompt cannot disagree.

Six verdicts: **regression**, **flaky**, **chronic**, **platform_specific**, **environment_break**, and
**unclear** — which is a correct answer, not a failure.

The correlation agent sees only the *failing* commit's metadata and file list, never the fix commit's.
[`tests/test_leakage.py`](tests/test_leakage.py) was committed before the agent existed and asserts it.

### The data contract

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

## Two surfaces

`flakeguard sweep` runs a fixed sequence from Python — health, gate, classify, correlate, draft, act — because that
path can modify a repository. Control flow that decides whether an artifact gets written does not belong in a
prompt; [the fragility experiment](docs/evaluation.md#llm-classification-is-not-locally-editable---a-controlled-experiment) is why.

`flakeguard explain <test_id> "<question>"` is the opposite. An agent gets the same four deterministic tools and
sequences them itself. It is read-only **by construction** — the action layer is not in its toolset and
[`flakeguard/explain.py`](flakeguard/explain.py) does not import it, which
[`tests/test_explain.py`](tests/test_explain.py) asserts.

Deterministic where correctness matters, agentic where exploration matters.

**The gate** ([`flakeguard/gate.py`](flakeguard/gate.py)) is plain Python: an overridden test is never acted on;
one decision per test per day; below `min_runs` goes to review; below `action_threshold` goes to review; a test
already quarantined and still flaky is left alone. Cheap checks run before the classifier, so a blocked case costs
no model call. Every artifact ends with how to overrule it, and closing a FlakeGuard issue or PR is respected —
recorded as a human decision, never recreated.

Quarantine uses `xfail(strict=False)`, not `skip`, so the test keeps running and reporting and the un-quarantine
loop can see it recover. The rationale is a comment in [`flakeguard/actions.py`](flakeguard/actions.py).

## Results

Measured against a deterministic threshold rule on cases built from real history, ten runs at temperature 0.
The full method, the per-fixture table and the caveats are in [`docs/evaluation.md`](docs/evaluation.md).

| | baseline | classifier |
|---|---|---|
| primary set (regression, flake, ambiguous) | 4/4 | 4/4 |
| conflict set (cases where one signal misleads) | **1/4** | **2/4** |
| verdict flips across 10 runs | — | 0 |
| invented numbers across 80 outputs | — | **0** |

The conflict set is four cases, three of them the same failure mode, so that 2/4 shows concentration reasoning
rather than multi-signal reasoning in general. Two results from it are worth knowing even if you never run this:

- **LLM classification is not locally editable.** One sentence added to one verdict definition fixed its target
  case 0/10 → 10/10, moved an *unrelated* verdict across the action threshold in 4/10 runs, and introduced 9
  fabricated numbers where there had been 0. We reverted it and kept the worse score — and it is why the gate is
  Python rather than a prompt.
- **The inferred denominator holds up.** Most of a test's `n` is a pass inferred from a succeeded job rather than
  read from a file. Checked against measured data: 1,380 of 1,401 (test, cell) pairs agree, and all 21 exceptions
  come from a single truncated artifact.

### What an unattended run costs

Two manual dispatches, both dry run, both creating nothing
([#1](https://github.com/tusharshah21/FlakeGuard/actions/runs/34748961534),
[#3](https://github.com/tusharshah21/FlakeGuard/actions/runs/34755101992)):

| | cold (empty cache) | warm |
|---|---|---|
| ingest | 911 s, 816 API requests | **19 s, 3 requests** |
| sweep | 180 s, 30 model calls (hit the ceiling) | 42 s, **6 model calls** |
| job total | 18 m 24 s | **1 m 17 s** |

A third dispatch is deliberately red: with the ceiling set to 1,
[run #2](https://github.com/tusharshah21/FlakeGuard/actions/runs/34754918660) aborted and failed with exit code 1.
It exists because an earlier version piped the sweep through `tee`, so an aborted sweep reported success.

## The artifacts it produced

The Issues and Pull Requests tabs of this repository hold **agent-generated replay artifacts**: FlakeGuard ran
against historical `dask/distributed` data and wrote here, because we do not own that repository. They are labelled
`flakeguard-replay`, titled `[REPLAY ...]`, and each opens with a disclaimer. Every PR targets `scratch`, never
`main` — asserted in code, not configured, and startup refuses live mode otherwise. **No action of any kind was
taken against `dask/distributed`.**

The live run produced an issue, a quarantine PR, a review-queue entry, and — after the test
passed 35 consecutive runs — [PR #7](https://github.com/tusharshah21/FlakeGuard/pull/7), one file and one line
removed, reversing its own quarantine. A human merged the quarantine that preceded it. FlakeGuard never merges.

`.github/workflows/sweep.yml` runs on manual dispatch. Its cron is **deliberately commented out**, not unfinished:
the workflow is proven to run, and a job firing twice daily through the judging window adds risk with no gain.

**Writing is opt-in.** `dry_run = true` is the committed default, `--dry-run` overrides config in the safe
direction only, and every run announces its mode on the first line. During development `dry_run` was left `false`
after a live run and a later local test opened a real issue
([#8](https://github.com/tusharshah21/FlakeGuard/issues/8), since closed). The safe default exists because of that.

## Limitations

- **Test-level history is 89 days deep.** GitHub retains artifacts for 90 days; anything older is job-level only.
- **Correlation looks at the latest failing commit, not the onset commit.** On a branch mid-fix the most recent
  failing commit may be unrelated, and correlation correctly reports "no plausible cause" while the real cause sits
  three commits back.
- **Truncated artifacts are not detected.** When pytest dies mid-session the artifact holds a fraction of its
  testcases. It fails safe — absent tests produce no observation, never a false pass — but nothing flags it.
- **Inferred denominators inherit the roster assumption.** Most of a test's `n` is inferred from a succeeded job
  plus a sampled roster. Validated at 98.5%, but it is an inference; `n_measured` and `n_inferred` are carried
  separately into every piece of evidence.
- **Ground truth is hard, and one of our own labels is in doubt.** See the PR-branch fixture in [the evaluation](docs/evaluation.md).
- **`explain` converts to percentages.** Two of five explanations wrote a derived percentage where the rule is to
  quote numbers as given. Correct arithmetic, but it is the one place a model still computes.
- **The conflict set is small and narrow** — four cases, three of them the same failure mode.
- GitHub Actions and pytest JUnit XML only. One workflow per repository.

## Prior art

dask/distributed ships its own hand-rolled flaky-test report (`continuous_integration/scripts/test_report.py`).
FlakeGuard does not read or adapt it. The difference is in kind: their script produces a static report a human must
go read; FlakeGuard triages, decides, and acts — and reverses itself when a test recovers. That the maintainers
built a report at all is evidence they want this solved.

## Setup

Verified from a clean clone.

```sh
git clone https://github.com/tusharshah21/FlakeGuard && cd FlakeGuard
uv sync                              # Python 3.11+; strands-agents, PyGithub, pydantic
cp .env.example .env                 # GITHUB_TOKEN (public_repo) + Bedrock credentials
uv run pytest                        # 48 tests, no credentials and no network
```

`pytest` runs against committed fixtures, and so does reading one:

```sh
uv run python -m flakeguard health fixtures/regression_test_get_client.json
```

Everything below needs credentials:

```sh
uv run scripts/check_bedrock.py      # one Bedrock call must succeed
uv run python -m flakeguard ingest   # ~90 days of CI -> flakeguard.db
                                     # first run ~15 min / ~800 requests; cached after (~20 s / 3)
uv run scripts/reconcile.py          # storage must reproduce the probe's numbers exactly
uv run python -m flakeguard sweep --recent --dry-run
uv run python -m flakeguard explain "distributed.tests.test_gc::test_gc_diagnosis_cpu_time" \
    "Why does this fail only on Windows?"
```

To let FlakeGuard write, set `dry_run = false` and point `scratch_repo` / `scratch_branch` at a repository and a
non-`main` branch you own. Startup refuses anything else.

## License

MIT — see [LICENSE](LICENSE).
