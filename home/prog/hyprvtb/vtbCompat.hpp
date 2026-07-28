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
#include <hyprland/src/desktop/view/View.hpp>
#include <hyprland/src/desktop/view/LayerSurface.hpp>
#include <hyprland/src/desktop/state/FocusState.hpp>
#include <hyprland/src/layout/target/Target.hpp>
#include <hyprland/src/render/Renderer.hpp>
#include <hyprland/src/render/decorations/DecorationPositioner.hpp>
#include <hyprland/src/render/OpenGL.hpp>
#include <hyprland/src/render/Framebuffer.hpp>
#include <hyprland/src/managers/SeatManager.hpp>
#include <hyprland/src/managers/KeybindManager.hpp>
#include <hyprland/src/managers/eventLoop/EventLoopManager.hpp>
#include <hyprland/src/managers/eventLoop/EventLoopTimer.hpp>
#include <hyprland/src/config/ConfigManager.hpp>
#include <hyprland/src/devices/IKeyboard.hpp>
#include <hyprland/src/devices/IPointer.hpp>
#include <hyprland/src/protocols/types/DataDevice.hpp>
#include <hyprland/src/debug/log/Logger.hpp>

// Aquamarine, for the one question only the backend can answer: is this output
// headless (see Hl::headlessMonitor below)? Hyprland's own Monitor.hpp already
// pulls in <aquamarine/output/Output.hpp>; Backend.hpp is what carries the
// eBackendType enum, and it is not transitively included.
#include <aquamarine/backend/Backend.hpp>

