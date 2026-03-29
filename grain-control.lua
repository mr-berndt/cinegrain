-- grain-control.lua
-- Live grain parameter control via glsl-shader-opts (no recompile needed)
-- QWERTZ row layout (all with Alt):
-- ALT+q       = toggle
-- ALT+r/f     = INTENSITY +/-
-- ALT+t/g     = PEAK +/-
-- ALT+z/h     = ROLLOFF +/-
-- ALT+u/j     = GRAIN_SIZE +/-
-- ALT+i/k     = COARSE_MIX +/-
-- ALT+o/l     = BLUR +/-
-- ALT+p/ö     = CHROMA +/-

local mp = require 'mp'

local SHADER_NAME = "cinegrain"
local SHADER_PATH = "~/.config/mpv/shaders/cinegrain.glsl"

local params = {
    INTENSITY  = 0.040,
    PEAK       = 0.40,
    ROLLOFF    = 0.20,
    GRAIN_SIZE = 2.0,
    COARSE_MIX = 0.3,
    BLUR       = 0.6,
    CHROMA     = 0.3,
}

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
    -- Read-merge-write: preserve other shaders' params in the shared flat map
    local cur = mp.get_property_native("glsl-shader-opts", {})
    cur[SHADER_NAME .. "/INTENSITY"]  = string.format("%.4f", params.INTENSITY)
    cur[SHADER_NAME .. "/PEAK"]       = string.format("%.4f", params.PEAK)
    cur[SHADER_NAME .. "/ROLLOFF"]    = string.format("%.4f", params.ROLLOFF)
    cur[SHADER_NAME .. "/GRAIN_SIZE"] = string.format("%.4f", params.GRAIN_SIZE)
    cur[SHADER_NAME .. "/COARSE_MIX"] = string.format("%.4f", params.COARSE_MIX)
    cur[SHADER_NAME .. "/BLUR"]       = string.format("%.4f", params.BLUR)
    cur[SHADER_NAME .. "/CHROMA"]     = string.format("%.4f", params.CHROMA)
    local parts = {}
    for k, v in pairs(cur) do parts[#parts+1] = k .. "=" .. v end
    mp.set_property("glsl-shader-opts", table.concat(parts, ","))
end

local function adjust(param, delta, min_val, max_val)
    params[param] = math.max(min_val, math.min(max_val, params[param] + delta))
    push_opts()
    mp.osd_message(string.format(
        "Grain  INT %.3f  PEAK %.2f  ROLL %.2f  SIZE %.1f  COARSE %.2f  BLUR %.2f  CHROMA %.2f",
        params.INTENSITY, params.PEAK, params.ROLLOFF, params.GRAIN_SIZE, params.COARSE_MIX, params.BLUR, params.CHROMA), 5)
end

local grain_enabled = true

local function toggle()
    if grain_enabled then
        local shaders = mp.get_property_native("glsl-shaders", {})
        local filtered = {}
        for _, s in ipairs(shaders) do
            if not s:find("cinegrain", 1, true) then filtered[#filtered+1] = s end
        end
        mp.set_property_native("glsl-shaders", filtered)
        grain_enabled = false
        mp.osd_message("Grain: OFF", 2)
    else
        local shaders = mp.get_property_native("glsl-shaders", {})
        shaders[#shaders+1] = SHADER_PATH
        mp.set_property_native("glsl-shaders", shaders)
        grain_enabled = true
        push_opts()
        mp.osd_message(string.format(
            "Grain: ON  INT %.3f  PEAK %.2f  ROLL %.2f  SIZE %.1f  COARSE %.2f  BLUR %.2f  CHROMA %.2f",
            params.INTENSITY, params.PEAK, params.ROLLOFF, params.GRAIN_SIZE, params.COARSE_MIX, params.BLUR, params.CHROMA), 5)
    end
end

-- Restore saved intensity on file load
local VALUE_FILE = "/home/nicola/.config/mpv/mpv-grain-value"

mp.register_event("file-loaded", function()
    local f = io.open(VALUE_FILE, "r")
    if not f then return end
    local val = tonumber(f:read("*l"))
    f:close()
    if val and val >= 0.0 and val <= 2.0 then
        params.INTENSITY = val
        push_opts()
    end
end)

mp.add_key_binding("Alt+q", "grain-toggle", toggle)

local rep = {repeatable = true}

mp.add_key_binding("Alt+r", "grain-intensity-up",    function() adjust("INTENSITY",   steps.INTENSITY,  0.0,  2.0) end, rep)
mp.add_key_binding("Alt+f", "grain-intensity-down",  function() adjust("INTENSITY",  -steps.INTENSITY,  0.0,  2.0) end, rep)

mp.add_key_binding("Alt+t", "grain-peak-up",         function() adjust("PEAK",        steps.PEAK,       0.0,  1.0) end, rep)
mp.add_key_binding("Alt+g", "grain-peak-down",       function() adjust("PEAK",       -steps.PEAK,       0.0,  1.0) end, rep)

mp.add_key_binding("Alt+z", "grain-rolloff-up",      function() adjust("ROLLOFF",     steps.ROLLOFF,    0.01, 2.0) end, rep)
mp.add_key_binding("Alt+h", "grain-rolloff-down",    function() adjust("ROLLOFF",    -steps.ROLLOFF,    0.01, 2.0) end, rep)

mp.add_key_binding("Alt+u", "grain-size-up",         function() adjust("GRAIN_SIZE",  steps.GRAIN_SIZE, 0.5,  6.0) end, rep)
mp.add_key_binding("Alt+j", "grain-size-down",       function() adjust("GRAIN_SIZE", -steps.GRAIN_SIZE, 0.5,  6.0) end, rep)

mp.add_key_binding("Alt+i", "grain-coarse-up",       function() adjust("COARSE_MIX",  steps.COARSE_MIX, 0.0,  1.0) end, rep)
mp.add_key_binding("Alt+k", "grain-coarse-down",     function() adjust("COARSE_MIX", -steps.COARSE_MIX, 0.0,  1.0) end, rep)

mp.add_key_binding("Alt+o", "grain-blur-up",         function() adjust("BLUR",        steps.BLUR,       0.0,  1.0) end, rep)
mp.add_key_binding("Alt+l", "grain-blur-down",       function() adjust("BLUR",       -steps.BLUR,       0.0,  1.0) end, rep)

mp.add_key_binding("Alt+p", "grain-chroma-up",       function() adjust("CHROMA",      steps.CHROMA,     0.0,  1.0) end, rep)
mp.add_key_binding("Alt+ö", "grain-chroma-down",     function() adjust("CHROMA",     -steps.CHROMA,     0.0,  1.0) end, rep)
