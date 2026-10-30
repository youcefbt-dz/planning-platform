"""Reports module — printable progress reports and CSV exports. It reads from other modules, owns no tables."""
from flask import Blueprint

from app.core.modules import Manifest, Tab

bp = Blueprint("reports", __name__, url_prefix="/app/<org_slug>/reports", template_folder="templates")

from app.modules.reports import views  # noqa: E402,F401

manifest = Manifest(
    id="reports",
    label_key="reports.module",
    icon="report-analytics",
    blueprint=bp,
    home_endpoint="reports.index",
    tabs=[Tab("reports.tabs.all", "reports.index", "report", match=("reports.show",))],
    optional_depends=["goals", "initiatives"],
    permissions={"reports.view": "viewer"},
)
