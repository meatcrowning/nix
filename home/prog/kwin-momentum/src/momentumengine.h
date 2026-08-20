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

// Tunables — spec §2. Starting values; the user tunes from feel, not an agent.
struct Params
{
    double relevanceWindowMs = 100.0;      // velocity averaged over the last 100 ms
    double maxVelocity = 6000.0;           // px/s clamp, direction-preserving
    double minFlingVelocity = 120.0;       // below this, no coast at all
    double decayPerSecond = 0.94;          // exponential factor toward zero
    double stopBelow = 20.0;               // px/s: end the coast, emit axis-stop
    double withheldStopMs = 300.0;         // spec/memory: withhold the 0 this long
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
    std::chrono::microseconds m_lastTick{0};
};

} // namespace KWinMomentum
