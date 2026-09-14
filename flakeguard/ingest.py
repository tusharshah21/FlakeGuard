"""Ingestion: GitHub Actions runs -> per-cell job conclusions -> JUnit artifacts -> observations. No LLM here."""
import io
import re
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from xml.etree import ElementTree

from .config import Config, Target
from .github import GitHub
from .storage import Storage


class CellPatternError(ValueError):
    """The configured cell_pattern did not match any job in the workflow. Ingestion would silently find nothing."""


@lru_cache(maxsize=8)
def _compiled(pattern: str) -> re.Pattern:
    rx = re.compile(pattern)
    if "cell" not in rx.groupindex:
        raise CellPatternError(f"cell_pattern must contain a named group (?P<cell>...): {pattern!r}")
    return rx


def cell_of(job_name: str, t: Target) -> str | None:
    """Map a GitHub job name onto the matrix cell it belongs to, which is also its artifact name.

    Every repository names matrix jobs differently, so the mapping is `[target] cell_pattern` in flakeguard.toml
    rather than code. The named group `cell` is the result; any other named groups are joined with cell_join, which
    is how dask's four-part name ("ubuntu-latest py312 test-ci not ci1") collapses onto its artifact
    ("ubuntu-latest-py312-test-ci-notci1"). Returns None for jobs that are not matrix cells at all.
    """
    m = _compiled(t.cell_pattern).match(job_name)
    if not m:
        return None
    groups = m.groupdict()
    # The `cell` group keeps its words, joined by cell_join. Any further named groups are suffixes whose internal
    # spaces are dropped entirely, which is how dask's "not ci1" becomes "notci1".
    parts = [t.cell_join.join(groups.pop("cell").split())]
    parts += ["".join(v.split()) for v in groups.values() if v]
    cell = t.cell_join.join(parts)
    return cell if t.cell_filter in cell else None


# A test id can appear more than once in one JUnit file (pytest emits a second <testcase> for a teardown error).
# One observation per (run, cell, test) is the contract, so duplicates collapse with this precedence, in this order.
# ponytail: pass-then-teardown-error is usually a resource leak, not flakiness; we collapse it to 'fail' today and
# name that as a known simplification in the README. Split it out if teardown errors ever matter on their own.
PRECEDENCE = ("fail", "pass", "skip")   # a skip never outranks a real outcome; skip-only ids are not observations


def resolve(outcomes: list[str]) -> str:
    return min(outcomes, key=PRECEDENCE.index)


def parse_junit(blob: bytes, quarantined: frozenset[str] = frozenset()) -> tuple[list[tuple[str, str]] | None, str | None, Counter]:
    """-> ([(test_id, 'pass'|'fail')], None, collapses) or (None, reason, collapses).
    Skipped testcases are not observations, with one exception: a quarantined test is marked xfail(strict=False) by the
    FlakeGuard conftest hook, and pytest reports its failure as <skipped type="pytest.xfail">. For tests in
    `quarantined` that counts as a failure, so the un-quarantine loop sees real outcomes. Legitimate xfails elsewhere are
    untouched. `collapses` counts duplicate ids by (first_outcome, second_outcome)."""
    collapses = Counter()
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
        xmls = [n for n in z.namelist() if n.endswith(".xml")]
        if not xmls:
            return None, "no xml in zip", collapses
        root = ElementTree.fromstring(z.read(xmls[0]))
    except zipfile.BadZipFile:
        return None, "bad zip", collapses
    except ElementTree.ParseError:
        return None, "xml parse error", collapses
    if root.find(".//testsuite") is None:
        return None, "no testsuite element", collapses
    seen = defaultdict(list)
    for tc in root.iter("testcase"):
        tid = f"{tc.get('classname')}::{tc.get('name')}"
        skipped = tc.find("skipped")
        if skipped is not None:
            o = "fail" if tid in quarantined and (skipped.get("type") or "").endswith("xfail") else "skip"
        else:
            o = "fail" if tc.find("failure") is not None or tc.find("error") is not None else "pass"
        seen[tid].append(o)
    for outcomes in seen.values():
        for a, b in zip(outcomes, outcomes[1:]):
            collapses[(a, b)] += 1
    rows = [(tid, o) for tid, outcomes in seen.items() if (o := resolve(outcomes)) != "skip"]
    return (rows, None, collapses) if rows else (None, "zero testcases", collapses)


