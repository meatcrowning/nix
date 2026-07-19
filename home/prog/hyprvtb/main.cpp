#define WLR_USE_UNSTABLE

#include <hyprland/src/Compositor.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include <hyprland/src/event/EventBus.hpp>

#include <algorithm>

#include "vtbDeco.hpp"
#include "globals.hpp"

// Do NOT change this function.
APICALL EXPORT std::string PLUGIN_API_VERSION() {
    return HYPRLAND_API_VERSION;
}

static void onNewWindow(PHLWINDOW window) {
    if (window->m_X11DoesntWantBorders)
        return;

    if (std::ranges::any_of(window->m_windowDecorations, [](const auto& d) { return d->getDisplayName() == "Hyprvtb"; }))
        return;

    auto bar = makeUnique<CVtbDeco>(window);
    g_pGlobalState->bars.emplace_back(bar);
    bar->m_self = bar;
    HyprlandAPI::addWindowDecoration(PHANDLE, window, std::move(bar));
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

    static auto P = Event::bus()->m_events.window.open.listen([&](PHLWINDOW w) { onNewWindow(w); });

    // Colour defaults follow the wal palette Theme.qml currently carries;
    // override via plugin:hyprvtb:* in hyprland.lua.
    g_pGlobalState->config.enabled           = makeShared<Config::Values::CBoolValue>("plugin:hyprvtb:enabled", "Whether the vertical titlebars are enabled", true);
    g_pGlobalState->config.barWidth          = makeShared<Config::Values::CIntValue>("plugin:hyprvtb:bar_width", "Width of the vertical titlebar", 32);
    g_pGlobalState->config.fontSize          = makeShared<Config::Values::CIntValue>("plugin:hyprvtb:font_size", "Text size in px", 16);
    g_pGlobalState->config.maximizeGap       = makeShared<Config::Values::CIntValue>("plugin:hyprvtb:maximize_gap", "Gap kept around a maximized window (= general:gaps_out)", 35);
    g_pGlobalState->config.font              = makeShared<Config::Values::CStringValue>("plugin:hyprvtb:font", "Titlebar font", "More Perfect DOS VGA");
    g_pGlobalState->config.bgColor           = makeShared<Config::Values::CColorValue>("plugin:hyprvtb:bg_color", "Bar background", 0xff000000);
    g_pGlobalState->config.textColor         = makeShared<Config::Values::CColorValue>("plugin:hyprvtb:col.text", "Title / glyph colour", 0xff3f6d8c);
    g_pGlobalState->config.buttonBorderColor = makeShared<Config::Values::CColorValue>("plugin:hyprvtb:col.button_border", "Button outline colour", 0xff192c38);
    g_pGlobalState->config.accentColor       = makeShared<Config::Values::CColorValue>("plugin:hyprvtb:col.accent", "Accent (active maximize) colour", 0xff5c9fcc);

    HyprlandAPI::addConfigValueV2(PHANDLE, g_pGlobalState->config.enabled);
    HyprlandAPI::addConfigValueV2(PHANDLE, g_pGlobalState->config.barWidth);
    HyprlandAPI::addConfigValueV2(PHANDLE, g_pGlobalState->config.fontSize);
    HyprlandAPI::addConfigValueV2(PHANDLE, g_pGlobalState->config.maximizeGap);
    HyprlandAPI::addConfigValueV2(PHANDLE, g_pGlobalState->config.font);
    HyprlandAPI::addConfigValueV2(PHANDLE, g_pGlobalState->config.bgColor);
    HyprlandAPI::addConfigValueV2(PHANDLE, g_pGlobalState->config.textColor);
    HyprlandAPI::addConfigValueV2(PHANDLE, g_pGlobalState->config.buttonBorderColor);
    HyprlandAPI::addConfigValueV2(PHANDLE, g_pGlobalState->config.accentColor);

    static auto P2 = Event::bus()->m_events.config.reloaded.listen([&] { onConfigReloaded(); });

    // decorate windows that already exist
    for (auto& w : g_pCompositor->m_windows) {
        if (w->isHidden() || !w->m_isMapped)
            continue;
        onNewWindow(w);
    }

    HyprlandAPI::reloadConfig();

    return {"hyprvtb", "Vertical per-window titlebars (close / maximize / rotated title)", "lam", "1.0"};
}

APICALL EXPORT void PLUGIN_EXIT() {
    for (auto& m : g_pCompositor->m_monitors)
        m->m_scheduledRecalc = true;

    g_pHyprRenderer->m_renderPass.removeAllOfType("CVtbPassElement");
}
