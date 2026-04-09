#!/usr/bin/env python3
"""
Newson-style grain tile generator at physical crystal resolution.

Generates grain at the actual crystal scale of the film stock, then
downscales through the scanner's optical transfer function to output
tile resolution. Each pixel in the generation grid = one crystal position.

Physical model:
1. Poisson Boolean field at crystal resolution (binary: crystal present or not)
2. Log-normal crystal size variation via multi-radius disc union
3. Gaussian blur = scanner/projector PSF
4. Lanczos downscale to output tile size

Usage:
    python3 generate_grain_tiles_newson.py [preset] [--output path]
"""

import numpy as np
import argparse
from pathlib import Path
from scipy.ndimage import gaussian_filter
from scipy.signal import fftconvolve


# ── Physical parameters ────────────────────────────────────────────────────────
# crystal_um: crystal diameter in micrometers
# frame_width_mm: film gate width in mm
# coverage: fraction of area covered by developed crystals (determines density)
# scanner_psf_um: scanner point spread function width in micrometers
# scan_width_px: scan resolution (pixels across frame width)
# tile_output_px: output tile size in pixels

PRESETS = {
    "35mm-50D": {
        "crystal_um": 0.5,
        "crystal_std": 0.3,      # log-normal spread
        "frame_width_mm": 22.0,
        "coverage": 0.45,         # ~45% coverage at mid-grey
        "scanner_psf_um": 5.0,    # scanner optical blur
        "scan_width_px": 4096,
        "tile_output_px": 512,
        "description": "35mm slow daylight — very fine grain",
    },
    "35mm-250D": {
        "crystal_um": 0.8,
        "crystal_std": 0.3,
        "frame_width_mm": 22.0,
        "coverage": 0.45,
        "scanner_psf_um": 5.0,
        "scan_width_px": 4096,
        "tile_output_px": 512,
        "description": "35mm medium daylight — moderate grain",
    },
    "35mm-500T": {
        "crystal_um": 1.5,
        "crystal_std": 0.3,
        "frame_width_mm": 22.0,
        "coverage": 0.45,
        "scanner_psf_um": 5.0,
        "scan_width_px": 4096,
        "tile_output_px": 512,
        "description": "35mm fast tungsten — visible grain",
    },
    "16mm-50D": {
        "crystal_um": 0.5,
        "crystal_std": 0.3,
        "frame_width_mm": 12.0,
        "coverage": 0.45,
        "scanner_psf_um": 5.0,
        "scan_width_px": 4096,
        "tile_output_px": 512,
        "description": "16mm fine stock — coarser due to magnification",
    },
    "16mm-500T": {
        "crystal_um": 0.4,
        "crystal_std": 0.3,
        "frame_width_mm": 12.0,
        "coverage": 0.45,
        "scanner_psf_um": 5.0,
        "scan_width_px": 4096,
        "tile_output_px": 512,
        "description": "16mm fast stock — heavy grain",
    },
    "S8-50D": {
        "crystal_um": 0.5,
        "crystal_std": 0.3,
        "frame_width_mm": 5.8,
        "coverage": 0.45,
        "scanner_psf_um": 5.0,
        "scan_width_px": 4096,
        "tile_output_px": 512,
        "description": "Super 8 fine — extreme magnification",
    },
    "S8-500T": {
        "crystal_um": 1.5,
        "crystal_std": 0.3,
        "frame_width_mm": 5.8,
        "coverage": 0.45,
        "scanner_psf_um": 5.0,
        "scan_width_px": 4096,
        "tile_output_px": 512,
        "description": "Super 8 fast — maximum grain",
    },
}


def compute_gen_size(preset):
    """Compute generation resolution from physical parameters."""
    p = preset
    # How much film does one output tile cover?
    tile_film_mm = p["tile_output_px"] / p["scan_width_px"] * p["frame_width_mm"]
    tile_film_um = tile_film_mm * 1000.0
    # How many crystal-widths fit in that?
    gen_size = int(np.ceil(tile_film_um / p["crystal_um"]))
    return gen_size


def compute_scanner_psf_pixels(preset):
    """Scanner PSF in crystal-grid pixels."""
    p = preset
    return p["scanner_psf_um"] / p["crystal_um"]


def compute_density(preset):
    """Crystal density from target coverage. coverage = 1 - exp(-density * mean_area)."""
    p = preset
    # Mean crystal area in grid pixels (disc of radius derived from crystal_um)
    # At crystal resolution, 1 pixel = 1 crystal diameter, so radius = 0.5 pixels
    # With log-normal size variation, mean area = pi * E[r^2]
    # For simplicity: base crystal = 1 pixel diameter = 0.5 pixel radius
    mean_r = 0.5  # base crystal radius in grid pixels
    mean_area = np.pi * mean_r**2  # ≈ 0.785 pixels
    # coverage = 1 - exp(-density * mean_area)
    # density = -ln(1 - coverage) / mean_area
    density = -np.log(1.0 - p["coverage"]) / mean_area
    return density


