# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Suggested sites for wonders on a planet without them (ADR-0099).

Each kind's candidates come from its random placer, drawn from sub-streams of
their own stage seed, so they are drawn as random wonders are and the same draws
give the same places at every mesh resolution. Each candidate is then scored by
what the planet is like there: a stated hypothesis about where such a landform
would form or survive, never a claim that it would. The best few of each kind are
suggested, well apart, each with the reason for its score.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import KDTree

from map_maker.terrain.domain.seeds import stage_seed
from map_maker.terrain.domain.wonders import WONDER_KINDS, WonderKind
from map_maker.terrain.pipeline.planet import PlanetBase, PlanetGround
from map_maker.terrain.pipeline.planet_mesh import sample_field
from map_maker.terrain.pipeline.planet_scarps import place_cliff, tepui_group
from map_maker.terrain.pipeline.planet_volcanism import ARC, wonder_volcanoes
from map_maker.terrain.pipeline.planet_waters import (
    deserts,
    fork_candidates,
    place_oases,
    river_outlets,
)
from map_maker.terrain.pipeline.planet_wonders import place_chasm, place_craters
from map_maker.terrain.pipeline.wonder_geometry import footprint

type F64 = NDArray[np.float64]
type B = NDArray[np.bool_]

SUGGESTION_STAGE_ID = "planet.wonder-suggestions"
DRAWS = 8  # candidate draws per kind, each from its own sub-stream
PER_KIND = 4  # suggestions kept per kind
APART_M = 400e3  # suggestions of one kind stand at least this far apart
NEAR_M = 1500e3  # how far a plume, an arc or a range still counts as near


@dataclass(frozen=True, slots=True)
class WonderSuggestion:
    """A plausible site for one wonder, with why it suits the place."""

    kind: WonderKind
    xyz: F64  # unit vector; the first end of a two-ended wonder
    end: F64 | None  # the far end of a two-ended wonder
    size_m: float | None  # what the kind's size measures (diameter, width or height)
    score: float  # 0..1, how well the place fits the hypothesis
    reason: str  # what about the place suits it, in a phrase


@dataclass(frozen=True, slots=True)
class _Candidate:
    xyz: F64
    end: F64 | None
    size_m: float | None
    extra: float = 0.0  # kind-specific measure the scorer needs (e.g. discharge)


def suggest_wonders(
    base: PlanetBase, kinds: tuple[WonderKind, ...] = WONDER_KINDS
) -> tuple[WonderSuggestion, ...]:
    """The best few plausible sites for each of ``kinds``, best first within a kind."""
    ground = base.ground
    site = _SiteFacts(base)
    seed = stage_seed(ground.settings.seed, SUGGESTION_STAGE_ID)
    out: list[WonderSuggestion] = []
    for kind in kinds:
        scored = [
            (score, reason, candidate)
            for candidate in _CANDIDATES[kind](base, seed)
            for score, reason in (_SCORERS[kind](site, candidate),)
        ]
        scored.sort(key=lambda item: -item[0])
        kept: list[F64] = []
        for score, reason, candidate in scored:
            if any(float(candidate.xyz @ other) > np.cos(APART_M / ground.mesh.radius_m)
                   for other in kept):
                continue
            kept.append(candidate.xyz)
            out.append(WonderSuggestion(
                kind, candidate.xyz, candidate.end, candidate.size_m, round(score, 3), reason
            ))
            if len(kept) == PER_KIND:
                break
    return tuple(out)


# Candidates: each kind's random placer, drawn from sub-streams and kept clear of
# the candidates drawn before it.


def _rng(seed: int, code: int, draw: int) -> np.random.Generator:
    return np.random.default_rng([seed, code, draw])


def _craters(base: PlanetBase, seed: int) -> list[_Candidate]:
    g = base.ground
    blocked = np.zeros(g.mesh.size, dtype=bool)
    out: list[_Candidate] = []
    for draw in range(DRAWS):
        craters = place_craters(
            g.mesh, g.land, g.coast_m, g.ground_m, _rng(seed, 9090, draw), blocked
        )
        blocked |= footprint(g.mesh, craters.xyz, 2.0 * craters.radius_m)
        out += [_Candidate(xyz, None, 2 * float(r)) for xyz, r in
                zip(craters.xyz, craters.radius_m, strict=True)]
    return out


def _chasms(base: PlanetBase, seed: int) -> list[_Candidate]:
    g = base.ground
    blocked = np.zeros(g.mesh.size, dtype=bool)
    out: list[_Candidate] = []
    for draw in range(DRAWS):
        chasms = place_chasm(
            g.mesh, g.land, g.coast_m, g.ground_m, _rng(seed, 9191, draw), blocked
        )
        if not len(chasms):
            continue
        axis, width = chasms.paths[0], float(chasms.width_m[0])
        blocked |= footprint(g.mesh, axis[::8], np.full(len(axis[::8]), 3 * width))
        out.append(_Candidate(axis[0], axis[-1], width, float(chasms.depth_m[0].mean())))
    return out


