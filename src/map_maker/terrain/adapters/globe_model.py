"""A planet map as a 3D globe model in glTF 2.0 binary form (``.glb``).

glTF is the open 3D scene format (ISO/IEC 12113). One ``.glb`` file holds the
sphere and its images, so 3D viewers, game engines and browser glTF viewers can
turn the globe without Map Maker.

The model is a desk globe: a smooth sphere one metre in radius, whose node
``extras`` record the map and the planet's true radius. glTF axes are
right-handed with +Y up and models face +Z, so the north pole is +Y, the world
frame's central meridian faces +Z and east is +X.

A viewer filters textures by image pixels, not by ground. Near a pole an
equirectangular image is squeezed east-west without limit, so viewers pick
coarse mip levels there and draw radial streaks. The globe is therefore three
surfaces on one 1.5° latitude-longitude grid:

- **a band** from 60° N to 60° S that shows the map itself, with exactly the
  world frame's texture coordinates (``u = (lon - west) / 360``,
  ``v = (90 - lat) / 180``) and its seam vertices doubled;
- **two polar caps** that show azimuthal equidistant images of the map out to
  1.5° beyond the caps, drawn by the app's view renderer
  (``map_projection.render``), where a pole is an ordinary point.

The caps and the band share their boundary vertices, so the sphere is closed.
Materials are the map's colour, not metallic and fully rough, with
``KHR_materials_unlit`` so viewers that support it show the map's own hillshade
instead of lighting it a second time.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from io import BytesIO

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from map_maker.terrain.adapters.map_projection import (
    MapProjection,
    MapTexture,
    lonlat_screen,
    render,
)

type F64 = NDArray[np.float64]
type I64 = NDArray[np.int64]

STEP_DEG = 1.5  # grid spacing: the facets are invisible on a smooth-shaded sphere
COLUMNS = round(360 / STEP_DEG)
CAP_DEG = 60.0  # latitude where the polar caps meet the band
CAP_IMAGE_SPAN_DEG = 90.0 - CAP_DEG + STEP_DEG  # pole to the edge of a cap image
GLB_MAGIC = 0x46546C67  # "glTF"
JSON_CHUNK = 0x4E4F534A  # "JSON"
BIN_CHUNK = 0x004E4942  # "BIN\0"
FLOAT, UNSIGNED_INT = 5126, 5125
ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER = 34962, 34963
LINEAR, LINEAR_MIPMAP_LINEAR, REPEAT, CLAMP_TO_EDGE = 9729, 9987, 10497, 33071
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True, slots=True)
class Surface:
    """One textured part of the globe: unit-sphere positions, texture coordinates,
    counter-clockwise triangles and its PNG image."""

    name: str
    positions: NDArray[np.float32]
    uv: NDArray[np.float32]
    indices: NDArray[np.uint32]
    image: bytes
    wraps: bool  # whether the image repeats east-west (the band)


def globe_model(
    map_png: bytes, central_meridian_deg: float, *, name: str, extras: dict[str, object]
) -> bytes:
    """A ``.glb`` globe showing ``map_png``, a world-frame (equirectangular) PNG image."""
    return glb(globe_surfaces(map_png, central_meridian_deg), name=name, extras=extras)


def globe_surfaces(map_png: bytes, central_meridian_deg: float) -> list[Surface]:
    """The band and the two polar caps of a globe showing ``map_png``."""
    if not map_png.startswith(PNG_SIGNATURE):
        raise ValueError("A globe model needs the map as a PNG image.")
    with Image.open(BytesIO(map_png)) as image:
        texture = MapTexture.from_image(image, central_meridian_deg)
        # Caps as sharp as the band: the band has width / 360 pixels per degree.
        size = max(16, round(image.width * 2 * CAP_IMAGE_SPAN_DEG / 360))
    steps = np.arange(round(2 * CAP_DEG / STEP_DEG) + 1, dtype=np.float64)
    latitudes = CAP_DEG - STEP_DEG * steps
    positions, lon, lat = _rings(latitudes)
    band_uv = np.stack(((lon + 180.0) / 360.0, (90.0 - lat) / 180.0), axis=-1)
    surfaces = [Surface("band", positions.astype(np.float32), band_uv.astype(np.float32),
                        _strips(len(latitudes)), map_png, wraps=True)]
    for kind, sign in (("north-polar", 1.0), ("south-polar", -1.0)):
        projection = MapProjection(
            kind, central_meridian_deg, limit_deg=sign * (90.0 - CAP_IMAGE_SPAN_DEG)
        )
        steps = np.arange(round((90.0 - CAP_DEG) / STEP_DEG), dtype=np.float64)
        rings = CAP_DEG + STEP_DEG * steps  # from the cap's edge towards its pole
        latitudes = rings[::-1] if sign > 0 else -rings  # listed north to south
        positions, lon, lat = _rings(latitudes)
        pole = np.array(((0.0, sign, 0.0),))
        # The pole is the cap image's centre; the north pole goes first, the south last.
        positions = np.concatenate((pole, positions) if sign > 0 else (positions, pole))
        lon = np.concatenate(([0.0], lon) if sign > 0 else (lon, [0.0]))
        lat = np.concatenate(([90.0], lat) if sign > 0 else (lat, [-90.0]))
        uv = np.array([
            _cap_uv(projection, size, central_meridian_deg + lon_i, lat_i)
            for lon_i, lat_i in zip(lon, lat, strict=True)
        ])
        indices = _cap(len(latitudes), north=sign > 0)
        image = render(texture, projection, (size, size))
        surfaces.append(Surface(kind.removesuffix("-polar") + " cap",
                                positions.astype(np.float32), uv.astype(np.float32), indices,
                                _png(image), wraps=False))
    return surfaces


def glb(surfaces: list[Surface], *, name: str, extras: dict[str, object]) -> bytes:
    """The glTF binary of one node whose mesh has a primitive per surface."""
    blobs: list[bytes] = []
    views: list[dict[str, object]] = []
    accessors: list[dict[str, object]] = []
    primitives: list[dict[str, object]] = []
    materials: list[dict[str, object]] = []
    images: list[dict[str, object]] = []

    def view(blob: bytes, target: int | None) -> int:
        entry: dict[str, object] = {"buffer": 0, "byteOffset": sum(len(b) for b in blobs),
                                    "byteLength": len(blob)}
        if target is not None:
            entry["target"] = target
        views.append(entry)
        blobs.append(blob + b"\0" * (_padded(len(blob)) - len(blob)))
        return len(views) - 1

    for index, surface in enumerate(surfaces):
        positions = view(surface.positions.tobytes(), ARRAY_BUFFER)
        accessors.append({
            "bufferView": positions, "componentType": FLOAT, "count": len(surface.positions),
            "type": "VEC3", "min": surface.positions.min(axis=0).tolist(),
            "max": surface.positions.max(axis=0).tolist(),
        })
        # On a unit sphere each vertex's normal is its position.
        accessors.append({"bufferView": positions, "componentType": FLOAT,
                          "count": len(surface.positions), "type": "VEC3"})
        accessors.append({"bufferView": view(surface.uv.tobytes(), ARRAY_BUFFER),
                          "componentType": FLOAT, "count": len(surface.uv), "type": "VEC2"})
        accessors.append({"bufferView": view(surface.indices.tobytes(), ELEMENT_ARRAY_BUFFER),
                          "componentType": UNSIGNED_INT, "count": len(surface.indices),
                          "type": "SCALAR"})
        first = len(accessors) - 4
        primitives.append({
            "attributes": {"POSITION": first, "NORMAL": first + 1, "TEXCOORD_0": first + 2},
            "indices": first + 3, "material": index,
        })
        materials.append({
            "name": surface.name,
            "pbrMetallicRoughness": {"baseColorTexture": {"index": index},
                                     "metallicFactor": 0.0, "roughnessFactor": 1.0},
            "extensions": {"KHR_materials_unlit": {}},
        })
        images.append({"name": surface.name, "bufferView": view(surface.image, None),
                       "mimeType": "image/png"})
    binary = b"".join(blobs)
    document = {
        "asset": {"version": "2.0", "generator": "Map Maker"},
        "extensionsUsed": ["KHR_materials_unlit"],
        "scene": 0,
        "scenes": [{"name": name, "nodes": [0]}],
        "nodes": [{"name": name, "mesh": 0, "extras": extras}],
        "meshes": [{"name": name, "primitives": primitives}],
        "materials": materials,
        "textures": [{"sampler": 0 if surface.wraps else 1, "source": index}
                     for index, surface in enumerate(surfaces)],
        "samplers": [
            {"magFilter": LINEAR, "minFilter": LINEAR_MIPMAP_LINEAR,
             "wrapS": REPEAT, "wrapT": CLAMP_TO_EDGE},
            {"magFilter": LINEAR, "minFilter": LINEAR_MIPMAP_LINEAR,
             "wrapS": CLAMP_TO_EDGE, "wrapT": CLAMP_TO_EDGE},
        ],
        "images": images,
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(binary)}],
    }
    text = json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    text += b" " * (_padded(len(text)) - len(text))
    total = 12 + 8 + len(text) + 8 + len(binary)
    return b"".join((
        struct.pack("<III", GLB_MAGIC, 2, total),
        struct.pack("<II", len(text), JSON_CHUNK), text,
        struct.pack("<II", len(binary), BIN_CHUNK), binary,
    ))


def _rings(latitudes: F64) -> tuple[F64, F64, F64]:
    """Unit-sphere points on rings of ``latitudes``, ``COLUMNS + 1`` per ring from 180° W.

    Longitudes are east of the central meridian; the last column repeats the first.
    """
    lon = np.linspace(-180.0, 180.0, COLUMNS + 1)
    grid_lon, grid_lat = np.meshgrid(lon, latitudes)
    lam, phi = np.radians(grid_lon), np.radians(grid_lat)
    positions = np.stack(
        (np.cos(phi) * np.sin(lam), np.sin(phi), np.cos(phi) * np.cos(lam)), axis=-1
    )
    return positions.reshape(-1, 3), grid_lon.ravel(), grid_lat.ravel()


def _strips(rings: int, first: int = 0) -> NDArray[np.uint32]:
    """Two triangles per cell between consecutive rings, listed north to south."""
    width = COLUMNS + 1
    top = first + (np.arange(rings - 1)[:, None] * width + np.arange(COLUMNS)[None, :]).ravel()
    bottom = top + width
    triangles = np.concatenate((
        np.stack((top, bottom, bottom + 1), axis=-1),
        np.stack((top, bottom + 1, top + 1), axis=-1),
    ))
    return triangles.astype(np.uint32).ravel()


def _cap(rings: int, *, north: bool) -> NDArray[np.uint32]:
    """A pole's fan and the strips between its rings (north: pole first; south: last)."""
    width = COLUMNS + 1
    i = np.arange(COLUMNS)
    if north:
        fan = np.stack((np.zeros(COLUMNS, dtype=np.int64), 1 + i, 2 + i), axis=-1)
        return np.concatenate((fan.astype(np.uint32).ravel(), _strips(rings, first=1)))
    last = (rings - 1) * width + i
    fan = np.stack((last, np.full(COLUMNS, rings * width), last + 1), axis=-1)
    return np.concatenate((_strips(rings), fan.astype(np.uint32).ravel()))


def _cap_uv(projection: MapProjection, size: int, lon: float, lat: float) -> tuple[float, float]:
    position = lonlat_screen(projection, (size, size), lon, lat)
    assert position is not None  # every cap vertex lies inside its image
    return position[0] / size, position[1] / size


def _png(image: Image.Image) -> bytes:
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def _padded(length: int) -> int:
    return (length + 3) // 4 * 4
