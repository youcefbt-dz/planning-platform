"""Request context: direction, current organization and role.

All product URLs live under  /app/<org_slug>/…  . A url_value_preprocessor resolves the
organization once per request and checks membership; a url_defaults hook means templates
call url_for('goals.index') without ever passing org_slug.

The public demo organization (is_demo=True) is readable by anyone, never writable.
"""
from __future__ import annotations

from flask import Flask, abort, g, redirect, request, url_for
from flask_login import current_user

from app.core import i18n
from app.core.models import Membership, Organization


def init_context(app: Flask) -> None:
    @app.before_request
    def _lang():
        g.lang = i18n.pick_lang()
        g.dir = i18n.direction(g.lang)
        # url_value_preprocessors run BEFORE before_request hooks, so keep what they set.
        g.org = getattr(g, "org", None)
        g.role = getattr(g, "role", None)
        g.read_only = getattr(g, "read_only", False)

    @app.url_value_preprocessor
    def _org(endpoint, values):
        if not values or "org_slug" not in values:
            return
        slug = values.pop("org_slug")
        org = Organization.query.filter_by(slug=slug).first()
        if org is None:
            abort(404)
        role = None
        if current_user.is_authenticated:
            m = Membership.query.filter_by(org_id=org.id, user_id=current_user.id).first()
            role = m.role if m else None
        if role is None and org.is_demo:
            role, g.read_only = "viewer", True
        if role is None:
            if not current_user.is_authenticated:
                # raised inside a preprocessor: abort with a redirect response
                abort(redirect(url_for("auth.login", next=request.full_path.rstrip("?"))))
            abort(404)  # authenticated but not a member: don't reveal the org exists
        g.org, g.role = org, role

    @app.url_defaults
    def _inject_org(endpoint, values):
        if "org_slug" in values or not getattr(g, "org", None):
            return
        try:
            expects = app.url_map.is_endpoint_expecting(endpoint, "org_slug")
        except KeyError:  # endpoint of a disabled module: let url_for raise its normal BuildError
            return
        if expects:
            values["org_slug"] = g.org.slug
