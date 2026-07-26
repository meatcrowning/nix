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

// ---------------------------------------------------------------------------
// Which Hyprland are we building against? (`top` runs the pinned 0.56.0;
// `air`/book runs Fedora Asahi's 0.55.4 rpm, and its plugin must be built
// against that — see docs/book-hyprvtb-version-bridge.md. DELETE the whole
// dual-version arrangement when Fedora ships 0.56.)
//
// There is NO Hyprland version macro to test: <hyprland/src/version.h> holds
// only GIT_* (all "unknown" in a tarball/nix/Fedora build) and *dependency*
// versions, and PluginAPI.hpp's HYPRLAND_API_VERSION has been "0.1" forever.
// The only exact signal is pkg-config's `Version:` field, which lives in the
// build system — hence two tiers:
//
//   Tier 1: VTB_HL_VERSION, injected by CMakeLists.txt from the pkg-config
//           version as MAJOR*10000 + MINOR*100 + PATCH (0.56.0 -> 5600).
//   Tier 2 (fallback, keeps this header self-sufficient for hand builds):
//           __has_include probes, biased NEW — the legacy branch is chosen
//           only on POSITIVE evidence of the pre-0.56 layout
//           (helpers/Monitor.hpp moved to output/ in 0.56 and is not coming
//           back), so an unrecognised future tree takes the 0.56 branch and
//           fails LOUDLY in this file instead of silently compiling 0.55 code.
// ---------------------------------------------------------------------------
#ifndef VTB_HL_056
  #if defined(VTB_HL_VERSION)
    #if VTB_HL_VERSION >= 5600
      #define VTB_HL_056 1
    #else
      #define VTB_HL_056 0
    #endif
  #elif __has_include(<hyprland/src/desktop/state/ViewState.hpp>)
    #define VTB_HL_056 1
  #elif __has_include(<hyprland/src/helpers/Monitor.hpp>)
    #define VTB_HL_056 0
  #else
    #define VTB_HL_056 1 // unrecognised tree: assume >= 0.56 and break loudly
  #endif
#endif

#include <hyprland/src/Compositor.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/desktop/state/FocusState.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include <hyprland/src/render/decorations/DecorationPositioner.hpp>
#include <hyprland/src/render/OpenGL.hpp>
#include <hyprland/src/render/Framebuffer.hpp>
#include <hyprland/src/managers/SeatManager.hpp>
#include <hyprland/src/managers/KeybindManager.hpp>
#include <hyprland/src/config/ConfigManager.hpp>
#include <hyprland/src/devices/IKeyboard.hpp>
#include <hyprland/src/protocols/types/DataDevice.hpp>

#if VTB_HL_056
// 0.56 pulled the window/monitor collections out of CCompositor into free
// state singletons, moved fullscreen into a controller, and moved the
// cursor-override controller under pointer/.
#include <hyprland/src/desktop/state/ViewState.hpp>   // Desktop::viewState()
#include <hyprland/src/desktop/state/WindowState.hpp> // Desktop::windowState()
#include <hyprland/src/state/MonitorState.hpp>        // State::monitorState()
#include <hyprland/src/managers/fullscreen/FullscreenController.hpp> // Fullscreen::controller()
#include <hyprland/src/pointer/cursor/CursorShapeOverrideController.hpp> // Pointer::Cursor::overrideController
#else
// 0.55.4: windows/monitors/z-order/hit-test all still hang off g_pCompositor
// (Compositor.hpp, above) and fullscreen is a CWindow member (Window.hpp,
// above). Only the cursor override controller needs a DIFFERENT include —
// same class, namespace Cursor rather than Pointer::Cursor. The two paths are
// mutually exclusive: 0.56 has no src/managers/cursor/, 0.55 no src/pointer/.
#include <hyprland/src/managers/cursor/CursorShapeOverrideController.hpp>
#endif

// Plain include: the plugin no longer needs the `#define private public`
// trick hyprbars uses. It was there for m_currentlyHeldButtons, which has a
// public accessor (hasHeldButtons(), literally `return
// !m_currentlyHeldButtons.empty()`); m_exclusiveLSes, the other member read
// here, is public already. Reaching into a class through the preprocessor is
// the most fragile access there is — an unrelated header that included
// InputManager.hpp first silently broke it — so it is worth not needing.
#include <hyprland/src/managers/input/InputManager.hpp>

