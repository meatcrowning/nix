#include "vtbKinetic.hpp"

#include "globals.hpp"
// Every volatile Hyprland internal this module touches goes through here —
// see vtbCompat.hpp and PORTING.md. There is exactly one exception, and it is
// sanctioned: CConfigValue<> reads of HYPRLAND's own config keys (not the
// plugin's), which the checkPhase greps deliberately do not cover and which
// vtbDeco.cpp:2183 already does for general:resize_on_border.
#include "vtbCompat.hpp"

#include <hyprland/src/config/ConfigValue.hpp>
#include <hyprland/src/desktop/Workspace.hpp>
#include <hyprland/src/event/EventBus.hpp>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <format>
#include <fstream>
#include <sstream>

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

// Comma-separated class list membership, tolerant of spaces. Empty needle never
// matches (an unnamed window must not be caught by a stray empty token).
static bool csvContains(const std::string& csv, const std::string& needle) {
    if (csv.empty() || needle.empty())
        return false;
    size_t i = 0;
    while (i <= csv.size()) {
        size_t j = csv.find(',', i);
        if (j == std::string::npos)
            j = csv.size();
        size_t a = i, b = j;
        while (a < b && std::isspace((unsigned char)csv[a]))
            a++;
        while (b > a && std::isspace((unsigned char)csv[b - 1]))
            b--;
        if (b > a && csv.compare(a, b - a, needle) == 0)
            return true;
        i = j + 1;
    }
    return false;
}

// These strings reach a JSON reader (kinetic_get/stats echo window classes
// straight from a client-controlled property), so control characters have to be
// escaped as well as the two obvious ones — a raw newline in a class name would
// otherwise produce a document nothing can parse.
static std::string jsonEscape(const std::string& s) {
    static constexpr char HEX[] = "0123456789abcdef";
    std::string           out;
    out.reserve(s.size() + 8);
    for (const char C : s) {
        const auto U = (unsigned char)C;
        if (C == '"' || C == '\\') {
            out += '\\';
            out += C;
        } else if (U < 0x20) {
            out += "\\u00";
            out += HEX[(U >> 4) & 0xF];
            out += HEX[U & 0xF];
        } else
            out += C;
    }
    return out;
}

// Every number that reaches the JSON writers goes through here. A non-finite
// double formats as a bare `nan`/`inf` token, which is not JSON at all — so a
// single bad value would make the whole diagnostic surface unparseable, exactly
// when it is most needed. setKnob now refuses non-finite input, so this is the
// second line of defence rather than the first.
static double jnum(double v) {
    return std::isfinite(v) ? v : 0.0;
}

// ---------------------------------------------------------------------------
// effective constants — runtime override (kinetic_set) shadows the config
// ---------------------------------------------------------------------------
//
// The clamps here are NOT redundant with the hyprlang ranges on the config
// values: kinetic_set writes straight into the override map with no validator
// behind it, and a friction of 0 would divide by zero in the closed-form
// integrator two lines into the next tick.

double CVtbKinetic::eff(const char* key, double cfg) const {
    const auto IT = m_overrides.find(key);
    return IT == m_overrides.end() ? cfg : IT->second;
}
bool CVtbKinetic::effEnabled() const {
    return eff("enabled", Cfg::kinetic() ? 1.0 : 0.0) != 0.0;
}
double CVtbKinetic::effFriction() const {
    return std::clamp(eff("friction", Cfg::kineticFriction()), 0.5, 20.0);
}
double CVtbKinetic::effMinStartVelocity() const {
    // Lower bound 1.0, matching the hyprlang min on the config key: a runtime
    // override must not be a back door to the floor of zero that key forbids.
    return std::clamp(eff("min_start_velocity", Cfg::kineticMinStartVelocity()), 1.0, 5000.0);
}
double CVtbKinetic::effMinVelocity() const {
    return std::clamp(eff("min_velocity", Cfg::kineticMinVelocity()), 1.0, 500.0);
}
double CVtbKinetic::effMaxVelocity() const {
    return std::clamp(eff("max_velocity", Cfg::kineticMaxVelocity()), 100.0, 40000.0);
}
double CVtbKinetic::effGain() const {
    return std::clamp(eff("gain", Cfg::kineticGain()), 0.1, 5.0);
}
double CVtbKinetic::effAxisLockRatio() const {
    return std::clamp((double)Cfg::kineticAxisLockRatio(), 0.0, 1.0);
}
double CVtbKinetic::effMaxCoastRatio() const {
    return std::clamp(eff("max_coast_ratio", Cfg::kineticMaxCoastRatio()), 1.0, 50.0);
}
int CVtbKinetic::effRateHz() const {
    return (int)std::lround(eff("rate_hz", (double)Cfg::kineticRateHz()));
}
int CVtbKinetic::effStopDelayMs() const {
    return (int)std::clamp(std::lround(eff("stop_delay_ms", (double)Cfg::kineticStopDelayMs())), 0L, 1000L);
}
int CVtbKinetic::effWindowMs() const {
    return (int)std::clamp((long)Cfg::kineticWindowMs(), 20L, 300L);
}
int CVtbKinetic::effStaleMs() const {
    return (int)std::clamp((long)Cfg::kineticStaleMs(), 20L, 500L);
}
int CVtbKinetic::effMaxDurationMs() const {
    return (int)std::clamp((long)Cfg::kineticMaxDurationMs(), 100L, 10000L);
}
bool CVtbKinetic::effFrameStopFallback() const {
    return eff("frame_stop_fallback", Cfg::kineticFrameStopFallback() ? 1.0 : 0.0) != 0.0;
}
int CVtbKinetic::effDebug() const {
    return (int)Cfg::kineticDebug();
}

void CVtbKinetic::debugLog(int level, const std::string& msg) {
    if (effDebug() >= level)
        Hl::log("[hyprvtb kinetic] " + msg);
}

// ---------------------------------------------------------------------------
// the readback channel
// ---------------------------------------------------------------------------
//
// `hyprctl eval` NEVER returns a value on this Hyprland. A chunk that succeeds
// prints exactly "ok", whatever it evaluates to; the only text that comes back
// out is an error message (`hyprctl eval 'error("x")'` -> "error: … x"). So a
// lua function's return value is unreadable from a script, and every one of
// this module's introspection calls would otherwise be write-only.
//
// Hence a file channel. Each call drops its blob into the plugin's state
// directory — the same one geometry.tsv and the hot-swap handoff use, which is
// $HOME-based, so a NESTED test compositor (started with HOME=$RUN/home) writes
// into the harness's own scratch tree and can neither read nor clobber the live
// session's files. That isolation is free and needs no instance signature.
//
// Atomic via write-then-rename into the same directory, so a poller reading
// concurrently sees either the previous complete blob or the new one, never a
// half-written file. Failures are silent on purpose: this is a diagnostic, and a
// full disk must not take a code path that the compositor depends on.
void CVtbKinetic::publish(const char* filename, const std::string& body) {
    std::error_code   ec;
    const auto        DIR = std::filesystem::path(vtbStateDir());
    std::filesystem::create_directories(DIR, ec); // may already exist; ec swallows that
    const auto FINAL = DIR / filename;
    const auto TMP   = DIR / (std::string(filename) + ".tmp");
    {
        std::ofstream f(TMP, std::ios::trunc);
        if (!f.good())
            return;
        f << body;
        if (!f.good())
            return;
    } // closed — and therefore flushed — before the rename
    std::filesystem::rename(TMP, FINAL, ec);
    if (ec)
        std::filesystem::remove(TMP, ec); // don't leave a .tmp behind on failure
}

