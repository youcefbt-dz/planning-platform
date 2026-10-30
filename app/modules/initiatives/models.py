"""Initiatives module tables."""
from __future__ import annotations

from app.core.models import now
from app.extensions import db

STATES = ("planned", "active", "on_hold", "completed", "cancelled")   # lifecycle (board columns)
PRIORITIES = ("high", "medium", "low")


class Initiative(db.Model):
    __tablename__ = "initiative"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.ForeignKey("organization.id"), nullable=False, index=True)
    cycle_id = db.Column(db.ForeignKey("cycle.id"), nullable=True)
    unit_id = db.Column(db.ForeignKey("org_unit.id"), nullable=True)
    owner_id = db.Column(db.ForeignKey("user.id"), nullable=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, default="")
    state = db.Column(db.String(12), default="planned", nullable=False)
    priority = db.Column(db.String(8), default="medium", nullable=False)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    manual_progress = db.Column(db.Float)   # used only when there are no milestones
    position = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now, nullable=False)

    owner = db.relationship("User", foreign_keys=[owner_id])
    unit = db.relationship("OrgUnit", foreign_keys=[unit_id])
    cycle = db.relationship("Cycle", foreign_keys=[cycle_id])
    milestones = db.relationship(
        "Milestone", backref="initiative", cascade="all, delete-orphan", order_by="Milestone.due_date, Milestone.id"
    )


class Milestone(db.Model):
    __tablename__ = "milestone"
    id = db.Column(db.Integer, primary_key=True)
    initiative_id = db.Column(db.ForeignKey("initiative.id"), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    due_date = db.Column(db.Date)
    done = db.Column(db.Boolean, default=False, nullable=False)
    done_at = db.Column(db.DateTime)
    weight = db.Column(db.Float, default=1.0)
