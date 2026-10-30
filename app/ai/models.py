"""Audit trail: every AI call is recorded (what task, which provider, and — for external providers — exactly what was sent)."""
from __future__ import annotations

from datetime import datetime

from app.extensions import db


class AICall(db.Model):
    __tablename__ = "ai_call"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.ForeignKey("organization.id"), nullable=True, index=True)
    user_id = db.Column(db.ForeignKey("user.id"), nullable=True)
    task = db.Column(db.String(40), nullable=False)
    provider = db.Column(db.String(40), nullable=False)
    model = db.Column(db.String(80), default="")
    external = db.Column(db.Boolean, default=False, nullable=False)  # did data leave the machine?
    ok = db.Column(db.Boolean, default=True, nullable=False)
    error = db.Column(db.String(300), default="")
    ms = db.Column(db.Integer, default=0)
    sent_chars = db.Column(db.Integer, default=0)
    sent_preview = db.Column(db.Text, default="")  # kept only for external calls, so the user can see what was shared
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
