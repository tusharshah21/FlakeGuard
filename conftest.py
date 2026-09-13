# --- FlakeGuard quarantine hook -------------------------------------------------------------------
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
