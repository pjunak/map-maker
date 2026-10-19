# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""3D globe models: a valid glTF binary whose closed sphere carries the world-frame map,
with regional maps lying over it."""

import json
import struct
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image
from scipy.ndimage import map_coordinates

from map_maker.terrain.adapters.globe_model import (
    CAP_DEG,
    CAP_IMAGE_SPAN_DEG,
    DRAPE_LIFT,
    Surface,
    globe_model,
    globe_surfaces,
)
from map_maker.terrain.adapters.map_projection import Drape, MapProjection, lonlat_screen
from map_maker.terrain.application.planet_views import save_globe
from map_maker.terrain.domain.world import WorldFrame
from map_maker.terrain.pipeline.planet_patch import forward_aeqd, inverse_aeqd
from map_maker.terrain.pipeline.sphere_views import DRAPE_FADE


@dataclass(frozen=True)
class Glb:
    document: dict[str, Any]
    binary: bytes

    def view(self, index: int) -> bytes:
        view = self.document["bufferViews"][index]
        return self.binary[view["byteOffset"] : view["byteOffset"] + view["byteLength"]]

    def accessor(self, index: int, dtype: type, width: int) -> np.ndarray:
        accessor = self.document["accessors"][index]
        values = np.frombuffer(self.view(accessor["bufferView"]), dtype=dtype)
        return values.reshape(accessor["count"], width) if width > 1 else values

    def image(self, index: int) -> bytes:
        return self.view(self.document["images"][index]["bufferView"])


def read_glb(data: bytes) -> Glb:
    """Parse a glTF binary, checking its framing as the specification requires."""
    magic, version, length = struct.unpack_from("<III", data, 0)
    assert (magic, version, length) == (0x46546C67, 2, len(data))
    json_length, json_type = struct.unpack_from("<II", data, 12)
    assert json_type == 0x4E4F534A and json_length % 4 == 0
    document = json.loads(data[20 : 20 + json_length])
    bin_length, bin_type = struct.unpack_from("<II", data, 20 + json_length)
    assert bin_type == 0x004E4942 and bin_length % 4 == 0
    assert 28 + json_length + bin_length == len(data)
    assert document["buffers"] == [{"byteLength": bin_length}]
    return Glb(document, data[28 + json_length :])


def _lonlat_png(columns: int = 720) -> bytes:
    """A world-frame image whose red and green encode longitude and latitude; blue is 128."""
    rows = columns // 2
    lon = (np.arange(columns) + 0.5) / columns * 360 - 180
    lat = 90 - (np.arange(rows) + 0.5) / rows * 180
    glon, glat = np.meshgrid(lon, lat)
    rgb = np.stack(((glon + 180) / 360 * 255, (glat + 90) / 180 * 255,
                    np.full(glon.shape, 128.0)), axis=-1)
    stream = BytesIO()
    Image.fromarray(np.round(rgb).astype(np.uint8)).save(stream, format="PNG")
    return stream.getvalue()


def _sample(png: bytes, uv: np.ndarray) -> np.ndarray:
    """Bilinear colours of a PNG at texture coordinates, as a viewer reads them."""
    with Image.open(BytesIO(png)) as image:
        pixels = np.asarray(image.convert("RGB"), dtype=np.float64)
    rows, columns = pixels.shape[:2]
    where = (uv[:, 1] * rows - 0.5, uv[:, 0] * columns - 0.5)
    return np.stack([map_coordinates(pixels[..., k], where, order=1, mode="nearest")
                     for k in range(3)], axis=-1)


def _latitudes(positions: np.ndarray) -> np.ndarray:
    return np.degrees(np.arcsin(np.clip(positions[:, 1].astype(np.float64), -1, 1)))


def test_globe_surfaces_close_the_sphere_facing_outwards() -> None:
    band, north, south = globe_surfaces(_lonlat_png(), central_meridian_deg=0.0)
    for surface in (band, north, south):
        corners = surface.positions[surface.indices.reshape(-1, 3)].astype(np.float64)
        normals = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
        assert (np.linalg.norm(normals, axis=1) > 1e-9).all()  # no degenerate triangles
        assert (np.einsum("ij,ij->i", normals, corners.sum(axis=1)) > 0).all()  # outwards
        assert np.allclose(np.linalg.norm(surface.positions, axis=1), 1.0, atol=1e-6)
        assert surface.indices.max() < len(surface.positions)
        assert ((surface.uv >= 0) & (surface.uv <= 1)).all()
    # The band shows the map with the world frame's own texture coordinates.
    lat = _latitudes(band.positions)
    assert lat.max() == pytest.approx(CAP_DEG) and lat.min() == pytest.approx(-CAP_DEG)
    assert np.allclose(90 - band.uv[:, 1] * 180, lat, atol=1e-4)
    lon = np.degrees(np.arctan2(band.positions[:, 0], band.positions[:, 2]))
    shift = (band.uv[:, 0] * 360 - 180 - lon + 180) % 360 - 180
    assert np.allclose(shift, 0, atol=1e-3)
    # North is +Y, the central meridian faces +Z and east is +X.
    front = np.argmin(np.linalg.norm(band.positions - (0, 0, 1), axis=1))
    east = np.argmin(np.linalg.norm(band.positions - (1, 0, 0), axis=1))
    assert np.allclose(band.uv[front], (0.5, 0.5)) and band.uv[east, 0] == pytest.approx(0.75)
    assert (0.0, 1.0, 0.0) in map(tuple, north.positions)
    assert (0.0, -1.0, 0.0) in map(tuple, south.positions)

    # Caps and band share their boundary vertices, so the sphere has no crack.
    def ring(positions: np.ndarray, at: float) -> set[tuple[float, ...]]:
        on = np.isclose(_latitudes(positions), at, atol=1e-4)
        return {tuple(p) for p in np.round(positions[on], 6)}

    assert ring(band.positions, CAP_DEG) == ring(north.positions, CAP_DEG)
    assert ring(band.positions, -CAP_DEG) == ring(south.positions, -CAP_DEG)


def test_polar_caps_show_the_map_at_each_vertex_and_meet_the_band() -> None:
    band, north, south = globe_surfaces(_lonlat_png(1440), central_meridian_deg=40.0)
    for cap in (north, south):
        colours = _sample(cap.image, cap.uv.astype(np.float64))
        lat = _latitudes(cap.positions)
        assert np.allclose(colours[:, 1] / 255 * 180 - 90, lat, atol=1.5)
        # The test image encodes longitude east of the frame's central meridian.
        lon = np.degrees(np.arctan2(cap.positions[:, 0], cap.positions[:, 2]))
        shown = colours[:, 0] / 255 * 360 - 180
        clear = (np.abs(lat) < 86) & (np.abs(lon) < 170)
        difference = (shown[clear] - lon[clear] + 180) % 360 - 180
        assert np.abs(difference).max() < 3.0
        # Where a cap meets the band both show the same colours.
        at = CAP_DEG if cap is north else -CAP_DEG
        edge = np.isclose(_latitudes(band.positions), at, atol=1e-4)
        cap_edge = np.isclose(lat, at, atol=1e-4)
        band_colours = _sample(band.image, band.uv[edge].astype(np.float64))
        cap_colours = colours[cap_edge]
        seam_free = np.abs(lon[cap_edge]) < 170
        assert np.abs(band_colours[seam_free] - cap_colours[seam_free]).max() < 4.0


def test_globe_model_is_valid_gltf_with_the_map_embedded_unchanged() -> None:
    png = _lonlat_png()
    data = globe_model(png, 0.0, name="Atlas", extras={"planet_radius_m": 6.0e6})
    model = read_glb(data)
    document = model.document
    assert document["asset"]["version"] == "2.0"
    assert model.image(0) == png  # the band shows the map itself
    surfaces = globe_surfaces(png, 0.0)
    primitives = document["meshes"][0]["primitives"]
    assert len(primitives) == len(surfaces) == len(document["images"]) == 3
    for primitive, surface in zip(primitives, surfaces, strict=True):
        attributes = primitive["attributes"]
        positions = model.accessor(attributes["POSITION"], np.float32, 3)
        assert np.array_equal(positions, surface.positions)
        assert np.array_equal(model.accessor(attributes["NORMAL"], np.float32, 3), positions)
        assert np.array_equal(model.accessor(attributes["TEXCOORD_0"], np.float32, 2),
                              surface.uv)
        assert np.array_equal(model.accessor(primitive["indices"], np.uint32, 1),
                              surface.indices)
        accessor = document["accessors"][attributes["POSITION"]]
        assert accessor["min"] == positions.min(axis=0).tolist()
        assert accessor["max"] == positions.max(axis=0).tolist()
        texture = document["textures"][
            document["materials"][primitive["material"]]["pbrMetallicRoughness"]
            ["baseColorTexture"]["index"]
        ]
        assert model.image(texture["source"]) == surface.image
        material = document["materials"][primitive["material"]]
        assert "KHR_materials_unlit" in material["extensions"]
    assert "KHR_materials_unlit" in document["extensionsUsed"]
    assert "extensionsRequired" not in document  # viewers without it still light the map
    assert document["nodes"][0]["extras"] == {"planet_radius_m": 6.0e6}
    assert all(view["byteOffset"] % 4 == 0 for view in document["bufferViews"])
    assert data == globe_model(png, 0.0, name="Atlas", extras={"planet_radius_m": 6.0e6})
    with pytest.raises(ValueError, match="PNG"):
        globe_model(b"GIF89a", 0.0, name="Atlas", extras={})


def test_the_app_saves_a_drawn_map_as_a_globe(tmp_path: Path) -> None:
    image = Image.open(BytesIO(_lonlat_png(256)))
    frame = WorldFrame((0.0, 0.0, 360.0, 180.0), 6000.0, 30.0)
    path = save_globe(tmp_path / "planet.glb", image, "Planet atlas", frame)
    model = read_glb(path.read_bytes())
    with Image.open(BytesIO(model.image(0))) as embedded:
        assert np.array_equal(np.asarray(embedded), np.asarray(image))
    assert model.document["nodes"][0]["extras"] == {
        "map": "Planet atlas", "model_radius_m": 1.0, "planet_radius_m": 6.0e6,
        "central_meridian_deg": 30.0,
    }
    assert len(model.document["meshes"][0]["primitives"]) == 3
    with pytest.raises(ValueError, match=r".glb"):
        save_globe(tmp_path / "planet.png", image, "Planet atlas", frame)
    # Opened regional maps lie over the globe, as on the app's globe.
    drape = Drape(_plain(32, (200, 30, 30)), (40.0, 10.0), 0.05)
    path = save_globe(tmp_path / "regions.glb", image, "Planet atlas", frame, (drape,))
    names = [m["name"] for m in read_glb(path.read_bytes()).document["materials"]]
    assert names == ["band", "north cap", "south cap", "regional map 1"]


# Regional maps over the globe


def _plain(size: int, colour: tuple[int, int, int]) -> Image.Image:
    return Image.new("RGB", (size, size), colour)


def _planet_axes(positions: np.ndarray, central_meridian_deg: float) -> np.ndarray:
    """Model positions as unit vectors with x at 0° E and z north, as ``inverse_aeqd`` gives."""
    unit = positions.astype(np.float64) / np.linalg.norm(positions, axis=1)[:, None]
    lon = np.arctan2(unit[:, 0], unit[:, 2]) + np.radians(central_meridian_deg)
    lat = np.arcsin(np.clip(unit[:, 1], -1, 1))
    return np.stack((np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)), axis=1)


def _image(surface: Surface) -> np.ndarray:
    with Image.open(BytesIO(surface.image)) as image:
        return np.asarray(image.convert("RGB"), dtype=np.float64)


def _pixel_centres(drape: Drape) -> tuple[np.ndarray, np.ndarray]:
    """Unit vectors of a drape image's pixel centres, and their distance in drape radii."""
    size = drape.image.width
    t = (np.arange(size) + 0.5) / size * 2 - 1
    x, y = np.meshgrid(t, -t)
    points = inverse_aeqd(x.ravel() * drape.angle_rad, y.ravel() * drape.angle_rad,
                          *drape.centre, 1.0)
    return points, np.hypot(x, y).ravel()


