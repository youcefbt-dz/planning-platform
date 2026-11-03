"""Public marketing site: landing page, waitlist, demo entry."""
from __future__ import annotations

import re

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, send_from_directory, url_for

from app.core.i18n import t
from app.core.models import Organization
from app.extensions import db
from app.site.models import Lead

bp = Blueprint("site", __name__, template_folder="templates")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@bp.get("/")
def landing():
    return render_template("site/landing.html")


@bp.get("/presentation")
def presentation():
    """The project presentation: a standalone full-screen slide deck (static files in static/presentation)."""
    return send_from_directory(current_app.static_folder + "/presentation", "index.html", max_age=0)


@bp.post("/waitlist")
def waitlist():
    email = (request.form.get("email") or "").strip().lower()
    company = (request.form.get("company") or "").strip()[:160]
    if not EMAIL.match(email):
        flash(t("site.waitlist.invalid"), "error")
    elif Lead.query.filter_by(email=email).first():
        flash(t("site.waitlist.exists"), "success")
    else:
        db.session.add(Lead(email=email, company=company, lang=g.lang))
        db.session.commit()
        flash(t("site.waitlist.ok"), "success")
    return redirect(url_for("site.landing") + "#waitlist")


@bp.get("/demo")
def demo():
    """Open the read-only sample organization in the visitor's language."""
    if not current_app.config.get("ENABLE_DEMO"):
        return redirect(url_for("site.landing"))
    from app.core.demo import ensure_demo

    # Always pass through the version check: a persistent database may already
    # contain an older demo that needs its seed refreshed after a deploy.
    org = ensure_demo(g.get("lang", "ar"))
    if org is None:
        flash(t("site.demo.missing"), "error")
        return redirect(url_for("site.landing"))
    return redirect(url_for("shell.overview", org_slug=org.slug))
