#define WLR_USE_UNSTABLE

#include <hyprland/src/Compositor.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include <hyprland/src/event/EventBus.hpp>
#include <hyprland/src/managers/KeybindManager.hpp>
#include <hyprland/src/desktop/state/FocusState.hpp>
#include <hyprland/src/config/ConfigManager.hpp>
#include <hyprland/src/config/shared/actions/ConfigActions.hpp>

extern "C" {
#include <lua.h>
#include <lauxlib.h>
}

#include <algorithm>
#include <cstdlib>
#include <filesystem>
#include <format>
#include <fstream>
#include <sstream>

#include "vtbDeco.hpp"
#include "globals.hpp"

// Do NOT change this function.
APICALL EXPORT std::string PLUGIN_API_VERSION() {
    return HYPRLAND_API_VERSION;
}

// ---- per-class geometry memory --------------------------------------------

std::string vtbStatePath() {
    const char* home = std::getenv("HOME");
    return std::string(home ? home : "") + "/.local/state/hyprvtb/geometry.tsv";
}

void vtbLoadGeometry() {
    std::ifstream f(vtbStatePath());
    if (!f.good())
        return;

    std::string line;
    while (std::getline(f, line)) {
        std::istringstream ss(line);
        std::string        cls;
        double             x, y, w, h;
        if (!std::getline(ss, cls, '\t'))
            continue;
        if (!(ss >> x >> y >> w >> h))
            continue;
        g_pGlobalState->savedGeometry[cls] = CBox{x, y, w, h};
    }
}

void vtbSaveGeometry() {
    const auto PATH = vtbStatePath();
    std::filesystem::create_directories(std::filesystem::path(PATH).parent_path());
    std::ofstream f(PATH, std::ios::trunc);
    for (const auto& [cls, box] : g_pGlobalState->savedGeometry)
        f << cls << '\t' << (int)box.x << ' ' << (int)box.y << ' ' << (int)box.w << ' ' << (int)box.h << '\n';
}

// ---- window lifecycle ------------------------------------------------------

static void onNewWindow(PHLWINDOW window) {
    if (window->m_X11DoesntWantBorders)
        return;

    if (std::ranges::any_of(window->m_windowDecorations, [](const auto& d) { return d->getDisplayName() == "Hyprvtb"; }))
        return;

    auto bar = makeUnique<CVtbDeco>(window);
    g_pGlobalState->bars.emplace_back(bar);
    bar->m_self = bar;
    HyprlandAPI::addWindowDecoration(PHANDLE, window, std::move(bar));

    // reopen where/how this app was last closed
    if (window->m_isFloating) {
        const auto IT = g_pGlobalState->savedGeometry.find(window->m_class);
        if (IT != g_pGlobalState->savedGeometry.end()) {
            Config::Actions::resize(IT->second.size(), false, window);
            Config::Actions::move(IT->second.pos(), false, window);
        }
    }
}

static void onCloseWindow(PHLWINDOW window) {
    if (!window || !window->m_isFloating || window->m_class.empty())
        return;

    for (auto& b : g_pGlobalState->bars) {
        if (b && b->getOwner() == window) {
            const auto BOX = b->memorableGeometry();
            if (BOX.w > 50 && BOX.h > 50) {
                g_pGlobalState->savedGeometry[window->m_class] = BOX;
                vtbSaveGeometry();
            }
            break;
        }
    }
}

static void onWindowFocus(PHLWINDOW window) {
    if (!window)
        return;

    for (auto& b : g_pGlobalState->bars) {
        if (b && b->getOwner() == window) {
            b->onFocusGained();
            break;
        }
    }
}

// Deco of the currently focused window, or nullptr.
static CVtbDeco* activeDeco() {
    if (!g_pGlobalState)
        return nullptr;
    const auto W = Desktop::focusState()->window();
    if (!W)
        return nullptr;
    for (auto& b : g_pGlobalState->bars) {
        if (b && b->getOwner() == W)
            return b.get();
    }
    return nullptr;
}

