"""Roles and permissions.

Roles ascend: viewer < member < admin < owner. Each module declares the minimum role
per permission in its manifest (`permissions={"goals.edit": "member"}`); core permissions
are below. `can("goals.edit")` is available in templates and Python.
"""
from __future__ import annotations

from functools import wraps

from flask import abort, current_app, g

from app.core.models import ROLES

CORE_PERMISSIONS = {
    "view": "viewer",
    "checkin": "member",
    "settings.view": "admin",
    "settings.manage": "admin",
    "members.manage": "admin",
    "org.delete": "owner",
}


def role_rank(role: str | None) -> int:
    return ROLES.index(role) if role in ROLES else -1


def all_permissions() -> dict[str, str]:
    perms = dict(CORE_PERMISSIONS)
    perms.update(current_app.extensions["modules"].permissions())
    return perms


def can(permission: str) -> bool:
    role = getattr(g, "role", None)
    if role is None:
        return False
    if getattr(g, "read_only", False) and permission != "view":
        return False
    needed = all_permissions().get(permission)
    if needed is None:
        return False
    return role_rank(role) >= role_rank(needed)


def require(permission: str):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not can(permission):
                abort(403)
            return fn(*a, **kw)

        return wrapper

    return deco