def _cliffs(base: PlanetBase, seed: int) -> list[_Candidate]:
    g = base.ground
    blocked = np.zeros(g.mesh.size, dtype=bool)
    out: list[_Candidate] = []
    for draw in range(DRAWS):
        cliffs = place_cliff(
            g.mesh, g.land, g.coast_m, g.ground_m, _rng(seed, 9292, draw), blocked
        )
        if not len(cliffs):
            continue
        path = cliffs.paths[0]
        blocked |= footprint(g.mesh, path[::4], np.full(len(path[::4]), 150e3))
        out.append(_Candidate(path[0], path[-1], float(cliffs.height_m[0])))
    return out


def _tepuis(base: PlanetBase, seed: int) -> list[_Candidate]:
    g = base.ground
    blocked = np.zeros(g.mesh.size, dtype=bool)
    out: list[_Candidate] = []
    for draw in range(DRAWS):
        group = tepui_group(g.mesh, g.land, g.coast_m, _rng(seed, 9393, draw), blocked)
        if not len(group):
            continue
        blocked |= footprint(g.mesh, group.xyz, np.full(len(group), APART_M))
        largest = int(np.argmax(group.radius_m))  # a group is suggested by its largest
        out.append(_Candidate(group.xyz[largest], None, 2 * float(group.radius_m[largest])))
    return out


def _oases(base: PlanetBase, seed: int) -> list[_Candidate]:
    g = base.ground
    if g.climate is None:
        return []
    c = g.climate
    eligible = deserts(g.land, c.precipitation_mm, c.pet_mm, c.temperature_c) & (
        g.coast_m > 60e3
    )
    out: list[_Candidate] = []
    for draw in range(DRAWS):
        oases = place_oases(g.mesh, eligible, _rng(seed, 9494, draw))
        eligible &= ~footprint(g.mesh, oases.xyz, np.full(len(oases), APART_M))
        out += [_Candidate(xyz, None, 2 * float(r)) for xyz, r in
                zip(oases.xyz, oases.radius_m, strict=True)]
    return out


def _volcano(kind: WonderKind) -> Callable[[PlanetBase, int], list[_Candidate]]:
    def candidates(base: PlanetBase, seed: int) -> list[_Candidate]:
        g = base.ground
        out: list[_Candidate] = []
        for draw in range(DRAWS):
            volcano = wonder_volcanoes(
                g.mesh, g.land, g.coast_m, stage_seed(seed, f"{kind}.{draw}"), (kind,)
            )
            out += [_Candidate(xyz, None, 2 * float(r)) for xyz, r in
                    zip(volcano.xyz, volcano.radius_m, strict=True)]
        return out

    return candidates


def _forks(base: PlanetBase, seed: int) -> list[_Candidate]:
    del seed  # forks are found, not drawn: the best low divides of the largest rivers
    g, planet = base.ground, base.planet
    elevation = np.where(g.land, g.ground_m + planet.volcanic_m, g.ground_m)
    u, _, _ = fork_candidates(g.mesh, g.land, g.coast_m, elevation, planet.lakes)
    out: list[_Candidate] = []
    rivers: set[int] = set()
    outlet = river_outlets(planet.lakes.flow.receiver)
    for node in u[: 50 * DRAWS].tolist():
        if outlet[node] in rivers:  # one fork per river
            continue
        rivers.add(int(outlet[node]))
        out.append(_Candidate(g.mesh.xyz[node], None, None,
                              float(planet.lakes.discharge_m3_s[node])))
        if len(out) == DRAWS:
            break
    return out


_CANDIDATES: dict[WonderKind, Callable[[PlanetBase, int], list[_Candidate]]] = {
    "titan": _volcano("titan"),
    "shattered": _volcano("shattered"),
    "active": _volcano("active"),
    "crater": _craters,
    "chasm": _chasms,
    "cliff": _cliffs,
    "tepui": _tepuis,
    "oasis": _oases,
    "fork": _forks,
}


# Scores: what the planet is like at a candidate, as 0..1 factors with reasons.


