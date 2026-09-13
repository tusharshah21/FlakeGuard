import tomllib
from pathlib import Path

from pydantic import BaseModel


class Target(BaseModel):
    repo: str
    scratch_repo: str
    scratch_branch: str
    workflow: str
    source: str
    exclude_cell_prefixes: list[str]
    same_commit_event: str
    same_commit_branch: str


class Ingest(BaseModel):
    days: int
    cache_dir: str
    db_path: str


class Stats(BaseModel):
    z: float
    min_onset_effect: float
    platform_min_fails: int
    platform_top_cell_share: float
    platform_top_os_share: float
    chronic_min_commits: int


class Classify(BaseModel):
    regression_ci_low: float
    flaky_ci_high: float


class Triage(BaseModel):
    window_runs: int
    min_runs: int
    action_threshold: float
    unquarantine_after_passes: int
    dry_run: bool
    recent_failure_days: int
    max_actions_per_sweep: int


class Overrides(BaseModel):
    ignore_tests: list[str]


class Bedrock(BaseModel):
    model_id: str
    region: str


class Config(BaseModel):
    target: Target
    ingest: Ingest
    stats: Stats
    classify: Classify
    triage: Triage
    overrides: Overrides
    bedrock: Bedrock


def load(path: str | Path = "flakeguard.toml") -> Config:
    with open(path, "rb") as f:
        return Config.model_validate(tomllib.load(f))
