"""Phase 3 eval: baseline vs classifier over every fixture. Prints verdicts, reasoning, agreement, invented numbers.

    uv run scripts/eval_classifier.py [--runs N] [--baseline-only]
"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # model prose may contain non-cp1252 characters on Windows

from flakeguard.baseline import classify as baseline_classify
from flakeguard.config import load
from flakeguard.stats import Thresholds, test_health

cfg = load()
T = Thresholds(**cfg.stats.model_dump())
RUNS = int(sys.argv[sys.argv.index("--runs") + 1]) if "--runs" in sys.argv else 1
BASELINE_ONLY = "--baseline-only" in sys.argv
NUM = re.compile(r"\d+(?:\.\d+)?")


def ok(verdict, expected):
    return verdict in (expected if isinstance(expected, list) else [expected])


def invented(text, evidence):
    """Numbers in the model's prose that do not appear verbatim in the evidence it was given."""
    allowed = set(NUM.findall(evidence))
    return sorted({n for n in NUM.findall(text) if n not in allowed})


fixtures = []
for f in sorted(Path("fixtures").glob("*.json")):
    fx = json.loads(f.read_text(encoding="utf-8"))
    fixtures.append((f.stem, fx["expected_verdict"], test_health(fx["observations"], T),
                     "conflict" if f.stem.startswith(("conflict_", "trap_")) else "primary"))

agent = None
if not BASELINE_ONLY:
    from flakeguard.classifier import classify, make_agent
    agent = make_agent(cfg)

totals = {"primary": [0, 0, 0], "conflict": [0, 0, 0]}  # [cases, baseline_correct, classifier_correct]
invented_total = 0
for run in range(RUNS):
    print(f"\n===== run {run + 1}/{RUNS} =====")
    print(f"{'fixture':55s} {'expected':18s} {'baseline':12s} {'classifier':18s} conf  agree")
    for name, expected, h, group in fixtures:
        b = baseline_classify(h, cfg.classify)
        totals[group][0] += 1
        totals[group][1] += ok(b, expected)
        if BASELINE_ONLY:
            print(f"{name:55s} {str(expected):18s} {b:12s}")
            continue
        c, evidence = classify(h, cfg, agent)
        totals[group][2] += ok(c.verdict, expected)
        bad = invented(" ".join([c.primary_signal, c.conflicting_signals, c.reasoning]), evidence)
        invented_total += len(bad)
        mark = lambda v: "OK " if ok(v, expected) else "WRONG"
        print(f"{name:55s} {str(expected):18s} {b:12s} {c.verdict:18s} {c.confidence:.2f}  {'same' if b == c.verdict else 'DIFF'}   [baseline {mark(b)}] [classifier {mark(c.verdict)}]")
        print(f"    primary:     {c.primary_signal}")
        print(f"    conflicting: {c.conflicting_signals}")
        print(f"    reasoning:   {c.reasoning}")
        if bad:
            print(f"    INVENTED NUMBERS: {bad}")

print("\n===== scores =====")
for group, (n, b, c) in totals.items():
    print(f"{group:9s} cases {n // RUNS}  baseline {b}/{n}  classifier {c}/{n}")
print(f"invented numbers across {RUNS} run(s): {invented_total}")
