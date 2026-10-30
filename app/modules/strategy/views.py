from __future__ import annotations

from flask import abort, current_app, flash, g, redirect, render_template, request, url_for

from app.core import forms as F
from app.core.i18n import t
from app.core.models import Link
from app.core.permissions import require
from app.core.services import add_link, links_from, links_to, log_activity, current_cycle
from app.extensions import db
from app.modules.strategy import bp
from app.modules.strategy.models import FOUNDATION_KINDS, SWOT_KINDS, FoundationItem, Priority, SwotItem


def _goals_on() -> bool:
    return current_app.extensions["modules"].is_enabled("goals")


def _get(model, ident):
    obj = F.get_scoped(model, ident)
    return obj


def _single(kind: str) -> FoundationItem | None:
    return FoundationItem.query.filter_by(org_id=g.org.id, kind=kind).first()


@bp.get("/")
def index():
    values = FoundationItem.query.filter_by(org_id=g.org.id, kind="value").order_by(FoundationItem.position, FoundationItem.id).all()
    priorities = Priority.query.filter_by(org_id=g.org.id).order_by(Priority.position, Priority.id).all()
    rolled = {}
    options = []
    if _goals_on():
        from app.modules.goals.service import compute_objectives

        views = compute_objectives(g.org)
        for p in priorities:
            ids = [l.source_id for l in links_to(g.org.id, ("priority", p.id), "supports") if l.source_type == "objective"]
            vs = [views[i] for i in ids if i in views]
            avg = sum(v.progress for v in vs) / len(vs) if vs else None
            rolled[p.id] = {"objectives": vs, "avg": avg}
        options = sorted(views.values(), key=lambda v: v.obj.title)
    return render_template("strategy/index.html", vision=_single("vision"), mission=_single("mission"), values=values,
                           priorities=priorities, rolled=rolled, options=options, goals_on=_goals_on())


@bp.post("/foundation")
@require("strategy.edit")
def foundation_save():
    for kind in ("vision", "mission"):
        text = F.s(kind)
        row = _single(kind)
        if row is None:
            row = FoundationItem(org_id=g.org.id, kind=kind)
            db.session.add(row)
        row.text = text
    db.session.commit()
    flash(t("strategy.flash.saved"), "success")
    return redirect(url_for("strategy.index"))


@bp.post("/values")
@require("strategy.edit")
def value_add():
    title = F.s("title", maxlen=200)
    if title:
        n = FoundationItem.query.filter_by(org_id=g.org.id, kind="value").count()
        db.session.add(FoundationItem(org_id=g.org.id, kind="value", title=title, text=F.s("text"), position=n))
        db.session.commit()
    return redirect(url_for("strategy.index") + "#values")


@bp.post("/values/<int:id>/delete")
@require("strategy.edit")
def value_delete(id):
    row = _get(FoundationItem, id)
    if row.kind == "value":
        db.session.delete(row)
        db.session.commit()
    return redirect(url_for("strategy.index") + "#values")


@bp.post("/priorities")
@require("strategy.edit")
def priority_add():
    title = F.s("title", maxlen=200)
    if title:
        n = Priority.query.filter_by(org_id=g.org.id).count()
        p = Priority(org_id=g.org.id, title=title, description=F.s("description"), position=n)
        db.session.add(p)
        db.session.flush()
        log_activity("created", "priority", p.id, p.title)
        db.session.commit()
    return redirect(url_for("strategy.index") + "#priorities")


@bp.post("/priorities/<int:id>/delete")
@require("strategy.edit")
def priority_delete(id):
    p = _get(Priority, id)
    Link.query.filter_by(org_id=g.org.id, target_type="priority", target_id=p.id).delete()
    db.session.delete(p)
    db.session.commit()
    return redirect(url_for("strategy.index") + "#priorities")


