"""The application shell: organization overview, search, activity and settings."""
from __future__ import annotations

import secrets

from flask_login import current_user
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from app.core import forms as F
from app.core.i18n import t
from app.core.models import ROLES, Activity, Cycle, Invite, Membership, OrgUnit, User
from app.core.permissions import can, require
from app.core.services import current_cycle, entity_url, units
from app.extensions import db

bp = Blueprint("shell", __name__, url_prefix="/app/<org_slug>", template_folder="templates")


@bp.get("/")
def overview():
    registry = current_app.extensions["modules"]
    widgets = []
    for w in registry.widgets():
        try:
            widgets.append({"w": w, "data": w.loader(g.org)})
        except Exception:  # one broken widget must never take the page down
            current_app.logger.exception("widget %s failed", w.id)
    feed = Activity.query.filter_by(org_id=g.org.id).order_by(Activity.created_at.desc(), Activity.id.desc()).limit(12).all()
    for a in feed:
        a.url = entity_url(a.entity_type, a.entity_id) if a.verb != "deleted" else None
    return render_template("shell/overview.html", widgets=widgets, feed=feed, cycle=current_cycle(g.org))


@bp.get("/search")
def search():
    q = (request.args.get("q") or "").strip()
    hits = current_app.extensions["modules"].search(g.org, q, 8) if len(q) >= 2 else []
    groups: dict[str, list] = {}
    for h in hits:
        groups.setdefault(h.type, []).append(h)
    return render_template("shell/search.html", q=q, groups=groups, total=len(hits))


# -- settings -------------------------------------------------------------------------------
@bp.get("/settings")
@require("settings.view")
def settings():
    return redirect(url_for("shell.settings_general"))


@bp.route("/settings/general", methods=["GET", "POST"])
@require("settings.view")
def settings_general():
    """Organization profile (name, logo, sector, vision…) and the rules that decide every goal's status."""
    from app.core import profile as P

    if request.method == "POST":
        if not can("settings.manage"):
            abort(403)
        name = F.s("name", maxlen=160)
        if name:
            g.org.name = name
        on, risk = F.num("on_track"), F.num("at_risk")
        cadence = F.integer("cadence")
        if "on_track" in request.form:  # the rules card is present only on the full form
            settings = dict(g.org.settings or {})
            if on is not None and risk is not None and 0 < on < risk <= 100:
                settings["status_thresholds"] = {"on_track": on, "at_risk": risk}
            else:
                flash(t("settings.errors.thresholds"), "error")
            if cadence and 1 <= cadence <= 90:
                settings["checkin_cadence_days"] = cadence
            g.org.settings = settings
        fiscal = F.integer("fiscal_start", 1)
        P.save_profile(
            g.org,
            sector=F.choice("sector", P.SECTORS, ""),
            size=F.choice("size", P.SIZES, ""),
            currency=F.choice("currency", P.CURRENCIES, "DZD"),
            fiscal_start=fiscal if fiscal and 1 <= fiscal <= 12 else 1,
            vision=F.s("vision", maxlen=600),
            mission=F.s("mission", maxlen=600),
            values=F.s("values", maxlen=400),
        )
        upload = request.files.get("logo")
        if request.form.get("remove_logo"):
            P.clear_logo(g.org)
        elif upload and upload.filename:
            data = upload.read(P.LOGO_MAX_BYTES + 1)
            if P.store_logo(g.org, data) is None:
                flash(t("profile.errors.logo"), "error")
        db.session.commit()
        flash(t("settings.flash.saved"), "success")
        # "then" is a fixed keyword, never a URL (no open redirect)
        return redirect(url_for("shell.overview") if request.form.get("then") == "overview" else url_for("shell.settings_general"))
    from app.core.services import cadence_days, thresholds

    return render_template("shell/settings_general.html", th=thresholds(g.org), cadence=cadence_days(g.org), prof=P.profile(g.org),
                           sectors=P.SECTORS, sizes=P.SIZES, currencies=P.CURRENCIES, welcome=bool(request.args.get("welcome")))


@bp.get("/logo")
def org_logo():
    """Serve the organization's own logo (only to its members; never guessable by file name)."""
    from flask import send_file

    from app.core import profile as P

    path = P.logo_path(g.org)
    if path is None:
        abort(404)
    resp = send_file(path, mimetype=P.LOGO_TYPES[path.suffix.lstrip(".")], max_age=3600)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "private, max-age=3600"
    resp.headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'"
    return resp


