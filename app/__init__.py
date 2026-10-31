"""Application factory."""
from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path

from flask import Flask, g, render_template, request, url_for
from flask_login import current_user

from app.core import formatting, i18n
from app.core.brand import Brand, logo_html
from app.core.charts import sparkline
from app.core.context import init_context
from app.core.icons import icon
from app.core.modules import Registry
from app.core.permissions import can
from app.core import scope
from app.extensions import csrf, db, login_manager, migrate

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = Path(__file__).resolve().parent

# Read ROOT/.env (API keys, SECRET_KEY...) into os.environ. The file wins over variables left in the shell/OS by
# earlier attempts (a stale GROQ_MODEL kept answering with an old model). On a host with no .env nothing changes.
try:
    from dotenv import dotenv_values

    for _k, _v in dotenv_values(ROOT / ".env").items():
        if _v not in (None, ""):  # an empty line in .env never erases a value that is already set
            os.environ[_k] = _v
except ImportError:  # python-dotenv missing: the environment variables must be set by hand
    pass


def _database_url() -> str:
    """DATABASE_URL as SQLAlchemy wants it: hosts hand out `postgres://…`, which SQLAlchemy no longer accepts."""
    url = os.environ.get("DATABASE_URL") or "sqlite:///app.db"
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _migrate_on_boot(app: Flask) -> None:
    """On a host (Render sets RENDER) or with AUTO_MIGRATE=1, bring the database to the latest schema before serving, so a fresh or wiped
    database never answers with `no such table`. Safe to repeat: it does nothing when the schema is current."""
    if app.config.get("TESTING") or not (os.environ.get("RENDER") or os.environ.get("AUTO_MIGRATE") == "1"):
        return
    from flask_migrate import upgrade

    with app.app_context():
        try:
            upgrade(directory=str(ROOT / "migrations"))
        except Exception:  # never block the site from starting; the log shows why
            app.logger.exception("automatic database upgrade failed")


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_path=str(ROOT / "instance"), instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        SQLALCHEMY_DATABASE_URI=_database_url(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        ENABLE_DEMO=os.environ.get("ENABLE_DEMO", "1") == "1",
        WTF_CSRF_TIME_LIMIT=None,
        TEMPLATES_AUTO_RELOAD=True,
    )
    if config:
        app.config.update(config)

    db.init_app(app)
    migrate.init_app(app, db, directory=str(ROOT / "migrations"))
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    csrf.init_app(app)

    # 1. brand ---------------------------------------------------------------
    app.extensions["brand"] = Brand()

    # 2. modules (imports their models, registers enabled blueprints) ----------
    registry = Registry()
    app.extensions["modules"] = registry
    from app.core import models as _core_models  # noqa: F401  (core tables)
    from app.site import models as _site_models  # noqa: F401
    from app.ai import models as _ai_models  # noqa: F401
    from app.ai.hub import Hub

    app.extensions["ai"] = Hub()
    registry.load(app)

    # 3. translations: core + site + every present module ----------------------
    app.extensions["catalogs"] = i18n.Catalogs(APP_DIR, list(registry.discovered))
    app.extensions["glossary"] = i18n.load_glossary(APP_DIR / "i18n" / "glossary.yaml")

    # 4. core blueprints -------------------------------------------------------
    from app.auth import bp as auth_bp
    from app.shell import bp as shell_bp
    from app.site import bp as site_bp

    app.register_blueprint(site_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(shell_bp)

    init_context(app)
    _register_template_api(app)
    _register_errors(app)

    from app.core.cli import register_cli

    register_cli(app)

    @login_manager.user_loader
    def _load_user(uid):
        from app.core.models import User

        return db.session.get(User, int(uid))

    _migrate_on_boot(app)
    return app


def _nav():
    """Top-level navigation (and each module's sub-tabs) built from the enabled modules."""
    from flask import current_app

    registry = current_app.extensions["modules"]
    items = []
    for m in registry.ordered():
        if not m.home_endpoint or not all(registry.is_enabled(r) for r in m.shown_with):
            continue
        tabs = [
            {"key": tb.key, "icon": tb.icon, "href": url_for(tb.endpoint),
             "current": request.endpoint == tb.endpoint or request.endpoint in tb.match}
            for tb in m.tabs if all(registry.is_enabled(r) for r in tb.requires)
        ]
        items.append({"id": m.id, "label_key": m.label_key, "icon": m.icon, "href": url_for(m.home_endpoint),
                      "active": request.blueprint == m.id, "tabs": tabs})
    return items


STATUS_ICONS = {
    "on_track": "trending-up", "at_risk": "alert-triangle", "off_track": "circle-x", "not_started": "circle-dashed",
    "on_hold": "player-pause", "completed": "circle-check", "cancelled": "x",
}


def my_orgs():
    if not current_user.is_authenticated:
        return []
    from app.core.models import Membership

    return [m.org for m in Membership.query.filter_by(user_id=current_user.id).order_by(Membership.id).all()]


def _register_template_api(app: Flask) -> None:
    """Everything templates can call. Keep this list short and documented in docs/TEMPLATE_API.md."""

    # Imported macros ({% from "components/ui.html" import ... %}) do NOT see context-processor
    # values, so every request-independent helper is registered as a Jinja global as well.
    def _attr(obj, path):
        for part in path.split("."):
            obj = getattr(obj, part, None)
        return obj

    def opts(items, value, label):
        """<select> options from model rows: opts(units, 'id', 'name') -> [(id, name), ...]"""
        return [(_attr(i, value), _attr(i, label)) for i in items]

    def topts(values, prefix):
        """<select> options from codes with a translated label: topts(states, 'goals.states.')"""
        return [(v, i18n.t(prefix + v)) for v in values]

    def org_logo_url(o):
        """URL of the organization's uploaded logo, or None (the tile then shows initials)."""
        from app.core import profile as _profile

        if o is None or not _profile.profile(o)["logo"]:
            return None
        return url_for("shell.org_logo", org_slug=o.slug, v=_profile.profile(o)["logo"])

    def org_initials(o):
        from app.core import profile as _profile

        return _profile.initials(o.name if o else "")

    app.jinja_env.globals.update(
        opts=opts, topts=topts, month_names=formatting.month_names, unit_text=formatting.unit_text, org_logo_url=org_logo_url, org_initials=org_initials,
        t=i18n.t, tn=i18n.tn, th=i18n.th, icon=icon, can=can, n=formatting.fmt_number,
        can_edit_goal=scope.can_edit_goal, can_update_goal=scope.can_update_goal, can_add_goal=scope.can_add_goal, can_edit_unit=scope.can_edit_unit,
        pct=formatting.fmt_percent, d=formatting.fmt_date, val=formatting.fmt_value, bdi=formatting.bdi,
        STATUS_ICONS=STATUS_ICONS,
        logo=lambda kind="full", tone="on_light", cls="": logo_html(kind, tone, i18n.current_lang(), cls),
        spark=lambda series: sparkline([v for _, v in series]),
    )

    @app.context_processor
    def inject():
        lang = i18n.current_lang()
        brand = app.extensions["brand"]
        ctx = {
            "t": i18n.t,
            "tn": i18n.tn,
            "th": i18n.th,
            "lang": lang,
            "dir": i18n.direction(lang),
            "brand": brand,
            "brand_name": brand.name_for(lang),
            "brand_short": brand.short_for(lang),
            "brand_css": brand.css_vars(),
            "logo": lambda kind="full", tone="on_light", cls="": logo_html(kind, tone, lang, cls),
            "icon": icon,
            "can": can,
            "n": formatting.fmt_number,
            "pct": formatting.fmt_percent,
            "d": formatting.fmt_date,
            "val": formatting.fmt_value,
            "bdi": formatting.bdi,
            "today": date.today(),
            "modules": app.extensions["modules"],
            "org": g.get("org"),
            "role": g.get("role"),
            "read_only": g.get("read_only", False),
            "me": current_user,
            "STATUS_ICONS": STATUS_ICONS,
            "spark": lambda series: sparkline([v for _, v in series]),
            "my_orgs": my_orgs,
            "org_logo_url": org_logo_url,
            "org_initials": org_initials,
        }
        if g.get("org") is not None:
            from app.core import profile as _profile
            from app.core import setup as _setup
            from app.core.services import current_cycle

            prof = _profile.profile(g.org)
            ctx["org_profile"] = prof
            ctx["band_cycle"] = current_cycle(g.org)
            ctx["band_sector"] = i18n.t("profile.sectors." + prof["sector"]) if prof["sector"] else ""
            ctx["setup"] = _setup.state(g.org) if (current_user.is_authenticated and not g.get("read_only") and can("settings.manage")) else None
            ctx["nav"] = _nav()
            ctx["create_actions"] = [a for a in app.extensions["modules"].create_actions() if not a.permission or can(a.permission)]
        return ctx

    @app.template_filter("ago")
    def _ago(dt: datetime):
        """Relative time, localized (days granularity is enough for planning)."""
        if not dt:
            return "—"
        days = (datetime.utcnow() - dt).days
        if days <= 0:
            return i18n.t("time.today")
        if days == 1:
            return i18n.t("time.yesterday")
        return i18n.tn("time.days_ago", days)


def _register_errors(app: Flask) -> None:
    def make(code):
        def handler(e):
            return render_template(f"errors/{code}.html", code=code), code

        return handler

    for code in (403, 404):
        app.register_error_handler(code, make(code))
