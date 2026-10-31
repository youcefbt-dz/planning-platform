"""The map page's data: everything the browser needs, as one JSON document (the drawing and the camera are js/journey.js).

The picture is an archipelago: the organization is the capital (identity, vision, mission), every department is an island with its head
standing on it and its goals around the head, and the real dependencies between goals (`Link` kind depends_on) are the routes between them.
Nothing here is invented: every number comes from facts.collect, every person from the departments and memberships.
"""
from __future__ import annotations

from datetime import date

from flask import url_for

from app.core.i18n import t
from app.core.models import Link, Membership
from app.core.profile import initials
from app.core.services import units as org_units

STATUSES = ("not_started", "on_track", "at_risk", "off_track", "completed")
WORDS = ("title", "journey", "of_time", "pace", "left", "days", "all", "attention", "attention_none", "deps", "align", "zoom_in", "zoom_out", "fit", "full", "exit_full",
         "hint", "origin", "vision", "mission", "horizon", "no_head", "head", "people", "goals", "avg", "owner", "unit", "ends", "krs", "gap", "levers", "behind", "ahead", "even",
         "points", "today", "depends", "needed", "serves", "served", "blocked", "open_goal", "open_unit", "close", "export", "map", "cycle", "no_goals", "org_goals",
         "legend_gap", "legend_today", "legend_dep", "legend_warn", "legend_align", "lands", "stations")


def _iso(d) -> str:
    return d.isoformat() if isinstance(d, date) else ""


def build(org, facts: dict, vision_text: str = "", mission_text: str = "") -> dict:
    nodes, stats, o = facts["nodes"], facts["stats"], facts["org"]
    all_units = org_units(org)
    members = {m.user_id: m for m in Membership.query.filter_by(org_id=org.id).all()}
    people: dict[int, int] = {}
    for m in members.values():
        if m.unit_id:
            people[m.unit_id] = people.get(m.unit_id, 0) + 1
    units = []
    for u in all_units:
        head = None
        if u.head is not None:
            m = members.get(u.head_id)
            head = {"name": u.head.name, "initials": initials(u.head.name), "title": (m.title if m and m.title else "")}
        units.append({"id": u.id, "name": u.name, "kind": u.kind, "parent": u.parent_id, "head": head, "people": people.get(u.id, 0), "url": url_for("orgmap.unit", org_slug=org.slug, id=u.id)})

    goals = []
    for gid in facts["goals"]:
        g = nodes[gid]
        krs = [{"id": k, "title": nodes[k]["label"], "status": nodes[k]["status"], "progress": nodes[k]["progress"], "now": nodes[k]["now"], "target": nodes[k]["target"],
                "gap": nodes[k]["gap"], "lands": nodes[k].get("lands", ""), "levers": [nodes[l]["label"] for l in nodes[k]["levers"]]} for k in g["kr"]]
        goals.append({"id": gid, "title": g["label"], "status": g["status"], "progress": g["progress"], "expected": g["expected"], "owner": g["owner"], "end": _iso(g["end"]),
                      "url": g["url"], "unit": g.get("unit_id"), "parent": g.get("parent"), "krs": krs})
    ids = {g["id"] for g in goals}
    deps = []
    for l in Link.query.filter_by(org_id=org.id, source_type="objective", target_type="objective", kind="depends_on").all():
        a, b = f"goal:{l.source_id}", f"goal:{l.target_id}"
        if a in ids and b in ids:
            deps.append({"from": a, "to": b})                       # `from` depends on `to`
    return {
        "org": {"name": o["label"], "logo": o.get("logo"), "initials": initials(o["label"]), "sector": o.get("sector", "")},
        "vision": {"text": vision_text, "mission": mission_text},
        "time": stats["time"], "journey": stats["journey"], "days_left": stats["days_left"], "cycle": stats["cycle"],
        "units": units, "goals": goals, "deps": deps,
        "i18n": {"status": {s: t("status." + s) for s in STATUSES}, **{w: t("orgmap.jx." + w) for w in WORDS}},
    }
