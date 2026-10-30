"""The wider chart vocabulary of the data page: share, ranking, bars, stacked, growth, cumulative, scatter, table, kpi.

Same rule as the rest of the page: a model only picks the kind and its few options (a spec); every number and every pixel is computed here from
the organization's own series. Each builder returns {"kind", "title", "svg"?, "rows"?, "insight", "unit", ...} and None when the data cannot support it.
Charts are plain SVG with `dv-*` classes (styled in dash.css) so they follow the theme; the SVG is left-to-right (axes), the text runs bidi.
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import date
from xml.sax.saxutils import escape

from app.core import formatting as F
from app.core.charts import nice_ticks
from app.core.i18n import t
from app.modules.data import insights as I

NEW_KINDS = ("share", "ranking", "bars", "stacked", "growth", "cumulative", "scatter", "table", "kpi")
NEEDS_BRANCHES = ("share", "ranking", "stacked")
BY = ("month", "quarter", "year")
PALETTE = ("#5864FF", "#0E8F9B", "#7A4DD8", "#C23B8A", "#162447", "#E08A00", "#8A93A8")
GOOD, BAD = "#11713f", "#b4231f"


def _e(s) -> str:
    return escape(str(s), {'"': "&quot;"})


def _tick(v: float) -> str:
    a = abs(v)
    if a >= 1_000_000_000:
        return F.fmt_number(v / 1e9, 1) + " " + t("data.dash.v.bn")
    if a >= 1_000_000:
        return F.fmt_number(v / 1e6, 1) + " " + t("data.dash.v.mn")
    if a >= 10_000:
        return F.fmt_number(v / 1e3, 0) + " " + t("data.dash.v.k")
    return F.fmt_number(v, 0 if a >= 10 or float(v).is_integer() else 1)


def _svg(w: int, h: int, body: str, label: str) -> str:
    return (f'<svg class="dv" viewBox="0 0 {w} {h}" role="img" aria-label="{_e(label)}" direction="ltr" preserveAspectRatio="xMidYMid meet">{body}</svg>')


def _txt(x, y, s, cls="dv-t", anchor="middle", extra="") -> str:
    return f'<text class="{cls}" x="{x:g}" y="{y:g}" text-anchor="{anchor}" {extra}>{_e(s)}</text>'


# -- grouping --------------------------------------------------------------------------------------------------------------------------
def _key(d: date, by: str):
    return (d.year, d.month) if by == "month" else (d.year, (d.month - 1) // 3 + 1) if by == "quarter" else (d.year,)


def _span(by: str) -> int:
    return {"month": 1, "quarter": 3, "year": 12}[by]


def group(pts: list[tuple[date, float]], by: str, aggregation: str, period_months: int = 1) -> list[dict]:
    """Points -> one value per month / quarter / year. Incomplete groups are dropped for sums (half a year is not a year), kept for averages and last values."""
    if period_months >= _span(by):
        by = "month" if period_months == 1 else "quarter" if period_months == 3 else "year"
    buckets: dict[tuple, list[tuple[date, float]]] = defaultdict(list)
    for d, v in pts:
        buckets[_key(d, by)].append((d, v))
    need = _span(by) // max(1, period_months)
    out = []
    for k in sorted(buckets):
        items = buckets[k]
        if aggregation == "sum" and len(items) < need:
            continue
        vals = [v for _, v in items]
        v = sum(vals) if aggregation == "sum" else statistics.mean(vals) if aggregation == "avg" else vals[-1]
        first = items[0][0]
        start = date(first.year, 1 if by == "year" else (first.month if by == "month" else ((first.month - 1) // 3) * 3 + 1), 1)
        out.append({"date": start, "value": v, "n": len(items)})
    return out


def _plabel(d: date, by: str, short: bool = True) -> str:
    from app.modules.data.dashboard import _month_name, period_label
    if by == "year":
        return period_label(d, 12)
    if by == "quarter":
        return period_label(d, 3)
    return f"{_month_name(d)} {str(d.year)[2:]}" if short else period_label(d, 1)


def _pick(m, spec):
    """The series a chart is about: the total, or one named branch."""
    branch = spec.get("branch")
    s = next((b for b in m.branches if b.dimension == branch), None) if branch else None
    return (s or m.total), (s.dimension if s else None)


def _by(m, spec) -> str:
    by = spec.get("by") if spec.get("by") in BY else None
    return by or ("month" if m.period_months == 1 else "quarter" if m.period_months == 3 else "year")


def _grouped(m, s, spec, need: int = 2):
    """Groups at the asked granularity; when the data is too short for it (two full years, say) step down to quarters, then months, rather than draw nothing."""
    by = _by(m, spec)
    chain = {"year": ("year", "quarter", "month"), "quarter": ("quarter", "month"), "month": ("month",)}[by]
    for b in chain:
        if b != "month" or True:
            g = group(s.pairs(), b, m.aggregation, m.period_months)
            if len(g) >= need:
                return g, b
    return [], by


def _limit(groups: list[dict], by: str, spec: dict) -> list[dict]:
    months = spec.get("months")
    if months:
        groups = groups[-max(1, months // _span(by)):] if months // _span(by) >= 2 else groups[-2:]
    return groups[-{"month": 24, "quarter": 12, "year": 10}[by]:]


def _title(spec, default):
    return spec.get("title") or default


# -- bars / growth: columns over time -------------------------------------------------------------------------------------------------------
def _columns(groups, vals, m, *, fmt, signed_colors=False, label="", highlight_last=True, W=900, H=330):
    pt, pb, pr = 26, 40, 16
    lo, hi = min(0, min(vals)), max(0, max(vals))
    ticks = nice_ticks(lo, hi)
    lo, hi = ticks[0], ticks[-1]
    pl = max(48, 16 + 7 * max(len(_tick(x)) for x in ticks))
    iw, ih = W - pl - pr, H - pt - pb
    n = len(vals)
    slot = iw / n
    bw = max(6, min(54, slot * 0.64))
    Y = lambda v: pt + ih - (v - lo) / (hi - lo) * ih
    y0 = Y(0)
    body = "".join(f'<line class="dv-grid" x1="{pl}" x2="{W - pr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>' + _txt(pl - 8, Y(v) + 4, _tick(v), "dv-t dv-y", "end") for v in ticks)
    body += f'<line class="dv-axis" x1="{pl}" x2="{W - pr}" y1="{y0:.1f}" y2="{y0:.1f}"/>'
    step = max(1, math.ceil(n / 10))
    for i, (g, v) in enumerate(zip(groups, vals)):
        x = pl + slot * i + (slot - bw) / 2
        top, h = (Y(v), y0 - Y(v)) if v >= 0 else (y0, Y(v) - y0)
        last = highlight_last and i == n - 1
        if signed_colors:
            style = f'fill="{GOOD if v >= 0 else BAD}"' + ('' if last else ' fill-opacity=".62"')
        else:
            style = 'class="dv-bar' + (' dv-bar--last' if last else '') + '"'
        body += f'<rect {style} x="{x:.1f}" y="{top:.1f}" width="{bw:.1f}" height="{max(h, 1):.1f}" rx="3"><title>{_e(_plabel(g["date"], label, False))}: {_e(fmt(v))}</title></rect>'
        if n <= 14 or last:
            ly = top - 6 if v >= 0 else top + h + 14
            body += _txt(x + bw / 2, ly, fmt(v), "dv-t dv-v" + (" dv-v--last" if last else ""))
        if i % step == 0 or last:
            body += _txt(x + bw / 2, H - 16, _plabel(g["date"], label), "dv-t dv-x")
    return W, H, body


def bars(m, spec):
    s, branch = _pick(m, spec)
    groups, by = _grouped(m, s, spec)
    groups = _limit(groups, by, spec)
    if len(groups) < 2:
        return None
    vals = [g["value"] for g in groups]
    fmt = lambda v: F.fmt_number(v, 0 if abs(v) >= 100 else 1) if abs(v) < 10_000 else _tick(v)      # the unit is in the header, not on every column
    W, H, body = _columns(groups, vals, m, fmt=fmt, label=by)
    hi, lo = max(groups, key=lambda g: g["value"]), min(groups, key=lambda g: g["value"])
    name = m.name if not branch else f"{m.name} — {branch}"
    insight = t("data.dash.v.bars", top=_plabel(hi["date"], by, False), value=F.fmt_value(hi["value"], m.unit), low=_plabel(lo["date"], by, False), low_value=F.fmt_value(lo["value"], m.unit))
    return {"kind": "bars", "title": _title(spec, t("data.dash.v.bars_title." + by, name=name)), "unit": F.unit_text(m.unit), "svg": _svg(W, H, body, name), "insight": insight}


def growth(m, spec):
    s, branch = _pick(m, spec)
    groups, by = _grouped(m, s, spec, need=14 if _by(m, spec) == "month" else 5)
    back = 12
    idx = {g["date"]: g["value"] for g in groups}
    rows = []
    for g in groups:
        prev = idx.get(I.add_months(g["date"], -back))
        ch = I.change(g["value"], prev, m.unit) if prev is not None else None
        v = (ch["abs"] if ch and ch["kind"] == "points" else (ch["rel"] * 100 if ch and ch["rel"] is not None else None)) if ch else None
        if v is not None:
            rows.append((g, v, ch))
    rows = _limit([{"date": g["date"], "value": v, "ch": ch} for g, v, ch in rows], by, spec)
    if len(rows) < 2:
        return None
    pct = not (rows[-1]["ch"]["kind"] == "points")
    suffix = "%" if pct else " " + t("data.dash.points")
    fmt = lambda v: ("+" if v > 0 else "−" if v < 0 else "") + F.fmt_number(abs(v), 1 if abs(v) < 10 else 0) + ("%" if pct else "")
    W, H, body = _columns(rows, [r["value"] for r in rows], m, fmt=fmt, signed_colors=True, label=by)
    last = rows[-1]
    name = m.name if not branch else f"{m.name} — {branch}"
    insight = t("data.dash.v.growth", period=_plabel(last["date"], by, False), delta=fmt(last["value"]) + ("" if pct else suffix), ref=t("data.dash.v.same_last_year"))
    return {"kind": "growth", "title": _title(spec, t("data.dash.v.growth_title", name=name)), "unit": "%" if pct else t("data.dash.points"), "svg": _svg(W, H, body, name), "insight": insight}


# -- stacked ---------------------------------------------------------------------------------------------------------------------------------
def stacked(m, spec):
    if m.aggregation != "sum" or len(m.branches) < 2:
        return None
    by = _by(m, spec)
    per = {b.dimension: {g["date"]: g["value"] for g in group(b.pairs(), by, m.aggregation, m.period_months)} for b in m.branches}
    dates = sorted({d for v in per.values() for d in v})
    dates = _limit([{"date": d} for d in dates], by, spec)
    dates = [x["date"] for x in dates]
    if len(dates) < 2:
        return None
    totals = {k: sum(v.get(d, 0) for d in dates) for k, v in per.items()}
    order = [k for k, _ in sorted(totals.items(), key=lambda kv: -kv[1])]
    keep, rest = order[:6], order[6:]
    series = [(k, [per[k].get(d, 0) for d in dates]) for k in keep]
    if rest:
        series.append((t("data.dash.v.others"), [sum(per[k].get(d, 0) for k in rest) for d in dates]))
    sums = [sum(s[1][i] for s in series) for i in range(len(dates))]
    W, H, pt, pb, pr = 900, 330, 26, 40, 16
    ticks = nice_ticks(0, max(sums))
    hi = ticks[-1]
    pl = max(48, 16 + 7 * max(len(_tick(x)) for x in ticks))
    iw, ih = W - pl - pr, H - pt - pb
    n = len(dates)
    slot, bw = iw / n, max(6, min(54, iw / n * 0.64))
    Y = lambda v: pt + ih - v / hi * ih
    body = "".join(f'<line class="dv-grid" x1="{pl}" x2="{W - pr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>' + _txt(pl - 8, Y(v) + 4, _tick(v), "dv-t dv-y", "end") for v in ticks)
    step = max(1, math.ceil(n / 10))
    for i, d in enumerate(dates):
        x, base = pl + slot * i + (slot - bw) / 2, 0
        for j, (name, vals) in enumerate(series):
            v = vals[i]
            if v <= 0:
                continue
            body += f'<rect x="{x:.1f}" y="{Y(base + v):.1f}" width="{bw:.1f}" height="{Y(base) - Y(base + v):.1f}" fill="{PALETTE[j % len(PALETTE)]}" stroke="#fff" stroke-width="1"><title>{_e(name)} · {_e(_plabel(d, by, False))}: {_e(F.fmt_value(v, m.unit))}</title></rect>'
            base += v
        if i % step == 0 or i == n - 1:
            body += _txt(x + bw / 2, H - 16, _plabel(d, by), "dv-t dv-x")
    legend = [{"name": name, "color": PALETTE[j % len(PALETTE)], "text": F.fmt_percent(sum(vals) / sum(sums), 0)} for j, (name, vals) in enumerate(series)]
    top = legend[0]
    return {"kind": "stacked", "title": _title(spec, t("data.dash.v.stacked_title", name=m.short)), "unit": F.unit_text(m.unit), "svg": _svg(W, H, body, m.name), "legend": legend,
            "insight": t("data.dash.v.stacked", top=top["name"], share=top["text"], name=m.short)}


# -- share (donut) and ranking ---------------------------------------------------------------------------------------------------------
def _branch_rows(m, spec):
    from app.modules.data.dashboard import branches
    b = branches(m, spec)
    return b


def share(m, spec):
    b = _branch_rows(m, spec)
    if not b or not b["share"]:
        return None
    rows = b["rows"]
    keep, rest = rows[:6], rows[6:]
    parts = [(r["name"], r["value"], r["text"]) for r in keep]
    if rest:
        parts.append((t("data.dash.v.others"), sum(r["value"] for r in rest), F.fmt_value(sum(r["value"] for r in rest), m.unit)))
    total = sum(v for _, v, _ in parts)
    W, H, cx, cy, R, r = 360, 300, 180, 150, 120, 74
    body, ang, legend = "", -math.pi / 2, []
    for j, (name, v, txt) in enumerate(parts):
        a = v / total * 2 * math.pi
        a2 = ang + a
        if a >= 2 * math.pi - 1e-6:
            body += f'<circle cx="{cx}" cy="{cy}" r="{(R + r) / 2}" fill="none" stroke="{PALETTE[0]}" stroke-width="{R - r}"/>'
        else:
            large = 1 if a > math.pi else 0
            p = lambda rad, an: (cx + rad * math.cos(an), cy + rad * math.sin(an))
            (x1, y1), (x2, y2), (x3, y3), (x4, y4) = p(R, ang), p(R, a2), p(r, a2), p(r, ang)
            body += (f'<path d="M{x1:.1f} {y1:.1f} A{R} {R} 0 {large} 1 {x2:.1f} {y2:.1f} L{x3:.1f} {y3:.1f} A{r} {r} 0 {large} 0 {x4:.1f} {y4:.1f} Z" '
                     f'fill="{PALETTE[j % len(PALETTE)]}" stroke="#fff" stroke-width="2.5"><title>{_e(name)}: {_e(txt)} · {_e(F.fmt_percent(v / total, 0))}</title></path>')
        legend.append({"name": name, "color": PALETTE[j % len(PALETTE)], "text": F.fmt_percent(v / total, 0), "value": txt})
        ang = a2
    body += _txt(cx, cy - 2, F.fmt_value(total, m.unit) if abs(total) < 10_000 else _tick(total), "dv-t dv-c")
    body += _txt(cx, cy + 20, t("data.dash.v.last_months", n=F.fmt_number(b["months"], 0)), "dv-t dv-x")
    return {"kind": "share", "title": _title(spec, t("data.dash.v.share_title", name=m.short)), "unit": F.unit_text(m.unit), "svg": _svg(W, H, body, m.name), "legend": legend, "insight": b["insight"], "side": True}


def ranking(m, spec):
    b = _branch_rows(m, spec)
    if not b:
        return None
    rows = b["rows"][:12]
    mx = max(abs(r["value"]) for r in rows) or 1
    W, rh = 900, 34
    H = 14 + rh * len(rows)
    lw = 200
    body = ""
    for i, r in enumerate(rows):
        y = 10 + i * rh
        w = max(3, abs(r["value"]) / mx * (W - lw - 150))
        body += _txt(lw - 12, y + 20, r["name"], "dv-t dv-y", "end")
        body += f'<rect class="dv-bar{" dv-bar--last" if i == 0 else ""}" x="{lw}" y="{y + 6}" width="{w:.1f}" height="20" rx="4"><title>{_e(r["name"])}: {_e(r["text"])}</title></rect>'
        body += _txt(lw + w + 8, y + 21, r["text"] + (f" · {r['share']}" if r["share"] else ""), "dv-t dv-v", "start")
    return {"kind": "ranking", "title": _title(spec, t("data.dash.v.ranking_title", name=m.short)), "unit": F.unit_text(m.unit), "svg": _svg(W, H, body, m.name), "insight": b["insight"]}


# -- cumulative: this year against last year ---------------------------------------------------------------------------------------------
def cumulative(m, spec):
    if m.aggregation != "sum" or m.period_months != 1:
        return None
    s, branch = _pick(m, spec)
    pts = s.pairs()
    years = sorted({d.year for d, _ in pts})[-3:]
    cur = years[-1]
    lines = {}
    for y in years:
        acc, line = 0.0, []
        for d, v in sorted((d, v) for d, v in pts if d.year == y):
            acc += v
            line.append((d.month, acc))
        lines[y] = line
    last_month = lines[cur][-1][0]
    if len(lines[cur]) < 2 and len(years) < 2:
        return None
    allv = [v for ln in lines.values() for _, v in ln]
    ticks = nice_ticks(0, max(allv))
    hi = ticks[-1]
    W, H, pt, pb, pr = 900, 330, 20, 40, 24
    pl = max(48, 16 + 7 * max(len(_tick(x)) for x in ticks))
    iw, ih = W - pl - pr, H - pt - pb
    X = lambda mo: pl + (mo - 1) * iw / 11
    Y = lambda v: pt + ih - v / hi * ih
    body = "".join(f'<line class="dv-grid" x1="{pl}" x2="{W - pr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>' + _txt(pl - 8, Y(v) + 4, _tick(v), "dv-t dv-y", "end") for v in ticks)
    from app.modules.data.dashboard import _month_name
    body += "".join(_txt(X(mo), H - 16, _month_name(date(2000, mo, 1)), "dv-t dv-x") for mo in range(1, 13))
    legend = []
    for j, y in enumerate(years):
        ln = lines[y]
        if not ln:
            continue
        col = PALETTE[0] if y == cur else ("#B7BED6" if j == len(years) - 2 else "#DCE0EE")
        d = " ".join(("M" if i == 0 else "L") + f"{X(mo):.1f} {Y(v):.1f}" for i, (mo, v) in enumerate(ln))
        body += f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{3.2 if y == cur else 2}" stroke-linecap="round" stroke-linejoin="round"/>'
        mo, v = ln[-1]
        body += f'<circle cx="{X(mo):.1f}" cy="{Y(v):.1f}" r="{5 if y == cur else 3.5}" fill="{col}" stroke="#fff" stroke-width="2"/>'
        body += _txt(X(mo) if X(mo) < W - 90 else X(mo) + 6, Y(v) - 12, F.fmt_number(v, 0) if abs(v) < 10_000 else _tick(v), "dv-t dv-v" + (" dv-v--last" if y == cur else ""), "middle" if X(mo) < W - 90 else "end")
        legend.append({"name": F._digits(str(y), "ar"), "color": col, "text": ""})
    prev = dict(lines.get(cur - 1, [])).get(last_month)
    now = lines[cur][-1][1]
    ch = I.change(now, prev, m.unit) if prev else None
    from app.modules.data.dashboard import signed
    insight = t("data.dash.v.cumulative", month=_month_name(date(2000, last_month, 1), "wide"), value=F.fmt_value(now, m.unit), prev=F.fmt_value(prev, m.unit), delta=signed(ch, m.unit)) if ch else ""
    name = m.name if not branch else f"{m.name} — {branch}"
    return {"kind": "cumulative", "title": _title(spec, t("data.dash.v.cumulative_title", name=name)), "unit": F.unit_text(m.unit), "svg": _svg(W, H, body, name), "legend": legend, "insight": insight}


# -- scatter: one measure against another ---------------------------------------------------------------------------------------------------
def scatter(m, m2, spec):
    a, b = dict(m.pts), dict(m2.pts)
    both = sorted(set(a) & set(b))
    if len(both) < 6:
        return None
    xs, ys = [a[d] for d in both], [b[d] for d in both]
    r = _pearson(xs, ys)
    tx, ty = nice_ticks(min(xs), max(xs)), nice_ticks(min(ys), max(ys))
    W, H, pt, pb, pr = 900, 370, 34, 46, 20
    pl = max(52, 18 + 7 * max(len(_tick(x)) for x in ty))
    iw, ih = W - pl - pr, H - pt - pb
    X = lambda v: pl + (v - tx[0]) / (tx[-1] - tx[0]) * iw
    Y = lambda v: pt + ih - (v - ty[0]) / (ty[-1] - ty[0]) * ih
    body = "".join(f'<line class="dv-grid" x1="{pl}" x2="{W - pr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>' + _txt(pl - 8, Y(v) + 4, _tick(v), "dv-t dv-y", "end") for v in ty)
    body += "".join(_txt(X(v), H - 24, _tick(v), "dv-t dv-x") for v in tx)
    if len(set(xs)) > 1:
        mx, my = statistics.mean(xs), statistics.mean(ys)
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
        c0 = my - slope * mx
        x1, x2 = tx[0], tx[-1]
        body += f'<line class="dv-fit" x1="{X(x1):.1f}" y1="{Y(max(ty[0], min(ty[-1], c0 + slope * x1))):.1f}" x2="{X(x2):.1f}" y2="{Y(max(ty[0], min(ty[-1], c0 + slope * x2))):.1f}"/>'
    for i, d in enumerate(both):
        last = i == len(both) - 1
        body += (f'<circle cx="{X(xs[i]):.1f}" cy="{Y(ys[i]):.1f}" r="{7 if last else 5}" fill="{PALETTE[0]}" fill-opacity="{1 if last else .55}" stroke="#fff" stroke-width="1.5">'
                 f'<title>{_e(_plabel(d, "month", False))}: {_e(F.fmt_value(xs[i], m.unit))} · {_e(F.fmt_value(ys[i], m2.unit))}</title></circle>')
    body += _txt(pl + iw / 2, H - 4, f"{m.short} ({F.unit_text(m.unit)})" if m.unit else m.short, "dv-t dv-axis-title")
    body += _txt(pl, 14, f"{m2.short} ({F.unit_text(m2.unit)})" if m2.unit else m2.short, "dv-t dv-axis-title", "start")
    word = "none" if r is None else "strong_up" if r >= .7 else "up" if r >= .35 else "strong_down" if r <= -.7 else "down" if r <= -.35 else "weak"
    insight = t("data.dash.v.scatter_" + word, a=m.short, b=m2.short, r=F.fmt_number(abs(r), 2) if r is not None else "") if r is not None else ""
    return {"kind": "scatter", "title": _title(spec, t("data.dash.v.scatter_title", a=m.short, b=m2.short)), "unit": "", "svg": _svg(W, H, body, m.name), "insight": insight}


def _pearson(xs, ys):
    if len(xs) < 3 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy) if sx and sy else None


# -- table and kpi -----------------------------------------------------------------------------------------------------------------------------
def table(m, spec):
    from app.modules.data.dashboard import _tone, signed
    s, branch = _pick(m, spec)
    groups, by = _grouped(m, s, spec)
    idx = {g["date"]: g["value"] for g in groups}
    rows = []
    for g in reversed(groups[-12:]):
        prev = idx.get(I.add_months(g["date"], -12))
        ch = I.change(g["value"], prev, m.unit) if prev is not None else None
        rows.append({"period": _plabel(g["date"], by, False), "value": F.fmt_value(g["value"], m.unit), "delta": signed(ch, m.unit) if ch else "", "tone": _tone(ch, m.direction) if ch else "flat"})
    if len(rows) < 2:
        return None
    name = m.name if not branch else f"{m.name} — {branch}"
    return {"kind": "table", "title": _title(spec, name), "unit": F.unit_text(m.unit), "rows": rows, "insight": "", "head": [t("data.dash.v.col_period"), t("data.dash.v.col_value"), t("data.dash.v.col_change")]}


def kpi(m, spec):
    from app.modules.data.dashboard import _mini, _tone, change_phrase, period_label
    s, branch = _pick(m, spec)
    pts = s.pairs()
    f = I.facts(pts, unit=m.unit, direction=m.direction, aggregation=m.aggregation, period_months=m.period_months)
    if not f:
        return None
    vs = f.vs_year or f.vs_prev
    ref = period_label(I.add_months(f.last, -12 if f.vs_year else -m.period_months), m.period_months)
    vals = [v for _, v in pts[-24:]]
    return {"kind": "kpi", "title": _title(spec, m.name if not branch else f"{m.name} — {branch}"), "unit": F.unit_text(m.unit), "value": F.fmt_value(f.latest, m.unit), "period": period_label(f.last, m.period_months),
            "phrase": change_phrase(vs, m.unit, ref), "tone": f.tone, "mini": _mini(pts[-24:], min(vals), max(vals), 360, 70), "insight": ""}


BUILDERS = {"share": share, "ranking": ranking, "bars": bars, "stacked": stacked, "growth": growth, "cumulative": cumulative, "table": table, "kpi": kpi}
