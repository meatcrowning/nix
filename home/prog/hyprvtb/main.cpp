#define WLR_USE_UNSTABLE

#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/desktop/history/WindowHistoryTracker.hpp>
#include <hyprland/src/event/EventBus.hpp>
#include <hyprland/src/config/ConfigManager.hpp>
#include <hyprland/src/config/shared/actions/ConfigActions.hpp>
#include <hyprland/src/config/supplementary/executor/Executor.hpp>
#include <hyprland/src/managers/eventLoop/EventLoopManager.hpp>

extern "C" {
#include <lua.h>
#include <lauxlib.h>
}

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <unistd.h> // getpid — the hot-swap handoff's staleness guard
#include <filesystem>
#include <format>
#include <fstream>
#include <iterator>
#include <sstream>

#include <hyprland/src/SharedDefs.hpp> // eRenderStage

#include "vtbDeco.hpp"
#include "VtbPassElement.hpp"
#include "vtbIpc.hpp"
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

// A remembered position can outlive the layout it was recorded on — a monitor
// that got unplugged, a resolution change, or a window that was dragged mostly
// off-screen before it was closed. Restoring it verbatim puts the window
// somewhere the user can never see or grab it (and, because onCloseWindow
// re-saves whatever box the window had, that state round-trips forever). Pull
// the restored position back onto the target monitor's usable area; windows
// wider/taller than the monitor just pin to its top-left.
static CBox clampToMonitor(const CBox& box, PHLWINDOW w) {
    const auto PMONITOR = w && w->m_monitor ? w->m_monitor.lock() : Hl::focusedMonitor();
    if (!PMONITOR)
        return box;

    const CBox usable = PMONITOR->m_reservedArea.apply(CBox{PMONITOR->m_position, PMONITOR->m_size});

    CBox       out    = box;
    out.x             = box.w <= usable.w ? std::clamp(box.x, usable.x, usable.x + usable.w - box.w) : usable.x;
    out.y             = box.h <= usable.h ? std::clamp(box.y, usable.y, usable.y + usable.h - box.h) : usable.y;
    return out;
}

// The slide-in scratchpad terminal's window class (defined here, ahead of the
// scratchpad section, because the session snapshot below also skips it).
static constexpr const char* SCRATCH_CLASS = "hyprvtb-scratch";

// ---- hot-swap handoff (roll/minimize state across `hyprctl reload`) --------
//
// PLUGIN_EXIT has to hand every window back in a plain state: a rolled-up
// window is HIDDEN and a minimized one is parked off-screen, and both are
// states only the running instance knows how to leave (restoreForUnload —
// leaving them would strand a window with no titlebar, or invisible entirely).
// But the incoming instance then sees plain windows, so every rolled-up window
// snapped open on a hot swap and never came back.
//
// So write those states down on the way out and re-apply them on the way in,
// which makes a swap invisible: the window is un-rolled and re-rolled inside
// one PLUGIN_EXIT/PLUGIN_INIT pair, with no frame drawn in between.
//
// Keyed by window ADDRESS, which is stable here in a way it is nowhere else:
// this is the same compositor process, mid-`hyprctl reload`, so the CWindow
// objects never move. The file records the compositor's PID for exactly that
// reason — after a restart the addresses are meaningless (and could collide
// with unrelated windows), so a PID mismatch discards it. It is consumed and
// deleted on the first read either way; nothing about it survives a login.
struct SHandoffEntry {
    uintptr_t addr     = 0;
    bool      rolled   = false;
    bool      minimized = false;
};

static std::string vtbHandoffPath() {
    const char* home = std::getenv("HOME");
    return std::string(home ? home : "") + "/.local/state/hyprvtb/handoff.tsv";
}

