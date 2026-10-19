"""Spinning globes: frames turn eastward through one turn and loop as an animated WebP."""

from io import BytesIO

import numpy as np
import pytest
from PIL import Image

from map_maker.terrain.adapters.globe_spin import SPIN_FRAME_RANGE, spin_frames, write_spin
from map_maker.terrain.adapters.map_projection import MapProjection, MapTexture, render


def _texture() -> MapTexture:
    """A world map whose red channel encodes longitude east of the central meridian."""
    columns, rows = 720, 360
    lon = (np.arange(columns) + 0.5) / columns * 360 - 180
    rgb = np.full((rows, columns, 3), 128, dtype=np.uint8)
    rgb[..., 0] = np.round((lon + 180) / 360 * 255).astype(np.uint8)
    return MapTexture.from_image(Image.fromarray(rgb))


def test_frames_turn_the_globe_eastward_through_one_turn() -> None:
    texture = _texture()
    frames = spin_frames(texture, MapProjection("globe", 40.0, 10.0), (96, 96), frames=8)
    assert len(frames) == 8
    for k, frame in enumerate(frames):  # frame k is the view turned 45k degrees
        lon = (40.0 - 45.0 * k + 180.0) % 360.0 - 180.0
        assert frame.tobytes() == render(texture, MapProjection("globe", lon, 10.0),
                                         (96, 96)).tobytes()
    # The ground moves from left to right, so the longitude at the centre falls.
    centre = [int(np.asarray(frame)[48, 48, 0]) for frame in frames[:3]]
    assert centre[0] > centre[1] > centre[2]


def test_spins_are_looping_animated_webp_images_that_repeat_exactly() -> None:
    view = MapProjection("north-polar", 0.0, 0.0, 30.0)
    frames = spin_frames(_texture(), view, (64, 64), frames=8)
    data, again = BytesIO(), BytesIO()
    write_spin(frames, data, seconds=2.0)
    write_spin(frames, again, seconds=2.0)
    assert data.getvalue() == again.getvalue()
    with Image.open(BytesIO(data.getvalue())) as image:
        assert image.format == "WEBP" and getattr(image, "n_frames", 1) == 8
        image.seek(3)
        image.load()  # a frame's timing is read with the frame
        assert image.info["loop"] == 0 and image.info["duration"] == 250
        assert image.info["timestamp"] == 750


def test_spins_refuse_flat_maps_and_unsupported_lengths() -> None:
    texture = _texture()
    with pytest.raises(ValueError, match="turns"):
        spin_frames(texture, MapProjection("equirectangular"), (64, 32), frames=8)
    with pytest.raises(ValueError, match="frames"):
        spin_frames(texture, MapProjection("globe"), (64, 64), frames=SPIN_FRAME_RANGE[0] - 1)
    frames = spin_frames(texture, MapProjection("globe"), (32, 32), frames=8)
    with pytest.raises(ValueError, match="seconds"):
        write_spin(frames, BytesIO(), seconds=0.5)