#include <algorithm>
#include <cmath>

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
    // Where the LAYOUT thinks the window is — the box a native drag seeds
    // itself from. Normally identical to posGoal(); they diverge exactly when
    // something warped the animation without telling the layout, which is the
    // bug warpPosLogical() below exists to prevent.
    inline Vector2D posLogical(PHLWINDOW w) {
        const auto TARGET = w->layoutTarget();
        return TARGET ? TARGET->position().pos() : posGoal(w);
    }

    // Move a window and tell the LAYOUT about it. Use this, not warpPos(), for
    // any relocation the plugin performs outside a native drag.
    //
    // warpPos() writes only the animated variable (value + goal). The layout
    // target keeps its OWN logical box (ITarget::m_box.logicalBox), and that is
    // the authoritative position: CDragStateController::updateDragWindow seeds
    // m_beginDragPositionXY from `DRAGGINGTARGET->position()`, i.e. the logical
    // box, and every subsequent motion sets `logical + DELTA`. So a window the
    // plugin moved by warping alone LOOKS moved but is still filed at its old
    // spot — and the first frame of the next native drag teleports it back
    // there. That is the "drag a rolled-up bar, unroll it, drag it: the window
    // jumps" bug (fixed 2.84); an older comment here claimed setValueAndWarp
    // kept the logical position in sync, which was true of the pre-0.55 layout
    // and is not true of the target-based one.
    //
    // Route through the target the same way updateEdgeResize does
    // (setPositionGlobal + warpPositionSize: instant, no rubber-banding). Size
    // is carried through unchanged. Falls back to a plain warp if the window
    // has no target — nothing else can be done then, and a visibly-stuck window
    // would be worse than a stale logical box.
    inline void warpPosLogical(PHLWINDOW w, const Vector2D& p) {
        const auto TARGET = w->layoutTarget();
        if (!TARGET) {
            posAnim(w)->setValueAndWarp(p);
            return;
        }
        TARGET->setPositionGlobal(CBox{p, sizeGoal(w)});
        TARGET->warpPositionSize();
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
    // Is this an output NOBODY CAN LOOK AT? `tools/sandbox.sh` creates an
    // off-screen monitor with `hyprctl output create headless` and launches
    // agent test windows onto it, so anything that walks the window list has to
    // be able to tell those apart from the user's own (see
    // home/prog/AGENTS.md, "the promise is nothing of the agent's reaches his
    // screen"). The panel has to infer it — no hardware identity, i.e. zero
    // physical size and no make/model/serial/description — because all it has
    // is `hyprctl -j monitors`. The compositor does not have to infer anything:
    // Aquamarine knows which backend created the output, and a headless one
    // says so. Available on BOTH pins (aquamarine 0.13.0 on top, 0.9.x on
    // book — `IOutput::getBackend()` and `AQ_BACKEND_HEADLESS` are present and
    // identically spelled in both).
    //
    // The hardware-identity test survives as the fallback for the one case the
    // honest question cannot answer: a monitor with no `m_output` at all (a
    // half-torn-down output), where there is no backend to ask.
    inline bool headlessMonitor(PHLMONITOR m) {
        if (!m)
            return false; // no monitor is not the same claim as "invisible"
        if (m->m_output) {
            if (const auto BACKEND = m->m_output->getBackend())
                return BACKEND->type() == Aquamarine::AQ_BACKEND_HEADLESS;
            const auto& O = m->m_output;
            return O->physicalSize == Vector2D{} && O->make.empty() && O->model.empty() && O->serial.empty() &&
                O->description.empty();
        }
        return m->m_description.empty() && m->m_shortDescription.empty();
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

    // ---- input / seat: momentum synthesis (kinetic scroll, added 2.78) ------
    //
    // vtbKinetic keeps emitting decaying axis events after the finger leaves the
    // trackpad. Everything it needs from the compositor passes through here.
    //
    // The whole block is pin-identical — `SeatManager.hpp` differs between the
    // pins ONLY at `nextSerial` and below (:77 gained a `bool enter = false`
    // parameter, plus three pointer-serial methods that exist on the top pin
    // alone), and nothing here goes near any of them. An axis event carries no
    // serial, so there is no reason to.
    //
    // NOTE the delivery model, because it shapes the whole module:
    // sendPointerAxis takes NO surface argument — it always sends to whatever
    // `m_state.pointerFocus` currently is. A fling therefore cannot be latched
    // to its original target; it can only be validated against it and dropped
    // when focus moves.

    // A synthetic axis value that must never reach the wire, and the reason the
    // module counts every refusal instead of shrugging at it.
    //
    // This is the degenerate-rect lesson transposed to the protocol. Two values
    // are load-bearing rather than merely odd:
    //   * 0.0  — `SeatManager.cpp` (:367-368 air / :439-440 top) turns a
    //            zero-value send on a non-WHEEL source into `wl_pointer.axis_stop`.
    //            So a rounding artefact mid-tail does not drop a frame, it ENDS
    //            the client's scroll sequence — which is precisely the signal
    //            every client-side fling estimator waits for. The one legal zero
    //            goes through sendAxisStop() below, and nowhere else.
    //   * NaN/inf — nothing upstream guards them: `Seat.cpp:242-250` checks only
    //            the surface and the caps, then calls `wl_fixed_from_double`,
    //            a union bit-trick that yields an arbitrary int32.
    // The magnitude clamp is the third: `wl_fixed_t` is 24.8 signed, so |value|
    // above 8388607 wraps and the content jumps BACKWARDS. 4000 px in one tick
    // is already far past anything the physics can produce (a 6000 px/s cap at
    // 60 Hz is 100 px), so the clamp only ever catches a bug.
    inline constexpr double AXIS_VALUE_MAX = 4000.0;

    // Emit one synthetic axis event. Returns false if the value was REFUSED —
    // callers count that; it must stay at zero (the wire-level equivalent of
    // "we never handed Hyprland a zero-area box").
    //
    // discrete/value120 are passed through for signature fidelity with
    // CInputManager::onMouseWheel's own call, but the module always passes 0/0:
    // `sendPointerAxis` skips that whole branch for a non-WHEEL source anyway,
    // and wayland.xml says value120 "must not be zero" — sending detents is what
    // would knock a client out of smooth/pixel mode. SeatManager.hpp:64-65,
    // character-identical on both pins.
    [[nodiscard]] inline bool sendAxis(uint32_t timeMs, wl_pointer_axis axis, double value, int32_t discrete, int32_t value120, wl_pointer_axis_source source,
                                       wl_pointer_axis_relative_direction relative) {
        if (!std::isfinite(value) || value == 0.0) // GUARD (see above)
            return false;
        g_pSeatManager->sendPointerAxis(timeMs, axis, std::clamp(value, -AXIS_VALUE_MAX, AXIS_VALUE_MAX), discrete, value120, source, relative);
        return true;
    }

    // The terminal `wl_pointer.axis_stop`, and the ONLY sanctioned zero send.
    // Named separately from sendAxis because it is a protocol OBLIGATION, not an
    // optimisation: a client left without it believes the scroll sequence is
    // still open forever (Qt keeps `scrollingPhase` true, GTK keeps `scroll->active`).
    inline void sendAxisStop(uint32_t timeMs, wl_pointer_axis axis, wl_pointer_axis_source source, wl_pointer_axis_relative_direction relative) {
        g_pSeatManager->sendPointerAxis(timeMs, axis, 0.0, 0, 0, source, relative);
    }

    // MANDATORY once per tick, and the reason the module cannot use
    // CInputManager::onMouseWheel: for FINGER/CONTINUOUS that function sets
    // `m_pointerAxisFramePending` and defers the frame to a real device frame
    // event, which a timer does not have — the client would buffer the axis
    // forever, and the flag is private. SeatManager.hpp:62 both pins.
    inline void sendPointerFrame() {
        g_pSeatManager->sendPointerFrame();
    }

    // Who the seat is currently sending pointer events to. SeatManager.hpp:89
    // (air) / :92 (top) — same member, line numbers only.
    inline SP<CWLSurfaceResource> pointerFocusSurface() {
        return g_pSeatManager->m_state.pointerFocus.lock();
    }
    // Momentum must die when focus moves — see the delivery-model note above.
    // SeatManager.hpp:105 (air) / :108 (top), CSignalT<> on both.
    inline Hyprutils::Signal::CHyprSignalListener listenPointerFocusChange(std::function<void()> fn) {
        return g_pSeatManager->m_events.pointerFocusChange.listen(std::move(fn));
    }

    // The pointer is over a layer surface (panel / lock screen / launcher).
    // A blanket "no momentum there" is what keeps the Quickshell bar's volume
    // and brightness sliders precise — they act per EVENT, so a coast would fire
    // dozens of wpctl spawns. InputManager.hpp:199 (air) / :202 (top), public.
    inline bool pointerOnLayerSurface() {
        return g_pInputManager->m_lastFocusOnLS;
    }
    // A game has grabbed/locked the pointer. InputManager.hpp:117 / :119.
    inline bool pointerConstrained() {
        return g_pInputManager->isConstrained();
    }
    // Every pointer device. The module needs the list for two things the event
    // bus cannot give it: hold-gesture signals (the bus has swipe and pinch but
    // NO hold on either pin) and the per-device scroll factor (the axis signal
    // carries no device). InputManager.hpp:162 (air) / :165 (top), public —
    // `private:` starts at :216 / :219.
    inline const std::vector<SP<IPointer>>& pointers() {
        return g_pInputManager->m_pointers;
    }
    // Proxy for "the seat still advertises a pointer capability".
    //
    // The real read — `PROTO::seat->m_currentCaps & HID_INPUT_CAPABILITY_POINTER`,
    // the gate every CWLPointerResource::sendAxis* silently bails on
    // (Seat.cpp:246-247 …) — is UNREACHABLE from a plugin, twice over:
    // `m_currentCaps` is private with a fixed friend list (Seat.hpp:196), and no
    // `PROTO::` symbol is exported by the compositor binary at all (`nm -D`
    // on both pins: zero matches), so naming `PROTO::seat` would bind to this
    // .so's own null UP and dereference it. This is the observable half of the
    // same condition — the caps are derived from the device list — and it costs
    // one comparison.
    inline bool anyPointerDevice() {
        return !g_pInputManager->m_pointers.empty();
    }
    // Modifier bits held down on ANY keyboard, in HL_MODIFIER_* space
    // (IKeyboard.hpp:14-21, byte-identical on both pins; the same mask
    // IKeyboard.cpp:357 hands to the keybind matcher).
    //
    // Deliberately NOT `g_pSeatManager->m_keyboard`, which is only the keyboard
    // that most recently produced an event: hold Ctrl on one keyboard, type on
    // another, and that read comes back clean while Ctrl is very much down. This
    // is the OR across all of them, which is also what Hyprland's own keybind
    // matching uses. InputManager.hpp:189 (air) / :192 (top), public on both.
    inline uint32_t modsAllKeyboards() {
        return g_pInputManager->getModsFromAllKBs();
    }

    // Surface -> view -> window/layer-surface. Pin-identical, so NO version arm:
    // going through the view indirection sidesteps the one place the two trees
    // really differ (0.55's g_pCompositor->getWindowFromSurface vs 0.56's
    // Desktop::viewState()->query()…runWindow()). WLSurface.hpp:79 (air) / :76
    // (top) for fromResource, :43 / :45 for view(), Window.hpp:120 and
    // LayerSurface.hpp:18 for fromView on both.
    //
    // NOTE what these do NOT do: resolve a subsurface or popup surface to the
    // toplevel that owns it. Neither pin offers that, which is worth writing
    // down because both of the calls that look like they would are in fact this
    // same expression — air's `CCompositor::getWindowFromSurface`
    // (Compositor.cpp:1242-1252) is `view()` plus a type check that REFUSES any
    // non-WINDOW view, and top's `viewState()->query().type(VIEW_TYPE_WINDOW)
    // .surface(s).runWindow()` gates its only tree walk (`layerBySurface`) on
    // the type being LAYER_SURFACE (ViewQuery.cpp:248-260, :288-290). The owner
    // refs that would answer it — `CSubsurface::m_windowParent`,
    // `CPopup::m_windowOwner` — are private on both pins. So a caller that
    // needs the OWNING window of an arbitrary focus surface must get it from
    // the cursor hit test (windowAtCursorProps) instead; see the classification
    // in vtbKinetic's startGate.
    inline SP<Desktop::View::IView> viewOf(SP<CWLSurfaceResource> surf) {
        if (!surf)
            return nullptr;
        const auto WLS = Desktop::View::CWLSurface::fromResource(surf);
        return WLS ? WLS->view() : nullptr;
    }
    inline PHLWINDOW windowFromSurface(SP<CWLSurfaceResource> surf) {
        return Desktop::View::CWindow::fromView(viewOf(surf));
    }
    inline PHLLS layerFromSurface(SP<CWLSurfaceResource> surf) {
        return Desktop::View::CLayerSurface::fromView(viewOf(surf));
    }

    // A monitor's refresh rate, for pacing the momentum timer. Same expression
    // on both pins even though the header moved (helpers/Monitor.hpp:134 air ->
    // output/Monitor.hpp:92 top) and the class gained a namespace — PHLMONITOR
    // absorbs both.
    inline float refreshHz(PHLMONITOR m) {
        return m ? m->m_refreshRate : 0.f;
    }

    // The compositor's own log. `Log::logger` is an inline UP<> in a header, so
    // this only works because both compositor binaries export it AND its guard
    // variable as STB_GNU_UNIQUE (`nm -D` shows `u _ZN3Log6loggerE` /
    // `u _ZGVN3Log6loggerE`) — the plugin's copy therefore merges with the
    // compositor's instead of running its own initializer over it. The
    // string_view overload is used deliberately: it is a directly exported
    // symbol on both pins, whereas the variadic template's BODY differs between
    // them (0.55 caches a `static bool TRACE`, 0.56 reads a member).
    inline void log(const std::string& msg) {
        Log::logger->log(Log::DEBUG, msg);
    }

    // ---- event loop: timers and deferred work ------------------------------
    //
    // g_pEventLoopManager is the compositor's wl_event_loop front end, and this
    // plugin uses three corners of it: the 150ms main-thread heartbeat
    // (main.cpp), the idle callbacks the roll animation finalizes itself from
    // (vtbDeco.cpp), and the readable-waiter that drains the clipboard pipe
    // asynchronously (pasteIntoEdit).
    //
    // Wrapped here for the usual Axis-A reason — one more relocatable global —
    // and for a sharper one: every one of those callbacks' CODE lives in this
    // .so, so the unload path has to be able to take them back, and a
    // cancellation API is only usable if the handle-issuing call is reachable
    // through the seam that the unload path already goes through. That is why
    // doLater() returns its sequence here rather than swallowing it.
    //
    // EventLoopManager.hpp is byte-identical between the two pins, so none of
    // these needs a version arm: addTimer/removeTimer :32-33, doLater/
    // removeDoLater :41-42, doOnReadable :77.

    // Main-thread timer registration. removeTimer is half of what makes a hot
    // swap survivable — the timer's lambda is in this image, so PLUGIN_EXIT
    // must deregister it before dlclose() (see main.cpp's tick).
    inline void addTimer(SP<CEventLoopTimer> timer) {
        g_pEventLoopManager->addTimer(timer);
    }
    inline void removeTimer(SP<CEventLoopTimer> timer) {
        g_pEventLoopManager->removeTimer(timer);
    }

    // Run fn on the next wayland idle turn.
    //
    // [[nodiscard]] on purpose: dropping the sequence is the bug this wrapper
    // exists to make hard. A queued idle lambda that is still in the
    // compositor's list when `hyprctl reload` dlclose()s this image runs into
    // unmapped memory — the same class of crash as an unremoved timer,
    // one loop turn wide, and the three call sites in vtbDeco.cpp discarded
    // the seq for their entire life. Hold it and removeDoLater() it on the way
    // out (CVtbDeco::queueDoLater / cancelPendingDoLater do exactly that).
    [[nodiscard]] inline uint64_t doLater(std::function<void()> fn) {
        return g_pEventLoopManager->doLater(fn);
    }
    // Harmless on a sequence that has already fired: upstream's erase_if simply
    // matches nothing (EventLoopManager.cpp:240-247).
    inline void removeDoLater(uint64_t seq) {
        g_pEventLoopManager->removeDoLater(seq);
    }

    // Run fn once fd is readable — and note it TAKES OWNERSHIP of fd, which is
    // why the caller passes a duplicate() of an fd it still wants to read from.
    // Two sharp edges are upstream's, not this wrapper's: fn runs SYNCHRONOUSLY
    // if the fd is already readable, and there is no cancel handle — a waiter
    // lives until its fd fires or the compositor dies. So use it only for a
    // client-driven pipe with a bounded lifetime (the clipboard paste), never
    // as a general deferral: doLater() above is the cancellable one.
    inline void doOnReadable(Hyprutils::OS::CFileDescriptor fd, std::function<void()>&& fn) {
        g_pEventLoopManager->doOnReadable(std::move(fd), std::move(fn));
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
