"""Owned prepared valley data and bounded metric queries; research only."""

from dataclasses import dataclass, replace
from hashlib import sha256
from math import ceil, prod
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray

from benchmarks.evolution.constrained import FittedSurface, HardHeights
from benchmarks.evolution.evidence import numeric_hash
from benchmarks.evolution.network import RiverNetwork
from benchmarks.evolution.paths import FloatArray
from benchmarks.evolution.valley_patches import ValleyPatches
from map_maker.terrain.adapters.build import canonical_json
from map_maker.terrain.domain.evolution import EvolutionGrid

FEATURE_MODEL_ID = "prepared-valley-surface@1"
MAX_QUERY_POINTS = 262_144
MAX_BATCH_POINTS = 8192
PATCH_ARRAYS = (
    "segments_m",
    "bed_heights_m",
    "anchor_corrections_m",
    "mouth_segments_m",
    "mouth_heights_m",
    "mouth_inward",
)


def digest(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError("Feature provenance requires lowercase SHA-256 identities.")
    return value


def _owned(values: NDArray[Any]) -> NDArray[Any]:
    # A bytes-backed buffer cannot have writeability restored through a public
    # NumPy view. This also separates the snapshot from mutable preparation data.
    return np.frombuffer(values.tobytes(order="C"), dtype=values.dtype).reshape(values.shape)


def _inside(grid: EvolutionGrid, xy: FloatArray) -> bool:
    return bool(np.all(xy >= 0) and np.all(xy <= (grid.width_m, grid.height_m)))


def _geometry(p: ValleyPatches, network: RiverNetwork) -> None:
    """Verify that stored patch subdivision belongs to the complete stored graph."""
    segments: list[FloatArray] = []
    mouths: list[FloatArray] = []
    normals: list[FloatArray] = []
    count = 0
    for edge in np.flatnonzero(network.required):
        path: FloatArray = network.coordinates_m[[edge, network.receivers[edge]]]
        length = cast(float, np.linalg.norm(path[1] - path[0]))
        n = ceil(length / p.settings.profile_spacing_m)
        if n < 1 or count + n > 2048:
            raise ValueError("Feature geometry exceeds 2,048 profile segments.")
        count += n
        t = np.linspace(0.0, 1.0, n + 1)
        xy = path[0] + t[:, None] * (path[1] - path[0])
        segments.extend(xy[i : i + 2] for i in range(n))
        if network.receivers[network.receivers[edge]] < 0:
            q = path[-1]
            normal = np.zeros(2, dtype=np.float64)
            if q[0] == 0 and np.all(p.source.ground_m[:, 0] == 0):
                normal[0] = 1
            elif q[1] == p.source.grid.height_m and np.all(p.source.ground_m[-1] == 0):
                normal[1] = -1
            else:
                raise ValueError("Feature mouths require the supported straight zero coast.")
            if float((path[0] - q) @ normal) <= 0:
                raise ValueError("Feature mouth must approach from inland.")
            mouths.append(path)
            normals.append(normal)
    for actual, expected in (
        (p.segments_m, segments),
        (p.mouth_segments_m, mouths),
        (p.mouth_inward, normals),
    ):
        if not np.array_equal(actual, np.asarray(expected, dtype=np.float64)):
            raise ValueError("Feature geometry does not match its stored network.")


def _validate(p: ValleyPatches, network: RiverNetwork) -> None:
    grid = p.source.grid
    if (
        p.cap_field.grid != grid
        or max(grid.width_m, grid.height_m) > 1e9
        or grid.spacing_m < 1e-6
        or p.mode not in ("fixed", "fresh")
        or (p.settings.boundary_model == "head-mouth" and p.mode != "fresh")
    ):
        raise ValueError("Feature grid or construction mode is unsupported.")
    if not _inside(grid, network.coordinates_m) or not _inside(grid, p.hard.points_m):
        raise ValueError("Feature network and hard heights must lie inside the metric domain.")
    n, pins, mouths = len(p.segments_m), len(p.hard.heights_m), len(p.mouth_heights_m)
    if not 1 <= n <= 2048 or not 0 <= pins <= 16 or not 1 <= mouths <= 256:
        raise ValueError("Feature counts exceed the bounded experiment.")
    shapes = ((n, 2, 2), (n, 2), (pins,), (mouths, 2, 2), (mouths,), (mouths, 2))
    for name, shape in zip(PATCH_ARRAYS, shapes, strict=True):
        a = getattr(p, name)
        if a.dtype != np.float64 or a.shape != shape or not np.all(np.isfinite(a)):
            raise ValueError(f"Invalid finite Float64 feature array: {name}.")
        if np.any(np.abs(a) > 1e12):
            raise ValueError(f"Feature values exceed the numerical envelope: {name}.")
    for a in (p.source.ground_m, p.cap_field.ground_m, p.hard.heights_m):
        if np.any(a < 0) or np.any(a > 1e7):
            raise ValueError("Feature heights and capacities must be within [0, 1e7] metres.")
    bounds = np.asarray(p.protected_bounds_m)
    if (
        bounds.shape != (4,)
        or not np.all(np.isfinite(bounds))
        or (bounds[0] >= bounds[2] or bounds[1] >= bounds[3] or np.any(np.abs(bounds) > 1e9))
    ):
        raise ValueError("Feature protection requires a finite nonempty metric rectangle.")
    for name in (
        "profile_spacing_m",
        "support_m",
        "floor_radius_m",
        "bank_rise_m",
        "fresh_cut_limit_m",
        "anchor_radius_m",
    ):
        if not 1e-6 <= getattr(p.settings, name) <= 1e9:
            raise ValueError("Feature physical scales exceed the numerical envelope.")
    if not 0 <= p.settings.mouth_taper_m <= 1e9 or not 1e-9 <= p.settings.initial_grade <= 1:
        raise ValueError("Feature taper or initial grade exceeds the numerical envelope.")
    _geometry(p, network)
    seen: set[int] = set()
    for transition in p.head_transitions:
        if (
            type(transition.head) is not int
            or type(transition.stop_node) is not int
            or transition.head not in network.heads()
            or transition.head in seen
            or transition.stop_node not in network.route(transition.head)[1:]
            or not np.all(
                np.isfinite(
                    (transition.length_m, transition.lower_at_head_m, transition.lift_at_head_m)
                )
            )
            or not 0 < transition.length_m <= 1e12
            or not 0 <= transition.lower_at_head_m <= 1e7
            or not 0 <= transition.lift_at_head_m <= 1e7
            or p.settings.boundary_model != "head-mouth"
        ):
            raise ValueError("Invalid feature head-transition record.")
        seen.add(transition.head)
    if np.any(np.abs(p.sample(*p.hard.points_m.T) - p.hard.heights_m) > 0.0001):
        raise ValueError("Feature field does not preserve its stored hard heights.")


@dataclass(frozen=True, slots=True)
class FeatureSurface:
    patch: ValleyPatches
    network: RiverNetwork
    parent_identity: str

    def __post_init__(self) -> None:
        digest(self.parent_identity)
        p = self.patch
        source = FittedSurface(p.source.grid, p.source.ground_m, {})
        cap = FittedSurface(p.cap_field.grid, p.cap_field.ground_m, {})
        hard = HardHeights(p.hard.points_m, p.hard.heights_m)
        network = RiverNetwork(self.network.coordinates_m, self.network.receivers)
        for owner, names in (
            (source, ("ground_m",)),
            (cap, ("ground_m",)),
            (hard, ("points_m", "heights_m")),
            (network, ("coordinates_m", "receivers")),
        ):
            for name in names:
                object.__setattr__(owner, name, _owned(getattr(owner, name)))
        p = replace(
            p,
            source=source,
            cap_field=cap,
            hard=hard,
            protected_bounds_m=tuple(p.protected_bounds_m),
            head_transitions=tuple(p.head_transitions),
            **{name: _owned(getattr(p, name)) for name in PATCH_ARRAYS},
        )
        _validate(p, network)
        object.__setattr__(self, "patch", p)
        object.__setattr__(self, "network", network)

    @property
    def grid(self) -> EvolutionGrid:
        return self.patch.source.grid

    def arrays(self) -> dict[str, NDArray[Any]]:
        p = self.patch
        return {
            **{name: getattr(p, name) for name in PATCH_ARRAYS},
            "source_m": p.source.ground_m,
            "cap_m": p.cap_field.ground_m,
            "hard_points_m": p.hard.points_m,
            "hard_heights_m": p.hard.heights_m,
            "coordinates_m": self.network.coordinates_m,
            "receivers": self.network.receivers,
        }

    def identity(self) -> str:
        from dataclasses import asdict

        return sha256(
            canonical_json(
                {
                    "model": FEATURE_MODEL_ID,
                    "patch_model": self.patch.model_id,
                    "parent": self.parent_identity,
                    "grid": asdict(self.grid),
                    "mode": self.patch.mode,
                    "settings": asdict(self.patch.settings),
                    "protected_bounds_m": self.patch.protected_bounds_m,
                    "head_transitions": [asdict(t) for t in self.patch.head_transitions],
                    "arrays": {k: numeric_hash(v) for k, v in self.arrays().items()},
                }
            )
        ).hexdigest()

    def sample(
        self, x: FloatArray, y: FloatArray, *, batch_points: int = MAX_BATCH_POINTS
    ) -> NDArray[np.float32]:
        if type(batch_points) is not int or not 1 <= batch_points <= MAX_BATCH_POINTS:
            raise ValueError("Feature query batch must contain 1-8,192 points.")
        x, y = np.asarray(x), np.asarray(y)
        shape = np.broadcast_shapes(x.shape, y.shape)
        if max(prod(shape), x.size, y.size) > MAX_QUERY_POINTS:
            raise ValueError("Feature query exceeds 262,144 points.")
        if x.dtype.kind not in "fiu" or y.dtype.kind not in "fiu":
            raise ValueError("Feature queries require real numeric coordinates.")
        # Check sizes before a dtype conversion can materialize a large strided view.
        x, y = x.astype(np.float64, copy=False), y.astype(np.float64, copy=False)
        if (
            not np.all(np.isfinite(x))
            or not np.all(np.isfinite(y))
            or np.any(x < 0)
            or np.any(x > self.grid.width_m)
            or np.any(y < 0)
            or np.any(y > self.grid.height_m)
        ):
            raise ValueError("Feature queries must be finite and inside the metric domain.")
        x, y = np.broadcast_arrays(x, y)
        xx, yy = x.ravel(), y.ravel()
        out = np.empty(x.size, dtype=np.float32)
        for start in range(0, x.size, batch_points):
            end = start + batch_points
            out[start:end] = self.patch.sample(xx[start:end], yy[start:end])
        if not np.all(np.isfinite(out)):
            raise ValueError("Feature query produced nonfinite ground.")
        return out.reshape(shape)
