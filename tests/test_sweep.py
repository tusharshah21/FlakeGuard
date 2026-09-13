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
    cfg.target.scratch_branch = "scratch"
    remote = MemoryRemote()
    remote.branches["scratch"] = "1" * 40
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
    assert remote.prs == [] and len(remote.issues) == 1 and remote.issues[0]["title"] == "[REPLAY] [FlakeGuard] Review queue"
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
    assert pr["base"] == "scratch" and all(b != "main" for (b, _) in remote.files)  # nothing near main
    assert "flakeguard-replay" in remote.labels


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
    assert kinds == [f"[REPLAY as of 2026-09-13] [FlakeGuard] quarantine {FLAKE}",
                     f"[REPLAY 2026-09-13 -> 2026-10-26] [FlakeGuard] un-quarantine {FLAKE}"]
    assert all(p["body"].startswith("[REPLAY") and "replay artifact" in p["body"] and "declared clock" in p["body"] for p in remote.prs)
    assert all("flakeguard-replay" in i["labels"] for i in remote.issues)
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


def test_human_closed_artifacts_are_not_recreated(world):
    run, remote, store, _ = world
    run("2026-09-13", [FLAKE, PLATFORM])
    for x in remote.issues + remote.prs:
        if x["title"] != "[REPLAY] [FlakeGuard] Review queue":
            x["state"] = "closed"                        # a maintainer closes both
    ts = run("2026-09-14", [PLATFORM])
    assert ts[0].outcome.kind == "closed_by_human" and len(remote.issues) == 1   # nothing recreated
    # the flake is still recorded as quarantined in storage (the PR existed); the loop, not a new PR, decides its future
    assert len(remote.prs) == 1


def test_superseded_label_lets_the_agent_redo_a_closed_artifact(world):
    run, remote, store, _ = world
    run("2026-09-13", [PLATFORM])
    remote.issues[0]["state"] = "closed"
    remote.issues[0]["labels"].add("flakeguard-superseded")
    ts = run("2026-09-14", [PLATFORM])
    assert ts[0].outcome.kind == "issue" and len(remote.issues) == 2


def test_action_cap_defers_the_rest_to_the_next_sweep(world):
    run, remote, store, _ = world
    orch.load  # noqa: B018  (cfg copy lives inside the fixture; set the cap on it)
    cfg = orch.rt().cfg if orch._rt else None
    ts = run("2026-09-13", [FLAKE, PLATFORM])
    assert [t.outcome.kind for t in ts] == ["quarantine_pr", "issue"]
    # a second world with cap 1: the second actionable case is deferred, not silently dropped
    orch.rt().cfg.triage.max_actions_per_sweep = 1
    store2 = Storage(":memory:")
    orch.configure(orch.rt().cfg, FIXTURES, remote=MemoryRemote(branches={"main": "0" * 40, "scratch": "1" * 40}), store=store2,
                   as_of="2026-09-13T23:59:59Z", log=lambda *_: None)
    ts = orch.sweep([FLAKE, PLATFORM], log=lambda *_: None)
    assert [t.outcome.kind for t in ts] == ["quarantine_pr", "deferred"]
    assert store2.decisions()[-1]["action"] == "deferred"
    # next day the deferred one goes through
    orch.configure(orch.rt().cfg, FIXTURES, remote=orch.rt().actions.remote, store=store2, as_of="2026-09-14T23:59:59Z", log=lambda *_: None)
    ts = orch.sweep([PLATFORM], log=lambda *_: None)
    assert ts[0].outcome.kind == "issue"


