"""Data-quality findings: reproducible rules that never change the data on their own."""
from datetime import date

from app.modules.data.quality import apply_fixes, inspect


def months(vals, y=2024, start=1):
    out = []
    for i, v in enumerate(vals):
        m = start - 1 + i
        out.append((date(y + m // 12, m % 12 + 1, 1), v))
    return out


def codes(fs):
    return [f.code for f in fs]


def test_a_clean_series_has_no_findings():
    pts = months([100 + i * 2 + (i % 3) for i in range(24)])
    assert codes(inspect(pts)) == []


def test_missing_months_are_found_and_can_be_filled_without_inventing_when_left():
    pts = [p for p in months([100 + i for i in range(14)]) if p[0].month != 5]
    f = [x for x in inspect(pts) if x.code == "gaps"][0]
    assert f.data["count"] == 1 and f.data["first"] == "2024-05-01" and f.open
    filled = dict(apply_fixes(pts, 1, {"gaps": "interpolate"}))
    assert filled[date(2024, 5, 1)] == (103 + 105) / 2
    assert date(2024, 5, 1) not in dict(apply_fixes(pts, 1, {"gaps": "leave"}))
    assert dict(apply_fixes(pts, 1, {"gaps": "zero"}))[date(2024, 5, 1)] == 0


def test_running_totals_are_detected_and_converted_to_per_period_values():
    per = [10, 12, 9, 11, 14, 13, 12, 15, 11, 10, 13, 16, 9, 12, 10, 11, 13, 12, 14, 10, 11, 12, 13, 15]
    cum, run = [], 0
    for i, v in enumerate(per):
        run = v if i % 12 == 0 else run + v
        cum.append(run)
    pts = months(cum)
    f = [x for x in inspect(pts) if x.code == "cumulative"]
    assert f and f[0].data["strength"] == "strong" and f[0].options == ("to_period", "keep")
    assert [v for _, v in apply_fixes(pts, 1, {"cumulative": "to_period"})] == per
    assert "jump" not in codes(inspect(pts))          # the January drop is explained by the running total, not reported twice


def test_averages_are_never_called_cumulative():
    pts = months([5, 6, 7, 8, 9, 10, 11, 12])
    assert "cumulative" not in codes(inspect(pts, aggregation="avg"))


def test_a_spike_is_flagged_and_can_be_excluded_but_a_new_level_cannot():
    base = [100, 102, 99, 101, 103, 100, 102, 101, 99, 100, 101, 102]
    spike = base[:6] + [400] + base[7:]
    f = [x for x in inspect(months(spike)) if x.code == "jump"][0]
    assert f.period == "2024-07-01" and f.data["kind"] == "spike" and f.options == ("keep", "exclude")
    assert date(2024, 7, 1) not in dict(apply_fixes(months(spike), 1, {"exclude": ["2024-07-01"]}))
    shift = base[:6] + [300] * 6
    g = [x for x in inspect(months(shift)) if x.code == "jump"][0]
    assert g.data["kind"] == "shift" and g.options == ("keep",)


def test_a_yearly_peak_that_repeats_is_not_an_error():
    yr = [100, 98, 102, 101, 99, 100, 103, 100, 101, 99, 102, 190]
    assert "jump" not in codes(inspect(months(yr + yr)))


def test_a_decision_marks_the_finding_as_answered():
    spike = [100, 102, 99, 101, 103, 100, 400, 101, 99, 100, 101, 102]
    f = [x for x in inspect(months(spike), fixes={"confirmed": ["2024-07-01"]}) if x.code == "jump"][0]
    assert f.chosen == "keep" and not f.open


def test_an_unfinished_last_month_is_flagged():
    pts = months([100, 102, 99, 101, 103, 100, 98, 40])
    f = [x for x in inspect(pts) if x.code == "partial_last"]
    assert f and f[0].data["usual"] == 100
    assert len(apply_fixes(pts, 1, {"drop_last": "drop"})) == 7


def test_short_history_is_stated_honestly():
    f = [x for x in inspect(months([1, 2, 3, 2, 3])) if x.code == "short"][0]
    assert f.data["points"] == 5 and f.data["enough_for_realism"] is False and not f.options
