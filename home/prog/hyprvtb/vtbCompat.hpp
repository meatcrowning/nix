#pragma once

#define WLR_USE_UNSTABLE

// The ONLY file in this plugin permitted to name a volatile Hyprland internal.
//
// hyprvtb uses six HyprlandAPI:: entries and ~forty *internal* Hyprland
// headers, so upstream's "no breaking changes" promise — which covers the
// plugin API — buys nothing here. Every compositor bump relocates a handful of
// symbols (g_pCompositor->m_windows -> Desktop::viewState()->windows(),
// w->m_realPosition -> w->positionAnimation(), …), and because those handfuls
// sat at ~180 call sites across vtbDeco.cpp and main.cpp, a ten-symbol port
// turned into a sprawling diff every time.
//
// So: everything else calls through here. When a bump breaks the build, it
// breaks in THIS FILE and nowhere else, and the port is a ~40-line diff. A
// checkPhase grep in default.nix enforces the seam; PORTING.md documents the
// bump ritual. NOTE the seam only contains *compile-time* churn (Axis A) —
// hyprutils semantics changes (Axis B) compile fine and need the type-level
// guard instead (CDecoRef in globals.hpp).
//
// Everything here is a thin inline forwarder: no policy, no state, no
// behaviour of its own — with two deliberate exceptions, both marked GUARD
// below, which drop degenerate (zero-area) boxes before they reach Hyprland.
// Hyprland ABORTS the whole compositor on a zero-size render rect (this took
// the session down in v2.45, from a music player paused at 0:00 feeding the
// vtb socket a zero-height playbar), so the guard belongs at the seam where
// every computed rect passes through, not at each of the 36 call sites.

#include <hyprland/src/Compositor.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/desktop/state/ViewState.hpp>
#include <hyprland/src/desktop/state/WindowState.hpp>
#include <hyprland/src/desktop/state/FocusState.hpp>
#include <hyprland/src/managers/fullscreen/FullscreenController.hpp>
#include <hyprland/src/state/MonitorState.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include <hyprland/src/render/decorations/DecorationPositioner.hpp>
#include <hyprland/src/render/OpenGL.hpp>
#include <hyprland/src/render/Framebuffer.hpp>
#include <hyprland/src/managers/SeatManager.hpp>
#include <hyprland/src/managers/KeybindManager.hpp>
#include <hyprland/src/config/ConfigManager.hpp>
#include <hyprland/src/devices/IKeyboard.hpp>
#include <hyprland/src/protocols/types/DataDevice.hpp>
#include <hyprland/src/pointer/cursor/CursorShapeOverrideController.hpp>

// Plain include: the plugin no longer needs the `#define private public`
// trick hyprbars uses. It was there for m_currentlyHeldButtons, which has a
// public accessor (hasHeldButtons(), literally `return
// !m_currentlyHeldButtons.empty()`); m_exclusiveLSes, the other member read
// here, is public already. Reaching into a class through the preprocessor is
// the most fragile access there is — an unrelated header that included
// InputManager.hpp first silently broke it — so it is worth not needing.
#include <hyprland/src/managers/input/InputManager.hpp>

// Call sites say Hl::something() — see the alias at the bottom of this file.
namespace Vtb::Hl {

    // ---- window geometry ---------------------------------------------------
    //
    // Position/size live in animated variables. `value()` is where the window
    // is being drawn this frame, `goal()` is where it is headed (== value once
    // settled); the plugin reads goal for anything it persists or measures
    // against, and value for anything it draws next to.

    inline Vector2D posValue(PHLWINDOW w) {
        return w->positionAnimation()->value();
    }
    inline Vector2D sizeValue(PHLWINDOW w) {
        return w->sizeAnimation()->value();
    }
    inline Vector2D posGoal(PHLWINDOW w) {
        return w->positionAnimation()->goal();
    }
    inline Vector2D sizeGoal(PHLWINDOW w) {
        return w->sizeAnimation()->goal();
    }
    inline CBox boxValue(PHLWINDOW w) {
        return {posValue(w), sizeValue(w)};
    }
    inline CBox boxGoal(PHLWINDOW w) {
        return {posGoal(w), sizeGoal(w)};
    }

    // Jump straight to a position/size with no animation.
    inline void warpPos(PHLWINDOW w, const Vector2D& p) {
        w->positionAnimation()->setValueAndWarp(p);
    }
    // Land the window on its goal immediately — kills a residual animation tail.
    inline void warpToGoal(PHLWINDOW w) {
        w->positionAnimation()->setValueAndWarp(w->positionAnimation()->goal());
        w->sizeAnimation()->setValueAndWarp(w->sizeAnimation()->goal());
    }

    // ---- window set / z-order / hit testing / focus ------------------------

    // Is the compositor up at all? PLUGIN_INIT can run at config-parse time,
    // before it exists.
    inline bool compositorReady() {
        return (bool)g_pCompositor;
    }
    inline const std::vector<PHLWINDOW>& windows() {
        return Desktop::viewState()->windows();
    }

