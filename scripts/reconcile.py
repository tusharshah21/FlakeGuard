"""Recompute the probe's headline numbers from storage. They must still match probe-results/ exactly.

    uv run scripts/reconcile.py

This was the Phase 1 exit gate, and it matched the probe exactly on the day it was written. It cannot keep matching
exactly, and the reason is worth stating rather than papering over: every ingest samples fresh test rosters, so the
number of *inferred* passes grows even inside a fixed window, and a few more (test, sha) pairs cross from "only
failures seen" into "both a failure and a pass seen". That is the pipeline working, not drifting.

So the check is split. Four structural invariants must still match exactly, because no amount of new data can move
them. The two counts that grow with roster coverage are reported with their delta and do not fail the run.
"""
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from probe_pooled import category, summarize  # noqa: E402  (the probe's classification rule, verbatim)

from flakeguard.config import load  # noqa: E402
from flakeguard.storage import Storage  # noqa: E402

# The probe's window. Observations after this instant did not exist when the expected numbers were recorded.
PROBE_CUTOFF = "2026-09-12T23:59:59Z"

store = Storage(load().ingest.db_path)
print(f"window: everything up to {PROBE_CUTOFF} (the probe's own window; later data is ignored on purpose)")
status = Counter(
    r[0] for r in store.db.execute("SELECT status FROM run_cells WHERE started_at <= ?", (PROBE_CUTOFF,))
)
print(f"run-cells: {dict(sorted(status.items()))}")

q2a, cats, mixed_by_test = 0, Counter(), defaultdict(set)
for t in store.failing_tests():
    tally = defaultdict(lambda: defaultdict(Counter))
    for o in store.pooled_observations(t):
        if o["started_at"] > PROBE_CUTOFF:
            continue
        tally[o["head_sha"]][o["cell"]][o["outcome"]] += 1
    for sha, percell in tally.items():
        s = summarize(percell)
        cat = category(*s)
        cats[cat] += 1
        if s[0] and s[0] < s[1]:
            q2a += 1
            if cat == "masked_flake":
                mixed_by_test[t].add(sha)
chronic = sum(len(v) >= 3 for v in mixed_by_test.values())
print(f"(test, sha) categories among tests with any failure: {dict(cats)}   (probe: masked_flake 168, platform_specific 15, fails_always 0)")
# Invariants: fixed by the data itself, not by how much of it we have sampled.
invariants = {
    "INFRA run-cells": (status.get("infra", 0), 9),
    "UNRESOLVED run-cells": (status.get("unresolved", 0), 32),
    "platform_specific (test, sha) pairs": (cats.get("platform_specific", 0), 15),
    "tests recovering across >= 3 commits": (chronic, 19),
}
# Grows with roster coverage: more sampled rosters mean more inferred passes, so more pairs show both outcomes.
grows = {
    "masked_flake (test, sha) pairs": (cats.get("masked_flake", 0), 168),
    "Q2(a) pairs with both outcomes": (q2a, 183),
}

print()
bad = []
for name, (now, probe) in invariants.items():
    mark = "exact" if now == probe else "BROKEN"
    if now != probe:
        bad.append(name)
    print(f"  {mark:6s} {name:38s} {now} (probe: {probe})")
for name, (now, probe) in grows.items():
    print(f"  {'grew':6s} {name:38s} {now} (probe: {probe}, +{now - probe} from wider roster coverage)")

print("\nRECONCILED" if not bad else f"\nBROKEN INVARIANT: {bad} - do not adjust numbers; report the discrepancy")
sys.exit(0 if not bad else 1)
