#!/usr/bin/env python3
"""
Bernoulli grain tile generator — fallback approach for cinegrain v2.

Not physically accurate (no crystal simulation), but produces visually
convincing grain by exploiting the central limit theorem:
  Binary random field → Gaussian blur → downscale → organic grain

The blur sigma controls the grain size. The downscale from high resolution
averages over many random pixels → smooth, Gaussian-distributed grain.

This is the best visual match to real scans so far (2026-04-09).
Metrically: ac1=0.916, gw=7.7px vs scan ac1=0.910, gw=7.3px for 16mm heavy.

Usage:
    python3 generate_grain_tiles_bernoulli.py [--sigma 7] [--gen-size 2048]
"""

import numpy as np
import argparse
from pathlib import Path
from scipy.ndimage import gaussian_filter


# Blur sigma at gen resolution → approximate output grain width:
# gw_output ≈ sigma * 2 * tile_size / gen_size
# At gen=2048, tile=512: gw ≈ sigma * 0.5
#
# 16mm heavy scan: gw=7.3px → sigma ≈ 14 ... but empirically sigma=7 at 2048→512
# gives gw=7.7. The downscale itself adds correlation.
PRESETS = {
    "35mm-50D":  {"sigma": 4,  "description": "Very fine grain (gw ~4.6px)"},
    "35mm-250D": {"sigma": 5,  "description": "Fine grain (gw ~5.6px)"},
    "35mm-500T": {"sigma": 6,  "description": "Moderate grain (gw ~6.7px)"},
    "16mm-50D":  {"sigma": 7,  "description": "Visible grain (gw ~7.7px)"},
    "16mm-500T": {"sigma": 9,  "description": "Heavy grain (gw ~9.7px)"},
    "S8-50D":    {"sigma": 12, "description": "Coarse grain (gw ~12.6px)"},
    "S8-500T":   {"sigma": 16, "description": "Very coarse grain (gw ~16px)"},
}


def generate_tile(gen_size, tile_size, sigma, seed):
    rng = np.random.default_rng(seed)

    # Binary random field at high resolution
    field = (rng.random((gen_size, gen_size)) < 0.5).astype(np.float32)

    # Optical transfer function (Gaussian blur)
    field = gaussian_filter(field, sigma=sigma)

    # High-pass: remove low-frequency density variation
    field = field - gaussian_filter(field, sigma=gen_size // 32)

    # Downscale to tile size (area averaging = optical integration)
    from PIL import Image
    tile = np.array(
        Image.fromarray(field).resize((tile_size, tile_size), Image.LANCZOS),
        dtype=np.float64,
    )

    # Normalize to [-1, 1]
    std = np.std(tile)
    if std > 0:
        tile = tile / (3.0 * std)
    return np.clip(tile, -1.0, 1.0)


def build_atlas(n_tiles, gen_size, tile_size, sigma, seed=None):
    rng = np.random.default_rng(seed)
    tiles = []
    for i in range(n_tiles):
        s = rng.integers(0, 2**32)
        print(f"  Tile {i+1}/{n_tiles} (seed={s}, sigma={sigma})...")
        tiles.append(generate_tile(gen_size, tile_size, sigma, s))

    cols = 2
    rows = (n_tiles + cols - 1) // cols
    atlas = np.zeros((rows * tile_size, cols * tile_size), dtype=np.float64)
    for i, tile in enumerate(tiles):
        r, c = i // cols, i % cols
        atlas[r*tile_size:(r+1)*tile_size, c*tile_size:(c+1)*tile_size] = tile
    return atlas


def save_atlas(atlas, path):
    from PIL import Image
    data = np.clip(atlas * 0.5 + 0.5, 0.0, 1.0)
    data_16 = (data * 65535).astype(np.uint16)
    Image.fromarray(data_16, mode='I;16').save(path)
    print(f"  Saved: {path} ({data_16.shape[1]}x{data_16.shape[0]}, 16-bit)")


def main():
    parser = argparse.ArgumentParser(description="Bernoulli grain tile generator")
    parser.add_argument("preset", nargs="?", default="16mm-50D",
                        choices=list(PRESETS.keys()))
    parser.add_argument("--sigma", type=float, default=None,
                        help="Override blur sigma")
    parser.add_argument("--gen-size", type=int, default=2048)
    parser.add_argument("--tile-size", type=int, default=512)
    parser.add_argument("--n-tiles", type=int, default=4)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--output", "-o", default=None)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    output_dir = Path(__file__).parent.parent / "tiles"
    output_dir.mkdir(exist_ok=True)

    presets = list(PRESETS.keys()) if args.all else [args.preset]

    for name in presets:
        sigma = args.sigma or PRESETS[name]["sigma"]
        print(f"\n[{name}] {PRESETS[name]['description']}")
        atlas = build_atlas(args.n_tiles, args.gen_size, args.tile_size, sigma, args.seed)
        path = args.output or str(output_dir / f"{name}-bernoulli.png")
        save_atlas(atlas, path)

    print("\nDone.")


if __name__ == "__main__":
    main()
