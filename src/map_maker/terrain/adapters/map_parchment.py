# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Fantasy / parchment map: inked coasts, mountain and tree symbols on old paper.

The same terrain drawn the way hand-made world maps draw it: symbols where the
relief, vegetation and water are, not shaded pixels. Symbol placement uses a
seeded jittered grid, so a map is identical every time it is drawn.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt as _edt
from scipy.ndimage import gaussian_filter

type F64 = NDArray[np.float64]
type B = NDArray[np.bool_]


def distance_transform_edt(mask: B) -> F64:
    """Distance (pixels) from each True pixel to the nearest False one."""
    return np.asarray(_edt(mask), dtype=np.float64)


PAPER: tuple[int, int, int] = (234, 218, 182)
STAIN: tuple[int, int, int] = (196, 168, 120)
SEA: tuple[int, int, int] = (190, 200, 186)
INK: tuple[int, int, int] = (58, 42, 30)
RIVER_INK: tuple[int, int, int] = (40, 62, 100)
SUPERSAMPLE = 2
MOUNTAIN_MIN_ROUGH_M = 150.0
HILL_MIN_ROUGH_M = 60.0
MOUNTAIN_SHARE_ABOVE = 0.85  # roughness quantile from which land is mountainous
HILL_SHARE_ABOVE = 0.55


@dataclass(frozen=True, slots=True)
class ParchmentInputs:
    """Per-pixel fields of the area to draw (NaN elevation outside it)."""

    elevation_m: F64
    land: B
    lakes: B
    rivers: F64  # 0..1 river coverage
    light: F64  # hillshade, 1 on flat ground
    forest: F64  # 0..1 tree cover
    cold: B  # conifers rather than broadleaf trees
    desert: F64  # 0..1 bare dry ground
    wetland: F64  # 0..1 marsh
    ice: B
    snow: B  # perennial snow: peaks drawn with snow caps
    volcanoes: tuple[tuple[float, float, bool], ...] = ()  # (column, row, active)


def parchment_image(
    inputs: ParchmentInputs, seed: int, symbol_px: float, *, framed: bool = True
) -> Image.Image:
    """The map; ``symbol_px`` is the width of a large mountain symbol in pixels.

    ``framed`` rules a double frame inside the sheet's edges. Regional windows
    are drawn without it: their disc touches the edges, and the globe shows
    them over the world map.
    """
    z = inputs.elevation_m
    inside = np.isfinite(z)
    zz = np.where(inside, z, 0.0)
    rows, columns = z.shape
    rng = np.random.default_rng([seed, 4242])
    rgb = _paper(rows, columns, rng)
    land = inputs.land & inside
    water = inside & (~inputs.land | inputs.lakes)
    # Sea wash and the ripple lines that follow the coast outwards.
    rgb = np.where(water[..., None], 0.55 * rgb + 0.45 * np.array(SEA, dtype=np.float64), rgb)
    shore_distance = distance_transform_edt(water)
    spacing = max(2.5, symbol_px / 5)
    for k in range(1, 4):
        line = np.clip(1 - np.abs(shore_distance - k * spacing) / 0.7, 0, 1) * (
            water & ~inputs.lakes
        )
        alpha = (0.45 * (1 - k / 4.5) * line)[..., None]
        rgb = rgb * (1 - alpha) + np.array(INK, dtype=np.float64) * alpha
    # A faint wash of relief on land, as an engraver's stipple would give.
    rgb = np.where(
        land[..., None], rgb * (0.9 + 0.1 * np.clip(inputs.light, 0, 1.3))[..., None], rgb
    )
    coast = distance_transform_edt(~land) <= 1.2
    coast &= ~land | (distance_transform_edt(land) <= 1.0)
    rgb[coast & inside] = 0.25 * rgb[coast & inside] + 0.75 * np.array(INK, dtype=np.float64)
    alpha = (0.95 * np.clip(1.6 * inputs.rivers, 0, 1) * land)[..., None]
    rgb = rgb * (1 - alpha) + np.array(RIVER_INK, dtype=np.float64) * alpha
    rgb = np.where(inside[..., None], rgb, np.array(PAPER, dtype=np.float64) * 0.93)
    image = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))
    symbols = _symbols(inputs, zz, land & ~inputs.lakes & ~inputs.ice, rng, symbol_px)
    image = _stamp(image, symbols)
    return _frame(image) if framed else image


@dataclass(frozen=True, slots=True)
class _Symbol:
    kind: str
    x: float
    y: float
    size: float
    flag: bool = False  # snow cap, conifer or active volcano


