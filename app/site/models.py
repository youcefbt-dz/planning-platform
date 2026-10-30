"""Marketing-site tables (waitlist). No testimonials, no fake numbers — only real sign-ups."""
from __future__ import annotations

from app.core.models import now
from app.extensions import db


class Lead(db.Model):
    __tablename__ = "lead"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), unique=True, nullable=False)
    company = db.Column(db.String(160), default="")
    lang = db.Column(db.String(5), default="ar")
    created_at = db.Column(db.DateTime, default=now, nullable=False)
