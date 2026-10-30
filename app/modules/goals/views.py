"""Goals routes. Server-rendered pages + plain form posts; no client framework."""
from __future__ import annotations

from datetime import date

from flask_login import current_user
from flask import abort, current_app, flash, g, jsonify, redirect, render_template, request, url_for

from app import ai
from app.ai import library as ai_library
from app.core import forms as F
from app.core import progress as P
from app.core import scope as SC
from app.core.charts import line_chart
from app.core.i18n import t
from app.core.models import Cycle, Link, Membership, OrgUnit, CheckIn
from app.core.permissions import require
from app.core.services import (add_checkin, add_link, checkins_for, current_cycle, entity_title, entity_url,
                               links_to, log_activity, remove_links_of, units)
from app.extensions import db
from app.modules.goals import bp
from app.modules.goals import coach, factors as FX, health as H, path as PATH
from app.modules.goals.models import (CERTAINTIES, COMMITMENTS, FACTOR_KINDS, FREQUENCIES, KR_TYPES, MEASURES, METRIC_TYPES, PERSPECTIVES,
                                      PROGRESS_DRIVERS, GoalEvent, Indicator, IndicatorValue, KeyResult, KRFactor, Objective)
from app.modules.goals.service import compute_indicators, compute_objectives, roots, summary

LEVER_STATES = ("planned", "in_progress", "done", "dropped")
LIVE_FILTERS = ("on_track", "at_risk", "off_track", "not_started", "completed", "on_hold", "cancelled")


# -- shared form data -----------------------------------------------------------
def _form_data(exclude_id: int | None = None) -> dict:
    cycles = Cycle.query.filter_by(org_id=g.org.id).order_by(Cycle.start_date.desc()).all()
    members = Membership.query.filter_by(org_id=g.org.id).all()
    all_objs = Objective.query.filter_by(org_id=g.org.id).order_by(Objective.id).all()
    blocked = set()
    if exclude_id:  # an objective cannot sit under itself or its own descendants
        blocked = {exclude_id}
        grew = True
        while grew:
            grew = False
            for o in all_objs:
                if o.parent_id in blocked and o.id not in blocked:
                    blocked.add(o.id)
                    grew = True
    return {
        "cycles": cycles, "units": SC.allowed_units(units(g.org)), "members": members,
        "parents": [o for o in all_objs if o.id not in blocked],
        "perspectives": PERSPECTIVES, "drivers": PROGRESS_DRIVERS, "metric_types": METRIC_TYPES,
        "kr_types": KR_TYPES, "commitments": COMMITMENTS, "has_series": _has_series(), "ai_state": _ai_badge(),
    }


def _modules():
    return current_app.extensions["modules"]


def _has_series() -> bool:
    return bool(_modules().query("series.exists", g.org.id))


def _apply_objective(o: Objective) -> str | None:
    title = F.s("title", maxlen=255)
    if not title:
        return "goals.errors.title_required"
    o.title = title
    o.description = F.s("description")
    o.rationale = F.s("rationale", maxlen=600)
    o.commitment = F.choice("commitment", COMMITMENTS, "committed")
    o.cycle_id = F.integer("cycle_id") if db.session.get(Cycle, F.integer("cycle_id") or 0) else None
    unit = db.session.get(OrgUnit, F.integer("unit_id") or 0)
    o.unit_id = unit.id if unit and unit.org_id == g.org.id else None
    owner = F.member_or_none(F.integer("owner_id"))
    o.owner_id = owner.id if owner else None
    parent = db.session.get(Objective, F.integer("parent_id") or 0)
    o.parent_id = parent.id if parent and parent.org_id == g.org.id and parent.id != o.id else None
    o.perspective = F.choice("perspective", PERSPECTIVES)
    o.progress_driver = F.choice("progress_driver", PROGRESS_DRIVERS, "key_results")
    o.weight = F.num("weight", 1.0) or 1.0
    o.state = F.choice("state", ("active", "on_hold", "cancelled"), "active")
    o.start_date, o.end_date = F.when("start_date"), F.when("end_date")
    if o.start_date and o.end_date and o.end_date <= o.start_date:
        return "goals.errors.dates"
    return None


# -- list -------------------------------------------------------------------------
@bp.get("/")
def index():
    views = compute_objectives(g.org)
    cycles = Cycle.query.filter_by(org_id=g.org.id).order_by(Cycle.start_date.desc()).all()
    cycle_arg = request.args.get("cycle")
    cur = current_cycle(g.org)
    cycle_id = None if cycle_arg == "all" else (int(cycle_arg) if (cycle_arg or "").isdigit() else (cur.id if cur else None))
    unit_id = request.args.get("unit", type=int)
    owner_id = request.args.get("owner", type=int)
    q = (request.args.get("q") or "").strip().lower()
    status = request.args.get("status")

    pool = [v for v in views.values() if (not cycle_id or v.obj.cycle_id in (cycle_id, *[c.id for c in cycles if c.parent_id == cycle_id]))]
    if unit_id:
        pool = [v for v in pool if v.obj.unit_id == unit_id]
    if owner_id:
        pool = [v for v in pool if v.obj.owner_id == owner_id]
    if q:
        pool = [v for v in pool if q in v.obj.title.lower()]
    stats = summary(views, pool)
    shown = [v for v in pool if not status or v.status == status]
    sort = request.args.get("sort") if request.args.get("sort") in ("gap", "progress", "title") else "gap"
    if sort == "gap":
        shown.sort(key=lambda v: (v.progress - v.expected, v.obj.id))
    elif sort == "progress":
        shown.sort(key=lambda v: (-v.progress, v.obj.id))
    else:
        shown.sort(key=lambda v: v.obj.title)
    return render_template(
        "goals/index.html", rows=shown, sort=sort, stats=stats, cycles=cycles, cycle_id=cycle_id, unit_id=unit_id,
        owner_id=owner_id, q=request.args.get("q", ""), status=status, filters=LIVE_FILTERS,
        units=units(g.org), members=Membership.query.filter_by(org_id=g.org.id).all(), views=views,
    )