def _window_uv(points: np.ndarray, drape: Drape) -> np.ndarray:
    """Texture coordinates of unit vectors in a drape's window, by ``forward_aeqd``."""
    x, y = (forward_aeqd(points, *drape.centre, 1.0) / drape.angle_rad).T
    return np.stack((0.5 * (1 + x), 0.5 * (1 - y)), axis=-1)


def _band_uv(points: np.ndarray, central_meridian_deg: float) -> np.ndarray:
    lon = np.degrees(np.arctan2(points[:, 1], points[:, 0])) - central_meridian_deg
    lat = np.degrees(np.arcsin(np.clip(points[:, 2], -1, 1)))
    return np.stack((((lon + 180) % 360) / 360, (90 - lat) / 180), axis=-1)


def _cap_uv(points: np.ndarray, central_meridian_deg: float, size: int) -> np.ndarray:
    """Texture coordinates in the north cap's image, by the view's own mapping."""
    cap = MapProjection("north-polar", central_meridian_deg, limit_deg=90 - CAP_IMAGE_SPAN_DEG)
    lon = np.degrees(np.arctan2(points[:, 1], points[:, 0]))
    lat = np.degrees(np.arcsin(np.clip(points[:, 2], -1, 1)))
    screen = [lonlat_screen(cap, (size, size), a, b) for a, b in zip(lon, lat, strict=True)]
    assert all(s is not None for s in screen)
    return np.array(screen) / size


