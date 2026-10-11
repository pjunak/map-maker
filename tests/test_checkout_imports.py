import subprocess
import sys
from pathlib import Path

import dmtools

SRC = Path(__file__).resolve().parents[1] / "src"


def test_tests_import_this_checkouts_package() -> None:
    assert Path(dmtools.__file__).resolve().parent == SRC / "dmtools"


def test_test_subprocesses_import_this_checkouts_package() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import dmtools; print(dmtools.__file__)"],
        check=True, capture_output=True, text=True,
    )
    assert Path(result.stdout.strip()).resolve().parent == SRC / "dmtools"