def ingest(cfg: Config, store: Storage, gh: GitHub, log=print) -> dict:
    t = cfg.target
    since = (datetime.now(timezone.utc) - timedelta(days=cfg.ingest.days)).strftime("%Y-%m-%d")
    runs = gh.workflow_runs(t.workflow, since, event=t.same_commit_event, branch=t.same_commit_branch)
    log(f"{len(runs)} completed {t.same_commit_event} runs of {t.workflow} on {t.same_commit_branch} since {since}")

    def is_pooled_cell(c):
        return c is not None and not c.startswith(tuple(t.exclude_cell_prefixes))

    def run_fields(r):
        return {"run_id": r["id"], "head_sha": r["head_sha"], "branch": r["head_branch"],
                "event": r["event"], "started_at": r["run_started_at"]}

    matched_any = False
    counts, run_cells, obs, collapses = defaultdict(int), [], [], Counter()
    quarantined = frozenset(t for t, _ in store.quarantined_tests())
    succeeded = defaultdict(list)  # cell -> [(started_at, run, artifact)] for roster sampling
    for r in runs:
        arts = {a["name"]: a for a in gh.artifacts(r["id"]) if not a["expired"]}
        for j in gh.jobs(r["id"]):
            c = cell_of(j["name"], t)
            if not is_pooled_cell(c):
                continue
            matched_any = True
            rc = {**run_fields(r), "cell": c, "job_conclusion": j["conclusion"]}
            if j["conclusion"] == "success":
                rc["status"] = "roster"
                if c in arts:
                    succeeded[c].append((r["run_started_at"], r, arts[c]))
            elif j["conclusion"] != "failure":
                rc["status"] = "skipped"  # cancelled etc.: neither numerator nor denominator
            elif c not in arts:
                rc["status"] = "unresolved"
            else:
                rows, why, col = parse_junit(gh.artifact_zip(arts[c]), quarantined)
                collapses += col
                if why:
                    rc["status"] = "unresolved"
                    counts[f"parse:{why}"] += 1
                elif not any(o == "fail" for _, o in rows):
                    rc["status"] = "infra"
                else:
                    rc["status"] = "parsed"
                    obs += [{**run_fields(r), "cell": c, "test_id": tid, "outcome": o, "source": "artifact"} for tid, o in rows]
            counts[rc["status"]] += 1
            run_cells.append(rc)
    if runs and not matched_any:
        raise CellPatternError(
            f"[target] cell_pattern {t.cell_pattern!r} matched no job in {t.workflow}, so there is nothing to ingest. "
            f"Check a job name with: gh api repos/{t.repo}/actions/runs/<id>/jobs --jq '.jobs[].name'")
    store.upsert_run_cells(run_cells)
    store.upsert_observations(obs)
    log(f"run-cells: {dict(counts)}; artifact observations: {len(obs)}; duplicate testcase collapses: {dict(collapses)}")

    # rosters: oldest, middle and newest passing artifact per cell (drift over 89 days is <= 6 tests added, 0 removed)
    for c, items in succeeded.items():
        items.sort(key=lambda x: x[0])
        for i in sorted({0, len(items) // 2, len(items) - 1}):
            started_at, r, a = items[i]
            rows, why, _ = parse_junit(gh.artifact_zip(a))
            if why:
                counts[f"roster-parse:{why}"] += 1
                continue
            store.upsert_roster(c, started_at, r["id"], {tid for tid, o in rows if o == "pass"})
    log(f"rosters: {store.count('rosters')} rows over {len(succeeded)} cells; requests used: {gh.requests_used}")
    return dict(counts)
