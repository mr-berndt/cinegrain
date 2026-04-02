# TODO: Enable COARSE_MIX inside the SOFTNESS path

## INSTRUCTION: MAKE THIS CHANGE NOW

This file is a work order. The change described below should be applied
to cinegrain.glsl on this machine (nelly). The purpose is visual A/B
comparison against reference scans on nelly's calibrated monitor.

Performance is NOT a concern on nelly — nelly has a fast GPU. The
performance note below is about amos (GTX 1650 Ti), which will be
tested separately later.

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

Replace this:

```glsl
grain  = fine_grain(pixel_pos,                   GRAIN_SIZE, seed) * 0.238;
grain += fine_grain(pixel_pos + vec2( r,  0.0), GRAIN_SIZE, seed) * 0.190;
grain += fine_grain(pixel_pos + vec2(-r,  0.0), GRAIN_SIZE, seed) * 0.190;
grain += fine_grain(pixel_pos + vec2(0.0,  r),  GRAIN_SIZE, seed) * 0.190;
grain += fine_grain(pixel_pos + vec2(0.0, -r),  GRAIN_SIZE, seed) * 0.190;
```

With this:

```glsl
grain  = grain_sample(pixel_pos,                   seed) * 0.238;
grain += grain_sample(pixel_pos + vec2( r,  0.0), seed) * 0.190;
grain += grain_sample(pixel_pos + vec2(-r,  0.0), seed) * 0.190;
grain += grain_sample(pixel_pos + vec2(0.0,  r),  seed) * 0.190;
grain += grain_sample(pixel_pos + vec2(0.0, -r),  seed) * 0.190;
```

Note: `grain_sample()` has a different signature than `fine_grain()` —
it takes `(pos, seed)` not `(pos, GRAIN_SIZE, seed)`. The GRAIN_SIZE
is read from the uniform inside `grain_sample()`.

## After the change

1. A/B against ProRes reference scans: `/mnt/serien_01/.video_in/Testvideos/Film_Grain_ALL_STANDARD/`
2. Check if grain character improves (more realistic clustering)
3. Check if presets need recalibration

## Performance note (for amos later, NOT relevant for nelly)

- Current: 5 × fine_grain = 45 hash ops
- After fix: 5 × grain_sample = 145 hash ops
- This was borderline on amos (GTX 1650 Ti at 4K) — will be tested there separately
