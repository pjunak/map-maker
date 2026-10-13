# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Reopen a completed planet build as a verified parent for regional detail."""

import itertools
import json
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from dmtools.terrain.adapters.build import canonical_json, file_sha256
from dmtools.terrain.adapters.planet_build import (
    AGING_KINDS,
    PLANET_BUILD_SCHEMA,
    PLANET_BUILD_VERSION,
)
from dmtools.terrain.adapters.world_project import read_world_project
from dmtools.terrain.domain.planet import PlanetClimateSettings, PlanetSettings
from dmtools.terrain.pipeline.planet_aging import AgedPatch, Aging
from dmtools.terrain.pipeline.planet_eruptions import Eruptions
from dmtools.terrain.pipeline.planet_ice import IceSheets
from dmtools.terrain.pipeline.planet_mesh import mesh_from_triangles
from dmtools.terrain.pipeline.planet_regional import RegionalParent
from dmtools.terrain.pipeline.planet_scarps import Cliffs, Tepuis
from dmtools.terrain.pipeline.planet_volcanism import Volcanoes
from dmtools.terrain.pipeline.planet_waters import Forks, Oases
from dmtools.terrain.pipeline.planet_wonders import Chasms, Craters, Wonders
from dmtools.terrain.pipeline.world import prepare_world_map

type F64 = NDArray[np.float64]

MAX_MANIFEST_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class LoadedPlanet:
    path: Path
    build_sha256: str
    parent: RegionalParent


def verified_build(path: Path, files: tuple[str, ...]) -> tuple[Path, dict[str, Any]]:
    """The build folder and its manifest, after checking the build hash and ``files``."""
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
    if sha256(canonical_json(manifest)).hexdigest() != claimed:
        raise ValueError("Planet manifest does not match its build hash.")
    manifest["build_sha256"] = claimed
    for name in files:
        record = manifest["outputs"].get(name)
        if record is None:
            raise ValueError(f"This planet build has no {name}.")
        if file_sha256(folder / name) != record["sha256"]:
            raise ValueError(f"Planet build file {name} is missing or changed.")
    return folder, manifest



def paths_from_archive(
    data: Mapping[str, NDArray[Any]], name: str
) -> tuple[tuple[F64, ...], tuple[F64, ...]]:
    """Paths and their per-vertex profiles, split at the archived offsets."""
    spans = tuple(itertools.pairwise(data[f"{name}_offsets"].tolist()))
    return (
        tuple(data[f"{name}_xyz"][a:b].astype(np.float64) for a, b in spans),
        tuple(data[f"{name}_profile"][a:b].astype(np.float64) for a, b in spans),
    )

def read_planet_parent(path: Path) -> LoadedPlanet:
    """Verify the manifest and output hashes, then rebuild the parent fields."""
    folder, manifest = verified_build(path, ("world.dmworld.json", "planet.npz"))
    claimed = manifest["build_sha256"]
    settings_doc = dict(manifest["settings"])
    climate = PlanetClimateSettings(**settings_doc.pop("climate"))
    settings_doc["wonders"] = tuple(settings_doc["wonders"])
    settings = PlanetSettings(**settings_doc, climate=climate)
    world = prepare_world_map(read_world_project(folder / "world.dmworld.json"))
    radius_m = float(manifest["world_frame"]["radius_km"]) * 1000
    with np.load(folder / "planet.npz", allow_pickle=False) as data:
        mesh = mesh_from_triangles(
            data["xyz"].astype(np.float64), data["triangles"].astype(np.int64), radius_m
        )
        land = data["land"].astype(bool)
        chasm_paths, chasm_depths = paths_from_archive(data, "chasm")
        cliff_paths, cliff_troughs = paths_from_archive(data, "cliff")
        parent = RegionalParent(
            world=world,
            settings=settings,
            mesh=mesh,
            land=land,
            surface_m=np.where(
                land | data["volcanic_island"].astype(bool),
                data["water_surface_m"].astype(np.float64),
                0.0,
            ),
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
            wonder_m=data["wonder_m"].astype(np.float64),
            ice=(
                IceSheets(
                    data["ice_m"].astype(np.float64), data["ice_balance_m"].astype(np.float64)
                )
                if "ice_m" in data
                else None
            ),
            wonders=Wonders(
                Craters(
                    data["crater_xyz"].astype(np.float64).reshape(-1, 3),
                    data["crater_radius_m"].astype(np.float64),
                    data["crater_depth_m"].astype(np.float64),
                ),
                Chasms(chasm_paths, data["chasm_width_m"].astype(np.float64), chasm_depths),
                Cliffs(cliff_paths, data["cliff_height_m"].astype(np.float64), cliff_troughs),
                Tepuis(
                    data["tepui_xyz"].astype(np.float64).reshape(-1, 3),
                    data["tepui_radius_m"].astype(np.float64),
                    data["tepui_height_m"].astype(np.float64),
                    data["tepui_aspect"].astype(np.float64),
                    data["tepui_azimuth"].astype(np.float64),
                ),
                Eruptions(
                    paths_from_archive(data, "lava")[0],
                    data["lava_width_m"].astype(np.float64),
                    data["lava_fresh"].astype(np.float64),
                    data["vent_xyz"].astype(np.float64).reshape(-1, 3),
                    data["vent_radius_m"].astype(np.float64),
                    data["plume_azimuth"].astype(np.float64),
                    data["plume_length_m"].astype(np.float64),
                ),
                Oases(
                    data["oasis_xyz"].astype(np.float64).reshape(-1, 3),
                    data["oasis_radius_m"].astype(np.float64),
                ),
                Forks(
                    data["fork_split_xyz"].astype(np.float64).reshape(-1, 3),
                    data["fork_branch_xyz"].astype(np.float64).reshape(-1, 3),
                    data["fork_discharge_m3_s"].astype(np.float64),
                    data["fork_area_m2"].astype(np.float64),
                ),
                Aging(tuple(
                    AgedPatch(
                        xyz, relief, float(spacing), float(age),
                        centre.astype(np.float64), float(reach), AGING_KINDS[int(kind)],
                        tuple(int(m) for m in data["aging_members"][a:b]),
                    )
                    for xyz, relief, spacing, age, centre, reach, kind, (a, b) in zip(
                        *paths_from_archive(data, "aging"), data["aging_spacing_m"],
                        data["aging_age_myr"], data["aging_centre"].reshape(-1, 3),
                        data["aging_reach_m"], data["aging_kind"],
                        itertools.pairwise(data["aging_member_offsets"].tolist()),
                        strict=True,
                    )
                )),
            ),
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
                data["volcano_summit_m"].astype(np.float64),
                data["volcano_emergent"].astype(bool),
            ),
            lake=data["lake"].astype(np.int64),
            lake_level_m=data["lake_level_m"].astype(np.float64),
            lake_endorheic=data["lake_endorheic"].astype(bool),
            wind_east=(
                data["wind_east_m_s"].astype(np.float64) if "wind_east_m_s" in data else None
            ),
            wind_north=(
                data["wind_north_m_s"].astype(np.float64) if "wind_north_m_s" in data else None
            ),
            flood_basalt=(
                data["flood_basalt"].astype(np.float64) if "flood_basalt" in data else None
            ),
            precip_warm_mm=(
                data["precipitation_warm_half_mm"].astype(np.float64)
                if "precipitation_warm_half_mm" in data
                else None
            ),
        )
    return LoadedPlanet(folder, str(claimed), parent)
