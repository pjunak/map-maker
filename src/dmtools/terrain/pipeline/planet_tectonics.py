# pyright: reportUnknownArgumentType=false, reportUnknownVariableType=false
"""Procedural plate tectonics that place belts, active margins, trenches and rifts.

A light version of plate-driven terrain (after Cortial et al. 2019, "Procedural
Tectonic Planets"): the sphere is split into plates (a noise-warped Voronoi of
random seeds), each rotating about its own Euler pole at Earth-like rates. The
relative velocity across each boundary says what happens there:

* convergent boundaries inside continents raise collision orogens, with a
  plateau on the overriding side (Himalaya and Tibet);
* divergent boundaries inside continents open rift valleys (East Africa, Rhine);
* coasts on a plate's leading edge, where the continent moves towards the sea,
  become active margins with coastal ranges and offshore trenches (Andes), and
  trailing edges stay passive (Inman and Nordstrom 1971).

The authored coastline stays authoritative: plates never move land, they only
decide where tectonic uplift and subsidence act.
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from dmtools.terrain.pipeline.planet_climate import surface_gradient, tangent_frame
from dmtools.terrain.pipeline.planet_kernels import multi_source_nearest
from dmtools.terrain.pipeline.planet_mesh import SphereMesh
from dmtools.terrain.pipeline.planet_noise import fbm3

type F64 = NDArray[np.float64]
type I64 = NDArray[np.int64]
type B = NDArray[np.bool_]

PLATE_COUNT = 18
PLUME_COUNT = 8
# Euler-pole angular speeds (degrees per million years): Earth's plates move at
# 0.2-1.3 deg/Myr, i.e. 1-10 cm/yr at the equator of their pole.
MIN_ROTATION_DEG_MYR = 0.25
MAX_ROTATION_DEG_MYR = 1.1
SECONDS_PER_MYR = 1e6


@dataclass(frozen=True, slots=True)
class Tectonics:
    plate: I64  # plate index per node
    velocity_east: F64  # m/yr
    velocity_north: F64  # m/yr
    boundary_m: F64  # distance to the nearest plate boundary
    across_m: F64  # signed distance across that boundary, positive on its foreland side
    convergence: F64  # closing rate at that boundary (m/yr), negative where it opens
    leading: F64  # 0..1 leading-edge strength of the nearest coast (active margin)
    plumes: F64  # (k, 3) fixed mantle-plume (hotspot) positions
    plume_heading: F64  # (k, 3) unit tangent of plate motion over each plume (0 if still)
    plume_speed_m_yr: F64  # plate speed over each plume


def plate_tectonics(mesh: SphereMesh, land: B, coast_m: F64, seed: int) -> Tectonics:
    rng = np.random.default_rng([seed, 4040])
    centres = rng.normal(size=(PLATE_COUNT, 3))
    centres /= np.linalg.norm(centres, axis=1)[:, None]
    poles = rng.normal(size=(PLATE_COUNT, 3))
    poles /= np.linalg.norm(poles, axis=1)[:, None]
    speed = np.deg2rad(rng.uniform(MIN_ROTATION_DEG_MYR, MAX_ROTATION_DEG_MYR, PLATE_COUNT))
    omega = poles * (speed / SECONDS_PER_MYR * 1.0)[:, None]  # rad/yr

    src = np.repeat(np.arange(mesh.size), np.diff(mesh.ptr))
    middle = 0.5 * (mesh.xyz[src] + mesh.xyz[mesh.nbr])
    # Plate boundaries bend and step like real ones instead of tracing great circles.
    warped = mesh.length_m * np.exp(0.7 * fbm3(middle, seed + 4141, 4, 5.0))
    nearest = np.argmax(mesh.xyz @ centres.T, axis=1)
    seeds = np.array([int(np.argmax(mesh.xyz @ c)) for c in centres], dtype=np.int64)
    _, plate = multi_source_nearest(
        seeds, np.arange(PLATE_COUNT, dtype=np.int64), mesh.ptr, mesh.nbr, warped
    )
    plate = np.where(plate >= 0, plate, nearest)

    # Surface velocity v = omega x r (m/yr) in the local east/north frame.
    velocity = np.cross(omega[plate], mesh.xyz) * mesh.radius_m
    east, north = tangent_frame(mesh.xyz)
    v_east = np.einsum("ij,ij->i", velocity, east)
    v_north = np.einsum("ij,ij->i", velocity, north)

    crossing = plate[src] != plate[mesh.nbr]
    a, b = src[crossing], mesh.nbr[crossing]
    normal = mesh.xyz[b] - mesh.xyz[a]
    normal -= np.einsum("ij,ij->i", normal, mesh.xyz[a])[:, None] * mesh.xyz[a]
    normal /= np.maximum(np.linalg.norm(normal, axis=1), 1e-15)[:, None]
    closing: F64 = np.einsum("ij,ij->i", velocity[a] - velocity[b], normal)
    boundary_nodes = np.unique(a)
    convergence_at = np.zeros(mesh.size)
    count = np.zeros(mesh.size)
    np.add.at(convergence_at, a, closing)
    np.add.at(count, a, 1.0)
    convergence_at /= np.maximum(count, 1.0)
    other = np.full(mesh.size, -1, dtype=np.int64)
    other[a] = plate[b]

    distance, label = multi_source_nearest(
        boundary_nodes, boundary_nodes, mesh.ptr, mesh.nbr, mesh.length_m
    )
    label = np.maximum(label, 0)
    convergence = convergence_at[label]
    # Which side of a boundary is the foreland (down-going plate) is a property
    # of the plate pair; the overriding side carries the plateau.
    pair_low = np.minimum(plate[label], other[label])
    pair_high = np.maximum(plate[label], other[label])
    foreland = np.where((pair_low * 7 + pair_high * 13 + seed) % 2 == 0, pair_low, pair_high)
    across = np.where(plate == foreland, distance, -distance)

    leading = _leading_edges(mesh, land, coast_m, velocity, east, north)
    plumes = rng.normal(size=(PLUME_COUNT, 3))
    plumes /= np.linalg.norm(plumes, axis=1)[:, None]
    over = np.argmax(plumes @ mesh.xyz.T, axis=1)
    motion = velocity[over] - np.einsum("ij,ij->i", velocity[over], plumes)[:, None] * plumes
    speed = np.linalg.norm(motion, axis=1)
    heading = motion / np.maximum(speed, 1e-12)[:, None]
    return Tectonics(
        plate, v_east, v_north, distance, across, convergence, leading, plumes, heading, speed
    )


def plume_track(plates: Tectonics, index: int, distance_m: F64, radius_m: float) -> F64:
    """Points ``distance_m`` along a hotspot track: older crust rides with the plate."""
    angle = np.asarray(distance_m, dtype=np.float64) / radius_m
    plume, heading = plates.plumes[index], plates.plume_heading[index]
    return np.cos(angle)[:, None] * plume + np.sin(angle)[:, None] * heading


def _leading_edges(
    mesh: SphereMesh, land: B, coast_m: F64, velocity: F64, east: F64, north: F64
) -> F64:
    """How strongly each coast's plate drives its land seaward (0..1), spread from the coast."""
    gradient_east, gradient_north = surface_gradient(mesh, coast_m, east, north)
    norm = np.maximum(np.hypot(gradient_east, gradient_north), 1e-12)
    # On land, coast distance grows inland, so -grad points to the sea.
    seaward_east, seaward_north = -gradient_east / norm, -gradient_north / norm
    v_east = np.einsum("ij,ij->i", velocity, east)
    v_north = np.einsum("ij,ij->i", velocity, north)
    push = (v_east * seaward_east + v_north * seaward_north) / 0.04  # 4 cm/yr -> 1
    src = np.repeat(np.arange(mesh.size), np.diff(mesh.ptr))
    coastal = np.unique(src[land[src] & ~land[mesh.nbr]])
    if not len(coastal):
        return np.zeros(mesh.size)
    _, label = multi_source_nearest(coastal, coastal, mesh.ptr, mesh.nbr, mesh.length_m)
    return np.clip(push[np.maximum(label, 0)], 0.0, 1.0)
