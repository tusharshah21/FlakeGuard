"""Orchestration. The steps are Strands tools (agents-as-tools: classifier, correlation and drafter are agents behind
tool functions; health and commit context are deterministic). `triage()` runs them in a fixed order from Python and
`sweep()` runs triage over many tests, applies the action gate, acts, and records.

Every tool takes only a test_id. No tool accepts a sha, a file list or a verdict from a caller, so nothing that
reaches a model can be steered by another model. The sequence is code, not a prompt. The gate is code.
"""
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from strands import tool

from .actions import PROTECTED_BASES, Actions, GitHubRemote, Outcome, Remote
from .baseline import episode
from .classifier import MODEL_CALLS, Classification, ModelBudgetExceeded, classify, render_evidence
from .config import Config, load
from .correlation import Correlation, correlate
from .drafter import draft
from .gate import Decision, decide, unquarantine_due
from .github import GitHub
from .stats import TestHealth, Thresholds, test_health
from .storage import Storage


@dataclass
class Runtime:
    cfg: Config
    store: Storage
    gh: GitHub
    actions: Actions
    fixtures: dict[str, list[dict]]   # test_id -> observations, when triaging fixtures instead of storage
    as_of: str | None = None          # replay clock: only observations started at or before this instant are visible

    def rows(self, test_id: str) -> list[dict]:
        rows = self.fixtures[test_id] if test_id in self.fixtures else self.store.pooled_observations(test_id)
        return [r for r in rows if r["started_at"] <= self.as_of] if self.as_of else rows

    @property
    def now(self) -> str:
        return self.as_of or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @property
    def today(self) -> str:
        return self.now[:10]


_rt: Runtime | None = None


def configure(cfg: Config | None = None, fixture_paths: list[str] = (), remote: Remote | None = None,
              store: Storage | None = None, as_of: str | None = None, log=print, force_dry: bool = False) -> Runtime:
    global _rt
    cfg = cfg or load()
    if force_dry:
        # --dry-run is one-way: it can only ever make a run safer, and no config value can switch it back on.
        cfg = cfg.model_copy(deep=True)
        cfg.triage.dry_run = True
    fixtures = {}
    for p in fixture_paths:
        fx = json.loads(Path(p).read_text(encoding="utf-8"))
        fixtures[fx["test_id"]] = fx["observations"]
    if not cfg.triage.dry_run:
        # Two invariants, refused at startup before any model or API call. (1) The write target is never the analysis
        # target. (2) PRs only ever target scratch_branch, which must exist and must not be main/master.
        if not cfg.target.scratch_repo or cfg.target.scratch_repo == cfg.target.repo:
            raise SystemExit("dry_run is off but scratch_repo is unset or equals the analysis target; refusing to act")
        if cfg.target.scratch_branch.lower() in PROTECTED_BASES:
            raise SystemExit(f"dry_run is off but scratch_branch is {cfg.target.scratch_branch!r}; it must be a dedicated non-main branch")
        remote = remote or GitHubRemote(cfg.target.scratch_repo, os.environ["GITHUB_TOKEN"])
        try:
            remote.head_sha(cfg.target.scratch_branch)
        except Exception as e:
            raise SystemExit(f"dry_run is off but scratch_branch {cfg.target.scratch_branch!r} does not exist in {cfg.target.scratch_repo}: {e}")
    if cfg.triage.dry_run:
        log("DRY RUN: nothing will be written." + (" (forced by --dry-run)" if force_dry else ""))
    else:
        log(f"WRITE MODE: artifacts will be created in {cfg.target.scratch_repo} on branch {cfg.target.scratch_branch}")
    today = (as_of or datetime.now(timezone.utc).isoformat())[:10]
    _rt = Runtime(cfg, store or Storage(cfg.ingest.db_path), GitHub(cfg.target.repo, cfg.ingest.cache_dir),
                  Actions(cfg, remote, log, as_of=as_of, today=today), fixtures, as_of)
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
    classification: Classification | None
    evidence: str
    correlation: Correlation | None
    commit_ctx: dict | None
    decision: Decision
    artifact: str
    invented_numbers: list[str]
    outcome: Outcome | None = None


def gate_state(test_id: str) -> dict:
    r = rt()
    return {"last_decision_on": r.store.last_real_decision_on(test_id),
            "quarantined": r.store.quarantined_at(test_id) is not None,
            "overridden": r.actions.overridden(test_id), "today": r.today}


def triage(test_id: str, budget: list[int] | None = None) -> Triage:
    """health -> gate pre-check -> artifact-budget check -> classify -> (regression only) correlate -> gate -> draft.

    Both cheap checks run before the classifier. The gate disposes of cases no verdict could change; the artifact
    budget disposes of cases no verdict could act on. Two budgets guarding different resources only compose if the
    cheaper one runs first - see the README."""
    r = rt()
    h = health(test_id)
    state = gate_state(test_id)
    pre = decide(h, None, r.cfg, **state)
    if pre.action == "none" or (pre.action == "review" and "min_runs" in pre.reason):
        evidence = render_evidence(h, r.cfg)
        return Triage(test_id, h, None, evidence, None, None, pre, review_note(test_id, evidence, pre), [])
    if budget is not None and budget[0] <= 0:
        # No artifact budget left, so no verdict could act. Spend nothing on inference; defer, and stay eligible
        # next sweep - deferral is not a triage decision, so the one-per-day rule must not swallow it.
        d = Decision("deferred", f"max_actions_per_sweep = {r.cfg.triage.max_actions_per_sweep} reached earlier in this "
                                 f"sweep; not classified, deferred to the next sweep")
        evidence = render_evidence(h, r.cfg)
        return Triage(test_id, h, None, evidence, None, None, d, review_note(test_id, evidence, d), [])
    cls, evidence = classify(h, r.cfg)
    corr, ctx = None, None
    if cls.verdict == "regression":
        ctx = r.gh.commit(episode(h).head_sha)
        corr, _ = correlate(test_id, h, ctx, r.cfg)
    decision = decide(h, cls, r.cfg, **state)
    artifact, invented = draft(test_id, h, cls, evidence, corr, ctx, decision, r.cfg)
    return Triage(test_id, h, cls, evidence, corr, ctx, decision, artifact, invented)


