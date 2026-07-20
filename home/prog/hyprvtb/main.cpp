#define WLR_USE_UNSTABLE

#include <hyprland/src/Compositor.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/desktop/history/WindowHistoryTracker.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include <hyprland/src/event/EventBus.hpp>
#include <hyprland/src/managers/KeybindManager.hpp>
#include <hyprland/src/desktop/state/FocusState.hpp>
#include <hyprland/src/config/ConfigManager.hpp>
#include <hyprland/src/config/shared/actions/ConfigActions.hpp>
#include <hyprland/src/config/supplementary/executor/Executor.hpp>

extern "C" {
#include <lua.h>
#include <lauxlib.h>
}

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <format>
#include <fstream>
#include <sstream>

#include <hyprland/src/SharedDefs.hpp> // eRenderStage

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

// ---- scratchpad terminal ---------------------------------------------------

static constexpr const char* SCRATCH_CLASS = "hyprvtb-scratch";

static PHLWINDOW scratchWindow() {
    for (auto& w : g_pCompositor->m_windows) {
        if (w->m_isMapped && !w->isHidden() && w->m_class == SCRATCH_CLASS)
            return w;
    }
    return nullptr;
}

// Pinned geometry: left edge of the usable area, full height, width from the
// remembered value (user-resizable via the right border, resize_on_border).
static CBox scratchTarget(PHLWINDOW w) {
    const auto PMONITOR = w->m_monitor ? w->m_monitor.lock() : Desktop::focusState()->monitor();
    if (!PMONITOR)
        return {};

    const auto BS     = w->getRealBorderSize();
    const CBox usable = PMONITOR->m_reservedArea.apply(CBox{PMONITOR->m_position, PMONITOR->m_size});

    double     width  = usable.w / 4.0;
    const auto IT     = g_pGlobalState->savedGeometry.find(SCRATCH_CLASS);
    if (IT != g_pGlobalState->savedGeometry.end() && IT->second.w >= 100)
        width = IT->second.w;

    return {usable.x + BS, usable.y + BS, width, usable.h - BS * 2};
}

static void showScratch(PHLWINDOW w, bool warpFromOffscreen) {
    const auto T = scratchTarget(w);
    if (T.w < 1)
        return;

    if (warpFromOffscreen)
        w->m_realPosition->setValueAndWarp(Vector2D(T.x - T.w - 16, T.y));

    Config::Actions::resize(T.size(), false, w);
    Config::Actions::move(T.pos(), false, w);
    g_pCompositor->changeWindowZOrder(w, false); // always at the BOTTOM
    Desktop::focusState()->fullWindowFocus(w, Desktop::FOCUS_REASON_CLICK);
    g_pGlobalState->scratchVisible = true;
}

static void hideScratch(PHLWINDOW w) {
    const auto T = scratchTarget(w);
    Config::Actions::move(Vector2D(T.x - T.w - 16, T.y), false, w);
    g_pGlobalState->scratchVisible = false;

    // hand focus back to some other window
    for (auto& o : g_pCompositor->m_windows) {
        if (o != w && o->m_isMapped && !o->isHidden() && o->m_workspace == w->m_workspace) {
            Desktop::focusState()->fullWindowFocus(o, Desktop::FOCUS_REASON_CLICK);
            return;
        }
    }
    Desktop::focusState()->resetWindowFocus();
}

static void toggleScratch() {
    const auto W = scratchWindow();
    if (!W) {
        // window.open places + slides it in once kitty has mapped
        Config::Supplementary::executor()->spawn(std::string("kitty --class ") + SCRATCH_CLASS);
        return;
    }

    if (g_pGlobalState->scratchVisible)
        hideScratch(W);
    else
        showScratch(W, false);
}

// ---- window lifecycle ------------------------------------------------------

