#pragma once

#include <hyprland/src/plugins/PluginAPI.hpp>
#include <hyprland/src/render/Texture.hpp>
#include <hyprland/src/config/values/types/BoolValue.hpp>
#include <hyprland/src/config/values/types/IntValue.hpp>
#include <hyprland/src/config/values/types/StringValue.hpp>
#include <hyprland/src/config/values/types/ColorValue.hpp>

#include <map>
#include <string>

#include <hyprland/src/helpers/signal/Signal.hpp>

inline HANDLE PHANDLE = nullptr;

class CVtbDeco;

struct SGlobalState {
    std::vector<WP<CVtbDeco>> bars;

    // Event-bus listeners live in the state object — NOT function-local
    // statics — so PLUGIN_EXIT tearing down the state also deregisters
    // every callback. A listener that outlives the plugin state segfaults
    // the compositor on the next config reload (learned the hard way).
    std::vector<Hyprutils::Signal::CHyprSignalListener> listeners;

    // class -> last known floating geometry, persisted to
    // ~/.local/state/hyprvtb/geometry.tsv so apps reopen where/how you left
    // them (saved on window close, applied on window open).
    std::map<std::string, CBox> savedGeometry;

    struct {
        SP<Config::Values::CBoolValue>   enabled;
        SP<Config::Values::CIntValue>    barWidth;
        SP<Config::Values::CIntValue>    fontSize;
        SP<Config::Values::CIntValue>    maximizeGap;
        SP<Config::Values::CStringValue> font;
        SP<Config::Values::CColorValue>  bgColor;
        SP<Config::Values::CColorValue>  bgAltColor;
        SP<Config::Values::CColorValue>  textColor;
        SP<Config::Values::CColorValue>  buttonBorderColor;
        SP<Config::Values::CColorValue>  accentColor;
        SP<Config::Values::CColorValue>  critColor;
        SP<Config::Values::CColorValue>  inactiveColor;
    } config;
};

inline UP<SGlobalState> g_pGlobalState;

std::string vtbStatePath();
void        vtbLoadGeometry();
void        vtbSaveGeometry();
