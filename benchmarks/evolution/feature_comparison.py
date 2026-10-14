"""Reopen prepared features and compare actual queries with the rejected raster."""

import argparse
from dataclasses import asdict, replace
from hashlib import sha256
from html import escape
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
from numpy.typing import NDArray

from benchmarks.evolution.boundary_comparison import dense_banks
from benchmarks.evolution.boundary_report import render_sections
from benchmarks.evolution.evidence import identity, numeric_hash, write_json
from benchmarks.evolution.feature_archive import read_feature_surface, write_feature_surface
from benchmarks.evolution.feature_surface import FEATURE_MODEL_ID, FeatureSurface
from benchmarks.evolution.network_comparison import routing
from benchmarks.evolution.network_fixture import FIXTURE_ID, NetworkFixture, fixture
from benchmarks.evolution.network_report import render_routes
from benchmarks.evolution.patch_comparison import inspect_surface
from benchmarks.evolution.valley_layout import relocate_guides
from benchmarks.evolution.valley_patches import PatchSettings, prepare_patches
from benchmarks.evolution.valley_support import prepare_support
from benchmarks.terrain import peak_resident_bytes
from map_maker.terrain.adapters.build import canonical_json, file_sha256


def parent_identity(f: NetworkFixture) -> str:
    """Identity of this fixture's inputs before automatic guide placement."""
    return sha256(
        canonical_json(
            {
                "fixture": FIXTURE_ID,
                "grid": asdict(f.source.grid),
                "source": numeric_hash(f.source.ground_m),
                "network": f.network.identity(),
                "limits": numeric_hash(f.limits_m),
                "hard_points": numeric_hash(f.hard.points_m),
                "hard_heights": numeric_hash(f.hard.heights_m),
                "protected_bounds_km": f.protected_divide_km.bounds,
            }
        )
    ).hexdigest()


def query_checks(surface: FeatureSurface) -> dict[str, Any]:
    """Overlaps sample the same immutable surface; this does not generate new detail."""
    rng = np.random.default_rng(874)
    xy = rng.random((2048, 2)) * (surface.grid.width_m, surface.grid.height_m)
    whole = surface.sample(*xy.T)
    order = rng.permutation(len(xy))
    comparisons = [np.array_equal(surface.sample(*xy[order].T), whole[order])]
    comparisons.extend(
        np.array_equal(surface.sample(*xy.T, batch_points=n), whole) for n in (17, 257)
    )
    x = np.linspace(0, surface.grid.width_m, 129)
    y = np.linspace(0, surface.grid.height_m, 97)
    ground = surface.sample(x[None, :], y[:, None])
    left = surface.sample(x[None, :70], y[:, None])
    right = surface.sample(x[None, 60:], y[:, None])
    top = surface.sample(x[None, :], y[:55, None])
    bottom = surface.sample(x[None, :], y[45:, None])
    tiles = [
        np.array_equal(left, ground[:, :70]),
        np.array_equal(right, ground[:, 60:]),
        np.array_equal(top, ground[:55]),
        np.array_equal(bottom, ground[45:]),
        np.array_equal(left[:, 60:], right[:, :10]),
        np.array_equal(top[45:], bottom[:10]),
    ]
    shared = np.array_equal(surface.sample(x[::2][None, :], y[::2, None]), ground[::2, ::2])
    return {
        "query_count": len(xy),
        "query_sha256": numeric_hash(whole),
        "order_and_batch_exact": all(comparisons),
        "four_tiles_and_halos_exact": all(tiles),
        "shared_coarse_coordinates_exact": shared,
        "scope": "same frozen field; no regional generation or downsample-mean claim",
    }