@bp.post("/settings/direction-draft")
@require("settings.manage")
def direction_draft():
    """HTML fragment: vision / mission / values wording proposed from the sector (and one optional sentence). Nothing is saved."""
    from app import ai
    from app.core import i18n
    from app.core import profile as P

    sector, size = F.choice("sector", P.SECTORS, ""), F.choice("size", P.SIZES, "")
    inputs = {"sector": sector, "size": size, "about": F.s("about", maxlen=300),
              "sector_label": i18n.t(f"profile.sectors.{sector}") if sector else "", "size_label": i18n.t(f"profile.sizes.{size}") if size else ""}
    res = ai.run("draft_direction", inputs)
    return render_template("shell/_direction_draft.html", d=res.data, res=res)


@bp.route("/settings/ai", methods=["GET", "POST"])
@require("settings.view")
def settings_ai():
    """Which model reads files and explains goals, the consent switch for cloud models, and the audit list of every call."""
    from app import ai
    from app.ai.models import AICall

    if request.method == "POST":
        if not can("settings.manage"):
            abort(403)
        settings = dict(g.org.settings or {})
        settings["ai_consent"] = "ai_consent" in request.form
        g.org.settings = settings
        db.session.commit()
        flash(t("ai.settings.saved"), "success")
        return redirect(request.form.get("next") or url_for("shell.settings_ai"))
    hub = ai.get_hub()
    calls = AICall.query.filter_by(org_id=g.org.id).order_by(AICall.id.desc()).limit(30).all()
    return render_template("shell/settings_ai.html", status=hub.status(), consent=ai.org_consent(g.org), calls=calls, rows=hub.privacy["sample_rows"],
                           cloud=hub.external_available())


# -- welcome (first sign-in): the model's consent, then the logo, then the profile page for the vision ------------------
@bp.route("/welcome", methods=["GET", "POST"])
@require("settings.manage")
def welcome():
    """Step 1: what the model may read, and the choice. Cloud model -> a real choice; local model or none -> nothing leaves the machine."""
    from app import ai
    from app.core import welcome as W

    hub = ai.get_hub()
    status = hub.status()
    cloud = hub.external_available()
    local = any(s["available"] and s["local"] for s in status)
    if request.method == "POST":
        if cloud:
            settings = dict(g.org.settings or {})
            settings["ai_consent"] = request.form.get("choice") == "allow"
            g.org.settings = settings
        W.mark(g.org, ai_asked=True)
        db.session.commit()
        return redirect(url_for("shell.welcome_logo"))
    mode = "cloud" if cloud else "local" if local else "none"
    # one tile per model the app can talk to, with the maker's mark; the ones that are set up light up
    marks = {"anthropic": ("Claude", "claude.svg"), "xai": ("Grok", "grok.svg"), "groq": ("Groq", "groq.svg"), "openai_compat": ("Ollama", "ollama.svg")}
    models = [{"key": s["name"], "name": marks[s["name"]][0], "logo": marks[s["name"]][1], "local": s["local"], "on": s["available"]}
              for s in sorted(status, key=lambda s: (not s["local"], s["name"])) if s["name"] in marks]
    return render_template("shell/welcome_model.html", mode=mode, rows=hub.privacy["sample_rows"], models=models, consent=ai.org_consent(g.org))


