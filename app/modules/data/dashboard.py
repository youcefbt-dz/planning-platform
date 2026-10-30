"""The visual data page: from a validated chart spec to drawable geometry, and the few findings worth a manager's attention.

Everything on screen is computed here, by code, from the organization's own series. A model may only choose WHICH charts to show
(a spec) or ask a clarifying question; `validate_spec` checks every spec against the series the organization owns before anything is drawn.

Page = measure tabs -> "what deserves attention" (ranked findings) -> one main chart -> drivers (bridge) -> branches (small multiples) -> season.

Kinds
  trend         one line (total or one branch), the same months a year earlier behind it, the odd months marked, and the goal if one is linked
  branches      small multiples: each branch's last 24 months on one shared scale, with its share and change
  contribution  a bridge from the last 12 months a year ago to the last 12 months, branch by branch (a plain bar list for averages)
  heatmap       month by year, shaded by rank (numbers on hover only), to see the season at a glance
  compare       two different measures on one chart, both indexed to 100 at the start so that different units can be read together, and how closely they move
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date

from app.core import formatting as F
from app.core import i18n
from app.core.charts import nice_ticks
from app.core.i18n import t
from app.modules.data import draw
from app.modules.data import insights as I
from app.modules.data.models import Series

KINDS = ("trend", "branches", "contribution", "heatmap", "compare", "share", "ranking", "bars", "stacked", "growth", "cumulative", "scatter", "table", "kpi")
SEP = " — "


@dataclass
class Measure:
    id: str
    name: str
    unit: str
    direction: str
    aggregation: str
    period_months: int
    total: Series
    branches: list[Series] = field(default_factory=list)
    dataset_name: str = ""

    @property
    def pts(self) -> list[tuple[date, float]]:
        return self.total.pairs()

    @property
    def short(self) -> str:
        return self.name.split("(")[0].strip().rstrip("%").strip() or self.name


def measures(series: list[Series]) -> list[Measure]:
    """Group the flat list of series into measures: the total and its branches (series named "<measure> — <branch>")."""
    totals = [s for s in series if s.dimension is None]
    out = []
    for tot in totals:
        prefix = tot.name + SEP
        branches = [s for s in series if s.dimension is not None and s.dataset_id == tot.dataset_id and s.name.startswith(prefix)]
        out.append(Measure(str(tot.id), tot.name, tot.unit or "", tot.direction, tot.aggregation or "sum", tot.period_months or 1, tot, branches, tot.dataset.name if tot.dataset else ""))
    return out


# -- spec ---------------------------------------------------------------------------------------------------------------------
def validate_spec(raw: dict | None, ms: list[Measure]) -> dict | None:
    """Return a clean spec or None. Only known kinds, only measures/branches that exist, only sane numbers."""
    if not isinstance(raw, dict) or raw.get("kind") not in KINDS:
        return None
    m = next((x for x in ms if x.id == str(raw.get("measure"))), None)
    if m is None:
        return None
    names = {b.dimension for b in m.branches}
    branch = raw.get("branch") if raw.get("branch") in names else None
    months = raw.get("months")
    months = months if isinstance(months, int) and not isinstance(months, bool) and 3 <= months <= 120 else None
    if raw["kind"] in ("branches", "contribution", "share", "ranking", "stacked") and len(m.branches) < 2:
        return None
    by = raw.get("by") if raw.get("by") in ("month", "quarter", "year") else None
    out = {"kind": raw["kind"], "measure": m.id, "branch": branch, "months": months, "title": str(raw.get("title") or "")[:90]}
    if by:
        out["by"] = by
    if raw["kind"] in ("compare", "scatter"):
        m2 = next((x for x in ms if x.id == str(raw.get("measure2")) and x.id != m.id), None)
        if m2 is None:
            return None
        out["measure2"] = m2.id
        out["branch"] = None
    return out


# -- text helpers ---------------------------------------------------------------------------------------------------------------
def _month_name(d: date, width: str = "abbreviated") -> str:
    loc = F._month_locale(i18n.current_lang())
    return loc.months["format"][width][d.month]


def period_label(d: date, months: int = 1) -> str:
    if months == 12:
        return F._digits(str(d.year), "ar")
    if months == 3:
        return F._digits(f"{t('data.dash.q')}{(d.month - 1) // 3 + 1} {d.year}", "ar")
    return F.fmt_date(d, "month")


def amount(ch: dict | None, unit: str) -> str:
    """The size of a change as words: '3.2 نقطة' for a % series, '7.4%' otherwise (or the raw amount if the base was zero)."""
    if ch is None:
        return ""
    if ch["kind"] == "points":
        return f"{F.fmt_number(abs(ch['abs']), 1)} {t('data.dash.points')}"
    if ch["rel"] is None:
        return F.fmt_value(abs(ch["abs"]), unit)
    return F.fmt_percent(abs(ch["rel"]), 1 if abs(ch["rel"]) < 0.1 else 0)


def _flat(ch: dict | None) -> bool:
    if ch is None:
        return True
    if ch["kind"] == "points":
        return abs(ch["abs"]) < 0.05
    return ch["rel"] is None and ch["abs"] == 0 or (ch["rel"] is not None and abs(ch["rel"]) < 0.0005)


def change_phrase(ch: dict | None, unit: str, ref: str) -> str:
    """'أعلى بـ7.4% من أغسطس 2025' / 'أقل بـ…' / 'دون تغيّر يُذكر عن …'"""
    if ch is None:
        return ""
    if _flat(ch):
        return t("data.dash.same", ref=ref)
    return t("data.dash.up" if ch["abs"] > 0 else "data.dash.down", amt=amount(ch, unit), ref=ref)


def short_change(ch: dict | None, unit: str) -> str:
    """'أعلى بـ7%' / 'أقل بـ…' / 'دون تغيّر' without a reference period (the reference is said once, around it)."""
    if ch is None:
        return ""
    if _flat(ch):
        return t("data.dash.flat")
    return t("data.dash.up_s" if ch["abs"] > 0 else "data.dash.down_s", amt=amount(ch, unit))


def signed(ch: dict | None, unit: str) -> str:
    if ch is None or _flat(ch):
        return "="
    return ("+" if ch["abs"] > 0 else "−") + amount(ch, unit)


def _tone(ch: dict | None, direction: str) -> str:
    if ch is None:
        return "flat"
    return I.tone_of(ch["value"] if ch.get("value") is not None else ch["abs"], direction)


def _gv(ch: dict | None) -> float | None:
    """Growth as one comparable number: a ratio for ordinary series, points/100 for % series."""
    if ch is None:
        return None
    if ch["kind"] == "points":
        return ch["abs"] / 100.0
    return ch["rel"]


# -- tabs: one compact line per measure -----------------------------------------------------------------------------------------------
def tabs(ms: list[Measure]) -> list[dict]:
    """The measure switcher. One number and ONE comparison (against a year ago, else the previous period) per measure; nothing else."""
    out = []
    for m in ms:
        f = I.facts(m.pts, unit=m.unit, direction=m.direction, aggregation=m.aggregation, period_months=m.period_months)
        if f is None:
            continue
        ch = f.vs_year or f.vs_prev
        ref = t("data.dash.vs_year") if f.vs_year else t("data.dash.vs_prev")
        arrow = "minus" if _flat(ch) else "trending-up" if ch["abs"] > 0 else "trending-down"
        out.append({"m": m, "value": F.fmt_value(f.latest, m.unit), "period": period_label(f.last, m.period_months), "chip": short_change(ch, m.unit),
                    "ref": ref, "tone": f.tone, "arrow": arrow})
    return out


# -- findings: what deserves attention ---------------------------------------------------------------------------------------------------------
def linked_targets(org_id: int, series_id: int) -> list[dict]:
    """Targets of key results measured by this series (read through the shared link table; empty when goals are off)."""
    from sqlalchemy import text

    from app.extensions import db

    try:
        rows = db.session.execute(text(
            "SELECT k.title, k.target_value FROM key_result k JOIN link l ON l.source_id = k.id AND l.source_type = 'key_result' "
            "AND l.target_type = 'series' AND l.kind = 'measured_by' WHERE l.target_id = :s AND l.org_id = :o AND k.org_id = :o ORDER BY k.id"),
            {"s": series_id, "o": org_id}).fetchall()
    except Exception:
        return []
    return [{"title": r[0], "value": float(r[1])} for r in rows]


def attention(m: Measure) -> list[dict]:
    """Up to four findings for the chosen measure, most important first. Each is one sentence made only of computed facts and points at a chart below."""
    f = I.facts(m.pts, unit=m.unit, direction=m.direction, aggregation=m.aggregation, period_months=m.period_months)
    if f is None:
        return []
    out: list[dict] = []
    nm = m.short

    # 1. the year, in one sentence
    if f.last12 is not None and f.prior12 is not None and f.vs_last12:
        word = {"sum": "year_sum", "avg": "year_avg"}.get(m.aggregation, "year_last")
        out.append({"tone": _tone(f.vs_last12, m.direction), "icon": "calendar", "anchor": "main",
                    "text": t(f"data.dash.f.{word}", name=nm, now=F.fmt_value(f.last12, m.unit), phrase=change_phrase(f.vs_last12, m.unit, t("data.dash.prev_year")))})
    elif f.vs_year or f.vs_prev:
        ch = f.vs_year or f.vs_prev
        ref = period_label(I.add_months(f.last, -12 if f.vs_year else -m.period_months), m.period_months)
        out.append({"tone": f.tone, "icon": "calendar", "anchor": "main",
                    "text": t("data.dash.f.latest", name=nm, now=F.fmt_value(f.latest, m.unit), period=period_label(f.last, m.period_months), phrase=change_phrase(ch, m.unit, ref))})

    # 2. is the pace changing? last 3 months against the same 3 a year earlier, versus the whole year
    if m.period_months == 1 and f.vs_last12:
        n3 = I.aggregate(m.pts, 3, f.last, m.aggregation)
        b3 = I.aggregate(m.pts, 3, f.last, m.aggregation, offset=12)
        ch3 = I.change(n3, b3, m.unit) if n3 is not None and b3 is not None else None
        g3, g12 = _gv(ch3), _gv(f.vs_last12)
        if g3 is not None and g12 is not None:
            step = 0.015 if m.unit.strip() == "%" else 0.04
            if (g3 >= 0) != (g12 >= 0) and abs(g3 - g12) >= step / 2:
                verb = "to_down" if g3 < 0 else "to_up"
            elif abs(g3 - g12) >= step:
                verb = ("faster" if g3 > g12 else "slower") if g12 > 0 else ("decl_slower" if g3 > g12 else "decl_faster")
            else:
                verb = None
            if verb:
                out.append({"tone": _tone(ch3, m.direction), "icon": "progress", "anchor": "main",
                            "text": t("data.dash.f.pace", name=nm, verb=t(f"data.dash.f.v.{verb}"), a3=short_change(ch3, m.unit), a12=short_change(f.vs_last12, m.unit))})

    # 3. who drove it, who dragged it
    parts = []
    if len(m.branches) >= 2 and m.period_months == 1:
        parts = [p for p in I.contributions({b.dimension: b.pairs() for b in m.branches}, f.last, 12, m.aggregation) if p["delta"] is not None]
    if len(parts) >= 2 and m.aggregation == "sum":
        tot = sum(p["delta"] for p in parts)
        parts.sort(key=lambda p: -p["delta"])
        up, down = parts[0], parts[-1]
        if down["delta"] < 0:
            bad = I.tone_of(-1, m.direction, tolerance=0)
            out.append({"tone": bad, "icon": "trending-down", "anchor": "drivers",
                        "text": t("data.dash.f.drag", low=down["name"], amt=F.fmt_value(abs(down["delta"]), m.unit), name=nm)})
        if tot > 0 and up["delta"] > 0 and up["delta"] / tot >= 0.4:
            out.append({"tone": I.tone_of(1, m.direction, tolerance=0), "icon": "trending-up", "anchor": "drivers",
                        "text": t("data.dash.f.driver", top=up["name"], share=F.fmt_percent(up["delta"] / tot, 0), name=nm, amt=F.fmt_value(up["delta"], m.unit), tot=F.fmt_value(tot, m.unit))})
        elif tot < 0 and up["delta"] < 0:
            out.append({"tone": I.tone_of(-1, m.direction, tolerance=0), "icon": "trending-down", "anchor": "drivers",
                        "text": t("data.dash.f.fall_all", name=nm)})
    # 4. an odd month in the last half year
    cut = I.add_months(f.last, -5)
    for a in f.anomalies:
        if a.period >= cut:
            word = t("data.dash.below") if a.deviation < 0 else t("data.dash.above")
            amt = F.fmt_percent(abs(a.rel), 0) if a.rel is not None and m.unit.strip() != "%" else F.fmt_number(abs(a.deviation), 1)
            out.append({"tone": I.tone_of(a.deviation, m.direction, tolerance=0), "icon": "alert-triangle", "anchor": "main",
                        "text": t("data.dash.anomaly", period=period_label(a.period), value=F.fmt_value(a.value, m.unit), expected=F.fmt_value(a.expected, m.unit), word=word, amt=amt)})
            break
    # 5. dependence on one branch
    if parts and m.aggregation == "sum":
        now_total = sum(p["now"] for p in parts)
        top = max(parts, key=lambda p: p["now"])
        if now_total > 0 and top["now"] / now_total >= 0.5:
            out.append({"tone": "flat", "icon": "chart-pie", "anchor": "branches",
                        "text": t("data.dash.f.concentration", top=top["name"], share=F.fmt_percent(top["now"] / now_total, 0), name=nm)})
    return out[:4]


# -- trend ---------------------------------------------------------------------------------------------------------------------------
def _fmt_tick(v: float) -> str:
    return F.fmt_number(v, 0 if abs(v) >= 10 or float(v).is_integer() else 1)


def _trend_view(pts, full, m: Measure, f, *, target: dict | None, label: str, W: int = 900, H: int = 330) -> dict:
    """One window of the main chart: the line, last year's line behind it, marked odd months, the goal, and the hover points."""
    pt, pb, pr = 18, 34, 20
    prior = [(d, full[I.add_months(d, -12)]) for d, _ in pts if I.add_months(d, -12) in full] if m.period_months == 1 else []
    vals = [v for _, v in pts] + [v for _, v in prior] + ([target["value"]] if target else [])
    ticks = nice_ticks(min(vals), max(vals))
    lo, hi = ticks[0], ticks[-1]
    pl = max(48, 16 + 7 * max(len(_fmt_tick(x)) for x in ticks))
    iw, ih = W - pl - pr, H - pt - pb
    n = len(pts)
    X = lambda i: round(pl + (iw / 2 if n == 1 else i * iw / (n - 1)), 1)
    Y = lambda v: round(pt + ih - (v - lo) / (hi - lo) * ih, 1)
    idx = {d: i for i, (d, _) in enumerate(pts)}
    line = " ".join(("M" if i == 0 else "L") + f"{X(i)} {Y(v)}" for i, (_, v) in enumerate(pts))
    area = line + f" L{X(n - 1)} {pt + ih} L{X(0)} {pt + ih} Z"
    prior_line, pen = [], False
    for d, v in prior:
        prior_line.append(("L" if pen else "M") + f"{X(idx[d])} {Y(v)}")
        pen = True
    step = max(1, round(n / 8))
    xt = [{"x": X(i), "label": (_month_name(d) + (f" {str(d.year)[2:]}" if d.month == 1 or i == 0 else "")) if m.period_months == 1 else period_label(d, m.period_months)}
          for i, (d, _) in enumerate(pts) if i % step == 0]
    marks, notes = [], []
    for a in (f.anomalies if f else []):
        if a.period in idx:
            marks.append({"x": X(idx[a.period]), "y": Y(a.value), "n": len(marks) + 1})
            word = t("data.dash.below") if a.deviation < 0 else t("data.dash.above")
            notes.append({"n": len(marks), "text": t("data.dash.anomaly", period=period_label(a.period), value=F.fmt_value(a.value, m.unit), expected=F.fmt_value(a.expected, m.unit),
                                                       word=word, amt=F.fmt_percent(abs(a.rel), 0) if a.rel is not None and m.unit.strip() != "%" else F.fmt_number(abs(a.deviation), 1))})
    prior_by = dict(prior)
    hover = []
    for i, (d, v) in enumerate(pts):
        pv = prior_by.get(I.add_months(d, -12))
        ch = I.change(v, pv, m.unit) if pv is not None else None
        hover.append([X(i), Y(v), period_label(d, m.period_months), F.fmt_value(v, m.unit), F.fmt_value(pv, m.unit) if pv is not None else "", signed(ch, m.unit) if ch else "",
                      _tone(ch, m.direction) if ch else "flat"])
    goal = None
    if target:
        goal = {"y": Y(target["value"]), "label": t("data.dash.goal_line", title=target["title"][:34], value=F.fmt_value(target["value"], m.unit))}
    return {"label": label, "w": W, "h": H, "left": pl, "right": W - pr, "base": pt + ih, "top": pt, "path": line, "area": area, "prior": " ".join(prior_line),
            "yt": [{"y": Y(v), "label": _fmt_tick(v)} for v in ticks], "xt": xt, "marks": marks, "notes": notes, "goal": goal,
            "end": {"x": X(n - 1), "y": Y(pts[-1][1]), "label": F.fmt_value(pts[-1][1], m.unit)}, "hover": hover, "has_prior": bool(prior)}


