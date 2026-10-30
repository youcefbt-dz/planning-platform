"""Organization profile: the identity of the company that owns a workspace.

Stored in Organization.settings["profile"] (no schema change, so it can grow freely):
  sector, size, currency, fiscal_start (1-12), vision, mission, values, logo (file name, if uploaded)

The profile is context for everything downstream: it appears in the app banner and in reports,
and it is passed (without personal data) to the AI as company context.
"""
from __future__ import annotations

from pathlib import Path

from flask import current_app

SECTORS = ("trade", "manufacturing", "services", "construction", "agri", "transport", "health", "education", "tech", "other")
SIZES = ("micro", "small", "medium", "large")
CURRENCIES = ("DZD", "EUR", "USD")
LOGO_MAX_BYTES = 1_500_000
LOGO_TYPES = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}

DEFAULTS = {"sector": "", "size": "", "currency": "DZD", "fiscal_start": 1, "vision": "", "mission": "", "values": "", "logo": ""}


def profile(org) -> dict:
    """The organization profile with defaults filled in."""
    stored = (org.settings or {}).get("profile") or {}
    out = dict(DEFAULTS)
    out.update({k: v for k, v in stored.items() if k in DEFAULTS})
    return out


def save_profile(org, **changes) -> None:
    """Merge `changes` into the stored profile (re-assigns the JSON so SQLAlchemy sees the change)."""
    settings = dict(org.settings or {})
    prof = dict(settings.get("profile") or {})
    for k, v in changes.items():
        if k in DEFAULTS:
            prof[k] = v
    settings["profile"] = prof
    settings["profile_saved"] = True
    org.settings = settings


def logo_dir() -> Path:
    d = Path(current_app.instance_path) / "logos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sniff_image(data: bytes) -> str | None:
    """Return 'png' | 'jpg' | 'webp' from the file's own bytes (never from its name), or None."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def store_logo(org, data: bytes) -> str | None:
    """Save an uploaded logo; returns the stored file name, or None if the bytes are not an accepted image."""
    ext = sniff_image(data)
    if ext is None or len(data) > LOGO_MAX_BYTES:
        return None
    clear_logo(org)
    name = f"{org.id}.{ext}"
    (logo_dir() / name).write_bytes(data)
    save_profile(org, logo=name)
    return name


def clear_logo(org) -> None:
    prof = profile(org)
    if prof["logo"]:
        try:
            (logo_dir() / prof["logo"]).unlink()
        except FileNotFoundError:
            pass
        save_profile(org, logo="")


def logo_path(org) -> Path | None:
    name = profile(org)["logo"]
    if not name:
        return None
    p = logo_dir() / Path(name).name  # never trust a stored path
    return p if p.is_file() else None


def initials(name: str) -> str:
    parts = [p for p in (name or "").split() if p]
    # skip the Arabic article and one-letter particles so "مؤسسة الأفق" gives "مأ", not "مال"
    parts = [(p[2:] if p.startswith("ال") and len(p) > 3 else p) for p in parts if len(p) > 1 or len(parts) == 1] or parts
    if not parts:
        return "؟"
    return (parts[0][0] + (parts[1][0] if len(parts) > 1 else "")).upper()
