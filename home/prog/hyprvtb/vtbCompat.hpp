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
#include <hyprland/src/render/OpenGL.hpp>
#include <hyprland/src/render/Framebuffer.hpp>
#include <hyprland/src/managers/SeatManager.hpp>
#include <hyprland/src/managers/KeybindManager.hpp>
#include <hyprland/src/devices/IKeyboard.hpp>
#include <hyprland/src/protocols/types/DataDevice.hpp>
#include <hyprland/src/pointer/cursor/CursorShapeOverrideController.hpp>

// inputIsValid() reads InputManager::m_exclusiveLSes, which is private — the
// same #define private public trick hyprbars uses. It lives here, once, so the
// rest of the plugin neither repeats it nor touches InputManager directly.
// (Any header that pulls in InputManager.hpp normally BEFORE this one would
// silently win the include guard and break the access, so this file is the
// place to keep it.)
#define private public
#include <hyprland/src/managers/input/InputManager.hpp>
#undef private

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
        return g_pInputManager->m_currentlyHeldButtons.empty();
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
    // Hand off to one of Hyprland's own dispatchers by name (the plugin uses
    // "mouse" to enter a real move-drag, and "pin").
    inline void dispatch(const std::string& name, const std::string& arg) {
        g_pKeybindManager->m_dispatchers[name](arg);
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
