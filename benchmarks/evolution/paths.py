"""Matched graph paths and physical-distance profile measures for frozen fields."""

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from benchmarks.evolution.surface import validate_graph
from map_maker.terrain.adapters.build import canonical_json
from map_maker.terrain.domain.evolution import EvolutionGrid

type FloatArray = NDArray[np.float64]
type Sampler = Callable[[FloatArray, FloatArray], NDArray[np.float32]]
PROFILE_TOLERANCE_M = 0.01


class PathNetwork(Protocol):
    """One profile interface for raster-linked and physical vector networks."""

    @property
    def receivers(self) -> NDArray[np.int64]: ...

    @property
    def required(self) -> NDArray[np.bool_]: ...

    def heads(self) -> NDArray[np.int64]: ...
    def route(self, head: int) -> NDArray[np.int64]: ...
    def points(self, nodes: NDArray[np.int64]) -> tuple[FloatArray, FloatArray]: ...
    def identity(self) -> str: ...


@dataclass(frozen=True, slots=True)
class ChannelPaths:
    grid: EvolutionGrid
    receivers: NDArray[np.int64]
    required: NDArray[np.bool_]

    def __post_init__(self) -> None:
        validate_graph(self.receivers, self.grid.shape)
        if self.required.shape != self.grid.shape or self.required.dtype != np.bool_:
            raise ValueError("Required paths must match the grid.")
        if np.any(self.required & (self.receivers < 0)):
            raise ValueError("Required paths must identify outgoing edges.")
        nodes = np.flatnonzero(self.required)
        targets = self.receivers.ravel()[nodes]
        if np.any(~self.required.ravel()[targets] & (self.receivers.ravel()[targets] >= 0)):
            raise ValueError("Required network is not connected to its terminals.")
        for name in ("receivers", "required"):
            owned = getattr(self, name).copy()
            owned.flags.writeable = False
            object.__setattr__(self, name, owned)

    def heads(self) -> NDArray[np.int64]:
        edges = np.flatnonzero(self.required)
        incoming = np.bincount(self.receivers.ravel()[edges], minlength=self.receivers.size)
        return np.flatnonzero(self.required.ravel() & (incoming == 0))

    def route(self, head: int) -> NDArray[np.int64]:
        if not 0 <= head < self.receivers.size or not self.required.ravel()[head]:
            raise ValueError("Route head must belong to the required network.")
        flow = self.receivers.ravel()
        path = [head]
        while flow[path[-1]] >= 0:
            path.append(int(flow[path[-1]]))
        return np.asarray(path, dtype=np.int64)

    def points(self, nodes: NDArray[np.int64]) -> tuple[FloatArray, FloatArray]:
        y, x = np.divmod(nodes, self.grid.shape[1])
        return x.astype(np.float64) * self.grid.spacing_m, y.astype(
            np.float64
        ) * self.grid.spacing_m

    def identity(self) -> str:
        return sha256(
            self.receivers.astype("<i8").tobytes()
            + self.required.tobytes()
            + canonical_json({"spacing_m": self.grid.spacing_m, "shape": self.grid.shape})
        ).hexdigest()


def station_distances(x: FloatArray, y: FloatArray, spacing_m: float) -> FloatArray:
    """Uniform arclength stations plus every original vertex; no gap exceeds spacing."""
    if isinstance(spacing_m, bool) or not isfinite(spacing_m) or spacing_m <= 0:
        raise ValueError("Profile spacing must be finite and positive.")
    if (
        x.ndim != 1
        or x.shape != y.shape
        or not np.all(np.isfinite(x))
        or not np.all(np.isfinite(y))
    ):
        raise ValueError("Profile vertices must be finite matching coordinate vectors.")
    cumulative = np.concatenate((np.array([0.0]), np.cumsum(np.hypot(np.diff(x), np.diff(y)))))
    if cumulative.size < 2 or np.any(np.diff(cumulative) <= 0):
        raise ValueError("Profile must have distinct successive vertices.")
    intervals = float(cumulative[-1]) / spacing_m
    if not isfinite(intervals) or intervals + cumulative.size > 1_000_000:
        raise ValueError("One profile exceeds the one-million-station work bound.")
    count = int(np.ceil(intervals))
    # Arithmetic coordinates are independent of any viewport or rendering size.
    return np.unique(np.concatenate((np.arange(count, dtype=np.float64) * spacing_m, cumulative)))


def profile(
    paths: PathNetwork,
    nodes: NDArray[np.int64],
    sampler: Sampler,
    spacing_m: float,
) -> tuple[FloatArray, NDArray[np.float32]]:
    x, y = paths.points(nodes)
    cumulative = np.concatenate((np.array([0.0]), np.cumsum(np.hypot(np.diff(x), np.diff(y)))))
    stations = station_distances(x, y, spacing_m)
    qx, qy = np.interp(stations, cumulative, x), np.interp(stations, cumulative, y)
    values = sampler(qx, qy)
    if (
        values.shape != stations.shape
        or values.dtype != np.float32
        or not np.all(np.isfinite(values))
    ):
        raise ValueError("Ground sampler must deliver finite Float32 profile heights.")
    return stations, values