// isNew distinguishes a genuine window.open (apply the remembered per-class
// geometry — "reopen the app where you left it") from re-decorating an already
// open window when the plugin loads over a running session (PLUGIN_INIT's
// existing-window sweep, incl. every hot `hyprctl plugin load`). Applying saved
// geometry to already-placed windows is what made a reload teleport them all.
static void onNewWindow(PHLWINDOW window, bool isNew) {
    if (window->m_X11DoesntWantBorders)
        return;

    // The scratchpad gets NO titlebar; it slides in from the left edge and
    // lives at the bottom of the z-order. Only (re)place it on a real open —
    // on a reload it's already positioned, leave it be.
    if (window->m_class == SCRATCH_CLASS) {
        if (isNew)
            showScratch(window, true);
        return;
    }

    if (std::ranges::any_of(window->m_windowDecorations, [](const auto& d) { return d->getDisplayName() == "Hyprvtb"; }))
        return;

    auto bar = makeUnique<CVtbDeco>(window);
    g_pGlobalState->bars.emplace_back(bar);
    bar->m_self = bar;
    HyprlandAPI::addWindowDecoration(PHANDLE, window, std::move(bar));

    // reopen where/how this app was last closed — ONLY for a genuinely new
    // window, never for one that's already open (a reload must not move it)
    if (isNew && window->m_isFloating) {
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

    if (window->m_class == SCRATCH_CLASS) {
        g_pGlobalState->scratchVisible = false;
        return; // width is persisted on resize, not here
    }

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

    // the scratchpad never rises above other windows, even focused
    if (window->m_class == SCRATCH_CLASS) {
        g_pCompositor->changeWindowZOrder(window, false);
        return;
    }

    // focus raises floating windows — so activating from the taskbar or
    // alt-tab actually brings the window forward, not just recolours it
    if (window->m_isFloating)
        g_pCompositor->changeWindowZOrder(window, true);

    for (auto& b : g_pGlobalState->bars) {
        if (b && b->getOwner() == window) {
            b->onFocusGained();
            break;
        }
    }
}

// ---- KDE-style alt-tab: most-recently-used window cycling -----------------
//
// Hyprland's cyclenext walks the window LIST (creation order); KDE walks
// focus history. Naively cycling the live history can only ever bounce
// between the two most recent windows (focusing B puts it at the front, so
// the "next" from B is A again — C is unreachable). KDE solves this with a
// hold-Alt walk that commits on release; we approximate it: successive
// calls within WALK_MS continue through a SNAPSHOT of the history taken
// when the walk began, so tab-tab-tab digs deeper exactly like KDE's
// switcher, and pausing (releasing Alt) naturally commits — the next
// alt-tab starts a fresh walk from the new focus order.
static std::vector<PHLWINDOWREF> s_altTabWalk;
static size_t                    s_altTabPos  = 0;
static Time::steady_tp           s_altTabLast = Time::steadyNow();
static constexpr int             ALTTAB_WALK_MS = 900;

static bool altTabCycleable(const PHLWINDOW& w) {
    if (!w || !w->m_isMapped || w->isHidden())
        return false;
    if (w->m_class == SCRATCH_CLASS) // the scratchpad is toggled, not tabbed to
        return false;
    if (w->m_workspace && !w->m_workspace->isVisible())
        return false;
    return true; // minimized windows stay in: focusing them slides them back
}

static void cycleHist(bool prev) {
    const auto CUR = Desktop::focusState()->window();
    const bool CONTINUING =
        std::chrono::duration_cast<std::chrono::milliseconds>(Time::steadyNow() - s_altTabLast).count() < ALTTAB_WALK_MS && !s_altTabWalk.empty();
    s_altTabLast = Time::steadyNow();

    if (!CONTINUING) {
        s_altTabWalk.clear();
        s_altTabPos = 0;
        for (const auto& w : Desktop::History::windowTracker()->fullHistory()) {
            const auto l = w.lock();
            if (!l)
                continue;
            if (l == CUR || altTabCycleable(l)) {
                if (l == CUR)
                    s_altTabPos = s_altTabWalk.size();
                s_altTabWalk.push_back(w);
            }
        }
    }

    const size_t N = s_altTabWalk.size();
    if (N < 2)
        return;

    // step around the frozen ring, skipping entries that died mid-walk
    for (size_t i = 1; i <= N; i++) {
        const size_t idx = (s_altTabPos + (prev ? N - (i % N) : i)) % N;
        const auto   w   = s_altTabWalk[idx].lock();
        if (!w || (w != CUR && !altTabCycleable(w)))
            continue;
        s_altTabPos = idx;
        // raise + minimized-restore ride on the window.active listener
        Desktop::focusState()->fullWindowFocus(w, Desktop::FOCUS_REASON_CLICK);
        return;
    }
}

// lua: hyprvtb.cycle_hist_next() / cycle_hist_prev() — Alt(+Shift)+Tab.
static int luaCycleHistNext(lua_State* L) {
    if (g_pGlobalState)
        cycleHist(false);
    return 0;
}

static int luaCycleHistPrev(lua_State* L) {
    if (g_pGlobalState)
        cycleHist(true);
    return 0;
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

// lua: hyprvtb.rollup([address]) — windowshade a window (same as the titlebar
// >> button). No arg targets the active window (bind this to a key). A shaded
// window is hidden and thus not focusable, so pass "address:0x.." to un-shade
// a specific one from a script.
static int luaRollup(lua_State* L) {
    if (!g_pGlobalState)
        return 0;

    std::string a = luaL_optstring(L, 1, "");
    if (a.starts_with("address:"))
        a = a.substr(8);

    CVtbDeco* deco = nullptr;
    if (a.starts_with("0x")) {
        const uintptr_t want = std::strtoull(a.c_str(), nullptr, 16);
        for (auto& b : g_pGlobalState->bars) {
            if (b && (uintptr_t)b->getOwner().get() == want) {
                deco = b.get();
                break;
            }
        }
    } else
        deco = activeDeco();

    if (deco)
        deco->toggleRollup();
    return 0;
}

// lua: hyprvtb.toggle_scratch() — the Meta+S slide-in terminal.
static int luaToggleScratch(lua_State* L) {
    if (g_pGlobalState)
        toggleScratch();
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
            onNewWindow(w, true); // real open — remembered geometry applies
    }));
    g_pGlobalState->listeners.push_back(Event::bus()->m_events.window.close.listen([](PHLWINDOW w) {
        if (g_pGlobalState)
            onCloseWindow(w);
    }));
    g_pGlobalState->listeners.push_back(Event::bus()->m_events.window.active.listen([](PHLWINDOW w, Desktop::eFocusReason r) {
        if (g_pGlobalState)
            onWindowFocus(w);
    }));
    // After any mouse release: re-pin the scratchpad (a border-drag may have
    // moved edges other than the right one) and persist its dragged width.
    g_pGlobalState->listeners.push_back(Event::bus()->m_events.input.mouse.button.listen([](IPointer::SButtonEvent e, Event::SCallbackInfo& info) {
        if (!g_pGlobalState || e.state != WL_POINTER_BUTTON_STATE_RELEASED || !g_pGlobalState->scratchVisible)
            return;
        const auto W = scratchWindow();
        if (!W)
            return;
        const auto  DRAGW = W->m_realSize->goal().x;
        auto        T     = scratchTarget(W);
        T.w               = DRAGW;
        if (W->m_realPosition->goal() != T.pos() || W->m_realSize->goal().y != T.h) {
            Config::Actions::resize(T.size(), false, W);
            Config::Actions::move(T.pos(), false, W);
        }
        auto& saved = g_pGlobalState->savedGeometry[SCRATCH_CLASS];
        if ((int)saved.w != (int)DRAGW) {
            saved = {0, 0, DRAGW, T.h};
            vtbSaveGeometry();
        }
    }));

    // Shaded (rolled-up) windows are hidden — Hyprland never renders them or
    // calls their decoration draw() — so draw each shaded window's bar here,
    // once per monitor. RENDER_PRE_WINDOWS fires after the background/bottom
    // layers but before windows, so the shade bar sits OVER the desktop
    // widgets (bottom-layer quickshell) yet UNDER every window.
    // renderShadeIfRolled no-ops for non-shaded bars.
    g_pGlobalState->listeners.push_back(Event::bus()->m_events.render.stage.listen([](eRenderStage stage) {
        if (!g_pGlobalState || stage != RENDER_PRE_WINDOWS)
            return;
        const auto PMONITOR = g_pHyprRenderer->m_renderData.pMonitor.lock();
        if (!PMONITOR)
            return;
        for (auto& b : g_pGlobalState->bars) {
            if (b)
                b->renderShadeIfRolled(PMONITOR);
        }
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
        HyprlandAPI::addLuaFunction(PHANDLE, "hyprvtb", "rollup", ::luaRollup);
        HyprlandAPI::addLuaFunction(PHANDLE, "hyprvtb", "toggle_scratch", ::luaToggleScratch);
        HyprlandAPI::addLuaFunction(PHANDLE, "hyprvtb", "cycle_hist_next", ::luaCycleHistNext);
        HyprlandAPI::addLuaFunction(PHANDLE, "hyprvtb", "cycle_hist_prev", ::luaCycleHistPrev);
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
            onNewWindow(w, false); // already open — decorate only, don't move it
        }
    }

    // NOTE: deliberately NOT calling HyprlandAPI::reloadConfig() here. When
    // the plugin is loaded by hl.plugin.load() during config parsing, the
    // remainder of that same parse applies our plugin:hyprvtb:* values, and
    // scheduling a nested reload from inside a reload is exactly the kind of
    // re-entrancy that segfaulted this plugin's v2. After a manual
    // `hyprctl plugin load`, run `hyprctl reload` yourself to apply colours.

    return {"hyprvtb", "Vertical per-window titlebars (close / maximize / minimize / pin / roll-up / stacked title) + KDE-style edge resize + MRU alt-tab", "lam", "2.16"};
}

APICALL EXPORT void PLUGIN_EXIT() {
    for (auto& m : g_pCompositor->m_monitors)
        m->m_scheduledRecalc = true;

    g_pHyprRenderer->m_renderPass.removeAllOfType("CVtbPassElement");

    // Destroys the event listeners with the state, so nothing can call back
    // into this image after unload.
    g_pGlobalState.reset();
}
