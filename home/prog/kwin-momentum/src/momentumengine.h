/*
    kwin-momentum — touchpad kinetic-scroll (macOS-style momentum) for KWin.

    momentumengine: the session-agnostic momentum core. Deliberately depends on
    nothing from KWin so it can be unit-reasoned in isolation and mirrors the
    verified vtbKinetic engine (hyprvtb). The full derivation of every constant
    and the sample-ring semantics live in
    docs/agents/kinetic-scroll-research/momentum-engine-spec-vtbkinetic-hyprvtb-module.md
    — read that before touching the math.

    STATUS: scaffold. Velocity estimation + exponential decay are wired to the
    real emit path; the decay constants are the spec's starting values and are
    the user's to tune from touchpad feel (see the runbook §5). Not yet verified
    on hardware.
*/
#pragma once

#include <array>
#include <chrono>
#include <cstddef>
#include <functional>

namespace KWinMomentum
{

// One 2D velocity sample, keyed on the event timestamp so a diagonal touchpad
// frame (two axis events, same timestamp) merges into one slot (spec §1.2).
struct Sample
{
    double dx = 0.0;                       // surface-local px, horizontal
    double dy = 0.0;                       // surface-local px, vertical
    std::chrono::microseconds t{0};        // event timestamp
};

// Tunables — the verified vtbKinetic spec's defaults (momentum-engine-spec §1.4,
// §3, §3.4). These are the spec's STARTING values; the floaty-vs-snappy feel is
// the user's to tune from his own touchpad, not an agent's (runbook §5). What is
// NOT a tunable is the decay MODEL: it is exponential in a friction rate `k`
// (s⁻¹), integrated in closed form (§3.2) — the pre-e370eda `pow(0.94, dt)` form
// was a units mistranslation that coasted a fling for ~74 s.
struct Params
{
    double relevanceWindowMs = 100.0;      // velocity averaged over the last 100 ms (§1.4)
    double staleMs = 100.0;                // finger rested this long before lift ⇒ no fling (§1.4)
    double maxVelocity = 6000.0;           // px/s clamp, direction-preserving (§3.4)
    double minStartVelocity = 200.0;       // px/s: below this, no coast at all (§3.4)
    double friction = 3.6;                 // k, s⁻¹: v(t)=v0·e^(−k·t); coast distance = v0/k (§3.1)
    double minVelocity = 24.0;             // px/s: end the coast, emit the single axis-stop (§3.4)
    double maxDurationMs = 2000.0;         // hard safety cut on total coast length (§3.4)
    double axisLockRatio = 0.25;           // |vminor| < ratio·|vmajor| ⇒ lock the minor axis to 0 (§1.4)
    double emitEps = 0.10;                 // px: fractional-carry floor; never emit below it, never emit 0 (§3.3)
};

class MomentumEngine
{
public:
    // emitFn(dx, dy): inject one synthetic axis frame back into the compositor.
    // stopFn(): emit the single axis-stop that ends a coast.
    using EmitFn = std::function<void(double dx, double dy)>;
    using StopFn = std::function<void()>;

    MomentumEngine() = default;

    void setParams(const Params &p) { m_params = p; }
    const Params &params() const { return m_params; }
    void setEmit(EmitFn emit) { m_emit = std::move(emit); }
    void setStop(StopFn stop) { m_stop = std::move(stop); }

    // Feed a live touchpad axis frame during the user's drag.
    void feed(double dx, double dy, std::chrono::microseconds t);

    // Record the timestamp of the last non-zero (moving) frame, so release() can
    // apply the staleness gate (§1.4): a finger that rested motionless on the pad
    // before lifting must not fling.
    std::chrono::microseconds lastMoveTime() const { return m_lastMove; }

    // The drag ended (finger up / libinput scroll-stop): decide whether to coast.
    // Returns true if a fling was started.
    bool release(std::chrono::microseconds t);

    // Advance the coast by one compositor frame. No-op when not coasting.
    // Returns true while still coasting.
    bool tick(std::chrono::microseconds now);

    bool coasting() const { return m_coasting; }
    void cancel() { m_coasting = false; }

private:
    static constexpr std::size_t kRing = 16;   // spec §1.2

    void push(double dx, double dy, std::chrono::microseconds t);
    // Average velocity (px/s) over the relevance window. Out params vx, vy.
    void velocity(std::chrono::microseconds now, double &vx, double &vy) const;

    Params m_params;
    EmitFn m_emit;
    StopFn m_stop;

    std::array<Sample, kRing> m_ring{};
    std::size_t m_head = 0;
    std::size_t m_count = 0;

    bool m_coasting = false;
    double m_vx = 0.0;                          // current coast velocity px/s
    double m_vy = 0.0;
    double m_accX = 0.0;                         // fractional-carry accumulator, px (§3.3)
    double m_accY = 0.0;
    std::chrono::microseconds m_lastTick{0};
    std::chrono::microseconds m_flingStart{0};  // for the max-duration safety cut
    std::chrono::microseconds m_lastMove{0};    // timestamp of the last non-zero frame
};

} // namespace KWinMomentum
