-- grain-control.lua
-- Live grain parameter control via glsl-shader-opts (no recompile needed)
-- ALT+q       = toggle
-- ALT+,/.     = preset cycle prev/next
-- ALT+r/f     = INTENSITY +/-
-- ALT+t/g     = PEAK +/-
-- ALT+z/h     = ROLLOFF +/-
-- ALT+u/j     = GRAIN_SIZE +/-
-- ALT+i/k     = COARSE_MIX +/-
-- ALT+o/l     = BLUR +/-
-- ALT+p/ö     = CHROMA +/-

local mp = require 'mp'

local SHADER_PATH = "~/.config/mpv/shaders/cinegrain.glsl"

-- ─── Presets ──────────────────────────────────────────────────────────────────
-- Add or edit presets here. Order = cycle order.
local presets = {
    { name = "Aliens 4K",      INTENSITY=0.040, PEAK=0.40, ROLLOFF=0.20, GRAIN_SIZE=2.0,  COARSE_MIX=0.30, BLUR=0.40, CHROMA=0.30 },
    { name = "35mm Normal",    INTENSITY=0.09,  PEAK=0.40, ROLLOFF=0.40, GRAIN_SIZE=0.75, COARSE_MIX=0.40, BLUR=0.70, CHROMA=0.20 },
    { name = "35mm High",      INTENSITY=0.075, PEAK=0.40, ROLLOFF=0.40, GRAIN_SIZE=1.25, COARSE_MIX=0.60, BLUR=0.10, CHROMA=0.20 },
    { name = "35mm G3",        INTENSITY=0.125, PEAK=0.35, ROLLOFF=0.40, GRAIN_SIZE=1.0,  COARSE_MIX=0.00, BLUR=0.00, CHROMA=0.30 },
    { name = "35mm Pushed",    INTENSITY=0.190, PEAK=0.35, ROLLOFF=0.47, GRAIN_SIZE=0.75, COARSE_MIX=0.40, BLUR=0.00, CHROMA=0.20 },
    { name = "Kodak Gold 200", INTENSITY=0.500, PEAK=0.29, ROLLOFF=0.45, GRAIN_SIZE=0.5,  COARSE_MIX=0.20, BLUR=0.00, CHROMA=0.30 },
    { name = "Off",            INTENSITY=0.00,  PEAK=0.40, ROLLOFF=0.40, GRAIN_SIZE=0.75, COARSE_MIX=0.40, BLUR=0.70, CHROMA=0.00 },
}
-- ──────────────────────────────────────────────────────────────────────────────

local preset_index = 1  -- start on first preset
local current_preset_name = nil  -- nil = custom (manually tweaked)

local params = {}
for k, v in pairs(presets[1]) do
    if k ~= "name" then params[k] = v end
end

local steps = {
    INTENSITY  = 0.005,
    PEAK       = 0.01,
    ROLLOFF    = 0.01,
    GRAIN_SIZE = 0.25,
    COARSE_MIX = 0.05,
    BLUR       = 0.05,
    CHROMA     = 0.05,
}

local function push_opts()
    mp.set_property("glsl-shader-opts", string.format(
        "INTENSITY=%.4f,PEAK=%.4f,ROLLOFF=%.4f,GRAIN_SIZE=%.4f,COARSE_MIX=%.4f,BLUR=%.4f,CHROMA=%.4f",
        params.INTENSITY, params.PEAK, params.ROLLOFF, params.GRAIN_SIZE,
        params.COARSE_MIX, params.BLUR, params.CHROMA))
end

local grain_enabled = true

local overlay = mp.create_osd_overlay("ass-events")

local function osd_update()
    local preset_tag = current_preset_name
        and string.format(" [%s]", current_preset_name)
        or  " [custom]"
    if not grain_enabled then
        overlay.data = "{\\an7\\fs16\\c&H00FFFF&}Grain: OFF"
    else
        overlay.data = string.format(
            "{\\an7\\fs16\\c&H00FFFF&}Grain%s  INT %.3f  PEAK %.2f  ROLL %.2f  SIZE %.2f  COARSE %.2f  BLUR %.2f  CHROMA %.2f",
            preset_tag,
            params.INTENSITY, params.PEAK, params.ROLLOFF, params.GRAIN_SIZE,
            params.COARSE_MIX, params.BLUR, params.CHROMA)
    end
    overlay:update()
end

