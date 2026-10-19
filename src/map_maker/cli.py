"""Command-line entry point for Map Maker."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from map_maker import __version__
from map_maker.terrain.domain.wonders import WONDER_KINDS, wonder_kinds


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="map-maker",
        description="Local-first worldbuilding and tabletop utilities.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    commands = parser.add_subparsers(dest="tool", title="tools")
    terrain = commands.add_parser(
        "terrain",
        help="Build and inspect deterministic terrain projects.",
        description="Build and inspect deterministic terrain projects.",
    )
    terrain.set_defaults(_command_parser=terrain)
    terrain_commands = terrain.add_subparsers(dest="terrain_command", title="terrain commands")
    gui = terrain_commands.add_parser(
        "gui",
        help="Open the world-map and terrain workbench.",
        description="Import a full world map with retained continents, or import closed SVG land "
                    "shapes and generate a local colour height map.",
    )
    startup = gui.add_mutually_exclusive_group()
    startup.add_argument("--project", type=Path, help="Open a saved local terrain project.")
    startup.add_argument("--world", type=Path, help="Open a portable .world.json world project.")
    gui.set_defaults(_handler=_run_terrain_gui)
    build = terrain_commands.add_parser(
        "build",
        help="Build numeric terrain, previews and a provenance manifest from a saved project.",
    )
    build.add_argument("project", type=Path, help="Saved .terrain.json project.")
    build.add_argument(
        "--output", type=Path, required=True, help="New build directory (must not exist)."
    )
    build.set_defaults(_handler=_run_terrain_build)
    budget = terrain_commands.add_parser(
        "water-budget",
        help="Forecast shoreline and potential internal-network sampling before a build.",
        description=("Count water profile demand using canonical terrain, without raster export "
                     "or fine ground review. Internal networks are conditional; external outlet "
                     "routes and contacts are not included."),
    )
    budget.add_argument("project", type=Path, help="Saved .terrain.json project (read only).")
    budget.set_defaults(_handler=_run_terrain_water_budget)
    region = terrain_commands.add_parser(
        "sample-region",
        help="Sample a bounded region more densely from the unchanged terrain field.",
        description=("Sample a saved project's unchanged field on a finer regional grid. "
                     "Preserves global constraints and routing; "
                     "adds no detail bands or fine rivers."),
    )
    region.add_argument("project", type=Path, help="Saved .terrain.json project (read only).")
    region.add_argument("--output", type=Path, required=True,
                        help="New regional result directory (must not exist).")
    region.add_argument("--bounds-km", type=float, nargs=4, required=True,
                        metavar=("X0", "Y0", "X1", "Y1"),
                        help="Source-local bounds in kilometres, x right and y down.")
    region.add_argument("--refine", type=int, required=True,
                        help="Power-of-two subdivision of reference intervals; 1 through 65536.")
    region.set_defaults(_handler=_run_terrain_region)
    for command in ("sample-parent", "enrich-region"):
        experimental = command == "enrich-region"
        parent = terrain_commands.add_parser(
            command, help=("Generate experimental protected detail from a verified parent build."
                           if experimental else "Sample a verified completed parent build."),
        )
        parent.add_argument("parent", type=Path, help="Completed current terrain build directory.")
        parent.add_argument("--output", type=Path, required=True, help="New independent directory.")
        parent.add_argument("--bounds-km", type=float, nargs=4, required=True,
                            metavar=("X0", "Y0", "X1", "Y1"))
        parent.add_argument("--refine", type=int, required=True,
                            help="Power of two; experimental detail needs at least 8.")
        parent.add_argument("--memory-mib", type=int, default=None,
                            help="Regional admission budget in MiB (default 1024); estimated "
                                 "allocations, not a process memory limit.")
        if experimental:
            parent.add_argument("--experimental", action="store_true", required=True,
                                help="Acknowledge detail is experimental and hydrology unreviewed.")
            parent.add_argument("--amplitude-m", type=float, default=12.,
                                help="Maximum residual budget in metres, (0, 100], default 12.")
        parent.set_defaults(_handler=_run_parent_region, _experimental_detail=experimental)
    world = commands.add_parser(
        "world", help="Inspect retained world maps and continent ownership.")
    world.set_defaults(_command_parser=world)
    world_commands = world.add_subparsers(dest="world_command", title="world commands")
    inspect = world_commands.add_parser("inspect", help="Validate and summarize a saved world map.")
    inspect.add_argument("project", type=Path, help="Portable .world.json project.")
    inspect.set_defaults(_handler=_run_world_inspect)
    world_terrain = world_commands.add_parser(
        "terrain", help="Create a local terrain project from a world continent and connected land.",
    )
    world_terrain.add_argument("project", type=Path, help="Portable .world.json project.")
    world_terrain.add_argument("--continent", required=True, help="Continent name or ID.")
    world_terrain.add_argument("--output", type=Path, required=True, help="New project folder.")
    world_terrain.add_argument("--seed", type=int, default=20260902)
    world_terrain.add_argument("--resolution", type=int, default=257,
                               help="Initial pixels; 64-4096.")
    world_terrain.add_argument("--geology", type=Path,
                               help="Saved .geology.json with explicit landform guidance.")
    world_terrain.add_argument("--context", type=Path,
                               help="Verified context.json or context folder for coastal support.")
    world_terrain.set_defaults(_handler=_run_world_terrain)
    context = world_commands.add_parser("context", help="Generate spherical geographic context.")
    context.add_argument("project", type=Path, help="Portable .world.json project.")
    context.add_argument("--output", type=Path, required=True,
                         help="New context directory (must not exist).")
    context.add_argument("--latitude-cells", type=int, default=180,
                         help="Latitude rows, 4-360; twice as many longitude columns; default 180.")
    context.set_defaults(_handler=_run_world_context)
    verify_context = world_commands.add_parser(
        "inspect-context", help="Verify and inspect a completed geographic context.")
    verify_context.add_argument("context", type=Path, help="Context directory or context.json.")
    verify_context.set_defaults(_handler=_run_world_context_inspect)
    geology = world_commands.add_parser(
        "inspect-geology", help="Resolve and inspect authored geology inputs.")
    geology.add_argument("recipe", type=Path, help="Portable .geology.json recipe.")
    geology.set_defaults(_handler=_run_world_geology_inspect)
    bathymetry = world_commands.add_parser(
        "bathymetry", help="Generate an authored ocean-depth scenario.")
    bathymetry.add_argument("inputs", type=Path, help="Portable .bathy.json inputs.")
    bathymetry.add_argument("--output", type=Path, required=True, help="New output directory.")
    bathymetry.set_defaults(_handler=_run_world_bathymetry)
    inspect_bathymetry = world_commands.add_parser(
        "inspect-bathymetry", help="Verify an ocean-depth result and retained geography.")
    inspect_bathymetry.add_argument(
        "result", type=Path, help="Result directory or bathymetry.json.")
    inspect_bathymetry.set_defaults(_handler=_run_world_bathymetry_inspect)
    refine = world_commands.add_parser(
        "refine-coast",
        help="Export the coast as zoomed maps draw it into a new SVG source map.",
    )
    refine.add_argument("project", type=Path, help="Portable .world.json project.")
    refine.add_argument("--output", type=Path, required=True, help="New .svg file.")
    refine.add_argument("--seed", type=int, default=20261006,
                        help="The planet's master seed; the coast detail depends on it.")
    refine.add_argument("--detail-km", type=float, default=10.0,
                        help="Finest coast wavelength to draw (km).")
    refine.set_defaults(_handler=_run_world_refine_coast)
    planet = world_commands.add_parser(
        "planet",
        help="Experimental: whole-planet relief by uplift and erosion, with climate and biomes.",
    )
    planet.add_argument("project", type=Path, help="Portable .world.json project.")
    planet.add_argument("--output", type=Path, required=True, help="New build directory.")
    planet.add_argument("--geology", type=Path, help="Optional matching .geology.json recipe.")
    planet.add_argument("--seed", type=int, default=20261006)
    planet.add_argument("--nodes", type=int, default=200_000,
                        help="Sphere mesh nodes (200,000 ~ 50 km spacing on an Earth-size world; "
                             "3,200,000 ~ 12 km resolves Earth-scale ranges and valleys).")
    planet.add_argument("--duration-myr", type=float, default=30.0)
    planet.add_argument("--erodibility", type=float, default=5e-6,
                        help="Base erodibility; lower values give higher relief.")
    planet.add_argument("--process-km2", type=float, default=600.0,
                        help="Smallest resolved drainage area (keeps relief mesh-independent).")
    planet.add_argument("--calibrate", type=int, default=3,
                        help="Geology target corrections (only with --geology).")
    planet.add_argument("--volcanic-islands", action="store_true",
                        help="Let young volcanoes at sea rise as islands (adds land "
                             "beyond your coastline).")
    planet.add_argument("--wonders", type=Path, metavar="FILE",
                        help="Optional matching .wonders.json document of hand-placed wonders.")
    planet.add_argument("--random-wonders", type=wonder_kinds, default=(), metavar="KINDS",
                        help="Fantastical landmarks placed at random: a comma-separated "
                             f"list of {', '.join(WONDER_KINDS)}, or all. Placed wonders "
                             "replace random ones of their kind.")
    planet.add_argument("--wonder-age", type=float, default=0.0, metavar="MYR",
                        help="Age the wonders by eroding each for this many million years "
                             "(0 keeps them fresh; placed wonders may set their own).")
    planet.add_argument("--climate-passes", type=int, default=1,
                        help="Climate/erosion couplings; 0 disables climate and biomes.")
    planet.add_argument("--width", type=int, default=4096, help="Raster and preview width.")
    planet.add_argument("--river-km2", type=float, default=25_000.0,
                        help="Contributing area for drawn and exported rivers.")
    planet.set_defaults(_handler=_run_world_planet)
    region = world_commands.add_parser(
        "region",
        help="Experimental: finer eroded detail for part of a planet build (cached tiles).",
    )
    region.add_argument("planet", type=Path, help="Planet build folder or its manifest.json.")
    region.add_argument("--lon", type=float, required=True, help="Window centre longitude.")
    region.add_argument("--lat", type=float, required=True, help="Window centre latitude.")
    region.add_argument("--radius-km", type=float, default=500.0)
    region.add_argument("--spacing-km", type=float, default=5.0,
                        help="Level-1 node spacing.")
    region.add_argument("--level", type=int, default=1, choices=(1, 2, 3),
                        help="Detail level: 1 region (5 km), 2 province (1 km), 3 local (200 m); "
                             "each is enriched from the level above.")
    region.add_argument("--output", type=Path, required=True, help="New region folder.")
    region.add_argument("--cache", type=Path, help="Tile cache (default: beside the planet).")
    region.add_argument("--pixels", type=int, default=1024)
    region.add_argument("--workers", type=int, default=0, help="Tile processes (0 = auto).")
    region.set_defaults(_handler=_run_world_region)
    view = world_commands.add_parser(
        "view", help="Show a saved planet build's map as a globe, polar or flat view."
    )
    _view_arguments(view, ("globe", "north-polar", "south-polar", "equirectangular"), 1600)
    view.add_argument("--output", type=Path, required=True, help="New .png file.")
    view.set_defaults(_handler=_run_world_view)
    spin = world_commands.add_parser(
        "spin", help="Save a saved planet build's globe or polar view turning once, as an "
                     "animated WebP image."
    )
    _view_arguments(spin, ("globe", "north-polar", "south-polar"), 720)
    spin.add_argument("--frames", type=int, default=120, help="Frames in one turn (8-720).")
    spin.add_argument("--seconds", type=float, default=6.0,
                      help="Seconds one turn takes (1-120).")
    spin.add_argument("--output", type=Path, required=True, help="New .webp file.")
    spin.set_defaults(_handler=_run_world_spin)
    globe = world_commands.add_parser(
        "globe", help="Write a saved planet build's map as a 3D globe model (.glb)."
    )
    globe.add_argument("planet", type=Path, help="Planet build folder or its manifest.json.")
    globe.add_argument("--theme", default="atlas",
                       help="Map theme, a build image's name without .png (see world view).")
    globe.add_argument("--output", type=Path, required=True, help="New .glb file.")
    globe.set_defaults(_handler=_run_world_globe)
    return parser


def _run_world_terrain(arguments: argparse.Namespace) -> int:
    from map_maker.terrain.adapters.world_geology import read_geology
    from map_maker.terrain.adapters.world_project import read_world_project
    from map_maker.terrain.application.world_context import open_context
    from map_maker.terrain.application.world_terrain import create_world_terrain_project
    from map_maker.terrain.domain import TerrainSettings

    try:
        world = read_world_project(arguments.project)
        matching = [c for c in world.continents
                    if c.id == arguments.continent
                    or c.name.casefold() == arguments.continent.casefold()]
        if len(matching) != 1:
            raise ValueError("Choose one continent by name or ID from: "
                             + ", ".join(c.name for c in world.continents))
        created = create_world_terrain_project(
            world, matching[0].id, arguments.output,
            settings=TerrainSettings(seed=arguments.seed, resolution_px=arguments.resolution),
            geology=None if arguments.geology is None
            else read_geology(arguments.geology)[0],
            context=None if arguments.context is None else open_context(arguments.context),
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"World terrain preparation failed: {error}", file=sys.stderr)
        return 1
    names = ", ".join(c.name for c in world.continents
                      if c.id in created.source.included_continent_ids)
    print(f"Terrain project ready: {created.loaded.path}")
    print(f"Included land: {names}; projected extent {created.source.object_scale_km:,.1f} km.")
    print("Open in the Terrain workspace or use map-maker terrain build.")
    print("Geographic context: " + ("connected to coastal relief (experimental)."
          if created.loaded.project.world_context else "not supplied; local coastal distance."))
    print(f"Landform regions: {len(created.loaded.project.constraints)}. "
          "World climate and aging are not applied yet.")
    return 0


def _run_world_planet(arguments: argparse.Namespace) -> int:
    from map_maker.terrain.application.planet import build_planet
    from map_maker.terrain.domain.planet import PlanetSettings
    from map_maker.terrain.domain.wonders import WonderSettings

    last = [-1]

    def progress(fraction: float, message: str) -> None:
        percent = int(fraction * 100)
        if percent != last[0]:
            last[0] = percent
            print(f"{percent:3d}% {message}", file=sys.stderr, flush=True)

    try:
        settings = PlanetSettings(
            seed=arguments.seed,
            nodes=arguments.nodes,
            duration_myr=arguments.duration_myr,
            erodibility=arguments.erodibility,
            process_area_km2=arguments.process_km2,
            calibration_iterations=arguments.calibrate,
            climate_passes=arguments.climate_passes,
            volcanic_islands=arguments.volcanic_islands,
        )
        path = build_planet(
            arguments.project, arguments.output, arguments.geology, settings,
            wonders_path=arguments.wonders,
            wonder_settings=WonderSettings(arguments.random_wonders, arguments.wonder_age),
            width=arguments.width, river_km2=arguments.river_km2, progress=progress,
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Planet generation failed: {error}", file=sys.stderr)
        return 1
    print(f"Planet build complete: {path}")
    print("Experimental relief and provisional climate; see relief.png / atlas.png.")
    return 0


def _run_world_region(arguments: argparse.Namespace) -> int:
    from map_maker.terrain.application.planet_region import build_region
    from map_maker.terrain.domain.planet import RegionalSettings

    def progress(fraction: float, message: str) -> None:
        print(f"{int(fraction * 100):3d}% {message}", file=sys.stderr, flush=True)

    try:
        spacing = arguments.spacing_km
        settings = RegionalSettings(spacing_km=spacing, process_area_km2=24 * spacing * spacing)
        path = build_region(
            arguments.planet, arguments.output, (arguments.lon, arguments.lat),
            arguments.radius_km, settings, level=arguments.level, cache=arguments.cache,
            pixels=arguments.pixels,
            workers=arguments.workers or None, progress=progress,
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Region generation failed: {error}", file=sys.stderr)
        return 1
    print(f"Region complete: {path}")
    print("Experimental detail; tiles are cached and reused by later regions.")
    return 0


def _view_arguments(
    command: argparse.ArgumentParser, projections: tuple[str, ...], pixels: int
) -> None:
    """The build, map and view options shared by ``world view`` and ``world spin``."""
    command.add_argument("planet", type=Path, help="Planet build folder or its manifest.json.")
    command.add_argument("--theme", default="atlas",
                         help="Map theme, a build image's name without .png: atlas, relief, "
                              "topographic, parchment, koppen, volcanoes, precipitation, "
                              "temperature, plates, seafloor, basins, geology.")
    command.add_argument("--projection", default="globe", choices=projections)
    command.add_argument("--lon", type=float, default=0.0,
                         help="Globe centre, or the meridian at the bottom/top of a polar "
                              "view (where a spin starts).")
    command.add_argument("--lat", type=float, default=0.0, help="Globe centre latitude.")
    command.add_argument("--zoom", type=float, default=1.0,
                         help="Globe zoom: 1 shows the whole globe, up to 16.")
    command.add_argument("--limit", type=float, default=0.0,
                         help="Latitude at the edge of a polar view (0 = the equator).")
    command.add_argument("--pixels", type=int, default=pixels, help="Height in pixels.")
    command.add_argument("--width", type=int, default=None,
                         help="Width in pixels (default: square, or twice the height for a "
                              "flat world). Globe and polar views fit the shorter side.")
    command.add_argument("--graticule", action="store_true", help="Draw a 30-degree grid.")


def _run_world_view(arguments: argparse.Namespace) -> int:
    from map_maker.terrain.adapters.map_projection import MapProjection
    from map_maker.terrain.application.planet_views import export_view

    try:
        projection = MapProjection(
            arguments.projection, arguments.lon, arguments.lat, arguments.limit, arguments.zoom
        )
        path = export_view(
            arguments.planet, arguments.output, arguments.theme, projection,
            arguments.pixels, width=arguments.width, graticule=arguments.graticule,
        )
    except (OSError, ValueError) as error:
        print(f"View failed: {error}", file=sys.stderr)
        return 1
    print(f"View written: {path}")
    return 0


def _run_world_spin(arguments: argparse.Namespace) -> int:
    from map_maker.terrain.adapters.map_projection import MapProjection
    from map_maker.terrain.application.planet_views import export_spin

    try:
        projection = MapProjection(
            arguments.projection, arguments.lon, arguments.lat, arguments.limit, arguments.zoom
        )
        path = export_spin(
            arguments.planet, arguments.output, arguments.theme, projection,
            arguments.pixels, width=arguments.width, frames=arguments.frames,
            seconds=arguments.seconds, graticule=arguments.graticule,
        )
    except (OSError, ValueError) as error:
        print(f"Spin failed: {error}", file=sys.stderr)
        return 1
    print(f"Spin written: {path}")
    return 0


def _run_world_globe(arguments: argparse.Namespace) -> int:
    from map_maker.terrain.application.planet_views import export_globe

    try:
        path = export_globe(arguments.planet, arguments.output, arguments.theme)
    except (OSError, ValueError) as error:
        print(f"Globe failed: {error}", file=sys.stderr)
        return 1
    print(f"Globe written: {path}")
    return 0


def _run_world_bathymetry(arguments: argparse.Namespace) -> int:
    from map_maker.terrain.application.world_bathymetry import build_bathymetry
    try:
        path = build_bathymetry(arguments.inputs, arguments.output)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Bathymetry generation failed: {error}", file=sys.stderr)
        return 1
    print(f"Ocean-depth hypothesis complete: {path}")
    print("Selected-water elevations only; no land DEM, circulation or erosion generated.")
    return 0


def _run_world_bathymetry_inspect(arguments: argparse.Namespace) -> int:
    from map_maker.terrain.application.world_bathymetry import open_bathymetry
    try:
        run = open_bathymetry(arguments.result)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Bathymetry inspection failed: {error}", file=sys.stderr)
        return 1
    result = run.result
    print(f"Verified ocean-depth hypothesis: {result.inputs.world.name}")
    print(f"{result.sampled_cells:,} centre samples; selected water IDs: {result.inputs.ocean_ids}")
    print(f"Selected waters without centre samples: {result.unsampled_ocean_ids}")
    print("Negative bed elevation in metres. Numerical bounds are not geological uncertainty.")
    return 0


def _run_world_geology_inspect(arguments: argparse.Namespace) -> int:
    from map_maker.terrain.application.world_geology import open_geology
    try:
        result = open_geology(arguments.recipe).coverage
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Geology inspection failed: {error}", file=sys.stderr)
        return 1
    print(f"Geology inputs: {result.recipe.world.name}; {len(result.recipe.provinces)} provinces")
    print("Ages: Ma before one common present; simulation span is a separate duration.")
    for region in result.regions:
        p = region.profile
        ages = "; ".join(f"{label} {value:g} Ma" if value is not None else f"{label} unknown"
                        for label, value in (("crust", p.crust_age_ma),
                                             ("rejuvenation", p.rejuvenation_age_ma),
                                             ("simulation span", p.evolution_duration_ma)))
        landform = (
            f"{p.landform.character}; base {p.landform.elevation_m:g} m; "
            f"relief {p.landform.relief_m:g} m" if p.landform else "background terrain"
        )
        print(f"  {region.name}: {region.area_km2:,.0f} km²; {p.setting}; {ages}; {landform}")
    print("Hypotheses and explicit guidance; inspection generates no relief, erosion or climate.")
    print("Use world terrain --geology RECIPE to transfer the landform controls.")
    return 0


def _run_world_context_inspect(arguments: argparse.Namespace) -> int:
    from map_maker.terrain.adapters.build import runtime_identity
    from map_maker.terrain.application.world_context import open_context
    try:
        run = open_context(arguments.context)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Context inspection failed: {error}", file=sys.stderr)
        return 1
    result = run.context
    rows, columns = result.grid.shape
    print(f"Verified context: {result.world.project.name}; {columns} x {rows} cells")
    print(f"{len(result.water_bodies)} water regions; land {result.land_area_km2:,.0f} km²")
    graph = result.connectivity
    print(f"{len(graph.water_body):,} water pieces; {len(graph.link_nodes):,} shared intervals; "
          f"{graph.component_count} graph components; {graph.split_cells:,} split cells.")
    if graph.fragmented_bodies:
        print(f"Unresolved water regions: {graph.fragmented_bodies}; "
              "no inferred connections; transport unsupported for these regions.")
    print("Shared-edge water openings in km; no depth or transport capacity inferred.")
    print(f"Shore distance: {result.shore_sampling.sample_count:,} samples; "
          f"maximum overestimate {result.shore_sampling.max_error_km:.3f} km.")
    print("Water exposure in 8 look directions; mixed-cell support recorded. Not rainfall.")
    print("Producer matches current runtime." if run.runtime == runtime_identity()
          else "Saved producer differs; viewing is supported, regenerate before exporting.")
    return 0


def _run_world_context(arguments: argparse.Namespace) -> int:
    from map_maker.terrain.application.world_context import build_world_context
    from map_maker.terrain.domain.world_context import WorldContextSettings
    try:
        path = build_world_context(arguments.project, arguments.output,
                                   WorldContextSettings(arguments.latitude_cells))
    except (OSError, ValueError, RuntimeError) as error:
        print(f"World context failed: {error}", file=sys.stderr)
        return 1
    print(f"Geographic context complete: {path}")
    print("Geography, water connectivity, shore distance and exposure; "
          "climate and terrain follow later.")
    return 0


def _run_world_refine_coast(arguments: argparse.Namespace) -> int:
    from map_maker.terrain.application.world import export_refined_coast

    def progress(fraction: float, message: str) -> None:
        print(f"{int(fraction * 100):3d}% {message}", file=sys.stderr, flush=True)

    try:
        coast = export_refined_coast(
            arguments.project, arguments.output, master_seed=arguments.seed,
            detail_km=arguments.detail_km, progress=progress,
        )
    except (OSError, ValueError) as error:
        print(f"Coast export failed: {error}", file=sys.stderr)
        return 1
    islands = sum(1 for s in coast.shapes if s.role == "island")
    print(f"Refined coast written: {arguments.output}")
    print(f"{len(coast.shapes)} shapes ({islands} islands), {coast.points:,} points, "
          f"coast detail down to {coast.detail_km:g} km.")
    print("Import it in the World tab: its coast detail is filled in, so zoomed maps "
          "add only finer detail.")
    return 0


def _run_world_inspect(arguments: argparse.Namespace) -> int:
    from map_maker.terrain.application.world import open_world
    try:
        result = open_world(arguments.project)
    except (OSError, ValueError) as error:
        print(f"World inspection failed: {error}", file=sys.stderr)
        return 1
    print(f"World: {result.project.name}")
    print(f"Spherical Plate Carree, radius {result.project.frame.radius_km:g} km")
    print(f"Continents: {len(result.continents)}; land coverage: {result.land_fraction:.2%}")
    for continent in result.continents:
        print(f"  {continent.name}: {continent.area_km2:,.0f} km²; "
              f"{continent.land_shapes} shapes, {continent.island_shapes} island shapes")
    print(f"Import adjustments: {len(result.adjustments)}; original SVG retained.")
    for adjustment in result.adjustments:
        print(f"  {adjustment.message} ({adjustment.area_source_units2:.6g} square source units)")
    print("Source map ready. Use world terrain for a local project; "
          "coupled world terrain is planned.")
    return 0


def _run_terrain_gui(arguments: argparse.Namespace) -> int:
    from map_maker.terrain.ui import run

    if arguments.world is not None:
        run(world=arguments.world)
    else:
        run(arguments.project)
    return 0


def _run_terrain_build(arguments: argparse.Namespace) -> int:
    from map_maker.terrain.application.build import build_terrain_project

    try:
        manifest = build_terrain_project(arguments.project, arguments.output)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Terrain build failed: {error}", file=sys.stderr)
        return 1
    print(f"Terrain build complete: {manifest}")
    return 0


def _run_terrain_region(arguments: argparse.Namespace) -> int:
    from map_maker.terrain.application.regional import sample_terrain_region

    try:
        x0, y0, x1, y1 = arguments.bounds_km
        manifest = sample_terrain_region(arguments.project, arguments.output,
                                         (x0, y0, x1, y1), arguments.refine)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Regional sampling failed: {error}", file=sys.stderr)
        return 1
    print(f"Regional samples complete: {manifest}")
    print("Denser unchanged-field samples; no new detail bands or refined hydrology.")
    return 0


def _run_parent_region(arguments: argparse.Namespace) -> int:
    from map_maker.terrain.application.parent_region import sample_parent_region
    from map_maker.terrain.application.region_memory import MIB, RegionalMemoryBudget
    from map_maker.terrain.domain.regional import RegionalDetailSettings

    try:
        x0, y0, x1, y1 = arguments.bounds_km
        detail = (RegionalDetailSettings(arguments.amplitude_m)
                  if arguments._experimental_detail else None)
        budget = (RegionalMemoryBudget(arguments.memory_mib * MIB)
                  if arguments.memory_mib is not None else None)
        manifest = sample_parent_region(
            arguments.parent, arguments.output, (x0, y0, x1, y1), arguments.refine,
            detail_settings=detail, memory_budget=budget,
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Parent regional generation failed: {error}", file=sys.stderr)
        return 1
    print(f"Parent regional result complete: {manifest}")
    print("Experimental added detail; hydrology unreviewed, small rivers unavailable."
          if detail else "Verified parent field; no new detail or refined hydrology.")
    return 0


def _run_terrain_water_budget(arguments: argparse.Namespace) -> int:
    from map_maker.terrain.application.water_budget import forecast_project_water_budget
    from map_maker.terrain.pipeline.water_budget import SamplingDemand

    try:
        result = forecast_project_water_budget(arguments.project)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Water budget forecast failed: {error}", file=sys.stderr)
        return 1
    budget = result.budget
    print(f"Water sampling budget: {result.project_path}")
    print(f"Canonical grid: {budget.grid_width} x {budget.grid_height}; "
          f"sampler: {budget.sampling_algorithm_id}")
    print(f"Limits: {budget.profile_sample_limit:,} stations/profile; "
          f"{budget.wet_network_sample_limit:,}/wet network; "
          f"{budget.dry_network_sample_limit:,}/dry network.")
    print("Counts include repeated stations. Budget failures are lower bounds.")
    print("Potential networks depend on outlet, shoreline and wet-connectivity checks. "
          "External routes/contacts and terrain clearance are not evaluated.")

    def show_demand(label: str, demand: SamplingDemand) -> None:
        count = f"{demand.requested_sample_count:,}"
        count = f"{count} (exact)" if demand.count_is_exact else f"at least {count}"
        status = ("within budget" if demand.status == "within_budget" else
                  f"EXCEEDS {demand.limiting_budget} budget")
        print(f"  {label}: {count} stations; {status}; "
              f"{demand.candidate_profile_count:,} profiles, "
              f"{demand.visited_profile_count:,} visited; "
              f"baseline {demand.baseline_sample_count:,}.")

    if not budget.basins:
        print("No authored basins; no shoreline or internal-network demand.")
    for basin in budget.basins:
        outlet = ", authored outlet" if basin.has_outlet else ""
        kind = basin.kind.replace("_", " ")
        print(f"Basin {basin.intent_id} ({kind}{outlet}): "
              f"{basin.footprint_cell_count:,} canonical nodes, {basin.wet_cell_count:,} wet.")
        if not basin.footprint_cell_count:
            print("  Footprint unresolved on the canonical grid; full review is required.")
        if basin.shoreline is not None:
            show_demand("Shoreline", basin.shoreline)
        if basin.wet_links is not None:
            show_demand("Potential wet network", basin.wet_links)
        if basin.dry_links is not None:
            show_demand("Potential dry network", basin.dry_links)
        if basin.wet_links is None:
            print("  No internal outlet network for this basin.")
    print(f"Project SHA-256: {result.project_sha256}")
    print(f"Coastline SHA-256: {result.coastline_sha256}")
    print(f"Generator source SHA-256: {result.runtime['package_source_sha256']}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = create_parser()
    arguments = parser.parse_args(argv)

    handler = getattr(arguments, "_handler", None)
    if handler is not None:
        return handler(arguments)
    command_parser: argparse.ArgumentParser | None = getattr(arguments, "_command_parser", None)
    if command_parser is not None:
        command_parser.print_help()
    else:
        parser.print_help()
    return 0
