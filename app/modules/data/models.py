"""Data module tables: an uploaded dataset (a spreadsheet the organization brought) and the time series built from it."""
from __future__ import annotations

from datetime import date

from app.core.models import now
from app.extensions import db


class Dataset(db.Model):
    """One uploaded file. `draft` while the user is still confirming what the columns mean; `ready` once series exist."""
    __tablename__ = "dataset"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.ForeignKey("organization.id"), nullable=False, index=True)
    created_by = db.Column(db.ForeignKey("user.id"), nullable=True)
    name = db.Column(db.String(160), nullable=False)
    filename = db.Column(db.String(200), default="")
    stored_as = db.Column(db.String(120), default="")          # file under instance/uploads/<org_id>/ ("" for seeded demo data)
    status = db.Column(db.String(8), default="draft", nullable=False)   # draft | ready

    sheet_index = db.Column(db.Integer, default=0, nullable=False)
    header_row = db.Column(db.Integer, nullable=True)           # None = detected automatically
    year_hint = db.Column(db.Integer, nullable=True)            # user override for month-only headers
    layout = db.Column(db.String(6), default="long")            # long | wide
    summary = db.Column(db.Text, default="")                    # one-sentence description of the table
    columns = db.Column(db.JSON, default=list)                  # the current mapping (what the user sees and confirms)
    questions = db.Column(db.JSON, default=list)                # open questions: [{column, question, options}]
    meta = db.Column(db.JSON, default=dict)                     # sheets, provider/model used, rows, notes, assumed_year…
    fixes = db.Column(db.JSON, default=dict)                    # what the user decided about odd values, per measure column: {"2": {"cumulative": "to_period", …}}
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now, nullable=False)

    series = db.relationship("Series", backref="dataset", cascade="all, delete-orphan", order_by="Series.id")
    versions = db.relationship("DatasetVersion", backref="dataset", cascade="all, delete-orphan", order_by="DatasetVersion.number")


class DatasetVersion(db.Model):
    """Every file the organization has uploaded for a dataset (the first upload and each newer version) and what changed with it."""
    __tablename__ = "dataset_version"
    id = db.Column(db.Integer, primary_key=True)
    dataset_id = db.Column(db.ForeignKey("dataset.id"), nullable=False, index=True)
    number = db.Column(db.Integer, nullable=False)
    filename = db.Column(db.String(200), default="")
    stored_as = db.Column(db.String(120), default="")
    uploaded_by = db.Column(db.ForeignKey("user.id"), nullable=True)
    confirmed = db.Column(db.Boolean, default=False, nullable=False)
    diff = db.Column(db.JSON, nullable=True)                    # what changed against the previous confirmed version (see service.diff_series)
    created_at = db.Column(db.DateTime, default=now, nullable=False)


class Series(db.Model):
    """A clean time series (one measure, optionally one category value). Goals point to it with a core `Link` of kind `measured_by`."""
    __tablename__ = "series"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.ForeignKey("organization.id"), nullable=False, index=True)
    dataset_id = db.Column(db.ForeignKey("dataset.id"), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    unit = db.Column(db.String(24), default="")
    direction = db.Column(db.String(14), default="higher_better", nullable=False)
    aggregation = db.Column(db.String(6), default="sum")
    dimension = db.Column(db.String(120), nullable=True)        # category value, None for the total
    period_months = db.Column(db.Integer, default=1, nullable=False)
    points = db.Column(db.JSON, default=list)                   # [["2025-01-01", 123.0], …] ascending
    created_at = db.Column(db.DateTime, default=now, nullable=False)

    def pairs(self) -> list[tuple[date, float]]:
        return [(date.fromisoformat(d), float(v)) for d, v in (self.points or [])]

    @property
    def latest(self):
        p = self.pairs()
        return p[-1] if p else None
