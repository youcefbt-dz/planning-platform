"""Goals module tables: objectives, key results, indicators (KPIs) and their values."""
from __future__ import annotations

from app.core.models import now
from app.extensions import db

PERSPECTIVES = ("financial", "customer", "process", "learning")  # Balanced Scorecard
PROGRESS_DRIVERS = ("key_results", "children", "both")
METRIC_TYPES = ("number", "percent", "currency", "boolean")
FREQUENCIES = ("weekly", "monthly", "quarterly", "yearly")
KR_TYPES = ("increase", "decrease", "stay_above", "stay_below", "binary", "milestone")
COMMITMENTS = ("committed", "aspirational")      # committed: expected to be fully delivered · aspirational: a stretch, ~70% counts as success
MEASURES = ("latest", "sum")                      # how a linked data series becomes the key result's current value
CERTAINTIES = ("confirmed", "probable", "hoped")
FACTOR_KINDS = ("price", "volume", "capacity", "market", "contract", "cost", "other")


class Objective(db.Model):
    __tablename__ = "objective"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.ForeignKey("organization.id"), nullable=False, index=True)
    cycle_id = db.Column(db.ForeignKey("cycle.id"), nullable=True, index=True)
    unit_id = db.Column(db.ForeignKey("org_unit.id"), nullable=True)
    owner_id = db.Column(db.ForeignKey("user.id"), nullable=True)
    parent_id = db.Column(db.ForeignKey("objective.id"), nullable=True, index=True)

    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, default="")
    perspective = db.Column(db.String(12))                       # optional BSC lane
    progress_driver = db.Column(db.String(12), default="key_results", nullable=False)
    weight = db.Column(db.Float, default=1.0)                    # weight inside its parent
    state = db.Column(db.String(10), default="active", nullable=False)  # active | on_hold | cancelled
    commitment = db.Column(db.String(12), default="committed", nullable=False)
    rationale = db.Column(db.Text, default="")                    # why this matters (the "who cares?" test)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now, nullable=False)

    owner = db.relationship("User", foreign_keys=[owner_id])
    unit = db.relationship("OrgUnit", foreign_keys=[unit_id])
    cycle = db.relationship("Cycle", foreign_keys=[cycle_id])
    parent = db.relationship("Objective", remote_side=[id], backref=db.backref("children", order_by="Objective.id"))
    key_results = db.relationship(
        "KeyResult", backref="objective", cascade="all, delete-orphan", order_by="KeyResult.position, KeyResult.id"
    )


class KeyResult(db.Model):
    __tablename__ = "key_result"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.ForeignKey("organization.id"), nullable=False, index=True)
    objective_id = db.Column(db.ForeignKey("objective.id"), nullable=False, index=True)
    owner_id = db.Column(db.ForeignKey("user.id"), nullable=True)
    title = db.Column(db.String(255), nullable=False)
    metric_type = db.Column(db.String(10), default="number", nullable=False)
    unit_label = db.Column(db.String(24), default="")   # "DZD", "clients", …
    start_value = db.Column(db.Float, default=0.0, nullable=False)
    target_value = db.Column(db.Float, default=100.0, nullable=False)
    current_value = db.Column(db.Float, default=0.0, nullable=False)
    weight = db.Column(db.Float, default=1.0)
    position = db.Column(db.Integer, default=0)
    kr_type = db.Column(db.String(12), default="increase", nullable=False)
    measure = db.Column(db.String(8), default="latest", nullable=False)
    confidence = db.Column(db.Integer, nullable=True)             # owner's confidence of delivering, 1..10
    justification = db.Column(db.Text, default="")                # why the target is defensible (shown in reports)
    basis = db.Column(db.JSON, nullable=True)                     # how the target was chosen: {"level": "ambitious", "series": id, ...}
    data_period = db.Column(db.Date, nullable=True)               # period of the latest uploaded data this value came from
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now, nullable=False)

    owner = db.relationship("User", foreign_keys=[owner_id])
    factors = db.relationship("KRFactor", backref="key_result", cascade="all, delete-orphan", order_by="KRFactor.id")


class KRFactor(db.Model):
    """A thing OUTSIDE the history that the target depends on (a price rise, a new branch, a signed contract), in the key result's own units."""
    __tablename__ = "kr_factor"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.ForeignKey("organization.id"), nullable=False, index=True)
    key_result_id = db.Column(db.ForeignKey("key_result.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    kind = db.Column(db.String(10), default="other", nullable=False)
    effect = db.Column(db.Float, nullable=False)                  # contribution toward the target, signed toward the goal
    certainty = db.Column(db.String(10), default="probable", nullable=False)
    evidence = db.Column(db.Text, default="")                     # what supports the number (a contract, a quote, a decision…)
    owner_id = db.Column(db.ForeignKey("user.id"), nullable=True)
    status = db.Column(db.String(12), default="planned", nullable=False)     # planned | in_progress | done | dropped
    due = db.Column(db.Date, nullable=True)                                  # when the lever is expected to start paying off
    actual = db.Column(db.Float, nullable=True)                              # the effect it really had, once known (same units as `effect`)
    created_at = db.Column(db.DateTime, default=now, nullable=False)

    owner = db.relationship("User", foreign_keys=[owner_id])


class GoalEvent(db.Model):
    """What happened to a goal besides numbers: a target that was changed (and why) or a decision that was taken (by whom, when)."""
    __tablename__ = "goal_event"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.ForeignKey("organization.id"), nullable=False, index=True)
    objective_id = db.Column(db.ForeignKey("objective.id"), nullable=False, index=True)
    key_result_id = db.Column(db.ForeignKey("key_result.id"), nullable=True)
    kind = db.Column(db.String(10), nullable=False)                           # target | decision
    text = db.Column(db.String(500), default="", nullable=False)
    old_value = db.Column(db.Float, nullable=True)
    new_value = db.Column(db.Float, nullable=True)
    user_id = db.Column(db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=now, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id])


class Indicator(db.Model):
    """A KPI — measured on a regular rhythm against a standing target (no start/end dates)."""

    __tablename__ = "indicator"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.ForeignKey("organization.id"), nullable=False, index=True)
    unit_id = db.Column(db.ForeignKey("org_unit.id"), nullable=True)
    owner_id = db.Column(db.ForeignKey("user.id"), nullable=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    perspective = db.Column(db.String(12))
    metric_type = db.Column(db.String(10), default="number", nullable=False)
    unit_label = db.Column(db.String(24), default="")
    direction = db.Column(db.String(14), default="higher_better", nullable=False)  # or lower_better
    frequency = db.Column(db.String(10), default="monthly", nullable=False)
    baseline_value = db.Column(db.Float)
    target_value = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=now, nullable=False)

    owner = db.relationship("User", foreign_keys=[owner_id])
    unit = db.relationship("OrgUnit", foreign_keys=[unit_id])
    values = db.relationship(
        "IndicatorValue", backref="indicator", cascade="all, delete-orphan", order_by="IndicatorValue.period_date"
    )


class IndicatorValue(db.Model):
    __tablename__ = "indicator_value"
    __table_args__ = (db.UniqueConstraint("indicator_id", "period_date"),)
    id = db.Column(db.Integer, primary_key=True)
    indicator_id = db.Column(db.ForeignKey("indicator.id"), nullable=False, index=True)
    period_date = db.Column(db.Date, nullable=False)   # first day of the measured period
    value = db.Column(db.Float, nullable=False)
    note = db.Column(db.String(255), default="")
    created_at = db.Column(db.DateTime, default=now, nullable=False)
