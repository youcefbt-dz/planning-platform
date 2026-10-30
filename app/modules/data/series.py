"""Mapped table -> clean time series (one per measure, plus one per category value). Pure, no Flask."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.modules.data.ingest.parsers import parse_number, parse_period
from app.modules.data.ingest.table import Table
from app.modules.data.quality import apply_fixes

PERIOD_MONTHS = {"day": 1, "month": 1, "quarter": 3, "year": 12}


@dataclass
class SeriesData:
    name: str
    unit: str
    direction: str
    aggregation: str
    dimension: str | None
    points: list[tuple[date, float]]
    period_months: int = 1
    notes: list[str] = field(default_factory=list)
    column: int = -1                      # the measure column of the table this series comes from


def floor_period(d: date, months: int) -> date:
    if months == 12:
        return date(d.year, 1, 1)
    if months == 3:
        return date(d.year, ((d.month - 1) // 3) * 3 + 1, 1)
    return date(d.year, d.month, 1)


def _granularity(table: Table, date_col: int, date_kind: str | None) -> int:
    return PERIOD_MONTHS.get(date_kind or "month", 1)


def build_series(table: Table, columns: list[dict], *, date_kind: str | None = None, max_dims: int = 12, fixes: dict | None = None) -> list[SeriesData]:
    """`fixes` = what the user decided about odd values, per measure column index (see quality.py). None = the raw series."""
    roles = [c.get("role") for c in columns]
    if "date" not in roles or "measure" not in roles:
        return []
    di = roles.index("date")
    dims = [i for i, r in enumerate(roles) if r == "dimension"]
    dim_i = dims[0] if dims else None
    pm = _granularity(table, di, date_kind)
    out: list[SeriesData] = []
    for mi in [i for i, r in enumerate(roles) if r == "measure"]:
        spec = columns[mi]
        agg = spec.get("aggregation") if spec.get("aggregation") in ("sum", "avg", "last") else "sum"
        cells: dict[tuple, list[float]] = {}
        for row in table.rows:
            p = parse_period(row[di])
            n = parse_number(row[mi])
            if not p or n is None:
                continue
            key = (floor_period(p[0], pm), str(row[dim_i]).strip() if dim_i is not None and row[dim_i] is not None else None)
            cells.setdefault(key, []).append(n[0])

        def reduce(vals):
            return sum(vals) / len(vals) if agg == "avg" else vals[-1] if agg == "last" else sum(vals)

        per_dim: dict[str | None, dict[date, float]] = {}
        for (period, dim), vals in cells.items():
            per_dim.setdefault(dim, {})[period] = reduce(vals)
        totals: dict[date, float] = {}
        if dim_i is None or None in per_dim and len(per_dim) == 1:
            totals = per_dim.get(None, {})
        else:
            by_period: dict[date, list[float]] = {}
            if agg == "avg":                                  # an average of all rows, not an average of averages
                for (period, _), vals in cells.items():
                    by_period.setdefault(period, []).extend(vals)
                totals = {p: sum(v) / len(v) for p, v in by_period.items()}
            else:                                             # flows add up; levels (headcount, stock) add up across categories
                for series in per_dim.values():
                    for period, v in series.items():
                        totals[period] = totals.get(period, 0.0) + v
        label = spec.get("label") or f"#{mi + 1}"
        base = dict(unit=spec.get("unit", ""), direction=spec.get("direction", "higher_better"), aggregation=agg, period_months=pm, column=mi)
        fx = (fixes or {}).get(str(mi))
        fix = (lambda items: apply_fixes(items, pm, fx)) if fx else (lambda items: sorted(items))
        if totals:
            out.append(SeriesData(name=label, dimension=None, points=fix(totals.items()), **base))
        if dim_i is not None and len([k for k in per_dim if k]) >= 2:
            ranked = sorted((k for k in per_dim if k), key=lambda k: -sum(abs(v) for v in per_dim[k].values()))[:max_dims]
            for k in ranked:
                out.append(SeriesData(name=f"{label} — {k}", dimension=k, points=fix(per_dim[k].items()), **base))
    return [s for s in out if len(s.points) >= 2]
