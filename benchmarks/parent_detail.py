# pyright: reportPrivateUsage=false
"""Measure parent-cell preservation, density drift and authored/hydrology conflicts."""

import argparse
import json
from dataclasses import asdict, replace
from functools import partial
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
from numpy.typing import NDArray

from benchmarks import channel_profiles, parent_cells
from benchmarks import terrain as fixtures
from benchmarks.parent_cells import (
    PARENT_CELL_METHOD_ID,
    PARENT_RESTRICTION_ID,
    interpolate_parent,
    parent_cell_means,
    project_parent_cells,
    restrict_cell_means,
)
from map_maker.terrain.adapters.build import canonical_json, file_sha256, runtime_identity
from map_maker.terrain.adapters.render import render_ground_map
from map_maker.terrain.domain import ElevationPoint, TerrainBasin
from map_maker.terrain.domain.regional import RegionalSamplingRequest
from map_maker.terrain.pipeline.regional import prepare_regional_sampler, regional_coordinates
from map_maker.terrain.pipeline.water import sampled_basin_water

type FloatArray = NDArray[np.float64]
CASES = ("regional", "authored", "water")


def sample_grid(
    x: FloatArray, y: FloatArray, values: NDArray[np.float32], qx: FloatArray, qy: FloatArray,
) -> NDArray[np.float32]:
    """The measured child is a Float32 node raster with bilinear interpolation."""
    if (qx.shape != qy.shape or not np.isfinite(qx).all() or not np.isfinite(qy).all()
            or np.any((qx < x[0]) | (qx > x[-1]) | (qy < y[0]) | (qy > y[-1]))):
        raise ValueError("Profile queries must remain inside the measured child.")
    c = np.clip(np.searchsorted(x, qx, side="right")-1, 0, len(x)-2)
    r = np.clip(np.searchsorted(y, qy, side="right")-1, 0, len(y)-2)
    u, v = (qx-x[c])/(x[c+1]-x[c]), (qy-y[r])/(y[r+1]-y[r])
    z = values.astype(np.float64)
    top = z[r, c] + u*(z[r, c+1]-z[r, c])
    bottom = z[r+1, c] + u*(z[r+1, c+1]-z[r+1, c])
    return (top + v*(bottom-top)).astype(np.float32)