def trend(m: Measure, spec: dict, target: dict | None = None) -> dict:
    branch = spec.get("branch")
    s = next((b for b in m.branches if b.dimension == branch), m.total) if branch else m.total
    allp = s.pairs()
    full = dict(allp)
    f = I.facts(allp, unit=m.unit, direction=m.direction, aggregation=m.aggregation, period_months=m.period_months)
    if spec.get("months") or m.period_months != 1:
        wins = [(spec.get("months") or len(allp), None)]
    else:
        wins = [(12, t("data.dash.win_12")), (24, t("data.dash.win_24"))] + ([(len(allp), t("data.dash.win_all"))] if len(allp) > 30 else [])
        wins = [w for w in wins if w[0] <= len(allp) or w[0] == 12]
    views = []
    for k, label in wins:
        views.append(_trend_view(allp[-k:], full, m, f, target=None if branch else target, label=label or ""))
    title = spec.get("title") or (m.name if not branch else f"{m.name}{SEP}{branch}")
    vs = f.vs_year or f.vs_prev if f else None
    head = None
    if f:
        ref = period_label(I.add_months(f.last, -12 if f.vs_year else -m.period_months), m.period_months)
        head = {"value": F.fmt_value(f.latest, m.unit), "period": period_label(f.last, m.period_months), "phrase": change_phrase(vs, m.unit, ref), "tone": f.tone}
    return {"kind": "trend", "title": title, "unit": F.unit_text(m.unit), "views": views, "head": head, "tone": f.tone if f else "flat",
            "insight": ""}


