"""Action drafter. Fixed artifact shape; the numbers come from stats.py verbatim, the prose from the classifier and
correlation outputs verbatim, and a small sub-agent writes only the summary and recommended-action paragraphs.

## Verdict / ## Evidence / ## Reasoning / ## Conflicting signals / [## Correlation] / ## Recommended action / ## How to override
"""
import re

from pydantic import BaseModel, Field
from strands import Agent

from .classifier import Classification, make_agent
from .config import Config
from .correlation import Correlation
from .stats import TestHealth

# What FlakeGuard proposes per verdict. Whether it actually happens is decided by the Phase 5 action gate, in code.
PROPOSED = {
    "regression": "Open an issue naming the failing commit and the likely file. Do not quarantine: the test is doing its job.",
    "flaky": "Open a quarantine PR that marks the test with pytest.mark.flaky and links this evidence. Un-quarantine automatically after sustained passes.",
    "chronic": "Open a quarantine PR that marks the test with pytest.mark.flaky and links this evidence, and open an issue for the underlying cause. Un-quarantine automatically after sustained passes.",
    "platform_specific": "Open an issue scoped to the affected cell(s) or OS. Do not quarantine globally: the test passes everywhere else.",
    "environment_break": "Open an issue pointing at the date the failures began at a fixed commit; the cause is outside the repository.",
    "unclear": "No repository change. Route to the review queue and wait for more runs.",
}

OVERRIDE = """FlakeGuard acted on statistics, not on knowledge of this code. If this is wrong:
- add the test id to `[overrides] ignore_tests` in `flakeguard.toml` to stop all future actions on it, or
- apply the label `flakeguard-override` to this issue or PR; the next sweep records the override and stops acting on this test.
Closing this issue or PR without either has no effect - the next sweep will recreate it once, then stop and record the disagreement."""


class Draft(BaseModel):
    summary: str = Field(description="One paragraph for a maintainer skimming the issue: what happened and what FlakeGuard concluded. No numbers unless quoted from the input.")
    recommended_action: str = Field(description="One paragraph refining the proposed action for this specific case. No numbers unless quoted from the input.")


SYSTEM_PROMPT = """You write the human-facing paragraphs of a CI triage artifact for FlakeGuard.
You are given a verdict, the classifier's reasoning and conflicting signals, an optional correlation result and a
proposed action. Write for a maintainer who has thirty seconds. Do not introduce any number, file name or claim that
is not in the input. If the conflicting signals are not "none", the summary must mention them. Plain prose, no
headings, no bullet points."""


def make_drafter_agent(cfg: Config) -> Agent:
    a = make_agent(cfg)
    a.system_prompt = SYSTEM_PROMPT
    return a


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text))


def draft(test_id: str, health: TestHealth, cls: Classification, evidence: str, correlation: Correlation | None,
          commit_ctx: dict | None, cfg: Config, agent: Agent | None = None) -> tuple[str, list[str]]:
    """Returns (markdown artifact, invented_numbers). invented_numbers is empty when the drafter's prose introduced none."""
    proposed = PROPOSED[cls.verdict]
    drafter_input = "\n".join([
        f"TEST: {test_id}",
        f"VERDICT: {cls.verdict} (confidence {cls.confidence:.2f})",
        f"PRIMARY SIGNAL: {cls.primary_signal}",
        f"CONFLICTING SIGNALS: {cls.conflicting_signals}",
        f"REASONING: {cls.reasoning}",
        f"CORRELATION: {'not run (verdict is not regression)' if correlation is None else f'plausible={correlation.plausible}; likely_file={correlation.likely_file}; {correlation.rationale}'}",
        f"PROPOSED ACTION: {proposed}",
    ])
    d = (agent or make_drafter_agent(cfg)).structured_output(Draft, prompt=drafter_input)
    allowed = _numbers(evidence) | _numbers(drafter_input)
    invented = sorted(_numbers(d.summary + " " + d.recommended_action) - allowed)

    parts = [
        f"# FlakeGuard: `{test_id}`",
        "",
        d.summary,
        "",
        "## Verdict",
        f"**{cls.verdict}** - confidence {cls.confidence:.2f}",
        f"Primary signal: {cls.primary_signal}",
        "",
        "## Evidence",
        "Computed deterministically by `flakeguard/stats.py`; the classifier saw exactly this block.",
        "```",
        evidence,
        "```",
        "",
        "## Reasoning",
        cls.reasoning,
        "",
        "## Conflicting signals",
        cls.conflicting_signals,
    ]
    if correlation is not None and commit_ctx is not None:
        files = "\n".join(f"- `{f['filename']}` ({f['status']}, +{f['additions']}/-{f['deletions']})" for f in commit_ctx["files"])
        parts += [
            "",
            "## Correlation",
            f"Failing commit `{commit_ctx['sha'][:10]}` ({commit_ctx['date'][:10]}): {commit_ctx['message'].strip().splitlines()[0]}",
            files,
            "",
            f"Plausible cause: **{'yes' if correlation.plausible else 'no'}**" + (f" - `{correlation.likely_file}`" if correlation.likely_file else ""),
            correlation.rationale,
            "",
            "_Reasoned forward from this commit only; FlakeGuard was not shown any later commit._",
        ]
    parts += [
        "",
        "## Recommended action",
        proposed,
        "",
        d.recommended_action,
        "",
        "## How to override",
        OVERRIDE,
    ]
    return "\n".join(parts), invented
