/*
    kwin-momentum — the KWin private-ABI seam.

    momentumfilter: a KWin::InputEventFilter that intercepts touchpad axis
    events (PointerAxisSource::Finger only — a wheel mouse passes straight
    through) and drives the session-agnostic MomentumEngine. The coast is fed
    back into the compositor via input()->pointer()->processAxis(...).

    Both entry points are KWin 6.7.4 private ABI, confirmed by grepping the
    installed headers (kwin-devel-6.7.4-2.fc44) — see the runbook §2:
      * intercept: bool InputEventFilter::pointerAxis(PointerAxisEvent *)
        (input.h:426), PointerAxisEvent fields at input_event.h:47.
      * inject:    PointerInputRedirection::processAxis(PointerAxis, qreal,
        qint32, PointerAxisSource, bool, microseconds, InputDevice*)
        (pointer_input.h:101), reached via input()->pointer().
    A KWin minor-version bump can move either; this whole .so is recompile-only.
*/
#pragma once

#include "momentumengine.h"

#include <input.h>

#include <QObject>
#include <QTimer>

namespace KWin
{
struct PointerAxisEvent;
class InputDevice;
}

namespace KWinMomentum
{

class MomentumFilter : public QObject, public KWin::InputEventFilter
{
    Q_OBJECT

public:
    MomentumFilter();
    ~MomentumFilter() override;

    // KWin input-chain intercept. Returns false so the live drag still reaches
    // the client untouched; we only observe the drag and, separately, inject
    // the coast frames.
    bool pointerAxis(KWin::PointerAxisEvent *event) override;

private:
    void onCoastFrame();
    void emitAxis(double dx, double dy);
    void emitStop();

    MomentumEngine m_engine;
    QTimer m_coastTimer;                 // stand-in for a per-frame render clock
    KWin::InputDevice *m_lastDevice = nullptr;
};

} // namespace KWinMomentum