def probe(case: str, seed: int, destination: Path | None = None) -> dict[str, Any]:
    coast, original_settings, constraints = fixtures.fixture(case, 65, seed)
    settings = replace(original_settings, detail_levels=2)
    started = perf_counter()
    sampler = prepare_regional_sampler(coast, settings, constraints=constraints)
    preparation = perf_counter()-started
    field, grid = sampler._field, sampler.reference_grid
    # The proposal adds bands while reusing the parent's complete prepared context.
    # It is not a new whole-map generation with newly prepared profiles/routing.
    proposal_field = replace(field, settings=replace(settings, detail_levels=4))
    centre = (.65, .28) if case == "regional" else (.55, .35)
    if case == "water":
        lake = next(c for c in constraints if isinstance(c, TerrainBasin) and c.kind == "lake")
        centre = tuple(np.mean(np.asarray(lake.points[:-1]), axis=0))
    left = max(0, min(grid.width-5, int(centre[0]*(grid.width-1))-2))
    top = max(0, min(grid.height-5, int(centre[1]*(grid.height-1))-2))
    coarse_request = RegionalSamplingRequest(sampler.source_id, grid, 1,
                                             (left, top, left+4, top+4), halo_cells=0)
    parent = sampler.sample(coarse_request).elevation_m
    assert np.isfinite(parent).all()
    parent_hash = sha256(parent.astype("<f4").tobytes()).hexdigest()
    target = parent_cell_means(parent)
    rows: list[dict[str, Any]] = []
    archive: dict[str, Any] = {"parent_m": parent}
    previous: NDArray[np.float32] | None = None
    previous_proposal: NDArray[np.float32] | None = None
    last = None
    for factor in (16, 32, 64):
        request = RegionalSamplingRequest(sampler.source_id, grid, factor,
            (left*factor, top*factor, (left+4)*factor, (top+4)*factor), halo_cells=0)
        x, y = regional_coordinates(request)
        xx, yy = np.meshgrid(x, y)
        current = field.sample_ground(xx, yy)
        proposed = proposal_field.sample_ground(xx, yy)
        started = perf_counter()
        result = project_parent_cells(parent, proposed, factor,
                                       maximum_elevation_m=settings.maximum_elevation_m)
        seconds = perf_counter()-started
        baseline = interpolate_parent(parent, factor)
        conditioned = result.elevation_m
        change = conditioned.astype(np.float64)-baseline
        parent_restriction_error = float(np.max(np.abs(
            restrict_cell_means(current, factor)-target)))
        proposal_restriction_error = float(np.max(np.abs(
            restrict_cell_means(proposed, factor)-target)))
        nested = None
        if previous is not None and previous_proposal is not None:
            np.testing.assert_array_equal(proposed[::2, ::2], previous_proposal)
            difference = conditioned[::2, ::2].astype(np.float64)-previous
            nested = {"exact": bool(np.array_equal(conditioned[::2, ::2], previous)),
                      "maximum_difference_m": float(np.max(np.abs(difference))),
                      "rms_difference_m": float(np.sqrt(np.mean(difference**2)))}
        previous, previous_proposal = conditioned, proposed
        # Each conditioning request owns complete cells, so independent overlapping
        # requests use identical support instead of a crop-dependent mean.
        for start in (0, 1, 0):
            part = project_parent_cells(parent[start:4, start:4],
                proposed[start*factor:3*factor+1, start*factor:3*factor+1], factor,
                maximum_elevation_m=settings.maximum_elevation_m)
            np.testing.assert_array_equal(part.elevation_m,
                                           conditioned[start*factor:3*factor+1,
                                                       start*factor:3*factor+1])
        edge = np.zeros(conditioned.shape, dtype=np.bool_)
        edge[::factor, :], edge[:, ::factor] = True, True
        # A finite one-step slope of the ADDED correction, not the existing
        # bilinear parent's gradient jumps or a claim about continuous slopes.
        x_steps = np.concatenate((np.abs(change[:, 1::factor]-change[:, :-1:factor]),
                                   np.abs(change[:, factor-1::factor]-change[:, factor::factor])),
                                  axis=None)
        y_steps = np.concatenate((np.abs(change[1::factor]-change[:-1:factor]),
                                   np.abs(change[factor-1::factor]-change[factor::factor])),
                                  axis=None)
        parent_water, _ = sampled_basin_water(current, xx, yy, field.basins)
        child_water, _ = sampled_basin_water(conditioned, xx, yy, field.basins)
        row: dict[str, Any] = {
            "refinement": factor, "shape": conditioned.shape,
            "spacing_km": [request.grid().x_spacing_km, request.grid().y_spacing_km],
            "projection_seconds": seconds,
            "parent_field_cell_mean_error_m": parent_restriction_error,
            "proposal_cell_mean_error_m": proposal_restriction_error,
            "conditioned_cell_mean_error_m": result.maximum_cell_mean_error_m,
            "quantization_tolerance_m": result.quantization_tolerance_m,
            "parent_nodes_exact": bool(np.array_equal(conditioned[::factor, ::factor], parent)),
            "overlap_and_repeat": "exact", "previous_density": nested,
            "bilinear_edge_error_m": float(np.max(np.abs(change[edge]))),
            "added_boundary_secant_slope_m_per_km": float(max(
                x_steps.max()/request.grid().x_spacing_km,
                y_steps.max()/request.grid().y_spacing_km)),
            "detail_rms_m": float(np.sqrt(np.mean(change**2))),
            "minimum_detail_scale": float(result.detail_scale.min()),
            "changed_wet_nodes_from_parent_field": int(np.count_nonzero(
                np.isfinite(parent_water) != np.isfinite(child_water))),
            "elevation_sha256": sha256(conditioned.astype("<f4").tobytes()).hexdigest(),
        }
        rows.append(row)
        for name, value in (("proposal", proposed), ("conditioned", conditioned),
                            ("bilinear", baseline), ("parent_field", current), ("x", x), ("y", y)):
            archive[f"{name}_{factor}"] = value
        last = request, x, y, current, proposed, conditioned, baseline
    assert last is not None
    request, x, y, current, proposed, conditioned, baseline = last
    valley = field.automatic_valleys
    vx, vy = np.meshgrid(valley.x_km, valley.y_km)
    inside = (vx >= x[0]) & (vx <= x[-1]) & (vy >= y[0]) & (vy <= y[-1])
    receivers = valley.drainage.receivers
    selected = valley.drainage.channel_mask & (receivers >= 0)
    receiver_inside = inside.ravel()[np.maximum(receivers, 0)]
    crossing = selected & (inside != receiver_inside)
    interior = selected & inside & receiver_inside
    channel_results: dict[str, Any] = {}
    for name, values in (("bilinear_parent", baseline), ("proposal", proposed),
                         ("conditioned", conditioned)):
        channel_results[name] = channel_profiles.measure_channels(
            valley.x_km, valley.y_km, receivers, interior,
            partial(sample_grid, x, y, values), stations=65)
    channel_results["parent_field"] = channel_profiles.measure_channels(
        valley.x_km, valley.y_km, receivers, interior, field.sample_ground, stations=65)
    sources = np.flatnonzero(interior.ravel())
    targets = receivers.ravel()[sources]
    sr, sc = np.divmod(sources, len(valley.x_km))
    tr, tc = np.divmod(targets, len(valley.x_km))
    fraction = np.linspace(0., 1., 65)[None, :]
    qx = valley.x_km[sc, None]*(1-fraction) + valley.x_km[tc, None]*fraction
    qy = valley.y_km[sr, None]*(1-fraction) + valley.y_km[tr, None]*fraction
    original = field.sample_ground(qx, qy).astype(np.float64)
    revised = sample_grid(x, y, conditioned, qx, qy).astype(np.float64)
    rise_before = np.max(original-np.minimum.accumulate(original, axis=1), axis=1)
    rise_after = np.max(revised-np.minimum.accumulate(revised, axis=1), axis=1)
    worsening = rise_after-rise_before
    paired = {"matched_edge_count": int(sources.size),
              "edges_worsening_above_0_01_m": int(np.count_nonzero(worsening > .01)),
              "maximum_excursion_increase_m": float(worsening.max()) if sources.size else None,
              "edge_pairs_sha256": sha256(
                  np.column_stack((sources, targets)).tobytes()).hexdigest()}
    anchors: list[dict[str, float]] = []
    for point in constraints:
        if not isinstance(point, ElevationPoint) or point.elevation_mode != "absolute":
            continue
        px, py = point.position[0]*grid.extent_km[2], point.position[1]*grid.extent_km[3]
        if not (x[0] <= px <= x[-1] and y[0] <= py <= y[-1]):
            continue
        qx, qy = np.asarray([px]), np.asarray([py])
        anchors.append({"x_km": px, "y_km": py, "authored_m": point.elevation_m,
                        "parent_field_m": float(field.sample_ground(qx, qy)[0]),
                        "proposal_field_m": float(proposal_field.sample_ground(qx, qy)[0]),
                        "proposal_raster_m": float(sample_grid(x, y, proposed, qx, qy)[0]),
                        "bilinear_parent_m": float(sample_grid(x, y, baseline, qx, qy)[0]),
                        "conditioned_m": float(sample_grid(x, y, conditioned, qx, qy)[0])})
    outputs: dict[str, str] = {}
    if destination is not None:
        numeric = destination/f"{case}-{seed}.npz"
        with numeric.open("xb") as stream:
            np.savez_compressed(stream, **archive)
        outputs[numeric.name] = file_sha256(numeric)
        for name, values in (("bilinear", baseline), ("proposal", proposed),
                             ("conditioned", conditioned)):
            target_path = destination/f"{case}-{seed}-{name}.png"
            with render_ground_map(values, np.ones(values.shape, dtype=np.bool_), request.grid(),
                                   settings.maximum_elevation_m, style="cartographic") as image:
                image.save(target_path, format="PNG")
            outputs[target_path.name] = file_sha256(target_path)
    assert parent_hash == sha256(parent.astype("<f4").tobytes()).hexdigest()
    return {"case": case, "seed": seed, "source_id": sampler.source_id,
            "input_sha256": sha256(canonical_json({"coastline": asdict(coast),
                "settings": asdict(settings),
                "constraints": [asdict(c) for c in constraints]})).hexdigest(),
            "parent_snapshot_sha256": parent_hash, "parent_grid": asdict(coarse_request.grid()),
            "parent_detail_levels": 2, "proposal_detail_levels": 4,
            "global_preparation_seconds": preparation, "levels": rows, "anchors": anchors,
            "boundary_crossing_channels": int(crossing.sum()),
            "channel_profiles": channel_results, "paired_channel_changes": paired,
            "outputs": outputs}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", nargs="+", choices=CASES, default=list(CASES))
    parser.add_argument("--seed", nargs="+", type=int, default=[42, 7])
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--save-grids", action="store_true")
    args = parser.parse_args()
    runtime = runtime_identity()
    files = [Path(__file__), Path(parent_cells.__file__), Path(fixtures.__file__),
             Path(channel_profiles.__file__)]
    sources = {p.name: file_sha256(p) for p in files}
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        destination = args.output.with_suffix("") if args.save_grids else None
        if destination is not None:
            destination.mkdir()
        cases: list[dict[str, Any]] = []
        for case in args.case:
            for seed in args.seed:
                result = probe(case, seed, destination)
                cases.append(result)
                print(json.dumps({"case": case, "seed": seed,
                    "maximum_mean_error_m": max(r["conditioned_cell_mean_error_m"]
                                                for r in result["levels"]),
                    "finest_density_comparison": result["levels"][-1]["previous_density"],
                    "anchors": result["anchors"]}), flush=True)
        if runtime != runtime_identity() or sources != {p.name: file_sha256(p) for p in files}:
            raise RuntimeError("Source or runtime changed during parent-cell measurement.")
        stream.write(canonical_json({
            "schema": "map-maker.parent-cell-experiment", "schema_version": 1,
            "complete": True, "runtime": runtime, "benchmark_sources": sources,
            "method": PARENT_CELL_METHOD_ID, "restriction": PARENT_RESTRICTION_ID,
            "parent_kind": "immutable-in-memory-snapshot-of-prepared-global-field",
            "proposal_context": "parent-prepared-profiles-and-routing-with-two-added-bands",
            "completed_parent_build_loading": False, "product_enrichment_implemented": False,
            "refined_hydrology": False, "cases": cases}).decode())


if __name__ == "__main__":
    main()