@bp.post("/priorities/<int:id>/attach")
@require("strategy.edit")
def priority_attach(id):
    p = _get(Priority, id)
    if _goals_on():
        from app.modules.goals.models import Objective

        o = db.session.get(Objective, F.integer("objective_id") or 0)
        if o and o.org_id == g.org.id:
            add_link(g.org.id, ("objective", o.id), ("priority", p.id), "supports")
            db.session.commit()
    return redirect(url_for("strategy.index") + f"#priority-{p.id}")


@bp.post("/priorities/<int:id>/detach/<int:oid>")
@require("strategy.edit")
def priority_detach(id, oid):
    p = _get(Priority, id)
    Link.query.filter_by(org_id=g.org.id, source_type="objective", source_id=oid, target_type="priority", target_id=p.id).delete()
    db.session.commit()
    return redirect(url_for("strategy.index") + f"#priority-{p.id}")


# -- SWOT ---------------------------------------------------------------------------------
@bp.get("/swot")
def swot():
    rows = SwotItem.query.filter_by(org_id=g.org.id).order_by(SwotItem.position, SwotItem.id).all()
    return render_template("strategy/swot.html", groups={k: [r for r in rows if r.kind == k] for k in SWOT_KINDS}, kinds=SWOT_KINDS)


@bp.post("/swot")
@require("strategy.edit")
def swot_add():
    kind, text = F.choice("kind", SWOT_KINDS), F.s("text", maxlen=400)
    if kind and text:
        n = SwotItem.query.filter_by(org_id=g.org.id, kind=kind).count()
        db.session.add(SwotItem(org_id=g.org.id, kind=kind, text=text, position=n))
        db.session.commit()
    return redirect(url_for("strategy.swot") + f"#{kind or ''}")


@bp.post("/swot/<int:id>/delete")
@require("strategy.edit")
def swot_delete(id):
    row = _get(SwotItem, id)
    kind = row.kind
    db.session.delete(row)
    db.session.commit()
    return redirect(url_for("strategy.swot") + f"#{kind}")


# -- strategy map ---------------------------------------------------------------------------
LANES = ("financial", "customer", "process", "learning")


@bp.get("/map")
def map():
    if not _goals_on():
        abort(404)
    from app.modules.goals.models import Objective
    from app.modules.goals.service import compute_objectives

    views = compute_objectives(g.org)
    cur = current_cycle(g.org)
    cycle_ids = {cur.id, cur.parent_id} if cur else set()
    # strategic level = objectives without a parent in the current cycle (year-level)
    top = [v for v in views.values() if v.obj.parent_id is None and (not cycle_ids or v.obj.cycle_id in cycle_ids)]
    lanes = {p: sorted([v for v in top if v.obj.perspective == p], key=lambda v: v.obj.id) for p in LANES}
    unassigned = [v for v in top if v.obj.perspective not in LANES]
    ids = {v.obj.id for v in top}
    edges = [{"from": l.source_id, "to": l.target_id} for l in Link.query.filter_by(org_id=g.org.id, source_type="objective", target_type="objective", kind="supports").all()
             if l.source_id in ids and l.target_id in ids]
    return render_template("strategy/map.html", lanes=lanes, unassigned=unassigned, edges=edges, top=sorted(top, key=lambda v: v.obj.title))


@bp.post("/map/link")
@require("strategy.edit")
def map_link():
    if not _goals_on():
        abort(404)
    a, b = F.integer("source_id"), F.integer("target_id")
    if a and b and a != b:
        from app.modules.goals.models import Objective

        oa, ob = db.session.get(Objective, a), db.session.get(Objective, b)
        if oa and ob and oa.org_id == g.org.id and ob.org_id == g.org.id:
            add_link(g.org.id, ("objective", a), ("objective", b), "supports")
            db.session.commit()
    return redirect(url_for("strategy.map"))


@bp.post("/map/unlink")
@require("strategy.edit")
def map_unlink():
    a, b = F.integer("source_id"), F.integer("target_id")
    Link.query.filter_by(org_id=g.org.id, source_type="objective", source_id=a, target_type="objective", target_id=b, kind="supports").delete()
    db.session.commit()
    return redirect(url_for("strategy.map"))
