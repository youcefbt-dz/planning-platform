"""What the numbers say, computed by code. Pure functions (no Flask, no database).

Every figure the dashboard shows comes from here; a model may only choose which of these facts to put on screen and phrase them.
For each series: the latest value, the change against the previous period and the same period a year earlier, the best and weakest
period, the periods that do not fit the usual pattern (anomalies), and the direction of the last months.

A change on a percentage series is measured in points (80% -> 83% is +3 points), on everything else in percent.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date


def _is_pct(unit: str | None) -> bool:
    return (unit or "").strip() == "%"


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def change(new: float, old: float | None, unit: str | None) -> dict | None:
    """{abs, rel, kind} where kind is 'points' (for a % series) or 'percent'. None if there is nothing to compare with."""
    if old is None:
        return None
    if _is_pct(unit):
        return {"abs": new - old, "rel": None, "kind": "points", "value": new - old}
    if old == 0:
        return {"abs": new - old, "rel": None, "kind": "percent", "value": None}
    return {"abs": new - old, "rel": (new - old) / abs(old), "kind": "percent", "value": (new - old) / abs(old)}


def tone_of(delta: float | None, direction: str, tolerance: float = 0.005) -> str:
    """'good' | 'bad' | 'flat' for a change, given whether higher or lower is better."""
    if delta is None or abs(delta) <= tolerance:
        return "flat"
    up = delta > 0
    return "good" if up == (direction != "lower_better") else "bad"


@dataclass
class Anomaly:
    period: date
    value: float
    expected: float
    deviation: float            # value - expected
    rel: float | None           # deviation / |expected|


@dataclass
class Facts:
    n: int
    first: date
    last: date
    latest: float
    prev: float | None
    year_ago: float | None
    vs_prev: dict | None
    vs_year: dict | None
    best: tuple[date, float]
    worst: tuple[date, float]
    trend: str                  # rising | falling | flat
    trend_tone: str             # good | bad | flat
    tone: str                   # overall tone used for the card (year-on-year when available, else previous period)
    anomalies: list[Anomaly] = field(default_factory=list)
    last12: float | None = None          # aggregate of the last 12 months (sum or mean, by aggregation)
    prior12: float | None = None
    vs_last12: dict | None = None


def _expected(points: list[tuple[date, float]], i: int, period_months: int) -> float | None:
    """What this period would normally be: the mean of the same calendar period in the other years, else the median of its neighbours."""
    d, _ = points[i]
    same = [v for j, (dd, v) in enumerate(points) if j != i and dd.month == d.month and period_months <= 12 and dd.year != d.year]
    if len(same) >= 2:
        # the level also drifts from year to year, so scale the seasonal pattern by the local level
        level = [v for dd, v in points if abs((dd.year - d.year) * 12 + dd.month - d.month) <= 6]
        ref = [v for dd, v in points if dd.year != d.year and abs(dd.month - d.month) <= 6]
        if level and ref and statistics.mean(ref):
            return statistics.mean(same) * (statistics.mean(level) / statistics.mean(ref))
        return statistics.mean(same)
    near = [points[j][1] for j in range(max(0, i - 3), min(len(points), i + 4)) if j != i]
    return statistics.median(near) if len(near) >= 3 else None


def find_anomalies(points: list[tuple[date, float]], period_months: int = 1, threshold: float = 3.0, limit: int = 3) -> list[Anomaly]:
    """Periods whose value is far from what the series normally does at that point (robust: median absolute deviation)."""
    if len(points) < 8:
        return []
    exp = [_expected(points, i, period_months) for i in range(len(points))]
    res = [(points[i][1] - e) if e is not None else None for i, e in enumerate(exp)]
    clean = [r for r in res if r is not None]
    if len(clean) < 6:
        return []
    med = statistics.median(clean)
    mad = statistics.median([abs(r - med) for r in clean]) or (statistics.pstdev(clean) / 1.4826 if len(clean) > 1 else 0)
    if not mad:
        return []
    scale = 1.4826 * mad
    out = []
    for i, r in enumerate(res):
        if r is None:
            continue
        z = abs(r - med) / scale
        if z >= threshold:
            e = exp[i]
            out.append((z, Anomaly(points[i][0], points[i][1], e, points[i][1] - e, (points[i][1] - e) / abs(e) if e else None)))
    out.sort(key=lambda x: -x[0])
    return [a for _, a in out[:limit]]


def aggregate(points: list[tuple[date, float]], months: int, end: date, aggregation: str, offset: int = 0) -> float | None:
    """Sum / mean / last of the `months` months that end at `end`, shifted back `offset` months. None if the window is incomplete."""
    stop = add_months(end, 1 - offset)
    start = add_months(stop, -months)
    vals = [v for d, v in points if start <= d < stop]
    need = months  # one point per month for monthly series
    if len(vals) < max(2, int(need * 0.75)):
        return None
    if aggregation == "avg":
        return statistics.mean(vals)
    if aggregation == "last":
        return vals[-1]
    return sum(vals)


def facts(points: list[tuple[date, float]], *, unit: str = "", direction: str = "higher_better", aggregation: str = "sum", period_months: int = 1) -> Facts | None:
    if len(points) < 2:
        return None
    pts = sorted(points)
    d, v = pts[-1]
    prev = pts[-2][1]
    by_date = dict(pts)
    year_ago = by_date.get(add_months(d, -12)) if period_months <= 12 else None
    vs_prev, vs_year = change(v, prev, unit), change(v, year_ago, unit)
    best_fn, worst_fn = (max, min) if direction != "lower_better" else (min, max)
    best, worst = best_fn(pts, key=lambda p: p[1]), worst_fn(pts, key=lambda p: p[1])
    recent = [x for _, x in pts[-6:]]
    base = statistics.mean(recent[:3]) if len(recent) >= 6 else recent[0]
    last3 = statistics.mean(recent[-3:])
    ref = abs(base) if base else (statistics.pstdev([x for _, x in pts]) or 1.0)
    slope = (last3 - base) / ref if not _is_pct(unit) else (last3 - base) / 100.0
    trend = "rising" if slope > 0.02 else "falling" if slope < -0.02 else "flat"
    trend_tone = tone_of(slope if trend != "flat" else 0, direction)
    main = vs_year or vs_prev
    tone = tone_of(main["value"] if main and main["value"] is not None else (main["abs"] if main else None), direction)
    last12 = aggregate(pts, 12, d, aggregation) if period_months == 1 else None
    prior12 = aggregate(pts, 12, d, aggregation, offset=12) if period_months == 1 else None
    return Facts(n=len(pts), first=pts[0][0], last=d, latest=v, prev=prev, year_ago=year_ago, vs_prev=vs_prev, vs_year=vs_year, best=best, worst=worst,
                 trend=trend, trend_tone=trend_tone, tone=tone, anomalies=find_anomalies(pts, period_months), last12=last12, prior12=prior12,
                 vs_last12=change(last12, prior12, unit) if last12 is not None and prior12 is not None else None)


def contributions(parts: dict[str, list[tuple[date, float]]], end: date, months: int = 12, aggregation: str = "sum") -> list[dict]:
    """How much each part (branch) moved the total: its aggregate over the last `months` minus the same window a year earlier."""
    rows = []
    for name, pts in parts.items():
        now, before = aggregate(sorted(pts), months, end, aggregation), aggregate(sorted(pts), months, end, aggregation, offset=12)
        if now is None:
            continue
        rows.append({"name": name, "now": now, "before": before, "delta": (now - before) if before is not None else None})
    return rows
