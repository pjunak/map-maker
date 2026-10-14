"""Current recipe/incision generator on the same rectangular physical extent."""

from dataclasses import asdict, replace
from typing import Any

import numpy as np

from benchmarks.channel_profiles import measure_channels
from benchmarks.evolution.reference import LandlabReference, Snapshot
from benchmarks.evolution.scenarios import EvolutionFields
from map_maker.terrain.domain.evolution import EvolutionEpoch, EvolutionHistory
from map_maker.terrain.domain.models import (
    Coastline,
    LandformSettings,
    TerrainConstraint,
    TerrainRegion,
    TerrainSettings,
    TerrainStructure,
)
from map_maker.terrain.pipeline.generate import prepare_terrain_field


def baseline(
    fields: EvolutionFields, seed: int, angle_deg: float,
) -> tuple[Snapshot, dict[str, Any]]:
    grid = fields.grid
    w, h = grid.width_m/1000., grid.height_m/1000.
    ring = ((0., 0.), (1., 0.), (1., 1.), (0., 1.), (0., 0.))
    coast = Coastline(((0., 0.), (w, 0.), (w, h), (0., h), (0., 0.)), "evolution-rectangle")
    theta = np.deg2rad(angle_deg)
    half = min(20., w*.3, h*.3)
    points = tuple((.48 + t*half*np.cos(theta)/w, .48 - t*half*np.sin(theta)/h)
                   for t in (-1., 1.))
    settings = TerrainSettings(seed=seed, object_scale_km=max(w, h), resolution_px=768,
                               maximum_elevation_m=1600., largest_feature_km=8.,
                               detail_levels=3, coastal_rise_km=8., variability=.35)
    constraints: tuple[TerrainConstraint, ...] = (
        TerrainRegion(ring, LandformSettings(elevation_m=120., relief_m=120.,
                                             feature_size_km=8., transition_km=2.)),
        TerrainStructure("ridge", points, 1300., 10.),
    )
    prepared = prepare_terrain_field(coast, settings, constraints, None)
    y, x = np.meshgrid(np.arange(grid.shape[0], dtype=np.float64)*grid.spacing_m/1000.,
                       np.arange(grid.shape[1], dtype=np.float64)*grid.spacing_m/1000.,
                       indexing="ij")
    values = prepared.sample_ground(x, y).astype(np.float64)
    # The experiment's rectangular perimeter is an explicit zero base level.
    values[~fields.core] = 0.
    comparison_fields = replace(fields, initial_m=values)
    epoch = EvolutionEpoch("baseline-routing", 1., 0.)
    engine = LandlabReference(comparison_fields, EvolutionHistory((epoch,)))
    engine.set_epoch(epoch)
    engine.route()
    automatic = prepared.automatic_valleys
    planned = measure_channels(automatic.x_km, automatic.y_km, automatic.drainage.receivers,
                               automatic.drainage.channel_mask, prepared.sample_ground, stations=17)
    return engine.snapshot("current-generator", 0.), {
        "meaning": "Present-day ridge/plain visual reference; not equal physical forcing",
        "coast": asdict(coast), "settings": asdict(settings),
        "constraints": [asdict(c) for c in constraints],
        "native_planned_channel_profiles": planned,
        "comparison_routing": "same D8/depression mapper as the evolved final DEM",
    }
