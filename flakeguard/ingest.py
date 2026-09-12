"""Ingestion: GitHub Actions runs -> per-cell job conclusions -> JUnit artifacts -> observations. No LLM here."""
import io
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree

from .config import Config
from .github import GitHub
from .storage import Storage


def cell_of(job_name: str) -> str | None:
    """dask's job name is '{os} {env} {task} {partition...}'; the artifact is named with '-' and the partition joined."""
    p = job_name.split(" ")
    return "-".join(p[:3] + ["".join(p[3:])]) if len(p) >= 4 else None


def parse_junit(blob: bytes) -> tuple[list[tuple[str, str]] | None, str | None]:
    """-> ([(test_id, 'pass'|'fail')], None) or (None, reason). Skipped testcases are not observations."""
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
        xmls = [n for n in z.namelist() if n.endswith(".xml")]
        if not xmls:
            return None, "no xml in zip"
        root = ElementTree.fromstring(z.read(xmls[0]))
    except zipfile.BadZipFile:
        return None, "bad zip"
    except ElementTree.ParseError:
        return None, "xml parse error"
    if root.find(".//testsuite") is None:
        return None, "no testsuite element"
    rows = []
    for tc in root.iter("testcase"):
        if tc.find("skipped") is not None:
            continue
        failed = tc.find("failure") is not None or tc.find("error") is not None
        rows.append((f"{tc.get('classname')}::{tc.get('name')}", "fail" if failed else "pass"))
    return (rows, None) if rows else (None, "zero testcases")


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

    counts, run_cells, obs = defaultdict(int), [], []
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
                rows, why = parse_junit(gh.artifact_zip(arts[c]))
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
    log(f"run-cells: {dict(counts)}; artifact observations: {len(obs)}")

    # rosters: oldest, middle and newest passing artifact per cell (drift over 89 days is <= 6 tests added, 0 removed)
    for c, items in succeeded.items():
        items.sort(key=lambda x: x[0])
        for i in sorted({0, len(items) // 2, len(items) - 1}):
            started_at, r, a = items[i]
            rows, why = parse_junit(gh.artifact_zip(a))
            if why:
                counts[f"roster-parse:{why}"] += 1
                continue
            store.upsert_roster(c, started_at, r["id"], {tid for tid, o in rows if o == "pass"})
    log(f"rosters: {store.count('rosters')} rows over {len(succeeded)} cells; requests used: {gh.requests_used}")
    return dict(counts)
