// Film grain shader - luminance-weighted, spatially correlated, multi-scale
// Base PRNG: haasn's permutation hash

//!PARAM INTENSITY
//!DESC Overall grain strength
//!TYPE float
//!MINIMUM 0.0
//!MAXIMUM 2.0
0.09

//!PARAM PEAK
//!DESC Luminance where grain is strongest (0.0-1.0)
//!TYPE float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.40

//!PARAM ROLLOFF
//!DESC Bell curve width (larger = wider/flatter)
//!TYPE float
//!MINIMUM 0.01
//!MAXIMUM 2.0
0.40

//!PARAM GRAIN_SIZE
//!DESC Primary grain size in pixels (1.0 = 1px, 3.0 = 3px)
//!TYPE float
//!MINIMUM 0.5
//!MAXIMUM 6.0
0.75

//!PARAM COARSE_MIX
//!DESC Amount of coarse grain layer (coarse = GRAIN_SIZE x2.5)
//!TYPE float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.4

//!PARAM BLUR
//!DESC Grain softness (0 = crisp, 1 = soft)
//!TYPE float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.7

//!PARAM CHROMA
//!DESC Colour grain strength (R/B shift, film-style)
//!TYPE float
//!MINIMUM 0.0
//!MAXIMUM 1.0
0.2

//!HOOK OUTPUT
//!BIND HOOKED
//!DESC cinegrain

float permute(float x)
{
    x = (34.0 * x + 1.0) * x;
    return fract(x * (1.0 / 289.0)) * 289.0;
}

// Hash a 2D grid cell + frame seed to [0,1]
// mod 289 keeps inputs in the range permute() was designed for
float grid_hash(vec2 cell, float seed)
{
    vec2 c = mod(cell, 289.0);
    float s = permute(permute(c.x + mod(seed * 73.1, 289.0)) + c.y);
    return fract(s * (1.0 / 41.0));
}

// Value noise with quintic smoothstep — returns [-1, 1]
float value_noise(vec2 pixel_pos, float size, float seed)
{
    vec2 p = pixel_pos / size;
    vec2 fl = floor(p);
    vec2 fr = fract(p);
    // Quintic smoothstep (C2 continuous, softer grid edges than cubic)
    fr = fr * fr * fr * (fr * (fr * 6.0 - 15.0) + 10.0);

    float n00 = grid_hash(fl + vec2(0.0, 0.0), seed);
    float n10 = grid_hash(fl + vec2(1.0, 0.0), seed);
    float n01 = grid_hash(fl + vec2(0.0, 1.0), seed);
    float n11 = grid_hash(fl + vec2(1.0, 1.0), seed);

    return mix(mix(n00, n10, fr.x), mix(n01, n11, fr.x), fr.y) * 2.0 - 1.0;
}

// Blurred noise: 5-tap cross pattern weighted average
float blurred_noise(vec2 pixel_pos, float size, float seed)
{
    float r = BLUR * size * 0.6;
    float n0 = value_noise(pixel_pos,                    size, seed) * 2.0;
    float n1 = value_noise(pixel_pos + vec2( r, 0.0),   size, seed);
    float n2 = value_noise(pixel_pos + vec2(-r, 0.0),   size, seed);
    float n3 = value_noise(pixel_pos + vec2(0.0,  r),   size, seed);
    float n4 = value_noise(pixel_pos + vec2(0.0, -r),   size, seed);
    return (n0 + n1 + n2 + n3 + n4) / 6.0;
}

// Bell curve: peaks at PEAK, fades toward highlights
float luma_weight(float luma)
{
    float d = (luma - PEAK) / ROLLOFF;
    return exp(-0.5 * d * d);
}

vec4 hook()
{
    vec2 pixel_pos = HOOKED_pos * HOOKED_size;
    float seed = random;

    float fine   = blurred_noise(pixel_pos, GRAIN_SIZE,       seed);
    float coarse = blurred_noise(pixel_pos, GRAIN_SIZE * 2.5, seed + 17.3);
    float grain  = mix(fine, coarse, COARSE_MIX);

    vec4 color = HOOKED_tex(HOOKED_pos);
    float luma = dot(color.rgb, vec3(0.2126, 0.7152, 0.0722));
    float weight = luma_weight(luma);

    color.rgb += vec3(INTENSITY * weight * grain);

    // Colour grain: correlated spatial structure, independent R/B shifts
    if (CHROMA > 0.0) {
        float size_c = GRAIN_SIZE * 1.8;  // chroma grain is coarser than luma
        float cr = blurred_noise(pixel_pos, size_c, seed + 31.7);
        float cb = blurred_noise(pixel_pos, size_c, seed + 57.2);
        float cw = INTENSITY * CHROMA * weight;
        color.r += cw * cr;
        color.b += cw * cb;
    }

    // Clamp to prevent negative values (dark channel clipping → black spots)
    color.rgb = max(color.rgb, vec3(0.0));

    return color;
}
