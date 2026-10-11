"""Test this checkout's sources and release closed Tk objects between tests."""

import gc
import os
import sys
from collections.abc import Generator
from pathlib import Path

import pytest

# Worktrees share the main checkout's virtualenv, whose editable install points
# at the main checkout's src. Put this checkout's src first, in-process and for
# test subprocesses (PYTHONPATH precedes site-packages), so every run tests the
# code beside these tests.
SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)
os.environ["PYTHONPATH"] = os.pathsep.join(
    path for path in (SRC, os.environ.get("PYTHONPATH")) if path
)


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_protocol(item: pytest.Item) -> Generator[None, bool | None, bool | None]:
    try:
        return (yield)
    finally:
        if item.path.stem.endswith(("_ui", "_workbench")):
            # Fixture teardown alone is too early: pytest still owns funcargs.
            # Once the protocol returns those references are released. Collect
            # on this UI thread so a later worker cannot finalize old Tk vars
            # against a destroyed interpreter while root.update() drives tests.
            gc.collect()