# -- branches: small multiples --------------------------------------------------------------------------------------------------------------
def _window(m: Measure, spec: dict) -> int:
    return spec.get("months") or 12


def _mini(pts, lo, hi, w=220, h=44) -> dict:
    n = len(pts)
    span = (hi - lo) or 1.0
    X = lambda i: round(2 + i * (w - 4) / max(1, n - 1), 1)
    Y = lambda v: round(h - 3 - (v - lo) / span * (h - 8), 1)
    path = " ".join(("M" if i == 0 else "L") + f"{X(i)} {Y(v)}" for i, (_, v) in enumerate(pts))
    return {"w": w, "h": h, "path": path, "area": path + f" L{X(n - 1)} {h} L{X(0)} {h} Z", "end": {"x": X(n - 1), "y": Y(pts[-1][1])}}


def branches(m: Measure, spec: dict) -> dict | None:
    months = _window(m, spec)
    rows = []
    end = m.pts[-1][0]
    for b in m.branches:
        pts = b.pairs()
        now = I.aggregate(pts, months, end, m.aggregation)
        before = I.aggregate(pts, months, end, m.aggregation, offset=12)
        if now is None:
            continue
        ch = I.change(now, before, m.unit)
        rows.append({"name": b.dimension, "value": now, "change": ch, "pts": pts[-24:]})
    if len(rows) < 2:
        return None
    rows.sort(key=lambda r: -r["value"] if m.direction != "lower_better" else r["value"])
    allv = [v for r in rows for _, v in r["pts"]]
    lo, hi = min(allv), max(allv)
    total = sum(r["value"] for r in rows)
    share = m.aggregation == "sum" and total > 0
    for r in rows:
        r["mini"] = _mini(r["pts"], lo, hi)
        r["share"] = F.fmt_percent(r["value"] / total, 0) if share else ""
        r["share_pct"] = round(r["value"] / total * 100) if share else 0
        r["text"] = F.fmt_value(r["value"], m.unit)
        r["delta"] = signed(r["change"], m.unit) if r["change"] else ""
        r["tone"] = _tone(r["change"], m.direction)
        r["arrow"] = "minus" if _flat(r["change"]) else "trending-up" if r["change"]["abs"] > 0 else "trending-down"
    best, worst = rows[0], rows[-1]
    title = spec.get("title") or t("data.dash.branches_title", name=m.short)
    if share:
        insight = t("data.dash.branches_share", top=best["name"], share=best["share"], name=m.short, months=F.fmt_number(months, 0), low=worst["name"], low_share=worst["share"])
    else:
        insight = t("data.dash.branches_best", top=best["name"], value=best["text"], low=worst["name"], low_value=worst["text"], months=F.fmt_number(months, 0))
    return {"kind": "branches", "title": title, "rows": rows, "insight": insight, "months": months, "unit": F.unit_text(m.unit), "share": share,
            "sub": t("data.dash.branches_sub", months=F.fmt_number(months, 0))}


