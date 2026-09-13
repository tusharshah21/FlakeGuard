"""Invented-number check over the explain surface: every numeric token in the model's prose must appear in tool output.

    uv run scripts/eval_explain.py
"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent.parent))

from flakeguard.config import load  # noqa: E402
from flakeguard.explain import explain  # noqa: E402
from flakeguard.orchestrator import configure  # noqa: E402

NUM = re.compile(r"\d+(?:\.\d+)?")
CASES = [
    ("distributed.tests.test_gc::test_gc_diagnosis_cpu_time", "Why does this fail only on Windows?"),
    ("distributed.tests.test_jupyter::test_shutdowns_cleanly", "Why is this flaky rather than broken?"),
    ("distributed.shuffle.tests.test_shuffle::test_restarting_during_transfer_raises_killed_worker", "Why is this one cell and not the others?"),
    ("distributed.tests.test_nanny::test_failure_during_worker_initialization", "What changed around the dates this started failing?"),
    ("fixtures/conflict_platform_pr_test_bad_executable.json", "What was the conflicting evidence and do you agree?"),
]

cfg = load()
total_invented = 0
for target, question in CASES:
    fixtures = [target] if target.endswith(".json") else []
    configure(cfg, fixtures, force_dry=True, log=lambda *_: None)
    test_id = json.loads(Path(target).read_text(encoding="utf-8"))["test_id"] if fixtures else target
    e = explain(test_id, question, cfg)
    allowed = set(NUM.findall(e.tool_output)) | set(NUM.findall(question))
    invented = sorted({n for n in NUM.findall(e.answer) if n not in allowed})
    total_invented += len(invented)
    print(f"{test_id.split('::')[-1]:48s} tools={len(e.tool_calls)} turns={e.model_calls} invented={invented or 'none'}")
    for n in invented:   # show the claim, not just the token: a bare number says nothing about whether it misleads
        for sent in re.split(r"(?<=[.])\s+", e.answer):
            if re.search(rf"(?<![\d.]){re.escape(n)}(?![\d])", sent):
                print(f"      {n!r}: {sent.strip()[:190]}")
                break
print(f"\ninvented numbers across {len(CASES)} explains: {total_invented}")