// Called from PLUGIN_EXIT BEFORE restoreForUnload undoes these states.
static void vtbSaveHandoff() {
    if (!g_pGlobalState)
        return;

    std::vector<SHandoffEntry> entries;
    for (auto& b : g_pGlobalState->bars) {
        if (!b.alive())
            continue;
        const auto w = b->getOwner();
        if (!w || !w->m_isMapped)
            continue;
        if (!b->isRolledUp() && !b->isMinimized())
            continue;
        entries.push_back({(uintptr_t)w.get(), b->isRolledUp(), b->isMinimized()});
    }

    const auto PATH = vtbHandoffPath();
    if (entries.empty()) {
        std::error_code ec;
        std::filesystem::remove(PATH, ec); // no stale file to mis-apply later
        return;
    }

    std::filesystem::create_directories(std::filesystem::path(PATH).parent_path());
    std::ofstream f(PATH, std::ios::trunc);
    f << "pid\t" << (long)getpid() << '\n';
    for (const auto& e : entries)
        f << e.addr << '\t' << (int)e.rolled << '\t' << (int)e.minimized << '\n';
}

// Called from PLUGIN_INIT AFTER the existing windows have been decorated (the
// state is applied through their fresh decorations).
static void vtbApplyHandoff() {
    const auto      PATH = vtbHandoffPath();
    std::ifstream   f(PATH);
    std::error_code ec;
    if (!f.good()) {
        std::filesystem::remove(PATH, ec);
        return;
    }

    std::vector<SHandoffEntry> entries;
    bool                       pidOk = false;
    std::string                line;
    while (std::getline(f, line)) {
        std::istringstream ss(line);
        std::string        first;
        if (!std::getline(ss, first, '\t'))
            continue;
        if (first == "pid") {
            long pid = 0;
            if (ss >> pid)
                pidOk = (pid == (long)getpid());
            continue;
        }
        SHandoffEntry e;
        int           rolled = 0, minimized = 0;
        e.addr = std::strtoull(first.c_str(), nullptr, 10);
        if (!(ss >> rolled >> minimized) || !e.addr)
            continue;
        e.rolled    = rolled;
        e.minimized = minimized;
        entries.push_back(e);
    }
    f.close();
    std::filesystem::remove(PATH, ec); // one-shot: never applied twice

    if (!pidOk || entries.empty() || !g_pGlobalState || !Hl::compositorReady())
        return;

    for (const auto& e : entries) {
        for (auto& b : g_pGlobalState->bars) {
            if (!b.alive())
                continue;
            const auto w = b->getOwner();
            if (!w || (uintptr_t)w.get() != e.addr)
                continue;
            if (e.rolled)
                b->toggleRollup(false); // snap back, no animation
            else if (e.minimized)
                b->minimizeWindow();
            break;
        }
    }
}

// ---- session snapshot (manual save on a keybind + restore at login) --------
//
// Unlike the per-class geometry memory above (which just repositions an app
// when you next open it), a session snapshot records the FULL set of open
// windows — class, geometry, min/roll/max state, and the exact command +cwd
// that launched each — so a fresh login can relaunch and lay them back out.
// Saving is explicit (hyprvtb:save_session, bound to a key); restore runs once
// at PLUGIN_INIT and only when the session is genuinely empty.

std::string vtbSessionPath() {
    const char* home = std::getenv("HOME");
    return std::string(home ? home : "") + "/.local/state/hyprvtb/session.tsv";
}

// Single-quote for /bin/sh, escaping embedded quotes, so argv tokens with
// spaces/metacharacters relaunch verbatim.
static std::string shQuote(const std::string& s) {
    std::string out = "'";
    for (const char c : s) {
        if (c == '\'')
            out += "'\\''";
        else
            out += c;
    }
    out += "'";
    return out;
}

