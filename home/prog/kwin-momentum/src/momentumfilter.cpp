/*
    kwin-momentum — input filter implementation (see momentumfilter.h).

    SCAFFOLD. The intercept and the injection both bind the real 6.7.4 ABI and
    the plugin builds/links clean against libkwin.so.6. Re-entrancy is handled by
    SOURCE, not a flag: our synthetic frames carry PointerAxisSource::Continuous
    and this filter acts only on ::Finger, so a coast frame is never re-fed to
    the estimator (no m_injecting guard needed).

    What is NOT yet proven on hardware, and stays the user's (runbook §5):
      * the coast clock — a plain QTimer stands in for a real per-frame render
        clock, so pacing (not distance — the engine integrates in closed form)
        may need the compositor's frame signal instead;
      * every decay constant / the momentum feel;
      * CLIENT-SIDE SELF-FLING. This filter installs at InputFilterOrder::Forward
        (last) and returns false on the finger-lift stop, i.e. it OBSERVES without
        swallowing — so the client still receives its own axis-stop and apps that
        self-fling on it (GTK, Chromium, kitty) will coast too, on top of ours.
        Suppressing that means consuming the stop (return true) from a filter
        installed BEFORE KWin's ForwardInputFilter; whether a same-order Forward
        filter runs before or after Forward's own delivery can only be settled by
        watching a live KWin, so it is left as an explicit open item, not guessed.
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
