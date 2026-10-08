# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Reopen a completed planet build as a verified parent for regional detail."""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from dmtools.terrain.adapters.build import canonical_json, file_sha256
from dmtools.terrain.adapters.planet_build import PLANET_BUILD_SCHEMA, PLANET_BUILD_VERSION
from dmtools.terrain.adapters.world_project import read_world_project
from dmtools.terrain.domain.planet import PlanetClimateSettings, PlanetSettings
from dmtools.terrain.pipeline.planet_mesh import mesh_from_triangles
from dmtools.terrain.pipeline.planet_regional import RegionalParent
from dmtools.terrain.pipeline.planet_volcanism import Volcanoes
from dmtools.terrain.pipeline.world import prepare_world_map

MAX_MANIFEST_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class LoadedPlanet:
    path: Path
    build_sha256: str
    parent: RegionalParent


def read_planet_parent(path: Path) -> LoadedPlanet:
    """Verify the manifest and output hashes, then rebuild the parent fields."""
    manifest_path = path / "manifest.json" if path.is_dir() else path
    folder = manifest_path.parent
    raw = manifest_path.read_bytes()
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("Planet manifest is too large.")
    manifest = json.loads(raw)
    if (
        manifest.get("schema") != PLANET_BUILD_SCHEMA
        or manifest.get("version") != PLANET_BUILD_VERSION
    ):
        raise ValueError("Not a current planet build; generate the planet again.")
    claimed = manifest.pop("build_sha256", None)
    from hashlib import sha256

    if sha256(canonical_json(manifest)).hexdigest() != claimed:
        raise ValueError("Planet manifest does not match its build hash.")
    for name in ("world.dmworld.json", "planet.npz"):
        record = manifest["outputs"].get(name)
        if record is None or file_sha256(folder / name) != record["sha256"]:
            raise ValueError(f"Planet build file {name} is missing or changed.")
    settings_doc = dict(manifest["settings"])
    climate = PlanetClimateSettings(**settings_doc.pop("climate"))
    settings = PlanetSettings(**settings_doc, climate=climate)
    world = prepare_world_map(read_world_project(folder / "world.dmworld.json"))
    radius_m = float(manifest["world_frame"]["radius_km"]) * 1000
    with np.load(folder / "planet.npz", allow_pickle=False) as data:
        mesh = mesh_from_triangles(
            data["xyz"].astype(np.float64), data["triangles"].astype(np.int64), radius_m
        )
        land = data["land"].astype(bool)
        parent = RegionalParent(
            world=world,
            settings=settings,
            mesh=mesh,
            land=land,
            surface_m=np.where(land, data["water_surface_m"].astype(np.float64), 0.0),
            steady_uplift=data["steady_uplift_m_per_yr"].astype(np.float64),
            pulse_uplift=data["pulse_uplift_m_per_yr"].astype(np.float64),
            erodibility=data["erodibility"].astype(np.float64),
            runoff_weight=(
                data["runoff_weight"].astype(np.float64) if "runoff_weight" in data else None
            ),
            receiver=data["receiver"].astype(np.int64),
            area_m2=data["contributing_area_m2"].astype(np.float64),
            temperature_c=(
                data["temperature_c"].astype(np.float64) if "temperature_c" in data else None
            ),
            precipitation_mm=(
                data["precipitation_mm"].astype(np.float64) if "precipitation_mm" in data else None
            ),
            biome=data["biome"].astype(np.int8) if "biome" in data else None,
            warm_season_c=(
                data["warm_season_c"].astype(np.float64) if "warm_season_c" in data else None
            ),
            coast_m=data["coast_distance_m"].astype(np.float64),
            sea_floor_m=np.where(land, 0.0, data["elevation_m"].astype(np.float64)),
            basin_depth_m=(
                data["basin_depth_m"].astype(np.float64) if "basin_depth_m" in data else None
            ),
            volcanic_m=data["volcanic_m"].astype(np.float64),
            volcanoes=Volcanoes(
                data["volcano_xyz"].astype(np.float64),
                data["volcano_height_m"].astype(np.float64),
                data["volcano_radius_m"].astype(np.float64),
                data["volcano_kind"].astype(np.int64),
                data["volcano_setting"].astype(np.int64),
                data["volcano_active"].astype(bool),
                data["volcano_age_myr"].astype(np.float64),
                data["volcano_caldera_radius_m"].astype(np.float64),
                data["volcano_caldera_depth_m"].astype(np.float64),
            ),
            lake=data["lake"].astype(np.int64),
            lake_level_m=data["lake_level_m"].astype(np.float64),
            lake_endorheic=data["lake_endorheic"].astype(bool),
            precip_warm_mm=(
                data["precipitation_warm_half_mm"].astype(np.float64)
                if "precipitation_warm_half_mm" in data
                else None
            ),
        )
    return LoadedPlanet(folder, str(claimed), parent)
