"""The gate is plain Python. These tests pin its behaviour on the real fixtures and on synthetic classifications."""
import json
from pathlib import Path

from flakeguard.classifier import Classification
from flakeguard.config import load
from flakeguard.gate import clean_runs_since, decide, unquarantine_due
from flakeguard.stats import Thresholds
from flakeguard.stats import test_health as health_of

ROOT = Path(__file__).parent.parent
cfg = load(ROOT / "flakeguard.toml")
T = Thresholds(**cfg.stats.model_dump())
TODAY = "2026-09-13"


def health(name):
    return health_of(json.loads((ROOT / "fixtures" / f"{name}.json").read_text(encoding="utf-8"))["observations"], T)


def cls(verdict, confidence):
    return Classification(verdict=verdict, confidence=confidence, primary_signal="x", conflicting_signals="none", reasoning="x")


def gate(h, c, **kw):
    defaults = dict(last_decision_on=None, quarantined=False, overridden=False, today=TODAY)
    return decide(h, c, cfg, **{**defaults, **kw})


def test_ambiguous_fixture_routes_to_review_and_touches_nothing():
    # exactly what the classifier produced on it, ten times out of ten
    d = gate(health("ambiguous_test_handle_null_partitions_2"), cls("unclear", 0.40))
    assert d.action == "review"
    # and even a confident verdict on it would be blocked: 12 runs < min_runs
    d = gate(health("ambiguous_test_handle_null_partitions_2"), cls("flaky", 0.95))
    assert d.action == "review" and "min_runs" in d.reason


def test_confidence_below_threshold_is_review_whatever_the_verdict():
    h = health("flake_test_shutdowns_cleanly")
    for v in ("flaky", "regression", "platform_specific", "chronic"):
        assert gate(h, cls(v, 0.74)).action == "review"
    assert gate(h, cls("chronic", 0.75)).action == "quarantine_pr"


def test_hard_idempotency_one_decision_per_day():
    h = health("regression_test_get_client")
    assert gate(h, cls("regression", 0.95), last_decision_on=TODAY).action == "none"
    assert gate(h, cls("regression", 0.95), last_decision_on="2026-09-12").action == "review"  # 2 runs < min_runs


def test_regression_with_enough_runs_opens_an_issue_and_flaky_quarantines():
    h = health("flake_test_shutdowns_cleanly")  # 191 runs
    assert gate(h, cls("regression", 0.95)).action == "issue"
    assert gate(h, cls("chronic", 0.85)).action == "quarantine_pr"
    assert gate(h, cls("platform_specific", 0.92)).action == "issue"


def test_already_quarantined_and_still_flaky_does_nothing():
    h = health("flake_test_shutdowns_cleanly")
    assert gate(h, cls("chronic", 0.85), quarantined=True).action == "none"
    assert gate(h, cls("regression", 0.95), quarantined=True).action == "issue"  # a regression still gets reported


def test_override_wins_over_everything():
    assert gate(health("flake_test_shutdowns_cleanly"), cls("regression", 0.99), overridden=True).action == "none"


def test_clean_streak_since_quarantine():
    rows = [{"run_id": i, "started_at": f"2026-09-{i:02d}T06:00:00Z", "outcome": o}
            for i, o in enumerate(["pass", "fail", "pass", "pass", "pass"], start=1)]
    assert clean_runs_since(rows, "2026-09-00") == 3      # runs 3,4,5 after the failure on run 2
    assert clean_runs_since(rows, "2026-09-02T06:00:00Z") == 3
    assert clean_runs_since(rows, "2026-09-05T06:00:00Z") == 0
    due, n = unquarantine_due(rows, "2026-09-00", cfg)
    assert (due, n) == (False, 3)
