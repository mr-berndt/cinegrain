#!/usr/bin/env python3
"""
Newson-style film grain tile generator for cinegrain v2.

Generates physically-motivated grain tiles using:
1. Poisson point process for crystal positions
2. Log-normal crystal size distribution
3. Gaussian blur as optical transfer function (scanner/projection)
4. Downscale to output tile size

Output: grayscale PNG atlas ready for //!TEXTURE loading in mpv.

Usage:
    python3 generate_grain_tiles.py [preset] [--output path]

Presets: 35mm-50D, 35mm-250D, 35mm-500T, 16mm-50D, 16mm-500T, S8-50D, S8-500T
"""

import numpy as np
import argparse
from pathlib import Path

# ── Film stock presets ─────────────────────────────────────────────────────────
# crystal_density: crystals per pixel² at generation resolution
# crystal_size_mean/std: log-normal parameters (in pixels at gen resolution)
# blur_sigma: optical transfer function (Gaussian blur before downscale)
PRESETS = {
    "35mm-50D": {
        "crystal_density": 0.8,
        "crystal_size_mean": 1.2,
        "crystal_size_std": 0.4,
        "blur_sigma": 2.0,
        "description": "Slow daylight stock, very fine grain",
    },
    "35mm-250D": {
        "crystal_density": 0.6,
        "crystal_size_mean": 1.8,
        "crystal_size_std": 0.5,
        "blur_sigma": 2.0,
        "description": "Medium daylight stock, moderate grain",
    },
    "35mm-500T": {
        "crystal_density": 0.5,
        "crystal_size_mean": 2.5,
        "crystal_size_std": 0.6,
        "blur_sigma": 2.0,
        "description": "Fast tungsten stock, visible grain",
    },
    "16mm-50D": {
        "crystal_density": 0.8,
        "crystal_size_mean": 1.2,
        "crystal_size_std": 0.4,
        "blur_sigma": 1.5,
        "description": "Fine 16mm — more magnification = coarser appearance",
    },
    "16mm-500T": {
        "crystal_density": 0.15,
        "crystal_size_mean": 2.0,
        "crystal_size_std": 0.3,
        "blur_sigma": 1.0,
        "description": "Fast 16mm, heavy grain",
    },
    "S8-50D": {
        "crystal_density": 0.8,
        "crystal_size_mean": 1.2,
        "crystal_size_std": 0.4,
        "blur_sigma": 1.0,
        "description": "Super 8 fine stock, extreme magnification",
    },
    "S8-500T": {
        "crystal_density": 0.5,
        "crystal_size_mean": 2.5,
        "crystal_size_std": 0.6,
        "blur_sigma": 1.0,
        "description": "Super 8 fast stock, maximum grain",
    },
}


def generate_grain_field(width, height, density, size_mean, size_std, rng):
    """
    Generate a grain field using Poisson point process with log-normal crystals.

    Each crystal is a small Gaussian splat at a random position with random size.
    This approximates the physical process of silver halide crystals developing
    on the film emulsion.
    """
    field = np.zeros((height, width), dtype=np.float64)

    # Number of crystals from Poisson process
    area = width * height
    n_crystals = rng.poisson(density * area)

    # Random positions (uniform)
    cx = rng.uniform(0, width, n_crystals)
    cy = rng.uniform(0, height, n_crystals)

    # Log-normal crystal sizes (radius in pixels)
    sizes = rng.lognormal(np.log(size_mean), size_std, n_crystals)
    sizes = np.clip(sizes, 0.5, size_mean * 4)

    # Random opacity per crystal
    opacity = rng.uniform(0.5, 1.0, n_crystals)

    # Paint filled discs (not point masses) — this gives crystals physical extent.
    # Use np.add.at for vectorized accumulation per radius bin.
    n_bins = 12
    size_min, size_max = float(sizes.min()), float(sizes.max())
    bin_edges = np.linspace(size_min, size_max, n_bins + 1)

    for b in range(n_bins):
        lo, hi = bin_edges[b], bin_edges[b + 1]
        mask = (sizes >= lo) & (sizes < hi) if b < n_bins - 1 else (sizes >= lo)
        if not np.any(mask):
            continue

        # Disc kernel for this size bin
        r = int(np.ceil((lo + hi) / 2.0))
        if r < 1:
            r = 1
        y_k, x_k = np.ogrid[-r:r+1, -r:r+1]
        disc = ((x_k**2 + y_k**2) <= r**2).astype(np.float64)
        disc /= disc.sum()  # normalize

        # Accumulate point masses
        points = np.zeros((height, width), dtype=np.float64)
        ix = np.clip(cx[mask].astype(int), 0, width - 1)
        iy = np.clip(cy[mask].astype(int), 0, height - 1)
        np.add.at(points, (iy, ix), opacity[mask])

        # Convolve with disc kernel (much faster than per-crystal splatting)
        from scipy.signal import fftconvolve
        field += fftconvolve(points, disc, mode='same')

    return field


