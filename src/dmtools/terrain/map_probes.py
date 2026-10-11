"""Plain-language readouts of what is under the cursor on each kind of map."""

from math import asin, atan2, cos, degrees, isfinite, radians, sin

import numpy as np
from scipy.spatial import KDTree  # pyright: ignore[reportMissingTypeStubs]

from dmtools.terrain.adapters.planet_region import RegionWindow, forward_aeqd
from dmtools.terrain.domain.world_context import EXPOSURE_BEARINGS
from dmtools.terrain.pipeline.planet import PlanetResult
from dmtools.terrain.pipeline.planet_koppen import KOPPEN, KOPPEN_NAMES
from dmtools.terrain.pipeline.planet_volcanism import KINDS as VOLCANO_KINDS
from dmtools.terrain.pipeline.planet_volcanism import SETTINGS as VOLCANO_SETTINGS
from dmtools.terrain.pipeline.world_context import WorldContext


def lonlat_text(longitude_deg: float, latitude_deg: float) -> str:
    return (
        f"{abs(latitude_deg):.2f}° {'N' if latitude_deg >= 0 else 'S'}  "
        f"{abs(longitude_deg):.2f}° {'E' if longitude_deg >= 0 else 'W'}"
    )


class PlanetProbe:
    """Nearest-node description of a planet result under the cursor.

    Building the search tree takes about a second for the finest meshes, so
    create probes off the Tk thread.
    """

    def __init__(self, result: PlanetResult) -> None:
        self.result = result
        self.tree = KDTree(result.mesh.xyz)
        volcanoes = result.volcanoes
        self.volcano_tree = KDTree(volcanoes.xyz) if len(volcanoes) else None

    def describe(self, longitude_deg: float, latitude_deg: float) -> str:
        lon, lat = radians(longitude_deg), radians(latitude_deg)
        point = (cos(lat) * cos(lon), cos(lat) * sin(lon), sin(lat))
        node = int(self.tree.query(point)[1])  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        result = self.result
        volcano = self._volcano(point)
        if not result.land[node]:
            sea = f"Sea · floor {result.elevation_m[node]:,.0f} m (display bathymetry)"
            return sea if volcano is None else f"{sea} · {volcano}"
        lakes = result.lakes
        parts = [f"Ground {result.elevation_m[node]:,.0f} m"]
        lake = int(lakes.lake[node])
        if lake >= 0:
            kind = "closed lake" if lakes.endorheic[lake] else "lake"
            parts.append(f"{kind} surface {lakes.level_m[lake]:,.0f} m")
        flow = float(lakes.discharge_m3_s[node])
        if flow >= 1:
            parts.append(f"river {flow:,.0f} m³/s")
        climate = result.climate
        if climate is not None:
            code = KOPPEN[int(climate.koppen[node])]
            parts.append(
                f"{climate.temperature_c[node]:.0f} °C · "
                f"{climate.precipitation_mm[node]:,.0f} mm/yr · "
                f"{code} {KOPPEN_NAMES.get(code, '')}"
            )
        if volcano is not None:
            parts.append(volcano)
        return " · ".join(parts)

    def _volcano(self, point: tuple[float, float, float]) -> str | None:
        """The volcano whose edifice is under the cursor, if any."""
        if self.volcano_tree is None:
            return None
        v = self.result.volcanoes
        chord, found = self.volcano_tree.query(point)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        index = int(found)  # pyright: ignore[reportUnknownArgumentType]
        distance = 2 * asin(min(float(chord) / 2, 1.0)) * self.result.mesh.radius_m  # pyright: ignore[reportUnknownArgumentType]
        if distance > max(float(v.radius_m[index]), 1.5 * self.result.mesh.spacing_m):
            return None
        state = "active" if v.active[index] else f"extinct ~{v.age_myr[index]:.1f} Myr"
        return (
            f"{state} {VOLCANO_KINDS[int(v.kind[index])]} "
            f"({VOLCANO_SETTINGS[int(v.setting[index])]}, {v.height_m[index]:,.0f} m edifice)"
        )


