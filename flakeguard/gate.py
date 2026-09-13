"""The action gate. Plain Python, not a tool, not model-controlled.

The model decides what a test IS. This function decides whether the repository gets touched. The two are kept apart
on purpose: a verdict is an opinion over statistics; an action is a mutation of someone else's repository.
"""
from dataclasses import dataclass

from .classifier import Classification
from .config import Config
from .stats import TestHealth

# What each verdict would do if the gate lets it through.
ACTION_FOR = {
    "regression": "issue",
    "platform_specific": "issue",
    "environment_break": "issue",
    "flaky": "quarantine_pr",
    "chronic": "quarantine_pr",
    "unclear": "review",
}


@dataclass
class Decision:
    action: str      # issue | quarantine_pr | review | none
    reason: str      # one sentence a maintainer can read in the artifact


def decide(h: TestHealth, cls: Classification | None, cfg: Config, *, last_decision_on: str | None,
           quarantined: bool, overridden: bool, today: str) -> Decision:
    t = cfg.triage
    if overridden:
        return Decision("none", "This test is on FlakeGuard's override list; no action is ever taken on it.")
    if last_decision_on == today:
        return Decision("none", f"Already triaged today ({today}); one decision per test per day.")
    if h.runs < t.min_runs:
        return Decision("review", f"Only {h.runs} runs in the window, below min_runs = {t.min_runs}; routed to review, nothing touched.")
    if cls is None:
        return Decision("review", "No classification available; routed to review.")
    if cls.confidence < t.action_threshold:
        return Decision("review", f"Classifier confidence {cls.confidence:.2f} is below action_threshold = {t.action_threshold}; routed to review, nothing touched.")
    action = ACTION_FOR[cls.verdict]
    if action == "review":
        return Decision("review", "Verdict is unclear; routed to review, nothing touched.")
    if quarantined and action == "quarantine_pr":
        return Decision("none", "Already quarantined and still flaky; nothing further to do until it recovers.")
    return Decision(action, f"Verdict {cls.verdict} at confidence {cls.confidence:.2f} clears action_threshold = {t.action_threshold} "
                            f"with {h.runs} runs in the window; FlakeGuard will {action.replace('_', ' ')}.")


def clean_runs_since(rows: list[dict], since: str) -> int:
    """Consecutive most-recent runs after `since` in which the test did not fail in any cell. A failure resets the streak."""
    failed, started = {}, {}
    for r in rows:
        if r["started_at"] <= since:
            continue
        failed[r["run_id"]] = failed.get(r["run_id"], False) or r["outcome"] == "fail"
        started[r["run_id"]] = r["started_at"]
    streak = 0
    for rid in sorted(failed, key=started.get, reverse=True):
        if failed[rid]:
            break
        streak += 1
    return streak


def unquarantine_due(rows: list[dict], quarantined_at: str, cfg: Config) -> tuple[bool, int]:
    """(due, clean_runs) for a quarantined test: due when the clean streak since quarantine reaches the threshold."""
    n = clean_runs_since(rows, quarantined_at)
    return n >= cfg.triage.unquarantine_after_passes, n
