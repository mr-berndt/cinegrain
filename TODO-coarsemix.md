# TODO: Enable COARSE_MIX inside the SOFTNESS path

## Problem

The shader has two code paths (see `hook()` in cinegrain.glsl):
- `SOFTNESS < 0.001` → calls `grain_sample()` → COARSE_MIX **works**
- `SOFTNESS >= 0.001` → calls `fine_grain()` → COARSE_MIX **is ignored**

All presets have SOFTNESS > 0, so they always take the second path.
**COARSE_MIX=0.70 in every preset currently does nothing.**

## What to do

In the `else` branch (SOFTNESS >= 0.001), replace all 5 `fine_grain()` calls
with `grain_sample()`. This makes COARSE_MIX active **together with** SOFTNESS.
The `if` branch (SOFTNESS == 0) stays unchanged.

Find the block that looks like this:

```glsl
// Current (COARSE_MIX broken):
grain  = fine_grain(pixel_pos,                   GRAIN_SIZE, seed) * 0.238;
grain += fine_grain(pixel_pos + vec2( r,  0.0), GRAIN_SIZE, seed) * 0.190;
grain += fine_grain(pixel_pos + vec2(-r,  0.0), GRAIN_SIZE, seed) * 0.190;
grain += fine_grain(pixel_pos + vec2(0.0,  r),  GRAIN_SIZE, seed) * 0.190;
grain += fine_grain(pixel_pos + vec2(0.0, -r),  GRAIN_SIZE, seed) * 0.190;

// Fixed (COARSE_MIX active):
grain  = grain_sample(pixel_pos,                   seed) * 0.238;
grain += grain_sample(pixel_pos + vec2( r,  0.0), seed) * 0.190;
grain += grain_sample(pixel_pos + vec2(-r,  0.0), seed) * 0.190;
grain += grain_sample(pixel_pos + vec2(0.0,  r),  seed) * 0.190;
grain += grain_sample(pixel_pos + vec2(0.0, -r),  seed) * 0.190;
```

## Validation

1. A/B against ProRes reference scans: `/mnt/serien_01/.video_in/Testvideos/Film_Grain_ALL_STANDARD/`
2. Compare on nelly (calibrated monitor) — amos projector is not accurate enough
3. Check if presets still match the scans or need recalibration
4. If COARSE_MIX works correctly, the preset values might converge (more linear relationship between formats, since the missing clustering was likely compensated by tweaking other params)

## Performance

- Current: 5 × fine_grain = 5 × 9 = **45 hash ops**
- Fixed: 5 × grain_sample = 5 × 29 = **145 hash ops**
- Original 9-tap (caused slowdown on amos): 261 ops
- 145 ops = 56% of the problematic original — likely OK on GTX 1650 Ti at 4K but must be tested on amos after

## Why this matters

COARSE_MIX and SOFTNESS model different physics:
- **COARSE_MIX**: silver halide crystal clustering in the emulsion (happens in the film)
- **SOFTNESS**: optical blur from projection magnification (happens during projection)

Both should be active simultaneously. The current code conflates them by accident.
