"""Reality check: is a target realistic, judged against the organization's OWN history?

Pure numbers, no model: the verdict is reproducible and every figure can be shown as evidence.
(The AI only explains it — see app/ai/tasks/explain_reality.py.)

Method
  * "improvement" = signed change toward the goal (up for higher_better, down for lower_better), relative to the start
    value, or absolute when the series has zeros/negatives.
  * required = the improvement the target asks for between `as_of` and `end_date`.
  * history  = every comparable window of the same length in the series: improvement from period t to t+h.
  * the verdict compares `required` with that distribution (percentile, median, p75, p90, best).
  * with >= 24 monthly points and material seasonality, both history and goal are compared de-seasonalised, so a
    December target is not judged against a July start.
"""
from __future__ import annotations

import math
import statistics
from datetime import date

LEVELS = ("realistic", "ambitious", "stretch", "unrealistic", "insufficient")


def months_between(a: date, b: date) -> int:
    return round((b - a).days / 30.4375)


def quantile(xs: list[float], q: float) -> float:
    s = sorted(xs)
    if not s:
        raise ValueError("empty")
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def to_grid(points: list[tuple[date, float]], period_months: int) -> tuple[list[date], list[float | None]]:
    """Consecutive periods from first to last; a period with no data is None (never invented)."""
    pts = dict(sorted(points))
    first, last = min(pts), max(pts)
    dates, y, m = [], first.year, first.month
    while (y, m) <= (last.year, last.month):
        dates.append(date(y, m, 1))
        m += period_months
        while m > 12:
            y, m = y + 1, m - 12
    return dates, [pts.get(d) for d in dates]


def seasonal_factors(dates: list[date], vals: list[float | None]) -> dict[int, float] | None:
    """Month-of-year factors (mean 1.0) from year-over-year-detrended values; None when there is not enough to say."""
    by_year: dict[int, list[float]] = {}
    for d, v in zip(dates, vals):
        if v is not None:
            by_year.setdefault(d.year, []).append(v)
    full = {y for y, v in by_year.items() if len(v) >= 10}
    if len(full) < 2:
        return None
    ratios: dict[int, list[float]] = {}
    for d, v in zip(dates, vals):
        if v is not None and d.year in full:
            mean = sum(by_year[d.year]) / len(by_year[d.year])
            if mean > 0:
                ratios.setdefault(d.month, []).append(v / mean)
    if len(ratios) < 12:
        return None
    f = {m: sum(r) / len(r) for m, r in ratios.items()}
    norm = sum(f.values()) / 12
    return {m: x / norm for m, x in f.items()}


def _imp(a: float, b: float, d: int, relative: bool) -> float:
    return d * (b - a) / abs(a) if relative else d * (b - a)


def _value_at(start: float, imp: float, d: int, relative: bool) -> float:
    return start + d * imp * abs(start) if relative else start + d * imp


