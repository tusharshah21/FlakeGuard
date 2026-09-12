"""Ingestion: GitHub Actions runs -> per-cell job conclusions -> JUnit artifacts -> observations. No LLM here."""
import io
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree

from .config import Config
from .github import GitHub
from .storage import Storage


def cell_of(job_name: str) -> str | None:
    """dask's job name is '{os} {env} {task} {partition...}'; the artifact is named with '-' and the partition joined."""
    p = job_name.split(" ")
    return "-".join(p[:3] + ["".join(p[3:])]) if len(p) >= 4 else None


# A test id can appear more than once in one JUnit file (pytest emits a second <testcase> for a teardown error).
# One observation per (run, cell, test) is the contract, so duplicates collapse with this precedence, in this order.
# ponytail: pass-then-teardown-error is usually a resource leak, not flakiness; we collapse it to 'fail' today and
# name that as a known simplification in the README. Split it out if teardown errors ever matter on their own.
PRECEDENCE = ("fail", "pass", "skip")   # a skip never outranks a real outcome; skip-only ids are not observations


def resolve(outcomes: list[str]) -> str:
    return min(outcomes, key=PRECEDENCE.index)


def parse_junit(blob: bytes) -> tuple[list[tuple[str, str]] | None, str | None, Counter]:
    """-> ([(test_id, 'pass'|'fail')], None, collapses) or (None, reason, collapses).
    Skipped testcases are not observations. `collapses` counts duplicate ids by (first_outcome, second_outcome)."""
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
        if tc.find("skipped") is not None:
            o = "skip"
        else:
            o = "fail" if tc.find("failure") is not None or tc.find("error") is not None else "pass"
        seen[f"{tc.get('classname')}::{tc.get('name')}"].append(o)
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
        return c and "-test-" in c and not c.startswith(tuple(t.exclude_cell_prefixes))

    def run_fields(r):
        return {"run_id": r["id"], "head_sha": r["head_sha"], "branch": r["head_branch"],
                "event": r["event"], "started_at": r["run_started_at"]}

    counts, run_cells, obs, collapses = defaultdict(int), [], [], Counter()
    succeeded = defaultdict(list)  # cell -> [(started_at, run, artifact)] for roster sampling
    for r in runs:
        arts = {a["name"]: a for a in gh.artifacts(r["id"]) if not a["expired"]}
        for j in gh.jobs(r["id"]):
            c = cell_of(j["name"])
            if not is_pooled_cell(c):
                continue
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
                rows, why, col = parse_junit(gh.artifact_zip(arts[c]))
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