// Tick period. rate_hz 0 (the default) follows the latched window's monitor,
// clamped to [50,144]: exceeding the refresh is pure waste, since Qt, GDK and
// Blink each turn ONE wl_pointer.frame into one input event and repaint at
// vsync anyway. An explicit rate is honoured over a wider range for testing.
double CVtbKinetic::period() const {
    const int CFG = effRateHz();
    int       hz  = 0;
    if (CFG > 0)
        hz = std::clamp(CFG, 30, 240);
    else {
        const auto  W = m_latch.window.lock();
        const float R = W ? Hl::refreshHz(W->m_monitor.lock()) : 0.f;
        hz            = std::clamp((int)std::lround(R > 0.f ? R : 60.f), 50, 144);
    }
    return 1.0 / (double)hz;
}

// The wire timestamp. It MUST continue libinput's CLOCK_MONOTONIC-ms stream —
// clients divide by dt — so it is the stop event's own timeMs plus the elapsed
// time since, never a wall clock and never a plugin-relative one.
uint32_t CVtbKinetic::wireTime() const {
    const auto MS = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - m_t0).count();
    return m_stopEventTimeMs + (uint32_t)std::max<int64_t>(0, MS);
}

// ---------------------------------------------------------------------------
// sample ring
// ---------------------------------------------------------------------------

void CVtbKinetic::resetSamples() {
    m_head  = 0;
    m_count = 0;
}

// A DIAGONAL touchpad frame is two SAxisEvents sharing one timeMs (aquamarine
// loops both axes, then emits a single frame), so a repeated timestamp merges
// into the slot rather than pushing a second one — otherwise a diagonal flick
// would halve its own velocity window.
void CVtbKinetic::pushSample(const IPointer::SAxisEvent& e) {
    const bool HORIZ = e.axis == WL_POINTER_AXIS_HORIZONTAL_SCROLL;
    if (m_count > 0) {
        const size_t LAST = (m_head + KIN_SAMPLES - 1) % KIN_SAMPLES;
        if (m_ring[LAST].tMs == e.timeMs) {
            (HORIZ ? m_ring[LAST].dx : m_ring[LAST].dy) += e.delta;
            m_lastSampleTimeMs = e.timeMs;
            m_lastSampleAt     = std::chrono::steady_clock::now();
            return;
        }
    }
    m_ring[m_head] = SSample{e.timeMs, HORIZ ? e.delta : 0.0, HORIZ ? 0.0 : e.delta};
    m_head         = (m_head + 1) % KIN_SAMPLES;
    if (m_count < KIN_SAMPLES)
        m_count++;
    m_lastSampleTimeMs = e.timeMs;
    m_lastSampleAt     = std::chrono::steady_clock::now();
}

// ---------------------------------------------------------------------------
// start gates
// ---------------------------------------------------------------------------
//
// Returns nullptr when a fling may start, otherwise the reason it may not —
// and the reason is the whole point of the return type: if ANY gate refuses,
// the caller must let the real axis_stop through untouched. Swallowing a stop
// without starting a fling strands the client in an open scroll sequence
// forever, which is worse than no momentum at all.

