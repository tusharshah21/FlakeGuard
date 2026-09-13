"""The interactive surface: `flakeguard explain <test_id> [question]`.

The deterministic pipeline (orchestrator.triage) runs a fixed sequence because correctness matters there. This
surface does the opposite: a Strands agent is handed the same read-only tools and sequences them itself, calling
them in whatever order and as often as the question needs. It is read-only *by construction* - the action tools
are not in its toolset, so no prompt and no refactor of its instructions can make it write. A test asserts that.
"""
from dataclasses import dataclass

from strands import Agent
from strands.models import BedrockModel

from .config import Config
from .orchestrator import classify_test, correlate_regression, get_commit_context, get_test_health

# Exactly these four, all read-only. Anything that mutates a repository lives in flakeguard.actions and is
# deliberately absent; tests/test_explain.py fails if that ever stops being true.
READ_ONLY_TOOLS = [get_test_health, get_commit_context, classify_test, correlate_regression]

SYSTEM_PROMPT = """You are FlakeGuard's analyst. A maintainer is asking about one test's CI history, and you have
tools that return deterministic statistics computed from real GitHub Actions results.

How to work
- Call the tools you need, in the order the question needs, as many times as it takes. `get_test_health` gives the
  statistics; `classify_test` gives a verdict with its conflicting signals; `get_commit_context` gives the commit
  under investigation; `correlate_regression` asks whether that commit explains the failure. Some questions need
  one tool, some need all four.
- Answer the question that was asked. Do not restate the verdict as if it were the answer: explain WHY the evidence
  points where it does, and say what would change your mind.
- Every number you write must appear in tool output, exactly as it appears there. Do not compute, estimate, round
  differently or convert to percentages. If you want a number you do not have, call a tool.
- Name the evidence that points the other way. If the data cannot settle the question, say so plainly.
- You can read, not act. You never open issues or pull requests; if the maintainer should act, say what and why.

Write four to eight sentences of prose. No headings, no bullet lists."""

DEFAULT_QUESTION = "Why does this test behave the way it does, and what should I take from it?"


@dataclass
class Explanation:
    test_id: str
    question: str
    answer: str
    tool_calls: list[str]        # tool names in the order the model called them
    model_calls: int
    tool_output: str             # everything the tools returned, for the invented-number check


def explain(test_id: str, question: str = DEFAULT_QUESTION, cfg: Config = None, max_calls: int = None) -> Explanation:
    from .config import load
    cfg = cfg or load()
    max_calls = max_calls or cfg.triage.max_explain_model_calls
    agent = Agent(
        model=BedrockModel(model_id=cfg.bedrock.model_id, region_name=cfg.bedrock.region, temperature=0.0),
        system_prompt=SYSTEM_PROMPT, tools=READ_ONLY_TOOLS, callback_handler=None,
    )
    result = agent(f"TEST: {test_id}\n\nQUESTION: {question}")

    # Walk the conversation: which tools ran, what they returned, and how many model turns it took.
    tool_calls, outputs, model_calls = [], [], 0
    for m in agent.messages:
        for block in m.get("content", []) if isinstance(m.get("content"), list) else []:
            if "toolUse" in block:
                tool_calls.append(block["toolUse"]["name"])
            if "toolResult" in block:
                for c in block["toolResult"].get("content", []):
                    if "text" in c:
                        outputs.append(c["text"])
        if m.get("role") == "assistant":
            model_calls += 1
    if model_calls > max_calls:
        raise RuntimeError(f"max_explain_model_calls = {max_calls} exceeded ({model_calls} model turns)")
    return Explanation(test_id, question, str(result).strip(), tool_calls, model_calls, "\n".join(outputs))
