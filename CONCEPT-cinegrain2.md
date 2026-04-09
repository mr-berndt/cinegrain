# cinegrain v2 — Tile-Pool Architecture

## Problem

cinegrain v1 generates grain per-pixel in real-time: 145 hash ops per pixel at
4K = ~1.2 billion operations per frame. This is the performance bottleneck,
especially on mid-range GPUs (GTX 1650 Ti). Goal: run on integrated GPUs.

## Core Idea

Physically accurate grain tiles (Newson model), generated at startup and pooled.
Distributed randomly across the image each frame. After pool is filled, zero
generation cost — only texture lookups remain.

## Architecture

### Phase 1: Tile Generation (Startup, ~5 frames)

Newson-style physical grain synthesis:
- Poisson point process for crystal positions
- Log-normal crystal size distribution
- Optical transfer function (Gaussian blur = scanner/projection optics)

Process per tile:
1. Generate at high resolution (e.g. 2048×2048) using Newson model
2. Downscale to 512×512 — the downscale IS the optical transfer function
3. Store in atlas

From each computed tile, derive 8 variants for free:
- 1× original + 1× horizontal mirror = 2
- Each × 4 rotations (0°, 90°, 180°, 270°) = 8
- Grain is isotropic — flipping/rotating changes pattern, not character

Pool build-up (1 tile computed per frame, smooth load):
- Frame 1: 1 tile computed → 8 variants available (some repetition, invisible)
- Frame 2: 2 tiles → 16 variants (tiling already invisible)
- Frame 3: 3 tiles → 24 variants (overkill)
- Frame 4+: 4 tiles → 32 variants → **generation stops**

Total generation cost: 4 × 2048 × 2048 = 16M pixels across 4 frames.
That's 4M pixels per frame during startup — half of v1's steady-state cost.

### Phase 2: Steady State (rest of the film)

**Zero generation. Only distribution + weighting.**

Per output pixel:
1. Determine 32×32 (or 64×64) block from pixel position
2. Hash block coords + frame seed → tile index (0–3) + variant (0–7) + offset
3. Single texture lookup from atlas
4. Single LUT lookup for luminance weight
5. Multiply: `color += grain × weight × INTENSITY`

Combinations per block: 4 tiles × 8 variants × thousands of offsets = no visible tiling.

### Luminance Weighting via LUT

Pre-computed 1D LUT (256 entries), replaces per-pixel `pow()` + `exp()` + `smoothstep()`:
- Generated once from the analytical `luma_weight` function at startup
- Regenerated on PEAK/ROLLOFF change (256 values, microseconds)
- Stored as 1D texture, single lookup per pixel
- Allows arbitrary curves (hand-drawn, measured from real film, etc.)

### Chroma Grain

- Derive from luma tile with offset + scale (cheapest)
- Or: separate smaller tiles (128×128), same pool mechanism

### Preset Changes

When user switches preset (e.g. 35mm → 16mm):
- Pool NOT invalidated instantly — old tiles stay
- New tiles replace old ones gradually (1 per frame)
- Full transition in 4 frames = 167ms at 24fps
- Viewer sees smooth blend of old/new grain — unnoticeable
- Frame time stays constant, no spike

## Tile Atlas Layout

```
+-------+-------+-------+-------+
| T0    | T0-M  | T0-90 | T0-M90|   (T0 = tile 0, M = mirrored,
+-------+-------+-------+-------+    90/180/270 = rotated)
| T0-180|T0-M180| T0-270|T0-M270|
+-------+-------+-------+-------+
| T1    | T1-M  | T1-90 | T1-M90|   (T1–T3 same pattern)
+-------+-------+-------+-------+
| T1-180|T1-M180| T1-270|T1-M270|
+-------+-------+-------+-------+
```

Atlas size: 8×4 = 32 tiles of 512×512 in a 4096×2048 texture
- COMPONENTS 1 → ~8MB VRAM (or 2048×2048 with 256×256 tiles → ~4MB)
- Variant selection = UV offset, no duplication needed if done in shader math

Alternative: store only the 4 base tiles (2×2 atlas = 1024×1024, ~1MB).
Apply mirror/rotation via UV transform in shader — zero extra VRAM.

