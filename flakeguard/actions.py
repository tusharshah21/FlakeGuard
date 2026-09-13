"""Repository actions. Every write is idempotent and goes to cfg.target.scratch_repo, never to the analysis target.

`Remote` is the handful of GitHub calls we need; `GitHubRemote` is PyGithub, `MemoryRemote` is the in-memory double
the idempotency tests run against. `dry_run` short-circuits every write with a log line.
"""
import re
from dataclasses import dataclass, field

from .config import Config

# Issue titles carry a date-free [REPLAY] prefix: idempotency matches on exact title across days.
TITLE = "[REPLAY] [FlakeGuard] {test_id}"
REVIEW_TITLE = "[REPLAY] [FlakeGuard] Review queue"
OVERRIDE_LABEL = "flakeguard-override"
REPLAY_LABEL = "flakeguard-replay"
SUPERSEDED_LABEL = "flakeguard-superseded"   # an operator closed it to redo, not to disagree; does not block recreation
PROTECTED_BASES = {"main", "master", ""}
QUARANTINE_FILE = ".flakeguard/quarantine.txt"
CONFTEST = "conftest.py"
CONFTEST_HOOK = '''# --- FlakeGuard quarantine hook -------------------------------------------------------------------
# Tests listed in .flakeguard/quarantine.txt (one "module.path[.Class]::name" per line) are marked
# xfail(strict=False): they still run and still report, but cannot fail the suite. FlakeGuard reads their
# outcomes from the JUnit XML and un-quarantines them automatically after sustained passes. Remove a line
# (or apply the flakeguard-override label to the PR) to take a test out of FlakeGuard's hands.
import pathlib

import pytest

_QUARANTINE = pathlib.Path(__file__).parent / ".flakeguard" / "quarantine.txt"


def pytest_collection_modifyitems(config, items):
    if not _QUARANTINE.exists():
        return
    quarantined = {ln.strip() for ln in _QUARANTINE.read_text().splitlines() if ln.strip() and not ln.startswith("#")}
    for item in items:
        cls = f".{item.cls.__name__}" if getattr(item, "cls", None) else ""
        if f"{item.module.__name__}{cls}::{item.name}" in quarantined:
            item.add_marker(pytest.mark.xfail(reason="quarantined by FlakeGuard", strict=False))
# --- end FlakeGuard quarantine hook ---------------------------------------------------------------
'''


