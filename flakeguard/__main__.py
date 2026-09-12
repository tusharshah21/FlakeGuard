"""uv run python -m flakeguard ingest | health <fixture.json | test_id>"""
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
else:
    sys.exit(f"unknown command {cmd!r}")