@bp.get("/tree")
def tree():
    views = compute_objectives(g.org)
    cycles = Cycle.query.filter_by(org_id=g.org.id).order_by(Cycle.start_date.desc()).all()
    cur = current_cycle(g.org)
    arg = request.args.get("cycle")
    cycle_id = None if arg == "all" else (int(arg) if (arg or "").isdigit() else (cur.id if cur else None))
    inside = {cycle_id, *[c.id for c in cycles if c.parent_id == cycle_id]} if cycle_id else None
    pool = {k: v for k, v in views.items() if inside is None or v.obj.cycle_id in inside}
    for v in list(pool.values()):                                   # a goal's ancestors stay in the map even when they belong to the year's cycle
        p = views.get(v.obj.parent_id)
        while p is not None and p.obj.id not in pool:
            pool[p.obj.id] = p
            p = views.get(p.obj.parent_id)
    top = sorted((v for v in pool.values() if v.obj.parent_id not in pool), key=lambda v: v.obj.id)
    stats = summary(views, list(pool.values()))
    return render_template("goals/tree.html", roots=top, cycles=cycles, cycle_id=cycle_id, stats=stats, pool=pool)


# -- objective CRUD ---------------------------------------------------------------
@bp.route("/new", methods=["GET", "POST"])
@require("goals.edit")
def new():
    if not SC.can_add_goal():
        abort(403)
    if request.method == "GET" and not request.args.get("classic") and not request.args.get("parent"):
        return redirect(url_for("goals.compose", **request.args))
    o = Objective(org_id=g.org.id, progress_driver="key_results")
    cur = current_cycle(g.org)
    if request.method == "POST":
        err = _apply_objective(o)
        if not err and not SC.can_edit_unit(o.unit_id):
            err = "goals.errors.unit_scope"
        if err:
            flash(t(err), "error")
        else:
            db.session.add(o)
            db.session.flush()
            _create_initial_krs(o)
            log_activity("created", "objective", o.id, o.title)
            db.session.commit()
            flash(t("goals.flash.created"), "success")
            return redirect(url_for("goals.detail", id=o.id))
    else:
        o.cycle_id = cur.id if cur else None
        o.parent_id = request.args.get("parent", type=int)
        o.unit_id = request.args.get("unit", type=int)
        if not SC.can_edit_unit(o.unit_id):
            o.unit_id = SC.default_unit_id()
    return render_template("goals/form.html", o=o, mode="new", **_form_data())


# -- the goal composer: a real number -> a verdict from the organization's own history -> levers -> a saved, measurable goal ---------------
def _arg_num(src, name):
    v = F.norm(src.get(name) or "").replace(" ", "")
    if "," in v and "." not in v:
        v = v.replace(",", ".")
    try:
        return float(v) if v else None
    except ValueError:
        return None


def _arg_date(src, name):
    try:
        return date.fromisoformat(F.norm(src.get(name) or ""))
    except ValueError:
        return None