// lua: hyprvtb.minimize_active() — used by the panel taskbar (clicking the
// active program's icon minimizes it).
static int luaMinimizeActive(lua_State* L) {
    if (auto d = activeDeco())
        d->minimizeWindow();
    return 0;
}

// lua: hyprvtb.toggle_maximize_active()
static int luaToggleMaximizeActive(lua_State* L) {
    if (auto d = activeDeco())
        d->toggleMaximize();
    return 0;
}

static void onConfigReloaded() {
    for (auto& b : g_pGlobalState->bars) {
        if (!b)
            continue;
        b->onConfigReloaded();
    }
}

APICALL EXPORT PLUGIN_DESCRIPTION_INFO PLUGIN_INIT(HANDLE handle) {
    PHANDLE = handle;

    const std::string HASH        = __hyprland_api_get_hash();
    const std::string CLIENT_HASH = __hyprland_api_get_client_hash();

    if (HASH != CLIENT_HASH) {
        HyprlandAPI::addNotification(PHANDLE, "[hyprvtb] Failure in initialization: Version mismatch (headers ver is not equal to running hyprland ver)",
                                     CHyprColor{1.0, 0.2, 0.2, 1.0}, 5000);
        throw std::runtime_error("[hyprvtb] Version mismatch");
    }

    g_pGlobalState = makeUnique<SGlobalState>();
    vtbLoadGeometry();

    // Listeners are stored in g_pGlobalState (destroyed with it in
    // PLUGIN_EXIT) and every callback re-checks the state pointer: a
    // callback firing into a torn-down plugin is a compositor segfault.
    g_pGlobalState->listeners.push_back(Event::bus()->m_events.window.open.listen([](PHLWINDOW w) {
        if (g_pGlobalState)
            onNewWindow(w);
    }));
    g_pGlobalState->listeners.push_back(Event::bus()->m_events.window.close.listen([](PHLWINDOW w) {
        if (g_pGlobalState)
            onCloseWindow(w);
    }));
    g_pGlobalState->listeners.push_back(Event::bus()->m_events.window.active.listen([](PHLWINDOW w, Desktop::eFocusReason r) {
        if (g_pGlobalState)
            onWindowFocus(w);
    }));

    // Colour defaults follow the wal palette; overridden live from
    // hyprland.lua / wal-set.sh via plugin:hyprvtb:*.
    g_pGlobalState->config.enabled           = makeShared<Config::Values::CBoolValue>("plugin:hyprvtb:enabled", "Whether the vertical titlebars are enabled", true);
    g_pGlobalState->config.barWidth          = makeShared<Config::Values::CIntValue>("plugin:hyprvtb:bar_width", "Width of the vertical titlebar", 32);
    g_pGlobalState->config.fontSize          = makeShared<Config::Values::CIntValue>("plugin:hyprvtb:font_size", "Text size in px", 16);
    g_pGlobalState->config.maximizeGap       = makeShared<Config::Values::CIntValue>("plugin:hyprvtb:maximize_gap", "Extra margin kept around a maximized window", 0);
    g_pGlobalState->config.font              = makeShared<Config::Values::CStringValue>("plugin:hyprvtb:font", "Titlebar font", "More Perfect DOS VGA");
    g_pGlobalState->config.bgColor           = makeShared<Config::Values::CColorValue>("plugin:hyprvtb:bg_color", "Bar background", 0xff000000);
    g_pGlobalState->config.bgAltColor        = makeShared<Config::Values::CColorValue>("plugin:hyprvtb:col.bg_alt", "Hovered button fill", 0xff080e12);
    g_pGlobalState->config.textColor         = makeShared<Config::Values::CColorValue>("plugin:hyprvtb:col.text", "Title / glyph colour", 0xff3f6d8c);
    g_pGlobalState->config.buttonBorderColor = makeShared<Config::Values::CColorValue>("plugin:hyprvtb:col.button_border", "Button outline colour", 0xff192c38);
    g_pGlobalState->config.accentColor       = makeShared<Config::Values::CColorValue>("plugin:hyprvtb:col.accent", "Accent (maximize/minimize hover) colour", 0xff5c9fcc);
    g_pGlobalState->config.critColor         = makeShared<Config::Values::CColorValue>("plugin:hyprvtb:col.crit", "Close-hover colour", 0xff70c3fa);
    g_pGlobalState->config.inactiveColor     = makeShared<Config::Values::CColorValue>("plugin:hyprvtb:col.inactive", "Unfocused text colour (matches general:col.inactive_border)", 0xaa595959);

    HyprlandAPI::addConfigValueV2(PHANDLE, g_pGlobalState->config.enabled);
    HyprlandAPI::addConfigValueV2(PHANDLE, g_pGlobalState->config.barWidth);
    HyprlandAPI::addConfigValueV2(PHANDLE, g_pGlobalState->config.fontSize);
    HyprlandAPI::addConfigValueV2(PHANDLE, g_pGlobalState->config.maximizeGap);
    HyprlandAPI::addConfigValueV2(PHANDLE, g_pGlobalState->config.font);
    HyprlandAPI::addConfigValueV2(PHANDLE, g_pGlobalState->config.bgColor);
    HyprlandAPI::addConfigValueV2(PHANDLE, g_pGlobalState->config.bgAltColor);
    HyprlandAPI::addConfigValueV2(PHANDLE, g_pGlobalState->config.textColor);
    HyprlandAPI::addConfigValueV2(PHANDLE, g_pGlobalState->config.buttonBorderColor);
    HyprlandAPI::addConfigValueV2(PHANDLE, g_pGlobalState->config.accentColor);
    HyprlandAPI::addConfigValueV2(PHANDLE, g_pGlobalState->config.critColor);
    HyprlandAPI::addConfigValueV2(PHANDLE, g_pGlobalState->config.inactiveColor);

    if (Config::mgr()->type() != Config::CONFIG_LEGACY) {
        HyprlandAPI::addLuaFunction(PHANDLE, "hyprvtb", "minimize_active", ::luaMinimizeActive);
        HyprlandAPI::addLuaFunction(PHANDLE, "hyprvtb", "toggle_maximize_active", ::luaToggleMaximizeActive);
    }

    g_pGlobalState->listeners.push_back(Event::bus()->m_events.config.reloaded.listen([] {
        if (g_pGlobalState)
            onConfigReloaded();
    }));

    // decorate windows that already exist (none when loaded at config-parse
    // time during compositor startup — the window.open listener covers those)
    if (g_pCompositor) {
        for (auto& w : g_pCompositor->m_windows) {
            if (w->isHidden() || !w->m_isMapped)
                continue;
            onNewWindow(w);
        }
    }

    // NOTE: deliberately NOT calling HyprlandAPI::reloadConfig() here. When
    // the plugin is loaded by hl.plugin.load() during config parsing, the
    // remainder of that same parse applies our plugin:hyprvtb:* values, and
    // scheduling a nested reload from inside a reload is exactly the kind of
    // re-entrancy that segfaulted this plugin's v2. After a manual
    // `hyprctl plugin load`, run `hyprctl reload` yourself to apply colours.

    return {"hyprvtb", "Vertical per-window titlebars (close / maximize / minimize / stacked title)", "lam", "2.2"};
}

APICALL EXPORT void PLUGIN_EXIT() {
    for (auto& m : g_pCompositor->m_monitors)
        m->m_scheduledRecalc = true;

    g_pHyprRenderer->m_renderPass.removeAllOfType("CVtbPassElement");

    // Destroys the event listeners with the state, so nothing can call back
    // into this image after unload.
    g_pGlobalState.reset();
}
