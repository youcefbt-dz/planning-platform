"""First-run welcome after sign-in: (1) may the model help, (2) the logo, (3) the organization's direction (vision, mission, values) with the model's help,
then the overview. Three org settings flags: `ai_asked`, `logo_done`, `welcomed` (all done, or the whole welcome skipped).
Organizations that already saved a profile before this existed never see it."""
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
    return "shell.welcome_direction" if s.get("logo_done") else "shell.welcome_logo"


def mark(org, **flags) -> None:
    s = dict(org.settings or {})
    s.update(flags)
    org.settings = s
