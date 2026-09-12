"""SQLite storage. Public rows always have the contract shape shared with fixtures/*.json:

    {run_id, head_sha, branch, event, started_at, cell, test_id, outcome, source}

`source` is "artifact" for an outcome read from a JUnit file and "roster" for a pass inferred from a succeeded
job plus the cell's nearest-in-time roster. Inferred passes are derived at read time, never stored.
"""
import sqlite3
from bisect import bisect_left
from collections import defaultdict

COLUMNS = ("run_id", "head_sha", "branch", "event", "started_at", "cell", "test_id", "outcome", "source")

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    run_id INTEGER, head_sha TEXT, branch TEXT, event TEXT, started_at TEXT,
    cell TEXT, test_id TEXT, outcome TEXT, source TEXT,
    PRIMARY KEY (run_id, test_id, cell)
);
CREATE INDEX IF NOT EXISTS obs_test ON observations (test_id);
-- one row per (run, matrix cell): the job's conclusion and what ingestion did with it
CREATE TABLE IF NOT EXISTS run_cells (
    run_id INTEGER, cell TEXT, head_sha TEXT, branch TEXT, event TEXT, started_at TEXT,
    job_conclusion TEXT,
    status TEXT,   -- parsed | roster | infra | unresolved | skipped
    PRIMARY KEY (run_id, cell)
);
-- sampled test rosters per cell (tests that passed in a sampled succeeded run)
CREATE TABLE IF NOT EXISTS rosters (
    cell TEXT, started_at TEXT, run_id INTEGER, test_id TEXT,
    PRIMARY KEY (cell, run_id, test_id)
);
"""


class Storage:
    def __init__(self, path: str = "flakeguard.db"):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # ---- writes (all idempotent on their primary keys)
    def upsert_observations(self, rows: list[dict]) -> None:
        self.db.executemany(
            f"INSERT OR REPLACE INTO observations ({','.join(COLUMNS)}) VALUES ({','.join('?' * len(COLUMNS))})",
            [tuple(r[c] for c in COLUMNS) for r in rows])
        self.db.commit()

    def upsert_run_cells(self, rows: list[dict]) -> None:
        cols = ("run_id", "cell", "head_sha", "branch", "event", "started_at", "job_conclusion", "status")
        self.db.executemany(
            f"INSERT OR REPLACE INTO run_cells ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            [tuple(r[c] for c in cols) for r in rows])
        self.db.commit()

    def upsert_roster(self, cell: str, started_at: str, run_id: int, test_ids: set[str]) -> None:
        self.db.executemany("INSERT OR REPLACE INTO rosters VALUES (?,?,?,?)",
                            [(cell, started_at, run_id, t) for t in test_ids])
        self.db.commit()

    # ---- reads
    def observations(self, test_id: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM observations", ()
        if test_id:
            q, args = q + " WHERE test_id = ?", (test_id,)
        return [dict(r) for r in self.db.execute(q, args)]

    def pooled_observations(self, test_id: str) -> list[dict]:
        """Artifact observations plus one inferred pass per succeeded run-cell whose nearest roster holds the test."""
        rows = self.observations(test_id)
        seen = {(r["run_id"], r["cell"]) for r in rows}
        roster_times = defaultdict(list)  # cell -> sorted [started_at] of roster samples containing this test
        for cell, started_at in self.db.execute(
                "SELECT cell, started_at FROM rosters WHERE test_id = ? ORDER BY cell, started_at", (test_id,)):
            roster_times[cell].append(started_at)
        all_times = defaultdict(list)
        for cell, started_at in self.db.execute("SELECT DISTINCT cell, started_at FROM rosters ORDER BY cell, started_at"):
            all_times[cell].append(started_at)
        for rc in self.db.execute("SELECT * FROM run_cells WHERE status = 'roster'"):
            if (rc["run_id"], rc["cell"]) in seen or rc["cell"] not in all_times:
                continue
            keys = all_times[rc["cell"]]
            nearest = keys[min(bisect_left(keys, rc["started_at"]), len(keys) - 1)]
            if nearest in roster_times[rc["cell"]]:
                rows.append({**{c: rc[c] for c in ("run_id", "head_sha", "branch", "event", "started_at", "cell")},
                             "test_id": test_id, "outcome": "pass", "source": "roster"})
        return rows

    def failing_tests(self) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT DISTINCT test_id FROM observations WHERE outcome = 'fail'")]

    def run_cell_status_counts(self) -> dict[str, int]:
        return dict(self.db.execute("SELECT status, COUNT(*) FROM run_cells GROUP BY status").fetchall())

    def count(self, table: str) -> int:
        return self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
