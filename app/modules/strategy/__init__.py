"""Strategy module — vision, mission, values, SWOT, strategic priorities, and the strategy map."""
from flask import Blueprint

from app.core.modules import CreateAction, EntityType, Manifest, Tab, Widget
from app.extensions import db

bp = Blueprint("strategy", __name__, url_prefix="/app/<org_slug>/strategy", template_folder="templates")

from app.modules.strategy import models  # noqa: E402,F401
from app.modules.strategy import views  # noqa: E402,F401
from app.modules.strategy.seed import seed  # noqa: E402
from app.modules.strategy.widgets import foundation_loader  # noqa: E402


def _priority(i):
    return db.session.get(models.Priority, i)


def search_provider(org, q, limit):
    from flask import url_for

    from app.core.modules import Hit

    rows = models.Priority.query.filter(models.Priority.org_id == org.id, models.Priority.title.ilike(f"%{q}%")).limit(limit).all()
    return [Hit("priority", r.id, r.title, "", url_for("strategy.index") + f"#priority-{r.id}", "flag-3") for r in rows]


manifest = Manifest(
    id="strategy",
    label_key="strategy.module",
    icon="compass",
    blueprint=bp,
    home_endpoint="strategy.index",
    tabs=[
        Tab("strategy.tabs.foundation", "strategy.index", "compass"),
        Tab("strategy.tabs.swot", "strategy.swot", "layout-grid"),
        Tab("strategy.tabs.map", "strategy.map", "route", requires=("goals",)),
    ],
    optional_depends=["goals"],
    permissions={"strategy.edit": "admin"},
    widgets=[Widget("strategy_foundation", "strategy/widget_foundation.html", foundation_loader, order=50, span=1)],
    create=[],
    search=search_provider,
    entities=[EntityType("priority", "strategy.entity.priority", "flag-3", _priority, lambda p: p.title, "strategy.index")],
    seed=seed,
)
