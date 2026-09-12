"""stats.py over the real fixtures. Numbers here were verified by hand against `python -m flakeguard health`."""
import ast
import json
from pathlib import Path

import pytest

from flakeguard.config import load
from flakeguard.stats import Thresholds, best_split, wilson
from flakeguard.stats import test_health as health_of

ROOT = Path(__file__).parent.parent
T = Thresholds(**load(ROOT / "flakeguard.toml").stats.model_dump())


def health(name):
    return health_of(json.loads((ROOT / "fixtures" / f"{name}.json").read_text(encoding="utf-8"))["observations"], T)


def test_stats_imports_nothing_from_strands():
    tree = ast.parse((ROOT / "flakeguard" / "stats.py").read_text(encoding="utf-8"))
    mods = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)} | \
           {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert mods <= {"math", "collections", "dataclasses"}, mods


def test_wilson_known_values():
    assert wilson(17, 17, 1.96) == pytest.approx((0.8157, 1.0), abs=1e-3)
    assert wilson(0, 17, 1.96) == pytest.approx((0.0, 0.1843), abs=1e-3)
    assert wilson(1, 4, 1.96) == pytest.approx((0.0456, 0.6994), abs=1e-3)
    assert wilson(0, 0, 1.96) == (0.0, 1.0)


def test_best_split_finds_the_boundary():
    s = best_split([("a", "t1", 0, 10), ("b", "t2", 0, 10), ("c", "t3", 10, 10), ("d", "t4", 10, 10)])
    assert (s.at_sha, s.shift, s.before_n, s.after_n) == ("c", 1.0, 20, 20)
    assert best_split([("a", "t1", 1, 1)]) is None


def test_regression_fixture():
    h = health("regression_test_get_client")
    failing = next(c for c in h.commits if c.head_sha.startswith("9ce93727b7"))
    fixed = next(c for c in h.commits if c.head_sha.startswith("696800cc91"))
    assert (failing.fails, failing.n, failing.cells_failed, failing.cells_total) == (17, 17, 17, 17)
    assert failing.ci_low > 0.8 and failing.p_hat == 1.0
    assert (fixed.fails, fixed.n) == (0, 17) and fixed.ci_high < 0.2
    assert not failing.concentrated and not failing.recovery
    assert h.n_inferred == 0  # PR branch: every observation is measured
    assert h.largest_shift.at_sha == fixed.head_sha and h.largest_shift.shift == -1.0
    assert h.onset_sha is None and not h.chronic


def test_flake_fixture():
    h = health("flake_test_shutdowns_cleanly")
    assert (h.fails, h.n, h.cells_total) == (37, 2267, 12)
    assert h.ci_high < 0.05  # never anywhere near a regression
    assert h.recovery_commits == 9 and h.spread_recovery_commits >= 3 and h.chronic
    assert all(c.ci_high < 0.3 for c in h.commits)
    assert h.onset_sha is None
    assert h.n_inferred > h.n_measured  # denominator is mostly inferred, and says so


def test_ambiguous_fixture_does_not_separate():
    h = health("ambiguous_test_handle_null_partitions_2")
    latest = h.commits[-1]
    assert latest.head_sha.startswith("aa2ddc315e") and (h.fails, h.n) == (1, 45)
    assert (latest.fails, latest.n, latest.cells_failed, latest.cells_total) == (1, 26, 1, 5)
    failing_cell = next(v for v in latest.per_cell.values() if v[0])
    assert failing_cell == [1, 1]  # the only failing cell has a single observation: platform break not excluded
    assert wilson(1, 1, T.z)[1] == 1.0
    assert h.ci_high > 0.1  # test level does not reach flake territory (the flake fixture's ci_high is 0.022)
    assert not h.chronic and h.onset_sha is None and h.recovery_commits == 1


def test_regression_and_flake_are_separated():
    reg = next(c for c in health("regression_test_get_client").commits if c.head_sha.startswith("9ce93727b7"))
    flake = health("flake_test_shutdowns_cleanly")
    assert reg.ci_low > flake.ci_high
    assert reg.ci_low > max(c.ci_high for c in flake.commits)