@bp.route("/compose", methods=["GET", "POST"])
@require("goals.edit")
def compose():
    if not SC.can_add_goal():
        abort(403)
    from app.modules.data import reality, service as DS
    from app.modules.data.models import Series

    series_list = DS.org_series(g.org.id)
    src = request.form if request.method == "POST" else request.args
    source = src.get("source") if src.get("source") in ("data", "manual") else ("data" if series_list else "manual")
    if not series_list:
        source = "manual"
    sel = next((x for x in series_list if str(x.id) == str(src.get("series"))), None) if source == "data" else None
    cur = current_cycle(g.org)
    end = _arg_date(src, "end") or (cur.end_date if cur else None)
    target = _arg_num(src, "target")
    start = (sel.latest[1] if sel and sel.latest else None)
    result, err = None, None
    man = {"name": (src.get("name") or "").strip()[:255], "unit": (src.get("unit") or "").strip()[:24], "start": _arg_num(src, "start"),
           "direction": "lower_better" if src.get("direction") == "lower_better" else "higher_better"}
    manual_ok = source == "manual" and man["name"] and target is not None and man["start"] is not None and end
    if sel and target is not None and end and start is not None:
        result = reality.check(sel, start=start, target=target, end_date=end, goal=(src.get("title") or "")[:160])
        err = result.get("error") if result and result.get("error") else None
        result = None if err else result
    supported = gap = None
    if manual_ok:
        gap = 0.0
    if result:
        rng = result["verdict"].get("range")
        supported = rng["high"] if rng else None
        gap = FX.gap_to_target(target, supported, sel.direction) if supported is not None else 0.0
    levers = []
    for i, ttl in enumerate(src.getlist("lever_title")):
        eff = _numf((src.getlist("lever_effect") + [""] * 9)[i])
        if ttl.strip() and eff is not None:
            levers.append({"title": ttl.strip()[:200], "effect": eff, "certainty": (src.getlist("lever_certainty") + ["probable"] * 9)[i]})
    cov = FX.coverage(gap, [{"effect": x["effect"], "certainty": x["certainty"]} for x in levers]) if gap is not None else None
    ready = bool(result or manual_ok)
    title = (src.get("title") or "").strip()
    lever_ideas = ai_library.levers(title, sel.name if sel else man["name"]) if ready else []
    if request.method == "POST":
        if not (ready and title):
            flash(t("goals.compose.incomplete"), "error")
        else:
            o = Objective(org_id=g.org.id, progress_driver="key_results", title=title[:255], cycle_id=cur.id if cur else None, end_date=end)
            o.commitment = F.choice("commitment", COMMITMENTS, "committed")
            want = F.integer("unit_id") or request.args.get("unit", type=int)
            o.unit_id = want if SC.can_edit_unit(want) and want else SC.default_unit_id()
            owner = F.member_or_none(F.integer("owner_id"))
            o.owner_id = owner.id if owner else current_user.id
            db.session.add(o)
            db.session.flush()
            direction = sel.direction if sel else man["direction"]
            kind = "decrease" if direction == "lower_better" else "increase"
            begin = start if sel else man["start"]
            kr = KeyResult(org_id=g.org.id, objective_id=o.id, title=(sel.name if sel else man["name"])[:255], kr_type=kind, start_value=begin,
                           target_value=target, current_value=begin, unit_label=((sel.unit if sel else man["unit"]) or "")[:24], position=0, owner_id=o.owner_id,
                           basis={"level": result["level"], "value": target, "at": date.today().isoformat()} if result else None)
            db.session.add(kr)
            db.session.flush()
            if sel:
                _modules().hook("key_result.saved", kr, form={"series_id": str(sel.id)}, index=None)
            for x in levers:
                db.session.add(KRFactor(org_id=g.org.id, key_result_id=kr.id, title=x["title"], effect=x["effect"],
                                        certainty=x["certainty"] if x["certainty"] in CERTAINTIES else "probable", kind="other"))
            log_activity("created", "objective", o.id, o.title)
            db.session.commit()
            flash(t("goals.flash.created"), "success")
            return redirect(url_for("goals.detail", id=o.id))
    return render_template("goals/compose.html", series_list=series_list, sel=sel, source=source, man=man, ready=ready, target=target, end=end, start=start, result=result, err=err, supported=supported,
                           gap=gap, cov=cov, levers=levers, lever_ideas=lever_ideas, title=title, members=Membership.query.filter_by(org_id=g.org.id).all(), commitments=COMMITMENTS,
                           certainties=CERTAINTIES, args=src, ai_state=_ai_badge(), commitment=src.get("commitment", "committed"), owner_id=_arg_num(src, "owner_id"))


def _numf(raw, default=None):
    v = F.norm(raw or "").replace(" ", "").replace(",", ".")
    try:
        return float(v) if v else default
    except ValueError:
        return default


def _kr_values(kind, start, target):
    """Normalise the numbers a key result of this kind needs."""
    if kind == "binary":
        return 0.0, 1.0
    if kind == "milestone":
        return 0.0, target if target and target >= 1 else 4.0
    if kind in ("stay_above", "stay_below"):
        return (target if start is None else start), target
    return start, target


def _create_initial_krs(o: Objective) -> None:
    f = request.form
    titles, kinds = f.getlist("kr_title"), f.getlist("kr_type")
    starts, targets, unitl, levels = f.getlist("kr_start"), f.getlist("kr_target"), f.getlist("kr_unit"), f.getlist("kr_level")
    at = lambda lst, i, d="": lst[i] if i < len(lst) else d
    for i, title in enumerate(titles):
        title = title.strip()
        if not title:
            continue
        kind = at(kinds, i) if at(kinds, i) in KR_TYPES else "increase"
        start, target = _kr_values(kind, _numf(at(starts, i), 0.0), _numf(at(targets, i), 100.0))
        kr = KeyResult(org_id=g.org.id, objective_id=o.id, title=title[:255], kr_type=kind, start_value=start, target_value=target,
                       current_value=start, unit_label=at(unitl, i).strip()[:24], position=i, owner_id=o.owner_id)
        lvl = at(levels, i)
        if lvl in ("conservative", "ambitious", "stretch"):
            kr.basis = {"level": lvl, "value": target, "at": date.today().isoformat()}
        db.session.add(kr)
        db.session.flush()
        _modules().hook("key_result.saved", kr, form=request.form, index=i)