def profile_numbers(stations: FloatArray, ground: NDArray[np.float32]) -> dict[str, float]:
    z = ground.astype(np.float64)
    rise = np.diff(z)
    # Apply the height tolerance to a complete nondecreasing run, not each
    # sampling interval: otherwise a gentle uphill disappears at finer spacing.
    runs = np.cumsum(rise < 0)
    run_ascent = np.bincount(runs, weights=np.maximum(rise, 0.0))
    affected = (rise > 0) & (run_ascent[runs] > PROFILE_TOLERANCE_M)
    return {
        "length_m": float(stations[-1]),
        "uphill_ascent_m": float(np.sum(np.maximum(rise, 0.0))),
        "affected_length_m": float(np.sum(np.diff(stations)[affected])),
        "maximum_excursion_m": float(np.max(z - np.minimum.accumulate(z))),
    }


def measure_paths(
    paths: PathNetwork,
    sampler: Sampler,
    ground_nodes: FloatArray,
    spacing_m: float,
    *,
    maximum_samples: int = 8_000_000,
) -> dict[str, Any]:
    """Measure every unique edge and every full head-to-terminal route, unchanged.

    Full-route ascent repeats shared downstream reaches, so its sum is explicitly
    separate from the unique-edge physical network measure.
    """
    if type(maximum_samples) is not int or not 1 <= maximum_samples <= 32_000_000:
        raise ValueError("Profile sample budget must be from 1 to 32,000,000.")
    if ground_nodes.shape != paths.receivers.shape or not np.all(np.isfinite(ground_nodes)):
        raise ValueError("Nodal ground must match the path network.")
    if isinstance(spacing_m, bool) or not isfinite(spacing_m) or spacing_m <= 0:
        raise ValueError("Profile spacing must be finite and positive.")
    used = 0
    digest = sha256()

    def measured(nodes: NDArray[np.int64]) -> tuple[dict[str, float], bool]:
        nonlocal used
        x, y = paths.points(nodes)
        intervals = float(np.sum(np.hypot(np.diff(x), np.diff(y)))) / spacing_m
        if not isfinite(intervals) or intervals + nodes.size > maximum_samples - used:
            raise ValueError("Profile comparison exhausted its sample budget.")
        s, z = profile(paths, nodes, sampler, spacing_m)
        used += len(s)
        digest.update(nodes.astype("<i8").tobytes())
        digest.update(s.astype("<f8").tobytes())
        digest.update(z.astype("<f4").tobytes())
        nodal_rises = np.diff(ground_nodes.ravel()[nodes])
        return profile_numbers(s, z), bool(np.all(nodal_rises <= PROFILE_TOLERANCE_M))

    totals = {
        "length_m": 0.0,
        "uphill_ascent_m": 0.0,
        "affected_length_m": 0.0,
        "maximum_excursion_m": 0.0,
    }
    edge_rows: list[dict[str, Any]] = []
    for source in np.flatnonzero(paths.required):
        target = int(paths.receivers.ravel()[source])
        numbers, nodally_nonascending = measured(np.array([source, target], dtype=np.int64))
        for name, value in numbers.items():
            totals[name] = (
                max(totals[name], value)
                if name == "maximum_excursion_m"
                else (totals[name] + value)
            )
        edge_rows.append(
            {
                "source": int(source),
                "target": target,
                "nodally_nonascending": nodally_nonascending,
                **numbers,
            }
        )
    route_rows: list[dict[str, Any]] = []
    for head in paths.heads():
        route = paths.route(int(head))
        numbers, nodally_nonascending = measured(route)
        route_rows.append(
            {
                "head": int(head),
                "terminal": int(route[-1]),
                "nodally_nonascending": nodally_nonascending,
                **numbers,
            }
        )
    return {
        "path_identity": paths.identity(),
        "station_spacing_m": spacing_m,
        "sampling_policy": "uniform route arclength plus original vertices",
        "rise_tolerance_m": PROFILE_TOLERANCE_M,
        "affected_length_policy": (
            "positive-rise intervals within nondecreasing runs exceeding the height tolerance"
        ),
        "sample_count": used,
        "profile_sha256": digest.hexdigest(),
        "unique_network": totals,
        "required_edge_count": len(edge_rows),
        "sampled_edge_count": len(edge_rows),
        "head_route_count": len(route_rows),
        "edges": edge_rows,
        "routes": route_rows,
    }


def anchor_residuals(
    sampler: Sampler,
    points_m: FloatArray,
    targets_m: FloatArray,
    *,
    tolerance_m: float = 0.01,
) -> dict[str, Any]:
    """Report targets a candidate violates; never patch the field to hide them."""
    if (
        points_m.ndim != 2
        or points_m.shape[1] != 2
        or targets_m.shape != (len(points_m),)
        or not np.all(np.isfinite(points_m))
        or not np.all(np.isfinite(targets_m))
        or not isfinite(tolerance_m)
        or tolerance_m < 0
    ):
        raise ValueError("Anchor coordinates, heights and tolerance must be finite and valid.")
    actual = sampler(points_m[:, 0], points_m[:, 1])
    if (
        actual.shape != targets_m.shape
        or actual.dtype != np.float32
        or not np.all(np.isfinite(actual))
    ):
        raise ValueError("Ground sampler must deliver finite Float32 anchor heights.")
    delta = actual.astype(np.float64) - targets_m
    return {
        "residuals_m": delta.tolist(),
        "tolerance_m": tolerance_m,
        "violated_indices": np.flatnonzero(np.abs(delta) > tolerance_m).tolist(),
    }
