"""First-run organization setup: AI consent, logo, direction, team, then departments.
Organizations that completed the older welcome flow or saved a profile before it existed
continue directly to the workspace."""
from __future__ import annotations


def step_endpoint(org, role: str | None) -> str | None:
    """The shell endpoint the person should land on, or None when the welcome is over / not theirs (only owners and admins configure the org)."""
    if role not in ("admin", "owner"):
        return None
    s = org.settings or {}
    if s.get("welcomed") or (s.get("profile_saved") and "ai_asked" not in s):
        return None
    if not s.get("ai_asked"):
        return "shell.welcome"
    if not s.get("logo_done"):
        return "shell.welcome_logo"
    if not s.get("direction_done"):
        return "shell.welcome_direction"
    if not s.get("team_done"):
        return "shell.welcome_members"
    if not s.get("units_done"):
        return "shell.welcome_units"
    return None


def mark(org, **flags) -> None:
    s = dict(org.settings or {})
    s.update(flags)
    org.settings = s