@bp.get("/<int:id>")
def detail(id):
    o = F.get_scoped(Objective, id)
    views = compute_objectives(g.org)
    v = views[o.id]
    kr_ids = [k.kr.id for k in v.krs]
    feed = (CheckIn.query.filter(CheckIn.org_id == g.org.id, ((CheckIn.entity_type == "objective") & (CheckIn.entity_id == o.id)) |
                                 ((CheckIn.entity_type == "key_result") & (CheckIn.entity_id.in_(kr_ids or [0]))))
            .order_by(CheckIn.created_at.desc(), CheckIn.id.desc()).limit(30).all())
    kr_titles = {k.kr.id: k.kr.title for k in v.krs}
    supporters = []
    for l in links_to(g.org.id, ("objective", o.id), "supports"):
        url = entity_url(l.source_type, l.source_id)
        if url:
            supporters.append({"type": l.source_type, "id": l.source_id, "title": entity_title(l.source_type, l.source_id), "url": url})
    # progress history from check-in snapshots on the objective itself
    snaps = [(c.created_at.date(), c.progress * 100) for c in reversed(checkins_for(g.org.id, "objective", o.id)) if c.progress is not None]
    chart = line_chart(snaps, 100) if len(snaps) > 1 else None
    from app.modules.goals.service import _dates

    start, end = _dates(o)
    infos = {}
    for kv in v.krs:
        k = kv.kr
        d = H.kr_data(k, end) if k.kr_type not in ("binary", "milestone") else None
        gap = FX.gap_to_target(k.target_value, d["supported"], d["direction"]) if d and d.get("supported") is not None and d.get("level") in ("stretch", "unrealistic") else 0.0
        cov = FX.coverage(gap, [{"effect": x.effect, "certainty": x.certainty} for x in k.factors])
        if d:
            actual = [(x, y) for x, y in d["series"].pairs()][-30:]
        else:
            actual = [(c.created_at.date(), c.value) for c in reversed(checkins_for(g.org.id, "key_result", k.id)) if c.value is not None]
        today = date.today()
        row = H.row(v, kv, today, start=start, end=end) if end else None
        pc = PATH.build(actual, start_date=start, start_value=k.start_value, target=k.target_value, end_date=end, today=today,
                        proj=d["projected"] if d else None, unit=k.unit_label) if k.kr_type in ("increase", "decrease") and end else None
        branches = _modules().query("kr.branches", k) if d else None
        infos[k.id] = {"data": d, "row": row, "path": pc, "branches": (branches[0] if branches else None),
                       "gap": gap, "coverage": cov, "needs_factors": gap > 0 or bool(k.factors),
                       "bar": H.range_bar(k.start_value, k.target_value, k.current_value, d["projected"] if d else None) if k.kr_type in ("increase", "decrease") else None}
    quality = coach.review(_objective_dict(o), [_kr_dict(kv.kr, infos[kv.kr.id]) for kv in v.krs], has_series=_has_series())
    events = GoalEvent.query.filter_by(org_id=g.org.id, objective_id=o.id).order_by(GoalEvent.created_at.desc(), GoalEvent.id.desc()).all()
    return render_template("goals/detail.html", o=o, v=v, feed=feed, events=events, lever_states=LEVER_STATES, kr_titles=kr_titles, supporters=supporters, infos=infos, quality=quality,
                           parent_view=views.get(o.parent_id), chart=chart, statuses=P.LIVE_STATUSES, kr_types=KR_TYPES, measures=MEASURES,
                           certainties=CERTAINTIES, factor_kinds=FACTOR_KINDS, commitments=COMMITMENTS, has_series=_has_series())


@bp.route("/<int:id>/edit", methods=["GET", "POST"])
@require("goals.edit")
def edit(id):
    o = F.get_scoped(Objective, id)
    SC.guard_edit(o)
    if request.method == "POST":
        before = o.unit_id
        err = _apply_objective(o)
        if not err and not SC.can_edit_unit(o.unit_id):
            err = "goals.errors.unit_scope"
        if err:
            db.session.rollback()
            flash(t(err), "error")
            o = F.get_scoped(Objective, id)
        else:
            log_activity("updated", "objective", o.id, o.title)
            db.session.commit()
            flash(t("goals.flash.saved"), "success")
            return redirect(url_for("goals.detail", id=o.id))
    return render_template("goals/form.html", o=o, mode="edit", **_form_data(exclude_id=o.id))


@bp.post("/<int:id>/delete")
@require("goals.delete")
def delete(id):
    o = F.get_scoped(Objective, id)
    SC.guard_edit(o)
    title = o.title
    for c in Objective.query.filter_by(org_id=g.org.id, parent_id=o.id).all():
        c.parent_id = None
    kr_ids = [k.id for k in o.key_results]
    CheckIn.query.filter(CheckIn.org_id == g.org.id, CheckIn.entity_type == "key_result", CheckIn.entity_id.in_(kr_ids or [0])).delete(synchronize_session=False)
    CheckIn.query.filter_by(org_id=g.org.id, entity_type="objective", entity_id=o.id).delete()
    for kid in kr_ids:
        remove_links_of(g.org.id, "key_result", kid)
    remove_links_of(g.org.id, "objective", o.id)
    db.session.delete(o)
    log_activity("deleted", "objective", id, title)
    db.session.commit()
    flash(t("goals.flash.deleted"), "success")
    return redirect(url_for("goals.index"))


@bp.post("/<int:id>/checkin")
@require("checkin")
def checkin(id):
    o = F.get_scoped(Objective, id)
    SC.guard_update(o)
    v = compute_objectives(g.org)[o.id]
    status = F.choice("status", P.LIVE_STATUSES)
    comment = F.s("comment")
    if not status and not comment:
        flash(t("goals.errors.checkin_empty"), "error")
        return redirect(url_for("goals.detail", id=o.id))
    add_checkin("objective", o.id, progress=v.progress, status=status, comment=comment)
    log_activity("checked_in", "objective", o.id, o.title)
    db.session.commit()
    flash(t("goals.flash.checkin"), "success")
    return redirect(url_for("goals.detail", id=o.id) + "#feed")


# -- key results ---------------------------------------------------------------------
@bp.get("/kr/<int:id>")
def kr_open(id):
    k = F.get_scoped(KeyResult, id)
    return redirect(url_for("goals.detail", id=k.objective_id) + f"#kr-{k.id}")


