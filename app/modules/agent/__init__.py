"""Agent module — the planning assistant: a model that READS the organization through tools (goals, key results, departments, uploaded data),
analyses, and PROPOSES drafts that a person approves. It owns no tables. See app/modules/agent/loop.py for the rules it works by."""
from flask import Blueprint

from app.core.modules import Manifest, Tab

bp = Blueprint("agent", __name__, url_prefix="/app/<org_slug>/assistant", template_folder="templates")

from app.modules.agent import views  # noqa: E402,F401

manifest = Manifest(
    id="agent",
    label_key="agent.module",
    icon="sparkles",
    blueprint=bp,
    home_endpoint="",  # the assistant is launched from the floating dock, not the main navigation
    tabs=[Tab("agent.tabs.chat", "agent.index", "message-circle")],
    optional_depends=["goals", "data", "orgmap"],
    permissions={"agent.apply": "member"}   # reading needs only access to the organization (a read-only visitor gets the computed briefing),
)
