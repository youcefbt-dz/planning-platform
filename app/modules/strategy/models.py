"""Strategy module tables: the strategic foundation (vision, mission, values), SWOT, priorities."""
from __future__ import annotations

from app.core.models import now
from app.extensions import db

SWOT_KINDS = ("strength", "weakness", "opportunity", "threat")
FOUNDATION_KINDS = ("vision", "mission", "value")


class FoundationItem(db.Model):
    """vision / mission (one row each, edited in place) and values (many rows)."""

    __tablename__ = "strategy_foundation"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.ForeignKey("organization.id"), nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False)
    title = db.Column(db.String(200), default="")      # value name (empty for vision/mission)
    text = db.Column(db.Text, default="")
    position = db.Column(db.Integer, default=0)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now, nullable=False)


class SwotItem(db.Model):
    __tablename__ = "strategy_swot"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.ForeignKey("organization.id"), nullable=False, index=True)
    kind = db.Column(db.String(12), nullable=False)    # strength | weakness | opportunity | threat
    text = db.Column(db.String(400), nullable=False)
    position = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=now, nullable=False)


class Priority(db.Model):
    """A strategic priority: a theme the objectives roll up to."""

    __tablename__ = "strategy_priority"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.ForeignKey("organization.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    position = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=now, nullable=False)