@bp.post("/<int:id>/kr")
@require("goals.edit")
def kr_add(id):
    o = F.get_scoped(Objective, id)
    SC.guard_edit(o)
    title = F.s("title", maxlen=255)
    if not title:
        flash(t("goals.errors.title_required"), "error")
        return redirect(url_for("goals.detail", id=o.id))
    kind = F.choice("kr_type", KR_TYPES, "increase")
    start, target = _kr_values(kind, F.num("start_value", 0.0), F.num("target_value", 100.0))
    owner = F.member_or_none(F.integer("owner_id")) or o.owner
    k = KeyResult(org_id=g.org.id, objective_id=o.id, title=title, kr_type=kind, metric_type=F.choice("metric_type", METRIC_TYPES, "number"),
                  unit_label=F.s("unit_label", maxlen=24), start_value=start, target_value=target, current_value=start,
                  weight=F.num("weight", 1.0) or 1.0, position=len(o.key_results),
                  owner_id=owner.id if owner else None)
    db.session.add(k)
    db.session.flush()
    current_app.extensions["modules"].hook("key_result.saved", k, form=request.form, index=None)
    log_activity("created", "key_result", k.id, k.title)
    db.session.commit()
    flash(t("goals.flash.kr_added"), "success")
    return redirect(url_for("goals.detail", id=o.id) + f"#kr-{k.id}")


@bp.post("/kr/<int:id>/checkin")
@require("checkin")
def kr_checkin(id):
    k = F.get_scoped(KeyResult, id)
    SC.guard_update(k.objective)
    value = F.num("value")
    if value is None:
        flash(t("goals.errors.value_required"), "error")
        return redirect(url_for("goals.detail", id=k.objective_id) + f"#kr-{k.id}")
    k.current_value = value
    add_checkin("key_result", k.id, value=value, progress=P.typed_kr_progress(k.kr_type, k.start_value, k.target_value, value), comment=F.s("comment"))
    log_activity("checked_in", "key_result", k.id, k.title)
    db.session.flush()
    # snapshot the parent objective's progress so its history line stays continuous
    v = compute_objectives(g.org)[k.objective_id]
    add_checkin("objective", k.objective_id, progress=v.progress, comment="")
    db.session.commit()
    flash(t("goals.flash.checkin"), "success")
    return redirect(url_for("goals.detail", id=k.objective_id) + f"#kr-{k.id}")


@bp.post("/kr/<int:id>/edit")
@require("goals.edit")
def kr_edit(id):
    k = F.get_scoped(KeyResult, id)
    SC.guard_edit(k.objective)
    k.title = F.s("title", k.title, 255)
    k.unit_label = F.s("unit_label", "", 24)
    k.metric_type = F.choice("metric_type", METRIC_TYPES, k.metric_type)
    k.kr_type = F.choice("kr_type", KR_TYPES, k.kr_type)
    k.measure = F.choice("measure", MEASURES, k.measure)
    old_target = k.target_value
    k.start_value, k.target_value = _kr_values(k.kr_type, F.num("start_value", k.start_value), F.num("target_value", k.target_value))
    if k.target_value != old_target:                     # a target never changes silently: the reason is part of the goal's history
        db.session.add(GoalEvent(org_id=g.org.id, objective_id=k.objective_id, key_result_id=k.id, kind="target", old_value=old_target, new_value=k.target_value,
                                 text=F.s("reason", "", 500), user_id=current_user.id))
    if k.basis and k.basis.get("value") != k.target_value:
        k.basis = None                                   # the target was changed by hand: it no longer follows a suggested level
    k.weight = F.num("weight", k.weight) or 1.0
    current_app.extensions["modules"].hook("key_result.saved", k, form=request.form, index=None)
    log_activity("updated", "key_result", k.id, k.title)
    db.session.commit()
    flash(t("goals.flash.saved"), "success")
    return redirect(url_for("goals.detail", id=k.objective_id) + f"#kr-{k.id}")


@bp.post("/kr/<int:id>/delete")
@require("goals.edit")
def kr_delete(id):
    k = F.get_scoped(KeyResult, id)
    SC.guard_edit(k.objective)
    oid = k.objective_id
    CheckIn.query.filter_by(org_id=g.org.id, entity_type="key_result", entity_id=k.id).delete()
    remove_links_of(g.org.id, "key_result", k.id)
    db.session.delete(k)
    db.session.commit()
    flash(t("goals.flash.deleted"), "success")
    return redirect(url_for("goals.detail", id=oid))


# -- indicators (KPI) -------------------------------------------------------------------
@bp.get("/indicators")
def indicators():
    items = compute_indicators(g.org)
    status = request.args.get("status")
    shown = [i for i in items if not status or i.status == status]
    counts = P.status_counts([i.status for i in items])
    return render_template("goals/indicators.html", items=shown, counts=counts, total=len(items), status=status,
                           from_chart=line_chart)


def _apply_indicator(i: Indicator) -> str | None:
    name = F.s("name", maxlen=200)
    target = F.num("target_value")
    if not name:
        return "goals.errors.title_required"
    if target is None:
        return "goals.errors.target_required"
    i.name, i.description = name, F.s("description")
    i.target_value, i.baseline_value = target, F.num("baseline_value")
    i.metric_type = F.choice("metric_type", METRIC_TYPES, "number")
    i.unit_label = F.s("unit_label", maxlen=24)
    i.direction = F.choice("direction", ("higher_better", "lower_better"), "higher_better")
    i.frequency = F.choice("frequency", FREQUENCIES, "monthly")
    i.perspective = F.choice("perspective", PERSPECTIVES)
    owner = F.member_or_none(F.integer("owner_id"))
    i.owner_id = owner.id if owner else None
    unit = db.session.get(OrgUnit, F.integer("unit_id") or 0)
    i.unit_id = unit.id if unit and unit.org_id == g.org.id else None
    return None