class _SiteFacts:
    """The base planet's fields at a point, as the scorers read them."""

    def __init__(self, base: PlanetBase) -> None:
        g: PlanetGround = base.ground
        self.ground = g
        self.tree = KDTree(g.mesh.xyz)
        land_uplift = g.forcing.steady_uplift[g.land]
        self.uplift_scale = max(float(np.percentile(land_uplift, 90)), 1e-9) if len(
            land_uplift
        ) else 1.0
        plates = g.forcing.tectonics
        self.plumes = None if plates is None or not len(plates.plumes) else plates.plumes
        volcanoes = g.volcanoes
        on_land = g.land[self._nodes(volcanoes.xyz)] if len(volcanoes) else np.zeros(0, bool)
        self.arcs = volcanoes.xyz[on_land & (volcanoes.setting == ARC)]
        self.active = volcanoes.xyz[on_land & volcanoes.active]
        self.max_discharge = max(float(base.planet.lakes.discharge_m3_s.max(initial=0.0)), 1.0)

    def _nodes(self, xyz: F64) -> NDArray[np.int64]:
        return np.asarray(self.tree.query(np.atleast_2d(xyz))[1], dtype=np.int64)

    def node(self, xyz: F64) -> int:
        return int(self._nodes(xyz)[0])

    def km(self, a: F64, others: F64 | None) -> float | None:
        """Distance (km) from ``a`` to the nearest of ``others``."""
        if others is None or not len(others):
            return None
        angle = float(np.arccos(np.clip((others @ a).max(), -1, 1)))
        return angle * self.ground.mesh.radius_m / 1e3

    def setting(self, xyz: F64) -> str | None:
        regions = self.ground.regions
        if regions is None:
            return None
        index = int(regions.region[self.node(xyz)])
        return None if index < 0 else regions.settings[index]

    def stable(self, xyz: F64) -> float:
        """1 on old, quiet crust that barely rises; 0 where it rises fastest."""
        setting = self.setting(xyz)
        if setting == "stable-interior":
            return 1.0
        if setting in ("active-belt", "volcanic"):
            return 0.1
        uplift = float(self.ground.forcing.steady_uplift[self.node(xyz)])
        return float(np.clip(1 - uplift / self.uplift_scale, 0, 1))

    def aridity(self, xyz: F64) -> float | None:
        """Precipitation over potential evaporation; None without a climate."""
        c = self.ground.climate
        if c is None:
            return None
        node = self.node(xyz)
        return float(c.precipitation_mm[node] / max(float(c.pet_mm[node]), 1.0))

    def temperature(self, xyz: F64) -> float | None:
        c = self.ground.climate
        return None if c is None else float(c.temperature_c[self.node(xyz)])

    def height(self, xyz: F64) -> float:
        return float(self.ground.ground_m[self.node(xyz)])

    def coast_km(self, xyz: F64) -> float:
        return float(self.ground.coast_m[self.node(xyz)]) / 1e3

    def highest_near(self, xyz: F64, reach_m: float) -> float:
        g = self.ground
        near = self.tree.query_ball_point(xyz, 2 * np.sin(reach_m / g.mesh.radius_m / 2))
        return float(g.ground_m[near].max()) if near else self.height(xyz)


def _near(km: float | None) -> float:
    """1 at the place, falling to 0 at ``NEAR_M``."""
    return 0.0 if km is None else float(np.clip(1 - km * 1e3 / NEAR_M, 0, 1))


def _summary(factors: list[tuple[float, str]], fallback: str) -> tuple[float, str]:
    """The mean of the factors and the phrases of the strong ones."""
    score = float(np.mean([value for value, _ in factors])) if factors else 0.0
    strong = [text for value, text in sorted(factors, key=lambda f: -f[0]) if value >= 0.5]
    return score, "; ".join(strong) or fallback


def _crater_score(site: _SiteFacts, c: _Candidate) -> tuple[float, str]:
    # Craters survive where crust is old and stable and erosion is slow (Earth's
    # preserved large craters lie on cratons, most in dry country).
    factors = [(site.stable(c.xyz), "old, stable crust that keeps craters")]
    aridity = site.aridity(c.xyz)
    if aridity is not None:
        factors.append((float(np.clip(1 - aridity, 0, 1)), "dry, so erosion is slow"))
    return _summary(factors, f"inland at {site.height(c.xyz):,.0f} m")


def _chasm_score(site: _SiteFacts, c: _Candidate) -> tuple[float, str]:
    # Great chasms open where the crust pulls apart, or on high plateaus (Valles
    # Marineris splits the Tharsis rise).
    g = site.ground
    node = site.node(c.xyz)
    plates = g.forcing.tectonics
    rift = 1.0 if site.setting(c.xyz) == "rift" else 0.0
    if plates is not None:
        opening = float(np.clip(-plates.convergence[node] / 0.01, 0, 1))
        rift = max(rift, opening * _near(float(plates.boundary_m[node]) / 1e3))
    plateau = float(np.clip((site.height(c.xyz) - 800.0) / 1500.0, 0, 1))
    factors = [
        (rift, "crust pulling apart nearby"),
        (plateau, f"a high plateau at {site.height(c.xyz):,.0f} m"),
        (float(np.clip(c.extra / 2000.0, 0, 1)), f"cut {c.extra:,.0f} m deep on average"),
    ]
    return _summary(factors, "deep ground well inland")


