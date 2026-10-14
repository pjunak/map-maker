"""Isolate cached-water display and native composition memory in fresh workers."""

import argparse
import json
import subprocess
import sys
from contextlib import closing
from hashlib import sha256
from pathlib import Path
from time import perf_counter

from PIL import Image, ImageDraw

from benchmarks.terrain import peak_resident_bytes
from map_maker.terrain.adapters.build import canonical_json, file_sha256, runtime_identity
from map_maker.terrain.adapters.render import compose_height_map
from map_maker.terrain.adapters.water_display import WaterDisplay


def pixel_digest(image: Image.Image) -> str:
    """Hash row bands without adding a second full image to a measured process."""
    digest = sha256(f"{image.mode}:{image.size}".encode())
    for top in range(0, image.height, 64):
        with closing(image.crop((0, top, image.width, min(top + 64, image.height)))) as band:
            digest.update(band.tobytes())
    return digest.hexdigest()


def measure(resolution: int, mode: str) -> dict[str, object]:
    runtime = runtime_identity()
    baseline = peak_resident_bytes()
    size = (resolution, resolution)
    with (closing(Image.new("RGBA", size, (83, 127, 96, 255))) as ground,
          closing(Image.new("F", size)) as areas):
        # Synthetic cached area categories isolate display cost from polygonization,
        # terrain generation and hydrology. Values exercise hidden/fading/opaque water.
        draw = ImageDraw.Draw(areas)
        for i, value in enumerate((0., 4., 9., 16., 25., 36., 100000.)):
            left, right = i * resolution // 7, (i + 1) * resolution // 7
            draw.rectangle((left, 0, right - 1, resolution - 1), fill=value)
        water = WaterDisplay(areas)
        setup_peak = peak_resident_bytes()
        records: list[dict[str, object]] = []
        identity = None
        for _ in range(3):
            start = perf_counter()
            if mode == "compose":
                image = compose_height_map(ground, water)
            elif mode == "water":
                image = water.render((0., 0., float(resolution), float(resolution)), size)
            else:
                image = water.render((-175.25, -102.75, 1950.5, 1830.125), (1296, 768))
            with closing(image):
                elapsed, peak = perf_counter() - start, peak_resident_bytes()
                digest = pixel_digest(image)
                if identity is not None and digest != identity:
                    raise RuntimeError("Repeated display changed pixels.")
                identity = digest
                records.append({"seconds": elapsed, "process_peak_bytes": peak,
                                "output_size": image.size, "pixels_sha256": digest})
        source_identity = pixel_digest(ground), pixel_digest(areas)
    if runtime_identity() != runtime:
        raise RuntimeError("Runtime changed during display measurement.")
    return {"runtime": runtime, "mode": mode, "resolution": resolution,
            "baseline_process_peak_bytes": baseline, "setup_peak_bytes": setup_peak,
            "source_pixels_sha256": source_identity, "steps": records}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolution", type=int, nargs="+", default=[1024, 4096])
    parser.add_argument("--mode", choices=["compose", "water", "viewport"], nargs="+",
                        default=["compose", "water", "viewport"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if any(not 2 <= size <= 4096 for size in args.resolution):
        parser.error("Resolution must be between 2 and 4096.")
    if args.worker:
        print(json.dumps(measure(args.resolution[0], args.mode[0])))
        return 0
    output: Path = args.output
    if output.exists() or output.is_symlink():
        parser.error("Choose a new report file.")
    runtime, runner_hash = runtime_identity(), file_sha256(Path(__file__))
    rows: list[dict[str, object]] = []
    for size in args.resolution:
        for mode in args.mode:
            completed = subprocess.run(
                [sys.executable, "-m", "benchmarks.preview_memory", "--worker",
                 "--resolution", str(size), "--mode", mode, "--output", str(output)],
                check=True, capture_output=True, text=True,
            )
            row: dict[str, object] = json.loads(completed.stdout)
            if row["runtime"] != runtime:
                raise RuntimeError("Worker runtime differs from controller.")
            rows.append(row)
            print(f"{size} {mode}: complete; repeated pixel hashes matched", flush=True)
    if runtime_identity() != runtime or file_sha256(Path(__file__)) != runner_hash:
        raise RuntimeError("Source changed; no report published.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(canonical_json({
            "runtime": runtime, "benchmark_sha256": runner_hash, "runs": rows,
            "limits": ["Fresh process per resolution/mode, three serial renders per worker.",
                       "Synthetic cached pool areas; excludes preparation, terrain and Tk.",
                       "Lifetime native peaks include imports and allocator retention.",
                       "Render times exclude row-band pixel hashing and source hashing."],
        }))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
