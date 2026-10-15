# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
"""A planet's map themes on the world frame, each drawn the first time it is needed.

Every registered theme (``map_views.THEMES``) has a painter here. The rasters,
display relief and rivers that the themes share are computed with the first map,
so each later map costs only its own colouring. The app draws the map it shows
first and the others when they are chosen; a build draws them all.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, replace

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from map_maker.terrain.adapters.map_thematic import (
    basins_image,
    geology_image,
    plates_image,
    sea_floor_age_image,
)
from map_maker.terrain.adapters.map_topographic import topographic_image
from map_maker.terrain.adapters.map_views import THEME_BY_ID, THEME_BY_LABEL, THEMES, MapTheme
from map_maker.terrain.adapters.planet_natural import (
    DisplayFields,
    compose,
    display_fields,
    natural_colour,
    planet_parchment,
    relief_colour,
    river_layer,
    sea_colour,
    volcano_markers,
)
from map_maker.terrain.adapters.planet_render import (
    RAIN_COLOURS,
    TEMPERATURE_COLOURS,
    PlanetRasters,
    koppen_image,
    planet_rasters,
    river_threshold_m3_s,
    scalar_image,
)
from map_maker.terrain.pipeline.planet import PlanetResult
from map_maker.terrain.pipeline.planet_tectonics import Tectonics

type F64 = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class MapInputs:
    """What every theme is drawn from: frame rasters, display relief and rivers."""

    result: PlanetResult
    rasters: PlanetRasters  # with no lakes under ice sheets
    fields: DisplayFields
    rivers: F64  # 0..1 river coverage, none on ice sheets
    sea: F64  # ocean colour


def map_inputs(result: PlanetResult, rasters: PlanetRasters, threshold_m3_s: float) -> MapInputs:
    land_px = rasters.land_px
    fields = display_fields(
        result, rasters.raster, land_px,
        np.where(land_px, rasters.elevation_m, 0.0), np.where(land_px, 0.0, rasters.elevation_m),
        rasters.islands_px,
    )
    # No rivers or lakes show on ice sheets.
    rivers = river_layer(result, rasters.raster, threshold_m3_s) * (1 - fields.ice.cover)
    rasters = replace(rasters, lakes_px=np.where(fields.ice.covered, -1, rasters.lakes_px))
    return MapInputs(result, rasters, fields, rivers, sea_colour(fields))


def shows(result: PlanetResult, theme: MapTheme) -> bool:
    """Whether the planet has what ``theme`` maps."""
    if theme.needs_climate and result.climate is None:
        return False
    if theme.id == "volcanoes":
        return bool(len(result.volcanoes))
    if theme.id in ("plates", "seafloor"):
        return result.forcing.tectonics is not None
    return True


class PlanetMaps:
    """The maps a planet can show at one width, each drawn once when first asked for.

    Thread-safe: views draw missing maps on worker threads while others read the
    drawn ones. The shared inputs are released once every map is drawn.
    """

    def __init__(self, result: PlanetResult, width: int, river_km2: float) -> None:
        self.result = result
        self.width = width
        self.river_km2 = river_km2
        self.labels = tuple(theme.label for theme in THEMES if shows(result, theme))
        self._images: dict[str, Image.Image] = {}
        self._rasters: PlanetRasters | None = None
        self._inputs: MapInputs | None = None
        self._lock = threading.RLock()

    @property
    def rasters(self) -> PlanetRasters:
        """The frame rasters at this width."""
        with self._lock:
            if self._rasters is None:
                self._rasters = planet_rasters(self.result, self.width)
            return self._rasters

    @property
    def inputs(self) -> MapInputs:
        with self._lock:
            if self._inputs is None:
                self._inputs = map_inputs(
                    self.result, self.rasters, river_threshold_m3_s(self.result, self.river_km2)
                )
            return self._inputs

    def image(self, label: str) -> Image.Image | None:
        """The map if it is drawn; never draws."""
        return self._images.get(label)

    def draw(self, label: str) -> Image.Image:
        """The map, drawn now if it is missing (seconds; keep it off the Tk thread)."""
        with self._lock:
            image = self._images.get(label)
            if image is None:
                if label not in self.labels:
                    raise ValueError(f"This planet has no {label} map.")
                image = _PAINTERS[THEME_BY_LABEL[label].id](self)
                self._images[label] = image
                if len(self._images) == len(self.labels):
                    self._rasters = self._inputs = None
            return image


def _tectonics(result: PlanetResult) -> Tectonics:
    plates = result.forcing.tectonics
    assert plates is not None
    return plates


def _atlas(maps: PlanetMaps) -> Image.Image:
    m = maps.inputs
    return compose(
        natural_colour(m.result, m.rasters.raster, m.rivers, m.fields), m.sea,
        m.rasters.land_px, m.rivers, m.result, m.rasters.lakes_px, m.fields.slope,
    )


def _relief(maps: PlanetMaps) -> Image.Image:
    m = maps.inputs
    return compose(
        relief_colour(m.fields), m.sea, m.rasters.land_px, m.rivers, m.result, m.rasters.lakes_px
    )


def _volcanoes(maps: PlanetMaps) -> Image.Image:
    return volcano_markers(
        maps.draw(THEME_BY_ID["atlas"].label), maps.result, maps.inputs.rasters.raster
    )


def _climate(maps: PlanetMaps, values: Callable[[PlanetResult], F64], low: float, high: float,
             colours: tuple[tuple[int, int, int], ...]) -> Image.Image:
    m = maps.inputs
    return scalar_image(
        m.rasters.raster.interpolate(m.result.mesh, values(m.result)), m.rasters.land_px,
        low, high, colours,
    )


def _climate_zones(maps: PlanetMaps) -> Image.Image:
    m = maps.inputs
    assert m.result.climate is not None
    return koppen_image(m.result.climate.koppen, m.rasters.raster, m.rasters.land_px)


def _topographic(maps: PlanetMaps) -> Image.Image:
    m = maps.inputs
    rows, columns = m.rasters.land_px.shape
    radius = m.result.mesh.radius_m
    return topographic_image(
        m.fields.elevation_m, m.rasters.land_px, m.rasters.lakes_px >= 0, m.rivers, m.fields.light,
        np.pi * radius / rows,
        2 * np.pi * radius / columns * np.maximum(np.cos(m.rasters.raster.latitude), 0.05),
        m.fields.ice.covered,
    )


def _parchment(maps: PlanetMaps) -> Image.Image:
    m = maps.inputs
    return planet_parchment(m.result, m.rasters, m.fields, m.rivers, m.fields.ice.covered)


def _rain(result: PlanetResult) -> F64:
    assert result.climate is not None
    return result.climate.precipitation_mm


def _temperature(result: PlanetResult) -> F64:
    assert result.climate is not None
    return result.climate.temperature_c


type Painter = Callable[[PlanetMaps], Image.Image]

# Theme id -> how its map is drawn.
_PAINTERS: dict[str, Painter] = {
    "atlas": _atlas,
    "relief": _relief,
    "koppen": _climate_zones,
    "volcanoes": _volcanoes,
    "precipitation": lambda maps: _climate(maps, _rain, 0.0, 2500.0, RAIN_COLOURS),
    "temperature": lambda maps: _climate(maps, _temperature, -25.0, 30.0, TEMPERATURE_COLOURS),
    "topographic": _topographic,
    "parchment": _parchment,
    "plates": lambda maps: plates_image(
        maps.result, maps.inputs.rasters, maps.inputs.fields.light, _tectonics(maps.result)
    ),
    "seafloor": lambda maps: sea_floor_age_image(
        maps.result, maps.inputs.rasters, maps.inputs.fields.light, _tectonics(maps.result)
    ),
    "basins": lambda maps: basins_image(
        maps.result, maps.inputs.rasters, maps.inputs.fields.light, maps.inputs.rivers
    ),
    "geology": lambda maps: geology_image(
        maps.result, maps.inputs.rasters, maps.inputs.fields.light
    ),
}