def assess(points, *, start: float, target: float, as_of: date, end_date: date, direction: str = "higher_better", period_months: int = 1, relative: bool | None = None) -> dict:
    d = 1 if direction == "higher_better" else -1
    pts = sorted((p, float(v)) for p, v in points if v is not None)
    notes: list[str] = []
    months = max(1, months_between(as_of, end_date))
    h = max(1, round(months / period_months))
    dates, vals = to_grid(pts, period_months) if len(pts) >= 2 else ([], [])
    n = len([v for v in vals if v is not None])
    latest = pts[-1][1] if pts else None
    natural = start > 0 and all(v > 0 for _, v in pts)
    relative = natural if relative is None else (relative and natural)   # a rate (%) is judged in points, never as "% of a %"
    if not relative and relative is not False and not natural:
        notes.append("negative_values")
    if latest is not None and latest != 0 and abs(start - latest) / abs(latest) > 0.05:
        notes.append("start_differs")

    # seasonality (monthly series with two or more full years)
    seasonal, f = False, None
    if period_months == 1 and len(dates) >= 24:
        f = seasonal_factors(dates, vals)
        if f and (max(f.values()) - min(f.values())) > 0.12:
            seasonal = True
    else:
        notes.append("short_history")
    work = vals
    s0, t0 = start, target
    if seasonal:
        work = [None if v is None else v / f[dt.month] for dt, v in zip(dates, vals)]
        start_month = pts[-1][0].month if "start_differs" not in notes else as_of.month
        s0, t0 = start / f[start_month], target / f[end_date.month]
        if abs(f[end_date.month] / f[start_month] - 1) > 0.10:
            notes.append("seasonal_end")

    if latest and latest > 0 and target > 0 and (target / latest > 8 or target / latest < 0.125):
        notes.insert(0, "scale_mismatch")          # 60 against a series that lives around 8,000,000: probably a unit or typing slip
    required = _imp(s0, t0, d, relative)
    if required <= 0:
        notes.append("already_met")

    windows = [_imp(work[i], work[i + h], d, relative) for i in range(len(work) - h)
               if work[i] is not None and work[i + h] is not None and work[i] != 0] if work else []
    steps = [_imp(work[i], work[i + 1], d, relative) for i in range(len(work) - 1)
             if work[i] is not None and work[i + 1] is not None and work[i] != 0] if work else []
    hist = None
    if windows:
        hist = {"n_points": n, "span_months": len(dates) * period_months, "windows": len(windows), "median": quantile(windows, .5),
                "p25": quantile(windows, .25), "p75": quantile(windows, .75), "p90": quantile(windows, .9), "best": max(windows), "worst": min(windows)}
    else:
        hist = {"n_points": n, "span_months": len(dates) * period_months, "windows": 0}

    verdict = {"direction": direction, "measure": "relative" if relative else "absolute", "start": start, "target": target,
               "months": months, "periods": h, "period_months": period_months, "required": required, "hist": hist, "notes": notes,
               "seasonal": seasonal, "percentile": None, "range": None, "latest": latest}
    if n < 6 or len(windows) < 3:
        if windows:
            notes.append("few_windows")
        verdict["level"] = "insufficient"
        verdict["facts"] = _facts(verdict)
        return verdict

    if len(windows) < 8:
        notes.append("few_windows")
    if steps and len(steps) >= 5:
        sd = statistics.pstdev(steps)
        if relative and sd > 0.15:
            notes.append("volatile")
        if hist["best"] - hist["worst"] < (0.02 if relative else 1e-9):
            notes.append("flat_history")
    recent = [v for v in work[-6:] if v is not None]
    if len(recent) >= 4:
        slope = (recent[-1] - recent[0]) / (len(recent) - 1)
        scale = abs(sum(recent) / len(recent)) or 1.0
        if d * slope / scale * h < -0.02 and required > 0:
            notes.append("declining_trend")

    # A very regular history has almost no spread, which would turn the tiniest excess into "unrealistic".
    # Never judge with less tolerance than a small margin (4 points relative; 5% of the typical level absolute).
    level_scale = statistics.fmean(abs(v) for v in work if v is not None) or 1.0
    floor = 0.04 if relative else 0.05 * level_scale
    med = hist["median"]
    t75, t90 = max(hist["p75"], med + 0.5 * floor), max(hist["p90"], med + floor)
    tbest = max(hist["best"] * 1.15 if hist["best"] > 0 else hist["best"], hist["best"] + 0.5 * floor)
    hist["tolerance"] = floor
    verdict["percentile"] = 100.0 * sum(1 for w in windows if w < required) / len(windows)
    best = hist["best"]
    if required <= t75:
        level = "realistic"
    elif required <= t90:
        level = "ambitious"
    elif required <= tbest:
        level = "stretch"
    else:
        level = "unrealistic"
    if required <= 0:
        level = "realistic"
    verdict["level"] = level
    verdict["ratio_best"] = (required / best) if best > 0 else None
    # the same improvements expressed as target values, so the user sees what would be defensible
    to_val = lambda imp: _value_at(start, imp if not seasonal else imp, d, relative)
    verdict["range"] = {"low": to_val(hist["p25"]), "typical": to_val(hist["median"]), "high": to_val(t90), "max": to_val(max(best, tbest if best > 0 else best)),
                        "p75": to_val(t75), "best": to_val(max(best, t90 + 0.5 * floor))}
    # the usual pace comes from the SAME comparable windows as the verdict (median window change, compounded like the required pace),
    # so "needed 5% a month vs. usually 1.3%" can never contradict "needed 34% in 6 months vs. usually 8%"
    verdict["monthly"] = {"required": _monthly(required, months, relative), "typical": _monthly(hist["median"], months, relative)}
    verdict["facts"] = _facts(verdict)
    return verdict


