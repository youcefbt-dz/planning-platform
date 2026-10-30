"""Core data model — shared by every module. Module-specific tables live in the module's own models.py.

Rules:
  * every business row carries org_id and is always queried through the current organization;
  * cross-module relations never use foreign keys between module tables — they go through
    `Link` (entity_type/entity_id pairs), so any module can be removed without breaking others;
  * check-ins and activity are generic (entity_type, entity_id).
"""
from __future__ import annotations

from datetime import date, datetime

from flask_login import UserMixin
from sqlalchemy import JSON, UniqueConstraint
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db

ROLES = ("viewer", "member", "admin", "owner")  # ascending power


def now() -> datetime:
    return datetime.utcnow()


class Organization(db.Model):
    __tablename__ = "organization"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(80), unique=True, nullable=False, index=True)
    is_demo = db.Column(db.Boolean, default=False, nullable=False)
    settings = db.Column(JSON, default=dict)  # thresholds, cadence, …
    created_at = db.Column(db.DateTime, default=now, nullable=False)

    memberships = db.relationship("Membership", back_populates="org", cascade="all, delete-orphan")

    def setting(self, key: str, default=None):
        return (self.settings or {}).get(key, default)


class User(UserMixin, db.Model):
    __tablename__ = "user"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    lang = db.Column(db.String(5), default="ar")
    created_at = db.Column(db.DateTime, default=now, nullable=False)

    memberships = db.relationship("Membership", back_populates="user", cascade="all, delete-orphan")

    def set_password(self, pw: str) -> None:
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw: str) -> bool:
        return check_password_hash(self.password_hash, pw)

    @property
    def initials(self) -> str:
        parts = [p for p in self.name.split() if p]
        return (parts[0][0] + (parts[1][0] if len(parts) > 1 else "")).upper() if parts else "?"


class Invite(db.Model):
    """A link that lets one person join an organization with a given role; valid for 7 days, single use."""
    __tablename__ = "invite"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.ForeignKey("organization.id"), nullable=False, index=True)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    role = db.Column(db.String(12), default="member", nullable=False)
    created_by = db.Column(db.ForeignKey("user.id"), nullable=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    used_by = db.Column(db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=now, nullable=False)

    org = db.relationship("Organization")

    def valid(self) -> bool:
        from datetime import datetime

        return self.used_at is None and self.expires_at > datetime.utcnow()


class Membership(db.Model):
    __tablename__ = "membership"
    __table_args__ = (UniqueConstraint("org_id", "user_id"),)
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.ForeignKey("organization.id"), nullable=False, index=True)
    user_id = db.Column(db.ForeignKey("user.id"), nullable=False, index=True)
    role = db.Column(db.String(12), default="member", nullable=False)
    unit_id = db.Column(db.ForeignKey("org_unit.id"), nullable=True)
    title = db.Column(db.String(120))  # job title, free text

    org = db.relationship("Organization", back_populates="memberships")
    user = db.relationship("User", back_populates="memberships")
    unit = db.relationship("OrgUnit", foreign_keys=[unit_id])


class OrgUnit(db.Model):
    """Organizational tree: company -> department -> team (kinds are labels, depth is free)."""

    __tablename__ = "org_unit"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.ForeignKey("organization.id"), nullable=False, index=True)
    parent_id = db.Column(db.ForeignKey("org_unit.id"), nullable=True)
    name = db.Column(db.String(160), nullable=False)
    kind = db.Column(db.String(20), default="department")  # company | department | team
    position = db.Column(db.Integer, default=0)
    head_id = db.Column(db.ForeignKey("user.id"), nullable=True)  # the head of this department (one person)

    children = db.relationship("OrgUnit", backref=db.backref("parent", remote_side=[id]), order_by="OrgUnit.position")
    head = db.relationship("User", foreign_keys=[head_id])


class Cycle(db.Model):
    """A planning period: year, quarter, or any custom range."""

    __tablename__ = "cycle"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.ForeignKey("organization.id"), nullable=False, index=True)
    parent_id = db.Column(db.ForeignKey("cycle.id"), nullable=True)
    name = db.Column(db.String(80), nullable=False)
    kind = db.Column(db.String(12), default="quarter")  # year | quarter | custom
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(10), default="active")  # planned | active | closed

    def contains(self, d: date) -> bool:
        return self.start_date <= d <= self.end_date


class Link(db.Model):
    """Loose, module-agnostic relation between two entities."""

    __tablename__ = "link"
    __table_args__ = (UniqueConstraint("org_id", "source_type", "source_id", "target_type", "target_id", "kind"),)
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.ForeignKey("organization.id"), nullable=False, index=True)
    source_type = db.Column(db.String(30), nullable=False)
    source_id = db.Column(db.Integer, nullable=False)
    target_type = db.Column(db.String(30), nullable=False)
    target_id = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(20), default="supports")  # supports | depends_on | relates
    created_at = db.Column(db.DateTime, default=now, nullable=False)


class CheckIn(db.Model):
    """A dated progress update on any entity (key result, objective, indicator, initiative…)."""

    __tablename__ = "check_in"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.ForeignKey("organization.id"), nullable=False, index=True)
    entity_type = db.Column(db.String(30), nullable=False)
    entity_id = db.Column(db.Integer, nullable=False)
    user_id = db.Column(db.ForeignKey("user.id"), nullable=True)
    value = db.Column(db.Float)          # new measured value, when the entity has one
    progress = db.Column(db.Float)       # progress 0..1 right after this check-in (snapshot)
    status = db.Column(db.String(12))    # manual status chosen by the author (optional)
    comment = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=now, nullable=False, index=True)

    user = db.relationship("User")

    __table_args__ = (db.Index("ix_checkin_entity", "org_id", "entity_type", "entity_id"),)


class Activity(db.Model):
    """Append-only feed: who did what to which entity."""

    __tablename__ = "activity"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.ForeignKey("organization.id"), nullable=False, index=True)
    user_id = db.Column(db.ForeignKey("user.id"), nullable=True)
    verb = db.Column(db.String(30), nullable=False)   # created | updated | checked_in | deleted …
    entity_type = db.Column(db.String(30), nullable=False)
    entity_id = db.Column(db.Integer, nullable=False)
    entity_title = db.Column(db.String(255), default="")
    created_at = db.Column(db.DateTime, default=now, nullable=False, index=True)

    user = db.relationship("User")