// Rebuild a relaunch command from a live PID: argv from /proc/PID/cmdline
// (NUL-separated), run in /proc/PID/cwd. "" if the process is gone or exposes
// no cmdline (kernel thread, already-exited helper) — such a window is simply
// not persisted, since we couldn't bring it back anyway.
static std::string vtbRelaunchCmd(pid_t pid) {
    if (pid <= 0)
        return "";

    std::ifstream cf("/proc/" + std::to_string(pid) + "/cmdline", std::ios::binary);
    if (!cf.good())
        return "";
    const std::string raw((std::istreambuf_iterator<char>(cf)), std::istreambuf_iterator<char>());
    if (raw.empty())
        return "";

    std::string argv, tok;
    const auto  flush = [&] {
        if (tok.empty())
            return;
        if (!argv.empty())
            argv += ' ';
        argv += shQuote(tok);
        tok.clear();
    };
    for (const char c : raw) {
        if (c == '\0')
            flush();
        else
            tok += c;
    }
    flush();
    if (argv.empty())
        return "";

    std::error_code ec;
    const auto      cwd = std::filesystem::read_symlink("/proc/" + std::to_string(pid) + "/cwd", ec);
    if (!ec && !cwd.empty())
        return "cd " + shQuote(cwd.string()) + " && exec " + argv;
    return "exec " + argv;
}

void vtbSaveSession() {
    const auto PATH = vtbSessionPath();
    std::filesystem::create_directories(std::filesystem::path(PATH).parent_path());
    std::ofstream f(PATH, std::ios::trunc);

    int n = 0;
    for (auto& b : g_pGlobalState->bars) {
        if (!b)
            continue;
        const auto w = b->getOwner();
        if (!w || !w->m_isMapped || w->m_class.empty() || w->m_class == SCRATCH_CLASS)
            continue;

        const std::string cmd = vtbRelaunchCmd(w->getPID());
        if (cmd.empty())
            continue; // can't relaunch it -> don't pretend we can

        const CBox box   = b->memorableGeometry();
        int        flags = 0;
        if (b->isMaximized())
            flags |= 1;
        if (b->isMinimized())
            flags |= 2;
        if (b->isRolledUp())
            flags |= 4;

        // cls \t flags \t x \t y \t w \t h \t cmd(rest-of-line)
        f << w->m_class << '\t' << flags << '\t' << (int)box.x << '\t' << (int)box.y << '\t' << (int)box.w << '\t'
          << (int)box.h << '\t' << cmd << '\n';
        n++;
    }
    f.close();

    HyprlandAPI::addNotification(PHANDLE, "[hyprvtb] session saved (" + std::to_string(n) + " windows)",
                                 CHyprColor{0.4, 0.8, 1.0, 1.0}, 3000);
}

// Read the snapshot and, ONLY on a fresh (empty) session, relaunch every entry
// and queue it for layout. onNewWindow consumes the queue as windows appear.
void vtbRestoreSession() {
    std::ifstream f(vtbSessionPath());
    if (!f.good())
        return;

    std::vector<SSessionEntry> entries;
    std::string                line;
    while (std::getline(f, line)) {
        std::istringstream ss(line);
        SSessionEntry      e;
        std::string        flagss, xs, ys, ws, hs;
        if (!std::getline(ss, e.cls, '\t') || !std::getline(ss, flagss, '\t') || !std::getline(ss, xs, '\t') ||
            !std::getline(ss, ys, '\t') || !std::getline(ss, ws, '\t') || !std::getline(ss, hs, '\t') ||
            !std::getline(ss, e.cmd))
            continue;
        try {
            const int flags = std::stoi(flagss);
            e.box            = CBox{(double)std::stoi(xs), (double)std::stoi(ys), (double)std::stoi(ws), (double)std::stoi(hs)};
            e.maximized      = flags & 1;
            e.minimized      = flags & 2;
            e.rolled         = flags & 4;
        } catch (...) {
            continue;
        }
        if (e.cls.empty() || e.cmd.empty())
            continue;
        entries.push_back(std::move(e));
    }
    if (entries.empty())
        return;

    // Only relaunch on a genuinely fresh session. If any non-scratch window is
    // already open, this is a mid-session (re)init, not a login — relaunching
    // would double everything, so bail without spawning or queuing.
    for (auto& w : Hl::windows()) {
        if (w && w->m_isMapped && !w->m_class.empty() && w->m_class != SCRATCH_CLASS)
            return;
    }

    g_pGlobalState->pendingRestore = std::move(entries);
    g_pGlobalState->restoreUntil   = std::chrono::steady_clock::now() + std::chrono::seconds(60);
    for (auto& e : g_pGlobalState->pendingRestore)
        Config::Supplementary::executor()->spawn(e.cmd);
}