def _monthly(req: float, months: int, relative: bool):
    if relative and req > -1:
        return (1 + req) ** (1 / max(1, months)) - 1
    return req / max(1, months)


def _facts(v: dict) -> list[float]:
    h = v.get("hist") or {}
    xs = [v["start"], v["target"], v["months"], v["required"], v.get("percentile"), h.get("n_points"), h.get("windows"), h.get("median"), h.get("p75"),
          h.get("p90"), h.get("best"), h.get("worst"), v.get("latest")]
    xs += list((v.get("range") or {}).values()) + [v.get("ratio_best")] + list((v.get("monthly") or {}).values())
    return [float(x) for x in xs if x is not None]


def nice(x: float, toward: float | None = None) -> float:
    """Round a number the way a person would set it: 3 significant digits (2 decimals below 10).
    With `toward`, rounds in that direction, so a suggested level never ends up beyond what history supports."""
    if x is None:
        return x
    digits = 2 if abs(x) < 10 else 3 - int(math.floor(math.log10(abs(x)))) - 1
    if toward is None:
        r = round(x, digits)
    else:
        k = 10 ** digits
        r = (math.floor(x * k) if toward < x else math.ceil(x * k)) / k
        r = round(r, max(digits, 0)) if digits > 0 else float(round(r, digits))
        if toward == x:
            r = x
    return float(r) if digits <= 0 else r


def levels(points, *, start: float, as_of: date, end_date: date, direction: str = "higher_better", period_months: int = 1, relative: bool | None = None) -> dict | None:
    """Three defensible targets from the organization's own history, for the horizon as_of -> end_date.

        conservative = what 3 of 4 comparable periods achieved or beat   (verdict: realistic)
        ambitious    = what the best tenth achieved                      (verdict: ambitious)
        stretch      = the best the organization has ever done           (verdict: stretch)

    Returns None when the history is too short to say (never a guess)."""
    v = assess(points, start=start, target=start, as_of=as_of, end_date=end_date, direction=direction, period_months=period_months, relative=relative)
    r = v.get("range")
    if v["level"] == "insufficient" or not r:
        return None
    vals = [r["p75"], r["high"], r["best"]]
    if direction == "higher_better":
        vals = [max(x, start) for x in vals]
    else:
        vals = [min(x, start) for x in vals]
    out = [nice(x, toward=start) for x in vals]
    return {"conservative": out[0], "ambitious": out[1], "stretch": out[2], "months": v["months"], "periods": v["periods"], "windows": v["hist"]["windows"],
            "measure": v["measure"], "notes": v["notes"], "typical": nice(r["typical"]), "low": nice(r["low"])}


def project(points, *, as_of: date, end_date: date, direction: str = "higher_better", period_months: int = 1, relative: bool | None = None) -> dict | None:
    """Where the series is expected to be at `end_date`, as a RANGE taken from what comparable periods did in the past
    (25th / median / 75th percentile of the change over the same horizon, applied to the latest value). None when history is too short."""
    pts = sorted((p, float(v)) for p, v in points if v is not None)
    if not pts:
        return None
    latest = pts[-1][1]
    v = assess(pts, start=latest, target=latest, as_of=as_of, end_date=end_date, direction=direction, period_months=period_months, relative=relative)
    r = v.get("range")
    if v["level"] == "insufficient" or not r:
        return None
    lo, hi = sorted((r["low"], r["p75"]))
    return {"latest": latest, "low": lo, "mid": r["typical"], "high": hi, "best": r["best"], "windows": v["hist"]["windows"], "months": v["months"], "notes": v["notes"]}
