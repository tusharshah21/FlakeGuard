"""Contract test: a fixture row written to storage reads back structurally identical."""
import json
from pathlib import Path

from flakeguard.storage import COLUMNS, Storage

FIXTURES = sorted(Path(__file__).parent.parent.glob("fixtures/*.json"))


def test_fixture_round_trip():
    assert FIXTURES, "no fixtures found"
    for f in FIXTURES:
        fx = json.loads(f.read_text(encoding="utf-8"))
        store = Storage(":memory:")
        store.upsert_observations(fx["observations"])
        store.upsert_observations(fx["observations"])  # idempotent
        rows = store.observations(fx["test_id"])
        key = lambda r: (r["run_id"], r["cell"])
        assert sorted(rows, key=key) == sorted(fx["observations"], key=key), f.name
        assert all(tuple(r) == COLUMNS for r in rows), f.name