# -- contribution: a bridge ---------------------------------------------------------------------------------------------------------------------
def _bridge(parts, before_total, now_total, unit, W=640, H=300) -> dict:
    """Vertical bridge: last year's total, one step per branch (up or down), this year's total. The axis starts near the totals, and says so."""
    pl, pr, pt, pb = 12, 12, 34, 54
    steps, run = [], before_total
    for p in parts:
        steps.append((p["name"], run, run + p["delta"], p["delta"]))
        run += p["delta"]
    levels = [before_total, now_total] + [x for s in steps for x in (s[1], s[2])]
    lo_v, hi_v = min(levels), max(levels)
    pad = (hi_v - lo_v) * 0.35 or abs(hi_v) * 0.1 or 1
    lo_t = lo_v - pad
    if lo_v >= 0 and lo_t < 0:
        lo_t = 0
    ticks = nice_ticks(lo_t, hi_v + pad * 0.6)
    lo, hi = ticks[0], ticks[-1]
    ih = H - pt - pb
    Y = lambda v: round(pt + ih - (v - lo) / (hi - lo) * ih, 1)
    cols = [("start", t("data.dash.bridge_start"), 0, before_total)] + [("step", s[0], s[1], s[2]) for s in steps] + [("end", t("data.dash.bridge_end"), 0, now_total)]
    n = len(cols)
    slot = (W - pl - pr) / n
    bw = round(min(slot * 0.62, 86), 1)
    bars = []
    for i, (kind, name, a, b) in enumerate(cols):
        cx = round(pl + slot * (i + 0.5), 1)
        top, bot = (Y(max(a, b)), Y(min(a, b))) if kind == "step" else (Y(b), pt + ih)
        up = kind == "step" and b >= a
        d = (b - a)
        bars.append({"x": round(cx - bw / 2, 1), "cx": cx, "w": bw, "y": top, "h": max(2.0, round(bot - top, 1)), "kind": kind if kind != "step" else ("up" if up else "down"),
                     "name": name, "label": F.fmt_value(b, unit) if kind != "step" else ("+" if up else "−") + F.fmt_value(abs(d), unit), "label_y": round(top - 7, 1)})
    links = []
    for i in range(n - 1):
        links.append({"x1": round(bars[i]["cx"] + bw / 2, 1), "x2": round(bars[i + 1]["cx"] - bw / 2, 1), "y": Y(cols[i][3])})
    return {"w": W, "h": H, "bars": bars, "links": links, "base": pt + ih, "name_y": pt + ih + 22, "truncated": lo > 0}