const char* CVtbKinetic::startGate(uint32_t tStopMs, double& outVx, double& outVy, SLatch& outLatch) {
    if (!effEnabled())
        return "disabled";
    if (m_phase != KIN_TRACKING || m_count == 0)
        return "no-samples";
    // N1's observable half — see Hl::anyPointerDevice for why the real seat-caps
    // read is unreachable from a plugin.
    if (!Hl::anyPointerDevice())
        return "no-pointer-dev";

    // "Fingers rested motionless on the pad, then lifted" is a deliberate stop,
    // not a fling. Chromium uses 200ms for the same guard; 100 is tighter on
    // purpose.
    if (tStopMs >= m_lastSampleTimeMs && (int)(tStopMs - m_lastSampleTimeMs) > effStaleMs())
        return "stale";

    const auto SURF = Hl::pointerFocusSurface();
    if (!SURF)
        return "no-focus";
    // Layer surfaces are exempt WHOLESALE, and it is the panel that makes this
    // non-negotiable: its brightness and volume sliders act per EVENT, so a
    // one-second coast would be forty wpctl spawns. Note this is a surface-type
    // test, NOT a class denylist — Quickshell's own FloatingWindow toplevels are
    // ordinary windows and do want momentum.
    if (Hl::pointerOnLayerSurface())
        return "layer-focus";

    // Two different questions, answered from two different places on purpose.
    //
    // CLASSIFICATION — "is the thing under the pointer a window-ish surface?" —
    // comes from the view type, and it is the only thing keeping the lock screen
    // and (with the layer gate above) the panel out.
    //
    // IDENTITY — "which window's policy applies?" — cannot come from the same
    // place. A client's pointer focus is frequently a SUBSURFACE or a POPUP
    // (GTK content planes, video surfaces, menus), and NOTHING on either pin
    // resolves one of those back to its owning toplevel: see the note on
    // Hl::windowFromSurface for why both of the calls that look like they would
    // are the same refusing type-check, and why the owner refs are private. So
    // the policy window comes from the cursor HIT TEST, which returns the
    // toplevel regardless of what subsurface the focus happens to sit on. With
    // follow_mouse = 2 (live on both machines) the two coincide by construction.
    //
    // Without this the SUBSURFACE and POPUP arms were dead code — every one of
    // them fell through to "not-window" — which silently denied momentum to a
    // large share of the desktop.
    const auto VIEW = Hl::viewOf(SURF);
    if (!VIEW)
        return "not-window";
    switch (VIEW->type()) {
        case Desktop::View::VIEW_TYPE_WINDOW:
        case Desktop::View::VIEW_TYPE_SUBSURFACE:
        case Desktop::View::VIEW_TYPE_POPUP: break;
        default: return "not-window";
    }
    auto WIN = Hl::windowFromSurface(SURF); // exact, for a plain toplevel surface
    if (!WIN)
        WIN = Hl::windowAtCursorProps(Hl::mouse()); // subsurface / popup: ask the hit test
    if (!WIN || !WIN->m_isMapped)
        return "not-window";

    if (Hl::inputExclusive())
        return "exclusive-ls";
    if (Hl::seatGrabRejects(SURF))
        return "seat-grab";
    if (Hl::pointerConstrained())
        return "constrained";
    if (!Hl::noButtonsHeld())
        return "buttons";
    // Any modifier held means the wheel means something else entirely —
    // surfer's Ctrl+wheel zoom is x1.1 per event AND written to disk on every
    // step, so a coast under Ctrl corrupts state rather than merely looking odd.
    if (Hl::modsAllKeyboards() & KIN_MOD_MASK)
        return "mods";
    // The one exemption that is a hit test rather than a surface/class test: a
    // titlebar's PLAYBAR track or an open address editor is about to eat this
    // wheel itself.
    if (vtbAxisConsumerAtCursor(Hl::mouse()))
        return "deco";
    if (!classAllowed(WIN->m_class))
        return "class-denied";
    if (Cfg::kineticDenyXwayland() && WIN->m_isX11)
        return "xwayland";
    if (!WIN->m_workspace || !WIN->m_workspace->isVisible())
        return "workspace";

    // ---- velocity, over a sum/dt window (GTK's shape, Firefox's width) ------
    // NOT an EMA of deltas: an EMA is rate-dependent (it yields "units per
    // report", not px/s) and lags the last two or three reports, which is
    // exactly the part of the gesture the hand meant. The denominator ends at
    // tStop rather than the last sample, which is what stops it inflating the
    // result by one report interval.
    const int      WINDOW_MS = effWindowMs();
    double         sumX = 0.0, sumY = 0.0, sumAbs = 0.0;
    uint32_t       oldest = tStopMs;
    uint32_t       newest = tStopMs;
    uint32_t       used   = 0;
    for (size_t i = 0; i < m_count; i++) {
        const auto& S = m_ring[(m_head + KIN_SAMPLES - 1 - i) % KIN_SAMPLES];
        if (tStopMs < S.tMs)
            continue; // timestamp ran backwards; ignore rather than trust it
        if ((int)(tStopMs - S.tMs) > WINDOW_MS)
            break;
        sumX += S.dx;
        sumY += S.dy;
        sumAbs += std::abs(S.dx) + std::abs(S.dy);
        if (used == 0)
            newest = S.tMs; // walking newest-first
        oldest = S.tMs;
        used++;
    }
    // Clamped at 8ms: a whole window inside one millisecond would otherwise
    // divide by ~0 and hand wl_fixed_from_double an inf.
    const double DT_MS = std::max(8.0, (double)(tStopMs - oldest));
    double       vx    = 1000.0 * sumX / DT_MS;
    double       vy    = 1000.0 * sumY / DT_MS;

    // Scroll factor, applied ONCE here, reproducing onMouseWheel's own formula
    // (InputManager.cpp:938-942 air / :974-978 top). The bus hook fires BEFORE
    // `delta = e.delta * factor`, so every sample above is raw libinput and this
    // is the conversion into the surface-local px the client actually sees.
    // ISTOUCHPADSCROLL is unconditionally true for us: we only ever handle
    // FINGER. The per-device override cannot come off the event (the axis
    // signal carries no device), so it is read from the touchpad list instead.
    static auto PTOUCHPADSCROLLFACTOR = CConfigValue<Config::FLOAT>("input:touchpad:scroll_factor");
    double      factor                = (double)*PTOUCHPADSCROLLFACTOR;
    for (const auto& P : Hl::pointers()) {
        if (P && P->m_isTouchpad && P->m_scrollFactor.has_value()) {
            factor = (double)*P->m_scrollFactor;
            break;
        }
    }
    if (WIN->isScrollTouchpadOverridden())
        factor = (double)WIN->getScrollTouchpad();
    factor *= effGain();
    vx *= factor;
    vy *= factor;

    // Axis lock: macOS locks the axis, and without this a flick three degrees
    // off vertical drifts 300px sideways.
    const double LOCK = effAxisLockRatio();
    if (std::abs(vx) < LOCK * std::abs(vy))
        vx = 0.0;
    else if (std::abs(vy) < LOCK * std::abs(vx))
        vy = 0.0;

    // Direction-preserving speed clamp.
    double speed = std::hypot(vx, vy);
    if (speed > effMaxVelocity() && speed > 0.0) {
        const double SCALE = effMaxVelocity() / speed;
        vx *= SCALE;
        vy *= SCALE;
        speed = effMaxVelocity();
    }
    if (speed < effMinStartVelocity())
        return "slow";

    // ---- coast-ratio cap ---------------------------------------------------
    //
    // The bug this exists for, in the user's words: "scrolling in tiny
    // increments actually scrolls faster than normal scrolling."
    //
    // Velocity is distance over TIME, so it says nothing about how far the
    // finger went. A 6px nudge delivered in 20ms reads ~300px/s and coasts
    // 300/3.6 = 83px — fourteen times its own travel — while a long deliberate
    // drag decelerates before the lift and barely coasts at all. The gesture
    // ends up proportional to its final instant rather than to itself, and the
    // small end of the range is where that inverts most violently.
    //
    // So bound the coast by the distance the finger actually covered inside the
    // velocity window. Because coast is exactly speed/k, the constraint
    //     speed <= k * ratio * travel
    // is precisely "coast <= ratio * travel" — the cap means what it is named,
    // with no second constant to keep in sync with the friction.
    //
    // Travel is the vector magnitude of the SAME per-axis sums the velocity came
    // from, carried through the same scroll factor so the units are the surface
    // px the client sees. |factor| because a negative one would otherwise invert
    // the cap into a sign flip.
    //
    // Deliberately AFTER the min_start_velocity gate, not before: the gate
    // decides whether this gesture was a fling at all, and it must judge the
    // real gesture. Capping first would turn every small nudge into a refusal
    // ("no coast at all") rather than the short, proportional coast that is the
    // point — an 8px nudge should glide 32px, not 0.
    const double TRAVEL  = std::hypot(sumX, sumY) * std::abs(factor);
    const double NATURAL = speed;
    const double CAP     = effFriction() * effMaxCoastRatio() * TRAVEL;
    bool         capped  = false;
    if (CAP > 0.0 && speed > CAP) {
        const double SCALE = CAP / speed;
        vx *= SCALE;
        vy *= SCALE;
        speed  = CAP;
        capped = true;
        m_stats.coastCapped++;
    }
    m_stats.lastNaturalV0 = NATURAL;
    m_stats.lastTravel    = TRAVEL;
    m_stats.lastWasCapped = capped;

    // LAST, after every multiply: the isfinite check has to sit downstream of
    // the factor and gain, not just downstream of the division. A non-finite
    // gain (kinetic_set is a raw setter) would sail past a check placed above
    // and produce a fling that emits nothing at all — the seam refuses every
    // NaN — while holding the client's scroll sequence open until
    // max_duration_ms. setKnob now rejects non-finite input too; this is the
    // structural half of that fix, and it is the half that also covers a
    // non-finite value arriving from a config file or a future knob.
    if (!std::isfinite(vx) || !std::isfinite(vy))
        return "nonfinite";

    m_stats.lastSamples = used;
    // Mean inter-SAMPLE interval, so it must span sample-to-sample and divide by
    // the number of gaps between them. Measuring to tStop instead would fold in
    // the lift gap and overstate the cadence — and this number's whole job is to
    // answer the one open question about this trackpad: whether window_ms holds
    // enough reports for a stable sum/dt.
    m_stats.lastCadenceMs   = used > 1 ? (double)(newest - oldest) / (double)(used - 1) : 0.0;
    m_stats.lastSumAbsDelta = sumAbs;

    outVx           = vx;
    outVy           = vy;
    outLatch        = SLatch{};
    outLatch.surface = SURF;
    outLatch.window  = WIN;
    outLatch.cls     = WIN->m_class;
    outLatch.isX11   = WIN->m_isX11;
    return nullptr;
}

bool CVtbKinetic::classAllowed(const std::string& cls) const {
    const std::string ALLOW = Cfg::kineticAllowClasses();
    if (!ALLOW.empty() && !csvContains(ALLOW, cls))
        return false;
    return !csvContains(Cfg::kineticDenyClasses(), cls);
}

// ---------------------------------------------------------------------------
// the flight
// ---------------------------------------------------------------------------