    // Rip THIS plugin's decorations off every window, right now, destroying
    // them here rather than leaving that to the window.
    //
    // The obvious call — HyprlandAPI::removeWindowDecoration, which the plugin
    // system itself runs for every registered deco on unload — is not enough:
    // it lands in CWindow::removeWindowDeco, which only QUEUES the deco in
    // m_decosToRemove and then calls updateWindowDecos(), and that early-returns
    // on `!m_isMapped || isHidden()`. A window that is hidden (this plugin hides
    // every rolled-up / minimized one) or not yet mapped therefore keeps holding
    // a UP<> to a decoration whose vtable and destructor live in a .so that
    // dlclose() is about to unmap. The window dies later, ~CWindow destroys that
    // pointer, and the compositor SIGSEGVs into freed memory under
    // CWindow::destroyWindow — the "hot swap worked, then the session died at
    // the next window close" crash (2026-07-25).
    //
    // So do the erase ourselves, unconditionally, uncaching from the positioner
    // exactly like updateWindowDecos would. Hyprland's own removeWindowDecoration
    // pass afterwards finds nothing to match and returns false, which is fine —
    // it compares raw pointers and never dereferences them.
    inline void detachOurDecos() {
        for (const auto& w : windows()) {
            if (!w)
                continue;
            std::erase_if(w->m_windowDecorations, [](const UP<IHyprWindowDecoration>& d) {
                if (!d)
                    return false;
                const auto NAME = d->getDisplayName();
                if (NAME != "Hyprvtb" && NAME != "HyprvtbShadow")
                    return false;
                g_pDecorationPositioner->uncacheDecoration(d.get());
                return true;
            });
        }
    }
    inline void raise(PHLWINDOW w) {
        Desktop::windowState()->raise(w);
    }
    inline void lower(PHLWINDOW w) {
        Desktop::windowState()->lower(w);
    }
    inline PHLWINDOW windowAt(const Vector2D& pos, uint16_t properties) {
        return Desktop::viewState()->hitTest().windowAt(pos, properties);
    }
    // The property set every hit test in this plugin uses: a window's reserved
    // + input extents, floating windows included.
    inline PHLWINDOW windowAtCursorProps(const Vector2D& pos) {
        return windowAt(pos, Desktop::View::RESERVED_EXTENTS | Desktop::View::INPUT_EXTENTS | Desktop::View::ALLOW_FLOATING);
    }
    inline SP<CWLSurfaceResource> layerSurfaceAt(const Vector2D& pos, std::vector<PHLLSREF>* layers, Vector2D* surfaceCoords, PHLLS* layerFound) {
        return Desktop::viewState()->hitTest().layerSurfaceAt(pos, layers, surfaceCoords, layerFound);
    }
    // A monitor's layer-surface array for one zwlr layer — a raw read of a
    // monitor member, kept here with the hit test it always feeds.
    inline std::vector<PHLLSREF>* monitorLayer(PHLMONITOR m, uint32_t zwlrLayer) {
        return &m->m_layerSurfaceLayers[zwlrLayer];
    }

    inline PHLWINDOW focusedWindow() {
        return Desktop::focusState()->window();
    }
    inline PHLMONITOR focusedMonitor() {
        return Desktop::focusState()->monitor();
    }
    inline void focusWindow(PHLWINDOW w) {
        Desktop::focusState()->fullWindowFocus(w, Desktop::FOCUS_REASON_CLICK);
    }
    inline void resetFocus() {
        Desktop::focusState()->resetWindowFocus();
    }
    inline bool isFullscreen(PHLWINDOW w) {
        return Fullscreen::controller()->isFullscreen(w);
    }

    // Is the compositor running a Lua config (as opposed to the old
    // hyprland.conf parser)? Only then are plugin Lua functions reachable.
    //
    // This one is here because a dry run of the next bump found it (see
    // PORTING.md, "Does the seam actually hold?"): upstream main has already
    // deleted CONFIG_LEGACY — CONFIG_LUA is the only member left — and the
    // check was sitting in main.cpp, outside the seam.
    //
    // Phrased as "is it Lua?" rather than "is it not LEGACY?" on purpose:
    // CONFIG_LUA is the member that survives, so this exact line compiles on
    // 0.56 (LEGACY | LUA) and on versions that have dropped LEGACY, with no
    // version gate. Same meaning either way. (`requires { Config::CONFIG_LEGACY; }`
    // does NOT work for this — a missing name in a non-dependent scope is a
    // hard error, not a failed constraint.)
    inline bool luaConfig() {
        return Config::mgr()->type() == Config::CONFIG_LUA;
    }

    // ---- monitors ----------------------------------------------------------

    inline const std::vector<PHLMONITOR>& monitors() {
        return State::monitorState()->monitors();
    }
    inline PHLMONITOR monitorAt(const Vector2D& v) {
        return State::monitorState()->query().vec(v).run();
    }

    // ---- input / seat ------------------------------------------------------

