"""Orchestration. The steps are Strands tools (agents-as-tools: classifier, correlation and drafter are agents behind
tool functions; health and commit context are deterministic). `triage()` runs them in a fixed order from Python.

Every tool takes only a test_id. No tool accepts a sha, a file list or a verdict from a caller, so nothing that
reaches a model can be steered by another model. The sequence is code, not a prompt.
"""
import json
from dataclasses import dataclass
from pathlib import Path

from strands import tool

from .baseline import episode
from .classifier import Classification, classify, render_evidence
from .config import Config, load
from .correlation import Correlation, correlate
from .drafter import draft
from .github import GitHub
from .stats import TestHealth, Thresholds, test_health
from .storage import Storage


@dataclass
class Runtime:
    cfg: Config
    store: Storage | None
    gh: GitHub
    fixtures: dict[str, list[dict]]  # test_id -> observations, when triaging a fixture instead of storage

    def rows(self, test_id: str) -> list[dict]:
        if test_id in self.fixtures:
            return self.fixtures[test_id]
        return self.store.pooled_observations(test_id)


_rt: Runtime | None = None


def configure(cfg: Config | None = None, fixture_paths: list[str] = ()) -> Runtime:
    global _rt
    cfg = cfg or load()
    fixtures = {}
    for p in fixture_paths:
        fx = json.loads(Path(p).read_text(encoding="utf-8"))
        fixtures[fx["test_id"]] = fx["observations"]
    _rt = Runtime(cfg, None if fixtures else Storage(cfg.ingest.db_path), GitHub(cfg.target.repo, cfg.ingest.cache_dir), fixtures)
    return _rt


def rt() -> Runtime:
    return _rt or configure()


def health(test_id: str) -> TestHealth:
    return test_health(rt().rows(test_id), Thresholds(**rt().cfg.stats.model_dump()))


@tool
def get_test_health(test_id: str) -> str:
    """Deterministic statistics for one test: the exact evidence block the classifier reasons over."""
    return render_evidence(health(test_id), rt().cfg)


@tool
def get_commit_context(test_id: str) -> str:
    """Message and changed files of the commit under investigation for this test: the most recent commit with a failure."""
    return json.dumps(rt().gh.commit(episode(health(test_id)).head_sha), indent=1)


@tool
def classify_test(test_id: str) -> str:
    """Classifier agent: verdict, confidence, primary signal, conflicting signals, reasoning."""
    return classify(health(test_id), rt().cfg)[0].model_dump_json(indent=1)


@tool
def correlate_regression(test_id: str) -> str:
    """Correlation agent: does the failing commit plausibly explain the failure? The commit is derived from the data."""
    h = health(test_id)
    ctx = rt().gh.commit(episode(h).head_sha)
    return correlate(test_id, h, ctx, rt().cfg)[0].model_dump_json(indent=1)


@dataclass
class Triage:
    test_id: str
    health: TestHealth
    classification: Classification
    evidence: str
    correlation: Correlation | None
    commit_ctx: dict | None
    artifact: str
    invented_numbers: list[str]


def triage(test_id: str) -> Triage:
    """The fixed pipeline: health -> classify -> (regression only) commit context + correlate -> draft."""
    r = rt()
    h = health(test_id)
    cls, evidence = classify(h, r.cfg)
    corr, ctx = None, None
    if cls.verdict == "regression":
        ctx = r.gh.commit(episode(h).head_sha)
        corr, _ = correlate(test_id, h, ctx, r.cfg)
    artifact, invented = draft(test_id, h, cls, evidence, corr, ctx, r.cfg)
    return Triage(test_id, h, cls, evidence, corr, ctx, artifact, invented)