def run(output: Path, *, figures: bool = True) -> dict[str, Any]:
    original_identity = identity()
    output.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    rows: list[dict[str, Any]] = []
    grounds: dict[str, NDArray[np.float32]] = {}
    try:
        for spacing, rotated in ((1000.0, False), (500.0, False), (250.0, False), (250.0, True)):
            label = f"dx{spacing:g}" + ("-rotated90" if rotated else "")
            directory = output / label
            directory.mkdir()
            f = fixture(spacing, rotate=rotated)
            parent = parent_identity(f)
            f = replace(f, network=relocate_guides(f, movable_edges=f.network.required).network)
            patch = prepare_patches(
                f, f.source, mode="fresh", settings=PatchSettings(boundary_model="head-mouth")
            )
            surface = FeatureSurface(patch, f.network, parent)
            tick = perf_counter()
            manifest = write_feature_surface(surface, directory / "surface")
            loaded = read_feature_surface(
                directory / "surface", expected_identity=surface.identity()
            )
            roundtrip_seconds = perf_counter() - tick
            repeated = write_feature_surface(loaded, directory / "repeat")
            if manifest != repeated:
                raise RuntimeError("Repeated feature serialization changed its identity.")
            for name in ("manifest.json", "fields.npz"):
                if (directory / "surface" / name).read_bytes() != (
                    directory / "repeat" / name
                ).read_bytes():
                    raise RuntimeError("Repeated feature serialization changed its bytes.")
            if loaded.network.identity() != f.network.identity():
                raise RuntimeError("Reopened feature graph differs from the admitted network.")
            reopened_fixture = replace(
                f, source=loaded.patch.source, network=loaded.network, hard=loaded.patch.hard
            )
            support = prepare_support(loaded.grid, loaded.network)
            original_metrics, original_common = inspect_surface(
                f, patch, patch.sample, rotated=rotated
            )
            metrics, common = inspect_surface(
                reopened_fixture, loaded.patch, loaded.sample, rotated=rotated
            )
            original_dense, original_profiles = dense_banks(
                prepare_support(f.source.grid, f.network), patch.sample
            )
            dense, profiles = dense_banks(support, loaded.sample)
            equal = (
                original_metrics == metrics
                and original_dense == dense
                and np.array_equal(original_profiles, profiles)
                and np.array_equal(original_common.ground_m, common.ground_m)
            )
            if not equal:
                raise RuntimeError("Feature roundtrip or query batching changed the local surface.")
            checks = query_checks(loaded)
            if not all(
                checks[k]
                for k in (
                    "order_and_batch_exact",
                    "four_tiles_and_halos_exact",
                    "shared_coarse_coordinates_exact",
                )
            ):
                raise RuntimeError("Feature query contract failed.")
            raster = loaded.patch.deliver(envelope="curvature")
            raster_dense, raster_profiles = dense_banks(support, raster.sample)
            raster_metrics, raster_common = inspect_surface(
                f, loaded.patch, raster.sample, rotated=rotated
            )
            metrics["quality_gates"]["dense_inward_bank_profiles"] = (
                dense["inward_uphill_sections"] == 0
            )
            arrays = {
                "bank_points_m": support.banks_m,
                "bed_points_m": support.beds_m,
                "bed_edges": support.bed_edges,
                "loaded_profiles_m": profiles,
                "original_profiles_m": original_profiles,
                "raster_profiles_m": raster_profiles,
                "loaded_common_m": common.ground_m,
                "raster_common_m": raster_common.ground_m,
            }
            with (directory / "checks.npz").open("xb") as stream:
                np.savez_compressed(stream, allow_pickle=False, **arrays)
            if figures:
                rises = np.max(
                    raster_profiles - np.minimum.accumulate(raster_profiles, axis=1), axis=1
                )
                witnesses = [int(i) for i in np.argsort(-rises, kind="stable")[:3]]
                render_sections(
                    directory / "banks.png",
                    support,
                    witnesses,
                    {"Bilinear raster": raster_profiles, "Reopened features": profiles},
                    title="Same banks after reopening: features versus raster",
                )
                render_routes(
                    directory / "routing.png",
                    f,
                    {
                        "Reopened features at 125 m": (common, routing(common)),
                        "Raster sampled at 125 m": (raster_common, routing(raster_common)),
                    },
                    label,
                )
            row = {
                "case": label,
                "parent_identity": parent,
                "surface_identity": loaded.identity(),
                "network_identity": loaded.network.identity(),
                "roundtrip_exact": equal,
                "repeated_files_exact": True,
                "archive_bytes": manifest["archive_bytes"],
                "roundtrip_seconds": roundtrip_seconds,
                "queries": checks,
                "loaded": metrics,
                "dense_banks": dense,
                "raster_control": raster_metrics,
                "raster_dense_banks": raster_dense,
                "numeric_hashes": {k: numeric_hash(v) for k, v in arrays.items()},
                "artifact_hashes": {
                    p.relative_to(directory).as_posix(): file_sha256(p)
                    for p in sorted(directory.rglob("*"))
                    if p.is_file()
                },
            }
            write_json(directory / "result.json", row)
            rows.append(row)
            grounds[label] = common.ground_m
            print(
                f"Reopened {label}: {dense['inward_uphill_sections']} bank failures; "
                f"raster control {raster_dense['inward_uphill_sections']}",
                flush=True,
            )
        rotation = float(
            np.max(
                np.abs(grounds["dx250"].astype(np.float64) - np.rot90(grounds["dx250-rotated90"]))
            )
        )
        failed = [
            f"{r['case']}: {gate}"
            for r in rows
            for gate, passed in r["loaded"]["quality_gates"].items()
            if not passed
        ]
        if rotation > 0.001:
            failed.append("quarter-turn height agreement exceeds 1 mm")
        if identity() != original_identity:
            raise RuntimeError("Code/runtime changed during feature comparison.")
        report = {
            "status": "complete",
            "model_id": FEATURE_MODEL_ID,
            "fixture_id": FIXTURE_ID,
            "identity": original_identity,
            "rows": rows,
            "rotation_maximum_ground_difference_m": rotation,
            "quality_decision": {
                "status": "rejected" if failed else "passed-this-fixture-only",
                "production_eligible": False,
                "failed_gates": failed,
            },
            "seconds": perf_counter() - started,
            "peak_resident_bytes": peak_resident_bytes(),
        }
        entries = "".join(
            f"<h2>{escape(r['case'])}</h2>"
            f"<a href='{escape(r['case'])}/result.json'>Measurements</a>"
            + (
                f"<img src='{escape(r['case'])}/banks.png'>"
                f"<img src='{escape(r['case'])}/routing.png'>"
                if figures
                else ""
            )
            for r in rows
        )
        (output / "index.html").write_text(
            "<!doctype html><meta charset='utf-8'><title>Prepared terrain features</title>"
            "<style>body{font:16px system-ui;max-width:1200px;margin:24px auto}"
            "img{width:100%}</style><h1>Prepared terrain features</h1>"
            "<p>Reopened numeric field and rejected raster control. "
            "This fixture and query boundary do not establish product "
            "or unseen-landscape acceptance.</p>"
            "<a href='comparison.json'>Decision and provenance</a>" + entries,
            encoding="utf-8",
        )
        write_json(output / "comparison.json", report)
        return report
    except Exception as error:
        write_json(
            output / "incomplete.json",
            {
                "status": "failed",
                "error": str(error),
                "model_id": FEATURE_MODEL_ID,
                "identity": original_identity,
                "seconds": perf_counter() - started,
            },
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New comparison directory")
    parser.add_argument("--no-figures", action="store_true", help="Numeric comparison only")
    args = parser.parse_args()
    run(args.output, figures=not args.no_figures)


if __name__ == "__main__":
    main()
