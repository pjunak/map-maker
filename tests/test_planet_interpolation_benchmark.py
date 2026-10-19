# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
"""The curved-interpolation benchmark (T22) scores what it says it scores."""

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
import rasterio
from affine import Affine
from numpy.typing import NDArray

from benchmarks.planet.interpolation import (
    CURVED,
    LinearSampler,
    Truth,
    Window,
    WindowScores,
    dem_truth,
    evaluate,
    planet_windows,
    rules,
)
from map_maker.terrain.pipeline.planet_mesh import SphereMesh, build_mesh
from map_maker.terrain.pipeline.planet_patch import forward_aeqd

type F64 = NDArray[np.float64]

RADIUS_M = 1_000_000.0
WINDOW = Window("test", 20.0, 35.0)
WINDOW_RADIUS_M = 150e3
LAND_RADIUS_M = 400e3  # beyond the cubics' reach: sea at 0 bends them inland


@pytest.fixture(scope="module")
def mesh() -> SphereMesh:
    return build_mesh(20_000, RADIUS_M, 11)  # about 25 km spacing


def analytic(field: Callable[[F64, F64], F64]) -> Truth:
    """A truth given in the window's plane: land within LAND_RADIUS_M of its centre."""

    def sample(xyz: F64) -> tuple[F64, NDArray[np.bool_]]:
        x, y = forward_aeqd(xyz, WINDOW.lon, WINDOW.lat, RADIUS_M).T
        land = np.hypot(x, y) < LAND_RADIUS_M
        return np.where(land, field(x, y), 0.0), land

    return Truth(RADIUS_M, sample, {"kind": "analytic"})


def scores(mesh: SphereMesh, truth: Truth) -> WindowScores:
    result = evaluate(truth, mesh, LinearSampler(mesh), WINDOW, window_radius_m=WINDOW_RADIUS_M)
    assert result is not None
    return result


def test_smooth_relief_is_rebuilt_better_and_without_creases_by_cubics(
    mesh: SphereMesh,
) -> None:
    wave = 2 * np.pi / 120e3  # five mesh spacings: the mesh resolves it

    def hills(x: F64, y: F64) -> F64:
        return 1500.0 + 800.0 * np.sin(wave * x) * np.cos(wave * y)

    result = scores(mesh, analytic(hills))
    truth, linear, cubic = result.truth, result.variants["linear"], result.variants["cubic"]
    # Smooth ground has no creases at coarse edges and few straight contours;
    # a linear rebuild creases at every edge and is flat inside each triangle.
    assert 0.8 < truth["crease_ratio"] < 1.25
    assert linear["crease_ratio"] > 3.0
    assert cubic["crease_ratio"] < 0.5 * linear["crease_ratio"]
    assert truth["straight_contour_share"] < 0.2
    assert linear["straight_contour_share"] > 3 * truth["straight_contour_share"]
    assert cubic["straight_contour_share"] < 0.5 * linear["straight_contour_share"]
    assert cubic["height_rmse_m"] < 0.6 * linear["height_rmse_m"]
    assert cubic["shade_correlation"] > linear["shade_correlation"]
    # A linear rebuild never leaves its triangle's corner values; the clipped cubic
    # neither. Smooth hills do rise above them between nodes, as free cubics may.
    assert linear["overshoot_max_m"] < 1e-6
    assert cubic["overshoot_max_m"] < 1e-6
    assert truth["overshoot_max_m"] > 50.0
    assert "overshoot_max_m" not in result.variants["twist"]
    verdict = rules([result])
    assert set(verdict) == set(CURVED)
    assert verdict["cubic"]["fewer_mesh_lines"] is True
    assert verdict["cubic"]["controls_keep_straight_ridges"] is None


def test_a_tilted_plane_is_rebuilt_exactly_with_straight_contours(mesh: SphereMesh) -> None:
    result = scores(mesh, analytic(lambda x, y: 3000.0 + 0.01 * x - 0.004 * y))
    assert result.truth["straight_contour_share"] == 1.0
    for name in ("linear", "cubic", "cubic-free"):
        assert result.variants[name]["height_rmse_m"] < 0.5
        assert result.variants[name]["straight_contour_share"] > 0.99


def test_scores_repeat_exactly(mesh: SphereMesh) -> None:
    def ridge(x: F64, y: F64) -> F64:
        return 900.0 + 600.0 * np.exp(-((x - 0.4 * y) / 40e3) ** 2)

    assert scores(mesh, analytic(ridge)).as_json() == scores(mesh, analytic(ridge)).as_json()


def test_dem_heights_are_read_at_pixel_centres(tmp_path: Path) -> None:
    step = 0.1
    lon = -10 + step * (np.arange(200) + 0.5)
    lat = 10 - step * (np.arange(200) + 0.5)
    grid_lon, grid_lat = np.meshgrid(lon, lat)
    path = tmp_path / "dem.tif"
    with rasterio.open(
        path, "w", driver="GTiff", width=200, height=200, count=1, dtype="float32",
        crs="EPSG:4326", transform=Affine(step, 0, -10, 0, -step, 10),
    ) as dataset:
        dataset.write((20 * grid_lon + 10 * grid_lat).astype(np.float32), 1)
    truth, windows = dem_truth(path)
    assert truth.radius_m == 6_371_000.0 and windows
    q_lon, q_lat = np.radians([3.37, -4.21, 0.05]), np.radians([2.5, -6.04, 1.0])
    xyz = np.stack(
        (np.cos(q_lat) * np.cos(q_lon), np.cos(q_lat) * np.sin(q_lon), np.sin(q_lat)), axis=1
    )
    height, land = truth.sample(xyz)
    want = 20 * np.degrees(q_lon) + 10 * np.degrees(q_lat)
    assert np.allclose(height, np.maximum(want, 0.0), atol=1e-3)
    assert land.tolist() == (want > 0).tolist()


def test_planet_windows_start_on_the_highest_inland_ground_and_do_not_overlap(
    mesh: SphereMesh,
) -> None:
    land = mesh.xyz[:, 2] > -0.2
    coast = np.where(land, 1e6, 0.0)
    height = np.where(land, 1000 + 500 * mesh.xyz[:, 0], 0.0)
    windows = planet_windows(mesh, land, coast, height, count=4)
    first = mesh.xyz[np.argmax(np.where(land, height, -1))]
    assert np.degrees(np.arctan2(first[1], first[0])) == pytest.approx(windows[0].lon, abs=1e-3)
    centres = np.array([
        [np.cos(np.radians(w.lat)) * np.cos(np.radians(w.lon)),
         np.cos(np.radians(w.lat)) * np.sin(np.radians(w.lon)),
         np.sin(np.radians(w.lat))]
        for w in windows
    ])
    angles = np.arccos(np.clip(centres @ centres.T, -1, 1))[np.triu_indices(len(windows), 1)]
    assert len(windows) == 4
    assert (angles * RADIUS_M >= 2 * 600e3).all()
