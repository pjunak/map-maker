# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""World-fixed cells on the sphere for regional drainage (ADR-0112).

A regional window draws its map on pixels of its own, in a plane centred on
the window, and steepest descent depends on where cells lie: overlapping
windows that routed on their own pixels put up to a few per cent of their
river pixels apart, and cells in fixed charts' planes still differed between
charts. Drainage is therefore worked out on cells that belong to the sphere.

The cells are those of an equiangular cubed sphere (Ronchi, Iacono and Paolucci
1996) with ``N`` cells along each face edge: each face's two angles step
evenly, so cells are near-square everywhere, and the sphere has no poles and
no projection to choose per map. Each cell holds one node, moved within it by
a jitter hashed from the cell, so steepest descent has no preferred grid
directions, and every map that uses ``N`` sees the same nodes. A disc of
nodes is triangulated on the sphere: planar Delaunay in the disc's
stereographic plane, which maps circles to circles, is the spherical Delaunay
triangulation, and every triangle away from the disc's rim is the one any
other disc holding its nodes finds.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from math import ceil, floor, log2, pi, sqrt

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import Delaunay

type F64 = NDArray[np.float64]
type I64 = NDArray[np.int64]
type B = NDArray[np.bool_]

# Faces: the axis through each face's centre and the two axes its angles turn about.
FACE_AXES = np.array(
    [
        [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        [[-1, 0, 0], [0, -1, 0], [0, 0, 1]],
        [[0, 1, 0], [-1, 0, 0], [0, 0, 1]],
        [[0, -1, 0], [1, 0, 0], [0, 0, 1]],
        [[0, 0, 1], [0, 1, 0], [-1, 0, 0]],
        [[0, 0, -1], [0, 1, 0], [1, 0, 0]],
    ],
    dtype=np.float64,
)
# Mean cell spacing times N, over the planet radius: sqrt(4 pi / 6).
SPACING_PER_RADIUS = sqrt(4 * pi / 6)
CELLS_PER_OCTAVE = 4  # cell sizes step by 2^(1/4), so a window's pixels are within 9 % of them
# Each node lies within this share of its cell's angular width from the cell's
# centre, along both of the face's angles. It keeps nodes about 0.2 cells apart at least.
NODE_JITTER = 0.4
MAX_DISC_RAD = 0.6  # a disc's nodes all lie on the faces' sides of the planet
# Every empty circle among nodes jittered within their own cells has a radius
# under sqrt(2) cells (a larger one holds a whole cell, so its node). Strips of
# a disc are triangulated apart with this margin, in cells, on each side.
STRIP_MARGIN_CELLS = 4.0
STRIP_NODES = 150_000  # strips are worth triangulating apart above about this many nodes


def cell_size(pixel_m: float) -> float:
    """The ladder's cell size nearest ``pixel_m`` (metres)."""
    return float(2.0 ** (round(CELLS_PER_OCTAVE * log2(pixel_m)) / CELLS_PER_OCTAVE))


def _hash(values: NDArray[np.uint64]) -> NDArray[np.uint64]:
    """SplitMix64 finaliser: well-mixed 64-bit integers from consecutive keys."""
    z = values + np.uint64(0x9E3779B97F4A7C15)
    z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
    z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    return z ^ (z >> np.uint64(31))


def _uniform(key: NDArray[np.uint64], salt: int) -> F64:
    """A uniform number in [0, 1) per key, from 53 well-mixed bits."""
    mixed = _hash(_hash(key) ^ np.uint64(salt))
    return (mixed >> np.uint64(11)).astype(np.float64) / float(2**53)


def delaunay(plane: F64, cell: float) -> I64:
    """Delaunay triangles of points in a plane, about one per ``cell`` square.

    Large sets are cut into strips triangulated in parallel. Delaunay is local:
    a triangle whose empty circumcircle lies within a strip and its margin is
    a triangle of the whole set, so each strip keeps the triangles whose
    circumcentres fall in its own core and whose radius is under its margin.
    Triangles along the set's outer hull, whose circles are larger, are dropped.
    """
    if len(plane) < 2 * STRIP_NODES:
        return Delaunay(plane).simplices.astype(np.int64)
    strips = min(os.cpu_count() or 1, len(plane) // STRIP_NODES, 16)
    x = plane[:, 0]
    edges = np.quantile(x, np.linspace(0, 1, strips + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    margin = STRIP_MARGIN_CELLS * cell

    def strip(k: int) -> I64:
        held = np.flatnonzero((x >= edges[k] - margin) & (x < edges[k + 1] + margin))
        found = Delaunay(plane[held]).simplices
        a, b, c = (plane[held][found[:, i]] for i in range(3))
        ux, uy = _circumcentres(a, b, c)
        radius = np.hypot(ux - a[:, 0], uy - a[:, 1])
        core = (ux >= edges[k]) & (ux < edges[k + 1]) & (radius < margin)
        return held[found[core]].astype(np.int64)

    with ThreadPoolExecutor(strips) as pool:
        return np.vstack(list(pool.map(strip, range(strips))))


def _circumcentres(a: F64, b: F64, c: F64) -> tuple[F64, F64]:
    """Centres of the circles through the corners of planar triangles."""
    bx, by = b[:, 0] - a[:, 0], b[:, 1] - a[:, 1]
    cx, cy = c[:, 0] - a[:, 0], c[:, 1] - a[:, 1]
    d = 2 * (bx * cy - by * cx)
    d = np.where(d == 0, np.finfo(np.float64).tiny, d)
    b2, c2 = bx * bx + by * by, cx * cx + cy * cy
    return a[:, 0] + (cy * b2 - by * c2) / d, a[:, 1] + (bx * c2 - cx * b2) / d


def cell_marks(rank: I64, seed: int) -> F64:
    """A number in [0, 1) per cell, fixed to the cell (``rank``) and ``seed``."""
    return _uniform(rank.astype(np.uint64) ^ np.uint64(seed % 2**64), 3)


def face_angles(xyz: F64) -> tuple[I64, F64, F64]:
    """The cube face of each unit vector and its two angles there (-pi/4 to pi/4)."""
    axis = np.argmax(np.abs(xyz), axis=1)
    face = 2 * axis + (xyz[np.arange(len(xyz)), axis] < 0)
    # Faces are ordered +X, -X, +Y, -Y, +Z, -Z.
    axes = FACE_AXES[face]
    normal = np.einsum("ij,ij->i", xyz, axes[:, 0])
    a = np.arctan(np.einsum("ij,ij->i", xyz, axes[:, 1]) / normal)
    b = np.arctan(np.einsum("ij,ij->i", xyz, axes[:, 2]) / normal)
    return face.astype(np.int64), a, b


def face_points(face: I64, a: F64, b: F64) -> F64:
    """Unit vectors at angles ``a`` and ``b`` on cube faces ``face``."""
    axes = FACE_AXES[face]
    p = axes[:, 0] + np.tan(a)[:, None] * axes[:, 1] + np.tan(b)[:, None] * axes[:, 2]
    return p / np.linalg.norm(p, axis=1, keepdims=True)


def _rectangle_area(x: F64, y: F64) -> F64:
    """Solid angle of the face's gnomonic rectangle from its centre to (x, y)."""
    return np.arctan(x * y / np.sqrt(1 + x * x + y * y))


@dataclass(frozen=True)
class GridCells:
    """A connected set of cells: nodes, their neighbours and their areas.

    ``rank`` orders cells the same way in every set that holds them; routing
    breaks ties by it, so cells that two sets share route alike.
    """

    xyz: F64  # (n, 3) unit vectors of the nodes
    rank: I64  # world-fixed order of the cells (for a raster, its flat index)
    area_m2: F64
    ptr: I64  # CSR neighbour offsets
    nbr: I64  # CSR neighbours
    step_m: F64  # distance to each CSR neighbour
    cell_m: float  # nominal spacing
    planet_m: float

    @property
    def size(self) -> int:
        return len(self.xyz)

    @classmethod
    def from_edges(
        cls, xyz: F64, rank: I64, area_m2: F64, src: I64, dst: I64, planet_m: float,
        cell_m: float,
    ) -> GridCells:
        """Cells joined by directed edges (src, dst), each pair listed both ways once."""
        order = np.argsort(src, kind="stable")
        s, d = src[order], dst[order]
        ptr = np.zeros(len(xyz) + 1, dtype=np.int64)
        np.add.at(ptr, s + 1, 1)
        chord = np.linalg.norm(xyz[s] - xyz[d], axis=1)
        step = 2 * planet_m * np.arcsin(np.minimum(chord / 2, 1.0))
        return cls(xyz, rank, area_m2, np.cumsum(ptr), d.astype(np.int64), step, cell_m, planet_m)

    @classmethod
    def raster(
        cls, shape: tuple[int, int], cell_m: float, planet_m: float = 6.371e6
    ) -> GridCells:
        """A raster's pixels as cells with eight neighbours each, ranked row by row.

        Its nodes lie in the azimuthal equidistant plane about (0, 0), rows north
        to south, so distances along rows and columns are ``cell_m``.
        """
        from map_maker.terrain.pipeline.planet_patch import inverse_aeqd

        rows, columns = shape
        r, c = np.mgrid[0:rows, 0:columns]
        flat = (r * columns + c).ravel()
        src, dst = [], []
        for dr, dc in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)):
            ok = ((r + dr >= 0) & (r + dr < rows) & (c + dc >= 0) & (c + dc < columns)).ravel()
            src.append(flat[ok])
            dst.append(flat[ok] + dr * columns + dc)
        x = ((c + 0.5) * cell_m - columns * cell_m / 2).ravel()
        y = (rows * cell_m / 2 - (r + 0.5) * cell_m).ravel()
        xyz = inverse_aeqd(x, y, 0.0, 0.0, planet_m)
        s, d = np.concatenate(src), np.concatenate(dst)
        cells = cls.from_edges(
            xyz, flat.astype(np.int64), np.full(rows * columns, cell_m * cell_m), s, d,
            planet_m, cell_m,
        )
        # Plane distances: exactly cell_m along rows and columns, as on a raster.
        owner = np.repeat(np.arange(rows * columns), np.diff(cells.ptr))
        step = np.hypot(
            cells.nbr // columns - owner // columns, cells.nbr % columns - owner % columns
        ) * cell_m
        return cls(
            cells.xyz, cells.rank, cells.area_m2, cells.ptr, cells.nbr, step, cell_m, planet_m
        )

    def neighbour_max(self, values: F64) -> F64:
        """The largest of ``values`` over each cell's neighbours (-inf without any)."""
        out = np.full(self.size, -np.inf)
        owner = np.repeat(np.arange(self.size), np.diff(self.ptr))
        np.maximum.at(out, owner, values[self.nbr])
        return out

    def label(self, mask: B) -> tuple[I64, int]:
        """Connected groups of ``mask`` cells: labels 1..count, 0 elsewhere."""
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components

        owner = np.repeat(np.arange(self.size), np.diff(self.ptr))
        keep = mask[owner] & mask[self.nbr]
        graph = coo_matrix(
            (np.ones(int(keep.sum())), (owner[keep], self.nbr[keep])),
            shape=(self.size, self.size),
        )
        count, found = connected_components(graph, directed=False)
        labels = np.zeros(self.size, dtype=np.int64)
        # Number the groups by their first cell in rank order, so labels repeat.
        groups = found[mask]
        if not len(groups):
            return labels, 0
        cells = np.flatnonzero(mask)
        first = np.full(count, np.iinfo(np.int64).max)
        np.minimum.at(first, groups, self.rank[cells])
        present = np.flatnonzero(first < np.iinfo(np.int64).max)
        number = np.zeros(count, dtype=np.int64)
        number[present[np.argsort(first[present])]] = np.arange(1, len(present) + 1)
        labels[cells] = number[groups]
        return labels, len(present)


@dataclass(frozen=True)
class WorldGrid:
    """The world-fixed cells of one size: ``cells_per_edge`` along each cube-face edge."""

    cells_per_edge: int
    planet_m: float
    seed: int

    @classmethod
    def for_pixels(cls, pixel_m: float, planet_m: float, seed: int) -> WorldGrid:
        """The grid whose cells are the ladder size nearest ``pixel_m``."""
        edge = max(1, round(SPACING_PER_RADIUS * planet_m / cell_size(pixel_m)))
        return cls(edge, planet_m, seed)

    @property
    def cell_m(self) -> float:
        """Mean node spacing: the square root of the mean cell area."""
        return SPACING_PER_RADIUS * self.planet_m / self.cells_per_edge

    def nodes(self, face: I64, i: I64, j: I64) -> F64:
        """The jittered node of each cell (face, i, j)."""
        width = pi / 2 / self.cells_per_edge
        key = self.ids(face, i, j).astype(np.uint64) ^ np.uint64(
            (self.seed * 0x632BE59BD9B4E019 + self.cells_per_edge) % 2**64
        )
        a = -pi / 4 + (i + 0.5 + NODE_JITTER * (2 * _uniform(key, 1) - 1)) * width
        b = -pi / 4 + (j + 0.5 + NODE_JITTER * (2 * _uniform(key, 2) - 1)) * width
        return face_points(face, a, b)

    def ids(self, face: I64, i: I64, j: I64) -> I64:
        n = self.cells_per_edge
        return (face * n + i) * n + j

    def cell_area_m2(self, i: I64, j: I64) -> F64:
        """Exact area of each cell (i, j) of a face."""
        width = pi / 2 / self.cells_per_edge
        x0, x1 = np.tan(-pi / 4 + i * width), np.tan(-pi / 4 + (i + 1) * width)
        y0, y1 = np.tan(-pi / 4 + j * width), np.tan(-pi / 4 + (j + 1) * width)
        solid = (
            _rectangle_area(x1, y1) - _rectangle_area(x0, y1)
            - _rectangle_area(x1, y0) + _rectangle_area(x0, y0)
        )
        return solid * self.planet_m**2

    def locate(self, xyz: F64) -> I64:
        """The id of the cell holding each unit vector."""
        face, a, b = face_angles(xyz)
        n = self.cells_per_edge
        width = pi / 2 / n
        i = np.clip(np.floor((a + pi / 4) / width), 0, n - 1).astype(np.int64)
        j = np.clip(np.floor((b + pi / 4) / width), 0, n - 1).astype(np.int64)
        return self.ids(face, i, j)

    def disc(self, centre: F64, radius_m: float) -> GridCells:
        """The cells whose nodes lie within ``radius_m`` of ``centre``, triangulated."""
        rho = radius_m / self.planet_m
        if not 0 < rho <= MAX_DISC_RAD:
            raise ValueError(f"Grid discs need a radius up to {MAX_DISC_RAD} planet radii.")
        centre = centre / np.linalg.norm(centre)
        e1 = np.cross([0.0, 0.0, 1.0], centre)
        if np.linalg.norm(e1) < 1e-9:
            e1 = np.array([1.0, 0.0, 0.0])
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(centre, e1)
        n = self.cells_per_edge
        width = pi / 2 / n
        # The disc's rim, in each face's gnomonic plane, bounds the cells to try.
        theta = np.linspace(0, 2 * pi, 2048, endpoint=False)
        rim = np.cos(rho) * centre + np.sin(rho) * (
            np.cos(theta)[:, None] * e1 + np.sin(theta)[:, None] * e2
        )
        rim = np.vstack((rim, centre))
        faces, rows, columns = [], [], []
        for face, (normal, u, v) in enumerate(FACE_AXES):
            if float(np.max(rim @ normal)) <= 0:
                continue
            ahead = rim[rim @ normal > 0]
            depth = ahead @ normal
            x = np.clip(ahead @ u / depth, -1, 1)
            y = np.clip(ahead @ v / depth, -1, 1)
            a, b = np.arctan(x), np.arctan(y)
            i0 = max(floor((float(a.min()) + pi / 4) / width) - 1, 0)
            i1 = min(ceil((float(a.max()) + pi / 4) / width) + 1, n)
            j0 = max(floor((float(b.min()) + pi / 4) / width) - 1, 0)
            j1 = min(ceil((float(b.max()) + pi / 4) / width) + 1, n)
            if i0 >= i1 or j0 >= j1:
                continue
            ii, jj = np.mgrid[i0:i1, j0:j1]
            faces.append(np.full(ii.size, face, dtype=np.int64))
            rows.append(ii.ravel().astype(np.int64))
            columns.append(jj.ravel().astype(np.int64))
        face_ids = np.concatenate(faces)
        i, j = np.concatenate(rows), np.concatenate(columns)
        xyz = self.nodes(face_ids, i, j)
        within = xyz @ centre >= np.cos(rho)
        face_ids, i, j, xyz = face_ids[within], i[within], j[within], xyz[within]
        ids = self.ids(face_ids, i, j)
        # Stereographic plane about the centre: circles stay circles, so planar
        # Delaunay there is the triangulation on the sphere. The plane's scale
        # grows away from the centre, by under 10 % within MAX_DISC_RAD.
        scale = 2 / (1 + xyz @ centre)
        plane = np.stack((scale * (xyz @ e1), scale * (xyz @ e2)), axis=1)
        triangles = delaunay(plane, 1.1 * self.cell_m / self.planet_m)
        src = triangles.ravel()
        dst = triangles[:, [1, 2, 0]].ravel()
        # Each interior edge is in two triangles: keep each pair once, both ways.
        key = np.sort(np.minimum(src, dst) * len(xyz) + np.maximum(src, dst))
        key = key[np.r_[True, key[1:] != key[:-1]]]
        low, high = key // len(xyz), key % len(xyz)
        src, dst = np.concatenate((low, high)), np.concatenate((high, low))
        return GridCells.from_edges(
            xyz, ids, self.cell_area_m2(i, j), src, dst, self.planet_m, self.cell_m,
        )
