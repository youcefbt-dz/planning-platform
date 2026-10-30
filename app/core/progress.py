"""Domain rules for progress and status — pure functions, no Flask, no database.

These rules are product decisions, documented in docs/DOMAIN_RULES.md. They are
deliberately small and testable (tests/test_progress.py).

  * Key-result progress   = clamp((current − start) / (target − start), 0..1)
                            works for "decrease to X" goals too (both terms negative).
  * Objective progress    = weighted mean of its drivers (key results / child objectives / both).
  * Expected progress     = linear share of the period elapsed.
  * Derived status        = gap = expected − actual   (percentage points)
                            gap ≤ on_track  -> on_track
                            gap ≤ at_risk   -> at_risk
                            otherwise       -> off_track
                            (the 25-point "off track" line follows Microsoft Viva Goals' rule;
                             both limits are adjustable per organization.)
  * A manual status given in a check-in overrides the derived one until the next check-in.
  * Staleness             = no check-in within the cadence (default 14 days).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Sequence

STATUSES = ("not_started", "on_track", "at_risk", "off_track", "on_hold", "completed", "cancelled")
LIVE_STATUSES = ("on_track", "at_risk", "off_track")
DEFAULT_THRESHOLDS = {"on_track": 10.0, "at_risk": 25.0}  # points of gap


def clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def kr_progress(start: float | None, target: float | None, current: float | None) -> float:
    """0..1. Degenerate cases (no span, missing numbers) give 0 — or 1 when already at target."""
    if start is None or target is None or current is None:
        return 0.0
    span = target - start
    if span == 0:
        return 1.0 if current == target else 0.0
    return clamp01((current - start) / span)


KR_TYPES = ("increase", "decrease", "stay_above", "stay_below", "binary", "milestone")
# A key result is one of six kinds (the set used by Perdoo / Profit.co / Cascade):
#   increase / decrease : move a metric from `start` to `target`
#   stay_above / below  : keep a metric on the right side of `target` (a guard-rail, not a journey)
#   binary              : done or not done (current 1 = done)
#   milestone           : `current` of `target` agreed steps are done


def typed_kr_progress(kind: str | None, start: float | None, target: float | None, current: float | None) -> float:
    if kind == "binary":
        return 1.0 if (current or 0) >= 1 else 0.0
    if kind in ("stay_above", "stay_below"):
        if target is None or current is None:
            return 0.0
        ok = current >= target if kind == "stay_above" else current <= target
        if ok:
            return 1.0
        scale = abs(target) or 1.0
        return clamp01(1.0 - abs(current - target) / scale)
    return kr_progress(start, target, current)


def weighted_mean(items: Iterable[tuple[float, float]]) -> float | None:
    """items = (progress, weight). None when there is nothing to average."""
    num = den = 0.0
    for progress, weight in items:
        w = weight if weight and weight > 0 else 0.0
        num += progress * w
        den += w
    return None if den == 0 else num / den


def combine_drivers(own: float | None, children: float | None, driver: str) -> float:
    """Objective progress from its two possible sources, per progress_driver."""
    if driver == "children":
        return children if children is not None else 0.0
    if driver == "both":
        vals = [v for v in (own, children) if v is not None]
        return sum(vals) / len(vals) if vals else 0.0
    return own if own is not None else 0.0  # key_results (default)


def expected_progress(start: date | None, end: date | None, today: date) -> float:
    if not start or not end or end <= start:
        return 0.0
    if today <= start:
        return 0.0
    if today >= end:
        return 1.0
    return (today - start).days / (end - start).days


def derive_status(
    actual: float,
    expected: float,
    *,
    start: date | None = None,
    today: date | None = None,
    state: str | None = None,
    manual: str | None = None,
    thresholds: dict | None = None,
) -> str:
    """Final status shown in the UI.

    state:  lifecycle set by people: None/'active' | 'on_hold' | 'cancelled'
    manual: status chosen in the latest check-in (overrides the derived live status only)
    """
    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    if state in ("on_hold", "cancelled"):
        return state
    if actual >= 0.999:
        return "completed"
    if manual in LIVE_STATUSES:
        return manual
    today = today or date.today()
    if start and today < start and actual == 0:
        return "not_started"
    if actual == 0 and expected == 0:
        return "not_started"
    gap = (expected - actual) * 100.0
    if gap <= th["on_track"]:
        return "on_track"
    if gap <= th["at_risk"]:
        return "at_risk"
    return "off_track"


def is_stale(last_checkin: datetime | date | None, cadence_days: int, now: datetime | None = None) -> bool:
    now = now or datetime.utcnow()
    if last_checkin is None:
        return False  # nothing to be stale about yet; "never updated" is shown separately
    if isinstance(last_checkin, datetime):
        delta = now - last_checkin
    else:
        delta = now.date() - last_checkin
    return delta.days > cadence_days


# -- indicators (KPIs) ---------------------------------------------------------
def indicator_attainment(latest: float | None, target: float | None, direction: str = "higher_better") -> float | None:
    """Share of target reached. For lower_better indicators, target/latest (1.0 = on target)."""
    if latest is None or target is None:
        return None
    if direction == "lower_better":
        if latest <= 0:
            return 1.0 if target >= latest else 0.0
        return target / latest
    if target == 0:
        return 1.0 if latest >= 0 else 0.0
    return latest / target


def indicator_status(attainment: float | None, *, good: float = 0.95, warn: float = 0.80) -> str:
    if attainment is None:
        return "not_started"
    if attainment >= good:
        return "on_track"
    if attainment >= warn:
        return "at_risk"
    return "off_track"


def status_counts(statuses: Sequence[str]) -> dict[str, int]:
    out = {s: 0 for s in STATUSES}
    for s in statuses:
        out[s] = out.get(s, 0) + 1
    return out
