"""Causal-direction guard. The correlation agent reasons forward from the FAILING commit only.

Nothing the agent is shown may contain the fix commit's sha or any file that only the fix commit touched.
This test is committed before flakeguard/correlation.py exists; it defines the interface that module must meet.
"""
import inspect
import json
from pathlib import Path

import pytest

from flakeguard.config import load
from flakeguard.stats import Thresholds
from flakeguard.stats import test_health as health_of

ROOT = Path(__file__).parent.parent
cfg = load(ROOT / "flakeguard.toml")
T = Thresholds(**cfg.stats.model_dump())
REGRESSIONS = sorted(ROOT.glob("fixtures/regression_*.json"))


def fixture(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", REGRESSIONS, ids=lambda p: p.stem)
def test_correlation_prompt_never_sees_the_fix(path):
    from flakeguard.baseline import episode
    from flakeguard.correlation import build_prompt

    fx = fixture(path)
    h = health_of(fx["observations"], T)
    # The commit under investigation is derived from the data, not passed in: the most recent commit with a failure.
    assert episode(h).head_sha == fx["failing_sha"]
    assert episode(h).head_sha != fx["fix_sha"]

    ctx = {"sha": fx["failing_sha"], "message": "irrelevant here", "date": "2026-01-01T00:00:00Z",
           "files": [{"filename": f, "status": "modified", "additions": 1, "deletions": 1} for f in fx["failing_commit_files"]]}
    prompt = build_prompt(fx["test_id"], h, ctx, cfg)

    assert fx["fix_sha"] not in prompt and fx["fix_sha"][:10] not in prompt and fx["fix_sha"][:7] not in prompt
    # The test's own module path is derivable from the test id alone, so it is not fix information even when the fix
    # commit edited it (PR #9356 did). Everything else the fix touched must be absent.
    own_file = fx["test_id"].split("::")[0].replace(".", "/") + ".py"
    for f in set(fx["fix_commit_files"]) - set(fx["failing_commit_files"]) - {own_file}:
        assert f not in prompt, f"fix-only file leaked: {f}"
    # and the prompt must not claim the failing commit touched the test file when it did not
    if own_file not in fx["failing_commit_files"]:
        assert f"  {own_file}" not in prompt.split("FILES CHANGED IN THIS COMMIT:")[1]
    assert fx["failing_sha"][:10] in prompt
    for f in fx["failing_commit_files"]:
        assert f in prompt


def test_build_prompt_has_no_parameter_for_fix_information():
    from flakeguard.correlation import build_prompt

    params = set(inspect.signature(build_prompt).parameters)
    assert params == {"test_id", "health", "ctx", "cfg"}
    assert not any("fix" in p for p in params)


def test_correlate_tool_takes_only_a_test_id():
    """The orchestrator's correlation step derives the commit itself; a model cannot hand it a sha."""
    from flakeguard.orchestrator import correlate_regression

    assert list(inspect.signature(correlate_regression).parameters) == ["test_id"]
