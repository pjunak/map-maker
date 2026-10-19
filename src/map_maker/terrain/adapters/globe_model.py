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

Regional maps opened in the app (``map_projection.Drape``) can lie over the
sphere, as they do on the app's globe (ADR-0111). Each is a fine polar grid
over its window's disc, with the window's own azimuthal equidistant texture
coordinates, lifted ``DRAPE_LIFT`` above the surface below it so depth tests
keep the deeper level on top in every viewer. Its rim fade is drawn into its
image against what the model shows below it, so it is opaque and needs no
blending, which viewers sort by object and would draw out of order.

Materials are the map's colour, not metallic and fully rough, with
``KHR_materials_unlit`` so viewers that support it show the map's own hillshade
instead of lighting it a second time.
"""

from __future__ import annotations

import json
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from math import ceil, pi, sin

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from map_maker.terrain.adapters.map_projection import (
    Drape,
    MapProjection,
    MapTexture,
    lonlat_screen,
    render,
)
from map_maker.terrain.pipeline.planet_patch import forward_aeqd, inverse_aeqd
from map_maker.terrain.pipeline.sphere_views import drape_weights

type F64 = NDArray[np.float64]
type I64 = NDArray[np.int64]
type U8 = NDArray[np.uint8]

STEP_DEG = 1.5  # grid spacing: the facets are invisible on a smooth-shaded sphere
COLUMNS = round(360 / STEP_DEG)
CAP_DEG = 60.0  # latitude where the polar caps meet the band
CAP_IMAGE_SPAN_DEG = 90.0 - CAP_DEG + STEP_DEG  # pole to the edge of a cap image
# A regional map's grid has at least this many rings from its centre to its rim and
# vertices per ring, so texture positions stay within a sixth of a pixel of a
# 900-pixel window's; wide windows get more, so cells stay DRAPE_CELL_RAD across.
DRAPE_RINGS = 32
DRAPE_SECTORS = 128
DRAPE_CELL_RAD = 0.005
# Model metres between a regional level and the surface below it: invisible on a
# 1 m globe, yet several depth-buffer steps in common viewers.
DRAPE_LIFT = 2e-4
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
    counter-clockwise triangles and its PNG image, lying at ``radius``."""

    name: str
    positions: NDArray[np.float32]
    uv: NDArray[np.float32]
    indices: NDArray[np.uint32]
    image: bytes
    wraps: bool  # whether the image repeats east-west (the band)
    radius: float = 1.0


def globe_model(
    map_png: bytes,
    central_meridian_deg: float,
    *,
    name: str,
    extras: dict[str, object],
    drapes: Sequence[Drape] = (),
) -> bytes:
    """A ``.glb`` globe showing ``map_png``, a world-frame (equirectangular) PNG image,
    with ``drapes`` over it, the last on top."""
    surfaces = globe_surfaces(map_png, central_meridian_deg, drapes)
    return glb(surfaces, name=name, extras=extras)


