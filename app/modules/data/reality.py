"""Reality check, assembled for the UI: the deterministic verdict + chart + a rule-based explanation (instant, free).
The AI explanation (`explain`) is a separate, optional call so the panel never waits for a model."""
from __future__ import annotations

from datetime import date

from flask import g

from app import ai
from app.ai.tasks import explain_reality
from app.modules.data import realism
from app.modules.data.chart import LEVEL_ICON, LEVEL_TONE, reality_chart
from app.modules.data.models import Series


def check(series: Series, *, start: float, target: float, end_date: date, as_of: date | None = None, direction: str | None = None,
          goal: str = "") -> dict:
    as_of = as_of or date.today()
    pts = series.pairs()
    direction = direction or series.direction
    if end_date <= as_of:
        return {"error": "dates"}
    v = realism.assess(pts, start=start, target=target, as_of=as_of, end_date=end_date, direction=direction, period_months=series.period_months,
                       relative=False if (series.unit or "").strip() == "%" else None)
    lang = g.get("lang", "ar")
    inputs = {"goal": goal, "series": series.name, "unit": series.unit, "verdict": _public(v), "facts": v["facts"]}
    quick = explain_reality.task.fallback(inputs, lang)
    return {"series": series, "verdict": v, "level": v["level"], "tone": LEVEL_TONE[v["level"]], "icon": LEVEL_ICON[v["level"]],
            "chart": reality_chart(pts, v, start=start, target=target, as_of=as_of, end_date=end_date), "explain": quick,
            "inputs": inputs, "unit": series.unit, "start": start, "target": target, "end_date": end_date, "as_of": as_of, "direction": direction,
            "ai": None}


def _public(v: dict) -> dict:
    """What an explanation may see: the verdict and its numbers, nothing from the raw file."""
    return {k: v.get(k) for k in ("direction", "measure", "start", "target", "months", "required", "hist", "notes", "seasonal", "percentile",
                                   "range", "latest", "level", "ratio_best", "monthly")}


def explain(result: dict) -> dict:
    """Ask the AI layer to explain the verdict; the numbers it may use are fixed by `facts` (checked by the task)."""
    res = ai.run("explain_reality", result["inputs"])
    result = {**result, "explain": res.data, "ai": res}
    return result
