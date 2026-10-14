import subprocess
import sys
from pathlib import Path

import map_maker

SRC = Path(__file__).resolve().parents[1] / "src"


def test_tests_import_this_checkouts_package() -> None:
    assert Path(map_maker.__file__).resolve().parent == SRC / "map_maker"


def test_test_subprocesses_import_this_checkouts_package() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import map_maker; print(map_maker.__file__)"],
        check=True, capture_output=True, text=True,
    )
    assert Path(result.stdout.strip()).resolve().parent == SRC / "map_maker"
