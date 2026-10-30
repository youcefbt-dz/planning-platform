from flask import url_for

from app.core.modules import Hit
from app.modules.goals.models import Indicator, KeyResult, Objective


def search_provider(org, q: str, limit: int):
    like = f"%{q}%"
    hits = []
    for o in Objective.query.filter(Objective.org_id == org.id, Objective.title.ilike(like)).limit(limit).all():
        hits.append(Hit("objective", o.id, o.title, o.cycle.name if o.cycle else "", url_for("goals.detail", id=o.id), "target-arrow"))
    for k in KeyResult.query.filter(KeyResult.org_id == org.id, KeyResult.title.ilike(like)).limit(limit).all():
        hits.append(Hit("key_result", k.id, k.title, k.objective.title, url_for("goals.detail", id=k.objective_id) + f"#kr-{k.id}", "flag"))
    for i in Indicator.query.filter(Indicator.org_id == org.id, Indicator.name.ilike(like)).limit(limit).all():
        hits.append(Hit("indicator", i.id, i.name, i.perspective or "", url_for("goals.indicator_detail", id=i.id), "chart-line"))
    return hits