def contribution(m: Measure, spec: dict) -> dict | None:
    months = _window(m, spec)
    end = m.pts[-1][0]
    parts = I.contributions({b.dimension: b.pairs() for b in m.branches}, end, months, m.aggregation)
    parts = [p for p in parts if p["delta"] is not None]
    if len(parts) < 2:
        return None
    total_delta = sum(p["delta"] for p in parts)
    parts.sort(key=lambda p: -p["delta"])
    up, down = parts[0], parts[-1]
    title = spec.get("title") or t("data.dash.contrib_title", name=m.short)
    top = max(abs(p["delta"]) for p in parts) or 1
    for p in parts:                                  # the plain list: drawn for averages, and read by other modules (org map) for every measure
        p["pct_bar"] = round(abs(p["delta"]) / top * 100)
        p["up"] = p["delta"] > 0
        p["tone"] = I.tone_of(p["delta"], m.direction, tolerance=0)
        p["text"] = ("+" if p["delta"] > 0 else "−") + (F.fmt_value(abs(p["delta"]), m.unit) if m.aggregation == "sum" else
                    F.fmt_number(abs(p["delta"]), 1) + ((" " + t("data.dash.points")) if m.unit.strip() == "%" else (" " + F.unit_text(m.unit)).rstrip()))
    out = {"kind": "contribution", "title": title, "months": months, "unit": F.unit_text(m.unit), "rows": parts}
    if m.aggregation == "sum":
        word = t("data.dash.rose" if total_delta > 0 else "data.dash.fell")
        out["bridge"] = _bridge(parts, sum(p["before"] for p in parts), sum(p["now"] for p in parts), m.unit)
        out["insight"] = t("data.dash.contrib_text", name=m.short, word=word, amt=F.fmt_value(abs(total_delta), m.unit), months=F.fmt_number(months, 0), top=up["name"], top_amt=F.fmt_value(abs(up["delta"]), m.unit),
                           low=down["name"], low_amt=F.fmt_value(abs(down["delta"]), m.unit), low_word=t("data.dash.rose" if down["delta"] > 0 else "data.dash.fell"))
    else:
        out["insight"] = t("data.dash.contrib_avg", name=m.short, months=F.fmt_number(months, 0), top=up["name"], low=down["name"])
    return out


