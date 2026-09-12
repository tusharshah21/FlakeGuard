"""Phase 1 exit check: recompute the probe's headline numbers from storage. Must match probe-results/ exactly.

    uv run scripts/reconcile.py
"""
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from probe_pooled import category, summarize  # noqa: E402  (the probe's classification rule, verbatim)

from flakeguard.config import load  # noqa: E402
from flakeguard.storage import Storage  # noqa: E402

store = Storage(load().ingest.db_path)
status = store.run_cell_status_counts()
print(f"run-cells: {status}")
print(f"  INFRA ........ {status.get('infra', 0)}   (probe: 9)")
print(f"  UNRESOLVED ... {status.get('unresolved', 0)}   (probe: 32)")

q2a, cats, mixed_by_test = 0, Counter(), defaultdict(set)
for t in store.failing_tests():
    tally = defaultdict(lambda: defaultdict(Counter))
    for o in store.pooled_observations(t):
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
print(f"  Q2(a) ........ {q2a}   (probe: 183)")
print(f"  Q2(b) ........ {chronic}   (probe: 19)")
ok = (status.get("infra"), status.get("unresolved"), q2a, chronic) == (9, 32, 183, 19)
print("\nRECONCILED" if ok else "\nMISMATCH - do not adjust numbers; report the discrepancy")
sys.exit(0 if ok else 1)
