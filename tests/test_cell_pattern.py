"""The job-name to matrix-cell mapping is configuration, so FlakeGuard can be pointed at another repository
by editing flakeguard.toml rather than editing Python."""
from pathlib import Path

import pytest

from flakeguard.config import Target, load
from flakeguard.ingest import CellPatternError, cell_of

ROOT = Path(__file__).parent.parent


def target(**overrides) -> Target:
    base = load(ROOT / "flakeguard.toml").target.model_dump()
    return Target(**{**base, **overrides})


def test_the_shipped_pattern_reproduces_dask_cell_names():
    """These are real dask/distributed job names and the artifact names they must map onto."""
    t = target()
    cases = {
        "ubuntu-latest py312 test-ci not ci1": "ubuntu-latest-py312-test-ci-notci1",
        "ubuntu-latest py310 test-noqueue not ci1": "ubuntu-latest-py310-test-noqueue-notci1",
        "windows-latest py313 test-ci ci1": "windows-latest-py313-test-ci-ci1",
        "macos-latest py314 test-ci not ci1": "macos-latest-py314-test-ci-notci1",
    }
    for job, cell in cases.items():
        assert cell_of(job, t) == cell


def test_jobs_that_are_not_matrix_cells_are_ignored():
    t = target()
    assert cell_of("Event File", t) is None      # too few parts to match
    assert cell_of("lint", t) is None
    assert cell_of("ubuntu-latest py312 build ci1", t) is None   # matches, but filtered out by cell_filter


@pytest.mark.parametrize(
    "pattern, cell_filter, job, expected",
    [
        # A conventional GitHub matrix: jobs are named "test (ubuntu-latest, 3.12)".
        (r"^test \((?P<cell>[^)]+)\)$", "", "test (ubuntu-latest, 3.12)", "ubuntu-latest,-3.12"),
        # A job named after its platform with no decoration.
        (r"^(?P<cell>pytest-.+)$", "", "pytest-ubuntu-py311", "pytest-ubuntu-py311"),
        # Two named groups: the extra one is a suffix with its spaces dropped.
        (r"^(?P<cell>\S+) / (?P<shard>shard \d+)$", "", "linux / shard 3", "linux-shard3"),
        # cell_filter narrows a workflow that also contains non-test jobs.
        (r"^(?P<cell>.+)$", "test", "build-docs", None),
        (r"^(?P<cell>.+)$", "test", "test-linux", "test-linux"),
    ],
)
def test_other_repositories_need_only_a_pattern(pattern, cell_filter, job, expected):
    t = target(cell_pattern=pattern, cell_filter=cell_filter)
    assert cell_of(job, t) == expected


def test_cell_join_is_configurable():
    t = target(cell_pattern=r"^(?P<cell>\S+ \S+)$", cell_join="_", cell_filter="")
    assert cell_of("ubuntu latest", t) == "ubuntu_latest"


def test_a_pattern_without_a_cell_group_is_rejected_immediately():
    t = target(cell_pattern=r"^test \((.+)\)$")
    with pytest.raises(CellPatternError, match="named group"):
        cell_of("test (anything)", t)