# -- heatmap -----------------------------------------------------------------------------------------------------------------------------------
def heatmap(m: Measure, spec: dict) -> dict | None:
    s = next((b for b in m.branches if b.dimension == spec.get("branch")), m.total) if spec.get("branch") else m.total
    if m.period_months != 1:
        return None
    pts = s.pairs()
    years = sorted({d.year for d, _ in pts})
    if len(years) < 2 and len(pts) < 8:
        return None
    grid = {(d.year, d.month): v for d, v in pts}
    ranked = sorted(grid.values())
    rank = lambda v: min(4, int(ranked.index(v) / max(1, len(ranked) - 1) * 4.999))        # shade by rank, so one extreme month does not wash out the rest
    by_month = {mo: statistics.mean([v for (yy, mm), v in grid.items() if mm == mo]) for mo in range(1, 13) if any(mm == mo for (_, mm) in grid)}
    strong, weak = max(by_month, key=by_month.get), min(by_month, key=by_month.get)
    if m.direction == "lower_better":
        strong, weak = weak, strong
    rows = []
    for y in years:
        cells = []
        for mo in range(1, 13):
            v = grid.get((y, mo))
            cells.append({"text": F.fmt_value(v, m.unit) if v is not None else "", "level": None if v is None else rank(v), "month": mo, "mark": "strong" if mo == strong else "weak" if mo == weak else ""})
        rows.append({"year": y, "cells": cells})
    mean = statistics.mean(by_month.values()) or 1
    spread = (max(by_month.values()) - min(by_month.values())) / abs(mean)
    title = spec.get("title") or t("data.dash.heat_title", name=m.short if not spec.get("branch") else f"{m.short}{SEP}{spec['branch']}")
    insight = t("data.dash.heat_text", strong=_month_name(date(2000, strong, 1), "wide"), weak=_month_name(date(2000, weak, 1), "wide"), spread=F.fmt_percent(spread, 0)) if m.unit.strip() != "%" else \
        t("data.dash.heat_text_pts", strong=_month_name(date(2000, strong, 1), "wide"), weak=_month_name(date(2000, weak, 1), "wide"), spread=F.fmt_number(max(by_month.values()) - min(by_month.values()), 1))
    months_names = [{"name": _month_name(date(2000, mo, 1)), "mark": "strong" if mo == strong else "weak" if mo == weak else ""} for mo in range(1, 13)]
    return {"kind": "heatmap", "title": title, "rows": rows, "months": months_names, "insight": insight}