void CVtbKinetic::startFling(double vx, double vy, uint32_t tStopMs, const SLatch& latch) {
    m_vx              = vx;
    m_vy              = vy;
    m_accX            = 0.0;
    m_accY            = 0.0;
    // The client is owed a terminal stop on every axis this flight will actually
    // move — derived from the launch velocity AFTER axis lock, so a
    // horizontal-only flick owes a horizontal stop and not a vertical one. The
    // caller ORs in the axis of any stop event it swallowed, which is a second,
    // independent obligation: swallowing a stop on an axis means that axis's
    // sequence is still open even if the physics never touches it.
    m_owedX           = vx != 0.0;
    m_owedY           = vy != 0.0;
    m_latch           = latch;
    m_stopEventTimeMs = tStopMs;
    m_t0              = std::chrono::steady_clock::now();
    m_lastTick        = m_t0;
    m_tickSeq         = 0;
    m_startMods       = Hl::modsAllKeyboards() & KIN_MOD_MASK;
    m_phase           = KIN_FLYING;
    m_trace.clear();
    m_stats.lastEmits = 0;
    m_stats.flings++;
    m_stats.lastV0       = std::hypot(vx, vy);
    m_stats.lastDistance = 0.0;
    armTick();
    debugLog(1,
             std::format("fling start v=({:.0f},{:.0f}) px/s coast~{:.0f}px travel={:.0f}px{} cls={} samples={} cadence={:.1f}ms{}", jnum(vx), jnum(vy),
                         jnum(std::hypot(vx, vy) / effFriction()), jnum(m_stats.lastTravel),
                         m_stats.lastWasCapped ? std::format(" CAPPED(natural {:.0f}px/s -> {:.0f})", jnum(m_stats.lastNaturalV0), jnum(std::hypot(vx, vy))) : std::string(),
                         latch.cls, m_stats.lastSamples, m_stats.lastCadenceMs, m_dry ? " [DRY]" : ""));
}

void CVtbKinetic::armTick() {
    if (m_shuttingDown)
        return;
    if (!m_timer) {
        // Built on first use, so a session that never flings never registers a
        // timer at all. The module keeps its own strong ref deliberately:
        // CEventLoopManager::onTimerFire skips any timer whose strongRef() is
        // not > 2 (its own vector plus the iteration copy already make two), so
        // a timer nobody else owns silently never fires.
        m_timer = makeShared<CEventLoopTimer>(
            std::nullopt,
            [](SP<CEventLoopTimer>, void*) {
                if (g_pGlobalState && g_pGlobalState->kinetic)
                    g_pGlobalState->kinetic->tick();
            },
            nullptr);
        Hl::addTimer(m_timer);
    }

    const auto                            NOW = std::chrono::steady_clock::now();
    std::chrono::steady_clock::duration   until;
    if (m_phase == KIN_GRACE)
        until = m_graceUntil - NOW;
    else {
        // Absolute schedule (t0 + n*period), never now+period: timer slack must
        // not be able to stretch the coast. The integrator runs on the MEASURED
        // dt, so a late tick still emits exactly the right distance.
        m_tickSeq++;
        const auto TARGET = m_t0 + std::chrono::duration_cast<std::chrono::steady_clock::duration>(std::chrono::duration<double>(period() * (double)m_tickSeq));
        until             = TARGET - NOW;
    }
    if (until < std::chrono::steady_clock::duration::zero())
        until = std::chrono::steady_clock::duration::zero();
    m_timer->updateTimeout(std::chrono::duration_cast<Time::steady_dur>(until));
}

void CVtbKinetic::disarm() {
    if (m_timer)
        m_timer->updateTimeout(std::nullopt);
}

void CVtbKinetic::tick() {
    if (m_shuttingDown)
        return;
    m_stats.ticks++;
    const auto NOW = std::chrono::steady_clock::now();

    if (m_phase == KIN_GRACE) {
        if (NOW >= m_graceUntil)
            finishStop();
        else
            armTick();
        return;
    }
    if (m_phase != KIN_FLYING) {
        disarm();
        return;
    }

    if (const char* WHY = verifyLatch()) {
        // These two mean the client already got wl_pointer.leave, and sending
        // axis events to a surface that was left is a protocol violation — so
        // they owe nothing. Everything else owes a stop.
        //
        // "window-gone" is deliberately NOT in this set: an unmapped window does
        // not imply the SURFACE is gone or that focus moved (a window can unmap
        // while its client lives, and finishStop re-checks pointer focus and
        // sends nothing if it has moved on). Treating it as a DROP threw away a
        // stop the client was still owed; treating it as a STOP cannot send a
        // stray one, because that re-check is the real guard.
        const bool DROP = !std::strcmp(WHY, "surface-gone") || !std::strcmp(WHY, "focus-moved");
        endFlight(DROP ? KIN_END_DROP : KIN_END_STOP, WHY);
        return;
    }

    double dt  = std::chrono::duration<double>(NOW - m_lastTick).count();
    m_lastTick = NOW;
    dt         = std::clamp(dt, 0.0, 0.25);

    // Closed-form integration, so the total distance is exactly v0/k for ANY
    // tick rate or jitter — rate_hz changes pacing only, never feel. Every
    // implementation surveyed uses v*dt and is mildly rate-dependent as a
    // result.
    const double K     = effFriction();
    const double DECAY = std::exp(-K * dt);
    const double SX    = m_vx * (1.0 - DECAY) / K;
    const double SY    = m_vy * (1.0 - DECAY) / K;
    m_vx *= DECAY;
    m_vy *= DECAY;

    // Fractional carry. This is what makes "never emit a literal 0.0" possible:
    // sub-epsilon movement accumulates instead of rounding to a zero that the
    // protocol would read as axis_stop.
    m_accX += SX;
    m_accY += SY;
    double outX = 0.0, outY = 0.0;
    if (std::abs(m_accX) >= KIN_EMIT_EPS) {
        outX   = m_accX;
        m_accX = 0.0;
    }
    if (std::abs(m_accY) >= KIN_EMIT_EPS) {
        outY   = m_accY;
        m_accY = 0.0;
    }
    if (outX != 0.0 || outY != 0.0)
        emit(outX, outY);

    const double ELAPSED_MS = std::chrono::duration<double, std::milli>(NOW - m_t0).count();
    if (std::hypot(m_vx, m_vy) < effMinVelocity() || ELAPSED_MS > (double)effMaxDurationMs()) {
        enterGrace();
        return;
    }
    armTick();
}

void CVtbKinetic::emit(double outX, double outY) {
    const uint32_t T = wireTime();
    m_stats.lastDistance += std::abs(outX) + std::abs(outY);

    // Counted PER AXIS, identically in both modes, so a dry run's `emits` is
    // directly comparable with a wet one's — the trace ring is capped and cannot
    // stand in for the count.
    if (m_dry) {
        // Dry: record what WOULD have gone on the wire. Nothing reaches a
        // client, so this is safe to run in the live session.
        if (outY != 0.0) {
            m_owedY = true;
            m_stats.emits++;
            m_stats.lastEmits++;
            if (m_trace.size() < KIN_TRACE_MAX)
                m_trace.emplace_back(T, outY);
        }
        if (outX != 0.0) {
            m_owedX = true;
            m_stats.emits++;
            m_stats.lastEmits++;
            if (m_trace.size() < KIN_TRACE_MAX)
                m_trace.emplace_back(T, outX);
        }
        return;
    }

    m_emitting = true;
    if (outY != 0.0) {
        if (Hl::sendAxis(T, WL_POINTER_AXIS_VERTICAL_SCROLL, outY, 0, 0, WL_POINTER_AXIS_SOURCE_FINGER, WL_POINTER_AXIS_RELATIVE_DIRECTION_IDENTICAL)) {
            m_owedY = true;
            m_stats.emits++;
            m_stats.lastEmits++;
            if (m_trace.size() < KIN_TRACE_MAX)
                m_trace.emplace_back(T, outY);
        } else
            m_stats.emitRefused++;
    }
    if (outX != 0.0) {
        if (Hl::sendAxis(T, WL_POINTER_AXIS_HORIZONTAL_SCROLL, outX, 0, 0, WL_POINTER_AXIS_SOURCE_FINGER, WL_POINTER_AXIS_RELATIVE_DIRECTION_IDENTICAL)) {
            m_owedX = true;
            m_stats.emits++;
            m_stats.lastEmits++;
            if (m_trace.size() < KIN_TRACE_MAX)
                m_trace.emplace_back(T, outX);
        } else
            m_stats.emitRefused++;
    }
    // Exactly one frame per tick, and it is MANDATORY: a timer-driven axis has
    // no device frame behind it, and upstream defers the frame for FINGER.
    Hl::sendPointerFrame();
    m_emitting = false;
}

