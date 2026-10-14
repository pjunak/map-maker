"""Paired actual-ground figures using the same frozen channel geometry."""

from html import escape
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from benchmarks.evolution.paths import ChannelPaths, PathNetwork, Sampler, profile
from benchmarks.evolution.surface import FlowAlignedSurface
from map_maker.terrain.adapters.render import render_ground_map
from map_maker.terrain.domain.coordinates import EndpointGrid


def render_panel(
    sampler: Sampler,
    paths: PathNetwork,
    bounds: tuple[float, float, float, float],
    maximum_m: float,
) -> Image.Image:
    x0, y0, x1, y1 = bounds
    width = 620
    height = max(64, round((width - 1) * (y1 - y0) / (x1 - x0)) + 1)
    x, y = np.meshgrid(np.linspace(x0, x1, width), np.linspace(y0, y1, height))
    ground = sampler(x, y)
    grid = EndpointGrid((x0 / 1000.0, y0 / 1000.0, x1 / 1000.0, y1 / 1000.0), width, height)
    panel = render_ground_map(ground, np.ones(ground.shape, dtype=np.bool_), grid, maximum_m)
    draw = ImageDraw.Draw(panel)
    for source in np.flatnonzero(paths.required):
        target = int(paths.receivers.flat[source])
        px, py = paths.points(np.array([source, target], dtype=np.int64))
        points = list(
            zip(
                (px - x0) / (x1 - x0) * (width - 1),
                (py - y0) / (y1 - y0) * (height - 1),
                strict=True,
            )
        )
        draw.line(points, fill="#003c78", width=1)
    return panel.convert("RGB")


def render_pair(
    output: Path,
    label: str,
    field: FlowAlignedSurface,
    paths: ChannelPaths,
    control: dict[str, Any],
    maximum_m: float,
) -> None:
    font = ImageFont.load_default(size=18)
    small = ImageFont.load_default(size=15)
    bounds = (0.0, 0.0, field.grid.width_m, field.grid.height_m)
    pair = [
        render_panel(sampler, paths, bounds, maximum_m)
        for sampler in (field.bilinear, field.sample)
    ]
    worst = max(control["edges"], key=lambda row: row["maximum_excursion_m"], default=None)
    zoom: list[Image.Image] = []
    if worst is not None:
        row, col = divmod(worst["source"], field.grid.shape[1])
        size = min(8, field.grid.shape[0] - 1, field.grid.shape[1] - 1) * field.grid.spacing_m
        x0 = min(max(0.0, (col - 4) * field.grid.spacing_m), field.grid.width_m - size)
        y0 = min(max(0.0, (row - 4) * field.grid.spacing_m), field.grid.height_m - size)
        zoom = [
            render_panel(sampler, paths, (x0, y0, x0 + size, y0 + size), maximum_m)
            for sampler in (field.bilinear, field.sample)
        ]
    h1 = pair[0].height
    h2 = zoom[0].height if zoom else 0
    image = Image.new("RGB", (1280, h1 + h2 + 410), "#fafafa")
    draw = ImageDraw.Draw(image)
    draw.text((20, 10), label, fill="#161b22", font=font)
    draw.text(
        (20, 35),
        f"Shared height scale: 0 to {maximum_m:.0f} m; blue lines: same required graph",
        fill="#161b22",
        font=small,
    )
    for index, title in enumerate(("Bilinear control", "Required-diagonal surface")):
        x = 20 + index * 640
        draw.text((x, 62), title, fill="#161b22", font=font)
        image.paste(pair[index], (x, 90))
        if zoom:
            draw.text(
                (x, h1 + 108), "Same crop around worst control edge", fill="#161b22", font=small
            )
            image.paste(zoom[index], (x, h1 + 135))
    route = max(control["routes"], key=lambda row: row["maximum_excursion_m"], default=None)
    top = h1 + h2 + 180
    if route is not None:
        nodes = paths.route(route["head"])
        distances, bilinear = profile(paths, nodes, field.bilinear, 25.0)
        _, aligned = profile(paths, nodes, field.sample, 25.0)
        draw.text(
            (20, top),
            f"Complete control-worst route {route['head']} to {route['terminal']} "
            f"({distances[-1] / 1000.0:.1f} km); 25 m stations + vertices",
            fill="#161b22",
            font=font,
        )
        low, high = (
            min(float(bilinear.min()), float(aligned.min())),
            max(float(bilinear.max()), float(aligned.max())),
        )
        high = max(high, low + 1.0)
        draw.rectangle((60, top + 45, 1220, top + 180), outline="#999999")
        for heights, colour in ((bilinear, "#b34515"), (aligned, "#0669a3")):
            points = list(
                zip(
                    60 + distances / distances[-1] * 1160,
                    top + 180 - (heights.astype(np.float64) - low) / (high - low) * 135,
                    strict=True,
                )
            )
            draw.line(points, fill=colour, width=2)
        draw.text(
            (65, top + 190),
            f"{low:.1f} to {high:.1f} m | orange: control; blue: candidate",
            fill="#161b22",
            font=small,
        )
    else:
        draw.text(
            (20, top),
            "No required routes at the fixed 25 km2 threshold.",
            fill="#161b22",
            font=font,
        )
    image.save(output)


def write_index(output: Path, rows: list[dict[str, Any]], omissions: list[dict[str, str]]) -> None:
    entries: list[str] = []
    for row in rows:
        folder = escape(row["folder"], quote=True)
        label = escape(row["label"])
        text = f"<h2>{label}</h2><p><a href='{folder}/result.json'>Complete measurements</a></p>"
        if row["status"] == "compared":
            text += f"<a href='{folder}/comparison.png'><img src='{folder}/comparison.png'></a>"
        else:
            text += f"<p>Rejected: {escape(row['reason'])}</p>"
        entries.append(text)
    omitted = "".join(f"<li>{escape(r['source'])}: {escape(r['reason'])}</li>" for r in omissions)
    html = (
        "<!doctype html><meta charset='utf-8'><title>Frozen reconstruction comparison</title>"
        "<style>body{font:16px system-ui;max-width:1300px;margin:24px auto;padding:0 16px}"
        "img{width:100%;height:auto}h2{margin-top:40px}</style>"
        "<h1>Frozen reconstruction comparison</h1><p>Both surfaces keep identical Float32 "
        "nodes, required channels, heads and terminals. Paths use saved final Float64-snapshot "
        "routing, not the original report's Float32-rerouted final metrics.</p>"
        "<p>The candidate remains experimental: D8 geometry, nodal uphill routes, C0 facets, "
        "off-grid authoring conflicts and process-grid sensitivity remain. Blue terrain tint "
        "is elevation, not water. Figures sample actual ground; there is no line smoothing.</p>"
        "<p><a href='comparison.json'>Comparison identity, coverage and summaries</a></p>"
        + (
            "<h2>Source runs without completed states</h2><ul>" + omitted + "</ul>"
            if omitted
            else ""
        )
        + "".join(entries)
    )
    with (output / "index.html").open("x", encoding="utf-8") as stream:
        stream.write(html)