# -- compare: two measures, one chart -------------------------------------------------------------------------------------------------------
def _pearson(xs: list[float], ys: list[float]) -> float | None:
    try:
        return statistics.correlation(xs, ys)
    except (statistics.StatisticsError, ZeroDivisionError):
        return None


def compare(m: Measure, m2: Measure, spec: dict) -> dict | None:
    """Both measures indexed to 100 at the first common month, so a count and an amount can be read on one scale; plus how closely their months move together."""
    if m.period_months != 1 or m2.period_months != 1:
        return None
    a, b = dict(m.pts), dict(m2.pts)
    common = sorted(set(a) & set(b))[-(spec.get("months") or 24):]
    if len(common) < 6 or a[common[0]] <= 0 or b[common[0]] <= 0:
        return None
    ia = [a[d] / a[common[0]] * 100 for d in common]
    ib = [b[d] / b[common[0]] * 100 for d in common]
    W, H, pt, pb, pr = 900, 330, 18, 34, 170
    ticks = nice_ticks(min(ia + ib + [100]), max(ia + ib + [100]))
    lo, hi = ticks[0], ticks[-1]
    pl = max(48, 16 + 7 * max(len(_fmt_tick(x)) for x in ticks))
    iw, ih = W - pl - pr, H - pt - pb
    n = len(common)
    X = lambda i: round(pl + i * iw / (n - 1), 1)
    Y = lambda v: round(pt + ih - (v - lo) / (hi - lo) * ih, 1)
    path = lambda vs: " ".join(("M" if i == 0 else "L") + f"{X(i)} {Y(v)}" for i, v in enumerate(vs))
    ya, yb = Y(ia[-1]), Y(ib[-1])
    if abs(ya - yb) < 18:                                   # keep the two end labels apart
        ya, yb = (ya - 9, yb + 9) if ya <= yb else (ya + 9, yb - 9)
    pct = lambda v: ("+" if v >= 100 else "−") + F.fmt_percent(abs(v - 100) / 100, 0)
    step = max(1, round(n / 8))
    xt = [{"x": X(i), "label": _month_name(d) + (f" {str(d.year)[2:]}" if d.month == 1 or i == 0 else "")} for i, d in enumerate(common) if i % step == 0]
    hover = [[X(i), Y(ia[i]), period_label(d), f"{m.short}: {F.fmt_value(a[d], m.unit)} ({pct(ia[i])})", f"{m2.short}: {F.fmt_value(b[d], m2.unit)} ({pct(ib[i])})", "", "flat"] for i, d in enumerate(common)]
    ra = [a[common[i]] / a[common[i - 1]] - 1 for i in range(1, n) if a[common[i - 1]]]
    rb = [b[common[i]] / b[common[i - 1]] - 1 for i in range(1, n) if b[common[i - 1]]]
    r = _pearson(ra, rb) if len(ra) == len(rb) else None
    if r is None:
        link = ""
    elif r >= 0.7:
        link = t("data.dash.cmp.strong", r=F.fmt_number(r, 1))
    elif r >= 0.4:
        link = t("data.dash.cmp.mid", r=F.fmt_number(r, 1))
    elif r <= -0.4:
        link = t("data.dash.cmp.opp", r=F.fmt_number(r, 1))
    else:
        link = t("data.dash.cmp.weak", r=F.fmt_number(r, 1))
    insight = t("data.dash.cmp.text", a=m.short, pa=pct(ia[-1]), b=m2.short, pb=pct(ib[-1]), months=F.fmt_number(n, 0), link=link).strip()
    view = {"label": "", "w": W, "h": H, "left": pl, "right": W - pr, "base": pt + ih, "top": pt, "yt": [{"y": Y(v), "label": _fmt_tick(v)} for v in ticks], "xt": xt,
            "a": path(ia), "b": path(ib), "base100": Y(100), "hover": hover,
            "ea": {"x": X(n - 1), "y": Y(ia[-1]), "ly": ya, "label": f"{m.short} {pct(ia[-1])}"}, "eb": {"x": X(n - 1), "y": Y(ib[-1]), "ly": yb, "label": f"{m2.short} {pct(ib[-1])}"}}
    return {"kind": "compare", "title": spec.get("title") or t("data.dash.cmp.title", a=m.short, b=m2.short), "unit": t("data.dash.cmp.unit"), "view": view, "insight": insight}


