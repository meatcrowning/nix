"""Pure state rules for the short-lived DeskStyle apply overlay.

The controller is the authority: its status record is written at the same time
as each D-Bus ``Progress`` signal.  Keeping the decision about whether an
overlay should appear outside the widget makes it possible to regression-test
the important honesty rule without putting a window on a real display.
"""

from __future__ import annotations

from typing import Any, Mapping


TERMINAL_STATES = frozenset(("complete", "failed"))


def status_for_generation(status: Mapping[str, Any], generation: int) -> str:
    """Classify a controller status record for one requested generation.

    A newer generation replaces this one, so an old overlay must stand down
    instead of covering the newer request.  A malformed/incomplete status is
    deliberately ``pending``: it must not fabricate a completion.
    """
    try:
        reported = int(status.get("generation", 0))
    except (TypeError, ValueError):
        return "pending"
    state = status.get("state")
    if reported > generation:
        return "superseded"
    if reported != generation or not isinstance(state, str):
        return "pending"
    return state if state in TERMINAL_STATES or state in {"queued", "applying", "waiting-for-apps"} else "pending"


def should_show(elapsed_ms: int, status: Mapping[str, Any], generation: int,
                threshold_ms: int = 120) -> bool:
    """Show only a real apply that outlasted the presentation threshold."""
    return (elapsed_ms >= threshold_ms
            and status_for_generation(status, generation)
            in {"queued", "applying", "waiting-for-apps"})


def progress(status: Mapping[str, Any], generation: int) -> tuple[float, str]:
    """Return controller-authored fraction/detail with safe display bounds."""
    if status_for_generation(status, generation) in ("pending", "superseded"):
        return 0.0, ""
    try:
        fraction = float(status.get("fraction", 0.0))
    except (TypeError, ValueError):
        fraction = 0.0
    fraction = max(0.0, min(1.0, fraction))
    detail = status.get("detail", "")
    return fraction, detail if isinstance(detail, str) else ""
