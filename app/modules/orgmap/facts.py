"""What the organization IS, as plain data: every thing the journey map may show, with an id, a type, a status and numbers computed by code.

The model that composes the journey only ever sees ids, types, labels and statuses (never raw series values) and answers with a spec; the spec is
checked against these facts (spec.validate), so the picture can rearrange and emphasise but cannot invent anything.

Node ids:  org · vision · goal:<id> · kr:<id> · br:<kr id>:<n> · ds:<series id> · lv:<factor id>
Types   :  org, vision, goal, kr, branch, series, lever
"""
from __future__ import annotations

from datetime import date

from flask import current_app, url_for

from app.core import formatting as F
from app.core.i18n import t
from app.core.profile import profile as get_profile
from app.core.services import current_cycle
from app.modules.orgmap.build import BAD, build as build_map

DONE = ("completed",)
GOOD = ("on_track", "completed")


def _pct(x: float | None) -> int:
    return max(0, min(100, round((x or 0) * 100)))


def _days(a: date | None, b: date | None) -> int | None:
    return (b - a).days if a and b else None


def collect(org, today: date | None = None) -> dict:
    """The facts: {"nodes": {id: node}, "goals": [ids], "edges": [(from, to, kind)], "stats": {...}, "org": {...}}."""
    today = today or date.today()
    m = build_map(org, today)
    prof = m["profile"]
    nodes: dict[str, dict] = {}
    edges: list[tuple[str, str, str]] = []
    goals: list[str] = []
    try:
        logo = url_for("shell.org_logo", org_slug=org.slug, v=prof["logo"]) if prof.get("logo") else None
    except Exception:
        logo = None
    nodes["org"] = {"id": "org", "type": "org", "label": org.name, "sector": prof.get("sector") or "", "logo": logo}
    story = " ".join(x for x in (prof.get("vision"), prof.get("mission")) if x)
    if story:
        nodes["vision"] = {"id": "vision", "type": "vision", "label": t("orgmap.j.vision"), "vision": prof.get("vision") or "", "mission": prof.get("mission") or ""}
        edges.append(("org", "vision", "origin"))

    cyc = current_cycle(org, today)
    cyc_total = _days(cyc.start_date, cyc.end_date) if cyc else None
    cyc_done = _days(cyc.start_date, min(today, cyc.end_date)) if cyc else None
    time_share = max(0.0, min(1.0, cyc_done / cyc_total)) if cyc_total else None
    days_left = max(0, (cyc.end_date - today).days) if cyc else None

    series_users: dict[str, list[str]] = {}
    total_krs = fed = 0
    progress_sum = weight_sum = 0.0
    biggest = None
    for gl in m["goals"]:
        o, view = gl["obj"], gl["view"]
        gid = f"goal:{o.id}"
        goals.append(gid)
        end = o.end_date or (o.cycle.end_date if o.cycle else None)
        nodes[gid] = {"id": gid, "type": "goal", "label": o.title, "status": gl["status"], "progress": _pct(view.progress), "expected": _pct(view.expected), "parent_id": o.parent_id, "unit_id": o.unit_id,
                      "owner": o.owner.name if o.owner else "", "end": end, "attention": gl["attention"], "url": url_for("goals.detail", org_slug=org.slug, id=o.id), "kr": []}
        edges.append(("vision" if "vision" in nodes else "org", gid, "goal"))
        progress_sum += view.progress * (o.weight or 1)
        weight_sum += (o.weight or 1)
        for k in gl["krs"]:
            kr = k["kr"]
            kid = f"kr:{kr.id}"
            row = k["row"]
            data = row["data"] if row and row.get("data") else None
            total_krs += 1
            prog = k.get("progress", 0)
            node = {"id": kid, "type": "kr", "label": kr.title, "status": k["status"], "progress": _pct(prog), "unit": kr.unit_label or "",
                    "now": F.fmt_value(kr.current_value, kr.unit_label), "target": F.fmt_value(kr.target_value, kr.unit_label), "source": "data" if data else "manual",
                    "gap": F.fmt_value(round(k["gap"]), kr.unit_label) if k["gap"] is not None and k["gap"] > 0 and k["status"] in BAD else "",
                    "goal": gid, "branches": [], "levers": [], "series": None}
            if row and row.get("projected"):
                node["lands"] = F.fmt_value(row["projected"]["mid"], kr.unit_label)
            nodes[kid] = node
            nodes[gid]["kr"].append(kid)
            edges.append((gid, kid, "kr"))
            if k["gap"] is not None and k["gap"] > 0 and k["status"] in BAD and (biggest is None or k["gap"] > biggest[0]):
                biggest = (k["gap"], kid)
            if data:
                fed += 1
                s = data["series"]
                sid = f"ds:{s.id}"
                if sid not in nodes:
                    nodes[sid] = {"id": sid, "type": "series", "label": s.name, "latest": F.fmt_value(data["latest"], s.unit), "period": F.fmt_date(data["latest_period"], "month"),
                                  "age_days": data.get("age_days", 0), "users": []}
                series_users.setdefault(sid, []).append(kid)
                nodes[sid]["users"].append(kid)
                node["series"] = sid
                edges.append((kid, sid, "measured_by"))
            for i, b in enumerate(k["branches"][:4]):
                bid = f"br:{kr.id}:{i}"
                nodes[bid] = {"id": bid, "type": "branch", "label": b["name"], "tone": b["tone"], "text": b["text"], "delta": b.get("delta"), "kr": kid}
                node["branches"].append(bid)
                edges.append((kid, bid, "branch"))
            for lv in k["levers"][:3]:
                lid = f"lv:{len(nodes)}"
                nodes[lid] = {"id": lid, "type": "lever", "label": lv["title"], "status": lv["status"], "effect": lv["effect"], "kr": kid}
                node["levers"].append(lid)
                edges.append((lid, kid, "lever"))

    for gid in goals:                                   # alignment: a goal that serves another goal of the same scope
        pid = nodes[gid].pop("parent_id", None)
        if pid and f"goal:{pid}" in nodes:
            nodes[gid]["parent"] = f"goal:{pid}"
            edges.append((gid, f"goal:{pid}", "serves"))

    c = m["counts"]
    reached = c.get("completed", 0)
    stats = {
        "journey": _pct(progress_sum / weight_sum) if weight_sum else 0,
        "time": _pct(time_share) if time_share is not None else None,
        "days_left": days_left,
        "cycle": cyc.name if cyc else "",
        "stations": m["total"], "reached": reached, "on_track": c.get("on_track", 0), "at_risk": c.get("at_risk", 0), "off_track": c.get("off_track", 0),
        "fed": fed, "krs": total_krs,
        "biggest": biggest[1] if biggest else None,
        "shared": [sid for sid, users in series_users.items() if len({nodes[u]["goal"] for u in users}) > 1],
    }
    return {"nodes": nodes, "goals": goals, "edges": edges, "stats": stats, "org": nodes["org"], "today": today, "empty": not goals}


def digest(facts: dict) -> dict:
    """What a model may read: ids, types, labels, statuses, whole-number progress. No series values, no amounts."""
    out = []
    for n in facts["nodes"].values():
        d = {"id": n["id"], "type": n["type"], "label": (n.get("label") or "")[:60]}
        for k in ("status", "progress", "expected", "tone", "kr", "goal"):
            if n.get(k) is not None:
                d[k] = n[k]
        if n["type"] == "goal":
            d["krs"] = n["kr"]
        if n["type"] == "kr":
            d["branches"], d["levers"], d["series"] = n["branches"], n["levers"], n["series"]
        out.append(d)
    s = facts["stats"]
    return {"nodes": out, "stats": {"journey": s["journey"], "time": s["time"], "at_risk": s["at_risk"], "off_track": s["off_track"], "stations": s["stations"], "shared": s["shared"]}}