def _smoothstep_fade(rho: np.ndarray) -> np.ndarray:
    s = np.clip((1 - rho) / DRAPE_FADE, 0, 1)
    return s * s * (3 - 2 * s)


def test_regional_maps_are_outward_grids_over_their_windows_lifted_by_level() -> None:
    meridian = 30.0
    drapes = (
        Drape(_plain(64, (200, 30, 30)), (meridian + 20.0, 15.0), 0.1),
        Drape(_plain(64, (30, 30, 200)), (meridian + 23.0, 16.0), 0.02),
        # Across the far side's seam and over the south pole.
        Drape(_plain(64, (30, 200, 30)), (meridian + 180.0, -80.0), 0.3),
    )
    surfaces = globe_surfaces(_lonlat_png(), meridian, drapes)
    assert [s.name for s in surfaces] == [
        "band", "north cap", "south cap", "regional map 1", "regional map 2", "regional map 3"
    ]
    for level, (drape, surface) in enumerate(zip(drapes, surfaces[3:], strict=True), start=1):
        assert surface.radius == pytest.approx(1 + level * DRAPE_LIFT)
        assert not surface.wraps
        positions = surface.positions.astype(np.float64)
        assert np.allclose(np.linalg.norm(positions, axis=1), 1.0, atol=1e-6)
        corners = positions[surface.indices.reshape(-1, 3)]
        normals = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
        assert (np.linalg.norm(normals, axis=1) > 1e-12).all()
        assert (np.einsum("ij,ij->i", normals, corners.sum(axis=1)) > 0).all()  # outwards
        assert surface.indices.max() < len(positions)
        # Every vertex shows the window pixel ``forward_aeqd`` puts it in...
        points = _planet_axes(positions, meridian)
        uv = surface.uv.astype(np.float64)
        assert np.abs(uv - _window_uv(points, drape)).max() < 1e-5
        # ...and lies where ``inverse_aeqd`` put that pixel.
        x, y = (2 * uv[:, 0] - 1) * drape.angle_rad, (1 - 2 * uv[:, 1]) * drape.angle_rad
        assert np.abs(inverse_aeqd(x, y, *drape.centre, 1.0) - points).max() < 1e-6
        # The grid covers the window's disc, from its centre to its rim.
        rho = np.hypot(2 * uv[:, 0] - 1, 2 * uv[:, 1] - 1)
        assert rho.min() == 0 and rho.max() == pytest.approx(1, abs=1e-6)
        assert ((uv >= 0) & (uv <= 1)).all()