def test_model_call_ceiling_aborts_the_sweep_loudly(world, monkeypatch):
    """The cap counts model calls, not artifacts: a runaway unattended sweep must go red, not quietly expensive."""
    from flakeguard.classifier import MODEL_CALLS, ModelBudgetExceeded, spend

    run, remote, store, _ = world
    monkeypatch.setattr(orch, "classify", lambda h, cfg, agent=None: (
        spend("classify", cfg.triage.max_model_calls_per_sweep),
        Classification(verdict=VERDICTS[h.test_id][0], confidence=VERDICTS[h.test_id][1],
                       primary_signal="s", conflicting_signals="none", reasoning="r"), "EVIDENCE")[1:])
    for k in MODEL_CALLS:
        MODEL_CALLS[k] = 0
    orch.load  # noqa: B018
    cfg_holder = []

    def run_capped(cap, tests):
        r = orch.configure(orch.rt().cfg if orch._rt else None, FIXTURES, remote=remote, store=store,
                           as_of="2026-09-13T23:59:59Z", log=lambda *_: None)
        r.cfg.triage.max_model_calls_per_sweep = cap
        cfg_holder.append(r.cfg)
        return orch.sweep(tests, log=lambda *_: None)

    run("2026-09-12", [])                      # prime the runtime/config
    with pytest.raises(ModelBudgetExceeded, match="max_model_calls_per_sweep = 1"):
        run_capped(1, [FLAKE, PLATFORM])
    assert sum(MODEL_CALLS.values()) == 1      # stopped at the ceiling, did not overshoot
    assert store.decisions()[-1]["action"] == "aborted"
    assert "sweep aborted" in store.decisions()[-1]["reason"]
    assert len(remote.prs) == 1                # the first case acted before the ceiling; the second never ran


def test_artifact_budget_stops_inference_not_just_actions(world, monkeypatch):
    """Two budgets guarding different resources compose only if the cheaper check runs first: once the artifact cap
    is spent, further candidates must cost zero model calls and stay eligible for the next sweep."""
    from flakeguard.classifier import MODEL_CALLS

    run, remote, store, calls = world
    for k in MODEL_CALLS:
        MODEL_CALLS[k] = 0
    orch.configure(orch.rt().cfg if orch._rt else None, FIXTURES, remote=remote, store=store,
                   as_of="2026-09-13T23:59:59Z", log=lambda *_: None) if orch._rt else None
    run("2026-09-12", [])                       # prime the runtime
    orch.rt().cfg.triage.max_actions_per_sweep = 1

    ts = run("2026-09-13", [FLAKE, PLATFORM, AMBIG])
    by = {t.test_id: t for t in ts}
    assert by[FLAKE].outcome.kind == "quarantine_pr"          # first actionable case spends its 1 artifact
    assert by[PLATFORM].decision.action == "deferred" and by[PLATFORM].classification is None
    assert "max_actions_per_sweep" in by[PLATFORM].decision.reason
    assert calls["classify"] == 1                             # deferred case cost no inference
    assert by[AMBIG].decision.action == "review"              # review needs no artifact budget and still runs

    # deferred is not a decision: the next sweep triages it normally
    assert store.last_real_decision_on(PLATFORM) is None
    orch.rt().cfg.triage.max_actions_per_sweep = 3
    ts = run("2026-09-14", [PLATFORM])
    assert ts[0].outcome.kind == "issue" and calls["classify"] == 2


def test_dry_run_flag_cannot_be_overridden_by_config(world):
    """--dry-run is one-way: it only ever makes a run safer, whatever flakeguard.toml says."""
    run, remote, store, _ = world
    cfg = orch.rt().cfg if orch._rt else None
    run("2026-09-12", [])
    live_cfg = orch.rt().cfg
    live_cfg.triage.dry_run = False                       # config says write
    r = orch.configure(live_cfg, FIXTURES, remote=remote, store=Storage(":memory:"),
                       as_of="2026-09-13T23:59:59Z", log=lambda *_: None, force_dry=True)
    assert r.actions.dry is True and r.cfg.triage.dry_run is True
    assert live_cfg.triage.dry_run is False               # the caller's config is not mutated
    orch.sweep([PLATFORM], log=lambda *_: None)
    assert remote.issues == [] and remote.prs == []


def test_startup_announces_the_effective_mode(world):
    run, remote, store, _ = world
    run("2026-09-12", [])
    lines = []
    cfg = orch.rt().cfg
    cfg.triage.dry_run = False
    orch.configure(cfg, FIXTURES, remote=remote, store=store, as_of="2026-09-13T23:59:59Z", log=lines.append)
    assert lines[0].startswith("WRITE MODE: artifacts will be created in someone/scratch on branch scratch")
    orch.configure(cfg, FIXTURES, remote=remote, store=store, as_of="2026-09-13T23:59:59Z", log=lines.append, force_dry=True)
    assert lines[-1] == "DRY RUN: nothing will be written. (forced by --dry-run)"
