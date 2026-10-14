import pytest

from map_maker.terrain.domain import ElevationPoint, TerrainBrushStroke, TerrainStructure


def test_elevation_point_requires_normalized_coordinates() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        ElevationPoint(position=(1.1, 0.5), elevation_m=1_000.0, influence_radius_km=50.0)


def test_structure_requires_two_distinct_points() -> None:
    with pytest.raises(ValueError, match="at least two"):
        TerrainStructure(
            kind="ridge",
            points=((0.5, 0.5),),
            elevation_m=2_000.0,
            influence_radius_km=100.0,
        )
    with pytest.raises(ValueError, match="different"):
        TerrainStructure(
            kind="valley",
            points=((0.5, 0.5), (0.5, 0.5)),
            elevation_m=250.0,
            influence_radius_km=80.0,
        )


def test_constraint_values_must_be_physical() -> None:
    with pytest.raises(ValueError, match="at or above sea level"):
        ElevationPoint(position=(0.5, 0.5), elevation_m=-1.0, influence_radius_km=50.0)
    with pytest.raises(ValueError, match="positive"):
        ElevationPoint(position=(0.5, 0.5), elevation_m=1_000.0, influence_radius_km=0.0)


def test_terrain_brush_requires_points_and_bounded_intensity() -> None:
    with pytest.raises(ValueError, match="at least one"):
        TerrainBrushStroke((), 1_000.0, 50.0, 0.5)
    with pytest.raises(ValueError, match="different"):
        TerrainBrushStroke(((0.5, 0.5), (0.5, 0.5)), 1_000.0, 50.0, 0.5)
    with pytest.raises(ValueError, match="at most 1"):
        TerrainBrushStroke(((0.5, 0.5),), 1_000.0, 50.0, 1.1)


def test_relative_constraints_validate_signed_and_directional_values() -> None:
    point = ElevationPoint((0.5, 0.5), -250.0, 50.0, "relative")
    brush = TerrainBrushStroke(((0.5, 0.5),), -400.0, 80.0, 0.5, "relative")

    assert point.elevation_mode == "relative"
    assert brush.elevation_mode == "relative"
    with pytest.raises(ValueError, match="must not be negative"):
        TerrainStructure("ridge", ((0.3, 0.5), (0.7, 0.5)), -100.0, 60.0, "relative")
