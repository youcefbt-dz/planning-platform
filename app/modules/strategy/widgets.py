from app.modules.strategy.models import FoundationItem, Priority


def foundation_loader(org) -> dict:
    rows = {k: FoundationItem.query.filter_by(org_id=org.id, kind=k).first() for k in ("vision", "mission")}
    values = FoundationItem.query.filter_by(org_id=org.id, kind="value").order_by(FoundationItem.position).all()
    return {
        "vision": rows["vision"].text if rows["vision"] else "",
        "mission": rows["mission"].text if rows["mission"] else "",
        "values": values,
        "priorities": Priority.query.filter_by(org_id=org.id).count(),
    }
