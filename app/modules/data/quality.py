"""Is this series safe to rely on?  Pure rules, no Flask, no model: every finding is reproducible and shows its numbers.

The user sees what looks odd BEFORE confirming and decides; nothing is changed silently. Findings:

  gaps          periods with no value inside the range          fix: interpolate | zero | leave
  cumulative    running totals (rise all year, drop in January) fix: to_period (convert to per-period) | keep
  jump          a step far outside the series' own habits        fix: keep | exclude (only for a spike that falls back)
  partial_last  the last period is far below the usual level     fix: drop | keep   (an unfinished month in the export)
  short         too little history to judge seasonality or a target  (information, no fix)

Decisions are stored per measure column in `Dataset.fixes` and applied by `apply_fixes`, which `series.build_series` calls.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date

from app.modules.data.realism import to_grid


@dataclass
class Finding:
    code: str
    severity: str                      # warn | info
    period: str | None = None          # ISO date of the first affected period
    data: dict = field(default_factory=dict)
    options: tuple = ()
    chosen: str | None = None          # the decision already taken (None = still open)
    column: int = -1
    series: str = ""

    @property
    def id(self) -> str:
        return f"{self.code}:{self.period or ''}"

    @property
    def open(self) -> bool:
        return bool(self.options) and self.chosen is None


def _months_per_year(period_months: int) -> int:
    return max(1, 12 // max(1, period_months))


def inspect(points, period_months: int = 1, *, aggregation: str = "sum", fixes: dict | None = None) -> list[Finding]:
    fixes = fixes or {}
    pts = sorted((d, float(v)) for d, v in points if v is not None)
    out: list[Finding] = []
    if len(pts) < 2:
        return out
    dates, vals = to_grid(pts, period_months)
    n = sum(1 for v in vals if v is not None)

    # -- gaps ------------------------------------------------------------------------------------------------
    missing = [d for d, v in zip(dates, vals) if v is None]
    if missing:
        out.append(Finding("gaps", "warn", missing[0].isoformat(), {"count": len(missing), "first": missing[0].isoformat(), "last": missing[-1].isoformat(),
                                                                    "examples": [m.isoformat() for m in missing[:3]]},
                           ("interpolate", "zero", "leave"), fixes.get("gaps")))

    # -- running totals ----------------------------------------------------------------------------------------
    cumulative = None
    if aggregation != "avg" and n >= 6:
        by_year: dict[int, list[tuple[date, float]]] = {}
        for d, v in pts:
            by_year.setdefault(d.year, []).append((d, v))
        rises = steps = 0
        for ys in by_year.values():
            for (_, a), (_, b) in zip(ys, ys[1:]):
                steps += 1
                rises += b >= a
        resets = []
        years = sorted(by_year)
        for y0, y1 in zip(years, years[1:]):
            last, first = by_year[y0][-1][1], by_year[y1][0][1]
            if last > 0 and first < 0.75 * last and by_year[y1][0][0].month <= 1 + period_months:
                resets.append(by_year[y1][0][0])
        if steps >= 4 and rises / steps >= 0.9 and resets:
            cumulative = {"strength": "strong", "resets": [r.isoformat() for r in resets][:3]}
        elif steps >= 5 and rises == steps and len(years) == 1 and pts[-1][1] >= 2.5 * pts[0][1] > 0:
            cumulative = {"strength": "weak", "resets": []}
    if cumulative:
        out.append(Finding("cumulative", "warn", pts[0][0].isoformat(), {**cumulative, "first": pts[0][1], "last": pts[-1][1]},
                           ("to_period", "keep"), fixes.get("cumulative")))

    # -- jumps / unfinished period are judged on the series the user agreed to read: converted when a running total was confirmed,
    #    and not at all while that question is still open (a January reset is not a jump)
    undecided_cum = bool(cumulative) and fixes.get("cumulative") is None
    if cumulative and fixes.get("cumulative") == "to_period":
        pts = apply_fixes(pts, period_months, {"cumulative": "to_period"})
        dates, vals = to_grid(pts, period_months) if len(pts) >= 2 else ([], [])
        n = sum(1 for v in vals if v is not None)
    if n >= 9 and not undecided_cum:
        base = [(dates[i], vals[i - 1], vals[i]) for i in range(1, len(vals)) if vals[i] is not None and vals[i - 1] not in (None, 0)]
        rel = [(d, (b - a) / abs(a)) for d, a, b in base]
        if len(rel) >= 8:
            med = statistics.median(r for _, r in rel)
            mad = statistics.median(abs(r - med) for _, r in rel)
            limit = max(0.5, 6 * max(1.4826 * mad, 0.05))
            by_date = dict(rel)
            confirmed = set(fixes.get("confirmed") or [])
            excluded = set(fixes.get("exclude") or [])
            for d, r in rel:
                if abs(r - med) < limit:
                    continue
                recurring = any(o != d and o.month == d.month and abs(r2) >= 0.5 * abs(r) and (r2 > 0) == (r > 0) for o, r2 in rel for r2 in [by_date[o]])
                if recurring:
                    continue
                nxt = by_date.get(date(d.year + (d.month - 1 + period_months) // 12, (d.month - 1 + period_months) % 12 + 1, 1))
                spike = nxt is not None and (nxt > 0) != (r > 0) and abs(nxt) >= 0.7 * abs(r) / (1 + abs(r)) * 1.0
                iso = d.isoformat()
                chosen = "exclude" if iso in excluded else "keep" if iso in confirmed else None
                out.append(Finding("jump", "warn", iso, {"change": r, "kind": "spike" if spike else "shift", "from": vals[dates.index(d) - 1], "to": vals[dates.index(d)]},
                                   ("keep", "exclude") if spike else ("keep",), chosen))

    # -- unfinished last period --------------------------------------------------------------------------------
    if period_months == 1 and aggregation == "sum" and n >= 6 and not undecided_cum:
        prev = [v for v in vals[-4:-1] if v is not None]
        if len(prev) == 3 and statistics.fmean(prev) > 0 and vals[-1] is not None:
            m = statistics.median(prev)
            spread = (max(prev) - min(prev)) / m if m else 1
            if spread < 0.5 and vals[-1] < 0.5 * m:
                out.append(Finding("partial_last", "warn", dates[-1].isoformat(), {"last": vals[-1], "usual": m}, ("drop", "keep"), fixes.get("drop_last")))

    # -- not enough history ------------------------------------------------------------------------------------
    if n < 12:
        out.append(Finding("short", "info", None, {"points": n, "enough_for_realism": n >= 6}))
    return out


# -- applying the decisions ----------------------------------------------------------------------------------------
def apply_fixes(points, period_months: int, fixes: dict | None) -> list[tuple[date, float]]:
    """The series the user has agreed to: excluded points removed, running totals converted, unfinished last period dropped, gaps filled."""
    fixes = fixes or {}
    pts = dict(sorted((d, float(v)) for d, v in points))
    for iso in fixes.get("exclude") or []:
        pts.pop(date.fromisoformat(iso), None)
    if fixes.get("cumulative") == "to_period" and pts:
        out: dict[date, float] = {}
        prev: tuple[date, float] | None = None
        for d in sorted(pts):
            contiguous = prev is not None and prev[0].year == d.year and _gap(prev[0], d, period_months) == 1
            if contiguous:
                out[d] = pts[d] - prev[1]
            elif d.month <= period_months:        # first period of a year: the running total starts here
                out[d] = pts[d]
            # otherwise the previous total is unknown: the period cannot be derived and is left out
            prev = (d, pts[d])
        pts = out
    if fixes.get("drop_last") == "drop" and pts:
        pts.pop(max(pts))
    if fixes.get("gaps") in ("interpolate", "zero") and len(pts) >= 2:
        dates, vals = to_grid(sorted(pts.items()), period_months)
        for i, (d, v) in enumerate(zip(dates, vals)):
            if v is not None:
                continue
            if fixes["gaps"] == "zero":
                pts[d] = 0.0
                continue
            lo = next(j for j in range(i - 1, -1, -1) if vals[j] is not None)
            hi = next(j for j in range(i + 1, len(vals)) if vals[j] is not None)
            pts[d] = vals[lo] + (vals[hi] - vals[lo]) * (i - lo) / (hi - lo)
    return sorted(pts.items())


def _gap(a: date, b: date, period_months: int) -> int:
    return ((b.year - a.year) * 12 + b.month - a.month) // max(1, period_months)
