"""Read-only downstream evidence for authored lake outlets on the finished field."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import TYPE_CHECKING, Literal

import numpy as np
from numpy.typing import NDArray
from shapely.geometry import LineString, MultiPolygon, Polygon

from map_maker.terrain.pipeline.outlet_profiles import DownstreamProfile, sample_downstream_profile
from map_maker.terrain.pipeline.water_sampling import (
    GroundProfile,
    GroundSampler,
    SamplingGuide,
    sample_ground_profile,
)

if TYPE_CHECKING:
    from map_maker.terrain.pipeline.water import MetricBasin


@dataclass(frozen=True, slots=True)
class OutletRouteReview:
    status: Literal["sampled_clear", "blocked", "unresolved"]
    connection_profile: GroundProfile | None
    downstream: DownstreamProfile | None
    path_flat_indices: tuple[int, ...]
    water_contact_flat_index: int | None
    length_km: float
    uphill_edge_count: int
    maximum_rise_m: float
    maximum_height_above_water_m: float
    terminal_flat_index: int | None
    terminal_boundary_flags: int
    issues: tuple[str, ...]


def review_outlet_routes(
    basins: tuple[MetricBasin, ...], intent_ids: NDArray[np.uint32],
    elevation_m: NDArray[np.float64], land_mask: NDArray[np.bool_],
    receivers: NDArray[np.int64], boundary_flags: NDArray[np.uint8],
    x_km: NDArray[np.float64], y_km: NDArray[np.float64], land: Polygon | MultiPolygon,
    outlet_elevations_m: tuple[float | None, ...], sample_ground: GroundSampler,
    features: tuple[SamplingGuide, ...] = (),
) -> tuple[OutletRouteReview | None, ...]:
    """Assess one deterministic nearby attachment and its entire conditioned route.

    The receiver copy supplies candidate topology only. Every traversed segment
    must stay on vector land and outside authored basins; sampled heights come
    from the unfilled Float32 ground. A clear result never activates an outlet.
    """
    shape = elevation_m.shape
    if (shape != (y_km.size, x_km.size) or min(shape) < 2
            or any(a.shape != shape for a in (intent_ids, land_mask, receivers, boundary_flags))):
        raise ValueError("Outlet review requires equally shaped grids and matching axes.")
    if np.any(land_mask & ~np.isfinite(elevation_m)):
        raise ValueError("Outlet review requires finite land elevations.")
    dx, dy = float(x_km[1] - x_km[0]), float(y_km[1] - y_km[0])
    if (dx <= 0 or dy <= 0 or not np.allclose(np.diff(x_km), dx)
            or not np.allclose(np.diff(y_km), dy)):
        raise ValueError("Outlet review requires increasing regular metric axes.")
    tolerance = .01
    radius = hypot(dx, dy)
    geometry_tolerance = 1e-9 * max(float(x_km[-1] - x_km[0]), float(y_km[-1] - y_km[0]))
    height, width = shape
    flat_land, flat_ids = land_mask.ravel(), intent_ids.ravel()
    flat_elevation, flat_receivers = elevation_m.ravel(), receivers.ravel()
    results: list[OutletRouteReview | None] = []

    def coordinate(index: int) -> tuple[float, float]:
        row, column = divmod(index, width)
        return float(x_km[column]), float(y_km[row])

    for basin_id, (basin, outlet_height) in enumerate(
        zip(basins, outlet_elevations_m, strict=True), start=1,
    ):
        if basin.outlet_km is None:
            results.append(None)
            continue
        assert basin.source.water_level_m is not None
        level = basin.source.water_level_m
        outlet = basin.outlet_km
        issues: list[str] = []
        if outlet_height is None:
            raise ValueError("An authored outlet needs its exact sampled elevation.")
        if outlet_height > level + tolerance:
            issues.append("outlet_above_water")
        row = int(np.argmin(np.abs(y_km - outlet[1])))
        column = int(np.argmin(np.abs(x_km - outlet[0])))
        candidates: list[tuple[float, int]] = []
        water_contacts: list[tuple[float, int]] = []
        for r in range(max(0, row - 1), min(height, row + 2)):
            for c in range(max(0, column - 1), min(width, column + 2)):
                index = r * width + c
                point = coordinate(index)
                distance = hypot(point[0] - outlet[0], point[1] - outlet[1])
                if distance > radius + geometry_tolerance or not flat_land[index]:
                    continue
                segment = LineString((outlet, point))
                if (flat_ids[index] == basin_id and flat_elevation[index] < level - tolerance
                        and (distance <= geometry_tolerance or basin.geometry.covers(segment))):
                    water_contacts.append((distance, index))
                if flat_ids[index] != 0 or distance <= geometry_tolerance:
                    continue
                if not land.covers(segment):
                    continue
                if segment.intersection(basin.geometry).length > geometry_tolerance:
                    continue
                if any(segment.intersects(other.geometry)
                       for other in basins if other is not basin):
                    continue
                candidates.append((distance, index))
        contact = min(water_contacts)[1] if water_contacts else None
        if contact is None:
            issues.append("outlet_without_sampled_water")
        if not candidates:
            issues.append("outlet_attachment_unresolved")
            results.append(OutletRouteReview(
                "unresolved", None, None, (), contact, 0., 0, 0., max(0., outlet_height - level),
                None, 0, tuple(issues),
            ))
            continue
        # Choose by geometric proximity before looking at downstream success.
        _distance, current = min(candidates)
        connection = None
        if contact is not None:
            connection = sample_ground_profile((coordinate(contact), outlet, coordinate(current)),
                                                min(dx, dy) / 4, sample_ground, features)
            if connection.status != "sampled":
                issues.append("outlet_connection_unresolved")
            else:
                assert connection.maximum_ground_m is not None
                if connection.maximum_ground_m > level + tolerance:
                    issues.append("outlet_connection_above_water")
        previous_point, previous_height = outlet, level
        path: list[int] = []
        visited: set[int] = set()
        length = max_rise = 0.
        max_above = max(0., outlet_height - level)
        if connection is not None and connection.maximum_ground_m is not None:
            max_above = max(max_above, connection.maximum_ground_m - level)
        uphill = 0
        terminal = None
        flags = 0
        while True:
            if current in visited:
                issues.append("outlet_route_cycle")
                break
            if current < 0 or current >= elevation_m.size or not flat_land[current]:
                issues.append("outlet_route_invalid_receiver")
                break
            if flat_ids[current] > 0:
                issues.append("outlet_route_enters_basin")
                break
            point = coordinate(current)
            segment = LineString((previous_point, point))
            if not land.covers(segment):
                issues.append("outlet_route_crosses_nonland")
                break
            if path and any(segment.intersects(other.geometry) for other in basins):
                issues.append("outlet_route_enters_basin")
                break
            visited.add(current)
            path.append(current)
            length += segment.length
            ground = float(flat_elevation[current])
            rise = max(0., ground - previous_height)
            max_rise = max(max_rise, rise)
            max_above = max(max_above, ground - level)
            uphill += int(rise > tolerance)
            receiver = int(flat_receivers[current])
            if receiver == -1:
                terminal = current
                flags = int(boundary_flags.ravel()[current])
                if flags == 0:
                    issues.append("outlet_route_interior_terminal")
                break
            if receiver < 0 or receiver >= elevation_m.size:
                issues.append("outlet_route_invalid_receiver")
                break
            rr, cc = divmod(receiver, width)
            cr, ccurr = divmod(current, width)
            if max(abs(rr - cr), abs(cc - ccurr)) != 1:
                issues.append("outlet_route_invalid_receiver")
                break
            previous_point, previous_height = point, ground
            current = receiver
        if uphill:
            issues.append("outlet_route_uphill")
        # An enclosed SVG hole (or a raster crop alone) has no authored water level.
        if terminal is not None and (flags & 4 or not flags & 2):
            issues.append("outlet_terminal_level_unknown")
        downstream = None
        if path:
            downstream = sample_downstream_profile(
                tuple(coordinate(node) for node in path),
                tuple(float(flat_elevation[node]) for node in path), terminal is not None,
                min(dx, dy) / 4, sample_ground, features)
            if downstream.profile.status != "sampled":
                issues.append("outlet_downstream_unresolved")
            else:
                assert downstream.maximum_uphill_excursion_m is not None
                assert downstream.profile.maximum_ground_m is not None
                max_above = max(max_above, downstream.profile.maximum_ground_m - level)
                if downstream.maximum_uphill_excursion_m > tolerance:
                    issues.append("outlet_downstream_uphill")
        status = "blocked" if issues else "sampled_clear"
        results.append(OutletRouteReview(
            status, connection, downstream, tuple(path), contact, length, uphill, max_rise,
            max_above, terminal, flags, tuple(issues)))
    return tuple(results)