BUILDERS = {"trend": lambda m, sp: trend(m, sp), "branches": branches, "contribution": contribution, "heatmap": heatmap}


def build(spec: dict, ms: list[Measure], org_id: int | None = None) -> dict | None:
    m = next((x for x in ms if x.id == spec["measure"]), None)
    if m is None:
        return None
    if spec["kind"] == "trend":
        tg = linked_targets(org_id, m.total.id) if org_id else []
        out = trend(m, spec, tg[0] if tg else None)
    elif spec["kind"] in ("compare", "scatter"):
        m2 = next((x for x in ms if x.id == spec.get("measure2")), None)
        out = (compare(m, m2, spec) if spec["kind"] == "compare" else draw.scatter(m, m2, spec)) if m2 else None
    elif spec["kind"] in draw.BUILDERS:
        out = draw.BUILDERS[spec["kind"]](m, spec)
    else:
        out = BUILDERS[spec["kind"]](m, spec)
    if out is not None:
        out["spec"] = spec
        out["measure_name"] = m.name
    return out


def default_specs(m: Measure) -> dict:
    """The page's fixed layout for one measure: the main chart, and (only when they can be drawn) drivers, branches and season."""
    base = {"measure": m.id, "branch": None, "months": None, "title": ""}
    out = {"main": {"kind": "trend", **base}}
    if len(m.branches) >= 2:
        out["drivers"] = {"kind": "contribution", **base}
        out["branches"] = {"kind": "branches", **base}
    out["season"] = {"kind": "heatmap", **base}
    return out
