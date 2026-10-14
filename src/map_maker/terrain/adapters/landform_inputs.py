"""Shared strict landform controls for terrain and world geology documents."""

from math import isfinite
from typing import cast

from map_maker.terrain.domain.models import LandformSettings


def landform_from_json(value: object) -> LandformSettings:
    fields = ("elevation_m", "relief_m", "feature_size_km", "transition_km", "orientation_deg")
    if not isinstance(value, dict):
        raise ValueError("Landform settings must be an object.")
    data = cast(dict[str, object], value)
    if set(data) != {"character", *fields}:
        raise ValueError("Landform settings must contain exactly the current controls.")
    character = data["character"]
    if character not in ("plain", "hills", "plateau", "mountains"):
        raise ValueError("Unknown landform character.")
    numbers: list[float] = []
    for key in fields:
        number = data[key]
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not isfinite(number):
            raise ValueError(f"Landform {key} must be a finite number.")
        numbers.append(float(number))
    return LandformSettings(character, *numbers)
