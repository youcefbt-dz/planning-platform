"""Tolerant form parsing: Arabic-Indic digits, comma decimals, ISO or d/m/Y dates, scoped lookups."""
from __future__ import annotations

from datetime import date, datetime

from flask import abort, g, request

from app.extensions import db

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬", "01234567890123456789.,")


def norm(value: str) -> str:
    return (value or "").translate(_DIGITS).strip()


def s(name: str, default: str = "", maxlen: int | None = None) -> str:
    v = (request.form.get(name) or "").strip() or default
    return v[:maxlen] if maxlen else v


def num(name: str, default: float | None = None) -> float | None:
    v = norm(request.form.get(name) or "").replace(" ", "").replace(" ", "")
    if not v:
        return default
    # "1,5" decimal comma vs "1,500" thousands: a single comma followed by !=3 digits is decimal
    if "," in v and "." not in v:
        head, _, tail = v.rpartition(",")
        v = f"{head}.{tail}" if len(tail) != 3 else head + tail
    else:
        v = v.replace(",", "")
    try:
        return float(v)
    except ValueError:
        return default


def integer(name: str, default: int | None = None) -> int | None:
    v = norm(request.form.get(name) or "")
    try:
        return int(v) if v else default
    except ValueError:
        return default


def when(name: str, default: date | None = None) -> date | None:
    v = norm(request.form.get(name) or "")
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return default


def choice(name: str, allowed, default=None):
    v = request.form.get(name)
    return v if v in allowed else default


def get_scoped(model, ident: int):
    """Fetch a row of the current organization or 404 (never leak across organizations)."""
    obj = db.session.get(model, ident)
    if obj is None or getattr(obj, "org_id", g.org.id) != g.org.id:
        abort(404)
    return obj


def member_or_none(user_id: int | None):
    """Validate that a chosen owner belongs to the current organization."""
    from app.core.models import Membership, User

    if not user_id:
        return None
    ok = Membership.query.filter_by(org_id=g.org.id, user_id=user_id).first()
    return db.session.get(User, user_id) if ok else None
