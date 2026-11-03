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


def test_briefing_report_contains_the_executive_report_and_strategy_map(app, owner):
    c, slug = owner
    sid = _ready(app, c, slug)
    c.post(f"/app/{slug}/goals/compose", data={"series": sid, "target": "999999999", "end": END,
            "title": "رفع المبيعات", "commitment": "committed", "do": "save"})
    r = c.get(f"/app/{slug}/reports/briefing")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "ir-cover" in html and "ir-executive" in html and "ir-method" in html
    assert "نطاق التقرير ومصادر الأرقام" in html
    assert "omap" in html and "التقرير المؤسسي" in html and "رفع المبيعات" in html
    assert "خط الأساس" in html and "المخطط الاستراتيجي" in html
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


def test_spoken_map_briefing_uses_real_goals_and_can_focus_one_goal(app, owner, monkeypatch):
    import json, re
    from app import ai
    from app.ai.base import AIResult
    from app.ai.tasks.explain_journey import task as explain_task

    c, slug = owner
    sid = _ready(app, c, slug)
    c.post(f"/app/{slug}/goals/compose", data={"series": sid, "target": "999999999", "end": END,
            "title": "رفع المبيعات", "commitment": "committed", "do": "save"})
    page = c.get(f"/app/{slug}/map/").get_data(as_text=True)
    data = json.loads(re.search(r'data-jx-data>(.*?)</script>', page, re.S).group(1))
    goal_id = data["goals"][0]["id"]

    def offline_result(name, inputs, lang=None):
        assert name == "explain_journey"
        return AIResult(data=explain_task.fallback(inputs, lang or "ar"), provider="offline")

    monkeypatch.setattr(ai, "run", offline_result)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    response = c.post(f"/app/{slug}/map/explain", json={})
    assert response.status_code == 200
    briefing = response.get_json()
    assert briefing["segments"][0]["kind"] == "org"
    assert briefing["segments"][-1]["kind"] == "org"
    assert any(x["kind"] == "goal" and x["id"] == goal_id for x in briefing["segments"])
    assert briefing["tts_available"] is False

    focused = c.post(f"/app/{slug}/map/explain", json={"focus": {"kind": "goal", "id": goal_id}})
    assert focused.status_code == 200
    segments = focused.get_json()["segments"]
    assert segments[1]["kind"] == "goal" and segments[1]["id"] == goal_id


def test_spoken_map_audio_endpoint_requires_organization_ai_consent(app, owner, monkeypatch):
    c, slug = owner
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    response = c.post(f"/app/{slug}/map/speech", json={"token": "not-a-valid-token", "voice": "fahad"})
    assert response.status_code == 403


def test_spoken_map_question_returns_a_grounded_answer_for_audio(app, owner, monkeypatch):
    import json, re
    from app import ai
    from app.ai.base import AIResult
    from app.ai.tasks.ask_journey import task as ask_task

    c, slug = owner
    sid = _ready(app, c, slug)
    c.post(f"/app/{slug}/goals/compose", data={"series": sid, "target": "999999999", "end": END,
            "title": "رفع المبيعات", "commitment": "committed", "do": "save"})
    page = c.get(f"/app/{slug}/map/").get_data(as_text=True)
    data = json.loads(re.search(r'data-jx-data>(.*?)</script>', page, re.S).group(1))
    goal = data["goals"][0]

    def offline_answer(name, inputs, lang=None):
        assert name == "ask_journey"
        return AIResult(data=ask_task.fallback(inputs, lang or "ar"), provider="offline")

    monkeypatch.setattr(ai, "run", offline_answer)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    response = c.post(f"/app/{slug}/map/ask", json={"question": "ما وضع هدف رفع المبيعات؟"})
    assert response.status_code == 200
    answer = response.get_json()
    assert answer["segment"]["kind"] == "goal"
    assert answer["segment"]["id"] == goal["id"]
    assert "رفع المبيعات" in answer["segment"]["text"]
    assert answer["parts"] and answer["tts_available"] is False
    assert c.post(f"/app/{slug}/map/ask", json={"question": " "}).status_code == 400
