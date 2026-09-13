"""Sweep behaviour against an in-memory GitHub double, with every model call stubbed. No network, no Bedrock."""
import json
from pathlib import Path

import pytest

from flakeguard import orchestrator as orch
from flakeguard.actions import MemoryRemote, QUARANTINE_FILE, CONFTEST
from flakeguard.classifier import Classification
from flakeguard.config import load
from flakeguard.storage import Storage

ROOT = Path(__file__).parent.parent
FLAKE = "distributed.tests.test_jupyter::test_shutdowns_cleanly"
AMBIG = "distributed.shuffle.tests.test_shuffle::test_handle_null_partitions_2"
PLATFORM = "distributed.shuffle.tests.test_shuffle::test_restarting_during_transfer_raises_killed_worker"
REGRESSION = "distributed.tests.test_worker::test_get_client"
FIXTURES = [str(p) for p in ROOT.glob("fixtures/*.json")]

# what the classifier produced on these fixtures, ten times out of ten (probe-results/eval-phase3-sonnet45-10runs.txt)
VERDICTS = {FLAKE: ("chronic", 0.85), AMBIG: ("unclear", 0.40), PLATFORM: ("platform_specific", 0.95), REGRESSION: ("regression", 0.95)}


@pytest.fixture
def world(monkeypatch):
    cfg = load(ROOT / "flakeguard.toml").model_copy(deep=True)
    cfg.triage.dry_run = False
    cfg.target.scratch_repo = "someone/scratch"
    remote = MemoryRemote()
    store = Storage(":memory:")
    calls = {"classify": 0}

    def fake_classify(h, cfg_, agent=None):
        calls["classify"] += 1
        v, c = VERDICTS[h.test_id]
        return Classification(verdict=v, confidence=c, primary_signal="stub", conflicting_signals="none", reasoning="stub"), "EVIDENCE"

    monkeypatch.setattr(orch, "classify", fake_classify)
    monkeypatch.setattr(orch, "correlate", lambda *a, **k: (None, ""))
    monkeypatch.setattr(orch, "draft", lambda *a, **k: ("ARTIFACT", []))
    monkeypatch.setattr(orch.GitHub, "commit", lambda self, sha: {"sha": sha, "message": "m", "date": "2026-01-01", "files": []})

    def run(day, tests, extra_rows=None):
        r = orch.configure(cfg, FIXTURES, remote=remote, store=store, as_of=f"{day}T23:59:59Z", log=lambda *_: None)
        for test_id, rows in (extra_rows or {}).items():
            r.fixtures[test_id] = r.fixtures[test_id] + rows
        return orch.sweep(tests, log=lambda *_: None)

    return run, remote, store, calls


def test_ambiguous_routes_to_review_and_touches_nothing(world):
    run, remote, store, _ = world
    run("2026-09-13", [AMBIG])
    assert remote.prs == [] and len(remote.issues) == 1 and remote.issues[0]["title"] == "[FlakeGuard] Review queue"
    assert store.decisions()[-1]["action"] == "review"
    assert not any(k[1] == QUARANTINE_FILE for k in remote.files)


def test_two_sweeps_one_day_zero_duplicates(world):
    run, remote, store, calls = world
    run("2026-09-13", [FLAKE, PLATFORM, AMBIG])
    prs, issues, comments = len(remote.prs), len(remote.issues), sum(map(len, remote.comments.values()))
    assert prs == 1 and issues == 2 and comments == 1     # quarantine PR, platform issue, review-queue issue + 1 comment
    n_calls = calls["classify"]
    ts = run("2026-09-13", [FLAKE, PLATFORM, AMBIG])
    assert all(t.decision.action == "none" for t in ts)
    assert (len(remote.prs), len(remote.issues), sum(map(len, remote.comments.values()))) == (prs, issues, comments)
    assert calls["classify"] == n_calls                    # second sweep cost zero model calls


def test_next_day_existing_issue_gets_a_comment_and_quarantined_flake_is_left_alone(world):
    run, remote, store, _ = world
    run("2026-09-13", [FLAKE, PLATFORM])
    ts = run("2026-09-14", [FLAKE, PLATFORM])
    by = {t.test_id: t for t in ts}
    assert by[FLAKE].decision.action == "none" and "Already quarantined" in by[FLAKE].decision.reason
    assert by[PLATFORM].outcome.kind == "issue_comment" and len(remote.issues) == 1 and len(remote.prs) == 1


def test_quarantine_pr_edits_the_list_adds_the_hook_and_never_merges(world):
    run, remote, store, _ = world
    run("2026-09-13", [FLAKE])
    pr = remote.prs[0]
    assert pr["state"] == "open" and pr["head"].startswith("flakeguard/quarantine/")
    assert FLAKE in remote.files[(pr["head"], QUARANTINE_FILE)]
    assert "pytest.mark.xfail" in remote.files[(pr["head"], CONFTEST)]
    assert (("main", QUARANTINE_FILE) not in remote.files)  # nothing landed on the default branch


def test_regression_fixture_has_too_few_runs_to_act(world):
    run, remote, store, calls = world
    ts = run("2026-09-13", [REGRESSION])
    assert ts[0].decision.action == "review" and "min_runs" in ts[0].decision.reason
    assert calls["classify"] == 0 and remote.prs == []


def test_unquarantine_reverses_a_prior_quarantine(world):
    run, remote, store, _ = world
    run("2026-09-13", [FLAKE])                       # quarantined today
    # synthetic future: 25 clean runs in every cell after the quarantine
    rows = json.loads((ROOT / "fixtures/flake_test_shutdowns_cleanly.json").read_text(encoding="utf-8"))["observations"]
    cells = sorted({r["cell"] for r in rows})[:3]
    future = [{**rows[0], "run_id": 900000 + i, "started_at": f"2026-10-{i + 1:02d}T06:00:00Z", "cell": c, "outcome": "pass", "source": "artifact"}
              for i in range(25) for c in cells]
    run("2026-10-26", [], extra_rows={FLAKE: future})   # a later sweep with nothing to triage still runs the un-quarantine pass
    kinds = [p["title"] for p in remote.prs]
    assert kinds == [f"[FlakeGuard] quarantine {FLAKE}", f"[FlakeGuard] un-quarantine {FLAKE}"]
    assert FLAKE not in remote.files[(remote.prs[1]["head"], QUARANTINE_FILE)]
    assert store.quarantined_at(FLAKE) is None


def test_unquarantine_not_due_while_failures_continue(world):
    run, remote, store, _ = world
    run("2026-08-01", [FLAKE])                       # quarantine as of Aug 1; real data shows failures after
    run("2026-09-13", [])
    assert len(remote.prs) == 1 and store.quarantined_at(FLAKE) is not None


def test_no_reversal_on_the_day_of_quarantine(world):
    run, remote, store, _ = world
    run("2026-09-13", [FLAKE])
    rows = json.loads((ROOT / "fixtures/flake_test_shutdowns_cleanly.json").read_text(encoding="utf-8"))["observations"]
    future = [{**rows[0], "run_id": 900000 + i, "started_at": f"2026-09-13T{6 + i // 4:02d}:{(i % 4) * 15:02d}:00Z", "outcome": "pass"} for i in range(25)]
    run("2026-09-13", [], extra_rows={FLAKE: future})
    assert len(remote.prs) == 1
