from __future__ import annotations

from datetime import date, datetime, timedelta

from flask import current_app, flash, g, redirect, render_template, request, url_for

from app.core import forms as F
from app.core.i18n import t
from app.core.models import CheckIn, Cycle, Link, Membership, OrgUnit
from app.core.permissions import require
from app.core.services import (add_checkin, add_link, current_cycle, entity_title, entity_url, links_from,
                               log_activity, remove_links_of, units)
from app.extensions import db
from app.modules.initiatives import bp
from app.modules.initiatives.models import PRIORITIES, STATES, Initiative, Milestone
from app.modules.initiatives.service import compute

LIVE = ("on_track", "at_risk", "off_track")


def _form_data():
    return {
        "cycles": Cycle.query.filter_by(org_id=g.org.id).order_by(Cycle.start_date.desc()).all(),
        "units": units(g.org),
        "members": Membership.query.filter_by(org_id=g.org.id).all(),
        "states": STATES, "priorities": PRIORITIES,
    }


def _goal_options():
    """Objectives an initiative can support — only when the goals module is enabled."""
    if not current_app.extensions["modules"].is_enabled("goals"):
        return []
    from app.modules.goals.models import Objective

    return Objective.query.filter_by(org_id=g.org.id).order_by(Objective.title).all()


def _apply(it: Initiative) -> str | None:
    title = F.s("title", maxlen=255)
    if not title:
        return "initiatives.errors.title_required"
    it.title, it.description = title, F.s("description")
    it.state = F.choice("state", STATES, "planned")
    it.priority = F.choice("priority", PRIORITIES, "medium")
    cyc = db.session.get(Cycle, F.integer("cycle_id") or 0)
    it.cycle_id = cyc.id if cyc and cyc.org_id == g.org.id else None
    unit = db.session.get(OrgUnit, F.integer("unit_id") or 0)
    it.unit_id = unit.id if unit and unit.org_id == g.org.id else None
    owner = F.member_or_none(F.integer("owner_id"))
    it.owner_id = owner.id if owner else None
    it.start_date, it.end_date = F.when("start_date"), F.when("end_date")
    if it.start_date and it.end_date and it.end_date <= it.start_date:
        return "initiatives.errors.dates"
    mp = F.num("manual_progress")
    it.manual_progress = None if mp is None else max(0.0, min(1.0, mp / 100.0))
    return None


@bp.get("/")
def index():
    views = compute(g.org)
    unit_id, status, q = request.args.get("unit", type=int), request.args.get("status"), (request.args.get("q") or "").strip().lower()
    rows = list(views.values())
    if unit_id:
        rows = [v for v in rows if v.obj.unit_id == unit_id]
    if q:
        rows = [v for v in rows if q in v.obj.title.lower()]
    counts = {}
    for v in rows:
        counts[v.status] = counts.get(v.status, 0) + 1
    if status:
        rows = [v for v in rows if v.status == status]
    rows.sort(key=lambda v: (v.obj.state in ("completed", "cancelled"), v.obj.end_date or date.max))
    return render_template("initiatives/index.html", rows=rows, counts=counts, status=status, unit_id=unit_id, q=request.args.get("q", ""),
                           units=units(g.org), total=len(views))


@bp.get("/board")
def board():
    views = compute(g.org)
    cols = {s: sorted([v for v in views.values() if v.obj.state == s], key=lambda v: (v.obj.position, v.obj.end_date or date.max)) for s in STATES}
    return render_template("initiatives/board.html", cols=cols, states=STATES)


@bp.get("/roadmap")
def roadmap():
    views = [v for v in compute(g.org).values() if v.obj.start_date and v.obj.end_date and v.obj.state != "cancelled"]
    cur = current_cycle(g.org)
    year = (cur.start_date.year if cur else date.today().year)
    lo, hi = date(year, 1, 1), date(year, 12, 31)
    for v in views:  # widen when something starts earlier / ends later
        lo, hi = min(lo, v.obj.start_date.replace(day=1)), max(hi, v.obj.end_date)
    total = (hi - lo).days or 1
    months, d = [], lo
    while d <= hi:
        nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        months.append({"date": d, "left": (d - lo).days / total * 100, "width": (min(nxt, hi + timedelta(days=1)) - d).days / total * 100})
        d = nxt
    bars = []
    for v in sorted(views, key=lambda v: (v.obj.unit.name if v.obj.unit else "", v.obj.start_date)):
        bars.append({"v": v, "left": (v.obj.start_date - lo).days / total * 100, "width": max(((v.obj.end_date - v.obj.start_date).days) / total * 100, 1.2),
                     "milestones": [{"m": m, "left": (m.due_date - lo).days / total * 100} for m in v.obj.milestones if m.due_date and lo <= m.due_date <= hi]})
    today_left = (date.today() - lo).days / total * 100 if lo <= date.today() <= hi else None
    return render_template("initiatives/roadmap.html", bars=bars, months=months, today_left=today_left)


@bp.route("/new", methods=["GET", "POST"])
@require("initiatives.edit")
def new():
    it = Initiative(org_id=g.org.id, state="planned", priority="medium")
    if request.method == "POST":
        err = _apply(it)
        if err:
            flash(t(err), "error")
        else:
            db.session.add(it)
            db.session.flush()
            goal = F.integer("goal_id")
            if goal and current_app.extensions["modules"].is_enabled("goals"):
                _link_goal(it, goal)
            log_activity("created", "initiative", it.id, it.title)
            db.session.commit()
            flash(t("initiatives.flash.created"), "success")
            return redirect(url_for("initiatives.detail", id=it.id))
    else:
        cur = current_cycle(g.org)
        it.cycle_id = cur.id if cur else None
        it.start_date, it.end_date = (cur.start_date, cur.end_date) if cur else (None, None)
    return render_template("initiatives/form.html", it=it, mode="new", goals=_goal_options(), preset_goal=request.args.get("goal", type=int), **_form_data())