## Performance Estimate

| | v1 (current) | v2 startup | v2 steady state |
|---|---|---|---|
| Generation | 8.3M px × 29 ops/frame | 4M px × ~50 ops/frame | **0** |
| Per-pixel apply | 29 hash ops | 3 ops | **3 ops** |
| Total ops/frame | ~240M | ~200M (generation) + 25M (apply) | **25M** |
| Speedup vs v1 | baseline | ~1× | **~10×** |
| VRAM | 62MB (2× texture) | ~1MB (atlas) | ~1MB |

3 ops per pixel at 4K = 25M ops/frame = **trivial** for any GPU including integrated.

## Shader Structure

### Pass 1: Pool Build (only during startup / preset change)

Could be a shader pass or Lua/Python pre-computation:
- If shader: fixed-size `//!SAVE` atlas, conditional regeneration via frame counter
- If Lua: write PNG to /tmp, load via `//!TEXTURE` — more flexible, Newson model
  easier to implement in Lua/Python than GLSL
- If `//!SAVE` doesn't persist across frames: Lua approach required anyway

### Pass 2: Apply Grain (every frame)

```glsl
//!HOOK OUTPUT
//!BIND HOOKED
//!BIND GRAIN_ATLAS   // pre-loaded texture
//!BIND WEIGHT_LUT    // 1D luminance weight LUT
//!DESC cinegrain2

vec4 hook() {
    vec4 color = HOOKED_tex(HOOKED_pos);
    float luma = dot(color.rgb, vec3(0.2126, 0.7152, 0.0722));

    // Block-based tile selection
    ivec2 block = ivec2(gl_FragCoord.xy) / BLOCK_SIZE;
    uint h = hash(block, frame_seed);
    int tile_idx = h & 3;        // which base tile (0–3)
    int variant = (h >> 2) & 7;  // mirror+rotation (0–7)
    vec2 offset = fract(vec2(h >> 5, h >> 13) / 256.0);

    // UV into atlas with variant transform
    vec2 uv = apply_variant(fract(pixel_in_block / tile_size + offset), variant);
    vec2 atlas_uv = tile_to_atlas(uv, tile_idx, variant);

    float grain = texture(GRAIN_ATLAS, atlas_uv).r;
    float weight = texture(WEIGHT_LUT, vec2(luma, 0.5)).r;

    color.rgb += vec3(INTENSITY * weight * grain);
    return color;
}
```

## Open Questions

1. **Tile generation in GLSL vs Lua**: Newson model has square roots, exponentials,
   Poisson sampling — all doable in GLSL but easier to debug in Lua/Python.
   Lua runs on CPU, writes texture, shader just reads it.

2. **//!TEXTURE loading**: Can mpv reload a `//!TEXTURE` at runtime? If yes,
   Lua generates tiles → writes PNG → triggers shader reload. If not, need
   `//!SAVE` persistence or a different approach.

3. **Block edge artifacts**: Adjacent blocks show different tiles. At 32×32 block
   size the seam is at sub-grain-size scale — likely invisible. If visible:
   blend 2–4 pixel border between blocks (slight cost increase).

4. **Temporal stability**: Same block gets same tile index per frame (hash of
   block coords). Only frame seed changes the offset → grain drifts naturally
   like real film in a projector gate. Tile index changes when pool rotates.

5. **SOFTNESS parameter**: Becomes tile generation parameter (Newson Gaussian
   blur radius) rather than runtime parameter. Different from v1 where it was
   live-adjustable — but physically more correct: softness is an optical
   property of the format, not a viewing preference.

## References

- Norkin/Birkbeck 2018: "Film Grain Synthesis for AV1 Video Codec"
  (64×64 template, AR filter, block-based distribution, piecewise-linear LUT)
- Newson et al. 2017: "Stochastic Movie Grain Synthesis" (IPOL)
  (Monte Carlo grain simulation, physically accurate, reference implementation)
- Newson et al. 2014: "A Stochastic Film Grain Model for Resolution-Independent
  Rendering" (Computer Graphics Forum)
  (Physical crystal model, log-normal size distribution, optical transfer)