def globe_surfaces(
    map_png: bytes, central_meridian_deg: float, drapes: Sequence[Drape] = ()
) -> list[Surface]:
    """The band and the two polar caps of a globe showing ``map_png``, then one
    surface per drape."""
    if not map_png.startswith(PNG_SIGNATURE):
        raise ValueError("A globe model needs the map as a PNG image.")
    with Image.open(BytesIO(map_png)) as image:
        band = np.asarray(image.convert("RGB"), dtype=np.uint8)
        texture = MapTexture.from_image(image, central_meridian_deg)
        # Caps as sharp as the band: the band has width / 360 pixels per degree.
        size = max(16, round(image.width * 2 * CAP_IMAGE_SPAN_DEG / 360))
    steps = np.arange(round(2 * CAP_DEG / STEP_DEG) + 1, dtype=np.float64)
    latitudes = CAP_DEG - STEP_DEG * steps
    positions, lon, lat = _rings(latitudes)
    band_uv = np.stack(((lon + 180.0) / 360.0, (90.0 - lat) / 180.0), axis=-1)
    surfaces = [Surface("band", positions.astype(np.float32), band_uv.astype(np.float32),
                        _strips(len(latitudes)), map_png, wraps=True)]
    caps: list[tuple[MapProjection, U8]] = []
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
        caps.append((projection, np.asarray(image, dtype=np.uint8)))
        surfaces.append(Surface(kind.removesuffix("-polar") + " cap",
                                positions.astype(np.float32), uv.astype(np.float32), indices,
                                _png(image), wraps=False))
    draped: list[tuple[Drape, U8]] = []
    for level, drape in enumerate(drapes, start=1):
        image = _faded(drape, _shown(_texels(drape), band, caps, draped, central_meridian_deg))
        draped.append((drape, image))
        plane, uv, indices = _drape_grid(drape)
        points = inverse_aeqd(plane[:, 0], plane[:, 1], *drape.centre, 1.0)
        surfaces.append(Surface(f"regional map {level}",
                                _model_axes(points, central_meridian_deg).astype(np.float32),
                                uv.astype(np.float32), indices, _png(Image.fromarray(image)),
                                wraps=False, radius=1.0 + level * DRAPE_LIFT))
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
        # On a sphere each vertex's normal is its unit position.
        normals = view(surface.positions.tobytes(), ARRAY_BUFFER)
        lifted = surface.positions
        positions = normals
        if surface.radius != 1.0:
            lifted = surface.positions * np.float32(surface.radius)
            positions = view(lifted.tobytes(), ARRAY_BUFFER)
        accessors.append({
            "bufferView": positions, "componentType": FLOAT, "count": len(lifted),
            "type": "VEC3", "min": lifted.min(axis=0).tolist(),
            "max": lifted.max(axis=0).tolist(),
        })
        accessors.append({"bufferView": normals, "componentType": FLOAT,
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


def _drape_grid(drape: Drape) -> tuple[F64, F64, NDArray[np.uint32]]:
    """A polar grid over a drape's disc: plane positions, texture coordinates, triangles.

    Plane positions are azimuthal equidistant (x east, y north) in radians of arc
    about the drape's centre; the centre comes first, then each ring clockwise from
    north. The texture coordinates place them in the window's square image, as
    ``inverse_aeqd`` placed its pixels, and the triangles face outwards.
    """
    angle = drape.angle_rad
    rings = max(DRAPE_RINGS, ceil(angle / DRAPE_CELL_RAD))
    sectors = max(DRAPE_SECTORS, ceil(2 * pi * sin(min(angle, pi / 2)) / DRAPE_CELL_RAD))
    theta = angle * np.arange(1, rings + 1)[:, None] / rings
    beta = 2 * pi * np.arange(sectors) / sectors
    x = np.concatenate(([0.0], (theta * np.sin(beta)).ravel()))
    y = np.concatenate(([0.0], (theta * np.cos(beta)).ravel()))
    uv = np.stack((0.5 * (1 + x / angle), 0.5 * (1 - y / angle)), axis=-1)
    here = np.arange(sectors)
    later = (here + 1) % sectors  # the next vertex clockwise, seen from outside
    fan = np.stack((np.zeros(sectors, dtype=np.int64), 1 + later, 1 + here), axis=-1)
    first = 1 + np.arange(rings - 1)[:, None] * sectors  # each inner ring's first vertex
    inner, inner_later = (first + here).ravel(), (first + later).ravel()
    outer, outer_later = inner + sectors, inner_later + sectors
    triangles = np.concatenate((
        fan,
        np.stack((inner, inner_later, outer_later), axis=-1),
        np.stack((inner, outer_later, outer), axis=-1),
    ))
    return np.stack((x, y), axis=-1), uv, triangles.astype(np.uint32).ravel()


def _texels(drape: Drape) -> F64:
    """Unit vectors (planet axes) of a drape image's pixel centres, row by row from the north."""
    size = drape.image.width
    t = ((np.arange(size) + 0.5) / size * 2 - 1) * drape.angle_rad
    x, y = np.meshgrid(t, -t)
    return inverse_aeqd(x.ravel(), y.ravel(), *drape.centre, 1.0)


def _faded(drape: Drape, below: F64) -> U8:
    """A drape's image faded at its rim into ``below``, the colours under its pixels.

    The fade is the app globe's (``drape_weights``), so the outermost pixels show
    what lies under them and an opaque surface meets its surroundings without a seam.
    """
    size = drape.image.width
    t = (np.arange(size) + 0.5) / size * 2 - 1
    weight = drape_weights(np.hypot(t[None, :], t[:, None]))[..., None]
    own = np.asarray(drape.image.convert("RGB"), dtype=np.float64)
    blended = weight * own + (1.0 - weight) * below.reshape(size, size, 3)
    return np.round(blended).astype(np.uint8)


def _shown(
    points: F64, band: U8, caps: list[tuple[MapProjection, U8]],
    draped: list[tuple[Drape, U8]], central_meridian_deg: float,
) -> F64:
    """Colours the model shows at unit vectors (planet axes): the band or a cap, or the
    last of the ``draped`` surfaces (with their faded images) whose disc holds a point.

    Each image is read as viewers read it, bilinearly at its texture coordinates.
    """
    east = np.degrees(np.arctan2(points[:, 1], points[:, 0])) - central_meridian_deg
    east = (east + 180.0) % 360.0 - 180.0  # longitude east of the central meridian
    lat = np.degrees(np.arcsin(np.clip(points[:, 2], -1.0, 1.0)))
    rows, columns = band.shape[:2]
    colours = _bilinear(band, (east + 180.0) / 360.0 * columns - 0.5,
                        (90.0 - lat) / 180.0 * rows - 0.5, wrap=True)
    for projection, image in caps:
        # The polar view's mapping (``lonlat_screen``), for many points at once.
        sign, half = projection.polar_sign, image.shape[0] / 2
        on = sign * lat > CAP_DEG
        rho = (90.0 - sign * lat[on]) / projection.polar_span_deg
        theta = np.radians(east[on])
        colours[on] = _bilinear(image, half * (1 + rho * np.sin(theta)) - 0.5,
                                half * (1 + sign * rho * np.cos(theta)) - 0.5, wrap=False)
    for drape, image in draped:
        x, y = (forward_aeqd(points, *drape.centre, 1.0) / drape.angle_rad).T
        on = np.hypot(x, y) <= 1.0
        half = image.shape[0] / 2
        colours[on] = _bilinear(image, half * (1 + x[on]) - 0.5, half * (1 - y[on]) - 0.5,
                                wrap=False)
    return colours


def _bilinear(image: U8, x: F64, y: F64, *, wrap: bool) -> F64:
    """Bilinear colours at pixel positions (pixel centres at whole numbers); columns
    wrap around if ``wrap`` and are clamped otherwise; rows are clamped."""
    rows, columns = image.shape[:2]
    x0, y0 = np.floor(x), np.floor(y)
    fx, fy = (x - x0)[:, None], (y - y0)[:, None]
    if wrap:
        c0 = x0.astype(np.int64) % columns
        c1 = (c0 + 1) % columns
    else:
        c0 = np.clip(x0, 0, columns - 1).astype(np.int64)
        c1 = np.clip(x0 + 1, 0, columns - 1).astype(np.int64)
    r0 = np.clip(y0, 0, rows - 1).astype(np.int64)
    r1 = np.clip(y0 + 1, 0, rows - 1).astype(np.int64)
    top = image[r0, c0] * (1 - fx) + image[r0, c1] * fx
    bottom = image[r1, c0] * (1 - fx) + image[r1, c1] * fx
    return top * (1 - fy) + bottom * fy


def _model_axes(points: F64, central_meridian_deg: float) -> F64:
    """Unit vectors in planet axes (x at 0° E, z north) turned into the model's axes."""
    lam = np.radians(central_meridian_deg)
    x, y, z = points.T
    return np.stack((y * np.cos(lam) - x * np.sin(lam), z, x * np.cos(lam) + y * np.sin(lam)),
                    axis=-1)


def _png(image: Image.Image) -> bytes:
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def _padded(length: int) -> int:
    return (length + 3) // 4 * 4