@bp.route("/welcome/logo", methods=["GET", "POST"])
@require("settings.manage")
def welcome_logo():
    """Step 2: the organization's logo (live preview of the header it will sit in). Skippable."""
    from app.core import profile as P
    from app.core import welcome as W

    if request.method == "POST":
        upload = request.files.get("logo")
        if upload and upload.filename and not request.form.get("skip"):
            if P.store_logo(g.org, upload.read(P.LOGO_MAX_BYTES + 1)) is None:
                flash(t("profile.errors.logo"), "error")
                return redirect(url_for("shell.welcome_logo"))
        W.mark(g.org, logo_done=True)
        db.session.commit()
        return redirect(url_for("shell.welcome_direction"))
    return render_template("shell/welcome_logo.html", max_kb=P.LOGO_MAX_BYTES // 1024)


@bp.route("/welcome/direction", methods=["GET", "POST"])
@require("settings.manage")
def welcome_direction():
    """Step 3: sector, size, vision, mission, values — the model proposes wording (same fragment as the profile page), then the overview."""
    from app.core import profile as P
    from app.core import welcome as W

    if request.method == "POST":
        if not request.form.get("skip"):
            P.save_profile(g.org, sector=F.choice("sector", P.SECTORS, ""), size=F.choice("size", P.SIZES, ""),
                           vision=F.s("vision", maxlen=600), mission=F.s("mission", maxlen=600), values=F.s("values", maxlen=400))
        W.mark(g.org, logo_done=True, welcomed=True)
        db.session.commit()
        return redirect(url_for("shell.overview"))
    return render_template("shell/welcome_direction.html", prof=P.profile(g.org), sectors=P.SECTORS, sizes=P.SIZES)


@bp.post("/welcome/skip")
@require("settings.manage")
def welcome_skip():
    from app.core import welcome as W

    W.mark(g.org, ai_asked=True, welcomed=True)
    db.session.commit()
    return redirect(url_for("shell.overview"))


@bp.route("/settings/members", methods=["GET", "POST"])
@require("settings.view")
def settings_members():
    if request.method == "POST":
        if not can("members.manage"):
            abort(403)
        email, name = F.s("email").lower(), F.s("name", maxlen=120)
        role = F.choice("role", ("viewer", "member", "admin"), "member")
        if not email or "@" not in email or not name:
            flash(t("auth.errors.required"), "error")
        else:
            user = User.query.filter_by(email=email).first()
            temp = None
            if user is None:
                temp = secrets.token_urlsafe(9)
                user = User(email=email, name=name, lang=g.lang)
                user.set_password(temp)
                db.session.add(user)
                db.session.flush()
            if Membership.query.filter_by(org_id=g.org.id, user_id=user.id).first():
                flash(t("settings.members.exists"), "error")
            else:
                root = OrgUnit.query.filter_by(org_id=g.org.id, kind="company").first()
                chosen = db.session.get(OrgUnit, F.integer("unit_id") or 0)
                unit_id = chosen.id if chosen and chosen.org_id == g.org.id else (root.id if root else None)
                db.session.add(Membership(org_id=g.org.id, user_id=user.id, role=role, unit_id=unit_id))
                db.session.commit()
                flash(t("settings.members.added_temp", password=temp) if temp else t("settings.members.added"), "success")
        return redirect(url_for("shell.settings_members"))
    rows = Membership.query.filter_by(org_id=g.org.id).order_by(Membership.id).all()
    from datetime import datetime

    invites = (Invite.query.filter(Invite.org_id == g.org.id, Invite.used_at.is_(None), Invite.expires_at > datetime.utcnow()).order_by(Invite.id.desc()).all()
               if can("members.manage") else [])
    unit_f = request.args.get("unit", type=int)
    all_rows = rows
    if unit_f:
        rows = [m for m in rows if m.unit_id == unit_f]
    heads = {u.head_id: u for u in units(g.org) if u.head_id}
    counts: dict = {}
    for m in all_rows:
        counts[m.unit_id] = counts.get(m.unit_id, 0) + 1
    return render_template("shell/settings_members.html", rows=rows, all_count=len(all_rows), roles=ROLES, units=units(g.org), invites=invites, unit_f=unit_f, heads=heads, counts=counts)


@bp.post("/settings/members/invite")
@require("members.manage")
def invite_create():
    from datetime import datetime, timedelta

    db.session.add(Invite(org_id=g.org.id, token=secrets.token_urlsafe(24), role=F.choice("role", ("viewer", "member", "admin"), "member"),
                          created_by=current_user.id, expires_at=datetime.utcnow() + timedelta(days=7)))
    db.session.commit()
    flash(t("settings.members.invite_made"), "success")
    return redirect(url_for("shell.settings_members"))


@bp.get("/settings/members/invite/<int:iid>/qr.svg")
@require("members.manage")
def invite_qr(iid):
    """The invitation link as a QR code (SVG), so a phone can join by scanning it. Only people who may manage members can fetch it."""
    import io

    import segno
    from flask import Response

    inv = F.get_scoped(Invite, iid)
    link = url_for("auth.join", token=inv.token, _external=True)
    buf = io.BytesIO()
    segno.make(link, error="m").save(buf, kind="svg", scale=8, border=2, dark="#162447", xmldecl=False, svgns=True, title=t("settings.members.qr_title"))
    headers = {"Cache-Control": "private, no-store"}
    if request.args.get("dl"):
        headers["Content-Disposition"] = 'attachment; filename="invite-qr.svg"'
    return Response(buf.getvalue(), mimetype="image/svg+xml", headers=headers)


@bp.post("/settings/members/invite/<int:iid>/revoke")
@require("members.manage")
def invite_revoke(iid):
    inv = F.get_scoped(Invite, iid)
    db.session.delete(inv)
    db.session.commit()
    return redirect(url_for("shell.settings_members"))


@bp.post("/settings/members/<int:mid>")
@require("members.manage")
def member_update(mid):
    m = F.get_scoped(Membership, mid)
    if m.role == "owner":
        flash(t("settings.members.owner_locked"), "error")
    else:
        if request.form.get("action") == "remove":
            OrgUnit.query.filter_by(org_id=g.org.id, head_id=m.user_id).update({"head_id": None})
            db.session.delete(m)
        else:
            m.role = F.choice("role", ("viewer", "member", "admin"), m.role)
            unit = db.session.get(OrgUnit, F.integer("unit_id") or 0)
            if unit and unit.org_id == g.org.id and unit.id != m.unit_id:
                OrgUnit.query.filter_by(org_id=g.org.id, head_id=m.user_id).update({"head_id": None})   # a head who moves stops heading the old department
                m.unit_id = unit.id
            m.title = F.s("title", m.title or "", 120)
        db.session.commit()
        flash(t("settings.flash.saved"), "success")
    return redirect(url_for("shell.settings_members"))


@bp.route("/settings/units", methods=["GET", "POST"])
@require("settings.view")
def settings_units():
    if request.method == "POST":
        if not can("settings.manage"):
            abort(403)
        name = F.s("name", maxlen=160)
        parent = db.session.get(OrgUnit, F.integer("parent_id") or 0)
        if name:
            db.session.add(OrgUnit(org_id=g.org.id, name=name, kind=F.choice("kind", ("department", "team"), "department"),
                                   parent_id=parent.id if parent and parent.org_id == g.org.id else None))
            db.session.commit()
            flash(t("settings.flash.saved"), "success")
        return redirect(url_for("shell.settings_units"))
    all_units = units(g.org)
    by_parent: dict = {}
    for u in all_units:
        by_parent.setdefault(u.parent_id, []).append(u)
    members = Membership.query.filter_by(org_id=g.org.id).all()
    count: dict = {}
    for m in members:
        count[m.unit_id] = count.get(m.unit_id, 0) + 1
    return render_template("shell/settings_units.html", by_parent=by_parent, all_units=all_units, members=members, count=count)


@bp.post("/settings/units/<int:uid>/head")
@require("settings.manage")
def unit_head(uid):
    """Name the head of a department. A head belongs to the department they head; none = the seat is empty."""
    u = F.get_scoped(OrgUnit, uid)
    m = Membership.query.filter_by(org_id=g.org.id, user_id=F.integer("head_id") or 0).first()
    if m:
        OrgUnit.query.filter(OrgUnit.org_id == g.org.id, OrgUnit.head_id == m.user_id, OrgUnit.id != u.id).update({"head_id": None})
        m.unit_id = u.id
    u.head_id = m.user_id if m else None
    db.session.commit()
    flash(t("settings.flash.saved"), "success")
    return redirect(url_for("shell.settings_units") + f"#u{u.id}")


@bp.post("/settings/units/<int:uid>/delete")
@require("settings.manage")
def unit_delete(uid):
    u = F.get_scoped(OrgUnit, uid)
    if u.kind == "company" or OrgUnit.query.filter_by(org_id=g.org.id, parent_id=u.id).count():
        flash(t("settings.units.cannot_delete"), "error")
    else:
        Membership.query.filter_by(unit_id=u.id).update({"unit_id": None})
        db.session.delete(u)
        db.session.commit()
    return redirect(url_for("shell.settings_units"))


@bp.route("/settings/cycles", methods=["GET", "POST"])
@require("settings.view")
def settings_cycles():
    if request.method == "POST":
        if not can("settings.manage"):
            abort(403)
        name, s, e = F.s("name", maxlen=80), F.when("start_date"), F.when("end_date")
        if not name or not s or not e or e <= s:
            flash(t("settings.errors.cycle"), "error")
        else:
            parent = db.session.get(Cycle, F.integer("parent_id") or 0)
            db.session.add(Cycle(org_id=g.org.id, name=name, kind=F.choice("kind", ("year", "quarter", "custom"), "custom"), start_date=s, end_date=e,
                                 parent_id=parent.id if parent and parent.org_id == g.org.id else None))
            db.session.commit()
            flash(t("settings.flash.saved"), "success")
        return redirect(url_for("shell.settings_cycles"))
    rows = Cycle.query.filter_by(org_id=g.org.id).order_by(Cycle.start_date.desc(), Cycle.end_date).all()
    return render_template("shell/settings_cycles.html", rows=rows)


@bp.post("/settings/cycles/<int:cid>/status")
@require("settings.manage")
def cycle_status(cid):
    c = F.get_scoped(Cycle, cid)
    c.status = F.choice("status", ("planned", "active", "closed"), c.status)
    db.session.commit()
    return redirect(url_for("shell.settings_cycles"))
