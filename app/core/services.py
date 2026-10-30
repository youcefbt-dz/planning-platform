"""Shared helpers used by modules: activity log, check-ins, links, entity lookup, org settings."""
from __future__ import annotations

from datetime import datetime

from flask import current_app, g, url_for
from flask_login import current_user

from app.core.models import Activity, CheckIn, Cycle, Link, Membership, OrgUnit
from app.core.progress import DEFAULT_THRESHOLDS
from app.extensions import db


def registry():
    return current_app.extensions["modules"]


# -- organization settings -----------------------------------------------------
def thresholds(org) -> dict:
    base = {**DEFAULT_THRESHOLDS, **current_app.config.get("PRODUCT_DEFAULTS", {}).get("status_thresholds", {})}
    return {**base, **(org.setting("status_thresholds") or {})}


def cadence_days(org) -> int:
    d = current_app.config.get("PRODUCT_DEFAULTS", {}).get("checkin_cadence_days", 14)
    return int(org.setting("checkin_cadence_days", d))


def current_cycle(org, today=None):
    from datetime import date

    today = today or date.today()
    cs = Cycle.query.filter_by(org_id=org.id).filter(Cycle.status != "closed").all()
    inside = [c for c in cs if c.contains(today)]
    if inside:  # prefer the narrowest (quarter over year)
        return min(inside, key=lambda c: (c.end_date - c.start_date).days)
    return max(cs, key=lambda c: c.end_date) if cs else None


def members(org):
    return Membership.query.filter_by(org_id=org.id).all()


def units(org):
    return OrgUnit.query.filter_by(org_id=org.id).order_by(OrgUnit.position, OrgUnit.id).all()


# -- activity & check-ins ------------------------------------------------------
def log_activity(verb: str, entity_type: str, entity_id: int, title: str = "", org=None, user=None) -> None:
    org = org or g.org
    user = user or (current_user if current_user.is_authenticated else None)
    db.session.add(
        Activity(
            org_id=org.id,
            user_id=user.id if user else None,
            verb=verb,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_title=title[:255],
        )
    )


def add_checkin(entity_type, entity_id, *, value=None, progress=None, status=None, comment="", org=None, user=None, when=None):
    org = org or g.org
    user = user or (current_user if current_user.is_authenticated else None)
    c = CheckIn(
        org_id=org.id,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user.id if user else None,
        value=value,
        progress=progress,
        status=status or None,
        comment=(comment or "").strip(),
        created_at=when or datetime.utcnow(),
    )
    db.session.add(c)
    return c


def checkins_for(org_id, entity_type, entity_id, limit=None):
    q = CheckIn.query.filter_by(org_id=org_id, entity_type=entity_type, entity_id=entity_id).order_by(CheckIn.created_at.desc(), CheckIn.id.desc())
    return q.limit(limit).all() if limit else q.all()


def last_checkin(org_id, entity_type, entity_id):
    return (
        CheckIn.query.filter_by(org_id=org_id, entity_type=entity_type, entity_id=entity_id)
        .order_by(CheckIn.created_at.desc(), CheckIn.id.desc())
        .first()
    )


# -- links (cross-module relations) -------------------------------------------
def add_link(org_id, source, target, kind="supports"):
    """source / target are (type, id) tuples. Idempotent."""
    exists = Link.query.filter_by(
        org_id=org_id, source_type=source[0], source_id=source[1], target_type=target[0], target_id=target[1], kind=kind
    ).first()
    if exists:
        return exists
    link = Link(org_id=org_id, source_type=source[0], source_id=source[1], target_type=target[0], target_id=target[1], kind=kind)
    db.session.add(link)
    return link


def links_from(org_id, source, kind=None):
    q = Link.query.filter_by(org_id=org_id, source_type=source[0], source_id=source[1])
    return (q.filter_by(kind=kind) if kind else q).all()


def links_to(org_id, target, kind=None):
    q = Link.query.filter_by(org_id=org_id, target_type=target[0], target_id=target[1])
    return (q.filter_by(kind=kind) if kind else q).all()


def remove_links_of(org_id, entity_type, entity_id):
    Link.query.filter_by(org_id=org_id, source_type=entity_type, source_id=entity_id).delete()
    Link.query.filter_by(org_id=org_id, target_type=entity_type, target_id=entity_id).delete()


# -- generic entity access -----------------------------------------------------
def entity_obj(entity_type: str, entity_id: int):
    et = registry().entity(entity_type)
    return et.loader(entity_id) if et else None


def entity_title(entity_type: str, entity_id: int) -> str:
    et = registry().entity(entity_type)
    obj = et.loader(entity_id) if et else None
    return et.title(obj) if obj is not None else "—"


def entity_url(entity_type: str, entity_id: int) -> str | None:
    et = registry().entity(entity_type)
    if not et:
        return None
    return url_for(et.endpoint, **{et.id_param: entity_id})


def entity_icon(entity_type: str) -> str:
    et = registry().entity(entity_type)
    return et.icon if et else "circle"