def review_note(test_id: str, evidence: str, decision: Decision) -> str:
    return "\n".join([f"# FlakeGuard: `{test_id}`", "", f"**{decision.action}** - {decision.reason}", "",
                      "## Evidence", "```", evidence, "```"])


def act(t: Triage, budget: list[int] | None = None) -> Outcome:
    """budget is a one-element list [remaining new artifacts this sweep]; decremented in place. ponytail: a list as a
    mutable counter; make it a Sweep object if the sweep grows more state."""
    r = rt()
    a = t.decision.action
    if a == "deferred":
        out = Outcome("deferred", None, t.decision.reason)
        r.store.record_decision(t.test_id, r.now, None, None, "deferred", t.decision.reason, None, r.actions.dry)
        t.outcome = out
        return out
    if a == "issue":
        out = r.actions.open_issue(t.test_id, t.artifact)
    elif a == "quarantine_pr":
        out = r.actions.open_quarantine_pr(t.test_id, t.artifact)
    elif a == "review":
        out = r.actions.review(t.test_id, r.today, t.artifact)
    else:
        out = Outcome("noop", None, t.decision.reason)
    if budget is not None and a in ("issue", "quarantine_pr") and out.kind not in ("closed_by_human",):
        budget[0] -= 1   # counts intent, not medium: a dry run must exercise the same cap a live run enforces
    recorded = out.kind if out.kind == "closed_by_human" else a   # the ledger records what happened, not what was intended
    r.store.record_decision(t.test_id, r.now, t.classification and t.classification.verdict,
                            t.classification and t.classification.confidence, recorded, f"{t.decision.reason} -> {out.detail}", out.url, r.actions.dry)
    t.outcome = out
    return out


def unquarantine_pass() -> list[tuple[str, int, Outcome]]:
    """A quarantined test that has passed for unquarantine_after_passes consecutive runs since quarantine gets un-quarantined."""
    r = rt()
    results = []
    for test_id, quarantined_at in r.store.quarantined_tests():
        if quarantined_at[:10] == r.today:
            continue  # never reverse a decision made in the same sweep day
        rows = r.rows(test_id)
        due, clean = unquarantine_due(rows, quarantined_at, r.cfg)
        if not due:
            continue
        h = test_health(rows, Thresholds(**r.cfg.stats.model_dump()))
        body = "\n".join([
            f"# FlakeGuard: un-quarantine `{test_id}`",
            "",
            f"Quarantined on {quarantined_at[:10]}. Since then the test has passed in every cell for **{clean} consecutive runs** "
            f"(threshold: {r.cfg.triage.unquarantine_after_passes}). FlakeGuard is reversing its own decision.",
            "",
            "## Evidence", "```", render_evidence(h, r.cfg), "```",
            "",
            "## How to override",
            "If you want the test to stay quarantined, close this PR and apply the label `flakeguard-override`.",
        ])
        out = r.actions.open_unquarantine_pr(test_id, body, span=f"{quarantined_at[:10]} -> {r.today}")
        recorded = out.kind if out.kind == "closed_by_human" else "unquarantine_pr"   # the ledger records what happened
        r.store.record_decision(test_id, r.now, None, None, recorded, f"{clean} clean runs since quarantine -> {out.detail}", out.url, r.actions.dry)
        results.append((test_id, clean, out))
    return results


def sweep(test_ids: list[str], log=print) -> list[Triage]:
    r = rt()
    log(f"sweep {r.today}{' (replay as of ' + r.as_of + ')' if r.as_of else ''}: {len(test_ids)} tests, "
        f"dry_run={r.actions.dry}, action target={r.cfg.target.scratch_repo or '<unset>'}")
    results = []
    budget = [r.cfg.triage.max_actions_per_sweep]
    for test_id in test_ids:
        try:
            t = triage(test_id, budget)
        except ModelBudgetExceeded as e:
            # Hard stop. Record it where the gate and the operator will both see it, then fail loudly: an unattended
            # sweep that runs away is worse than one that goes red.
            r.store.record_decision(test_id, r.now, None, None, "aborted", str(e), None, r.actions.dry)
            log(f"  ABORTED at {test_id}: {e}")
            log(f"  model calls this process: {dict(MODEL_CALLS)} (total {sum(MODEL_CALLS.values())})")
            raise
        out = act(t, budget)
        v = f"{t.classification.verdict}@{t.classification.confidence:.2f}" if t.classification else "not classified"
        log(f"  {test_id.split('::')[-1]:50s} {v:22s} gate={t.decision.action:14s} -> {out.kind}: {out.detail}")
        if t.invented_numbers:
            log(f"    drafter introduced numbers not in its input: {t.invented_numbers}")
        results.append(t)
    for test_id, clean, out in unquarantine_pass():
        log(f"  {test_id.split('::')[-1]:50s} {'quarantined':22s} gate={'unquarantine_pr':14s} -> {out.kind}: {out.detail} ({clean} clean runs)")
    log(f"  model calls this process: {dict(MODEL_CALLS)} (total {sum(MODEL_CALLS.values())})")
    return results
