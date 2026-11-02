"""The agent's tools. Each one READS the organization as the current user may see it and returns small, plain JSON; the model never computes a figure
itself — it asks. Two tools (`propose_goal`) only DRAFT: nothing is written until a person approves the card.

A tool is `Tool(name, description, parameters (JSON schema), fn)`; `fn(**args) -> dict`. Raise `ToolError("message")` for an error the model can read and
correct (a wrong id, a missing value). Adding a tool = adding one function and one entry in TOOLS."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

from flask import current_app, g
from flask_login import current_user

from app.core import scope as SC


class ToolError(Exception):
    """A mistake the model can read and fix (it is returned to it as {"error": ...})."""


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable[..., dict]
    label: str = ""          # shown to the person while it runs ("قرأتُ صحة الأهداف")

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


def _r(x, d=2):
    return None if x is None else round(float(x), d)


def _date(raw, field="end_date") -> date:
    try:
        return date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        raise ToolError(f"{field} must be a date like 2026-12-31") from None


def _on(mid: str) -> bool:
    return current_app.extensions["modules"].is_enabled(mid)


# -- the organization ------------------------------------------------------------------------------------------------------------------------
def org_overview() -> dict:
    from app.core.profile import profile
    from app.core.services import current_cycle
    from app.modules.goals import service as GS

    cyc = current_cycle(g.org)
    out = {"organization": g.org.name, "today": date.today().isoformat(), "you": {"name": current_user.name, "role": getattr(g, "role", None)}}
    prof = profile(g.org) or {}
    out["profile"] = {k: prof.get(k) for k in ("sector", "size", "currency") if prof.get(k)}
    out["cycle"] = {"name": cyc.name, "start": cyc.start_date.isoformat(), "end": cyc.end_date.isoformat()} if cyc else None
    if _on("goals"):
        views = GS.compute_objectives(g.org)
        sm = GS.summary(views)
        out["goals"] = {"total": sm["total"], "by_status": {k: v for k, v in sm["counts"].items() if v}, "average_progress_pct": _r((sm["avg"] or 0) * 100, 0)}
    if _on("data"):
        from app.modules.data import service as DS
        out["data_series"] = len(DS.org_series(g.org.id))
    return out


def org_units() -> dict:
    from app.core.services import units
    from app.modules.goals import service as GS

    us = units(g.org)
    views = GS.compute_objectives(g.org) if _on("goals") else {}
    by_unit: dict[int | None, list] = {}
    for v in views.values():
        by_unit.setdefault(v.obj.unit_id, []).append(v)
    allowed = {u.id for u in SC.allowed_units(us)}
    rows = []
    for u in us:
        gs = by_unit.get(u.id, [])
        rows.append({"id": u.id, "name": u.name, "kind": u.kind, "parent_id": u.parent_id, "head": u.head.name if u.head else None, "goals": len(gs),
                     "at_risk_or_off_track": sum(1 for v in gs if v.status in ("at_risk", "off_track")),
                     "avg_progress_pct": _r(100 * sum(v.progress for v in gs) / len(gs), 0) if gs else None, "you_may_add_goals_here": u.id in allowed})
    return {"units": rows, "units_without_goals": [r["name"] for r in rows if r["kind"] != "company" and not r["goals"]]}


# -- goals ----------------------------------------------------------------------------------------------------------------------------------------
def _owner(o) -> str | None:
    return o.owner.name if getattr(o, "owner", None) else None


def list_goals(status: str = "", unit_id: int | None = None, limit: int = 30) -> dict:
    from app.modules.goals import service as GS

    views = GS.compute_objectives(g.org)
    rows = []
    for v in sorted(views.values(), key=lambda v: v.obj.id):
        o = v.obj
        if status and v.status != status or (unit_id and o.unit_id != int(unit_id)):
            continue
        rows.append({"id": o.id, "title": o.title, "unit": o.unit.name if o.unit else None, "owner": _owner(o), "parent_id": o.parent_id, "status": v.status,
                     "progress_pct": _r(v.progress * 100, 0), "expected_pct": _r(v.expected * 100, 0), "stale": v.stale, "key_results": len(v.krs), "commitment": o.commitment})
    return {"count": len(rows), "goals": rows[: max(1, min(int(limit or 30), 60))]}


def _kr_history(k, d) -> dict:
    from app.modules.goals.views import _kr_history as kh
    return kh(k, d)


def get_goal(goal_id: int) -> dict:
    from app.modules.goals import health as H, service as GS
    from app.modules.goals.models import Objective

    o = db_get(Objective, goal_id)
    views = GS.compute_objectives(g.org)
    v = views.get(o.id)
    start, end = GS._dates(o)
    out = {"id": o.id, "title": o.title, "rationale": o.rationale, "unit": o.unit.name if o.unit else None, "owner": _owner(o), "parent_id": o.parent_id,
           "status": v.status, "progress_pct": _r(v.progress * 100, 0), "expected_pct": _r(v.expected * 100, 0), "commitment": o.commitment,
           "starts": start.isoformat() if start else None, "ends": end.isoformat() if end else None, "children": [c.obj.id for c in v.children], "key_results": []}
    for kv in v.krs:
        k = kv.kr
        row = H.row(v, kv, date.today(), start=start, end=end)
        d = row["data"]
        item = {"id": k.id, "title": k.title, "type": k.kr_type, "unit": k.unit_label, "start": _r(k.start_value), "now": _r(k.current_value), "target": _r(k.target_value),
                "progress_pct": _r(kv.progress * 100, 0), "status": row["status"], "measured_by_data": bool(d), "stale": row["stale"]}
        if k.kr_type in ("increase", "decrease", "stay_above", "stay_below"):
            hist = _kr_history(k, d)
            item["needs_change"] = _r(hist["need"])
            item["needs_change_pct"] = _r(hist["need_pct"] * 100, 1) if hist["need_pct"] is not None else None
            item["value_a_year_ago"] = _r(hist["year_ago"][1]) if hist["year_ago"] else None
            item["change_over_last_year_pct"] = _r(hist["yoy"] * 100, 1) if hist["yoy"] is not None else None
            item["best_ever"] = _r(hist["best"])
        if d:
            item["series_id"] = d["series"].id
            item["data_age_days"] = d.get("age_days")
            if d.get("level"):
                item["target_verdict"] = d["level"]
        pr = row["projected"]
        if pr:
            item["expected_end_range"] = {"low": _r(pr["low"]), "likely": _r(pr["mid"]), "high": _r(pr["high"])}
        if k.factors:
            item["levers_and_risks"] = [{"title": f.title, "effect": _r(f.effect), "certainty": f.certainty} for f in k.factors[:6]]
        out["key_results"].append(item)
    return out


def goal_health(limit: int = 25) -> dict:
    """What needs attention: every key result that is off track, at risk or stale, worst first, with the projected end against the target."""
    from app.modules.goals import health as H, service as GS

    views = GS.compute_objectives(g.org)
    data = H.build(views, g.org)
    rank = {"off_track": 0, "at_risk": 1, "completed": 9, "on_track": 5, "not_started": 6}
    items = []
    for grp in data["groups"]:
        for r in grp["rows"]:
            if r["status"] in ("completed", "on_track") and not r["stale"]:
                continue
            kr, pr = r["kr"], r["projected"]
            items.append({"goal_id": r["obj"].id, "goal": r["obj"].title, "unit": r["obj"].unit.name if r["obj"].unit else None, "key_result_id": kr.id,
                          "key_result": kr.title, "status": r["status"], "source": r["source"], "progress_pct": _r(r["progress"] * 100, 0),
                          "expected_pct": _r(r["expected"] * 100, 0), "now": _r(kr.current_value), "target": _r(kr.target_value), "unit_label": kr.unit_label,
                          "projected_end": {"low": _r(pr["low"]), "likely": _r(pr["mid"]), "high": _r(pr["high"])} if pr else None,
                          "data_age_days": r["data"]["age_days"] if r["data"] else None, "stale": r["stale"]})
    items.sort(key=lambda x: (rank.get(x["status"], 7), -(x["expected_pct"] or 0) + (x["progress_pct"] or 0)))
    return {"counts": {k: v for k, v in data["counts"].items() if v}, "total_key_results": data["total"], "needing_attention": items[: max(1, min(int(limit or 25), 40))]}


def db_get(model, ident):
    from app.extensions import db

    try:
        row = db.session.get(model, int(ident))
    except (TypeError, ValueError):
        raise ToolError("the id must be a number") from None
    if row is None or getattr(row, "org_id", g.org.id) != g.org.id:
        raise ToolError(f"{model.__name__} {ident} does not exist in this organization")
    return row


# -- data -------------------------------------------------------------------------------------------------------------------------------------------
def list_series() -> dict:
    from app.modules.data import service as DS

    rows = []
    for s in DS.org_series(g.org.id):
        lp = s.latest
        rows.append({"id": s.id, "name": s.name, "unit": s.unit, "direction": s.direction, "points": len(s.points or []), "period_months": s.period_months,
                     "latest": {"date": lp[0].isoformat(), "value": _r(lp[1])} if lp else None, "dataset": s.dataset.name if s.dataset else None})
    return {"count": len(rows), "series": rows}


def _series(series_id):
    from app.modules.data.models import Series
    return db_get(Series, series_id)


def series_history(series_id: int, last: int = 18) -> dict:
    s = _series(series_id)
    pts = s.pairs()
    if not pts:
        raise ToolError("this series has no readings")
    d, v = pts[-1]
    want = d - timedelta(days=365)
    near = min(pts[:-1], key=lambda p: abs((p[0] - want).days), default=None)
    year_ago = near if near and abs((near[0] - want).days) <= 35 else None
    vals = [x for _, x in pts]
    lower = s.direction == "lower_better"
    out = {"id": s.id, "name": s.name, "unit": s.unit, "direction": s.direction, "period_months": s.period_months, "readings": len(pts),
           "first": {"date": pts[0][0].isoformat(), "value": _r(pts[0][1])}, "latest": {"date": d.isoformat(), "value": _r(v)},
           "previous": {"date": pts[-2][0].isoformat(), "value": _r(pts[-2][1])} if len(pts) > 1 else None,
           "a_year_ago": {"date": year_ago[0].isoformat(), "value": _r(year_ago[1])} if year_ago else None,
           "change_over_last_year_pct": _r((v - year_ago[1]) / abs(year_ago[1]) * 100, 1) if year_ago and year_ago[1] else None,
           "best": _r(min(vals) if lower else max(vals)), "worst": _r(max(vals) if lower else min(vals)),
           "average_last_12": _r(sum(vals[-12:]) / len(vals[-12:])), "recent": [{"date": a.isoformat(), "value": _r(b)} for a, b in pts[-max(3, min(int(last or 18), 36)):]]}
    return out


def check_target(series_id: int, target: float, end_date: str, start: float | None = None) -> dict:
    from app.modules.data import reality

    s = _series(series_id)
    pts = s.pairs()
    if not pts:
        raise ToolError("this series has no readings")
    end = _date(end_date)
    res = reality.check(s, start=float(start) if start is not None else pts[-1][1], target=float(target), end_date=end)
    if res.get("error"):
        raise ToolError("the end date must be in the future")
    v = res["verdict"]
    h, rng, mo = v.get("hist") or {}, v.get("range") or {}, v.get("monthly") or {}
    out = {"series": s.name, "unit": s.unit, "start": _r(v["start"]), "target": _r(v["target"]), "end_date": end.isoformat(), "months_left": v["months"],
           "verdict": res["level"], "measure": v["measure"], "required_change": _r(v["required"], 4), "history_windows": h.get("windows", 0),
           "typical_change": _r(h.get("median"), 4), "best_change": _r(h.get("best"), 4), "notes": v.get("notes", [])}
    if rng:
        out["defensible_target_range"] = {"typical": _r(rng["typical"]), "high": _r(rng["high"]), "best_seen": _r(rng["best"])}
    if mo.get("required") is not None:
        out["monthly_pace"] = {"required": _r(mo["required"], 4), "typical": _r(mo.get("typical"), 4)}
    return out


def target_levels(series_id: int, end_date: str) -> dict:
    from app.modules.data import realism

    s = _series(series_id)
    pts = s.pairs()
    if not pts:
        raise ToolError("this series has no readings")
    end = _date(end_date)
    if end <= date.today():
        raise ToolError("the end date must be in the future")
    lv = realism.levels(pts, start=pts[-1][1], as_of=date.today(), end_date=end, direction=s.direction, period_months=s.period_months,
                        relative=False if (s.unit or "").strip() == "%" else None)
    if not lv:
        return {"series": s.name, "available": False, "reason": "not enough history to say what is defensible"}
    return {"series": s.name, "unit": s.unit, "start": _r(pts[-1][1]), "end_date": end.isoformat(), "available": True,
            "conservative_realistic": _r(lv["conservative"]), "ambitious": _r(lv["ambitious"]), "stretch": _r(lv["stretch"]), "history_windows": lv["windows"], "notes": lv["notes"]}


# -- drafts (nothing is written here) -----------------------------------------------------------------------------------------------------
LEVELS = ("conservative", "ambitious", "stretch")


def build_proposal(*, title: str, unit_id: int | None = None, rationale: str = "", end_date: str = "", parent_id: int | None = None, key_results: list | None = None) -> dict:
    """Validate a goal draft and fill EVERY figure from code: a measured key result starts at its latest reading and its target comes from the
    organization's own history (a level) or is a number the person gave, checked by the reality engine. Never a number from the model."""
    from app.core.services import current_cycle, units
    from app.modules.data import realism, reality
    from app.modules.goals.models import Objective

    title = (title or "").strip()
    if len(title) < 4:
        raise ToolError("the goal needs a clear title")
    if not SC.can_add_goal():
        raise ToolError("this user may not create goals")
    us = units(g.org)
    uid = int(unit_id) if unit_id else SC.default_unit_id()
    unit = next((u for u in us if u.id == uid), None)
    if (uid and unit is None) or not SC.can_edit_unit(uid):
        raise ToolError("the user may not add goals to that unit; see org_units for where he may (you_may_add_goals_here)")
    cyc = current_cycle(g.org)
    end = _date(end_date) if end_date else (cyc.end_date if cyc else None)
    if end is None or end <= date.today():
        raise ToolError("give an end_date in the future (or set a planning cycle)")
    par = None
    if parent_id:
        par = db_get(Objective, parent_id)
    if not key_results:
        raise ToolError("a goal needs 1 to 4 key results")
    krs, warns = [], []
    for i, k in enumerate(key_results[:4]):
        name = (k.get("title") or "").strip()
        if not name:
            raise ToolError(f"key result {i + 1} has no title")
        item = {"title": name[:255], "series_id": None, "unit": (k.get("unit") or "").strip()[:24], "direction": "lower_better" if k.get("direction") == "lower_better" else "higher_better",
                "start": None, "target": None, "level": None, "verdict": None}
        if k.get("series_id"):
            s = _series(k["series_id"])
            pts = s.pairs()
            if not pts:
                raise ToolError(f"series {s.id} has no readings")
            item.update(series_id=s.id, unit=s.unit or "", direction=s.direction, start=pts[-1][1], title=item["title"] or s.name)
            lvl = k.get("target_level")
            if lvl in LEVELS:
                lv = realism.levels(pts, start=pts[-1][1], as_of=date.today(), end_date=end, direction=s.direction, period_months=s.period_months,
                                    relative=False if (s.unit or "").strip() == "%" else None)
                if not lv:
                    raise ToolError(f"series {s.id} has too little history to set a {lvl} target; give an explicit target or use a key result without data")
                item.update(target=lv[lvl], level=lvl)
            elif k.get("target") is not None:
                try:
                    item["target"] = float(k["target"])
                except (TypeError, ValueError):
                    raise ToolError(f"key result {i + 1}: target must be a number") from None
            else:
                raise ToolError(f"key result {i + 1}: give target_level (conservative | ambitious | stretch) or a target the person stated")
            chk = reality.check(s, start=item["start"], target=item["target"], end_date=end)
            if not chk.get("error"):
                item["verdict"] = chk["level"]
                if chk["level"] in ("stretch", "unrealistic"):
                    warns.append(f"{item['title']}: {chk['level']}")
        else:
            if k.get("start") is None or k.get("target") is None:
                raise ToolError(f"key result {i + 1} has no data: ask the person for its start value and target, do not invent them")
            try:
                item.update(start=float(k["start"]), target=float(k["target"]))
            except (TypeError, ValueError):
                raise ToolError(f"key result {i + 1}: start and target must be numbers") from None
        krs.append(item)
    return {"title": title[:255], "rationale": (rationale or "").strip()[:600], "unit_id": unit.id if unit else None, "unit_name": unit.name if unit else g.org.name, "parent_id": par.id if par else None,
            "parent_title": par.title if par else None, "end_date": end.isoformat(), "key_results": krs, "warnings": warns}