def generate_crystal_field(gen_size, density, crystal_std, rng):
    """
    Generate Boolean crystal field at physical crystal resolution.

    Each pixel = one potential crystal position. Crystals are discs with
    log-normal size variation around 0.5px base radius.
    """
    # Jittered grid placement: uniform coverage with local randomness.
    # More realistic than Poisson — real emulsion coats uniformly, crystals
    # nucleate at roughly regular intervals with random offset.
    spacing = 1.0 / np.sqrt(density)  # grid spacing from target density
    nx = int(np.ceil(gen_size / spacing))
    ny = int(np.ceil(gen_size / spacing))
    gx, gy = np.meshgrid(
        np.arange(nx) * spacing + spacing / 2,
        np.arange(ny) * spacing + spacing / 2,
    )
    gx = gx.ravel()
    gy = gy.ravel()
    # Jitter: random offset up to ±spacing/2 (fills the cell uniformly)
    n_crystals = len(gx)
    cx = (gx + rng.uniform(-spacing/2, spacing/2, n_crystals)).astype(np.int32).clip(0, gen_size - 1)
    cy = (gy + rng.uniform(-spacing/2, spacing/2, n_crystals)).astype(np.int32).clip(0, gen_size - 1)

    # Log-normal crystal radii (in grid pixels, centered around 0.5)
    radii = rng.lognormal(np.log(0.5), crystal_std, n_crystals)
    radii = np.clip(radii, 0.3, 2.0)

    # Binary field with Boolean union via binned disc convolution + clamp
    field = np.zeros((gen_size, gen_size), dtype=np.float32)

    # Bin crystals by size for vectorized disc convolution
    r_unique = np.unique(np.round(radii).astype(int).clip(0, 3))
    for r_int in r_unique:
        mask = (np.round(radii).astype(int) == r_int)
        if not mask.any():
            continue

        if r_int == 0:
            # Point crystals: direct pixel placement
            np.add.at(field, (cy[mask], cx[mask]), 1.0)
        else:
            # Disc crystals
            points = np.zeros((gen_size, gen_size), dtype=np.float32)
            np.add.at(points, (cy[mask], cx[mask]), 1.0)
            y_k, x_k = np.ogrid[-r_int:r_int+1, -r_int:r_int+1]
            disc = ((x_k**2 + y_k**2) <= r_int**2).astype(np.float32)
            field += fftconvolve(points, disc, mode='same')

    # NO Boolean clamp — keep additive accumulation.
    # At high crystal density, CLT makes the coverage per pixel approximately
    # Gaussian-distributed → symmetric grain signal after normalization.
    # Boolean clamp creates asymmetry (dark holes) that real scans don't have.
    return field


def apply_scanner_psf(field, psf_sigma):
    """Gaussian blur modeling scanner/projector optical transfer function."""
    if psf_sigma > 0.5:
        return gaussian_filter(field, sigma=psf_sigma)
    return field


def downscale(field, target_size):
    """Lanczos downscale from crystal resolution to output tile."""
    from PIL import Image
    img = Image.fromarray(field)
    return np.array(img.resize((target_size, target_size), Image.LANCZOS), dtype=np.float64)


def normalize_grain(field):
    """Zero-mean, normalized to [-1, 1]. High-pass to remove DC variation."""
    field = field - gaussian_filter(field, sigma=max(16, field.shape[0] // 32))
    std = np.std(field)
    if std > 0:
        field = field / (3.0 * std)
    return np.clip(field, -1.0, 1.0)


def generate_tile(preset_name, seed=None):
    """Full pipeline: crystal field → scanner PSF → downscale → normalize."""
    p = PRESETS[preset_name]
    rng = np.random.default_rng(seed)

    gen_size = compute_gen_size(p)
    density = compute_density(p)
    psf_px = compute_scanner_psf_pixels(p)
    tile_size = p["tile_output_px"]

    print(f"    Gen size: {gen_size}×{gen_size} ({gen_size**2/1e6:.1f}M pixels)")
    print(f"    Crystal density: {density:.4f}/px² ({int(density * gen_size**2)} crystals)")
    print(f"    Scanner PSF: {psf_px:.1f} crystal-pixels (σ={psf_px:.1f})")
    print(f"    Downscale: {gen_size} → {tile_size} ({gen_size/tile_size:.1f}×)")

    # Step 1: Crystal field at physical resolution
    field = generate_crystal_field(gen_size, density, p["crystal_std"], rng)

    # Step 2: Scanner PSF
    field = apply_scanner_psf(field, psf_px)

    # Step 3: Downscale to output tile
    field = downscale(field, tile_size)

    # Step 4: Normalize
    field = normalize_grain(field)

    return field


def build_atlas(preset_name, n_tiles=4, seed=None):
    rng = np.random.default_rng(seed)
    p = PRESETS[preset_name]
    tile_size = p["tile_output_px"]
    tiles = []

    for i in range(n_tiles):
        s = rng.integers(0, 2**32)
        print(f"  Tile {i+1}/{n_tiles} (seed={s}):")
        tiles.append(generate_tile(preset_name, s))

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
    print(f"  Saved: {path} ({data_16.shape[1]}×{data_16.shape[0]}, 16-bit)")


def main():
    parser = argparse.ArgumentParser(description="Newson grain tile generator (physical resolution)")
    parser.add_argument("preset", nargs="?", default="16mm-500T",
                        choices=list(PRESETS.keys()))
    parser.add_argument("--output", "-o", default=None)
    parser.add_argument("--n-tiles", type=int, default=1)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    output_dir = Path(__file__).parent.parent / "tiles"
    output_dir.mkdir(exist_ok=True)

    presets = list(PRESETS.keys()) if args.all else [args.preset]

    for name in presets:
        print(f"\n[{name}] {PRESETS[name]['description']}")
        atlas = build_atlas(name, n_tiles=args.n_tiles, seed=args.seed)
        path = args.output or str(output_dir / f"{name}-newson.png")
        save_atlas(atlas, path)

    print("\nDone.")


if __name__ == "__main__":
    main()