def test_regional_maps_fade_at_their_rims_into_what_lies_below() -> None:
    """A drape's image is its window faded over the app globe's rim band into the band,
    a cap or the drape below it, so its rim matches its surroundings."""
    meridian = 30.0
    region = Drape(_plain(600, (230, 20, 20)), (meridian + 20.0, 15.0), 0.1)
    province = Drape(_plain(600, (20, 20, 230)), (meridian + 25.0, 15.0), 0.02)  # at the rim
    polar = Drape(_plain(128, (20, 230, 20)), (meridian + 10.0, 78.0), 0.1)
    png = _lonlat_png(1440)
    surfaces = globe_surfaces(png, meridian, (region, province, polar))
    band, north = surfaces[0], surfaces[1]
    images = {name: _image(s) for name, s in zip(("region", "province", "polar"), surfaces[3:],
                                                 strict=True)}

    def below(drape: Drape, points: np.ndarray) -> np.ndarray:
        if drape is region:
            return _sample(band.image, _band_uv(points, meridian))
        if drape is province:  # the region where it covers the province, else the band
            colours = _sample(band.image, _band_uv(points, meridian))
            inside = np.hypot(*(2 * _window_uv(points, region) - 1).T) <= 1
            colours[inside] = _sample(surfaces[3].image, _window_uv(points[inside], region))
            return colours
        return _sample(north.image, _cap_uv(points, meridian, _image(north).shape[0]))

    for name, drape in (("region", region), ("province", province), ("polar", polar)):
        points, rho = _pixel_centres(drape)
        under = below(drape, points)
        weight = _smoothstep_fade(rho)[:, None]
        own = np.asarray(drape.image, dtype=np.float64).reshape(-1, 3)
        shown = images[name].reshape(-1, 3)
        assert np.abs(shown - (weight * own + (1 - weight) * under)).max() <= 0.51
        assert (shown[rho <= 1 - DRAPE_FADE] == own[rho <= 1 - DRAPE_FADE]).all()
        assert (np.abs(shown[rho >= 1] - under[rho >= 1]) <= 0.51).all()
    # Where a grid ends, viewers read the colour of the surface below it.
    for drape, surface in ((region, surfaces[3]), (province, surfaces[4])):
        uv = surface.uv.astype(np.float64)
        rim = np.hypot(2 * uv[:, 0] - 1, 2 * uv[:, 1] - 1) > 1 - 1e-6
        points = _planet_axes(surface.positions[rim], meridian)
        assert np.abs(_sample(surface.image, uv[rim]) - below(drape, points)).max() <= 2.0
    # The province crosses the region's rim, so it fades into both the region and the band.
    points, rho = _pixel_centres(province)
    in_region = np.hypot(*(2 * _window_uv(points, region) - 1).T) <= 1
    assert in_region[rho >= 1].any() and not in_region[rho >= 1].all()