def propose_goal(title: str, key_results: list, unit_id: int | None = None, rationale: str = "", end_date: str = "", parent_id: int | None = None) -> dict:
    p = build_proposal(title=title, unit_id=unit_id, rationale=rationale, end_date=end_date, parent_id=parent_id, key_results=key_results)
    p["id"] = f"p{len(g.get('agent_proposals') or []) + 1}"
    g.agent_proposals = [*(g.get("agent_proposals") or []), p]
    # what the model sees back: the figures the CODE set, to quote exactly as they are
    return {"status": "drafted_awaiting_approval", "proposal_id": p["id"], "unit": p["unit_name"], "end_date": p["end_date"], "warnings": p["warnings"],
            "key_results": [{"title": k["title"], "unit": k["unit"], "start": _r(k["start"]), "target": _r(k["target"]), "target_level": k["level"], "verdict": k["verdict"]} for k in p["key_results"]]}


# -- registry ----------------------------------------------------------------------------------------------------------------------------------------
_ID = {"type": "integer"}
_DATE = {"type": "string", "description": "ISO date, e.g. 2026-12-31"}
TOOLS: list[Tool] = [
    Tool("org_overview", "The organization in one look: today's date, planning cycle, number of goals by status, average progress, how many data series exist, and who the user is. Call it first for broad questions.",
         {"type": "object", "properties": {}}, org_overview, "نظرة على المؤسسة"),
    Tool("org_units", "Departments and teams with their heads, how many goals each has, how many are at risk, average progress, which departments have NO goals, and where the user may add goals.",
         {"type": "object", "properties": {}}, org_units, "قراءة الأقسام ورؤسائها"),
    Tool("list_goals", "List goals (id, title, department, owner, status, progress vs the progress expected by now, stale or not). Filter by status (on_track|at_risk|off_track|completed|not_started) or by department id.",
         {"type": "object", "properties": {"status": {"type": "string"}, "unit_id": _ID, "limit": _ID}}, list_goals, "قائمة الأهداف"),
    Tool("get_goal", "Everything about one goal: its key results with start, now, target, what the target requires, the value a year ago, best ever, data verdict, expected end range, levers and risks.",
         {"type": "object", "properties": {"goal_id": _ID}, "required": ["goal_id"]}, get_goal, "قراءة تفاصيل هدف"),
    Tool("goal_health", "Key results that need attention (off track, at risk, stale), worst first, with where each is expected to END against its target. The best first call for 'how are we doing' questions.",
         {"type": "object", "properties": {"limit": _ID}}, goal_health, "فحص صحة الأهداف"),
    Tool("list_series", "The data series uploaded by the organization (id, name, unit, latest reading, number of readings). Use it to find what can measure a goal.",
         {"type": "object", "properties": {}}, list_series, "قراءة المقاييس المتاحة"),
    Tool("series_history", "History of one data series: latest, previous, a year ago, change over the last year, best, worst, 12-month average and the recent readings.",
         {"type": "object", "properties": {"series_id": _ID, "last": _ID}, "required": ["series_id"]}, series_history, "قراءة تاريخ مقياس"),
    Tool("check_target", "Is this target realistic given the organization's OWN history? Returns the verdict (realistic|ambitious|stretch|unrealistic|insufficient), the change required vs the typical and best change, and a defensible range.",
         {"type": "object", "properties": {"series_id": _ID, "target": {"type": "number"}, "end_date": _DATE, "start": {"type": "number"}}, "required": ["series_id", "target", "end_date"]}, check_target, "فحص واقعية مستهدف"),
    Tool("target_levels", "Three defensible targets for a series by a date, from the organization's own history: conservative (realistic), ambitious, stretch. Use these instead of choosing a target yourself.",
         {"type": "object", "properties": {"series_id": _ID, "end_date": _DATE}, "required": ["series_id", "end_date"]}, target_levels, "حساب مستويات المستهدف"),
    Tool("propose_goal", "DRAFT a goal for the person to approve (nothing is created). Each key result either has a series_id plus target_level (conservative|ambitious|stretch; the code fills start and target) or, without data, a start and target the PERSON gave you. Put the goal in a department he may edit.",
         {"type": "object", "properties": {"title": {"type": "string"}, "rationale": {"type": "string"}, "unit_id": _ID, "end_date": _DATE, "parent_id": _ID,
                                          "key_results": {"type": "array", "items": {"type": "object", "properties": {
                                              "title": {"type": "string"}, "series_id": _ID, "target_level": {"type": "string", "enum": list(LEVELS)}, "target": {"type": "number"},
                                              "start": {"type": "number"}, "unit": {"type": "string"}, "direction": {"type": "string", "enum": ["higher_better", "lower_better"]}},
                                              "required": ["title"]}}}, "required": ["title", "key_results"]}, propose_goal, "صياغة مسودة هدف"),
]
BY_NAME = {t.name: t for t in TOOLS}


def available(read_only: bool = False) -> list[Tool]:
    """Tools whose module is on (a tool for a switched-off module never reaches the model)."""
    needs_goals = {"list_goals", "get_goal", "goal_health", "propose_goal"}
    needs_data = {"list_series", "series_history", "check_target", "target_levels"}
    out = []
    for t in TOOLS:
        if t.name in needs_goals and not _on("goals") or t.name in needs_data and not _on("data"):
            continue
        out.append(t)
    return out


def run(name: str, args: dict) -> tuple[dict, bool]:
    """-> (result, ok). Exceptions inside a tool become an error the model can read, never a crash."""
    tool = BY_NAME.get(name)
    if tool is None:
        return {"error": f"unknown tool '{name}'"}, False
    try:
        return tool.fn(**{k: v for k, v in (args or {}).items() if v is not None}), True
    except ToolError as e:
        return {"error": str(e)}, False
    except TypeError as e:
        return {"error": f"bad arguments: {e}"}, False
    except Exception:  # a bug in a tool must not end the conversation
        current_app.logger.exception("agent tool %s failed", name)
        return {"error": "the tool failed; try another way or tell the person"}, False
