#pragma once

#include <hyprland/src/plugins/PluginAPI.hpp>
#include <hyprland/src/render/Texture.hpp>
#include <hyprland/src/config/values/types/BoolValue.hpp>
#include <hyprland/src/config/values/types/IntValue.hpp>
#include <hyprland/src/config/values/types/StringValue.hpp>
#include <hyprland/src/config/values/types/ColorValue.hpp>

inline HANDLE PHANDLE = nullptr;

class CVtbDeco;

struct SGlobalState {
    std::vector<WP<CVtbDeco>> bars;

    struct {
        SP<Config::Values::CBoolValue>   enabled;
        SP<Config::Values::CIntValue>    barWidth;
        SP<Config::Values::CIntValue>    fontSize;
        SP<Config::Values::CIntValue>    maximizeGap;
        SP<Config::Values::CStringValue> font;
        SP<Config::Values::CColorValue>  bgColor;
        SP<Config::Values::CColorValue>  textColor;
        SP<Config::Values::CColorValue>  buttonBorderColor;
        SP<Config::Values::CColorValue>  accentColor;
    } config;
};

inline UP<SGlobalState> g_pGlobalState;