@bp.route("/indicators/new", methods=["GET", "POST"])
@require("indicators.edit")
def indicator_new():
    i = Indicator(org_id=g.org.id)
    if request.method == "POST":
        err = _apply_indicator(i)
        if err:
            flash(t(err), "error")
        else:
            db.session.add(i)
            db.session.flush()
            log_activity("created", "indicator", i.id, i.name)
            db.session.commit()
            flash(t("goals.flash.created"), "success")
            return redirect(url_for("goals.indicator_detail", id=i.id))
    return render_template("goals/indicator_form.html", i=i, mode="new", **_form_data())


@bp.get("/indicators/<int:id>")
def indicator_detail(id):
    ind = F.get_scoped(Indicator, id)
    view = next(v for v in compute_indicators(g.org) if v.ind.id == ind.id)
    chart = line_chart(view.series, ind.target_value)
    return render_template("goals/indicator_detail.html", i=ind, v=view, chart=chart, rows=list(reversed(view.series)),
                           notes={x.period_date: x.note for x in ind.values})


@bp.route("/indicators/<int:id>/edit", methods=["GET", "POST"])
@require("indicators.edit")
def indicator_edit(id):
    i = F.get_scoped(Indicator, id)
    if request.method == "POST":
        err = _apply_indicator(i)
        if err:
            flash(t(err), "error")
        else:
            log_activity("updated", "indicator", i.id, i.name)
            db.session.commit()
            flash(t("goals.flash.saved"), "success")
            return redirect(url_for("goals.indicator_detail", id=i.id))
    return render_template("goals/indicator_form.html", i=i, mode="edit", **_form_data())


@bp.post("/indicators/<int:id>/value")
@require("indicators.edit")
def indicator_value(id):
    i = F.get_scoped(Indicator, id)
    value, period = F.num("value"), F.when("period_date", date.today().replace(day=1))
    if value is None:
        flash(t("goals.errors.value_required"), "error")
        return redirect(url_for("goals.indicator_detail", id=i.id))
    row = IndicatorValue.query.filter_by(indicator_id=i.id, period_date=period).first()
    if row:
        row.value, row.note = value, F.s("note", maxlen=255)
    else:
        db.session.add(IndicatorValue(indicator_id=i.id, period_date=period, value=value, note=F.s("note", maxlen=255)))
    log_activity("checked_in", "indicator", i.id, i.name)
    db.session.commit()
    flash(t("goals.flash.value_saved"), "success")
    return redirect(url_for("goals.indicator_detail", id=i.id))


@bp.post("/indicators/<int:id>/delete")
@require("indicators.delete")
def indicator_delete(id):
    i = F.get_scoped(Indicator, id)
    remove_links_of(g.org.id, "indicator", i.id)
    log_activity("deleted", "indicator", i.id, i.name)
    db.session.delete(i)
    db.session.commit()
    flash(t("goals.flash.deleted"), "success")
    return redirect(url_for("goals.indicators"))


# -- goal quality: rules first, then (optionally) a model ----------------------------------------------------------
def _objective_dict(o: Objective) -> dict:
    return {"title": o.title, "rationale": o.rationale, "has_horizon": bool(o.end_date or o.cycle_id), "has_owner": bool(o.owner_id), "commitment": o.commitment}


def _kr_dict(k: KeyResult, info: dict | None = None) -> dict:
    d = (info or {}).get("data")
    return {"title": k.title, "type": k.kr_type, "start": k.start_value, "target": k.target_value, "unit": k.unit_label, "measured": bool(d),
            "verdict": (d or {}).get("level"), "factors": len(k.factors)}


def _end_from_form():
    end = F.when("end_date")
    if end:
        return end
    cyc = db.session.get(Cycle, F.integer("cycle_id") or 0)
    return cyc.end_date if cyc and cyc.org_id == g.org.id else None


def _review_from_form() -> tuple[dict, list[dict], list[dict]]:
    """The goal as typed in the form (not saved yet): objective dict, key-result dicts, and the inputs the model would see."""
    f = request.form
    obj = {"title": f.get("title", "").strip(), "rationale": f.get("rationale", "").strip(), "commitment": f.get("commitment", "committed"),
           "has_horizon": bool(f.get("end_date") or f.get("cycle_id")), "has_owner": bool(f.get("owner_id"))}
    end = _end_from_form()
    krs = []
    titles, kinds, starts, targets = f.getlist("kr_title"), f.getlist("kr_type"), f.getlist("kr_start"), f.getlist("kr_target")
    units, sers = f.getlist("kr_unit"), f.getlist("kr_series")
    for i, title in enumerate(titles):
        if not title.strip():
            continue
        kind = kinds[i] if i < len(kinds) and kinds[i] in KR_TYPES else "increase"
        start, target = _kr_values(kind, _numf(starts[i] if i < len(starts) else ""), _numf(targets[i] if i < len(targets) else ""))
        sid = int(sers[i]) if i < len(sers) and (sers[i] or "").isdigit() else None
        verdict = None
        if sid and target is not None and end and start is not None and kind in METRIC_TYPES:
            r = _modules().query("series.check", sid, g.org.id, start=start, target=target, end_date=end)
            verdict = r[0]["level"] if r else None
        krs.append({"row": i, "title": title.strip(), "type": kind, "start": start, "target": target, "unit": (units[i] if i < len(units) else "").strip(),
                    "measured": bool(sid), "verdict": verdict, "factors": 0})
    return obj, krs, [i for i in range(len(krs))]