// ---- scratchpad terminal ---------------------------------------------------
// (SCRATCH_CLASS is defined above, ahead of the session-snapshot helpers.)

static PHLWINDOW scratchWindow() {
    for (auto& w : Hl::windows()) {
        if (w->m_isMapped && !w->isHidden() && w->m_class == SCRATCH_CLASS)
            return w;
    }
    return nullptr;
}

// Pinned geometry: left edge of the usable area, full height, width from the
// remembered value (user-resizable via the right border, resize_on_border).
static CBox scratchTarget(PHLWINDOW w) {
    const auto PMONITOR = w->m_monitor ? w->m_monitor.lock() : Hl::focusedMonitor();
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
        Hl::warpPos(w, Vector2D(T.x - T.w - 16, T.y));

    Config::Actions::resize(T.size(), false, w);
    Config::Actions::move(T.pos(), false, w);
    Hl::lower(w); // always at the BOTTOM
    Hl::focusWindow(w);
    g_pGlobalState->scratchVisible = true;
}

static void hideScratch(PHLWINDOW w) {
    const auto T = scratchTarget(w);
    Config::Actions::move(Vector2D(T.x - T.w - 16, T.y), false, w);
    g_pGlobalState->scratchVisible = false;

    // hand focus back to some other window
    for (auto& o : Hl::windows()) {
        if (o != w && o->m_isMapped && !o->isHidden() && o->m_workspace == w->m_workspace) {
            Hl::focusWindow(o);
            return;
        }
    }
    Hl::resetFocus();
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
    const CDecoRef thisDeco = g_pGlobalState->bars.back();
    bar->m_self = bar;
    HyprlandAPI::addWindowDecoration(PHANDLE, window, std::move(bar));

    // Separate decoration for the bottom-left hard shadow (see CVtbShadowDeco).
    HyprlandAPI::addWindowDecoration(PHANDLE, window, makeUnique<CVtbShadowDeco>(window));

    // reopen where/how this app was last closed — ONLY for a genuinely new
    // window, never for one that's already open (a reload must not move it)
    if (isNew && window->m_isFloating) {
        // A pending session-restore entry for this class wins over the per-class
        // memory: place the relaunched window at its snapshot geometry and put
        // it back into its saved min/roll/max state. First unconsumed match by
        // class (multiple windows of one class restore in save order).
        SSessionEntry* match = nullptr;
        for (auto& e : g_pGlobalState->pendingRestore) {
            if (!e.consumed && e.cls == window->m_class) {
                match = &e;
                break;
            }
        }
        if (match) {
            match->consumed = true;
            Config::Actions::resize(match->box.size(), false, window);
            Config::Actions::move(match->box.pos(), false, window);
            // Re-apply the one exclusive state (geometry is set first so a later
            // un-maximize / un-minimize returns to the restored box).
            if (thisDeco) {
                if (match->maximized)
                    thisDeco->toggleMaximize();
                else if (match->rolled)
                    thisDeco->toggleRollup(false); // snap to rolled state, no animation
                else if (match->minimized)
                    thisDeco->minimizeWindow();
            }
            return;
        }

        const auto IT = g_pGlobalState->savedGeometry.find(window->m_class);
        if (IT != g_pGlobalState->savedGeometry.end()) {
            Config::Actions::resize(IT->second.size(), false, window);
            Config::Actions::move(clampToMonitor(IT->second, window).pos(), false, window);
        }

        // Play the open reveal: only titlebar fades in, then the window rolls out
        // and takes focus. Reached only for a genuinely new, normally-shown
        // floating window (session-restore of a special state returned above).
        if (thisDeco)
            thisDeco->startOpenReveal();
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
        Hl::lower(window);
        return;
    }

    // focus raises floating windows — so activating from the taskbar or
    // alt-tab actually brings the window forward, not just recolours it
    if (window->m_isFloating)
        Hl::raise(window);

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
    const auto CUR = Hl::focusedWindow();
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
        Hl::focusWindow(w);
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
    const auto W = Hl::focusedWindow();
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

// lua: hyprvtb.close_active() — close the active window exactly as if its
// titlebar [x] were clicked: closeWindow() runs the roll-up + fade-out close
// animation for ordinary floating windows (falling back to a plain sendClose
// for tiled/min/max), vs. Hyprland's own window.close which tears the window
// down with no plugin animation. Bind this to a key.
static int luaCloseActive(lua_State* L) {
    if (auto d = activeDeco())
        d->closeWindow();
    return 0;
}

// The last window rolled up through the no-arg keybind path, so a second press
// of the same key un-shades it: a rolled window is hidden and can't be the
// active window, so the toggle can't find it through focus — we remember it.
static PHLWINDOWREF g_lastRolled;

// lua: hyprvtb.rollup([address]) — windowshade a window (same as the titlebar
// >> button). No arg is the keybind toggle: roll up the active window, and on
// the NEXT press un-shade whatever it last rolled up (a shaded window is hidden
// and thus not focusable, so it can't be reached through the active window).
// Pass "address:0x.." to un-shade a specific one from a script.
static int luaRollup(lua_State* L) {
    if (!g_pGlobalState)
        return 0;

    std::string a = luaL_optstring(L, 1, "");
    if (a.starts_with("address:"))
        a = a.substr(8);

    // Explicit address target (scripts): toggle exactly that window.
    if (a.starts_with("0x")) {
        const uintptr_t want = std::strtoull(a.c_str(), nullptr, 16);
        for (auto& b : g_pGlobalState->bars) {
            if (b && (uintptr_t)b->getOwner().get() == want) {
                b->toggleRollup();
                break;
            }
        }
        return 0;
    }

    // No-arg keybind toggle. First, if we have a still-shaded window from the
    // last press, un-shade it (and forget it) instead of rolling a new one.
    if (const auto W = g_lastRolled.lock()) {
        g_lastRolled.reset();
        for (auto& b : g_pGlobalState->bars) {
            if (b && b->getOwner() == W && b->isRolledUp()) {
                b->toggleRollup(); // roll back out; toggleRollup refocuses it
                return 0;
            }
        }
        // fell through: it closed or was un-shaded elsewhere — roll a new one.
    }

    // Roll up the active window and remember it (it's live/focusable, so it is
    // never itself already shaded — no need to check which way the toggle goes).
    if (const auto d = activeDeco()) {
        g_lastRolled = d->getOwner();
        d->toggleRollup();
    }
    return 0;
}

// lua: hyprvtb.toggle_scratch() — the Meta+S slide-in terminal.
static int luaToggleScratch(lua_State* L) {
    if (g_pGlobalState)
        toggleScratch();
    return 0;
}

// lua: hyprvtb.close_all() — the graceful session-exit primitive used by the
// power menu (logout / reboot / poweroff via quickshell-files/scripts/
// session-exit.sh). "Clicks the [x]" on every decorated non-scratch window: a
// plain sendClose() is the same graceful xdg-toplevel close the titlebar
// button issues, giving each app a chance to persist its own state — and
// giving the plugin's own window.close handler a chance to record the
// window's geometry — before the compositor is torn down (vs. pkill Hyprland,
// which just drops the socket). THAT is the whole point of this: apps and
// per-class geometry remember where the window was. It deliberately does NOT
// snapshot a session for relaunch; logging in should not spawn anything.
// (Session snapshots are a separate, explicit thing — hyprvtb.save_session()
// on Meta+Ctrl+S.)
//
// sendClose only *requests* the close — the client goes away asynchronously
// (window.close fires later), so iterating the bar list here is safe and the
// caller waits for the windows to actually vanish before pulling the plug.
static int luaCloseAll(lua_State* L) {
    if (!g_pGlobalState)
        return 0;
    for (auto& b : g_pGlobalState->bars) {
        if (!b)
            continue;
        const auto w = b->getOwner();
        if (w && w->m_isMapped && w->m_class != SCRATCH_CLASS)
            w->sendClose();
    }
    return 0;
}

// lua: hyprvtb.save_session() — snapshot the current windows (position +
// min/roll/max state + relaunch command) so the next fresh login restores
// them. Bind to a key (Meta+Ctrl+S); pops a confirmation notification.
static int luaSaveSession(lua_State* L) {
    if (g_pGlobalState)
        vtbSaveSession();
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

    // App-button socket ($XDG_RUNTIME_DIR/hyprvtb-buttons.sock): client apps
    // register the inner titlebar column's buttons here. All I/O on its own
    // thread; see vtbIpc.hpp for the protocol.
    VtbIpc::start();

    // 150ms main-thread heartbeat: repaints bars whose registration changed
    // (the IPC thread must never touch the renderer) and pops hover tooltips
    // once their dwell passes even with a motionless cursor. Same re-arm
    // pattern as Hyprland's own ANRManager.
    g_pGlobalState->tick = makeShared<CEventLoopTimer>(std::chrono::milliseconds(150),
                                                       [](SP<CEventLoopTimer> self, void*) {
                                                           if (!g_pGlobalState)
                                                               return;
                                                           // Stale restore entries stop being restore entries (see
                                                           // SGlobalState::restoreUntil).
                                                           if (!g_pGlobalState->pendingRestore.empty() &&
                                                               std::chrono::steady_clock::now() > g_pGlobalState->restoreUntil)
                                                               g_pGlobalState->pendingRestore.clear();
                                                           const auto SERIAL = VtbIpc::serial.load(std::memory_order_relaxed);
                                                           for (auto& b : g_pGlobalState->bars) {
                                                               if (b)
                                                                   b->mainThreadTick(SERIAL);
                                                           }
                                                           self->updateTimeout(std::chrono::milliseconds(150));
                                                       },
                                                       nullptr);
    g_pEventLoopManager->addTimer(g_pGlobalState->tick);

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
        const auto  DRAGW = Hl::sizeGoal(W).x;
        auto        T     = scratchTarget(W);
        T.w               = DRAGW;
        if (Hl::posGoal(W) != T.pos() || Hl::sizeGoal(W).y != T.h) {
            Config::Actions::resize(T.size(), false, W);
            Config::Actions::move(T.pos(), false, W);
        }
        auto& saved = g_pGlobalState->savedGeometry[SCRATCH_CLASS];
        if ((int)saved.w != (int)DRAGW) {
            saved = {0, 0, DRAGW, T.h};
            vtbSaveGeometry();
        }
    }));

    // Two render-stage jobs, both per-monitor:
    //  * RENDER_PRE_WINDOWS (after background/bottom layers, before windows):
    //    first the flat drop-shadow layer — EVERY window's shadow, unioned into
    //    one region so overlapping shadows don't blend into a darker patch and
    //    no shadow lands on a window (vtbRenderShadowLayer). Then each shaded
    //    (rolled-up) window's bar: a shaded window is hidden, so Hyprland never
    //    renders it or calls its draw() — the shade bar sits OVER the desktop
    //    widgets (bottom-layer quickshell) yet UNDER windows, and over the
    //    shadows, which is why it is enqueued second.
    //  * RENDER_POST_WINDOWS (after windows, before top/overlay layers): draw
    //    the hover tooltip so it lands OVER the window it labels (the bar's own
    //    UNDER-layer pass draws before the window; the tooltip overhangs left
    //    into the window's area and would be occluded there).
    // Both helpers no-op when they have nothing to draw.
    g_pGlobalState->listeners.push_back(Event::bus()->m_events.render.stage.listen([](eRenderStage stage) {
        if (!g_pGlobalState || (stage != RENDER_PRE_WINDOWS && stage != RENDER_POST_WINDOWS))
            return;
        const auto PMONITOR = Hl::renderMonitor();
        if (!PMONITOR)
            return;
        if (stage == RENDER_PRE_WINDOWS) {
            auto shadows        = CVtbPassElement::SVtbData{};
            shadows.shadowLayer = true;
            Hl::addPass(makeUnique<CVtbPassElement>(shadows));
        }
        for (auto& b : g_pGlobalState->bars) {
            if (!b)
                continue;
            // Shade bar UNDER windows (pre); hover tooltip OVER windows (post).
            // Exception: a window on its way to the foreground — sliding OUT
            // (un-shading) or playing its open reveal — draws OVER windows from
            // the first frame, otherwise it animates behind everything and only
            // pops on top when it lands and the real window is un-hidden/raised.
            const bool aboveWindows = b->isRollingOut() || b->isOpening();
            if (stage == RENDER_PRE_WINDOWS) {
                if (!aboveWindows)
                    b->renderShadeIfRolled(PMONITOR);
            } else {
                if (aboveWindows)
                    b->renderShadeIfRolled(PMONITOR);
                b->enqueueTooltip(PMONITOR);
            }
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

    // Every plugin action is exposed as a Lua function and nothing else.
    // `addDispatcherV2` is deliberately NOT used: under the Lua config,
    // `hyprctl dispatch X` *evaluates X as a Lua expression*, so a registered
    // dispatcher name resolves to an undefined global and silently does
    // nothing (that's how `hyprctl dispatch hyprvtbsaveclose` in
    // session-exit.sh spent its whole life as a no-op). Scripts call these
    // with `hyprctl eval "hl.plugin.hyprvtb.<fn>()"`, keybinds with
    // `hl.plugin.hyprvtb.<fn>()` directly. See PORTING.md.
    if (Hl::luaConfig()) {
        HyprlandAPI::addLuaFunction(PHANDLE, "hyprvtb", "minimize_active", ::luaMinimizeActive);
        HyprlandAPI::addLuaFunction(PHANDLE, "hyprvtb", "toggle_maximize_active", ::luaToggleMaximizeActive);
        HyprlandAPI::addLuaFunction(PHANDLE, "hyprvtb", "close_active", ::luaCloseActive);
        HyprlandAPI::addLuaFunction(PHANDLE, "hyprvtb", "rollup", ::luaRollup);
        HyprlandAPI::addLuaFunction(PHANDLE, "hyprvtb", "toggle_scratch", ::luaToggleScratch);
        HyprlandAPI::addLuaFunction(PHANDLE, "hyprvtb", "cycle_hist_next", ::luaCycleHistNext);
        HyprlandAPI::addLuaFunction(PHANDLE, "hyprvtb", "cycle_hist_prev", ::luaCycleHistPrev);
        HyprlandAPI::addLuaFunction(PHANDLE, "hyprvtb", "save_session", ::luaSaveSession);
        HyprlandAPI::addLuaFunction(PHANDLE, "hyprvtb", "close_all", ::luaCloseAll);
    }

    g_pGlobalState->listeners.push_back(Event::bus()->m_events.config.reloaded.listen([] {
        if (g_pGlobalState)
            onConfigReloaded();
    }));

    // decorate windows that already exist (none when loaded at config-parse
    // time during compositor startup — the window.open listener covers those)
    //
    // HIDDEN windows count. This used to skip them, which was invisible while
    // an unloaded plugin's decorations stayed attached to their windows: a
    // minimized or rolled-up window kept its old titlebar (drawn by dead code)
    // across a `hyprctl reload` swap. Now that PLUGIN_EXIT really tears those
    // off (Hl::detachOurDecos), skipping here would leave every minimized
    // window with NO titlebar — no close button, no roll-out — for the rest of
    // the session. Unmapped ones are still skipped: addWindowDecoration
    // refuses them anyway, and the window.open listener decorates them when
    // they map.
    if (Hl::compositorReady()) {
        for (auto& w : Hl::windows()) {
            if (!w->m_isMapped)
                continue;
            onNewWindow(w, false); // already open — decorate only, don't move it
        }
    }

    // Put back the roll/minimize states PLUGIN_EXIT had to undo, if this init is
    // the other half of a hot swap. No-op (and self-cleaning) on a fresh login.
    vtbApplyHandoff();

    // Restore a saved session, but only on a fresh login (vtbRestoreSession
    // no-ops if any user window is already open — see its guard). Must run
    // AFTER the window.open listener is registered above so the relaunched
    // windows get consumed from pendingRestore as they map.
    vtbRestoreSession();

    // NOTE: deliberately NOT calling HyprlandAPI::reloadConfig() here. When
    // the plugin is loaded by hl.plugin.load() during config parsing, the
    // remainder of that same parse applies our plugin:hyprvtb:* values, and
    // scheduling a nested reload from inside a reload is exactly the kind of
    // re-entrancy that segfaulted this plugin's v2. After a manual
    // `hyprctl plugin load`, run `hyprctl reload` yourself to apply colours.

    return {"hyprvtb", "Vertical per-window titlebars (close / maximize / minimize / pin / roll-up / stacked title) + app-button column via socket + KDE-style edge resize + MRU alt-tab + session save/restore", "lam", "2.72"};
}

APICALL EXPORT void PLUGIN_EXIT() {
    // Join the IPC thread FIRST — it must be gone before this .so unloads.
    VtbIpc::stop();

    // The tick timer's callback code lives in this .so: deregister and drop it
    // before anything else so it can never fire into an unloaded image.
    if (g_pGlobalState && g_pGlobalState->tick) {
        g_pEventLoopManager->removeTimer(g_pGlobalState->tick);
        g_pGlobalState->tick.reset();
    }

    for (auto& m : Hl::monitors())
        m->m_scheduledRecalc = true;

    Hl::removePassesOfType("CVtbPassElement");

    // Hand every window back in a state the NEXT instance can work with: a
    // rolled-up window is hidden and a minimized one is parked off-screen, and
    // neither state survives the swap — the incoming .so sees a plain window
    // (or, for a hidden one, used to see nothing at all). Restore first, detach
    // second.
    //
    // Write those states down BEFORE undoing them: vtbApplyHandoff re-applies
    // them in the matching PLUGIN_INIT, so a rolled-up window stays rolled up
    // across `hyprctl reload` instead of snapping open.
    vtbSaveHandoff();

    if (g_pGlobalState) {
        for (auto& b : g_pGlobalState->bars) {
            if (b.alive())
                b->restoreForUnload();
        }
    }

    // Destroy every decoration we added, HERE, while our code is still mapped.
    // Hyprland's own unload pass cannot be trusted to do it: its removal is a
    // no-op for hidden or unmapped windows, and each one it misses leaves a
    // UP<CVtbDeco> owned by a window whose destructor will call into this .so
    // long after dlclose(). See Hl::detachOurDecos for the full autopsy — this
    // one line is what makes `hyprctl reload`'s hot swap survivable.
    Hl::detachOurDecos();

    // Destroys the event listeners with the state, so nothing can call back
    // into this image after unload.
    g_pGlobalState.reset();
}