// ---------------------------------------------------------------------------
// Dependency-tuple tripwire — NOT a version branch. Every hyprutils symbol the
// plugin touches is source-compatible across 0.13.1/0.14.0; what this guards
// is the ONE failure this dual-version build can produce that neither the
// compiler nor the linker will: compiling against a hyprutils GENERATION that
// does not match the Hyprland being targeted. hyprutils 0.14.0 added a
// `void* m_data` member to CUniquePointer (and get() reads it), so UP<T> is
// one pointer on 0.13.x and two on 0.14.x — and detachOurDecos() below walks
// Hyprland's std::vector<UP<IHyprWindowDecoration>> directly. A mismatched
// tuple is silent memory corruption over the compositor's own decoration
// vector. Fail the build instead. (misc/HyprAssert.hpp exists only in
// 0.14.0+ — it is what lock()'s terminate() uses — making it a reliable
// generation probe with no version macro to parse.)
// ---------------------------------------------------------------------------
#if __has_include(<hyprutils/misc/HyprAssert.hpp>)
  #define VTB_HYPRUTILS_014 1
#else
  #define VTB_HYPRUTILS_014 0
#endif
#if VTB_HL_056
static_assert(VTB_HYPRUTILS_014,
              "Hyprland 0.56 needs hyprutils >= 0.14.0 headers; 0.13.x's CUniquePointer has no m_data member and is ABI-incompatible");
#else
static_assert(!VTB_HYPRUTILS_014,
              "Hyprland 0.55.4 needs hyprutils 0.13.x headers; 0.14.0's CUniquePointer grew an m_data member and is ABI-incompatible");
#endif
static_assert(sizeof(UP<int>) == (VTB_HYPRUTILS_014 ? 2 * sizeof(void*) : sizeof(void*)),
              "hyprutils CUniquePointer layout does not match the detected generation — "
              "the pkg-config search path is resolving a different hyprutils than the Hyprland it targets");

// Call sites say Hl::something() — see the alias at the bottom of this file.
namespace Vtb::Hl {

    // ---- window geometry ---------------------------------------------------
    //
    // Position/size live in animated variables. `value()` is where the window
    // is being drawn this frame, `goal()` is where it is headed (== value once
    // settled); the plugin reads goal for anything it persists or measures
    // against, and value for anything it draws next to.

    // 0.56 moved the two PHLANIMVAR<Vector2D>s off CWindow into the protected
    // section of CGeometricMovableAnimated and exposed them via
    // positionAnimation()/sizeAnimation() — plain identity getters. On 0.55.4
    // they are still public members m_realPosition/m_realSize on CWindow, and
    // the pointee (hyprutils CGenericAnimatedVariable) is identical, so the
    // whole difference is the spelling of the accessor. Returned by reference:
    // the member is a UP<>, which cannot be copied.
#if VTB_HL_056
    inline PHLANIMVAR<Vector2D>& posAnim(PHLWINDOW w) {
        return w->positionAnimation();
    }
    inline PHLANIMVAR<Vector2D>& sizeAnim(PHLWINDOW w) {
        return w->sizeAnimation();
    }
#else
    inline PHLANIMVAR<Vector2D>& posAnim(PHLWINDOW w) {
        return w->m_realPosition;
    }
    inline PHLANIMVAR<Vector2D>& sizeAnim(PHLWINDOW w) {
        return w->m_realSize;
    }
#endif

    inline Vector2D posValue(PHLWINDOW w) {
        return posAnim(w)->value();
    }
    inline Vector2D sizeValue(PHLWINDOW w) {
        return sizeAnim(w)->value();
    }
    inline Vector2D posGoal(PHLWINDOW w) {
        return posAnim(w)->goal();
    }
    inline Vector2D sizeGoal(PHLWINDOW w) {
        return sizeAnim(w)->goal();
    }
    inline CBox boxValue(PHLWINDOW w) {
        return {posValue(w), sizeValue(w)};
    }
    inline CBox boxGoal(PHLWINDOW w) {
        return {posGoal(w), sizeGoal(w)};
    }