// The tail is over. Emit nothing for stop_delay_ms, then the terminal stop —
// by which time every client-side velocity estimator's window (Chromium 200ms,
// GTK 150, kitty 150, Firefox 100) holds nothing but zeros, so none of them can
// stack a second fling on ours.
void CVtbKinetic::enterGrace() {
    m_vx   = 0.0;
    m_vy   = 0.0;
    m_accX = 0.0;
    m_accY = 0.0;
    const int DELAY = effStopDelayMs();
    if (DELAY <= 0) {
        finishStop();
        return;
    }
    m_phase      = KIN_GRACE;
    m_graceUntil = std::chrono::steady_clock::now() + std::chrono::milliseconds(DELAY);
    armTick();
}

void CVtbKinetic::finishStop() {
    const uint32_t T    = wireTime();
    bool           sent = false;

    if (m_owedX || m_owedY) {
        if (m_dry) {
            if (m_trace.size() < KIN_TRACE_MAX)
                m_trace.emplace_back(T, 0.0);
            sent = true;
        } else {
            // Only if the client we owe is still the one listening. If focus
            // moved, it already got wl_pointer.leave and the sequence is over
            // by protocol.
            const auto SURF = Hl::pointerFocusSurface();
            if (SURF && SURF == m_latch.surface.lock()) {
                if (m_owedY)
                    Hl::sendAxisStop(T, WL_POINTER_AXIS_VERTICAL_SCROLL, WL_POINTER_AXIS_SOURCE_FINGER, WL_POINTER_AXIS_RELATIVE_DIRECTION_IDENTICAL);
                if (m_owedX)
                    Hl::sendAxisStop(T, WL_POINTER_AXIS_HORIZONTAL_SCROLL, WL_POINTER_AXIS_SOURCE_FINGER, WL_POINTER_AXIS_RELATIVE_DIRECTION_IDENTICAL);
                Hl::sendPointerFrame();
                if (m_trace.size() < KIN_TRACE_MAX)
                    m_trace.emplace_back(T, 0.0);
                sent = true;
            }
        }
    }
    if (sent)
        m_stats.stopsSent++;

    debugLog(1, std::format("fling end distance={:.0f}px emits={} ticksTotal={} stop={}", jnum(m_stats.lastDistance), m_stats.lastEmits, m_stats.ticks, sent ? "sent" : "none"));

    m_owedX = false;
    m_owedY = false;
    if (!m_injecting) // see m_dry
        m_dry = false;
    m_phase = KIN_IDLE;
    resetSamples();
    disarm();
}

void CVtbKinetic::endFlight(eEnd how, const char* reason) {
    if (m_phase != KIN_FLYING && m_phase != KIN_GRACE)
        return;
    // Already in grace, and grace IS the answer to a STOP — so a second STOP is
    // a no-op, not a restart. Re-entering enterGrace() here would push
    // m_graceUntil out by another stop_delay_ms every time, and every cancel
    // source repeats: holding Shift and typing would defer the client's terminal
    // axis_stop for as long as the typing lasted, keeping its scroll sequence
    // open and booking a cancel per keystroke.
    if (how == KIN_END_STOP && m_phase == KIN_GRACE)
        return;
    m_stats.cancels[reason]++;
    debugLog(1, std::format("fling cancel reason={} action={}", reason, how == KIN_END_DROP ? "DROP" : "STOP"));
    if (how == KIN_END_DROP) {
        m_stats.drops++;
        m_owedX = false;
        m_owedY = false;
        if (!m_injecting) // see m_dry: only injectTest owns it while it is running
            m_dry = false;
        m_phase = KIN_IDLE;
        resetSamples();
        disarm();
        return;
    }
    // STOP still honours the grace window: emission stops dead (the content
    // freezes) and the stop lands 300ms later against a measurably zero tail.
    enterGrace();
}

// Re-checked EVERY tick, because a fling cannot be latched (sendPointerAxis has
// no surface argument) and the compositor state under it can change without any
// event we listen for — a window can map under a stationary cursor and move
// pointer focus through one of the 26 simulateMouseMovement() call sites.
const char* CVtbKinetic::verifyLatch() {
    const auto SURF = m_latch.surface.lock();
    if (!SURF)
        return "surface-gone";
    if (Hl::pointerFocusSurface() != SURF)
        return "focus-moved";
    const auto W = m_latch.window.lock();
    if (!W || !W->m_isMapped)
        return "window-gone";
    if (!W->m_workspace || !W->m_workspace->isVisible())
        return "workspace";
    if (Hl::pointerConstrained())
        return "constrained";
    if (Hl::inputExclusive())
        return "exclusive-ls";
    if (Hl::seatGrabRejects(SURF))
        return "seat-grab";
    if (Hl::pointerOnLayerSurface())
        return "layer-focus";
    // Checked here as well as in onKeyboardKey because the bus has no modifier
    // event: a modifier press produces a key event, but the depressed mask is
    // updated on a separate path and may not have landed yet when it fires.
    if ((Hl::modsAllKeyboards() & KIN_MOD_MASK) != m_startMods)
        return "modifier";
    if (!Hl::noButtonsHeld())
        return "buttons";
    if (vtbAxisConsumerAtCursor(Hl::mouse()))
        return "deco";
    if (!Hl::anyPointerDevice())
        return "no-pointer-dev";
    return nullptr;
}

// ---------------------------------------------------------------------------
// feeds
// ---------------------------------------------------------------------------

void CVtbKinetic::onAxis(const IPointer::SAxisEvent& e, Event::SCallbackInfo& info) {
    if (m_shuttingDown)
        return;
    // Structural, not defensive: direct-seat emission never touches the bus, so
    // this can only ever be true if someone reroutes emission back through
    // CInputManager::onMouseWheel. Then it is an early return instead of
    // unbounded recursion.
    if (m_emitting)
        return;

    // Sources other than FINGER are not ours, and the check is FIRST so a wheel
    // mouse costs nothing here: on `top` every scroll event in the session is a
    // trackball WHEEL, and the device rescan below allocates.
    if (e.source != WL_POINTER_AXIS_SOURCE_FINGER)
        return;

    // Disabled: do no ring work, no device scan, nothing. The cost of the whole
    // module on a machine that never turns it on is then this one comparison per
    // finger event. A gesture already in progress when someone enables it
    // mid-stream simply refuses "no-samples" once and the next one works.
    if (!effEnabled()) {
        if (m_phase != KIN_IDLE) {
            m_phase = KIN_IDLE;
            resetSamples();
        }
        return;
    }

    rescanDevices();

    if (e.delta != 0.0) {
        // A new finger scroll supersedes anything in flight — DROP, no stop:
        // the new sequence is a continuation, and macOS treats a fresh Began
        // phase the same way.
        if (m_phase == KIN_FLYING || m_phase == KIN_GRACE)
            endFlight(KIN_END_DROP, "new-scroll");
        // Set for EVERY touchpad, because the bus carries no device on an axis
        // event and there is therefore nothing to attribute it to. Each device's
        // own frame consumes only its own entry — see onDeviceFrame.
        for (auto& [ID, SAW] : m_devSawAxis)
            SAW = true;
        m_haveLastStop = false;
        if (m_phase != KIN_TRACKING) {
            resetSamples();
            m_phase = KIN_TRACKING;
        }
        pushSample(e);
        return;
    }

    // delta == 0 on a FINGER source: libinput's guaranteed finger-lift.
    if (m_phase == KIN_FLYING || m_phase == KIN_GRACE) {
        // The second axis of a two-axis lift, or a spurious stop mid-tail.
        // It must NEVER reach the client while we are still coasting — one
        // axis_stop is all any client-side fling estimator needs.
        info.cancelled                                                  = true;
        (e.axis == WL_POINTER_AXIS_HORIZONTAL_SCROLL ? m_owedX : m_owedY) = true;
        return;
    }

    // A DIAGONAL lift emits one stop per axis in the same frame, sharing a
    // timeMs. If the first was refused, the ring has already been cleared, so
    // the second can only ever refuse "no-samples" — a phantom that would
    // double every refusal count and bury the real reason. Take the first stop
    // of a millisecond and ignore the rest of it.
    if (m_haveLastStop && e.timeMs == m_lastStopTimeMs)
        return;
    m_lastStopTimeMs = e.timeMs;
    m_haveLastStop   = true;

    double vx = 0.0, vy = 0.0;
    SLatch latch;
    if (const char* WHY = startGate(e.timeMs, vx, vy, latch)) {
        m_stats.refusals[WHY]++;
        debugLog(2, std::string("no fling: ") + WHY);
        m_phase = KIN_IDLE;
        resetSamples();
        return; // the REAL stop passes through, untouched
    }

    info.cancelled = true;
    startFling(vx, vy, e.timeMs, latch);
    // ...and the axis whose stop we just swallowed is owed one too, on top of
    // whatever the launch velocity implies (startFling).
    (e.axis == WL_POINTER_AXIS_HORIZONTAL_SCROLL ? m_owedX : m_owedY) = true;
}

