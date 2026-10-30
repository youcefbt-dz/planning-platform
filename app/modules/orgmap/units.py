"""Departments: a grid of every department with how its goals stand, and one page per department (its head, people, goals, numbers, and which
other departments it depends on or serves). Owns no tables: heads and members come from the core, goals from the goals module, and a
dependency between departments is *derived* from `depends_on` links between their goals, so nobody has to maintain it twice."""
from __future__ import annotations

from flask import abort, current_app, flash, g, redirect, render_template, request, url_for

from app.core import forms as F
from app.core.i18n import t
from app.core.models import Cycle, Link, Membership, OrgUnit
from app.core.permissions import can, require
from app.core.services import current_cycle, units
from app.extensions import db
from app.modules.orgmap import bp

BAD = ("off_track", "at_risk")


def _goals_on() -> bool:
    return current_app.extensions["modules"].is_enabled("goals")


def _subtree(all_units, uid: int) -> set[int]:
    kids: dict = {}
    for u in all_units:
        kids.setdefault(u.parent_id, []).append(u.id)
    out, todo = set(), [uid]
    while todo:
        x = todo.pop()
        if x not in out:
            out.add(x)
            todo += kids.get(x, [])
    return out


def _cycle_pool(views):
    cycles = Cycle.query.filter_by(org_id=g.org.id).order_by(Cycle.start_date.desc()).all()
    arg = request.args.get("cycle")
    cur = current_cycle(g.org)
    cid = None if arg == "all" else (int(arg) if (arg or "").isdigit() else (cur.id if cur else None))
    inside = {cid, *[c.id for c in cycles if c.parent_id == cid]} if cid else None
    return cycles, cid, {k: v for k, v in views.items() if inside is None or v.obj.cycle_id in inside}


def _standing(vs) -> str:
    st = [v.status for v in vs]
    for s in ("off_track", "at_risk"):
        if s in st:
            return s
    if st and all(s == "completed" for s in st):
        return "completed"
    return "on_track" if st else "not_started"


def _card(u, all_units, views_pool, members):
    ids = _subtree(all_units, u.id)
    mine = [v for v in views_pool.values() if v.obj.unit_id in ids]
    avg = sum(v.progress for v in mine) / len(mine) if mine else 0.0
    counts: dict = {}
    for v in mine:
        counts[v.status] = counts.get(v.status, 0) + 1
    return {"unit": u, "goals": len(mine), "avg": avg, "status": _standing(mine), "counts": counts,
            "people": sum(1 for m in members if m.unit_id in ids), "head": u.head}


@bp.get("/units")
def units_index():
    from app.modules.goals.service import compute_objectives

    all_units = units(g.org)
    members = Membership.query.filter_by(org_id=g.org.id).all()
    views = compute_objectives(g.org) if _goals_on() else {}
    cycles, cycle_id, pool = _cycle_pool(views)
    cards = [_card(u, all_units, pool, members) for u in all_units if u.kind != "company"]
    root = next((u for u in all_units if u.kind == "company"), None)
    return render_template("orgmap/units.html", cards=cards, root=root, cycles=cycles, cycle_id=cycle_id, goals_on=_goals_on(),
                           headless=sum(1 for c in cards if not c["head"]), people=len(members))


@bp.get("/units/<int:id>")
def unit(id):
    all_units = units(g.org)
    u = next((x for x in all_units if x.id == id), None)
    if u is None:
        abort(404)
    ids = _subtree(all_units, u.id)
    members = Membership.query.filter_by(org_id=g.org.id).all()
    direct = [m for m in members if m.unit_id == u.id]
    direct.sort(key=lambda m: (m.user_id != u.head_id, m.user.name))
    subs = [x for x in all_units if x.parent_id == u.id]
    ctx = dict(u=u, direct=direct, subs=subs, parent=u.parent, goals_on=_goals_on(), people=sum(1 for m in members if m.unit_id in ids), all_units=all_units)
    if not _goals_on():
        return render_template("orgmap/unit.html", **ctx, mine=[], decisions=[], inds=[], depends=[], serves=[], cycles=[], cycle_id=None, stats=None, my_goals=[], other_goals=[])
    from app.modules.goals.service import compute_indicators, compute_objectives, summary

    views = compute_objectives(g.org)
    cycles, cycle_id, pool = _cycle_pool(views)
    mine = sorted((v for v in pool.values() if v.obj.unit_id in ids), key=lambda v: (v.progress - v.expected, v.obj.id))
    stats = summary(views, mine)
    decisions = sorted(((v, k) for v in mine for k in v.krs if k.status in BAD), key=lambda x: (x[1].status != "off_track", x[1].progress))[:5]
    inds = [i for i in compute_indicators(g.org) if i.ind.unit_id in ids]
    # dependencies between departments, derived from goal-to-goal `depends_on` links
    mine_ids = {v.obj.id for v in views.values() if v.obj.unit_id in ids}     # whatever the cycle: a dependency does not expire with a quarter
    links = Link.query.filter_by(org_id=g.org.id, source_type="objective", target_type="objective", kind="depends_on").all()
    dep: dict = {}
    srv: dict = {}
    for l in links:
        a, b = views.get(l.source_id), views.get(l.target_id)
        if not a or not b:
            continue
        if a.obj.id in mine_ids and b.obj.unit_id not in ids:
            dep.setdefault(b.obj.unit_id, []).append((l, a, b))
        elif b.obj.id in mine_ids and a.obj.unit_id not in ids:
            srv.setdefault(a.obj.unit_id, []).append((l, a, b))
    by_id = {x.id: x for x in all_units}
    rel = lambda d: [{"unit": by_id.get(k), "pairs": v, "status": _standing([p[2] for p in v] if d == "dep" else [p[1] for p in v])} for k, v in d_items(d, dep, srv) if by_id.get(k)]
    my_goals = [v for v in views.values() if v.obj.unit_id in ids and v.obj.state == "active"]
    other_goals = [v for v in views.values() if v.obj.unit_id not in ids and v.obj.state == "active"]
    return render_template("orgmap/unit.html", **ctx, mine=mine, stats=stats, decisions=decisions, inds=inds, cycles=cycles, cycle_id=cycle_id,
                           depends=rel("dep"), serves=rel("srv"), my_goals=my_goals, other_goals=other_goals)


def d_items(kind, dep, srv):
    return (dep if kind == "dep" else srv).items()


@bp.post("/units/<int:id>/depends")
@require("goals.edit")
def unit_depends_add(id):
    from app.modules.goals.models import Objective

    mine = db.session.get(Objective, F.integer("goal_id") or 0)
    other = db.session.get(Objective, F.integer("on_id") or 0)
    ok = mine and other and mine.org_id == g.org.id == other.org_id and mine.id != other.id
    if ok and not Link.query.filter_by(org_id=g.org.id, source_type="objective", source_id=mine.id, target_type="objective", target_id=other.id, kind="depends_on").first():
        db.session.add(Link(org_id=g.org.id, source_type="objective", source_id=mine.id, target_type="objective", target_id=other.id, kind="depends_on"))
        db.session.commit()
        flash(t("settings.flash.saved"), "success")
    return redirect(url_for("orgmap.unit", id=id) + "#relations")


@bp.post("/units/<int:id>/depends/<int:lid>/delete")
@require("goals.edit")
def unit_depends_del(id, lid):
    l = F.get_scoped(Link, lid)
    if l.kind == "depends_on":
        db.session.delete(l)
        db.session.commit()
    return redirect(url_for("orgmap.unit", id=id) + "#relations")