def _link_goal(it: Initiative, objective_id: int) -> bool:
    from app.modules.goals.models import Objective

    obj = db.session.get(Objective, objective_id)
    if obj and obj.org_id == g.org.id:
        add_link(g.org.id, ("initiative", it.id), ("objective", obj.id), "supports")
        return True
    return False


@bp.get("/<int:id>")
def detail(id):
    it = F.get_scoped(Initiative, id)
    v = compute(g.org)[it.id]
    supports = []
    for l in links_from(g.org.id, ("initiative", it.id), "supports"):
        url = entity_url(l.target_type, l.target_id)
        if url:
            supports.append({"id": l.id, "title": entity_title(l.target_type, l.target_id), "url": url, "type": l.target_type})
    feed = CheckIn.query.filter_by(org_id=g.org.id, entity_type="initiative", entity_id=it.id).order_by(CheckIn.created_at.desc(), CheckIn.id.desc()).limit(20).all()
    return render_template("initiatives/detail.html", it=it, v=v, supports=supports, goals=_goal_options(), feed=feed, statuses=LIVE, states=STATES)


@bp.route("/<int:id>/edit", methods=["GET", "POST"])
@require("initiatives.edit")
def edit(id):
    it = F.get_scoped(Initiative, id)
    if request.method == "POST":
        err = _apply(it)
        if err:
            flash(t(err), "error")
        else:
            log_activity("updated", "initiative", it.id, it.title)
            db.session.commit()
            flash(t("initiatives.flash.saved"), "success")
            return redirect(url_for("initiatives.detail", id=it.id))
    return render_template("initiatives/form.html", it=it, mode="edit", goals=[], preset_goal=None, **_form_data())


@bp.post("/<int:id>/delete")
@require("initiatives.delete")
def delete(id):
    it = F.get_scoped(Initiative, id)
    CheckIn.query.filter_by(org_id=g.org.id, entity_type="initiative", entity_id=it.id).delete()
    remove_links_of(g.org.id, "initiative", it.id)
    log_activity("deleted", "initiative", it.id, it.title)
    db.session.delete(it)
    db.session.commit()
    flash(t("initiatives.flash.deleted"), "success")
    return redirect(url_for("initiatives.index"))


@bp.post("/<int:id>/state")
@require("initiatives.edit")
def set_state(id):
    it = F.get_scoped(Initiative, id)
    state = F.choice("state", STATES)
    if state:
        it.state = state
        log_activity("updated", "initiative", it.id, it.title)
        db.session.commit()
    return redirect(request.form.get("back") if (request.form.get("back") or "").startswith("/") else url_for("initiatives.board"))


@bp.post("/<int:id>/milestones")
@require("initiatives.edit")
def milestone_add(id):
    it = F.get_scoped(Initiative, id)
    title = F.s("title", maxlen=255)
    if title:
        db.session.add(Milestone(initiative_id=it.id, title=title, due_date=F.when("due_date")))
        log_activity("updated", "initiative", it.id, it.title)
        db.session.commit()
    return redirect(url_for("initiatives.detail", id=it.id) + "#milestones")


def _milestone(mid: int) -> Milestone:
    m = db.session.get(Milestone, mid)
    if m is None or m.initiative.org_id != g.org.id:
        from flask import abort

        abort(404)
    return m


@bp.post("/milestones/<int:mid>/toggle")
@require("initiatives.edit")
def milestone_toggle(mid):
    m = _milestone(mid)
    m.done = not m.done
    m.done_at = datetime.utcnow() if m.done else None
    log_activity("updated", "initiative", m.initiative_id, m.initiative.title)
    db.session.commit()
    return redirect(url_for("initiatives.detail", id=m.initiative_id) + "#milestones")


@bp.post("/milestones/<int:mid>/delete")
@require("initiatives.edit")
def milestone_delete(mid):
    m = _milestone(mid)
    iid = m.initiative_id
    db.session.delete(m)
    db.session.commit()
    return redirect(url_for("initiatives.detail", id=iid) + "#milestones")


@bp.post("/<int:id>/checkin")
@require("checkin")
def checkin(id):
    it = F.get_scoped(Initiative, id)
    status, comment = F.choice("status", LIVE), F.s("comment")
    if not status and not comment:
        flash(t("initiatives.errors.checkin_empty"), "error")
    else:
        v = compute(g.org)[it.id]
        add_checkin("initiative", it.id, progress=v.progress, status=status, comment=comment)
        log_activity("checked_in", "initiative", it.id, it.title)
        db.session.commit()
        flash(t("initiatives.flash.checkin"), "success")
    return redirect(url_for("initiatives.detail", id=it.id) + "#feed")


@bp.post("/<int:id>/link")
@require("initiatives.edit")
def link_goal(id):
    it = F.get_scoped(Initiative, id)
    if current_app.extensions["modules"].is_enabled("goals") and _link_goal(it, F.integer("goal_id") or 0):
        db.session.commit()
    return redirect(url_for("initiatives.detail", id=it.id) + "#supports")


@bp.post("/<int:id>/unlink/<int:link_id>")
@require("initiatives.edit")
def unlink(id, link_id):
    it = F.get_scoped(Initiative, id)
    l = db.session.get(Link, link_id)
    if l and l.org_id == g.org.id and l.source_type == "initiative" and l.source_id == it.id:
        db.session.delete(l)
        db.session.commit()
    return redirect(url_for("initiatives.detail", id=it.id) + "#supports")
