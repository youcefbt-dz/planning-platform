"""Initiatives module — the projects and actions that move objectives: list, board, roadmap, milestones."""
from flask import Blueprint

from app.core.modules import CreateAction, EntityType, Manifest, Tab, Widget
from app.extensions import db

bp = Blueprint("initiatives", __name__, url_prefix="/app/<org_slug>/initiatives", template_folder="templates")

from app.modules.initiatives import models  # noqa: E402,F401
from app.modules.initiatives import views  # noqa: E402,F401
from app.modules.initiatives.seed import seed  # noqa: E402
from app.modules.initiatives.widgets import health_loader  # noqa: E402


def _initiative(i):
    return db.session.get(models.Initiative, i)


def search_provider(org, q, limit):
    from flask import url_for

    from app.core.modules import Hit

    rows = models.Initiative.query.filter(models.Initiative.org_id == org.id, models.Initiative.title.ilike(f"%{q}%")).limit(limit).all()
    return [Hit("initiative", r.id, r.title, r.unit.name if r.unit else "", url_for("initiatives.detail", id=r.id), "rocket") for r in rows]


manifest = Manifest(
    id="initiatives",
    label_key="initiatives.module",
    icon="rocket",
    blueprint=bp,
    home_endpoint="initiatives.index",
    tabs=[
        Tab("initiatives.tabs.list", "initiatives.index", "list-details", match=("initiatives.detail", "initiatives.new", "initiatives.edit")),
        Tab("initiatives.tabs.board", "initiatives.board", "layout-kanban"),
        Tab("initiatives.tabs.roadmap", "initiatives.roadmap", "timeline"),
    ],
    optional_depends=["goals"],
    permissions={"initiatives.edit": "member", "initiatives.delete": "admin"},
    widgets=[Widget("initiatives_health", "initiatives/widget_health.html", health_loader, order=40, span=1)],
    create=[CreateAction("initiatives.create", "initiatives.new", "rocket", "initiatives.edit")],
    search=search_provider,
    entities=[EntityType("initiative", "initiatives.entity", "rocket", _initiative, lambda i: i.title, "initiatives.detail")],
    seed=seed,
)