def apply_optical_transfer(field, sigma):
    """
    Disc (pillbox) blur — models optical transfer function more accurately
    than Gaussian. Real lenses have a sharper MTF cutoff (Airy disc).
    sigma controls the disc radius.
    """
    from scipy.signal import fftconvolve
    r = max(1, int(round(sigma)))
    y, x = np.ogrid[-r:r+1, -r:r+1]
    disc = ((x**2 + y**2) <= r**2).astype(np.float64)
    disc /= disc.sum()
    return fftconvolve(field, disc, mode='same')


def normalize_grain(field):
    """
    Normalize to zero-mean, unit-variance grain signal in [-1, 1] range.
    This makes the grain ready for INTENSITY scaling in the shader.
    """
    field = field - np.mean(field)
    std = np.std(field)
    if std > 0:
        field = field / (3.0 * std)  # 3-sigma → [-1, 1] for most values
    return np.clip(field, -1.0, 1.0)


def downscale(field, target_w, target_h):
    """
    Area-average downscale — physically correct optical integration.
    """
    from PIL import Image
    img = Image.fromarray(field.astype(np.float32))
    img = img.resize((target_w, target_h), Image.LANCZOS)
    return np.array(img, dtype=np.float64)


def generate_tile(preset_name, gen_size=2048, tile_size=512, seed=None):
    """
    Generate one grain tile: Newson synthesis at gen_size, downscale to tile_size.
    """
    preset = PRESETS[preset_name]
    rng = np.random.default_rng(seed)

    # Step 1: Poisson crystal field at high resolution
    field = generate_grain_field(
        gen_size, gen_size,
        preset["crystal_density"],
        preset["crystal_size_mean"],
        preset["crystal_size_std"],
        rng,
    )

    # Step 2: Optical transfer function (disc blur)
    if preset["blur_sigma"] > 0:
        field = apply_optical_transfer(field, preset["blur_sigma"])

    # Step 3: Downscale to tile size (this is additional optical integration)
    field = downscale(field, tile_size, tile_size)

    # Step 4: Normalize to [-1, 1] grain signal
    field = normalize_grain(field)

    return field


def build_atlas(preset_name, n_base_tiles=4, gen_size=2048, tile_size=512, seed=None):
    """
    Generate atlas: n_base_tiles computed, stored in a 2×N grid.
    Mirror/rotation variants are applied in the shader, not baked into the atlas.
    """
    rng = np.random.default_rng(seed)
    tiles = []

    for i in range(n_base_tiles):
        tile_seed = rng.integers(0, 2**32)
        print(f"  Generating tile {i+1}/{n_base_tiles} (seed={tile_seed})...")
        tile = generate_tile(preset_name, gen_size, tile_size, tile_seed)
        tiles.append(tile)

    # Arrange in 2×2 grid (for 4 tiles)
    cols = 2
    rows = (n_base_tiles + cols - 1) // cols
    atlas_w = cols * tile_size
    atlas_h = rows * tile_size
    atlas = np.zeros((atlas_h, atlas_w), dtype=np.float64)

    for i, tile in enumerate(tiles):
        r = i // cols
        c = i % cols
        y0 = r * tile_size
        x0 = c * tile_size
        atlas[y0:y0 + tile_size, x0:x0 + tile_size] = tile

    return atlas


def save_atlas(atlas, path):
    """
    Save atlas as 16-bit grayscale PNG.
    Map [-1, 1] → [0, 65535] for maximum precision.
    """
    from PIL import Image
    # Remap [-1, 1] → [0, 1]
    data = (atlas * 0.5 + 0.5)
    data = np.clip(data, 0.0, 1.0)
    # To 16-bit
    data_16 = (data * 65535).astype(np.uint16)
    img = Image.fromarray(data_16, mode='I;16')
    img.save(path)
    print(f"  Atlas saved: {path} ({img.size[0]}×{img.size[1]}, 16-bit)")


def main():
    parser = argparse.ArgumentParser(description="Generate grain tiles for cinegrain v2")
    parser.add_argument("preset", nargs="?", default="35mm-50D",
                        choices=list(PRESETS.keys()),
                        help="Film stock preset")
    parser.add_argument("--output", "-o", default=None,
                        help="Output path (default: tiles/<preset>.png)")
    parser.add_argument("--gen-size", type=int, default=2048,
                        help="Generation resolution per tile (default: 2048)")
    parser.add_argument("--tile-size", type=int, default=512,
                        help="Output tile size (default: 512)")
    parser.add_argument("--n-tiles", type=int, default=4,
                        help="Number of base tiles (default: 4)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for reproducibility")
    parser.add_argument("--all", action="store_true",
                        help="Generate all presets")
    args = parser.parse_args()

    output_dir = Path(__file__).parent.parent / "tiles"
    output_dir.mkdir(exist_ok=True)

    presets_to_generate = list(PRESETS.keys()) if args.all else [args.preset]

    for preset_name in presets_to_generate:
        print(f"\n[{preset_name}] {PRESETS[preset_name]['description']}")
        atlas = build_atlas(
            preset_name,
            n_base_tiles=args.n_tiles,
            gen_size=args.gen_size,
            tile_size=args.tile_size,
            seed=args.seed,
        )
        out_path = args.output or str(output_dir / f"{preset_name}.png")
        save_atlas(atlas, out_path)

    print("\nDone.")


if __name__ == "__main__":
    main()
