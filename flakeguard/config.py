import tomllib
from pathlib import Path

from pydantic import BaseModel


class Target(BaseModel):
    repo: str
    scratch_repo: str
    workflow: str
    source: str
    exclude_cell_prefixes: list[str]
    same_commit_event: str
    same_commit_branch: str


class Ingest(BaseModel):
    days: int
    cache_dir: str
    db_path: str


class Triage(BaseModel):
    window_runs: int
    min_runs: int
    action_threshold: float
    unquarantine_after_passes: int
    dry_run: bool


class Bedrock(BaseModel):
    model_id: str
    region: str


class Config(BaseModel):
    target: Target
    ingest: Ingest
    triage: Triage
    bedrock: Bedrock


def load(path: str | Path = "flakeguard.toml") -> Config:
    with open(path, "rb") as f:
        return Config.model_validate(tomllib.load(f))