def _symbols(
    inputs: ParchmentInputs, z: F64, ground: B, rng: np.random.Generator, symbol_px: float
) -> list[_Symbol]:
    rows, columns = z.shape
    # Mapmakers draw mountains where the ground is rugged, not merely high: a
    # plateau is plain country. Roughness is the height spread within about a
    # symbol's reach; summits above their surroundings get the symbols.
    # Statistics over land only: a coast below a high plateau and the blank
    # beyond a round window are not cliffs.
    on_land = (inputs.land & np.isfinite(inputs.elevation_m)).astype(np.float64)
    ground_z = np.where(on_land > 0, z, 0.0)
    weight = np.maximum(gaussian_filter(on_land, symbol_px), 1e-6)
    mean = gaussian_filter(ground_z, symbol_px) / weight
    square = gaussian_filter(ground_z * ground_z, symbol_px) / weight
    rough = np.sqrt(np.maximum(square - mean * mean, 0.0))
    above = np.clip((ground_z - mean) / np.maximum(rough, 1.0), -1, 1)
    # Thresholds follow the map's own range of ruggedness (a world map and a
    # valley map differ by orders of magnitude) above absolute floors, so only the
    # most rugged ground gets mountains and a plain stays a plain.
    land_rough = rough[ground] if ground.any() else np.zeros(1)
    high = max(MOUNTAIN_MIN_ROUGH_M, float(np.quantile(land_rough, MOUNTAIN_SHARE_ABOVE)))
    mid = max(HILL_MIN_ROUGH_M, float(np.quantile(land_rough, HILL_SHARE_ABOVE)))
    mountain = np.clip((rough - high) / high + 0.5, 0, 1) * (0.6 + 0.4 * above)
    hill = np.clip((rough - mid) / mid + 0.5, 0, 1) * (0.6 + 0.4 * above)
    out: list[_Symbol] = []
    taken = np.zeros((rows, columns), dtype=bool)

    def place(kind: str, score: F64, step: float, threshold: float, size: float) -> None:
        for y0 in np.arange(0, rows, step):
            for x0 in np.arange(0, columns, step):
                x = x0 + rng.uniform(0.15, 0.85) * step
                y = y0 + rng.uniform(0.15, 0.85) * step
                c, r = int(x), int(y)
                if not (0 <= r < rows and 0 <= c < columns) or not ground[r, c] or taken[r, c]:
                    continue
                s = float(score[r, c])
                if s < threshold or rng.random() > min(1.0, s * 1.4):
                    continue
                flag = (
                    bool(inputs.snow[r, c])
                    if kind == "mountain"
                    else (bool(inputs.cold[r, c]) if kind == "tree" else False)
                )
                scale = size * (0.75 + 0.5 * min(s, 1.0))
                out.append(_Symbol(kind, x, y, scale, flag))
                half = max(1, int(scale * 0.45))
                taken[max(r - half, 0) : r + half, max(c - half, 0) : c + half] = True

    for column, row, active in inputs.volcanoes:
        c, r = int(column), int(row)
        if 0 <= r < rows and 0 <= c < columns and ground[r, c]:
            out.append(_Symbol("volcano", column, row, symbol_px * 0.9, active))
            half = int(symbol_px * 0.5)
            taken[max(r - half, 0) : r + half, max(c - half, 0) : c + half] = True
    place("mountain", mountain, symbol_px * 0.55, 0.45, symbol_px)
    place("hill", np.where(mountain < 0.45, hill, 0.0), symbol_px * 0.6, 0.35, symbol_px * 0.55)
    # Woods are drawn as stands: narrow riverside forest would bead along rivers.
    woods = gaussian_filter(inputs.forest, symbol_px * 0.4)
    place("tree", woods, symbol_px * 0.28, 0.45, symbol_px * 0.3)
    place("marsh", inputs.wetland, symbol_px * 0.45, 0.4, symbol_px * 0.35)
    place("dune", inputs.desert, symbol_px * 0.5, 0.55, symbol_px * 0.35)
    # Draw from the top of the map down, so nearer symbols overlap farther ones.
    return sorted(out, key=lambda symbol: symbol.y)


