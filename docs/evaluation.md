# Evaluation

How well FlakeGuard's classifier works, and how we know. Raw outputs are in
[`probe-results/`](../probe-results/); this document is the reading of them.

Everything below is measured against fixtures built from real `dask/distributed` history, ten runs at temperature 0,
Claude Sonnet 4.5 on Bedrock.

## The benchmark

A deterministic threshold rule on the Wilson interval ([`flakeguard/baseline.py`](../flakeguard/baseline.py)) is the
control. It classifies the three primary fixtures correctly, and so does the model, so the interesting question is
what happens where a single signal misleads.

The conflict set is four real cases. **Three are the same failure mode** — failures concentrated in one cell or one
OS — and one is a `cells_present` trap, where a test runs in 9 of 17 cells and fails in all 9. A good score here
demonstrates concentration reasoning specifically, not multi-signal reasoning in general.

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
across the ten runs, and zero invented numbers in 80 outputs — every numeric token in the model's prose is checked
against the evidence block it was given ([`scripts/eval_classifier.py`](../scripts/eval_classifier.py)).

## The classifier's most instructive failure
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

### A later reading suggests our own label may be the error
We labelled this fixture `platform_specific` on the strength of the episode: at the most recent failing commit, all
five failures are on `windows-latest`. The classifier said `regression`, and we recorded it as a miss. That score
stands at 2 of 4, unrevised.

But the `explain` surface, reading the same data and asked what the conflicting evidence was, narrated a mechanism
we had not: four consecutive commits failing 17 of 17 cells, then a collapse at `3865fc878b` where the failure rate
drops from 82/85 to 10/63 (shift -0.806), with the episode sitting in the recovery tail where only Windows had yet
to catch up. On that reading the branch had a genuine cross-platform regression that was being fixed, and the
Windows-only residue is its last stage rather than a platform quirk - which is to say the classifier's `regression`
may have been right and our label wrong.

We are not revising the score after the fact; a fixture relabelled once the answer is known is worth nothing. The
honest report is that **ground truth here is genuinely hard**. A verdict on a branch mid-fix depends on where you
stand in time, our label was drawn from one commit, and the evidence supports more than one defensible reading.
That is a more useful result than either a clean win or a clean miss: it is why the action gate blocks this case at
0.40 whoever turns out to be right, and why `explain` earns its place as a second look rather than a second opinion.

## LLM classification is not locally editable - a controlled experiment
This is the strongest empirical result in the project, so it gets its own section. We tried to improve the score,
succeeded on the target, broke two unrelated cases, and reverted to the worse number.

**Hypothesis.** A one-sentence clarification to one category's definition is a local edit: it changes the verdict
on the case that definition was misread on, and nothing else.

**Method.** The trap case (a pre-existing test that fails 9/9 in the 9 cells where it exists) was being called
`environment_break` because the evidence shows a 0/9 to 9/9 jump between commits and the definition said only
"failures begin after a period of none". We appended one sentence to that definition and nothing else:

```diff
   failures before the boundary and a material rate after), across cells rather than one platform.
+  The boundary must fall WITHIN one commit's runs; a jump from 0/n to n/n BETWEEN commits
+  (largest_shift_between_commits) is a regression signature, not an environment break.
```

Then we re-ran the **entire** fixture set, not just the trap: 8 fixtures x 10 runs, temperature 0, same model,
same evidence blocks, same invented-number check (every numeric token in the model's prose must appear verbatim in
the evidence it was given). Raw outputs: `probe-results/eval-phase3-sonnet45-10runs.txt` (before) and
`probe-results/eval-phase3-sonnet45-10runs-postfix.txt` (after).

**Result.**

| case | before (10 runs) | after (10 runs) |
|---|---|---|
| trap: 9/9 of 9 present cells | environment_break x10 @ 0.95 | **regression x10 @ 0.95** - target fixed |
| ambiguous: 1 failure in 45 obs, 44 inferred | unclear x10 @ 0.40 | unclear x6, **flaky x4 @ 0.75** - exactly on the action threshold |
| PR-branch platform case | regression x10, 0 invented numbers | regression x10, **invented numbers in 7 of 10 outputs** |
| the other five | unchanged | unchanged |
| conflict-set score | 2/4 | 3/4 |
| invented numbers across 80 outputs | **0** | **9** (`100` as a percentage of a 1.00 share, 7x; `0.159` and `0.965`, in no evidence block) |

The trap reasoning went from

> "At commit acf771d460, failures began across all 9 present cells after a period of zero failures (0/9 -> 9/9),
> with shift +1.000 exceeding the onset threshold of 0.2. The failures are not concentrated (top_cell_share 0.11,
> top_os_share 0.44), indicating an environment break rather than platform-specific issue."

to

> "The episode wilson95 lower bound of 0.701 exceeds the regression threshold of 0.5, and failures cover all 9
> present cells (cells_failed 9 of cells_present 9) with concentrated False, meeting the regression criteria. The
> shift from 0/9 to 9/9 between commits is a regression signature, not an environment break which requires failure
> onset within a single commit's runs."

which is exactly what we wanted. Meanwhile the ambiguous case, untouched by the edit, produced in 4 of 10 runs:

> "The episode wilson95 upper bound of 0.189 exceeds the flaky threshold of 0.1, but with only 1 measured failure
> out of 26 total observations (25 inferred), the evidence is weak. The test shows recovery and failures are not
> concentrated, consistent with flaky behavior, though chronic threshold is not met."

- verdict `flaky`, confidence 0.75, from a sentence that states the flaky threshold is not met.

**Conclusion.** LLM classification is not locally editable. One sentence in one definition moved an unrelated
verdict onto the action threshold with self-contradictory reasoning and broke number discipline in a third case.
We reverted and kept 2/4 with zero fabrication over 3/4 with nine fabricated numbers. This is the measured argument
for the action gate living in Python and not in the prompt, and it is why the classifier prompt is now frozen: any
change requires this full protocol - every fixture, ten runs, invented-number counts - before it can land.

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

## The environment-break category has no instance in this data
dask's CI environment was stable for the whole window. An environment break - a fixed commit whose failures
start on a date because a runner image, a transitive dependency or an upstream service moved - leaves a signature:
zero failures before a boundary, a material rate after, across cells. We searched both long-lived commits
(`40fcd99a8c`, 78 runs over 39 days; `dc182bda54`, 34 runs over 17 days). Failures run flat at ~3.5 per day, no
day spikes, and no test's failures begin on a date. The statistic (`within_commit_over_time`) and the category
(`environment_break`) are implemented; the data contains no instance; we did not fabricate one.

## The explain surface

The same invented-number check applies to `flakeguard explain`
([`scripts/eval_explain.py`](../scripts/eval_explain.py), output in
[`probe-results/eval-explain.txt`](../probe-results/eval-explain.txt)). Over five explanations, **2 of the numbers
written were not traceable, and both were percentage conversions** - "passes roughly 98% of the time" from 8
failures in 407 observations, and "failed consistently at 100%" from a p_hat of 1.000.

Neither is false, and both are the kind of rounding a maintainer does out loud. The check flags them because the
rule is that numbers are quoted, not computed. It is also a fair reminder that the prose surface is looser than the
artifact surface, which is why only one of the two can act.
