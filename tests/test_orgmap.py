from datetime import date, timedelta

from tests.test_compose import _ready
from tests.test_data_flow import owner  # noqa: F401

END = (date.today() + timedelta(days=300)).isoformat()


def test_map_page_and_svg(app, owner):
    c, slug = owner
    assert "لا توجد أهداف فعّالة" in c.get(f"/app/{slug}/map/").get_data(as_text=True)   # empty state works
    sid = _ready(app, c, slug)
    c.post(f"/app/{slug}/goals/compose", data={"series": sid, "target": "999999999", "end": END, "title": "رفع المبيعات", "lever_title": ["فرع"], "lever_effect": ["5"],
                                                "lever_certainty": ["hoped"], "commitment": "committed"})
    page = c.get(f"/app/{slug}/map/").get_data(as_text=True)
    assert "رفع المبيعات" in page and "data-journey" in page and "data-jr-data" in page and "journey.js" in page
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
    c.post(f"/app/{slug}/goals/compose", data={"series": sid, "target": "999999999", "end": END, "title": "رفع المبيعات", "commitment": "committed"})
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
    c.post(f"/app/{slug}/goals/compose", data={"series": sid, "target": "999999999", "end": END, "title": "رفع المبيعات", "commitment": "committed"})
    r = c.post(f"/app/{slug}/map/compose", data={"family": "tree"}, follow_redirects=True)
    assert r.status_code == 200 and "data-journey" in r.get_data(as_text=True)


def test_journey_payload_carries_real_links(app, owner):
    """The page draws from one JSON document: goals with status/progress/expected, alignment parents and shared data series — nothing invented."""
    import json, re
    c, slug = owner
    sid = _ready(app, c, slug)
    c.post(f"/app/{slug}/goals/compose", data={"series": sid, "target": "999999999", "end": END, "title": "رفع المبيعات", "commitment": "committed"})
    page = c.get(f"/app/{slug}/map/").get_data(as_text=True)
    data = json.loads(re.search(r'data-jr-data>(.*?)</script>', page, re.S).group(1))
    assert data["goals"] and data["goals"][0]["title"] == "رفع المبيعات"
    g = data["goals"][0]
    assert {"status", "progress", "expected", "krs", "url", "parent"} <= set(g) and 0 <= g["progress"] <= 100
    assert data["i18n"]["status"]["on_track"] and "org" in data and "shares" in data
    assert "controls" not in page and 'data-act="play"' not in page                      # no player: the picture is always whole