def _stamp(image: Image.Image, symbols: list[_Symbol]) -> Image.Image:
    k = SUPERSAMPLE
    big = image.resize((image.width * k, image.height * k), Image.Resampling.BILINEAR)
    draw = ImageDraw.Draw(big)
    ink = INK
    paper = PAPER
    for s in symbols:
        x, y, w = s.x * k, s.y * k, s.size * k
        line = max(1, round(w / 18))
        if s.kind in ("mountain", "volcano"):
            h = w * (0.85 if s.kind == "mountain" else 0.6)
            apex = (x + w * 0.05, y - h * 0.6)
            left, right = (x - w / 2, y + h * 0.4), (x + w / 2, y + h * 0.4)
            draw.polygon([left, apex, right], fill=paper)
            draw.line([left, apex, right], fill=ink, width=line)
            # Shade the lee side with strokes from the ridge line down.
            for t in np.linspace(0.2, 0.85, 4):
                top = (
                    apex[0] + (right[0] - apex[0]) * t * 0.35,
                    apex[1] + (right[1] - apex[1]) * t * 0.35,
                )
                bottom = (apex[0] + (right[0] - apex[0]) * t, right[1])
                draw.line([top, bottom], fill=ink, width=max(1, line // 2 + 1))
            if s.kind == "mountain" and s.flag:
                cap = [
                    (apex[0] - w * 0.14, apex[1] + h * 0.22),
                    (apex[0] - w * 0.04, apex[1] + h * 0.14),
                    (apex[0] + w * 0.06, apex[1] + h * 0.24),
                    (apex[0] + w * 0.15, apex[1] + h * 0.18),
                ]
                draw.line(cap, fill=ink, width=line)
            if s.kind == "volcano":
                crater = (apex[0] - w * 0.08, apex[1] - 2, apex[0] + w * 0.08, apex[1] + 2)
                draw.ellipse(crater, outline=ink, width=line)
                if s.flag:
                    for i in range(3):
                        cx = apex[0] + i * w * 0.08
                        cy = apex[1] - (i + 1) * h * 0.25
                        draw.arc(
                            (cx - w * 0.1, cy - h * 0.12, cx + w * 0.1, cy + h * 0.12),
                            200,
                            340,
                            fill=ink,
                            width=line,
                        )
        elif s.kind == "hill":
            box = (x - w / 2, y - w * 0.3, x + w / 2, y + w * 0.3)
            draw.chord(box, 180, 360, fill=paper)
            draw.arc(box, 180, 360, fill=ink, width=line)
            draw.line([(x + w * 0.12, y - w * 0.12), (x + w * 0.3, y)], fill=ink, width=line)
        elif s.kind == "tree":
            if s.flag:
                draw.polygon(
                    [(x, y - w * 0.75), (x - w * 0.32, y + w * 0.1), (x + w * 0.32, y + w * 0.1)],
                    fill=paper,
                    outline=ink,
                )
            else:
                # A broadleaf crown: a round top with its shaded lower right side.
                crown = (x - w * 0.32, y - w * 0.72, x + w * 0.32, y - w * 0.08)
                draw.ellipse(crown, fill=paper, outline=ink, width=line)
                draw.arc(
                    (
                        crown[0] + w * 0.08,
                        crown[1] + w * 0.08,
                        crown[2] - w * 0.04,
                        crown[3] - w * 0.04,
                    ),
                    10,
                    120,
                    fill=ink,
                    width=line,
                )
            draw.line([(x, y - w * 0.08), (x, y + w * 0.3)], fill=ink, width=line)
        elif s.kind == "marsh":
            for dx in (-0.3, 0.0, 0.3):
                draw.line(
                    [(x + dx * w, y), (x + dx * w + w * 0.05, y - w * 0.35)], fill=ink, width=line
                )
            draw.line([(x - w * 0.45, y + 1), (x + w * 0.45, y + 1)], fill=ink, width=line)
        elif s.kind == "dune":
            draw.arc(
                (x - w / 2, y - w * 0.25, x + w / 2, y + w * 0.25), 200, 340, fill=ink, width=line
            )
    return big.resize(image.size, Image.Resampling.LANCZOS)


def _paper(rows: int, columns: int, rng: np.random.Generator) -> F64:
    """Aged paper: fibre grain, broad stains and darker edges."""
    grain = gaussian_filter(rng.normal(size=(rows, columns)), 1.0)
    grain /= max(float(np.abs(grain).max()), 1e-9)
    stains = gaussian_filter(rng.normal(size=(rows, columns)), max(rows, columns) / 25)
    stains /= max(float(np.abs(stains).max()), 1e-9)
    y, x = np.mgrid[0:rows, 0:columns]
    edge = np.minimum.reduce([x, y, columns - 1 - x, rows - 1 - y]) / max(
        min(rows, columns) * 0.08, 1
    )
    vignette = 1 - np.clip(1 - edge, 0, 1) ** 2
    stain = np.clip(0.5 * stains + 0.25 * (1 - vignette), 0, 1)
    base = np.array(PAPER, dtype=np.float64) * (1 + 0.025 * grain)[..., None]
    return (
        base * (1 - 0.6 * stain[..., None])
        + np.array(STAIN, dtype=np.float64) * 0.6 * stain[..., None]
    )


def _frame(image: Image.Image) -> Image.Image:
    draw = ImageDraw.Draw(image)
    w, h = image.size
    inset = max(4, min(w, h) // 120)
    draw.rectangle(
        (inset, inset, w - 1 - inset, h - 1 - inset), outline=INK, width=max(1, inset // 3)
    )
    gap = inset + max(3, inset // 2)
    draw.rectangle((gap, gap, w - 1 - gap, h - 1 - gap), outline=INK, width=1)
    return image
