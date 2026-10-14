"""NumPy sampling adapter for the dependency-light grid contract."""

import numpy as np
from numpy.typing import NDArray

from map_maker.terrain.domain.coordinates import EndpointGrid


def grid_coordinates(grid: EndpointGrid) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    x0, y0, x1, y1 = grid.extent_km
    return (
        np.linspace(x0, x1, grid.width, dtype=np.float64),
        np.linspace(y0, y1, grid.height, dtype=np.float64),
    )
