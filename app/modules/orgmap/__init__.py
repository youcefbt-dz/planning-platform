"""Org map (مخطط المؤسسة): the whole organization on one page — organization → goals → indicators (with branch drill-down) → levers —
with the gaps highlighted. Owns no tables; reads goals and, when it is on, data."""
from flask import Blueprint

from app.core.modules import Manifest, Tab

bp = Blueprint("orgmap", __name__, url_prefix="/app/<org_slug>/map", template_folder="templates")

from app.modules.orgmap import units, views  # noqa: E402,F401

manifest = Manifest(
    id="orgmap",
    label_key="orgmap.module",
    icon="sitemap",
    blueprint=bp,
    home_endpoint="orgmap.index",
    tabs=[Tab("orgmap.tabs.map", "orgmap.index", "sitemap"), Tab("orgmap.tabs.units", "orgmap.units_index", "users-group", match=("orgmap.unit",))],
    optional_depends=["goals", "data"],
    shown_with=["goals"],
)
