"""Correlation sub-agent: does the FAILING commit plausibly explain the failure? Invoked only on verdict == regression.

The commit is the episode (most recent commit with a failure), derived from the data by baseline.episode(). The
agent is shown that commit's message and file list and nothing after it. tests/test_leakage.py enforces this.
"""
from pydantic import BaseModel, Field
from strands import Agent

from .baseline import episode
from .classifier import MODEL_CALLS, make_agent
from .config import Config
from .stats import TestHealth


class Correlation(BaseModel):
    plausible: bool = Field(description="Whether the changed files plausibly explain the test failing.")
    likely_file: str | None = Field(description="The single changed file most likely responsible, exactly as listed, or null.")
    rationale: str = Field(description="Two sentences maximum. Reason forward from the change to the test; do not speculate beyond the listed files.")


def test_module_path(test_id: str) -> str:
    """'distributed.tests.test_worker::test_get_client' -> 'distributed/tests/test_worker.py'."""
    return test_id.split("::")[0].replace(".", "/") + ".py"


def build_prompt(test_id: str, health: TestHealth, ctx: dict, cfg: Config) -> str:
    e = episode(health)
    assert ctx["sha"] == e.head_sha, "correlation context must be the episode commit"
    files = "\n".join(f"  {f['status']:9s} +{f['additions']}/-{f['deletions']}  {f['filename']}" for f in ctx["files"]) or "  (none)"
    return "\n".join([
        f"TEST: {test_id}",
        f"TEST FILE: {test_module_path(test_id)}",
        f"AT COMMIT {ctx['sha'][:10]} ({ctx['date'][:10]}) this test failed in {e.cells_failed} of {e.cells_total} cells it runs in "
        f"({e.fails} failures in {e.n} observations, wilson95 [{e.ci_low:.3f}, {e.ci_high:.3f}]).",
        "",
        "COMMIT MESSAGE:",
        "  " + ctx["message"].strip().splitlines()[0],
        "",
        "FILES CHANGED IN THIS COMMIT:",
        files,
        "",
        "Question: reasoning forward from this change alone, does it plausibly explain the failure? Which single listed file is "
        "the most likely cause? If the test file itself is among the changes, say so. Quote numbers only as given above.",
    ])


SYSTEM_PROMPT = """You assess whether a code change plausibly explains a test failure for FlakeGuard.
You see one commit - its message and the files it changed - and one test that started failing at that commit.
Reason forward: from what changed to what the test exercises. You know nothing about later commits.
Do not invent files, functions or numbers. Name at most one file, exactly as listed. If the change cannot plausibly
reach the test, say plausible = false. Two sentences of rationale, maximum."""


def make_correlation_agent(cfg: Config) -> Agent:
    a = make_agent(cfg)
    a.system_prompt = SYSTEM_PROMPT
    return a


def correlate(test_id: str, health: TestHealth, ctx: dict, cfg: Config, agent: Agent | None = None) -> tuple[Correlation, str]:
    prompt = build_prompt(test_id, health, ctx, cfg)
    MODEL_CALLS["correlate"] += 1
    return (agent or make_correlation_agent(cfg)).structured_output(Correlation, prompt=prompt), prompt
