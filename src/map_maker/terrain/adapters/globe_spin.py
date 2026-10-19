"""A globe or polar view turning once, saved as an animated WebP image.

Animated WebP plays in web browsers and most chat and document tools, keeps full
colour (an animated GIF has 256) and needs no video encoder. The view turns
eastward, as planets do, so the ground moves from left to right on a globe and
anticlockwise about the north pole. The last frame leads into the first, so the
animation loops without a jump.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import BinaryIO

from PIL import Image

from map_maker.terrain.adapters.map_projection import (
    NO_DRAPES,
    DrapeTextures,
    MapProjection,
    MapTexture,
    Size,
    render,
)

SPIN_FRAMES = 120  # 3° a frame
SPIN_SECONDS = 6.0  # one turn, 20 frames a second
SPIN_FRAME_RANGE = (8, 720)
SPIN_SECONDS_RANGE = (1.0, 120.0)
# 120 frames of a 720-pixel globe of Aethelara's atlas take 3.9 MB; quality 90 takes 6.6 MB.
WEBP_QUALITY = 80


def check_spin(frames: int, seconds: float) -> None:
    """Refuse frame counts and durations outside the supported ranges."""
    low, high = SPIN_FRAME_RANGE
    if not low <= frames <= high:
        raise ValueError(f"A spin has {low}-{high} frames.")
    shortest, longest = SPIN_SECONDS_RANGE
    if not shortest <= seconds <= longest:
        raise ValueError(f"A spin lasts {shortest:g}-{longest:g} seconds.")


def spin_frames(
    texture: MapTexture,
    projection: MapProjection,
    size: Size,
    *,
    frames: int = SPIN_FRAMES,
    graticule: bool = False,
    drapes: DrapeTextures = NO_DRAPES,
) -> list[Image.Image]:
    """``frames`` views of ``projection`` turned eastward through one full turn."""
    check_spin(frames, SPIN_SECONDS)
    if projection.kind == "equirectangular":
        raise ValueError("Only a globe or a polar view turns.")
    return [
        render(
            texture,
            replace(projection, lon_deg=(projection.lon_deg - 360.0 * k / frames + 180.0)
                    % 360.0 - 180.0),
            size, graticule=graticule, drapes=drapes,
        )
        for k in range(frames)
    ]


def write_spin(
    frames: Sequence[Image.Image], stream: BinaryIO, seconds: float = SPIN_SECONDS
) -> None:
    """Write ``frames`` as an animated WebP that loops once every ``seconds``."""
    check_spin(len(frames), seconds)
    first, *rest = frames
    first.save(
        stream, format="WEBP", save_all=True, append_images=rest,
        duration=round(1000 * seconds / len(frames)), loop=0, quality=WEBP_QUALITY, method=4,
    )
