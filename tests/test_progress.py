import pytest
from datetime import date, datetime, timedelta

from app.core import progress as P


def test_kr_progress():
    assert P.kr_progress(0, 100, 50) == 0.5
    assert P.kr_progress(40, 90, 65) == 0.5          # baseline matters
    assert P.kr_progress(100, 0, 25) == 0.75         # decreasing targets work
    assert P.kr_progress(0, 100, 150) == 1.0         # clamped
    assert P.kr_progress(0, 100, -5) == 0.0
    assert P.kr_progress(5, 5, 5) == 1.0 and P.kr_progress(5, 5, 4) == 0.0
    assert P.kr_progress(None, 10, 3) == 0.0


def test_weighted_mean_and_drivers():
    assert P.weighted_mean([(1, 1), (0, 3)]) == 0.25
    assert P.weighted_mean([]) is None
    assert P.combine_drivers(0.4, 0.8, "key_results") == 0.4
    assert P.combine_drivers(0.4, 0.8, "children") == 0.8
    assert abs(P.combine_drivers(0.4, 0.8, "both") - 0.6) < 1e-9
    assert P.combine_drivers(None, None, "both") == 0.0


def test_expected_progress_is_linear():
    s, e = date(2026, 1, 1), date(2026, 1, 11)
    assert P.expected_progress(s, e, date(2025, 12, 1)) == 0
    assert P.expected_progress(s, e, date(2026, 1, 6)) == 0.5
    assert P.expected_progress(s, e, date(2027, 1, 1)) == 1
    assert P.expected_progress(None, e, s) == 0


def test_status_thresholds():
    kw = dict(start=date(2026, 1, 1), today=date(2026, 6, 1))
    assert P.derive_status(0.50, 0.55, **kw) == "on_track"      # gap 5
    assert P.derive_status(0.40, 0.55, **kw) == "at_risk"       # gap 15
    assert P.derive_status(0.20, 0.55, **kw) == "off_track"     # gap 35
    assert P.derive_status(0.45, 0.55, thresholds={"on_track": 12}, **kw) == "on_track"  # per-org rule
    assert P.derive_status(1.0, 0.5, **kw) == "completed"
    assert P.derive_status(0.2, 0.5, state="on_hold", **kw) == "on_hold"
    assert P.derive_status(0.2, 0.5, state="cancelled", manual="on_track", **kw) == "cancelled"
    assert P.derive_status(0.2, 0.5, manual="on_track", **kw) == "on_track"   # manual overrides live status
    assert P.derive_status(0, 0, start=date(2026, 7, 1), today=date(2026, 6, 1)) == "not_started"


def test_staleness():
    now = datetime(2026, 6, 30)
    assert P.is_stale(now - timedelta(days=15), 14, now)
    assert not P.is_stale(now - timedelta(days=14), 14, now)
    assert not P.is_stale(None, 14, now)


def test_indicators():
    assert P.indicator_attainment(90, 100) == 0.9
    assert P.indicator_attainment(5, 4, "lower_better") == 0.8        # target/latest
    assert P.indicator_attainment(None, 4) is None
    assert P.indicator_status(0.96) == "on_track"
    assert P.indicator_status(0.85) == "at_risk"
    assert P.indicator_status(0.5) == "off_track"
    assert P.indicator_status(None) == "not_started"


def test_typed_key_results():
    from app.core.progress import typed_kr_progress as tp
    assert tp("increase", 0, 100, 50) == 0.5 and tp("decrease", 10, 0, 5) == 0.5
    assert tp("binary", 0, 1, 0) == 0.0 and tp("binary", 0, 1, 1) == 1.0
    assert tp("milestone", 0, 4, 3) == 0.75
    assert tp("stay_above", 0, 70, 72) == 1.0 and tp("stay_above", 0, 70, 63) == pytest.approx(0.9)
    assert tp("stay_below", 0, 2, 1.5) == 1.0 and tp("stay_below", 0, 2, 3) == pytest.approx(0.5)
    assert tp(None, 0, 10, 5) == 0.5