def test_globe_models_carry_regional_maps_as_opaque_lifted_primitives() -> None:
    png = _lonlat_png()
    drapes = (Drape(_plain(48, (200, 30, 30)), (10.0, 20.0), 0.1),
              Drape(_plain(48, (30, 30, 200)), (12.0, 21.0), 0.02))
    data = globe_model(png, 0.0, name="Atlas", extras={}, drapes=drapes)
    model = read_glb(data)
    document = model.document
    surfaces = globe_surfaces(png, 0.0, drapes)
    primitives = document["meshes"][0]["primitives"]
    assert len(primitives) == len(surfaces) == 5
    for primitive, surface in zip(primitives, surfaces, strict=True):
        attributes = primitive["attributes"]
        positions = model.accessor(attributes["POSITION"], np.float32, 3)
        normals = model.accessor(attributes["NORMAL"], np.float32, 3)
        assert np.array_equal(positions, surface.positions * np.float32(surface.radius))
        assert np.array_equal(normals, surface.positions)
        assert np.allclose(np.linalg.norm(positions, axis=1), surface.radius, atol=1e-6)
        accessor = document["accessors"][attributes["POSITION"]]
        assert accessor["min"] == positions.min(axis=0).tolist()
        assert accessor["max"] == positions.max(axis=0).tolist()
        material = document["materials"][primitive["material"]]
        assert "alphaMode" not in material  # opaque: the fade is in the image
        texture = document["textures"][material["pbrMetallicRoughness"]["baseColorTexture"]
                                       ["index"]]
        assert model.image(texture["source"]) == surface.image
        assert texture["sampler"] == (0 if surface.wraps else 1)
    assert model.image(0) == png
    assert data == globe_model(png, 0.0, name="Atlas", extras={}, drapes=drapes)