def context_readout(context: WorldContext, layer: str, bearing: str, u: float, v: float) -> str:
    """The context cell at normalized map position (u across, v down) for ``layer``."""
    rows, columns = context.grid.shape
    col = min(columns - 1, max(0, int(u * columns)))
    row = min(rows - 1, max(0, int(v * rows)))
    if layer == "Shore distance":
        distance = float(context.shore_distance_km[row, col])
        return (
            f"Cell-centre shore distance: {distance:,.1f} km · "
            f"overestimate <= {context.shore_sampling.max_error_km:.2f} km"
            if isfinite(distance)
            else "No shoreline exists in this world"
        )
    if layer in ("Water exposure", "Exposure support"):
        direction = EXPOSURE_BEARINGS.index(bearing)
        return (
            f"Looking {bearing}: "
            f"{context.water_exposure[direction, row, col]:.1%} weighted water · "
            f"{context.exposure_mixed_support[direction, row, col]:.1%} mixed support"
        )
    if layer == "Water connectivity":
        graph = context.connectivity
        cell = row * columns + col
        start, end = map(int, graph.cell_offsets[cell : cell + 2])
        pieces = "; ".join(
            f"#{node}: region {graph.water_body[node]}, {graph.incident_links[node]} intervals"
            for node in range(start, min(end, start + 3))
        )
        detail = f"Cell {row + 1}, {col + 1}: {end - start} water pieces"
        if pieces:
            detail += " · " + pieces + ("; …" if end - start > 3 else "")
        if any(body in graph.fragmented_bodies for body in graph.water_body[start:end]):
            detail += " · unresolved connectivity"
        return detail
    if layer == "Water openings":
        north = context.south_opening_km[row - 1, col] if row else 0.0
        return (
            f"Cell {row + 1}, {col + 1} · longest water opening (km): "
            f"N {north:.2f} · E {context.east_opening_km[row, col]:.2f} · "
            f"S {context.south_opening_km[row, col]:.2f} · "
            f"W {context.east_opening_km[row, (col - 1) % columns]:.2f}"
        )
    return (
        f"Cell {row + 1}, {col + 1}: {context.land_fraction[row, col]:.1%} land · "
        f"water region {context.water_body[row, col]} · "
        + ("mixed/subgrid support" if context.support_flags[row, col] else "single surface")
    )


def _pixel(window: RegionWindow, u: float, v: float) -> tuple[int, int]:
    row = min(window.pixels - 1, max(0, int(v * window.pixels)))
    return row, min(window.pixels - 1, max(0, int(u * window.pixels)))


def window_lonlat(window: RegionWindow, u: float, v: float) -> tuple[float, float]:
    """Longitude and latitude (degrees) at normalized window position (u, v)."""
    row, column = _pixel(window, u, v)
    x, y, z = (float(c) for c in window.points[row * window.pixels + column])
    return degrees(atan2(y, x)), degrees(asin(max(-1.0, min(1.0, z))))


def window_position(window: RegionWindow, lon: float, lat: float) -> tuple[float, float]:
    """Normalized window position (u across, v down) of a longitude and latitude."""
    phi, lam = radians(lat), radians(lon)
    point = np.array([[cos(phi) * cos(lam), cos(phi) * sin(lam), sin(phi)]])
    x, y = forward_aeqd(point, *window.centre, window.planet_m)[0]
    return (float(x) + window.radius_m) / (2 * window.radius_m), (
        window.radius_m - float(y)
    ) / (2 * window.radius_m)


def region_readout(window: RegionWindow, u: float, v: float) -> str:
    """Place, offset from the window centre and the surface at normalized position (u, v)."""
    row, column = _pixel(window, u, v)
    value = float(window.elevation_m[row, column])
    if not np.isfinite(value):
        return "Outside the region"
    x = (column + 0.5) * window.pixel_m - window.radius_m
    y = window.radius_m - (row + 0.5) * window.pixel_m
    where = f"{x / 1000:+,.0f} km E · {y / 1000:+,.0f} km N of centre"
    surface = "ground" if window.land[row, column] else "sea floor"
    lake = " · lake" if window.lakes[row, column] else ""
    place = lonlat_text(*window_lonlat(window, u, v))
    return f"{place}  ·  {where} · {surface} {value:,.0f} m{lake}"
