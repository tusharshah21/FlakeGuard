"""Deterministic single-signal baseline: thresholds on the Wilson interval of the most recent failing commit.

This is what you would write instead of an agent. It exists to be measured against the classifier on the
conflict fixtures (see README "Why a model"). It knows nothing about cell dispersion, time, or inference share.
"""
from .config import Classify
from .stats import CommitStats, TestHealth


def episode(h: TestHealth) -> CommitStats:
    """The most recent commit with any failure - the thing a sweep is triaging. Falls back to the newest commit."""
    return next((c for c in reversed(h.commits) if c.fails), h.commits[-1])


def classify(h: TestHealth, cfg: Classify) -> str:
    c = episode(h)
    if c.ci_low >= cfg.regression_ci_low:
        return "regression"
    if c.ci_high <= cfg.flaky_ci_high:
        return "flaky"
    return "unclear"
