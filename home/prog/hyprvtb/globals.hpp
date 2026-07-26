#pragma once

#include <hyprland/src/plugins/PluginAPI.hpp>
#include <hyprland/src/render/Texture.hpp>
#include <hyprland/src/config/values/types/BoolValue.hpp>
#include <hyprland/src/config/values/types/IntValue.hpp>
#include <hyprland/src/config/values/types/FloatValue.hpp>
#include <hyprland/src/config/values/types/StringValue.hpp>
#include <hyprland/src/config/values/types/ColorValue.hpp>

#include <chrono>
#include <map>
#include <string>

#include <hyprland/src/helpers/signal/Signal.hpp>
#include <hyprland/src/managers/eventLoop/EventLoopTimer.hpp>

inline HANDLE PHANDLE = nullptr;

class CVtbDeco;
class CVtbKinetic;

// Weak reference to a decoration — deliberately NOT a bare WP<CVtbDeco>.
//
// Hyprland owns window decorations through a CUniquePointer, and hyprutils
// 0.14.0 added an assert to CWeakPointer::lock() forbidding a lock over a
// unique-owned object. That's what v2.48 was: the plugin compiled cleanly and
// then aborted the compositor a few seconds into login, from the roll
// animation's deferred open-reveal callback on the session-restore path. No
// compat shim can absorb a semantics change like that, so the fix is a type
// that simply does not offer the illegal operation.
//
// Reach the live object with `operator->`, gated on the liveness predicate —
// which is exactly what lock() used to check before handing back a SP.
// Shared-owned refs (PHLWINDOWREF, monitors, keyboards) are unaffected by all
// of this and keep using .lock() normally. See PORTING.md ("Axis B").
class CDecoRef {
  public:
    CDecoRef() = default;
    // Implicit from the owning UP, so `bars.emplace_back(bar)` / `m_self = bar`
    // read the same as they did with a raw WP.
    CDecoRef(const UP<CVtbDeco>& owner) : m_w(owner) {}

    // valid(): the object still exists. Mirrors WP's own operator bool, so
    // `if (!ref)` keeps its exact previous meaning at every call site.
    explicit operator bool() const {
        return m_w.valid();
    }
    // alive(): not expired — stricter than valid(), it also excludes an object
    // that is mid-destruction. This is lock()'s old precondition, and it is the
    // guard to use before dereferencing a ref that was captured into a deferred
    // callback (doLater / doOnReadable), where the deco may have died in the
    // meantime.
    bool alive() const {
        return !m_w.expired();
    }

    CVtbDeco* operator->() const {
        return m_w.get();
    }
    CVtbDeco* get() const {
        return m_w.get();
    }
    void reset() {
        m_w.reset();
    }
    bool operator==(const CDecoRef& rhs) const {
        return m_w == rhs.m_w;
    }

  private:
    WP<CVtbDeco> m_w; // private on purpose: no lock() can escape
};

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
    std::vector<CDecoRef>      bars;

    // Windows queued for layout after a login relaunch; drained by onNewWindow
    // as each relaunched window maps. Empty except briefly at startup.
    std::vector<SSessionEntry> pendingRestore;

    // ...and dropped wholesale once this passes. An entry whose app never
    // showed up (crashed, slow, closed before it mapped) used to sit here for
    // the rest of the session and then get claimed by the next window of that
    // class you opened BY HAND — which took the restore path, so it landed at
    // the snapshot geometry with no open animation. A restore that hasn't
    // happened within the window below is never going to happen.
    std::chrono::steady_clock::time_point restoreUntil{};

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

    // Main-thread heartbeat (150ms): damages bars whose app-button
    // registration changed (the IPC thread can't touch the renderer) and pops
    // hover tooltips after their dwell even when the cursor sits perfectly
    // still (mouse-move events alone can't do that). Removed in PLUGIN_EXIT
    // before the state dies.
    SP<CEventLoopTimer> tick;

    // macOS-style momentum scrolling (vtbKinetic.hpp). Owned here so
    // g_pGlobalState.reset() in PLUGIN_EXIT destroys it deterministically, with
    // the bus listeners that feed it. Null until PLUGIN_INIT builds it; the
    // whole module is inert unless plugin:hyprvtb:kinetic is on.
    UP<CVtbKinetic>     kinetic;

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

        // ---- kinetic scrolling (see vtbKinetic.hpp) ----
        // Flat underscore names, matching bar_width / font_size. The dotted
        // `col.*` group exists only because wal-set.sh writes those keys.
        // EVERY default lives here in C++ and nowhere else: hyprland.lua is a
        // seed-once file on both machines, so a default expressed there would
        // silently not apply to whichever copy is stale.
        SP<Config::Values::CBoolValue>   kinetic;
        SP<Config::Values::CFloatValue>  kineticFriction;
        SP<Config::Values::CFloatValue>  kineticMinStartVelocity;
        SP<Config::Values::CFloatValue>  kineticMinVelocity;
        SP<Config::Values::CFloatValue>  kineticMaxVelocity;
        SP<Config::Values::CFloatValue>  kineticGain;
        SP<Config::Values::CFloatValue>  kineticAxisLockRatio;
        SP<Config::Values::CIntValue>    kineticRateHz;
        SP<Config::Values::CIntValue>    kineticStopDelayMs;
        SP<Config::Values::CIntValue>    kineticWindowMs;
        SP<Config::Values::CIntValue>    kineticStaleMs;
        SP<Config::Values::CIntValue>    kineticMaxDurationMs;
        SP<Config::Values::CStringValue> kineticDenyClasses;
        SP<Config::Values::CStringValue> kineticAllowClasses;
        SP<Config::Values::CBoolValue>   kineticDenyXwayland;
        SP<Config::Values::CBoolValue>   kineticFrameStopFallback;
        SP<Config::Values::CIntValue>    kineticDebug;
    } config;
};

