"""The explain surface is read-only by construction, not by instruction."""
import inspect
from pathlib import Path

import flakeguard.actions as actions
from flakeguard.explain import READ_ONLY_TOOLS, SYSTEM_PROMPT, explain

ROOT = Path(__file__).parent.parent
READ_ONLY_NAMES = {"get_test_health", "get_commit_context", "classify_test", "correlate_regression"}


def tool_name(t):
    return getattr(t, "tool_name", None) or getattr(t, "__name__", str(t))


def test_toolset_is_exactly_the_four_read_only_tools():
    assert {tool_name(t) for t in READ_ONLY_TOOLS} == READ_ONLY_NAMES


def test_no_action_tool_can_reach_the_explain_agent():
    """A later refactor must not be able to slip a writing tool in here."""
    writing = {n for n, _ in inspect.getmembers(actions.Actions, inspect.isfunction)
               if n in {"open_issue", "open_quarantine_pr", "open_unquarantine_pr", "review"}}
    assert writing, "expected to find the action methods"
    for t in READ_ONLY_TOOLS:
        name = tool_name(t)
        assert name in READ_ONLY_NAMES
        src = inspect.getsource(inspect.unwrap(getattr(t, "_tool_func", None) or t.__wrapped__ if hasattr(t, "__wrapped__") else t)) \
            if not hasattr(t, "original_function") else inspect.getsource(t.original_function)
        for w in writing:
            assert w not in src, f"{name} references the action method {w}"


def test_explain_module_never_imports_the_action_layer():
    src = (ROOT / "flakeguard" / "explain.py").read_text(encoding="utf-8")
    assert "from .actions" not in src and "import actions" not in src
    assert " act(" not in src and "sweep(" not in src
    assert "You can read, not act" in SYSTEM_PROMPT


def test_explain_signature_has_a_call_ceiling():
    params = inspect.signature(explain).parameters
    assert "max_calls" in params
