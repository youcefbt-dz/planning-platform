"""Sign-in, registration (creates an organization), sign-out."""
from __future__ import annotations

import re
import secrets
from datetime import date

from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user

from app.core.i18n import t
from app.core.models import Cycle, Membership, Organization, OrgUnit, User
from app.extensions import db

bp = Blueprint("auth", __name__, template_folder="templates")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def safe_next(target: str | None) -> str | None:
    return target if target and target.startswith("/") and not target.startswith("//") else None


def home_for(user: User) -> str:
    m = Membership.query.filter_by(user_id=user.id).order_by(Membership.id).first()
    if m is None:
        return url_for("site.landing")
    from app.core import welcome

    step = welcome.step_endpoint(m.org, m.role)  # first sign-in of a new organization: the welcome (model consent, logo) before the overview
    return url_for(step or "shell.overview", org_slug=m.org.slug)


def unique_slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "org"
    slug = base
    while Organization.query.filter_by(slug=slug).first() or slug in {"demo", "static", "app"}:
        slug = f"{base}-{secrets.token_hex(2)}"
    return slug


def create_organization(name: str, owner: User) -> Organization:
    """A fresh workspace: company unit + this year's cycle with its current quarter."""
    org = Organization(name=name, slug=unique_slug(name), settings={})
    db.session.add(org)
    db.session.flush()
    root = OrgUnit(org_id=org.id, name=name, kind="company")
    db.session.add(root)
    db.session.flush()
    db.session.add(Membership(org_id=org.id, user_id=owner.id, role="owner", unit_id=root.id))
    y = date.today().year
    year = Cycle(org_id=org.id, name=str(y), kind="year", start_date=date(y, 1, 1), end_date=date(y, 12, 31), status="active")
    db.session.add(year)
    db.session.flush()
    q = (date.today().month - 1) // 3
    qs = date(y, q * 3 + 1, 1)
    qe = date(y + (q == 3), (q * 3 + 4 - 1) % 12 + 1, 1)
    from datetime import timedelta

    db.session.add(Cycle(org_id=org.id, parent_id=year.id, name=f"Q{q + 1} {y}", kind="quarter", start_date=qs, end_date=qe - timedelta(days=1), status="active"))
    return org


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(request.form.get("password") or ""):
            login_user(user, remember=True)
            return redirect(safe_next(request.args.get("next")) or home_for(user))
        flash(t("auth.errors.credentials"), "error")
    return render_template("auth/login.html")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        f = request.form
        name, email, pw, org_name = (f.get("name") or "").strip(), (f.get("email") or "").strip().lower(), f.get("password") or "", (f.get("org_name") or "").strip()
        error = None
        if not name or not org_name:
            error = "auth.errors.required"
        elif not EMAIL.match(email):
            error = "auth.errors.email"
        elif len(pw) < 8:
            error = "auth.errors.password_short"
        elif User.query.filter_by(email=email).first():
            error = "auth.errors.email_taken"
        if error:
            flash(t(error), "error")
            return render_template("auth/register.html", form=f), 400
        user = User(name=name, email=email, lang=g.lang)
        user.set_password(pw)
        db.session.add(user)
        db.session.flush()
        org = create_organization(org_name, user)
        db.session.commit()
        login_user(user, remember=True)
        return redirect(url_for("shell.welcome", org_slug=org.slug))
    return render_template("auth/register.html", form={})


@bp.post("/logout")
def logout():
    logout_user()
    return redirect(url_for("site.landing"))


@bp.get("/app")
def app_home():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    return redirect(home_for(current_user))


@bp.route("/join/<token>", methods=["GET", "POST"])
def join(token):
    """Accept an invitation: a signed-in person joins directly, a new person creates an account first."""
    from datetime import datetime

    from app.core.models import Invite

    inv = Invite.query.filter_by(token=token).first()
    if inv is None or not inv.valid():
        return render_template("auth/join.html", inv=None), 404
    org = inv.org
    if request.method == "POST":
        user = current_user if current_user.is_authenticated else None
        if user is None:
            f = request.form
            name, email, pw = (f.get("name") or "").strip(), (f.get("email") or "").strip().lower(), f.get("password") or ""
            error = ("auth.errors.required" if not name else "auth.errors.email" if not EMAIL.match(email) else "auth.errors.password_short" if len(pw) < 8
                     else "auth.errors.email_taken" if User.query.filter_by(email=email).first() else None)
            if error:
                flash(t(error), "error")
                return render_template("auth/join.html", inv=inv, org=org, form=f), 400
            user = User(name=name, email=email, lang=g.lang)
            user.set_password(pw)
            db.session.add(user)
            db.session.flush()
        if not Membership.query.filter_by(org_id=org.id, user_id=user.id).first():
            root = OrgUnit.query.filter_by(org_id=org.id, kind="company").first()
            db.session.add(Membership(org_id=org.id, user_id=user.id, role=inv.role, unit_id=root.id if root else None))
        inv.used_at, inv.used_by = datetime.utcnow(), user.id
        db.session.commit()
        login_user(user, remember=True)
        return redirect(url_for("shell.overview", org_slug=org.slug))
    return render_template("auth/join.html", inv=inv, org=org, form={})
