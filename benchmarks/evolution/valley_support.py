"""Physical bank-to-network support with explicit junction ownership."""

from dataclasses import dataclass
from math import isfinite

import numpy as np
from numpy.typing import NDArray

from benchmarks.evolution.network import RiverNetwork
from benchmarks.evolution.paths import FloatArray
from map_maker.terrain.domain.evolution import EvolutionGrid

VALLEY_SUPPORT_ID = "nearest-network-bank-support@1"


@dataclass(frozen=True, slots=True)
class ValleySupport:
    network_identity: str
    banks_m: FloatArray
    beds_m: FloatArray
    requested_edges: NDArray[np.int64]
    bed_edges: NDArray[np.int64]
    remaining_to_mouth_m: FloatArray
    station_spacing_m: float
    offset_m: float
    minimum_slope: float
    outside_domain_count: int

    def __post_init__(self) -> None:
        banks = np.array(self.banks_m, dtype=np.float64, copy=True)
        beds = np.array(self.beds_m, dtype=np.float64, copy=True)
        requested = np.array(self.requested_edges, copy=True)
        owners = np.array(self.bed_edges, copy=True)
        remaining = np.array(self.remaining_to_mouth_m, dtype=np.float64, copy=True)
        if (
            len(self.network_identity) != 64
            or any(c not in "0123456789abcdef" for c in self.network_identity)
            or banks.ndim != 2
            or banks.shape[1] != 2
            or beds.shape != banks.shape
            or not 1 <= len(banks) <= 8192
            or requested.shape != (len(banks),)
            or owners.shape != requested.shape
            or remaining.shape != requested.shape
            or np.any(remaining < 0)
            or not np.all(np.isfinite(remaining))
            or requested.dtype != np.int64
            or owners.dtype != np.int64
            or np.any(requested < 0)
            or np.any(owners < 0)
            or not np.all(np.isfinite(banks))
            or not np.all(np.isfinite(beds))
            or type(self.outside_domain_count) is not int
            or self.outside_domain_count < 0
        ):
            raise ValueError("Valley support needs matching finite bank/bed points and edge IDs.")
        for value in (self.station_spacing_m, self.offset_m, self.minimum_slope):
            if isinstance(value, bool) or not isfinite(value) or value <= 0:
                raise ValueError("Valley support distances and slope must be finite and positive.")
        for name, value in (
            ("banks_m", banks),
            ("beds_m", beds),
            ("requested_edges", requested),
            ("bed_edges", owners),
            ("remaining_to_mouth_m", remaining),
        ):
            value.flags.writeable = False
            object.__setattr__(self, name, value)

    @property
    def distances_m(self) -> FloatArray:
        return np.sqrt(np.sum((self.banks_m - self.beds_m) ** 2, axis=1))

    @property
    def drops_m(self) -> FloatArray:
        # Banks meet their terminal level at the mouth. Requiring a positive
        # bank height on a fixed zero-height coast would be contradictory.
        fade = np.minimum(self.remaining_to_mouth_m / self.offset_m, 1.0)
        return self.minimum_slope * self.distances_m * fade * fade * (3.0 - 2.0 * fade)

    def witness(self, index: int) -> dict[str, object]:
        return {
            "support_index": index,
            "bank_m": self.banks_m[index].tolist(),
            "bed_m": self.beds_m[index].tolist(),
            "requested_edge": int(self.requested_edges[index]),
            "bed_edge": int(self.bed_edges[index]),
            "required_drop_m": float(self.drops_m[index]),
            "distance_to_mouth_m": float(self.remaining_to_mouth_m[index]),
        }


def prepare_support(
    grid: EvolutionGrid,
    network: RiverNetwork,
    *,
    station_spacing_m: float = 250.0,
    offset_m: float = 500.0,
    minimum_slope: float = 0.0005,
) -> ValleySupport:
    for value in (station_spacing_m, offset_m, minimum_slope):
        if isinstance(value, bool) or not isfinite(value) or value <= 0:
            raise ValueError("Valley support distances and slope must be finite and positive.")
    if (
        np.any(network.coordinates_m < 0)
        or np.any(network.coordinates_m[:, 0] > grid.width_m)
        or np.any(network.coordinates_m[:, 1] > grid.height_m)
    ):
        raise ValueError("Valley network must lie inside the metric domain.")
    banks: list[FloatArray] = []
    requested: list[int] = []
    outside = 0
    for edge in np.flatnonzero(network.required):
        p, q = network.coordinates_m[[edge, network.receivers[edge]]]
        d = q - p
        length = float(np.hypot(d[0], d[1]))
        if 2 * (np.ceil(length / station_spacing_m) + 1) + len(banks) + outside > 8192:
            raise ValueError("Valley support exceeds 8,192 physical bank probes.")
        # Include heads and junctions explicitly, independent of raster spacing.
        stations = np.unique(
            np.concatenate(([0.0, length], np.arange(0, length, station_spacing_m)))
        )
        normal = np.array([-d[1], d[0]]) / length
        for station in stations:
            centre = p + (station / length) * d
            for side in (-1, 1):
                bank = centre + side * offset_m * normal
                if np.any(bank < 0) or bank[0] > grid.width_m or bank[1] > grid.height_m:
                    outside += 1
                    continue
                banks.append(bank)
                requested.append(int(edge))
    xy = np.asarray(banks, dtype=np.float64)
    nearest = np.full(len(xy), np.inf, dtype=np.float64)
    beds = np.zeros_like(xy)
    owners = np.full(len(xy), -1, dtype=np.int64)
    remaining = np.zeros(len(xy), dtype=np.float64)
    for edge in np.flatnonzero(network.required):
        p, q = network.coordinates_m[[edge, network.receivers[edge]]]
        d = q - p
        t = np.clip(((xy - p) @ d) / np.dot(d, d), 0, 1)
        projected: FloatArray = p + t[:, None] * d
        distance = np.sum((xy - projected) ** 2, axis=1)
        take = distance < nearest
        nearest[take], beds[take], owners[take] = distance[take], projected[take], edge
        route = network.coordinates_m[network.route(int(edge))]
        route_length = float(np.sum(np.hypot(np.diff(route[:, 0]), np.diff(route[:, 1]))))
        remaining[take] = np.maximum(0.0, route_length - t[take] * np.hypot(d[0], d[1]))
    # At a junction, a candidate bank can belong to the adjoining reach. Use
    # that actual nearest bed instead of raising a tributary as another's bank.
    return ValleySupport(
        network.identity(),
        xy,
        beds,
        np.asarray(requested, dtype=np.int64),
        owners,
        remaining,
        station_spacing_m,
        offset_m,
        minimum_slope,
        outside,
    )
