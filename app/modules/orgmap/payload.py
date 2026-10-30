"""The journey page's data: everything the browser needs to draw the journey as one JSON document (the drawing itself is js/journey.js).

Nothing here is invented: every number comes from facts.collect. Links are the two real kinds of dependency the product knows about:
  - `serves`: a goal that is aligned under another goal (Objective.parent_id)
  - `shares`: key results of different goals that are measured by the same data series
"""
from __future__ import annotations

from datetime import date

from app.core.i18n import t
from app.core.profile import initials

STATUSES = ("not_started", "on_track", "at_risk", "off_track", "completed")


def _iso(d) -> str:
    return d.isoformat() if isinstance(d, date) else ""


def build(facts: dict, vision_text: str = "", mission_text: str = "") -> dict:
    nodes, stats, org = facts["nodes"], facts["stats"], facts["org"]
    goals = []
    for gid in facts["goals"]:
        g = nodes[gid]
        krs = []
        for kid in g["kr"]:
            k = nodes[kid]
            krs.append({"id": kid, "title": k["label"], "status": k["status"], "progress": k["progress"], "now": k["now"], "target": k["target"], "gap": k["gap"],
                        "lands": k.get("lands", ""), "series": k["series"], "levers": [nodes[l]["label"] for l in k["levers"]]})
        goals.append({"id": gid, "title": g["label"], "status": g["status"], "progress": g["progress"], "expected": g["expected"], "owner": g["owner"], "end": _iso(g["end"]),
                      "url": g["url"], "parent": g.get("parent"), "attention": bool(g["attention"]), "krs": krs})
    shares = []
    for sid in stats["shared"]:
        s = nodes[sid]
        users = [{"kr": u, "goal": nodes[u]["goal"]} for u in s["users"]]
        shares.append({"id": sid, "label": s["label"], "latest": s["latest"], "period": s["period"], "users": users})
    return {
        "org": {"name": org["label"], "logo": org.get("logo"), "initials": initials(org["label"])},
        "vision": {"text": vision_text, "mission": mission_text},
        "time": stats["time"], "journey": stats["journey"], "days_left": stats["days_left"], "cycle": stats["cycle"],
        "goals": goals, "shares": shares,
        "i18n": {
            "status": {s: t("status." + s) for s in STATUSES},
            "origin": t("orgmap.jr.origin"), "vision": t("orgmap.jr.vision"), "horizon": t("orgmap.jr.horizon"), "today": t("orgmap.jr.today"),
            "behind": t("orgmap.jr.behind"), "ahead": t("orgmap.jr.ahead"), "even": t("orgmap.jr.even"), "points": t("orgmap.jr.points"),
            "serves": t("orgmap.jr.serves"), "served_by": t("orgmap.jr.served_by"), "shares": t("orgmap.jr.shares"), "owner": t("orgmap.jr.owner"), "ends": t("orgmap.jr.ends"),
            "open": t("orgmap.jr.open"), "krs": t("orgmap.jr.krs"), "lands": t("orgmap.jr.lands"), "gap": t("orgmap.jr.gap"), "levers": t("orgmap.jr.levers"),
            "blocks": t("orgmap.jr.blocks"), "of_time": t("orgmap.jr.of_time"), "axis": t("orgmap.jr.axis"), "mission": t("orgmap.jr.mission"), "close": t("orgmap.jr.close"),
        },
    }