// Belt-and-braces finger-lift: a device frame carrying no axis event while a
// scroll is in progress. libinput's contract says the terminating zero always
// comes, but this trackpad has never actually been observed, so the fallback
// stays. NOTE it cancels nothing — there was no stop event to cancel — and if
// the real stop does turn up afterwards, the FLYING branch above swallows it.
//
// TWO limitations, both deliberate, because this path infers rather than
// observes:
//
//  * The evidence it consumes ("no axis since my last frame") is per device
//    here, so another pointer's motion-only frame cannot end this touchpad's
//    scroll — but the flag can only ever be SET for all devices at once, since
//    the event bus carries no device on an axis event. What that leaves
//    uncovered is a motion-only frame from the SAME device mid-gesture: it would
//    read as a lift with the fingers still down. It cannot be ruled out from
//    source (whether aquamarine emits a frame for a motion-only group on this
//    driver is unverified), and the staleness check below bounds it to 100ms
//    after the last scroll sample.
//  * Hence the kill switch. `plugin:hyprvtb:kinetic_frame_stop_fallback = false`
//    (or kinetic_set("frame_stop_fallback", 0), no reload needed) disables this
//    entire path and leaves the primary libinput-guaranteed stop as the only
//    trigger. If momentum ever starts mid-gesture, that is the first thing to
//    turn off.
void CVtbKinetic::onDeviceFrame(uintptr_t devId) {
    if (m_shuttingDown)
        return;

    const auto IT  = m_devSawAxis.find(devId);
    const bool SAW = IT != m_devSawAxis.end() && IT->second;
    if (IT != m_devSawAxis.end())
        IT->second = false;

    if (m_phase != KIN_TRACKING || SAW || !effFrameStopFallback())
        return;

    // The stale gate cannot work off timestamps here (a frame event carries
    // none), so it works off the wall between the last sample and now.
    const auto SINCE = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - m_lastSampleAt).count();
    if (SINCE > (double)effStaleMs()) {
        m_phase = KIN_IDLE;
        resetSamples();
        return;
    }

    double vx = 0.0, vy = 0.0;
    SLatch latch;
    if (const char* WHY = startGate(m_lastSampleTimeMs, vx, vy, latch)) {
        m_stats.refusals[WHY]++;
        m_phase = KIN_IDLE;
        resetSamples();
        return;
    }
    // No stop event was swallowed on this path, so the owed axes are exactly the
    // ones the launch velocity will move — which startFling already derived. A
    // hardcoded vertical here used to hand a horizontal-only flick an axis_stop
    // for an axis that never had an event, and none for the axis that did.
    startFling(vx, vy, m_lastSampleTimeMs, latch);
    debugLog(1, "fling start via device-frame fallback (no terminating zero seen)");
}

// Fingers back on the pad. zwp_pointer_gesture_hold_v1 exists, in the words of
// its own protocol xml, "in particular [...] to cancel kinetic scrolling" — so
// this is the brake. Reachable only per device: neither pin has a hold event on
// the bus.
void CVtbKinetic::onHoldBegin() {
    if (!m_shuttingDown)
        endFlight(KIN_END_STOP, "hold");
}

void CVtbKinetic::onPointerButton() {
    if (!m_shuttingDown)
        endFlight(KIN_END_STOP, "button");
}

void CVtbKinetic::onKeyboardKey() {
    if (m_shuttingDown || (m_phase != KIN_FLYING && m_phase != KIN_GRACE))
        return;
    // Only a MODIFIER-set change cancels. Plain typing during a coast is
    // harmless, and cancelling on it would make momentum unusable in an editor.
    if ((Hl::modsAllKeyboards() & KIN_MOD_MASK) != m_startMods)
        endFlight(KIN_END_STOP, "modifier");
}

void CVtbKinetic::onGestureBegin() {
    if (!m_shuttingDown)
        endFlight(KIN_END_STOP, "gesture");
}

// DROP, never STOP: the old surface has already had wl_pointer.leave, which
// ends the sequence per protocol. Sending it an axis_stop afterwards would be
// the violation, and sending one to the NEW surface would hand it a stop for a
// sequence it never saw begin.
void CVtbKinetic::onPointerFocusChange() {
    if (!m_shuttingDown)
        endFlight(KIN_END_DROP, "focus-change");
}

void CVtbKinetic::onConfigReloaded() {
    if (m_shuttingDown)
        return;
    m_overrides.clear();
    if (!effEnabled())
        endFlight(KIN_END_STOP, "config-disabled");
}

// The pointer device list has NO add/remove event on either pin, so the
// per-device listeners are re-derived whenever a cheap fingerprint of it moves.
// Called from the top of onAxis and from main.cpp's existing 150ms heartbeat,
// which together cover both "a device appeared while scrolling" and "a device
// appeared while idle".
void CVtbKinetic::rescanDevices() {
    std::vector<uintptr_t> fp;
    for (const auto& P : Hl::pointers()) {
        if (P && P->m_isTouchpad)
            fp.push_back((uintptr_t)P.get());
    }
    if (fp == m_devFingerprint)
        return;

    m_devFingerprint = fp;
    m_devListeners.clear();
    m_devSawAxis.clear();
    for (const auto& P : Hl::pointers()) {
        if (!P || !P->m_isTouchpad)
            continue;
        // The device's identity travels into the frame listener by value, so each
        // touchpad consumes only its own "saw an axis" evidence. Captured as a
        // plain integer, never a ref: the listener must not keep the device
        // alive, and it never dereferences the value.
        const uintptr_t ID = (uintptr_t)P.get();
        m_devSawAxis[ID]   = false;
        m_devListeners.emplace_back(P->m_pointerEvents.holdBegin.listen([](IPointer::SHoldBeginEvent e) {
            if (g_pGlobalState && g_pGlobalState->kinetic)
                g_pGlobalState->kinetic->onHoldBegin();
        }));
        m_devListeners.emplace_back(P->m_pointerEvents.frame.listen([ID]() {
            if (g_pGlobalState && g_pGlobalState->kinetic)
                g_pGlobalState->kinetic->onDeviceFrame(ID);
        }));
    }
    debugLog(1, std::format("touchpad listeners rebuilt: {}", fp.size()));
}

