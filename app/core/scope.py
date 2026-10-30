"""Who may touch which goal: the department scope.

owner / admin ........ every goal of the organization (including the organization's own goals, the ones with no department)
a head of department . the goals of their department and of the departments under it, nothing else
any other member ..... no goal edits; they update (check in) what is assigned to them: goals and key results they own
viewer ............... read only

`can_edit_goal` is what the pages and the routes both ask, so a hidden button is never the only lock.
"""
from __future__ import annotations

from flask import abort, g
from flask_login import current_user

from app.core.models import OrgUnit
from app.core.permissions import can, role_rank


def _is_admin() -> bool:
    return role_rank(getattr(g, "role", None)) >= role_rank("admin")


def headed_unit_ids() -> set[int]:
    """The departments this person heads, and everything beneath them (cached for the request)."""
    cached = getattr(g, "_headed", None)
    if cached is not None:
        return cached
    out: set[int] = set()
    if getattr(g, "org", None) is not None and current_user.is_authenticated:
        all_units = OrgUnit.query.filter_by(org_id=g.org.id).all()
        kids: dict = {}
        for u in all_units:
            kids.setdefault(u.parent_id, []).append(u.id)
        todo = [u.id for u in all_units if u.head_id == current_user.id]
        while todo:
            x = todo.pop()
            if x not in out:
                out.add(x)
                todo += kids.get(x, [])
    g._headed = out
    return out


def can_edit_unit(unit_id: int | None) -> bool:
    """May this person create or change goals that belong to this department (None = the organization's own goals)?"""
    if not can("goals.edit"):
        return False
    if _is_admin():
        return True
    return unit_id is not None and unit_id in headed_unit_ids()


def can_add_goal() -> bool:
    return can("goals.edit") and (_is_admin() or bool(headed_unit_ids()))


def can_edit_goal(o) -> bool:
    return can_edit_unit(o.unit_id)


def can_update_goal(o) -> bool:
    """Check in on a goal or its key results: whoever may edit it, its owner, or the owner of one of its key results."""
    if not can("checkin"):
        return False
    if can_edit_goal(o):
        return True
    uid = current_user.id if current_user.is_authenticated else None
    return uid is not None and (o.owner_id == uid or any(k.owner_id == uid for k in o.key_results))


def allowed_units(all_units):
    """The departments this person may put a goal in (everything for an admin)."""
    if _is_admin():
        return list(all_units)
    ids = headed_unit_ids()
    return [u for u in all_units if u.id in ids]


def default_unit_id() -> int | None:
    if _is_admin():
        return None
    ids = sorted(headed_unit_ids())
    return ids[0] if ids else None


def guard_edit(o) -> None:
    if not can_edit_goal(o):
        abort(403)


def guard_update(o) -> None:
    if not can_update_goal(o):
        abort(403)
