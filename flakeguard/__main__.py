"""uv run python -m flakeguard ingest"""
import sys

from .config import load
from .github import GitHub
from .ingest import ingest
from .storage import Storage

cfg = load()
cmd = sys.argv[1] if len(sys.argv) > 1 else "ingest"
if cmd == "ingest":
    ingest(cfg, Storage(cfg.ingest.db_path), GitHub(cfg.target.repo, cfg.ingest.cache_dir))
else:
    sys.exit(f"unknown command {cmd!r}")
