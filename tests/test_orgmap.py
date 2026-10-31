from datetime import date, timedelta

from tests.test_compose import _ready
from tests.test_data_flow import owner  # noqa: F401

END = (date.today() + timedelta(days=300)).isoformat()


def test_map_page_and_svg(app, owner):
    c, slug = owner
    assert "لا توجد أهداف فعّالة" in c.get(f"/app/{slug}/map/").get_data(as_text=True)   # empty state works
    sid = _ready(app, c, slug)
    c.post(f"/app/{slug}/goals/compose", data={"series": sid, "target": "999999999", "end": END, "title": "رفع المبيعات", "lever_title": ["فرع"], "lever_effect": ["5"],
                                                "lever_certainty": ["hoped"], "commitment": "committed", "do": "save"})
    page = c.get(f"/app/{slug}/map/").get_data(as_text=True)
    assert "رفع المبيعات" in page and "data-journey" in page and "data-jx-data" in page and "journey.js" in page
    r = c.get(f"/app/{slug}/map/export.svg")
    assert r.status_code == 200 and r.mimetype == "image/svg+xml" and b"<svg" in r.data and "رفع المبيعات".encode() in r.data


def test_briefing_report_starts_with_the_map(app, owner):
    c, slug = owner
    r = c.get(f"/app/{slug}/reports/briefing")
    assert r.status_code == 200 and "cover" in r.get_data(as_text=True) and "omap" in r.get_data(as_text=True)
    assert c.get(f"/app/{slug}/reports/briefing.csv").status_code == 404


def test_journey_spec_is_checked_against_the_facts(app, owner):
    from flask import g  # noqa: F401
    from app.modules.orgmap import facts as FA, spec as SP, render as RN
    from app.core.models import Organization
    c, slug = owner
    sid = _ready(app, c, slug)
    c.post(f"/app/{slug}/goals/compose", data={"series": sid, "target": "999999999", "end": END, "title": "رفع المبيعات", "commitment": "committed", "do": "save"})
    with app.test_request_context():
        org = Organization.query.filter_by(slug=slug).first()
        f = FA.collect(org)
        assert f["goals"] and f["nodes"]["org"]["type"] == "org"
        d = SP.default(f, "route")
        assert SP.validate(d, f)["family"] == "route"
        import pytest
        with pytest.raises(ValueError):
            SP.validate({"family": "route", "steps": [{"show": ["goal:999999"]}], "title": "x"}, f)
        for fam in SP.families():
            comp = RN.compose(f, SP.default(f, fam))
            svg = RN.svg(comp, standalone=True)
            assert svg.startswith("<?xml") and "<svg" in svg and len(comp["steps"]) >= 2


def test_compose_switches_family_without_ai(app, owner):
    c, slug = owner
    sid = _ready(app, c, slug)
    c.post(f"/app/{slug}/goals/compose", data={"series": sid, "target": "999999999", "end": END, "title": "رفع المبيعات", "commitment": "committed", "do": "save"})
    r = c.post(f"/app/{slug}/map/compose", data={"family": "tree"}, follow_redirects=True)
    assert r.status_code == 200 and "data-journey" in r.get_data(as_text=True)


def test_map_payload_carries_departments_heads_and_real_dependencies(app, owner):
    """The page draws from one JSON document: departments with their heads, goals with status/progress/expected, and the real depends_on links — nothing invented."""
    import json, re
    from app.core.models import Link, Membership, Organization, OrgUnit, User
    from app.extensions import db
    from app.modules.goals.models import Objective
    c, slug = owner
    sid = _ready(app, c, slug)
    for title in ("رفع المبيعات", "تسريع التسليم"):
        c.post(f"/app/{slug}/goals/compose", data={"series": sid, "target": "999999999", "end": END, "title": title, "commitment": "committed", "do": "save"})
    with app.app_context():
        org = Organization.query.filter_by(slug=slug).first()
        root = OrgUnit.query.filter_by(org_id=org.id, kind="company").first()
        sales = OrgUnit(org_id=org.id, name="المبيعات", kind="department", parent_id=root.id)
        db.session.add(sales); db.session.flush()
        head = Membership.query.filter_by(org_id=org.id).first()
        head.title = "مدير المبيعات"; sales.head_id = head.user_id; head.unit_id = sales.id
        a, b = Objective.query.filter_by(org_id=org.id).order_by(Objective.id).all()[:2]
        a.unit_id = sales.id
        db.session.add(Link(org_id=org.id, source_type="objective", source_id=a.id, target_type="objective", target_id=b.id, kind="depends_on"))
        db.session.commit()
        a_id, b_id, head_name = a.id, b.id, head.user.name
    page = c.get(f"/app/{slug}/map/").get_data(as_text=True)
    data = json.loads(re.search(r'data-jx-data>(.*?)</script>', page, re.S).group(1))
    unit = [u for u in data["units"] if u["name"] == "المبيعات"][0]
    assert unit["head"]["name"] == head_name and unit["head"]["title"] == "مدير المبيعات" and unit["head"]["initials"]
    g = [x for x in data["goals"] if x["id"] == f"goal:{a_id}"][0]
    assert g["unit"] == unit["id"] and {"status", "progress", "expected", "krs", "url", "parent"} <= set(g) and 0 <= g["progress"] <= 100
    assert data["deps"] == [{"from": f"goal:{a_id}", "to": f"goal:{b_id}"}]            # `from` depends on `to`
    assert data["i18n"]["status"]["on_track"] and "org" in data
    assert 'data-act="play"' not in page                                               # no player: the picture is always whole, on open space
