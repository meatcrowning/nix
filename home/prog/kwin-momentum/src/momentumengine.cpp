/*
    kwin-momentum — session-agnostic momentum core (see momentumengine.h).

    SCAFFOLD: the ring + decay are wired end to end so the plugin builds and the
    injection path is exercised, but the constants are the spec's starting
    values and no hardware tuning has happened. Do not treat the feel as final.
*/
#include "momentumengine.h"

#include <cmath>

namespace KWinMomentum
{

using std::chrono::microseconds;

static double toSeconds(microseconds us)
{
    return static_cast<double>(us.count()) / 1e6;
}

void MomentumEngine::push(double dx, double dy, microseconds t)
{
    // Merge a same-timestamp frame into the newest slot (diagonal frame, §1.2).
    if (m_count > 0) {
        const std::size_t last = (m_head + kRing - 1) % kRing;
        if (m_ring[last].t == t) {
            m_ring[last].dx += dx;
            m_ring[last].dy += dy;
            return;
        }
    }
    m_ring[m_head] = Sample{dx, dy, t};
    m_head = (m_head + 1) % kRing;
    if (m_count < kRing) {
        ++m_count;
    }
}

void MomentumEngine::feed(double dx, double dy, microseconds t)
{
    // A live drag frame cancels any coast that was still running.
    m_coasting = false;
    push(dx, dy, t);
    m_lastMove = t;                              // §1.4 staleness gate reference
}

void MomentumEngine::velocity(microseconds now, double &vx, double &vy) const
{
    // Sum displacement over the last relevanceWindowMs, divide by elapsed.
    const double windowUs = m_params.relevanceWindowMs * 1000.0;
    double sumX = 0.0, sumY = 0.0;
    microseconds oldest = now;
    int used = 0;

    for (std::size_t i = 0; i < m_count; ++i) {
        const std::size_t idx = (m_head + kRing - 1 - i) % kRing;
        const Sample &s = m_ring[idx];
        if (static_cast<double>((now - s.t).count()) > windowUs) {
            break;
        }
        sumX += s.dx;
        sumY += s.dy;
        oldest = s.t;
        ++used;
    }

    if (used < 2) {
        vx = vy = 0.0;
        return;
    }
    // GTK-form sum/Δt, Δt floored at 8 ms so a burst of near-simultaneous
    // samples cannot divide by a tiny window and inflate the velocity (§1.4).
    double dt = toSeconds(now - oldest);
    if (dt < 0.008) {
        dt = 0.008;
    }
    vx = sumX / dt;
    vy = sumY / dt;

    // Axis lock (§1.4): a near-vertical flick shouldn't drift sideways. If the
    // minor component is under axisLockRatio of the major, zero it.
    const double ax = std::abs(vx), ay = std::abs(vy);
    if (ay >= ax) {
        if (ax < m_params.axisLockRatio * ay) {
            vx = 0.0;
        }
    } else {
        if (ay < m_params.axisLockRatio * ax) {
            vy = 0.0;
        }
    }

    // Direction-preserving clamp (§3.4).
    const double speed = std::hypot(vx, vy);
    if (speed > m_params.maxVelocity && speed > 0.0) {
        const double k = m_params.maxVelocity / speed;
        vx *= k;
        vy *= k;
    }
}

bool MomentumEngine::release(microseconds t)
{
    // Staleness gate (§1.4): finger rested motionless before lifting ⇒ a
    // deliberate stop, not a fling. Let the real stop through, do not coast.
    if (m_count > 0) {
        const double restedMs = toSeconds(t - m_lastMove) * 1000.0;
        if (restedMs > m_params.staleMs) {
            m_coasting = false;
            return false;
        }
    }

    double vx = 0.0, vy = 0.0;
    velocity(t, vx, vy);
    const double speed = std::hypot(vx, vy);
    if (speed < m_params.minStartVelocity) {
        m_coasting = false;
        return false;
    }
    m_vx = vx;
    m_vy = vy;
    m_accX = 0.0;
    m_accY = 0.0;
    m_lastTick = t;
    m_flingStart = t;
    m_coasting = true;
    return true;
}

bool MomentumEngine::tick(microseconds now)
{
    if (!m_coasting) {
        return false;
    }

    // Hard safety cut on total coast length (§3.4): at k=3.6 a fling ends
    // naturally at ~1.5 s, but a pathological velocity/friction must not run away.
    if (toSeconds(now - m_flingStart) * 1000.0 > m_params.maxDurationMs) {
        m_coasting = false;
        if (m_stop) {
            m_stop();
        }
        return false;
    }

    const double dt = toSeconds(now - m_lastTick);
    m_lastTick = now;
    if (dt <= 0.0) {
        return true;
    }

    // Exponential decay, integrated in closed form so the coast DISTANCE is
    // exactly v0/k for any tick rate or jitter (§3.2): distance this tick is the
    // exact ∫v dt = v0·(1−decay)/k, not the rate-dependent v·dt. Guard k>0.
    const double k = m_params.friction > 1e-6 ? m_params.friction : 1e-6;
    const double decay = std::exp(-k * dt);
    const double sx = m_vx * (1.0 - decay) / k;
    const double sy = m_vy * (1.0 - decay) / k;
    m_vx *= decay;
    m_vy *= decay;

    // End of flight on the velocity floor (§3.4) — emit the single real stop.
    const double speed = std::hypot(m_vx, m_vy);
    if (speed < m_params.minVelocity) {
        m_coasting = false;
        if (m_stop) {
            m_stop();            // never a mid-flight zero; this is the real stop.
        }
        return false;
    }

    // Fractional carry (§3.3): accumulate sub-emitEps displacement and hold it
    // rather than quantizing to a value Qt/KWin would drop or read as a stop.
    // Emit only the axes that cleared the floor; if both are still under it,
    // emit NOTHING this tick — an axis delta of 0 IS the stop event on the wire.
    m_accX += sx;
    m_accY += sy;
    double outX = 0.0, outY = 0.0;
    if (std::abs(m_accX) >= m_params.emitEps) {
        outX = m_accX;
        m_accX = 0.0;
    }
    if (std::abs(m_accY) >= m_params.emitEps) {
        outY = m_accY;
        m_accY = 0.0;
    }
    if (m_emit && (outX != 0.0 || outY != 0.0)) {
        m_emit(outX, outY);
    }
    return true;
}

} // namespace KWinMomentum