def _cliff_score(site: _SiteFacts, c: _Candidate) -> tuple[float, str]:
    # Great escarpments mark a step between high and low country.
    assert c.end is not None
    g = site.ground
    middle = c.xyz + c.end
    middle /= np.linalg.norm(middle)
    normal = np.cross(middle, c.end - c.xyz)
    normal /= max(float(np.linalg.norm(normal)), 1e-12)
    reach = 100e3 / g.mesh.radius_m
    sides = np.stack([np.cos(reach) * middle + s * np.sin(reach) * normal for s in (1, -1)])
    left, right = sample_field(g.mesh, sides, g.ground_m)
    step = abs(float(left - right))
    factors = [(float(np.clip(step / 1000.0, 0, 1)), f"the land steps {step:,.0f} m across it")]
    if site.setting(c.xyz) == "rift":
        factors.append((1.0, "a rift's faults"))
    return _summary(factors, "a long stretch of open country")


def _tepui_score(site: _SiteFacts, c: _Candidate) -> tuple[float, str]:
    # Tepuis are sandstone tablelands of old shields in the wet tropics (Guiana Shield).
    factors = [(site.stable(c.xyz), "an old shield")]
    aridity, warm = site.aridity(c.xyz), site.temperature(c.xyz)
    if aridity is not None and warm is not None:
        wet = float(np.clip((aridity - 0.6) / 0.8, 0, 1))
        hot = float(np.clip((warm - 10.0) / 12.0, 0, 1))
        factors.append((min(wet, hot), "wet and warm, like the Guiana Shield"))
    return _summary(factors, "inland country")


def _titan_score(site: _SiteFacts, c: _Candidate) -> tuple[float, str]:
    # A shield of that size needs a mantle plume under a slowly moving plate, far inland.
    plume = site.km(c.xyz, site.plumes)
    inland = float(np.clip(site.coast_km(c.xyz) / 1500.0, 0, 1))
    factors = [
        (_near(plume), "a mantle plume beneath" if plume is not None and plume < 300
         else f"a mantle plume {plume or 0:,.0f} km away"),
        (inland, f"{site.coast_km(c.xyz):,.0f} km from the sea"),
    ]
    return _summary(factors, "deep inland")


def _arc_score(site: _SiteFacts, c: _Candidate) -> tuple[float, str]:
    # Explosive collapses happen on arc volcanoes, fed by subducted water.
    arc = site.km(c.xyz, site.arcs)
    factors = [(_near(arc), f"an arc of volcanoes {arc or 0:,.0f} km away")]
    if site.setting(c.xyz) in ("volcanic", "active-belt"):
        factors.append((1.0, "a volcanic province"))
    return _summary(factors, "far from other volcanoes")


def _active_score(site: _SiteFacts, c: _Candidate) -> tuple[float, str]:
    # A giant erupting volcano fits among other active volcanoes or over a plume.
    active, plume = site.km(c.xyz, site.active), site.km(c.xyz, site.plumes)
    factors = [
        (_near(active), f"active volcanoes {active or 0:,.0f} km away"),
        (_near(plume), f"a mantle plume {plume or 0:,.0f} km away"),
    ]
    return _summary(factors, "far from other volcanoes")


def _oasis_score(site: _SiteFacts, c: _Candidate) -> tuple[float, str]:
    # Springs in deserts are fed by groundwater from rain on nearby mountains.
    aridity = site.aridity(c.xyz) or 0.0
    highest = site.highest_near(c.xyz, 300e3)
    factors = [
        (float(np.clip(1 - aridity / 0.15, 0, 1)), "deep desert"),
        (float(np.clip((highest - site.height(c.xyz) - 500.0) / 1500.0, 0, 1)),
         f"mountains up to {highest:,.0f} m nearby feed its spring"),
    ]
    return _summary(factors, "a hot desert")


def _fork_score(site: _SiteFacts, c: _Candidate) -> tuple[float, str]:
    # The largest rivers make the most striking divided rivers.
    share = float(np.sqrt(c.extra / site.max_discharge))
    return float(np.clip(share, 0, 1)), f"a river of {c.extra:,.0f} m³/s on a low divide"


_SCORERS: dict[WonderKind, Callable[[_SiteFacts, _Candidate], tuple[float, str]]] = {
    "titan": _titan_score,
    "shattered": _arc_score,
    "active": _active_score,
    "crater": _crater_score,
    "chasm": _chasm_score,
    "cliff": _cliff_score,
    "tepui": _tepui_score,
    "oasis": _oasis_score,
    "fork": _fork_score,
}
