"""Data module — the company's own numbers.

Upload last year's Excel; the page shows it like a spreadsheet, the AI layer reads the column headers and asks the user about
what it does not understand, and the confirmed columns become time series. Goals can then be checked against that history:
"is +30% realistic for *you*?".  See docs/AI.md and docs/DOMAIN_RULES.md (reality check).
"""
from flask import Blueprint

from app.core.modules import CreateAction, EntityType, Manifest, Tab, Widget
from app.extensions import db

bp = Blueprint("data", __name__, url_prefix="/app/<org_slug>/data", template_folder="templates")

from app.modules.data import models  # noqa: E402,F401
from app.modules.data import views  # noqa: E402,F401
from app.modules.data import hooks  # noqa: E402,F401  (registers the template functions)
from app.modules.data.seed import seed  # noqa: E402
from app.modules.data.widgets import data_loader  # noqa: E402


def _dataset(i):
    return db.session.get(models.Dataset, i)


def _series(i):
    return db.session.get(models.Series, i)


def search_provider(org, q, limit):
    from flask import url_for

    from app.core.modules import Hit

    hits = []
    for d in models.Dataset.query.filter(models.Dataset.org_id == org.id, models.Dataset.name.ilike(f"%{q}%")).limit(limit).all():
        hits.append(Hit("dataset", d.id, d.name, d.filename, url_for("data.detail", id=d.id), "table"))
    for s in models.Series.query.filter(models.Series.org_id == org.id, models.Series.name.ilike(f"%{q}%")).limit(limit).all():
        hits.append(Hit("series", s.id, s.name, s.dataset.name, url_for("data.series", id=s.id), "chart-line"))
    return hits


manifest = Manifest(
    id="data",
    label_key="data.module",
    icon="table",
    blueprint=bp,
    home_endpoint="data.index",
    tabs=[
        Tab("data.tabs.files", "data.index", "table", match=("data.map", "data.detail", "data.series")),
        Tab("data.tabs.dashboard", "data.dashboard", "layout-dashboard"),
        Tab("data.tabs.charts", "data.charts", "chart-dots"),
        Tab("data.tabs.ask", "data.ask", "sparkles"),
    ],
    optional_depends=["goals"],
    permissions={"data.edit": "member", "data.delete": "admin"},
    widgets=[Widget("data_overview", "data/widget_data.html", data_loader, order=15, span=1)],
    create=[CreateAction("data.create.upload", "data.index", "upload", "data.edit")],
    search=search_provider,
    entities=[
        EntityType("dataset", "data.entity.dataset", "table", _dataset, lambda d: d.name, "data.detail"),
        EntityType("series", "data.entity.series", "chart-line", _series, lambda s: s.name, "data.series"),
    ],
    seed=seed,
    hooks={"key_result.saved": hooks.key_result_saved, "kr.data": hooks.kr_data, "kr.branches": hooks.kr_branches, "series.check": hooks.series_check, "series.exists": hooks.series_exists, "series.catalog": hooks.series_catalog, "series.levels": hooks.series_levels},
)
