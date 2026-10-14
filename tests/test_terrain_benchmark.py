import json
import subprocess
import sys
from pathlib import Path

import pytest

from benchmarks.terrain import DEFAULT_CASES, ROOT, fixture, peak_resident_bytes
from map_maker.terrain.domain import ElevationPoint, TerrainBasin


def test_benchmark_report_is_repeatable_and_measures_native_process_memory(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmarks.terrain",
            "--case",
            "archipelago",
            "regional",
            "--resolution",
            "64",
            "--seed",
            "42",
            "--repeats",
            "2",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["complete"] is True
    assert report["method"]["fresh_process_per_run"] is True
    first, second, regional_first, regional_second = report["runs"]
    for a, b in ((first, second), (regional_first, regional_second)):
        for key in ("input_sha256", "output_sha256", "drainage", "routing_agreement", "quality"):
            assert a[key] == b[key]
        assert "routing_incision_limit" in a["output_sha256"]
    assert regional_first["case"] == "regional"
    assert regional_first["constraint_count"] == 4
    assert first["boundary_vertices"] == 960
    assert 0.0 < first["land_fraction"] < 1.0
    assert first["generation_cpu_seconds"] > 0.0
    assert first["generation_stages_seconds"]["Building elevation field"] > 0.0
    assert first["worker_wall_seconds"] > first["generation_seconds"]
    if sys.platform in ("win32", "linux", "darwin"):
        assert first["generation_process_peak_bytes"] > 0
        assert first["products_process_peak_bytes"] >= first["generation_process_peak_bytes"]


def test_benchmark_refuses_to_overwrite_existing_output(tmp_path: Path) -> None:
    output = tmp_path / "existing.json"
    output.write_text("keep this", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmarks.terrain",
            "--case",
            "square",
            "--resolution",
            "64",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert output.read_text(encoding="utf-8") == "keep this"


def test_benchmark_fixture_identity_preserves_explicit_parameters() -> None:
    coast, settings, constraints = fixture("authored", 65, 17)
    assert settings.seed == 17
    assert settings.resolution_px == 65
    assert coast.boundary_point_count == 4
    assert len(constraints) == 5
    with pytest.raises(ValueError, match="Unknown benchmark case"):
        fixture("unknown", 65, 17)


def test_peak_memory_is_unavailable_or_a_positive_byte_count() -> None:
    peak = peak_resident_bytes()
    assert peak is None or peak > 0


@pytest.mark.parametrize("case,lakes,points,radius", [
    ("lakes_small", 4, 16, 12.), ("lakes", 16, 64, 12.), ("lakes_broad", 16, 64, 2000.),
])
def test_scaling_fixtures_are_explicit_repeatable_and_opt_in(
    case: str, lakes: int, points: int, radius: float,
) -> None:
    first = fixture(case, 65, 17)
    assert first == fixture(case, 65, 17) and case not in DEFAULT_CASES
    _, settings, constraints = first
    assert settings.resolution_px == 65 and settings.seed == 17
    basins = [c for c in constraints if isinstance(c, TerrainBasin)]
    anchors = [c for c in constraints if isinstance(c, ElevationPoint)]
    assert len(basins) == lakes and sum(b.outlet is not None for b in basins) == lakes // 2
    assert len(anchors) == points and all(p.influence_radius_km == radius for p in anchors)
