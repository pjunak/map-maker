# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""3D globe models: a valid glTF binary whose closed sphere carries the world-frame map."""

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

from map_maker.terrain.adapters.globe_model import CAP_DEG, globe_model, globe_surfaces
from map_maker.terrain.application.planet_views import save_globe
from map_maker.terrain.domain.world import WorldFrame


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
    with pytest.raises(ValueError, match=r".glb"):
        save_globe(tmp_path / "planet.png", image, "Planet atlas", frame)
