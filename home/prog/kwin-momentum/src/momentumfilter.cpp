/*
    kwin-momentum — input filter implementation (see momentumfilter.h).

    SCAFFOLD. The intercept and the injection both bind the real 6.7.4 ABI and
    the plugin builds/links clean against libkwin.so.6. What is NOT yet proven
    on hardware: the coast clock (a plain QTimer stands in for the render frame
    clock), the exact re-entrancy behaviour of processAxis feeding our own
    filter (guarded here with m_injecting), and every decay constant. Runtime
    verification is the user's touchpad — see runbook §5.
*/
#include "momentumfilter.h"

#include <core/inputdevice.h>
#include <input_event.h>
#include <pointer_input.h>

#include <chrono>

using namespace std::chrono_literals;

namespace KWinMomentum
{

// Coast pump interval — placeholder for a real per-frame render clock.
static constexpr int kCoastIntervalMs = 8;      // ~120 Hz

static std::chrono::microseconds nowUs()
{
    return std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::steady_clock::now().time_since_epoch());
}

MomentumFilter::MomentumFilter()
    : KWin::InputEventFilter(KWin::InputFilterOrder::Forward)
{
    m_engine.setEmit([this](double dx, double dy) { emitAxis(dx, dy); });
    m_engine.setStop([this]() { emitStop(); });

    m_coastTimer.setInterval(kCoastIntervalMs);
    connect(&m_coastTimer, &QTimer::timeout, this, &MomentumFilter::onCoastFrame);
}

MomentumFilter::~MomentumFilter() = default;

bool MomentumFilter::pointerAxis(KWin::PointerAxisEvent *event)
{
    // Only touchpad/finger scrolling gets momentum; a wheel mouse is untouched.
    if (event->source != KWin::PointerAxisSource::Finger) {
        return false;
    }

    m_lastDevice = event->device;

    // Vertical vs horizontal split; natural-scroll sign is already applied by
    // libinput upstream, so the delta is used as-is (spec V1).
    double dx = 0.0, dy = 0.0;
    if (event->orientation == Qt::Vertical) {
        dy = event->delta;
    } else {
        dx = event->delta;
    }

    if (event->delta == 0.0) {
        // libinput scroll-stop: the finger lifted — decide whether to coast.
        if (m_engine.release(event->timestamp)) {
            m_coastTimer.start();
        }
    } else {
        m_engine.feed(dx, dy, event->timestamp);
    }

    // Observe only; the live drag still reaches the client.
    return false;
}

void MomentumFilter::onCoastFrame()
{
    if (!m_engine.tick(nowUs())) {
        m_coastTimer.stop();
    }
}

void MomentumFilter::emitAxis(double dx, double dy)
{
    auto *pointer = KWin::input()->pointer();
    if (!pointer) {
        return;
    }
    const auto t = nowUs();
    if (dy != 0.0) {
        pointer->processAxis(KWin::PointerAxis::Vertical, dy, 0,
                             KWin::PointerAxisSource::Continuous, false, t,
                             m_lastDevice);
    }
    if (dx != 0.0) {
        pointer->processAxis(KWin::PointerAxis::Horizontal, dx, 0,
                             KWin::PointerAxisSource::Continuous, false, t,
                             m_lastDevice);
    }
}

void MomentumFilter::emitStop()
{
    auto *pointer = KWin::input()->pointer();
    if (!pointer) {
        return;
    }
    const auto t = nowUs();
    // A single explicit axis-stop (delta 0) ends the coast — never mid-flight.
    pointer->processAxis(KWin::PointerAxis::Vertical, 0.0, 0,
                         KWin::PointerAxisSource::Continuous, false, t,
                         m_lastDevice);
}

} // namespace KWinMomentum
