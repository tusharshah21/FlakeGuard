"""PRs may only target the scratch branch. A PR against main would put the conftest hook and quarantine list one
merge away from the project's real test suite. This is an assertion in code, not a config toggle."""
from pathlib import Path

import pytest

from flakeguard.actions import Actions, MemoryRemote, CONFTEST, QUARANTINE_FILE
from flakeguard.config import load

ROOT = Path(__file__).parent.parent


def live_cfg(branch):
    cfg = load(ROOT / "flakeguard.toml").model_copy(deep=True)
    cfg.triage.dry_run = False
    cfg.target.scratch_repo = "someone/project"
    cfg.target.scratch_branch = branch
    return cfg


@pytest.mark.parametrize("bad", ["main", "master", "", "MAIN"])
def test_pr_against_a_protected_or_unset_base_raises_before_any_api_call(bad):
    remote = MemoryRemote()
    a = Actions(live_cfg(bad), remote)
    with pytest.raises(RuntimeError, match="scratch_branch"):
        a.open_quarantine_pr("m::t", "body")
    with pytest.raises(RuntimeError, match="scratch_branch"):
        a.open_unquarantine_pr("m::t", "body")
    assert remote.prs == [] and remote.files == {} and remote.branches == {"main": "0" * 40}


def test_pr_targets_the_scratch_branch_and_nothing_lands_on_main():
    remote = MemoryRemote()
    remote.branches["scratch"] = "1" * 40
    a = Actions(live_cfg("scratch"), remote)
    out = a.open_quarantine_pr("m::t", "body")
    pr = remote.prs[0]
    assert out.kind == "quarantine_pr" and pr["base"] == "scratch"
    assert all(b != "main" for (b, _) in remote.files)


def test_hook_and_quarantine_list_are_absent_from_the_main_tree():
    assert not (ROOT / CONFTEST).exists()
    assert not (ROOT / QUARANTINE_FILE).exists()
    assert not (ROOT / "tests" / "scratch_suite").exists()


def test_startup_refuses_live_mode_without_a_valid_scratch_branch():
    from flakeguard import orchestrator as orch

    remote = MemoryRemote()  # has only main
    with pytest.raises(SystemExit, match="scratch_branch"):
        orch.configure(live_cfg("scratch"), remote=remote)
    with pytest.raises(SystemExit, match="scratch_branch"):
        orch.configure(live_cfg("main"), remote=remote)
    remote.branches["scratch"] = "1" * 40
    orch.configure(live_cfg("scratch"), remote=remote)  # ok
