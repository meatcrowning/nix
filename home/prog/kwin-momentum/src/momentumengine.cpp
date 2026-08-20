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
    const double dt = toSeconds(now - oldest);
    if (dt <= 0.0) {
        vx = vy = 0.0;
        return;
    }
    vx = sumX / dt;
    vy = sumY / dt;

    // Direction-preserving clamp (§2).
    const double speed = std::hypot(vx, vy);
    if (speed > m_params.maxVelocity && speed > 0.0) {
        const double k = m_params.maxVelocity / speed;
        vx *= k;
        vy *= k;
    }
}

bool MomentumEngine::release(microseconds t)
{
    double vx = 0.0, vy = 0.0;
    velocity(t, vx, vy);
    const double speed = std::hypot(vx, vy);
    if (speed < m_params.minFlingVelocity) {
        m_coasting = false;
        return false;
    }
    m_vx = vx;
    m_vy = vy;
    m_lastTick = t;
    m_coasting = true;
    return true;
}

bool MomentumEngine::tick(microseconds now)
{
    if (!m_coasting) {
        return false;
    }
    const double dt = toSeconds(now - m_lastTick);
    m_lastTick = now;
    if (dt <= 0.0) {
        return true;
    }

    // Exponential decay toward zero, frame-rate independent.
    const double factor = std::pow(m_params.decayPerSecond, dt);
    m_vx *= factor;
    m_vy *= factor;

    const double speed = std::hypot(m_vx, m_vy);
    if (speed < m_params.stopBelow) {
        m_coasting = false;
        if (m_stop) {
            m_stop();            // never a mid-flight zero; this is the real stop.
        }
        return false;
    }

    if (m_emit) {
        m_emit(m_vx * dt, m_vy * dt);
    }
    return true;
}

} // namespace KWinMomentum