void CVtbKinetic::heartbeat() {
    if (!m_shuttingDown)
        rescanDevices();
}

// ---------------------------------------------------------------------------
// teardown
// ---------------------------------------------------------------------------
//
// The order is load-bearing. Stop deciding, drop the timer, drop the device
// listeners, and only THEN pay what the client is owed — so the flush cannot
// re-arm anything into an image that dlclose() is about to unmap. This is the
// same discipline as the tick timer PLUGIN_EXIT already removes first, and the
// obligation itself is NEW for this plugin: a client abandoned mid-sequence
// believes a scroll is still in progress forever (Qt keeps scrollingPhase true,
// GTK keeps scroll->active), and nothing ever tells it otherwise.

void CVtbKinetic::shutdown() {
    m_shuttingDown = true;

    if (m_timer) {
        m_timer->cancel();
        Hl::removeTimer(m_timer);
        m_timer.reset();
    }
    m_devListeners.clear();
    m_devFingerprint.clear();

    // Flush LAST, with no grace — there is no later to wait for. The pointer
    // focus check is what keeps this from being a protocol violation on the way
    // out; with no focus at all there is nobody to tell, so we skip entirely.
    if ((m_phase == KIN_FLYING || m_phase == KIN_GRACE) && (m_owedX || m_owedY) && !m_dry) {
        const auto SURF = Hl::pointerFocusSurface();
        if (SURF && SURF == m_latch.surface.lock()) {
            const uint32_t T = wireTime();
            if (m_owedY)
                Hl::sendAxisStop(T, WL_POINTER_AXIS_VERTICAL_SCROLL, WL_POINTER_AXIS_SOURCE_FINGER, WL_POINTER_AXIS_RELATIVE_DIRECTION_IDENTICAL);
            if (m_owedX)
                Hl::sendAxisStop(T, WL_POINTER_AXIS_HORIZONTAL_SCROLL, WL_POINTER_AXIS_SOURCE_FINGER, WL_POINTER_AXIS_RELATIVE_DIRECTION_IDENTICAL);
            Hl::sendPointerFrame();
            m_stats.stopsSent++;
        }
    }
    m_owedX = false;
    m_owedY = false;
    m_phase = KIN_IDLE;
}

CVtbKinetic::~CVtbKinetic() {
    if (!m_shuttingDown)
        shutdown();
}

// ---------------------------------------------------------------------------
// lua surface
// ---------------------------------------------------------------------------

bool CVtbKinetic::setEnabled(bool on) {
    return setKnob("enabled", on ? 1.0 : 0.0);
}

bool CVtbKinetic::setKnob(const std::string& key, double val) {
    if (m_shuttingDown)
        return false;
    // Non-finite is refused at the DOOR. Every eff*() clamp is a std::clamp, and
    // std::clamp propagates NaN rather than absorbing it — so a
    // kinetic_set("gain", 0/0) used to reach the physics, produce a fling that
    // emits nothing (the seam refuses every NaN it is handed) and hold the
    // client's scroll sequence open until max_duration_ms, while making
    // kinetic_get emit a bare `nan` token that is not valid JSON.
    if (!std::isfinite(val))
        return false;
    // unsafe_wet is a PROCESS-lifetime unlock, not a tunable: it is deliberately
    // not in the override map, so a config reload cannot clear it and a script
    // cannot arm it by accident on the way past.
    if (key == "unsafe_wet") {
        m_unsafeWet = val != 0.0;
        return true;
    }
    static const char* KNOBS[] = {"enabled", "friction", "min_start_velocity", "min_velocity", "max_velocity", "gain", "stop_delay_ms", "rate_hz", "frame_stop_fallback", "max_coast_ratio"};
    bool               known   = false;
    for (const char* K : KNOBS)
        known = known || key == K;
    if (!known)
        return false;

    m_overrides[key] = val;
    if (key == "enabled" && val == 0.0)
        endFlight(KIN_END_STOP, "disabled");
    debugLog(1, std::format("set {} = {}", key, val));
    return true;
}

// Fabricate a finger gesture and push it through the real estimator, so the
// gates, the physics and the emission path are all exercised.
//
// DRY by default, and wet is refused unless explicitly unlocked, because
// sendPointerAxis has NO surface argument: a wet run in the live session sprays
// scroll at whatever the pointer happens to be over. The nested test harness
// opts in with kinetic_set("unsafe_wet", 1) — there is deliberately no
// environment sniffing, because "am I nested?" is exactly the kind of guess
// that is wrong once and then costs a session.
int CVtbKinetic::injectTest(double dy, int n, int ms, bool wet) {
    if (m_shuttingDown)
        return 0;
    if (wet && !m_unsafeWet) {
        Hl::log("[hyprvtb kinetic] kinetic_test: WET run refused — it would send real scroll to whatever is under the pointer. "
                "Call kinetic_set(\"unsafe_wet\", 1) first, and only inside a nested compositor.");
        return 0;
    }
    n  = std::clamp(n, 1, 64);
    ms = std::clamp(ms, 1, 200);

    // ---- the invariant: a DRY invocation can never emit ---------------------
    //
    // cancelNow() is not enough on its own. On a live fling it routes through
    // endFlight(STOP) -> enterGrace(), which leaves the phase at GRACE, not IDLE
    // — and then the first injected delta hits the FLYING/GRACE branch of onAxis,
    // whose DROP path used to clear m_dry. A dry test fired within stop_delay_ms
    // of any earlier fling therefore went WET and sprayed real scroll at whatever
    // the pointer was over, with unsafe_wet never consulted.
    //
    // Two independent guards now, either of which alone would close it:
    //   1. the hard reset below puts the phase at IDLE *before* m_dry is set, so
    //      no endFlight can run between setting it and startFling consuming it;
    //   2. m_injecting makes every flight-end path leave m_dry alone for the
    //      duration of this function, so even a path nobody has thought of yet
    //      cannot flip it.
    m_injecting = true;

    // Settle whatever was already in flight BEFORE taking the state over. A
    // previous flight may still owe the client its terminal axis_stop, and the
    // hard reset below would otherwise discard that debt and leave its scroll
    // sequence open forever. finishStop() pays it immediately, with no grace —
    // or, if that flight was itself dry, merely records it. (It leaves m_dry
    // alone, because m_injecting is already set; the assignment below is what
    // establishes this run's mode.)
    if (m_phase == KIN_FLYING || m_phase == KIN_GRACE)
        finishStop();

    m_phase = KIN_IDLE;
    m_owedX = false;
    m_owedY = false;
    resetSamples();
    disarm();
    m_dry = !wet;
    m_trace.clear();

    // A synthetic timestamp base, stamped so the burst ENDS at now: wire
    // timestamps must never run ahead of the real libinput clock, or a client
    // dividing by dt sees a negative interval on the next genuine event.
    // Monotonic within the run either way, which is all the estimator needs.
    const uint32_t       NOW_MS = (uint32_t)std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
    const uint32_t       BASE   = NOW_MS - (uint32_t)(n * ms);
    Event::SCallbackInfo info;

    for (int i = 0; i < n; i++) {
        IPointer::SAxisEvent e;
        e.timeMs            = BASE + (uint32_t)(i * ms);
        e.source            = WL_POINTER_AXIS_SOURCE_FINGER;
        e.axis              = WL_POINTER_AXIS_VERTICAL_SCROLL;
        e.relativeDirection = WL_POINTER_AXIS_RELATIVE_DIRECTION_IDENTICAL;
        e.delta             = dy;
        info.cancelled      = false;
        onAxis(e, info);
    }

    IPointer::SAxisEvent stop;
    stop.timeMs            = BASE + (uint32_t)(n * ms);
    stop.source            = WL_POINTER_AXIS_SOURCE_FINGER;
    stop.axis              = WL_POINTER_AXIS_VERTICAL_SCROLL;
    stop.relativeDirection = WL_POINTER_AXIS_RELATIVE_DIRECTION_IDENTICAL;
    stop.delta             = 0.0;
    info.cancelled         = false;
    onAxis(stop, info);

    const bool STARTED = m_phase == KIN_FLYING;
    if (!STARTED)
        m_dry = false; // nothing to run: hand m_dry back before releasing it
    m_injecting = false;
    return STARTED ? 1 : 0;
}

