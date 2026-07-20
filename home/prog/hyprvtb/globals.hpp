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

// One saved window from a session snapshot (see vtbSaveSession /
// vtbRestoreSession in main.cpp): what to relaunch, where to place it, and
// which exclusive state to put it back into.
struct SSessionEntry {
    std::string cls;
    std::string cmd;                // shell command (incl. cd to cwd) to relaunch
    CBox        box;                // geometry to restore
    bool        maximized = false;
    bool        minimized = false;
    bool        rolled    = false;
    bool        consumed  = false;  // set once a relaunched window has claimed it
};

struct SGlobalState {
    std::vector<WP<CVtbDeco>> bars;

    // Windows queued for layout after a login relaunch; drained by onNewWindow
    // as each relaunched window maps. Empty except briefly at startup.
    std::vector<SSessionEntry> pendingRestore;

    // Event-bus listeners live in the state object — NOT function-local
    // statics — so PLUGIN_EXIT tearing down the state also deregisters
    // every callback. A listener that outlives the plugin state segfaults
    // the compositor on the next config reload (learned the hard way).
    std::vector<Hyprutils::Signal::CHyprSignalListener> listeners;

    // class -> last known floating geometry, persisted to
    // ~/.local/state/hyprvtb/geometry.tsv so apps reopen where/how you left
    // them (saved on window close, applied on window open). The scratchpad
    // terminal's entry only carries a meaningful width (the rest of its
    // geometry is enforced).
    std::map<std::string, CBox> savedGeometry;

    // The slide-in scratchpad terminal (kitty --class hyprvtb-scratch):
    // no titlebar, pinned to the left edge full-height, always at the
    // bottom of the z-order. Toggled by hl.plugin.hyprvtb.toggle_scratch().
    bool scratchVisible = false;

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
std::string vtbSessionPath();
void        vtbSaveSession();
void        vtbRestoreSession();