    // Jump straight to a position/size with no animation.
    inline void warpPos(PHLWINDOW w, const Vector2D& p) {
        posAnim(w)->setValueAndWarp(p);
    }
    // Land the window on its goal immediately — kills a residual animation tail.
    inline void warpToGoal(PHLWINDOW w) {
        posAnim(w)->setValueAndWarp(posAnim(w)->goal());
        sizeAnim(w)->setValueAndWarp(sizeAnim(w)->goal());
    }

    // ---- window set / z-order / hit testing / focus ------------------------

    // Is the compositor up at all? PLUGIN_INIT can run at config-parse time,
    // before it exists.
    inline bool compositorReady() {
        return (bool)g_pCompositor;
    }
    inline const std::vector<PHLWINDOW>& windows() {
#if VTB_HL_056
        return Desktop::viewState()->windows();
#else
        // 0.55.4: the same z-ordered vector, straight off the compositor.
        // 0.56's viewState() is a function-local static and can never be null;
        // g_pCompositor can (config-parse time), so keep this wrapper as total
        // as the 0.56 one. NB on 0.55 a fading-out (closing) window stays in
        // this vector until removed; the m_isMapped guards at the call sites
        // already cover that.
        static const std::vector<PHLWINDOW> EMPTY;
        return g_pCompositor ? g_pCompositor->m_windows : EMPTY;
#endif
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
    // 0.56's raise/lower (CWindowState::moveToZ) is the line-for-line
    // descendant of 0.55's changeWindowZOrder — same validMapped bail, same
    // fullscreen-input update, same X11 transient-stack walk. One rename
    // inside: 0.55 sets m_createdOverFullscreen (default false) where 0.56
    // sets m_allowedOverFullscreen (default true) — Hyprland policy, nothing
    // in this plugin reads either.
    inline void raise(PHLWINDOW w) {
#if VTB_HL_056
        Desktop::windowState()->raise(w);
#else
        g_pCompositor->changeWindowZOrder(w, true);
#endif
    }
    inline void lower(PHLWINDOW w) {
#if VTB_HL_056
        Desktop::windowState()->lower(w);
#else
        g_pCompositor->changeWindowZOrder(w, false);
#endif
    }
    inline PHLWINDOW windowAt(const Vector2D& pos, uint16_t properties) {
#if VTB_HL_056
        return Desktop::viewState()->hitTest().windowAt(pos, properties);
#else
        // Same parameter list incl. the defaulted ignoreWindow.
        return g_pCompositor->vectorToWindowUnified(pos, properties);
#endif
    }
    // The property set every hit test in this plugin uses: a window's reserved
    // + input extents, floating windows included.
    inline PHLWINDOW windowAtCursorProps(const Vector2D& pos) {
        return windowAt(pos, Desktop::View::RESERVED_EXTENTS | Desktop::View::INPUT_EXTENTS | Desktop::View::ALLOW_FLOATING);
    }
    inline SP<CWLSurfaceResource> layerSurfaceAt(const Vector2D& pos, std::vector<PHLLSREF>* layers, Vector2D* surfaceCoords, PHLLS* layerFound) {
#if VTB_HL_056
        return Desktop::viewState()->hitTest().layerSurfaceAt(pos, layers, surfaceCoords, layerFound);
#else
        // Byte-for-byte the same body upstream, same trailing
        // `aboveLockscreen = false` default.
        return g_pCompositor->vectorToLayerSurface(pos, layers, surfaceCoords, layerFound);
#endif
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
#if VTB_HL_056
        return Fullscreen::controller()->isFullscreen(w);
#else
        // 0.55.4: no controller — the flag lives on the window, and
        // CWindow::isFullscreen() is the exact predicate 0.56's handler
        // evaluates for a mode-less query (internal != FSMODE_NONE). The null
        // guard reproduces the 0.56 controller's own early return, which the
        // call sites rely on — do not "simplify" it away.
        return w && w->isFullscreen();
#endif
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
#if VTB_HL_056
        return State::monitorState()->monitors();
#else
        // Enabled monitors (0.56's monitors() vs allMonitors() split matches
        // 0.55's m_monitors vs m_realMonitors). Same null-guard rationale as
        // windows().
        static const std::vector<PHLMONITOR> EMPTY;
        return g_pCompositor ? g_pCompositor->m_monitors : EMPTY;
#endif
    }
    inline PHLMONITOR monitorAt(const Vector2D& v) {
#if VTB_HL_056
        return State::monitorState()->query().vec(v).run();
#else
        // A vec-only query short-circuits to closestTo(v) upstream, which is
        // the same contains-point-then-nearest algorithm as this.
        return g_pCompositor->getMonitorFromVector(v);
#endif
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
    // The override controller is the identical class on both versions (the
    // headers differ only in the namespace-opening line); 0.56 nested Cursor
    // inside a new Pointer namespace. Alias it once inside OUR namespace —
    // never inject into theirs — and keep single wrapper bodies.
#if VTB_HL_056
    namespace VtbCursor = ::Pointer::Cursor;
#else
    namespace VtbCursor = ::Cursor;
#endif
    inline void setCursorOverride(const std::string& shape) {
        VtbCursor::overrideController->setOverride(shape, VtbCursor::CURSOR_OVERRIDE_WINDOW_EDGE);
    }
    inline void clearCursorOverride() {
        VtbCursor::overrideController->unsetOverride(VtbCursor::CURSOR_OVERRIDE_WINDOW_EDGE);
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
    //
    // 0.56 hands back a FRESH, caller-owned FB per call. 0.55.4 has no such
    // call: makeSnapshot() is void and renders into a FB the WINDOW owns and
    // caches (CWindow::m_snapshotFB) — and the compositor is a second writer
    // to that same FB (CWindow::onUnmap re-snapshots into it). Reproduce
    // 0.56's contract by DETACHING: clear the slot first (so makeSnapshot
    // must allocate a new FB + texture rather than re-render into one we may
    // still be drawing — alloc() early-returns on same size and would reuse
    // the texture), snapshot, take sole ownership, clear the slot again so
    // the compositor's own unmap snapshot can never touch our copy.
    //
    // The isHidden() guard: inside makeSnapshot, renderWindow bails on a
    // hidden window AFTER the FB was cleared, which would hand back a fully
    // transparent snapshot. Returning nullptr instead keeps the callers'
    // last-good texture (they already handle a failed snapshot).
    inline SP<Render::IFramebuffer> snapshotFB(PHLWINDOW w) {
#if VTB_HL_056
        return g_pHyprRenderer->makeSnapshotFB(w);
#else
        if (!w || w->isHidden())
            return nullptr;
        w->m_snapshotFB.reset();
        g_pHyprRenderer->makeSnapshot(w);
        auto fb = w->m_snapshotFB;
        w->m_snapshotFB.reset();
        return (fb && fb->isAllocated() && fb->getTexture()) ? fb : nullptr;
#endif
    }

    // Release an offscreen framebuffer safely MID-FRAME, then drop the ref.
    // 0.56's CGLFramebuffer::release() rebinds the renderer's previously
    // bound FB afterwards — added upstream precisely for a plugin releasing
    // from inside a pass element. 0.55's binds FB 0 and walks away, and the
    // pass loop never rebinds between elements, so every later draw in that
    // frame would land in the default framebuffer (one corrupt frame at the
    // end of every open/close fade). On 0.55, put the pass's target back
    // ourselves.
    inline void releaseFB(SP<Render::IFramebuffer>& fb) {
        if (!fb)
            return;
        fb->release();
#if !VTB_HL_056
        if (g_pHyprRenderer->m_renderData.currentFB)
            g_pHyprRenderer->m_renderData.currentFB->bind();
#endif
        fb.reset();
    }

}

// Short alias: the seam is called on nearly every other line of vtbDeco.cpp,
// and `Hl::` keeps those call sites as readable as the raw globals were.
namespace Hl = Vtb::Hl;