def slug(test_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", test_id.lower()).strip("-")[:80]


class Remote:
    """The GitHub surface FlakeGuard needs. Issue/PR objects are plain dicts: {number, title, body, labels, html_url, head}."""

    def open_issues(self) -> list[dict]: ...
    def open_prs(self) -> list[dict]: ...
    def create_issue(self, title: str, body: str, labels: list[str] = ()) -> dict: ...
    def ensure_label(self, name: str, color: str, description: str) -> None: ...
    def comment(self, number: int, body: str) -> str: ...
    def labels_anywhere(self, title: str) -> set[str]: ...  # labels on any open or closed issue/PR with this title
    def closed_titled(self, title: str) -> list[set[str]]: ...  # label sets of closed issues/PRs with exactly this title
    def default_branch(self) -> str: ...
    def head_sha(self, branch: str) -> str: ...
    def create_branch(self, name: str, from_sha: str) -> None: ...
    def get_file(self, path: str, ref: str) -> str | None: ...
    def put_file(self, path: str, content: str, message: str, branch: str) -> None: ...
    def create_pr(self, title: str, body: str, head: str, base: str) -> dict: ...
    def add_labels(self, number: int, labels: list[str]) -> None: ...


@dataclass
class MemoryRemote(Remote):
    issues: list[dict] = field(default_factory=list)
    prs: list[dict] = field(default_factory=list)
    comments: dict[int, list[str]] = field(default_factory=dict)
    files: dict[tuple[str, str], str] = field(default_factory=dict)   # (branch, path) -> content
    branches: dict[str, str] = field(default_factory=lambda: {"main": "0" * 40})
    labels: set[str] = field(default_factory=set)
    _n: int = 0

    def _next(self):
        self._n += 1
        return self._n

    def open_issues(self): return [i for i in self.issues if i["state"] == "open"]
    def open_prs(self): return [p for p in self.prs if p["state"] == "open"]

    def create_issue(self, title, body, labels=()):
        i = {"number": self._next(), "title": title, "body": body, "labels": set(labels), "state": "open"}
        i["html_url"] = f"memory://issues/{i['number']}"
        self.issues.append(i)
        return i

    def ensure_label(self, name, color, description): self.labels.add(name)

    def comment(self, number, body):
        self.comments.setdefault(number, []).append(body)
        return f"memory://comments/{number}/{len(self.comments[number])}"

    def labels_anywhere(self, title):
        return set().union(*(x["labels"] for x in self.issues + self.prs if x["title"] == title), set())

    def closed_titled(self, title):
        return [x["labels"] for x in self.issues + self.prs if x["title"] == title and x["state"] == "closed"]

    def default_branch(self): return "main"

    def head_sha(self, branch):
        if branch not in self.branches:
            raise KeyError(f"branch {branch!r} does not exist")
        return self.branches[branch]

    def create_branch(self, name, from_sha):
        self.branches[name] = from_sha
        src = next((b for b, sha in self.branches.items() if sha == from_sha and b != name), "main")
        for (b, p), c in list(self.files.items()):
            if b == src:
                self.files[(name, p)] = c

    def get_file(self, path, ref): return self.files.get((ref, path))
    def put_file(self, path, content, message, branch): self.files[(branch, path)] = content

    def create_pr(self, title, body, head, base):
        p = {"number": self._next(), "title": title, "body": body, "labels": set(), "state": "open", "head": head, "base": base}
        p["html_url"] = f"memory://pull/{p['number']}"
        self.prs.append(p)
        return p

    def add_labels(self, number, labels):
        for x in self.issues + self.prs:
            if x["number"] == number:
                x["labels"] |= set(labels)


class GitHubRemote(Remote):
    def __init__(self, repo_full_name: str, token: str):
        from github import Github
        self.repo = Github(token).get_repo(repo_full_name)

    @staticmethod
    def _d(x, head=None):
        return {"number": x.number, "title": x.title, "body": x.body or "", "labels": {l.name for l in x.labels},
                "html_url": x.html_url, "state": x.state, "head": head}

    def open_issues(self): return [self._d(i) for i in self.repo.get_issues(state="open") if i.pull_request is None]
    def open_prs(self): return [self._d(p, p.head.ref) for p in self.repo.get_pulls(state="open")]
    def create_issue(self, title, body, labels=()): return self._d(self.repo.create_issue(title=title, body=body, labels=list(labels)))
    def comment(self, number, body): return self.repo.get_issue(number).create_comment(body).html_url

    def ensure_label(self, name, color, description):
        from github import GithubException
        try:
            self.repo.get_label(name)
        except GithubException as e:
            if e.status != 404:
                raise
            self.repo.create_label(name, color, description)

    def labels_anywhere(self, title):
        return set().union(*(self._d(i)["labels"] for i in self.repo.get_issues(state="all") if i.title == title), set())

    def closed_titled(self, title):
        return [{l.name for l in i.labels} for i in self.repo.get_issues(state="closed") if i.title == title]  # PRs are issues here too

    def default_branch(self): return self.repo.default_branch
    def head_sha(self, branch): return self.repo.get_branch(branch).commit.sha
    def create_branch(self, name, from_sha): self.repo.create_git_ref(ref=f"refs/heads/{name}", sha=from_sha)

    def get_file(self, path, ref):
        from github import GithubException
        try:
            return self.repo.get_contents(path, ref=ref).decoded_content.decode()
        except GithubException as e:
            if e.status == 404:
                return None
            raise

    def put_file(self, path, content, message, branch):
        from github import GithubException
        try:
            existing = self.repo.get_contents(path, ref=branch)
            self.repo.update_file(path, message, content, existing.sha, branch=branch)
        except GithubException as e:
            if e.status != 404:
                raise
            self.repo.create_file(path, message, content, branch=branch)

    def create_pr(self, title, body, head, base):
        p = self.repo.create_pull(title=title, body=body, head=head, base=base)
        return self._d(p, head)

    def add_labels(self, number, labels): self.repo.get_issue(number).add_to_labels(*labels)


@dataclass
class Outcome:
    kind: str            # issue | issue_comment | quarantine_pr | unquarantine_pr | review | dry_run | noop
    url: str | None
    detail: str


DISCLAIMER = ("**Agent-generated replay artifact.** FlakeGuard analysed the public CI history of `dask/distributed` and wrote "
              "this here, in its own repository's scratch area; no action of any kind was taken against `dask/distributed`. "
              "Every PR targets the `{branch}` branch, never `main`. The runs and outcomes cited are real.")
CLOCK_NOTE = (" This run used a declared clock (`--as-of {as_of}`): FlakeGuard saw only observations up to that instant. The date "
              "was chosen by the operators knowing what followed, because a recovery window of twenty scheduled runs cannot "
              "otherwise be demonstrated inside a hackathon.")


class Actions:
    def __init__(self, cfg: Config, remote: Remote | None, log=print, as_of: str | None = None, today: str | None = None):
        """Every artifact is a replay artifact: title prefix [REPLAY ...], label flakeguard-replay, first-line disclaimer.
        `as_of` is the declared clock when one was used; `today` is the sweep date otherwise."""
        self.cfg, self.remote, self.log, self.as_of, self.today = cfg, remote, log, as_of, today
        self.dry = cfg.triage.dry_run or remote is None
        self._labels_ready = False

    def _stamp(self, title: str, body: str, span: str | None = None) -> tuple[str, str]:
        date = (self.as_of or self.today or "")[:10]
        label = f"[REPLAY {span or 'as of ' + date}]"
        note = DISCLAIMER.format(branch=self.cfg.target.scratch_branch) + (CLOCK_NOTE.format(as_of=self.as_of[:10]) if self.as_of else "")
        return f"{label} {title}".strip(), f"{label} {note}\n\n{body}"

    def _base(self) -> str:
        """The only branch a PR may target. Raises - never warns, never falls back - on anything protected or unset."""
        base = self.cfg.target.scratch_branch
        if base.lower() in PROTECTED_BASES:
            raise RuntimeError(f"refusing to open a PR against {base!r}: scratch_branch must be a dedicated non-main branch")
        return base

    def _human_closed(self, title: str) -> bool:
        """A closed artifact with this title is a human decision unless an operator labelled it superseded."""
        return any(SUPERSEDED_LABEL not in labels for labels in self.remote.closed_titled(title))

    def _ensure_labels(self):
        if not self._labels_ready:
            self.remote.ensure_label(REPLAY_LABEL, "1d76db", "Agent-generated replay artifact from FlakeGuard; see README")
            self._labels_ready = True

    def _dry(self, what) -> Outcome:
        self.log(f"[dry-run] would {what} in {self.cfg.target.scratch_repo or '<scratch_repo unset>'}")
        return Outcome("dry_run", None, what)

    def overridden(self, test_id: str) -> bool:
        if test_id in self.cfg.overrides.ignore_tests:
            return True
        return not self.dry and OVERRIDE_LABEL in self.remote.labels_anywhere(TITLE.format(test_id=test_id))

    def open_issue(self, test_id: str, body: str) -> Outcome:
        title = TITLE.format(test_id=test_id)
        if self.dry:
            return self._dry(f"open or comment on issue {title!r}")
        existing = next((i for i in self.remote.open_issues() if i["title"] == title), None)
        if existing:
            url = self.remote.comment(existing["number"], body)
            return Outcome("issue_comment", url, f"commented on existing issue #{existing['number']}")
        if self._human_closed(title):
            return Outcome("closed_by_human", None, "a human closed the previous issue; not recreated, disagreement recorded")
        self._ensure_labels()
        i = self.remote.create_issue(title, self._stamp("", body)[1], [REPLAY_LABEL])
        return Outcome("issue", i["html_url"], f"opened issue #{i['number']}")

    def _quarantine_change(self, test_id: str, body: str, add: bool, span: str | None = None) -> Outcome:
        kind = "quarantine_pr" if add else "unquarantine_pr"
        verb = "quarantine" if add else "un-quarantine"
        base = self._base()  # raises before any API call
        branch = f"flakeguard/{verb}/{slug(test_id)}"
        title, body = self._stamp(f"[FlakeGuard] {verb} {test_id}", body, span)
        if self.dry:
            return self._dry(f"open PR {title!r} from {branch} into {base} editing {QUARANTINE_FILE}")
        existing = next((p for p in self.remote.open_prs() if p["head"] == branch), None)
        if existing:
            return Outcome("noop", existing["html_url"], f"PR #{existing['number']} already open for this branch")
        if self._human_closed(title):
            return Outcome("closed_by_human", None, "a human closed the previous PR; not recreated, disagreement recorded")
        assert base == self.cfg.target.scratch_branch and base.lower() not in PROTECTED_BASES
        self.remote.create_branch(branch, self.remote.head_sha(base))
        current = self.remote.get_file(QUARANTINE_FILE, base) or "# Tests quarantined by FlakeGuard. One id per line. Remove a line to un-quarantine.\n"
        lines = [ln for ln in current.splitlines() if ln.strip()]
        if add and test_id not in lines:
            lines.append(test_id)
        if not add:
            lines = [ln for ln in lines if ln != test_id]
        self.remote.put_file(QUARANTINE_FILE, "\n".join(lines) + "\n", f"FlakeGuard: {verb} {test_id}", branch)
        if add and self.remote.get_file(CONFTEST, base) is None:
            self.remote.put_file(CONFTEST, CONFTEST_HOOK, "FlakeGuard: add quarantine hook", branch)
        p = self.remote.create_pr(title, body, branch, base)
        self._ensure_labels()
        self.remote.add_labels(p["number"], [REPLAY_LABEL])
        return Outcome(kind, p["html_url"], f"opened PR #{p['number']} (never merged by FlakeGuard)")

    def open_quarantine_pr(self, test_id: str, body: str) -> Outcome:
        return self._quarantine_change(test_id, body, add=True)

    def open_unquarantine_pr(self, test_id: str, body: str, span: str | None = None) -> Outcome:
        return self._quarantine_change(test_id, body, add=False, span=span)

    def review(self, test_id: str, today: str, body: str) -> Outcome:
        """One shared issue; one comment per (test, day). Mutates no code."""
        if self.dry:
            return self._dry(f"add {test_id} to the review queue issue for {today}")
        marker = f"<!-- flakeguard-review {test_id} {today} -->"
        queue = next((i for i in self.remote.open_issues() if i["title"] == REVIEW_TITLE), None)
        if queue is None:
            self._ensure_labels()
            queue = self.remote.create_issue(REVIEW_TITLE, self._stamp("", "Low-confidence cases FlakeGuard declined to act on. "
                                             "One comment per test per day; nothing here changes code.")[1], [REPLAY_LABEL])
        url = self.remote.comment(queue["number"], f"{marker}\n{body}")
        return Outcome("review", url, f"queued on issue #{queue['number']}")
