"""Classifier agent. The only place in the triage path where a model reasons.

Everything numeric is computed in stats.py and rendered by `render_evidence`; the model receives that text and
returns a Classification. Thresholds are interpolated from the same config that baseline.py reads, so the prompt
and the code cannot disagree.
"""
from typing import Literal

from pydantic import BaseModel, Field
from strands import Agent
from strands.models import BedrockModel

from .baseline import episode
from .config import Config
from .stats import Split, TestHealth

VERDICTS = ("flaky", "regression", "platform_specific", "environment_break", "chronic", "unclear")


class Classification(BaseModel):
    verdict: Literal["flaky", "regression", "platform_specific", "environment_break", "chronic", "unclear"]
    confidence: float = Field(ge=0, le=1)
    primary_signal: str = Field(description="The one statistic that drove the verdict, quoted with its value.")
    conflicting_signals: str = Field(description="Statistics that pointed toward a different verdict, or 'none'.")
    reasoning: str = Field(description="Two sentences maximum.")


def _split(s: Split | None, label: str) -> str:
    if s is None:
        return f"{label}: not computable (fewer than two groups)"
    return (f"{label}: failure rate {s.before_fails}/{s.before_n} before -> {s.after_fails}/{s.after_n} after "
            f"{s.at_sha[:10]} ({s.at_started_at[:10]}), shift {s.shift:+.3f}")


def render_evidence(h: TestHealth, cfg: Config) -> str:
    """Fixed-format evidence block. Every number the model may cite appears here verbatim."""
    e = episode(h)
    t, c = cfg.stats, cfg.classify
    lines = [
        f"TEST: {h.test_id}",
        f"WINDOW: {h.window_start[:10]} to {h.window_end[:10]}; runs {h.runs}; commits {len(h.commits)}",
        "",
        "TEST LEVEL (all commits pooled)",
        f"  n {h.n} = measured {h.n_measured} + inferred {h.n_inferred}; failures {h.fails}; p_hat {h.p_hat:.3f}; "
        f"wilson95 [{h.ci_low:.3f}, {h.ci_high:.3f}]",
        f"  cells_failed {h.cells_failed} of cells_present {h.cells_total}; top_cell_share {h.top_cell_share:.2f}; "
        f"top_os {h.top_os} share {h.top_os_share:.2f}; concentrated {h.concentrated}",
        f"  recovery_commits {h.recovery_commits}; spread_recovery_commits {h.spread_recovery_commits}; chronic {h.chronic}; "
        f"max_consecutive_failing_runs {h.max_consecutive_failing_runs}",
        f"  {_split(h.largest_shift, 'largest_shift_between_commits')}; onset_sha {h.onset_sha[:10] if h.onset_sha else None}",
        "",
        f"EPISODE (most recent commit with a failure): {e.head_sha[:10]}, {e.first_started_at[:10]} to {e.last_started_at[:10]}, runs {e.runs}",
        f"  n {e.n} = measured {e.n_measured} + inferred {e.n_inferred}; failures {e.fails}; p_hat {e.p_hat:.3f}; "
        f"wilson95 [{e.ci_low:.3f}, {e.ci_high:.3f}]",
        f"  cells_failed {e.cells_failed} of cells_present {e.cells_total}; top_cell_share {e.top_cell_share:.2f}; "
        f"top_os {e.top_os} share {e.top_os_share:.2f}; concentrated {e.concentrated}; recovery {e.recovery}",
        "  failing cells (failures/observations): " + (", ".join(f"{k} {v[0]}/{v[1]}" for k, v in e.per_cell.items() if v[0]) or "none"),
        f"  {_split(e.temporal, 'within_commit_over_time')}",
        "",
        "PER COMMIT (chronological): sha, first_run, runs, n, measures, failures, p_hat, wilson95, cells_failed/cells_present",
    ]
    for k in h.commits:
        lines.append(f"  {k.head_sha[:10]} {k.first_started_at[:10]} {k.runs} {k.n} {k.n_measured} {k.fails} {k.p_hat:.3f} "
                     f"[{k.ci_low:.3f}, {k.ci_high:.3f}] {k.cells_failed}/{k.cells_total}")
    lines += [
        "",
        "THRESHOLDS (from flakeguard.toml; identical to the deterministic baseline)",
        f"  regression: episode wilson95 lower bound >= {c.regression_ci_low}",
        f"  flaky: episode wilson95 upper bound <= {c.flaky_ci_high}",
        f"  concentrated: failures >= {t.platform_min_fails} and (top_cell_share >= {t.platform_top_cell_share} "
        f"or top_os_share >= {t.platform_top_os_share})",
        f"  chronic: spread_recovery_commits >= {t.chronic_min_commits}",
        f"  onset: shift between commits >= {t.min_onset_effect}",
    ]
    return "\n".join(lines)


SYSTEM_PROMPT = """You classify one test's CI history for FlakeGuard. You will be given a block of statistics that were
computed deterministically from real GitHub Actions results. Your job is judgement over those numbers, nothing else.

Rules
- Reason ONLY over the numbers provided. Do not compute new statistics, do not estimate, do not round differently,
  do not convert to percentages. When you cite a number, quote it exactly as it appears in the evidence.
- `unclear` is an expected and correct verdict. Choose it whenever the evidence does not separate the cases, and give
  it low confidence. Declining to decide is better than a confident wrong call.
- Weigh `measured` against `inferred`. Inferred observations are passes deduced from a succeeded job plus a sampled
  roster; they are sound but weaker than measured ones. A denominator that is mostly inferred lowers confidence.
- The denominator for cell coverage is `cells_present`, never a fixed matrix size. A test that runs in 9 cells and
  fails in 9 has failed everywhere.
- The thresholds listed at the end of the evidence are the definitions. Apply them as written.

Verdicts
- regression: at the episode commit the wilson95 lower bound meets the regression threshold and failures cover the
  present cells rather than one platform.
- platform_specific: failures are concentrated in one cell or one operating system (the `concentrated` flag, or the
  top_cell_share / top_os_share thresholds), whatever the pooled rate says. Concentration overrides the pooled interval.
- environment_break: at a fixed commit, failures begin after a period of none (within_commit_over_time shows zero
  failures before the boundary and a material rate after), across cells rather than one platform.
- chronic: a flaky pattern (low pooled rate, recoveries) whose spread recoveries reach the chronic threshold.
- flaky: the episode wilson95 upper bound meets the flaky threshold, failures are spread across cells, and the test
  recovers, but the chronic threshold is not reached.
- unclear: the interval spans the thresholds, n is too small, or the signals conflict without resolution.

Output
- primary_signal: the single statistic that decided it, with its value quoted.
- conflicting_signals: what pointed toward a different verdict. Write "none" only if nothing did.
- reasoning: two sentences maximum."""


def make_agent(cfg: Config) -> Agent:
    model = BedrockModel(model_id=cfg.bedrock.model_id, region_name=cfg.bedrock.region, temperature=0.0)
    return Agent(model=model, system_prompt=SYSTEM_PROMPT, callback_handler=None)


def classify(h: TestHealth, cfg: Config, agent: Agent | None = None) -> tuple[Classification, str]:
    """Returns the classification and the exact evidence text the model saw."""
    evidence = render_evidence(h, cfg)
    result = (agent or make_agent(cfg)).structured_output(Classification, prompt=evidence)
    return result, evidence
