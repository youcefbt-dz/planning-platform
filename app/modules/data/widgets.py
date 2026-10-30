from __future__ import annotations

from app.modules.data.models import Dataset
from app.modules.data.service import org_series


def data_loader(org) -> dict:
    series = org_series(org.id)
    drafts = Dataset.query.filter_by(org_id=org.id, status="draft").count()
    return {"count": len(series), "series": series[:5], "drafts": drafts, "datasets": Dataset.query.filter_by(org_id=org.id, status="ready").count()}
