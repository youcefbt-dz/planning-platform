"""First-run setup: what a new manager still has to do, in the order that gives value at every step.

  1. profile  — name, logo, sector (and optionally the vision)        -> a branded workspace
  2. data     — last year's spreadsheet, read and explained            -> the numbers understood
  3. goal     — a first goal tied to an indicator                      -> a realistic target
  4. team     — optional: invite the people who own goals

The state is derived from the database, never stored, so it can never drift from reality.
Required steps are 1-3; step 4 is a suggestion that does not block "complete".
"""
from __future__ import annotations

from flask import current_app, url_for


def _has_data(org) -> bool:
    try:
        from app.modules.data.models import Dataset
    except Exception:
        return True  # module absent: the step does not exist
    return Dataset.query.filter_by(org_id=org.id).count() > 0


def _has_goal(org) -> bool:
    try:
        from app.modules.goals.models import Objective
    except Exception:
        return True
    return Objective.query.filter_by(org_id=org.id).count() > 0


def _has_team(org) -> bool:
    from app.core.models import Membership

    return Membership.query.filter_by(org_id=org.id).count() > 1


def state(org) -> dict:
    """{steps: [{id, label_key, href, done, required}], done, total, complete, next}"""
    registry = current_app.extensions["modules"]
    steps = [{"id": "profile", "label_key": "setup.profile", "text_key": "setup.profile_text", "icon": "building", "href": url_for("shell.settings_general", _anchor="profile"),
              "done": bool((org.settings or {}).get("profile_saved")), "required": True}]
    if registry.is_enabled("data"):
        steps.append({"id": "data", "label_key": "setup.data", "text_key": "setup.data_text", "icon": "table", "href": url_for("data.index"), "done": _has_data(org), "required": True})
    if registry.is_enabled("goals"):
        steps.append({"id": "goal", "label_key": "setup.goal", "text_key": "setup.goal_text", "icon": "target-arrow", "href": url_for("goals.new"), "done": _has_goal(org), "required": True})
    steps.append({"id": "team", "label_key": "setup.team", "text_key": "setup.team_text", "icon": "users", "href": url_for("shell.settings_members"), "done": _has_team(org), "required": False})
    required = [s for s in steps if s["required"]]
    done = sum(1 for s in required if s["done"])
    nxt = next((s for s in required if not s["done"]), None)
    return {"steps": steps, "done": done, "total": len(required), "complete": done == len(required), "next": nxt}