void CVtbKinetic::cancelNow() {
    if (m_shuttingDown)
        return;
    if (m_phase == KIN_FLYING || m_phase == KIN_GRACE)
        endFlight(KIN_END_STOP, "manual");
    else {
        m_phase = KIN_IDLE;
        if (!m_injecting) // see m_dry
            m_dry = false;
        resetSamples();
        disarm();
    }
}

// NB written unconditionally, including when the trace is empty: "this fling
// emitted nothing" is a meaningful answer, and skipping the write would leave a
// stale file that reads as if it were the answer.
std::string CVtbKinetic::dumpJson() {
    static const char* NAMES[] = {"idle", "tracking", "flying", "grace"};
    std::ostringstream o;
    o << "{\"seq\":" << ++m_introspectSeq << ",\"state\":\"" << NAMES[(int)m_phase] << "\",\"friction\":" << std::format("{:.3f}", jnum(effFriction())) << ",\"vx\":" << std::format("{:.2f}", jnum(m_vx))
      << ",\"vy\":" << std::format("{:.2f}", jnum(m_vy)) << ",\"dry\":" << (m_dry ? "true" : "false") << ",\"owed\":[" << (m_owedX ? "true" : "false") << ","
      << (m_owedY ? "true" : "false") << "],\"trace\":[";
    for (size_t i = 0; i < m_trace.size(); i++) {
        if (i)
            o << ',';
        o << '[' << m_trace[i].first << ',' << std::format("{:.4f}", jnum(m_trace[i].second)) << ']';
    }
    o << "]}";
    const auto BODY = o.str();
    publish("kinetic-dump.json", BODY + "\n");
    return BODY;
}

std::string CVtbKinetic::statsJson() {
    std::ostringstream o;
    o << "{\"flings\":" << m_stats.flings << ",\"stopsSent\":" << m_stats.stopsSent << ",\"drops\":" << m_stats.drops << ",\"ticks\":" << m_stats.ticks
      << ",\"emits\":" << m_stats.emits
      // This one is the wire-level analogue of the degenerate-rect assertion.
      // It must be zero; anything else means a NaN or a literal 0.0 reached the
      // seam and was refused there rather than never computed.
      << ",\"emitRefused\":" << m_stats.emitRefused << ",\"lastEmits\":" << m_stats.lastEmits << ",\"coastCapped\":" << m_stats.coastCapped
      << ",\"lastV0\":" << std::format("{:.1f}", jnum(m_stats.lastV0)) << ",\"lastNaturalV0\":" << std::format("{:.1f}", jnum(m_stats.lastNaturalV0))
      << ",\"lastTravel\":" << std::format("{:.2f}", jnum(m_stats.lastTravel)) << ",\"lastWasCapped\":" << (m_stats.lastWasCapped ? "true" : "false")
      << ",\"lastDistance\":" << std::format("{:.1f}", jnum(m_stats.lastDistance)) << ",\"lastSamples\":" << m_stats.lastSamples
      << ",\"lastCadenceMs\":" << std::format("{:.2f}", jnum(m_stats.lastCadenceMs)) << ",\"lastSumAbsDelta\":" << std::format("{:.2f}", jnum(m_stats.lastSumAbsDelta))
      << ",\"refusals\":{";
    bool first = true;
    for (const auto& [K, V] : m_stats.refusals) {
        if (!first)
            o << ',';
        first = false;
        o << '"' << jsonEscape(K) << "\":" << V;
    }
    o << "},\"cancels\":{";
    first = true;
    for (const auto& [K, V] : m_stats.cancels) {
        if (!first)
            o << ',';
        first = false;
        o << '"' << jsonEscape(K) << "\":" << V;
    }
    o << "}}";
    const auto BODY = o.str();
    // "seq N" on its own first line, JSON on the second: these two are .txt, not
    // .json, precisely so a poller can read the freshness token with `head -1`
    // without parsing anything. kinetic-dump.json stays pure JSON (its seq is a
    // field) so `jq` can be pointed straight at it.
    publish("kinetic-stats.txt", std::format("seq {}\n{}\n", ++m_introspectSeq, BODY));
    return BODY;
}

std::string CVtbKinetic::getJson() {
    std::ostringstream o;
    o << "{\"enabled\":" << (effEnabled() ? "true" : "false") << ",\"configEnabled\":" << (Cfg::kinetic() ? "true" : "false")
      << ",\"friction\":" << std::format("{:.3f}", jnum(effFriction())) << ",\"min_start_velocity\":" << std::format("{:.1f}", jnum(effMinStartVelocity()))
      << ",\"min_velocity\":" << std::format("{:.1f}", jnum(effMinVelocity())) << ",\"max_velocity\":" << std::format("{:.1f}", jnum(effMaxVelocity()))
      << ",\"gain\":" << std::format("{:.3f}", jnum(effGain())) << ",\"axis_lock_ratio\":" << std::format("{:.3f}", jnum(effAxisLockRatio()))
      << ",\"max_coast_ratio\":" << std::format("{:.2f}", jnum(effMaxCoastRatio())) << ",\"rate_hz\":" << effRateHz()
      << ",\"tick_hz\":" << std::format("{:.1f}", jnum(1.0 / period())) << ",\"stop_delay_ms\":" << effStopDelayMs() << ",\"window_ms\":" << effWindowMs()
      << ",\"stale_ms\":" << effStaleMs() << ",\"max_duration_ms\":" << effMaxDurationMs()
      << ",\"frame_stop_fallback\":" << (effFrameStopFallback() ? "true" : "false") << ",\"emit_eps\":" << std::format("{:.2f}", KIN_EMIT_EPS)
      << ",\"deny_classes\":\"" << jsonEscape(Cfg::kineticDenyClasses()) << "\",\"allow_classes\":\"" << jsonEscape(Cfg::kineticAllowClasses())
      << "\",\"deny_xwayland\":" << (Cfg::kineticDenyXwayland() ? "true" : "false") << ",\"debug\":" << effDebug() << ",\"unsafe_wet\":" << (m_unsafeWet ? "true" : "false")
      << ",\"touchpads\":" << m_devFingerprint.size() << ",\"overrides\":{";
    bool first = true;
    for (const auto& [K, V] : m_overrides) {
        if (!first)
            o << ',';
        first = false;
        o << '"' << jsonEscape(K) << "\":" << std::format("{:.4f}", jnum(V));
    }
    o << "}}";
    const auto BODY = o.str();
    publish("kinetic-get.txt", std::format("seq {}\n{}\n", ++m_introspectSeq, BODY));
    return BODY;
}
