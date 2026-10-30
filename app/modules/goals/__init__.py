"""Goals module — objectives & key results (OKR), alignment tree, indicators (KPI), check-ins."""
from flask import Blueprint

from app.core.modules import CreateAction, EntityType, Manifest, Tab, Widget
from app.extensions import db

bp = Blueprint("goals", __name__, url_prefix="/app/<org_slug>/goals", template_folder="templates")

from app.modules.goals import models  # noqa: E402,F401  (registers tables)
from app.modules.goals import views  # noqa: E402,F401  (registers routes on bp)
from app.modules.goals.search import search_provider  # noqa: E402
from app.modules.goals.seed import seed  # noqa: E402
from app.modules.goals.service import sync_from_series  # noqa: E402
from app.modules.goals.widgets import attention_loader, indicators_loader, summary_loader  # noqa: E402


def _objective(i):
    return db.session.get(models.Objective, i)


def _key_result(i):
    return db.session.get(models.KeyResult, i)


def _indicator(i):
    return db.session.get(models.Indicator, i)


manifest = Manifest(
    id="goals",
    label_key="goals.module",
    icon="target-arrow",
    blueprint=bp,
    home_endpoint="goals.index",
    tabs=[
        Tab("goals.tabs.list", "goals.index", "list-details", match=("goals.detail", "goals.new", "goals.edit")),
        Tab("goals.tabs.health", "goals.health", "progress-check"),
        Tab("goals.tabs.tree", "goals.tree", "sitemap"),
        Tab("goals.tabs.indicators", "goals.indicators", "chart-line", match=("goals.indicator_detail", "goals.indicator_new", "goals.indicator_edit")),
    ],
    permissions={"goals.edit": "member", "goals.delete": "admin", "indicators.edit": "member", "indicators.delete": "admin"},
    widgets=[
        Widget("goals_summary", "goals/widget_summary.html", summary_loader, order=10, span=2),
        Widget("goals_attention", "goals/widget_attention.html", attention_loader, order=20, span=1),
        Widget("goals_indicators", "goals/widget_indicators.html", indicators_loader, order=30, span=1),
    ],
    create=[
        CreateAction("goals.create.objective", "goals.new", "target-arrow", "goals.edit"),
        CreateAction("goals.create.indicator", "goals.indicator_new", "chart-line", "indicators.edit"),
    ],
    search=search_provider,
    entities=[
        EntityType("objective", "goals.entity.objective", "target-arrow", _objective, lambda o: o.title, "goals.detail"),
        EntityType("key_result", "goals.entity.key_result", "flag", _key_result, lambda k: k.title, "goals.kr_open"),
        EntityType("indicator", "goals.entity.indicator", "chart-line", _indicator, lambda i: i.name, "goals.indicator_detail"),
    ],
    seed=seed,
    hooks={"series.updated": sync_from_series},
)