@bp.post("/review")
def review():
    """HTML fragment: the quality checks of the goal as it is being written. `ai=1` also asks the model to coach it."""
    obj, krs, _ = _review_from_form()
    res = coach.review(obj, krs, has_series=_has_series())
    advice = None
    if request.form.get("ai") == "1":
        inputs = {"objective": obj, "krs": krs, "findings": [{"code": c["code"], "target": c["target"], "level": c["level"]} for c in res["open"]],
                  "facts": _facts_of(obj, krs)}
        advice = ai.run("review_goal", inputs)
    return render_template("goals/_review.html", res=res, advice=advice, objective=obj, krs=krs)


def _facts_of(obj, krs) -> list[float]:
    """Numbers a rewrite may quote: those already in the goal (its numeric fields and any figure inside its text)."""
    import re

    out = []
    for k in krs:
        out += [x for x in (k.get("start"), k.get("target")) if x is not None]
    for text in [obj.get("title", ""), obj.get("rationale", ""), *[k.get("title", "") for k in krs]]:
        out += [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", text)]
    return out


def _ai_badge() -> dict:
    hub = ai.get_hub()
    st = [s for s in hub.status() if s["available"] and s["name"] != "offline"]
    return {"models": [s["name"] for s in st], "consent": ai.org_consent(g.org), "external_only": bool(st) and all(not s["local"] for s in st)}


@bp.post("/draft")
@require("goals.edit")
def draft():
    """HTML fragment: well-formed goals proposed from ONE typed line, so the manager picks and edits instead of writing from nothing."""
    intent = F.s("intent", maxlen=200)
    if len(intent) < 3:
        return render_template("goals/_draft.html", options=[], empty="short", advice=None, intent=intent)
    res = ai.run("draft_goal", {"intent": intent})
    return render_template("goals/_draft.html", options=res.data["options"], empty=None, advice=res, intent=intent)


@bp.post("/suggest-krs")
@require("goals.edit")
def suggest_krs():
    """HTML fragment: key results proposed from the organization's own uploaded series, each with three defensible target levels."""
    title, rationale = F.s("title", maxlen=255), F.s("rationale", maxlen=600)
    cat = _modules().query("series.catalog", g.org.id)
    series = cat[0] if cat else []
    if not series or not title:
        return render_template("goals/_suggest.html", items=[], matched=False, empty=("title" if series else "series"), advice=None)
    res = ai.run("suggest_krs", {"objective": {"title": title, "rationale": rationale}, "series": series})
    end = _end_from_form()
    by_id = {s["id"]: s for s in series}
    items = []
    for k in res.data["krs"]:
        s = by_id.get(k["series_id"])
        if not s:
            continue
        lv = (_modules().query("series.levels", s["id"], g.org.id, end_date=end) or [None])[0] if end else None
        items.append({**k, "series": s, "levels": lv})
    return render_template("goals/_suggest.html", items=items, matched=res.data["matched"], empty=None, advice=res, ai_state=_ai_badge())


# -- outside factors, justification, confidence -------------------------------------------------------------------------
def _kr(id, level: str = "edit") -> KeyResult:
    k = F.get_scoped(KeyResult, id)
    (SC.guard_update if level == "update" else SC.guard_edit)(k.objective)
    return k


@bp.post("/kr/<int:id>/factor")
@require("goals.edit")
def factor_add(id):
    k = _kr(id)
    title, effect = F.s("title", maxlen=200), F.num("effect")
    if not title or effect is None:
        flash(t("goals.errors.factor_incomplete"), "error")
        return redirect(url_for("goals.detail", id=k.objective_id) + f"#kr-{k.id}")
    owner = F.member_or_none(F.integer("owner_id"))
    db.session.add(KRFactor(org_id=g.org.id, key_result_id=k.id, title=title, kind=F.choice("kind", FACTOR_KINDS, "other"), effect=effect,
                            certainty=F.choice("certainty", CERTAINTIES, "probable"), evidence=F.s("evidence", maxlen=500), owner_id=owner.id if owner else None))
    log_activity("updated", "key_result", k.id, k.title)
    db.session.commit()
    flash(t("goals.flash.factor_added"), "success")
    return redirect(url_for("goals.detail", id=k.objective_id) + f"#kr-{k.id}")


@bp.post("/factor/<int:id>/delete")
@require("goals.edit")
def factor_delete(id):
    f = F.get_scoped(KRFactor, id)
    k = f.key_result
    SC.guard_edit(k.objective)
    db.session.delete(f)
    db.session.commit()
    flash(t("goals.flash.deleted"), "success")
    return redirect(url_for("goals.detail", id=k.objective_id) + f"#kr-{k.id}")


@bp.post("/factor/<int:id>/update")
@require("goals.edit")
def factor_update(id):
    f = F.get_scoped(KRFactor, id)
    SC.guard_edit(f.key_result.objective)
    f.status = F.choice("status", LEVER_STATES, f.status)
    f.actual = F.num("actual", None)
    f.due = F.when("due", None)
    log_activity("updated", "key_result", f.key_result_id, f.title)
    db.session.commit()
    flash(t("goals.flash.saved"), "success")
    return redirect(url_for("goals.detail", id=f.key_result.objective_id) + f"#kr-{f.key_result_id}")


@bp.post("/<int:id>/decision")
@require("goals.edit")
def decision_add(id):
    o = F.get_scoped(Objective, id)
    SC.guard_edit(o)
    text = F.s("text", "", 500)
    if text:
        db.session.add(GoalEvent(org_id=g.org.id, objective_id=o.id, kind="decision", text=text, user_id=current_user.id))
        log_activity("updated", "objective", o.id, o.title)
        db.session.commit()
        flash(t("goals.flash.saved"), "success")
    return redirect(url_for("goals.detail", id=o.id) + "#events")


@bp.post("/kr/<int:id>/justification")
@require("goals.edit")
def justification_save(id):
    k = _kr(id)
    k.justification = F.s("justification", maxlen=2000)
    db.session.commit()
    flash(t("goals.flash.saved"), "success")
    return redirect(url_for("goals.detail", id=k.objective_id) + f"#kr-{k.id}")


@bp.post("/kr/<int:id>/justification/draft")
@require("goals.edit")
def justification_draft(id):
    """JSON {text, provider, ...}: a draft of the justification from the numbers and factors recorded (never saved by itself)."""
    from app.modules.goals.service import _dates

    k = _kr(id)
    _, end = _dates(k.objective)
    d = H.kr_data(k, end) if k.kr_type in METRIC_TYPES else None
    gap = FX.gap_to_target(k.target_value, d["supported"], d["direction"]) if d and d.get("supported") is not None else 0.0
    fl = [{"title": x.title, "kind": x.kind, "effect": x.effect, "certainty": x.certainty, "evidence": x.evidence} for x in k.factors]
    cov = FX.coverage(gap, fl)
    facts = [k.start_value, k.target_value, gap, d["supported"] if d else None, *[x["effect"] for x in fl], cov["confirmed"], cov["total"], cov["probable"], cov["hoped"], abs(cov["headwind"])]
    inputs = {"goal": k.objective.title, "kr": k.title, "unit": k.unit_label, "level": d["level"] if d else None, "target": k.target_value, "supported": d["supported"] if d else k.target_value,
              "gap": gap, "factors": fl, "coverage": {x: cov[x] for x in ("status", "confirmed", "probable", "hoped", "total")}, "facts": [x for x in facts if x is not None]}
    res = ai.run("draft_justification", inputs)
    return jsonify(text=res.data["text"], provider=res.provider, label=t("ai.provider." + res.provider), model=res.model, rules=(res.provider == "offline"), fell_back=res.fell_back)


@bp.post("/kr/<int:id>/confidence")
@require("checkin")
def confidence_save(id):
    k = _kr(id, "update")
    c = F.integer("confidence")
    k.confidence = c if c and 1 <= c <= 10 else None
    db.session.commit()
    return redirect(url_for("goals.detail", id=k.objective_id) + f"#kr-{k.id}")


# -- goal health ------------------------------------------------------------------------------------------------------------
@bp.get("/health")
def health():
    views = compute_objectives(g.org)
    cycles = Cycle.query.filter_by(org_id=g.org.id).order_by(Cycle.start_date.desc()).all()
    cur = current_cycle(g.org)
    arg = request.args.get("cycle")
    cycle_id = None if arg == "all" else (int(arg) if (arg or "").isdigit() else (cur.id if cur else None))
    data = H.build(views, g.org, cycle_id=cycle_id)
    order = ("off_track", "at_risk", "on_track", "completed", "not_started")
    buckets = {st: [r for grp in data["groups"] for r in grp["rows"] if r["status"] == st] for st in order}
    return render_template("goals/health.html", data=data, buckets={k: v for k, v in buckets.items() if v}, cycles=cycles, cycle_id=cycle_id, ai_state=_ai_badge(), stale_days=H.STALE_DAYS)


@bp.post("/health/brief")
def health_brief():
    """HTML fragment: the model's (or the rules') brief on what deserves attention."""
    views = compute_objectives(g.org)
    arg = request.form.get("cycle")
    cycle_id = int(arg) if (arg or "").isdigit() else None
    data = H.build(views, g.org, cycle_id=cycle_id)
    rows, facts = [], []
    for grp in data["groups"]:
        for r in grp["rows"]:
            pr = r["projected"]
            rows.append({"title": r["kr"].title, "status": r["status"] if r["source"] != "manual" or r["data"] else r["status"], "progress": round(r["progress"] * 100),
                         "projected": {k: round(pr[k], 2) for k in ("low", "mid", "high")} if pr else None, "target": r["kr"].target_value, "unit": r["kr"].unit_label,
                         "data_age_days": r["data"]["age_days"] if r["data"] else None, "confidence": r["kr"].confidence})
            facts += [round(r["progress"] * 100), r["kr"].target_value, r["kr"].confidence or 0, (r["data"] or {}).get("age_days") or 0] + (list(pr.values()) if pr else [])
    inputs = {"counts": {k: v for k, v in data["counts"].items() if v}, "rows": rows, "facts": [*[float(x) for x in facts if x is not None], *map(float, data["counts"].values()), float(data["total"])]}
    res = ai.run("summarize_health", inputs)
    return render_template("goals/_brief.html", brief=res.data, res=res, ai_state=_ai_badge())