    inline Vector2D mouse() {
        return g_pInputManager->getMouseCoordsInternal();
    }
    // No mouse button is currently down anywhere — the plugin only re-evaluates
    // resize-edge hover when the user isn't already dragging something.
    inline bool noButtonsHeld() {
        return !g_pInputManager->hasHeldButtons();
    }
    // An exclusive-focus layer surface (a lock screen, a fullscreen launcher)
    // owns all input: the titlebars must not react at all while one is up.
    inline bool inputExclusive() {
        return !g_pInputManager->m_exclusiveLSes.empty();
    }
    inline SP<IKeyboard> keyboard() {
        return g_pSeatManager->m_keyboard.lock();
    }
    inline SP<IDataSource> selectionSource() {
        return g_pSeatManager->m_selection.currentSelection.lock();
    }
    // True when an active seat grab (a client-side popup grab, e.g. an open
    // menu) refuses events for this surface — the titlebar must stay inert.
    inline bool seatGrabRejects(SP<CWLSurfaceResource> surface) {
        return g_pSeatManager->m_seatGrab && !g_pSeatManager->m_seatGrab->accepts(surface);
    }
    inline void mouseBindMode(eMouseBindMode mode) {
        g_pKeybindManager->changeMouseBindMode(mode);
    }
    inline void setCursorOverride(const std::string& shape) {
        Pointer::Cursor::overrideController->setOverride(shape, Pointer::Cursor::CURSOR_OVERRIDE_WINDOW_EDGE);
    }
    inline void clearCursorOverride() {
        Pointer::Cursor::overrideController->unsetOverride(Pointer::Cursor::CURSOR_OVERRIDE_WINDOW_EDGE);
    }

    // ---- rendering ---------------------------------------------------------

    // A box that Hyprland must never be handed: renderRect asserts on a
    // zero-area box and takes the compositor with it. Nothing is visible in
    // one either, so dropping it is invisible as well as safe.
    inline bool degenerate(const CBox& b) {
        return !(b.w > 0 && b.h > 0);
    }

    inline void damage(const CBox& b) {
        if (degenerate(b)) // GUARD (see file header)
            return;
        g_pHyprRenderer->damageBox(b);
    }
    inline void rect(const CBox& box, const CHyprColor& col, Render::GL::CHyprOpenGLImpl::SRectRenderData data = {}) {
        if (degenerate(box)) // GUARD (see file header)
            return;
        Render::GL::g_pHyprOpenGL->renderRect(box, col, data);
    }
    inline void texture(SP<Render::ITexture> tex, const CBox& box, Render::GL::CHyprOpenGLImpl::STextureRenderData data = {}) {
        if (!tex || degenerate(box)) // GUARD (see file header)
            return;
        Render::GL::g_pHyprOpenGL->renderTexture(tex, box, data);
    }

    // The monitor currently being rendered, and its damage region. Only valid
    // inside a render stage.
    inline PHLMONITOR renderMonitor() {
        return g_pHyprRenderer->m_renderData.pMonitor.lock();
    }
    inline CRegion renderDamage() {
        return g_pHyprRenderer->m_renderData.damage.copy();
    }

    // Pass elements are the sanctioned way into the render pipeline; the
    // pass list itself is a renderer member, so it is reached through here.
    inline void addPass(UP<IPassElement>&& element) {
        g_pHyprRenderer->m_renderPass.add(std::move(element));
    }
    inline void removePassesOfType(const std::string& type) {
        g_pHyprRenderer->m_renderPass.removeAllOfType(type);
    }

    // Texture / text / framebuffer helpers off the renderer.
    inline SP<Render::ITexture> textureFromCairo(cairo_surface_t* surface) {
        return g_pHyprRenderer->createTexture(surface);
    }
    inline SP<Render::ITexture> renderText(const std::string& text, const CHyprColor& col, int size, bool italic, const std::string& font, int maxWidth) {
        return g_pHyprRenderer->renderText(text, col, size, italic, font, maxWidth);
    }
    inline SP<Render::IFramebuffer> createFB(const std::string& name) {
        return g_pHyprRenderer->createFB(name);
    }
    inline auto bindTempFB(SP<Render::IFramebuffer> fb) {
        return g_pHyprRenderer->bindTempFB(fb);
    }

    // Position of the monitor currently being rendered — pass elements report
    // their bounding box in monitor-local coordinates.
    inline Vector2D renderMonitorPos() {
        return g_pHyprRenderer->m_renderData.pMonitor->m_position;
    }

    // Snapshot a window into a framebuffer — used to keep drawing a window
    // that has been hidden (roll-up / close animations).
    inline SP<Render::IFramebuffer> snapshotFB(PHLWINDOW w) {
        return g_pHyprRenderer->makeSnapshotFB(w);
    }

}

// Short alias: the seam is called on nearly every other line of vtbDeco.cpp,
// and `Hl::` keeps those call sites as readable as the raw globals were.
namespace Hl = Vtb::Hl;