inline UP<SGlobalState> g_pGlobalState;

// Read the plugin's config values through here, never
// `g_pGlobalState->config.foo->value()` at the call site.
//
// `Config::Values::C*Value` is new and still moving upstream, and `->value()`
// is the shape of it that leaks everywhere — 32 sites' worth. Returning `auto`
// means not even the value types are named outside this block, so a change to
// either only has to be absorbed here. Same containment idea as vtbCompat.hpp
// (see PORTING.md), for config instead of compositor internals.
//
// Callers that can run with the plugin state torn down still have to check
// g_pGlobalState first — these do not, deliberately: a silent default would
// hide the bug rather than crash on it.
namespace Vtb::Cfg {
    inline auto enabled() {
        return g_pGlobalState->config.enabled->value();
    }
    inline auto barWidth() {
        return g_pGlobalState->config.barWidth->value();
    }
    inline auto fontSize() {
        return g_pGlobalState->config.fontSize->value();
    }
    inline auto maximizeGap() {
        return g_pGlobalState->config.maximizeGap->value();
    }
    inline auto font() {
        return g_pGlobalState->config.font->value();
    }
    inline auto bgColor() {
        return g_pGlobalState->config.bgColor->value();
    }
    inline auto bgAltColor() {
        return g_pGlobalState->config.bgAltColor->value();
    }
    inline auto textColor() {
        return g_pGlobalState->config.textColor->value();
    }
    inline auto buttonBorderColor() {
        return g_pGlobalState->config.buttonBorderColor->value();
    }
    inline auto accentColor() {
        return g_pGlobalState->config.accentColor->value();
    }
    inline auto critColor() {
        return g_pGlobalState->config.critColor->value();
    }
    inline auto inactiveColor() {
        return g_pGlobalState->config.inactiveColor->value();
    }

    // ---- kinetic scrolling ----
    // These are the CONFIGURED values. vtbKinetic reads them through its own
    // eff*() helpers, which let a runtime kinetic_set() override shadow them
    // without a `hyprctl reload` — feel-tuning has to be interactive to be
    // possible at all, and an override that survives a reload would be a
    // trapdoor rather than a knob.
    inline auto kinetic() {
        return g_pGlobalState->config.kinetic->value();
    }
    inline auto kineticFriction() {
        return g_pGlobalState->config.kineticFriction->value();
    }
    inline auto kineticMinStartVelocity() {
        return g_pGlobalState->config.kineticMinStartVelocity->value();
    }
    inline auto kineticMinVelocity() {
        return g_pGlobalState->config.kineticMinVelocity->value();
    }
    inline auto kineticMaxVelocity() {
        return g_pGlobalState->config.kineticMaxVelocity->value();
    }
    inline auto kineticGain() {
        return g_pGlobalState->config.kineticGain->value();
    }
    inline auto kineticAxisLockRatio() {
        return g_pGlobalState->config.kineticAxisLockRatio->value();
    }
    inline auto kineticRateHz() {
        return g_pGlobalState->config.kineticRateHz->value();
    }
    inline auto kineticStopDelayMs() {
        return g_pGlobalState->config.kineticStopDelayMs->value();
    }
    inline auto kineticWindowMs() {
        return g_pGlobalState->config.kineticWindowMs->value();
    }
    inline auto kineticStaleMs() {
        return g_pGlobalState->config.kineticStaleMs->value();
    }
    inline auto kineticMaxDurationMs() {
        return g_pGlobalState->config.kineticMaxDurationMs->value();
    }
    inline auto kineticDenyClasses() {
        return g_pGlobalState->config.kineticDenyClasses->value();
    }
    inline auto kineticAllowClasses() {
        return g_pGlobalState->config.kineticAllowClasses->value();
    }
    inline auto kineticDenyXwayland() {
        return g_pGlobalState->config.kineticDenyXwayland->value();
    }
    inline auto kineticFrameStopFallback() {
        return g_pGlobalState->config.kineticFrameStopFallback->value();
    }
    inline auto kineticDebug() {
        return g_pGlobalState->config.kineticDebug->value();
    }
}
namespace Cfg = Vtb::Cfg;

// Does any titlebar consume a vertical wheel event at this cursor position (the
// PLAYBAR scrub track, or an open address editor)? Defined in vtbDeco.cpp.
//
// It is declared HERE, next to the free functions, rather than in vtbDeco.hpp
// so that vtbKinetic.cpp can ask the question without naming a decoration type
// — the module is otherwise entirely free of CVtbDeco and could be lifted into
// a sibling plugin by moving two files. It exists because `info.cancelled` is
// useless as a "did someone else eat this?" test: hyprutils calls every
// listener unconditionally and the kinetic listener is registered FIRST, so it
// would always observe `false` no matter what a deco does afterwards.
bool        vtbAxisConsumerAtCursor(const Vector2D& mouse);

std::string vtbStatePath();
void        vtbLoadGeometry();
void        vtbSaveGeometry();
std::string vtbSessionPath();
void        vtbSaveSession();
void        vtbRestoreSession();
