"""uv run python -m flakeguard ingest | health <fixture.json | test_id> | triage <fixture.json | test_id>
                          | sweep [--fixtures a.json b.json] [--tests id ...] [--all-failing | --recent] [--as-of ISO8601] [--dry-run]
                          | decisions [YYYY-MM-DD] | ledger export|import <file>
                          | explain <fixture.json | test_id> [question] [--json]"""
import json
import sys
from pathlib import Path

from .config import load
from .github import GitHub
from .ingest import ingest
from .stats import Thresholds, test_health
from .storage import Storage

cfg = load()
cmd = sys.argv[1] if len(sys.argv) > 1 else "ingest"
if cmd == "ingest":
    ingest(cfg, Storage(cfg.ingest.db_path), GitHub(cfg.target.repo, cfg.ingest.cache_dir))
elif cmd == "health":
    arg = sys.argv[2]
    rows = json.loads(Path(arg).read_text(encoding="utf-8"))["observations"] if arg.endswith(".json") \
        else Storage(cfg.ingest.db_path).pooled_observations(arg)
    h = test_health(rows, Thresholds(**cfg.stats.model_dump()))
    print(f"{h.test_id}\n  window {h.window_start[:10]}..{h.window_end[:10]}  runs={h.runs} commits={len(h.commits)}")
    print(f"  n={h.n} (measured {h.n_measured}, inferred {h.n_inferred})  fails={h.fails}  p_hat={h.p_hat:.4f}  wilson95=[{h.ci_low:.3f}, {h.ci_high:.3f}]")
    print(f"  cells_failed/cells_total={h.cells_failed}/{h.cells_total}  max_consecutive_failing_runs={h.max_consecutive_failing_runs}")
    print(f"  top_cell_share={h.top_cell_share:.2f}  top_os={h.top_os}({h.top_os_share:.2f})  concentrated={h.concentrated}")
    print(f"  recovery_commits={h.recovery_commits}  spread_recovery_commits={h.spread_recovery_commits}  chronic={h.chronic}")
    if h.largest_shift:
        s = h.largest_shift
        print(f"  largest_shift={s.shift:+.3f} at {s.at_sha[:10]} ({s.before_fails}/{s.before_n} before -> {s.after_fails}/{s.after_n} after)  onset_sha={h.onset_sha and h.onset_sha[:10]}")
    print(f"  {'sha':10} {'first':10} {'runs':>4} {'n':>5} {'meas':>4} {'fail':>4} {'p_hat':>6} {'wilson95':>15} {'cells':>6} {'topcell':>7} {'topOS':>6} conc rec temporal")
    for c in h.commits:
        tmp = f"{c.temporal.shift:+.2f}@{c.temporal.at_started_at[5:10]}" if c.temporal else "-"
        print(f"  {c.head_sha[:10]} {c.first_started_at[:10]} {c.runs:4d} {c.n:5d} {c.n_measured:4d} {c.fails:4d} {c.p_hat:6.3f} [{c.ci_low:5.3f}, {c.ci_high:5.3f}] {c.cells_failed:2d}/{c.cells_total:<3d} {c.top_cell_share:7.2f} {c.top_os_share:6.2f} {str(c.concentrated)[0]:>4} {str(c.recovery)[0]:>3} {tmp}")
elif cmd == "triage":
    from .orchestrator import configure, triage
    arg = sys.argv[2]
    if arg.endswith(".json"):
        configure(cfg, [arg])
        arg = json.loads(Path(arg).read_text(encoding="utf-8"))["test_id"]
    else:
        configure(cfg)
    t = triage(arg)
    sys.stdout.reconfigure(encoding="utf-8")
    print(t.artifact)
    if t.invented_numbers:
        print(f"<!-- drafter introduced numbers not in its input: {t.invented_numbers} -->", file=sys.stderr)
elif cmd == "sweep":
    from .orchestrator import configure, sweep
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[2:]
    def opt(name):
        if name not in args:
            return []
        i = args.index(name) + 1
        out = []
        while i < len(args) and not args[i].startswith("--"):
            out.append(args[i]); i += 1
        return out
    fixtures = opt("--fixtures")
    as_of = (opt("--as-of") or [None])[0]
    r = configure(cfg, fixtures, as_of=as_of, force_dry="--dry-run" in args)
    tests = opt("--tests") or list(r.fixtures) if fixtures else opt("--tests")
    if "--all-failing" in args:
        tests = r.store.failing_tests()
    if "--recent" in args:
        from datetime import datetime, timedelta, timezone
        since = ((datetime.fromisoformat(as_of.replace("Z", "+00:00")) if as_of else datetime.now(timezone.utc))
                 - timedelta(days=cfg.triage.recent_failure_days)).strftime("%Y-%m-%d")
        tests = r.store.recently_failing_tests(since)
    from .classifier import ModelBudgetExceeded
    try:
        sweep(tests)
    except ModelBudgetExceeded as e:
        sys.exit(f"FlakeGuard aborted: {e}")   # non-zero exit: the Actions run goes red rather than silently expensive
elif cmd == "explain":
    # Interactive surface: the model sequences read-only tools itself. Never writes; see flakeguard/explain.py.
    from .explain import DEFAULT_QUESTION, explain
    from .orchestrator import configure
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[2:]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    test_id, question = args[0], " ".join(args[1:]) or DEFAULT_QUESTION
    configure(cfg, [test_id] if test_id.endswith(".json") else [], force_dry=True, log=lambda *_: None)
    if test_id.endswith(".json"):
        test_id = json.loads(Path(test_id).read_text(encoding="utf-8"))["test_id"]
    e = explain(test_id, question, cfg)
    if as_json:
        print(json.dumps({"test_id": e.test_id, "question": e.question, "answer": e.answer,
                          "tool_calls": e.tool_calls, "model_calls": e.model_calls}, indent=1))
    else:
        tools = " -> ".join(e.tool_calls) or "none"
        print(f"{e.test_id}\nQ: {e.question}\n\n{e.answer}\n\n[tools: {tools} | model turns: {e.model_calls}]")
elif cmd == "ledger":
    # ledger export <file> | ledger import <file>  - the decision ledger is the state the gate reads; CI inherits it from here
    from .storage import Storage
    store = Storage(cfg.ingest.db_path)
    if sys.argv[2] == "export":
        rows = [d for d in store.decisions() if not d["dry_run"]]
        Path(sys.argv[3]).write_text(json.dumps(rows, indent=1), encoding="utf-8")
        print(f"exported {len(rows)} live decisions")
    else:
        print(f"imported {store.import_decisions(json.loads(Path(sys.argv[3]).read_text(encoding='utf-8')))} new decisions")
elif cmd == "decisions":
    from .storage import Storage
    for d in Storage(cfg.ingest.db_path).decisions(sys.argv[2] if len(sys.argv) > 2 else None):
        print(f"{d['decided_at']} {'DRY ' if d['dry_run'] else 'LIVE'} {d['action']:15s} {d['test_id'].split('::')[-1]:45s} {d['verdict'] or '-':18s} {d['url'] or ''}  {d['reason']}")
else:
    sys.exit(f"unknown command {cmd!r}")
