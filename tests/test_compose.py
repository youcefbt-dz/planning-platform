"""The goal composer: series + target + date -> verdict -> levers -> a saved goal linked to its series, with levers recorded."""
from datetime import date, timedelta

from app.extensions import db
from app.modules.data.models import Series
from app.modules.goals.models import KRFactor, KeyResult, Objective
from tests.test_data_flow import owner, upload  # noqa: F401

END = (date.today() + timedelta(days=300)).isoformat()


def _ready(app, c, slug):
    r = upload(c, slug, "sales_by_branch.xlsx")
    ds_id = int(r.headers["Location"].split("/")[-2])
    c.post(f"/app/{slug}/data/{ds_id}/confirm")
    with app.app_context():
        return Series.query.filter_by(dimension=None).first().id


def test_new_with_series_goes_to_composer_and_shows_verdict(app, owner):
    c, slug = owner
    sid = _ready(app, c, slug)
    r = c.get(f"/app/{slug}/goals/new?series={sid}")
    assert r.status_code == 302 and "/goals/compose" in r.headers["Location"]
    page = c.get(f"/app/{slug}/goals/compose?series={sid}&target=999999999&end_date={END}").get_data(as_text=True)
    assert "verdict" in page and "lever_title" in page


def test_saving_creates_goal_with_linked_series_and_levers(app, owner):
    c, slug = owner
    sid = _ready(app, c, slug)
    r = c.post(f"/app/{slug}/goals/compose", data={"series": sid, "target": "999999999", "end_date": END, "title": "رفع المبيعات", "lever_title": ["فرع جديد", ""],
                                                    "lever_effect": ["500", ""], "lever_certainty": ["probable", "hoped"], "commitment": "committed", "do": "save"})
    assert r.status_code == 302 and "/goals/" in r.headers["Location"]
    with app.app_context():
        o = Objective.query.one()
        kr = KeyResult.query.filter_by(objective_id=o.id).one()
        assert kr.target_value == 999999999 and KRFactor.query.filter_by(key_result_id=kr.id).count() == 1
        from app.modules.data import service
        assert service.linked_series_id(kr.org_id, kr.id) == sid


def test_incomplete_post_creates_nothing(app, owner):
    c, slug = owner
    sid = _ready(app, c, slug)
    c.post(f"/app/{slug}/goals/compose", data={"series": sid, "title": "x", "do": "save"})
    with app.app_context():
        assert Objective.query.count() == 0


def test_goal_outside_the_data_is_allowed(app, owner):
    c, slug = owner
    page = c.get(f"/app/{slug}/goals/new", follow_redirects=True).get_data(as_text=True)
    assert 'name="name"' in page
    r = c.post(f"/app/{slug}/goals/compose", data={"source": "manual", "name": "رضا الزبائن", "unit": "%", "start": "70", "target": "85", "end_date": END,
                                                    "title": "بلوغ رضا 85٪", "commitment": "committed", "do": "save"})
    assert r.status_code == 302
    with app.app_context():
        kr = KeyResult.query.one()
        assert kr.start_value == 70 and kr.target_value == 85 and kr.unit_label == "%"


def test_goal_page_shows_path_levers_and_history(app, owner):
    c, slug = owner
    sid = _ready(app, c, slug)
    c.post(f"/app/{slug}/goals/compose", data={"series": sid, "target": "999999999", "end_date": END, "title": "رفع", "lever_title": ["فرع جديد"], "lever_effect": ["500"],
                                                "lever_certainty": ["probable"], "commitment": "committed", "do": "save"})
    with app.app_context():
        o = Objective.query.one()
        oid, krid = o.id, KeyResult.query.one().id
        fid = KRFactor.query.one().id
    page = c.get(f"/app/{slug}/goals/{oid}").get_data(as_text=True)
    assert "pathc__svg" in page and "tl2" in page and "kj" in page
    assert c.post(f"/app/{slug}/goals/factor/{fid}/update", data={"status": "done", "actual": "300"}).status_code == 302
    assert c.post(f"/app/{slug}/goals/{oid}/decision", data={"text": "تأجيل الفرع"}).status_code == 302
    c.post(f"/app/{slug}/goals/kr/{krid}/edit", data={"title": "x", "target_value": "888", "start_value": "1", "reason": "السوق تغيّر"})
    from app.modules.goals.models import GoalEvent
    with app.app_context():
        assert KRFactor.query.one().status == "done" and KRFactor.query.one().actual == 300
        kinds = sorted((e.kind, e.text) for e in GoalEvent.query.all())
        assert ("decision", "تأجيل الفرع") in kinds and ("target", "السوق تغيّر") in kinds
    assert "تأجيل الفرع" in c.get(f"/app/{slug}/goals/{oid}").get_data(as_text=True)
