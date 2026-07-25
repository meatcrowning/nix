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
#include <hyprland/src/managers/eventLoop/EventLoopTimer.hpp>

inline HANDLE PHANDLE = nullptr;

class CVtbDeco;

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