local function apply_preset(idx)
    preset_index = idx
    local p = presets[idx]
    current_preset_name = p.name
    for k, v in pairs(p) do
        if k ~= "name" then params[k] = v end
    end
    push_opts()
    osd_update()
end

local function cycle_preset(dir)
    local n = #presets
    preset_index = ((preset_index - 1 + dir) % n) + 1
    apply_preset(preset_index)
end

local function adjust(param, delta, min_val, max_val)
    params[param] = math.max(min_val, math.min(max_val, params[param] + delta))
    current_preset_name = nil  -- mark as custom
    push_opts()
    osd_update()
end

local function toggle()
    if grain_enabled then
        local shaders = mp.get_property_native("glsl-shaders", {})
        local filtered = {}
        for _, s in ipairs(shaders) do
            if not s:find("cinegrain", 1, true) then filtered[#filtered+1] = s end
        end
        mp.set_property_native("glsl-shaders", filtered)
        grain_enabled = false
    else
        local shaders = mp.get_property_native("glsl-shaders", {})
        shaders[#shaders+1] = SHADER_PATH
        mp.set_property_native("glsl-shaders", shaders)
        grain_enabled = true
        push_opts()
    end
    osd_update()
end

-- Restore saved intensity on file load
local VALUE_FILE = "/home/nicola/.config/mpv/mpv-grain-value"

mp.register_event("file-loaded", function()
    local f = io.open(VALUE_FILE, "r")
    if f then
        local val = tonumber(f:read("*l"))
        f:close()
        if val and val >= 0.0 and val <= 2.0 then
            params.INTENSITY = val
            current_preset_name = nil
            push_opts()
        end
    end
    osd_update()
end)

-- Apply first preset on startup
apply_preset(1)

local rep = {repeatable = true}

mp.add_key_binding("Alt+q",     "grain-toggle",       toggle)
mp.add_key_binding("Alt+,",     "grain-preset-prev",  function() cycle_preset(-1) end)
mp.add_key_binding("Alt+.",     "grain-preset-next",  function() cycle_preset( 1) end)

mp.add_key_binding("Alt+r", "grain-intensity-up",   function() adjust("INTENSITY",  steps.INTENSITY,  0.0,  2.0)  end, rep)
mp.add_key_binding("Alt+f", "grain-intensity-down", function() adjust("INTENSITY", -steps.INTENSITY,  0.0,  2.0)  end, rep)

mp.add_key_binding("Alt+t", "grain-peak-up",        function() adjust("PEAK",       steps.PEAK,       0.0,  1.0)  end, rep)
mp.add_key_binding("Alt+g", "grain-peak-down",      function() adjust("PEAK",      -steps.PEAK,       0.0,  1.0)  end, rep)

mp.add_key_binding("Alt+z", "grain-rolloff-up",     function() adjust("ROLLOFF",    steps.ROLLOFF,    0.01, 2.0)  end, rep)
mp.add_key_binding("Alt+h", "grain-rolloff-down",   function() adjust("ROLLOFF",   -steps.ROLLOFF,    0.01, 2.0)  end, rep)

mp.add_key_binding("Alt+u", "grain-size-up",        function() adjust("GRAIN_SIZE", steps.GRAIN_SIZE, 0.5,  6.0)  end, rep)
mp.add_key_binding("Alt+j", "grain-size-down",      function() adjust("GRAIN_SIZE",-steps.GRAIN_SIZE, 0.5,  6.0)  end, rep)

mp.add_key_binding("Alt+i", "grain-coarse-up",      function() adjust("COARSE_MIX", steps.COARSE_MIX, 0.0,  1.0)  end, rep)
mp.add_key_binding("Alt+k", "grain-coarse-down",    function() adjust("COARSE_MIX",-steps.COARSE_MIX, 0.0,  1.0)  end, rep)

mp.add_key_binding("Alt+o", "grain-blur-up",        function() adjust("BLUR",       steps.BLUR,       0.0,  1.0)  end, rep)
mp.add_key_binding("Alt+l", "grain-blur-down",      function() adjust("BLUR",      -steps.BLUR,       0.0,  1.0)  end, rep)

mp.add_key_binding("Alt+p", "grain-chroma-up",      function() adjust("CHROMA",     steps.CHROMA,     0.0,  1.0)  end, rep)
mp.add_key_binding("Alt+ö", "grain-chroma-down",    function() adjust("CHROMA",    -steps.CHROMA,     0.0,  1.0)  end, rep)
