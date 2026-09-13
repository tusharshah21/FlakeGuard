"""Thin GitHub Actions client. Every response that can be cached is cached on disk; parsing never re-downloads."""
import json
import os
from pathlib import Path

import requests


class GitHub:
    def __init__(self, repo: str, cache_dir: str, token: str | None = None):
        self.api = f"https://api.github.com/repos/{repo}"
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {token or os.environ['GITHUB_TOKEN']}",
            "Accept": "application/vnd.github+json",
        })
        self.requests_used = 0

    def _get(self, url, **params):
        r = self.s.get(url if url.startswith("http") else f"{self.api}{url}", params=params, timeout=60)
        self.requests_used += 1
        r.raise_for_status()
        return r

    def _cached_json(self, name, url, key):
        f = self.cache / name
        if not f.exists():
            f.write_text(json.dumps(self._get(url, per_page=100).json()[key]), encoding="utf-8")
        return json.loads(f.read_text(encoding="utf-8"))

    def workflow_runs(self, workflow: str, since: str, **filters) -> list[dict]:
        """Completed runs of one workflow created on/after `since` (YYYY-MM-DD). Not cached: the list grows daily."""
        runs, page = [], 1
        while True:
            batch = self._get(f"/actions/workflows/{workflow}/runs", per_page=100, page=page,
                              created=f">={since}", **filters).json()["workflow_runs"]
            if not batch:
                return sorted(runs, key=lambda r: r["run_started_at"])
            runs += [r for r in batch if r["status"] == "completed"]
            page += 1

    def jobs(self, run_id: int) -> list[dict]:
        return self._cached_json(f"jobs_{run_id}.json", f"/actions/runs/{run_id}/jobs", "jobs")

    def artifacts(self, run_id: int) -> list[dict]:
        return self._cached_json(f"run_{run_id}.json", f"/actions/runs/{run_id}/artifacts", "artifacts")

    def commit(self, sha: str) -> dict:
        """Commit metadata and changed files, cached. Only ever called with a sha derived from the failure data."""
        f = self.cache / f"commit_{sha}.json"
        if not f.exists():
            c = self._get(f"/commits/{sha}").json()
            f.write_text(json.dumps({
                "sha": c["sha"], "message": c["commit"]["message"], "date": c["commit"]["author"]["date"],
                "files": [{k: x.get(k) for k in ("filename", "status", "additions", "deletions")} for x in c.get("files", [])],
            }), encoding="utf-8")
        return json.loads(f.read_text(encoding="utf-8"))

    def artifact_zip(self, artifact: dict) -> bytes:
        f = self.cache / f"{artifact['id']}.zip"
        if not f.exists():
            f.write_bytes(self._get(artifact["archive_download_url"]).content)
        return f.read_bytes()
