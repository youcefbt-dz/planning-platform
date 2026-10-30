"""The reality engine: deterministic, judged against the organization's own history."""
import random
from datetime import date

import pytest

from app.modules.data.realism import assess


def series(n=24, base=100.0, growth=0.01, noise=0.02, seed=1):
    rnd, v, out = random.Random(seed), base, []
    for i in range(n):
        v *= 1 + growth + rnd.gauss(0, noise)
        out.append((date(2024 + i // 12, i % 12 + 1, 1), v))
    return out


def run(pts, factor, direction="higher_better", **kw):
    st = pts[-1][1]
    return assess(pts, start=st, target=st * factor, as_of=date(2026, 1, 1), end_date=date(2026, 12, 1), direction=direction, **kw)


def test_levels_rise_with_the_size_of_the_ask():
    pts = series()
    levels = [run(pts, f)["level"] for f in (1.05, 1.10, 1.30, 2.0)]
    assert levels[0] == "realistic" and levels[-1] == "unrealistic"
    order = ["realistic", "ambitious", "stretch", "unrealistic"]
    assert [order.index(x) for x in levels] == sorted(order.index(x) for x in levels)


def test_same_input_same_answer():
    pts = series()
    assert run(pts, 1.2) == run(pts, 1.2)


def test_short_history_is_insufficient_not_guessed():
    assert run(series(n=5), 1.1)["level"] == "insufficient"


def test_perfectly_regular_history_does_not_turn_a_tiny_excess_into_unrealistic():
    pts = series(noise=0.0)
    assert run(pts, 1.13)["level"] in ("realistic", "ambitious")      # history: +1%/month -> ~12.7% a year
    assert run(pts, 1.30)["level"] in ("stretch", "unrealistic")


def test_lower_is_better_is_mirrored():
    pts = [(date(2024 + i // 12, i % 12 + 1, 1), 20 - 0.3 * i) for i in range(24)]
    assert run(pts, 0.8, "lower_better")["level"] == "realistic"
    assert run(pts, 0.3, "lower_better")["level"] == "unrealistic"


def test_a_rate_is_judged_in_points_not_percent_of_percent():
    pts = [(date(2024 + i // 12, i % 12 + 1, 1), 26 + 0.07 * i) for i in range(24)]
    v = assess(pts, start=27.6, target=31, as_of=date(2026, 1, 1), end_date=date(2026, 12, 1), relative=False)
    assert v["measure"] == "absolute" and v["required"] == pytest.approx(3.4)


def test_target_already_met():
    v = run(series(), 0.9)
    assert v["level"] == "realistic" and "already_met" in v["notes"]


def test_wrong_scale_is_flagged():
    pts = series(base=8_000_000)
    v = assess(pts, start=pts[-1][1], target=60, as_of=date(2026, 1, 1), end_date=date(2026, 12, 1))
    assert "scale_mismatch" in v["notes"]


def test_range_is_expressed_as_target_values_and_facts_are_listed():
    v = run(series(), 1.2)
    assert v["range"]["low"] <= v["range"]["typical"] <= v["range"]["high"] <= v["range"]["max"]
    assert v["facts"] and all(isinstance(x, float) for x in v["facts"])


def test_seasonality_is_removed_when_there_are_two_full_years():
    import math
    pts = [(date(2024 + i // 12, i % 12 + 1, 1), 100 * (1 + 0.3 * math.sin((i % 12) / 12 * 2 * math.pi)) * (1 + 0.005 * i)) for i in range(36)]
    v = assess(pts, start=pts[-1][1], target=pts[-1][1] * 1.05, as_of=date(2027, 1, 1), end_date=date(2027, 12, 1))
    assert v["seasonal"] is True


# ---- 1.1: suggested levels and projection ----------------------------------------------------------
from app.modules.data.realism import levels, project  # noqa: E402


def test_levels_are_ordered_and_each_one_gets_the_matching_verdict():
    pts = series()
    st = pts[-1][1]
    kw = dict(as_of=date(2026, 1, 1), end_date=date(2026, 12, 1))
    lv = levels(pts, start=st, **kw)
    assert lv["conservative"] <= lv["ambitious"] <= lv["stretch"]
    assert lv["conservative"] >= st
    order = ["realistic", "ambitious", "stretch", "unrealistic"]
    got = [assess(pts, start=st, target=lv[k], direction="higher_better", **kw)["level"] for k in ("conservative", "ambitious", "stretch")]
    assert got[0] == "realistic" and order.index(got[1]) <= order.index("ambitious") and order.index(got[2]) <= order.index("stretch")


def test_levels_mirror_for_lower_is_better_and_never_cross_the_start():
    pts = [(date(2024 + i // 12, i % 12 + 1, 1), 20 - 0.3 * i) for i in range(24)]
    st = pts[-1][1]
    lv = levels(pts, start=st, as_of=date(2026, 1, 1), end_date=date(2026, 12, 1), direction="lower_better")
    assert lv["stretch"] <= lv["ambitious"] <= lv["conservative"] <= st


def test_levels_and_projection_refuse_to_guess_on_short_history():
    pts = series(n=5)
    assert levels(pts, start=pts[-1][1], as_of=date(2026, 1, 1), end_date=date(2026, 12, 1)) is None
    assert project(pts, as_of=date(2026, 1, 1), end_date=date(2026, 12, 1)) is None


def test_projection_is_a_range_around_the_latest_value():
    pts = series()
    pr = project(pts, as_of=date(2026, 1, 1), end_date=date(2026, 12, 1))
    assert pr["low"] <= pr["mid"] <= pr["high"] and pr["latest"] == pts[-1][1] and pr["high"] > pr["latest"]
