"""Upload -> read like a spreadsheet -> answer the AI's questions -> confirm -> series -> reality check -> goals."""
import io
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.core.models import Link
from app.extensions import db
from app.modules.data.models import Dataset, Series
from tests.conftest import register

END = (date.today() + timedelta(days=300)).isoformat()
SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def sample(name):
    return (io.BytesIO((SAMPLES / name).read_bytes()), name)


@pytest.fixture()
def owner(app, client):
    r = register(client)
    assert r.status_code == 302
    return client, r.headers["Location"].split("/app/")[1].split("/")[0]


def upload(c, slug, name):
    return c.post(f"/app/{slug}/data/upload", data={"file": sample(name)}, content_type="multipart/form-data")


def test_data_intake_shows_illustrative_erp_systems_instead_of_sample_card(app, owner):
    c, slug = owner
    page = c.get(f"/app/{slug}/data/").get_data(as_text=True)
    assert 'data-kind="integrations"' in page
    assert "Odoo" in page and "Sage 100" in page and "SAP" in page
    assert "المبيعات" in page and "المخزون" in page and "المحاسبة" in page
    assert "لا يوجد اتصال فعلي" in page
    assert "نموذج جاهز" not in page


def test_long_file_upload_map_confirm(app, owner):
    c, slug = owner
    r = upload(c, slug, "sales_by_branch.xlsx")
    assert r.status_code == 302 and r.headers["Location"].endswith("/map")
    page = c.get(r.headers["Location"] + "").get_data(as_text=True)
    assert 'class="grid"' in page and "صفًّا إضافيًّا" in page   # the spreadsheet, its header row, a window onto long files
    ds_id = int(r.headers["Location"].split("/")[-2])
    assert c.post(f"/app/{slug}/data/{ds_id}/confirm").status_code == 302
    with app.app_context():
        ds = db.session.get(Dataset, ds_id)
        assert ds.status == "ready" and any(s.dimension is None for s in ds.series) and any(s.dimension for s in ds.series)


def test_answering_a_question_changes_the_column_and_removes_the_question(app, owner):
    c, slug = owner
    r = upload(c, slug, "المبيعات_والموظفون.xlsx")
    ds_id = int(r.headers["Location"].split("/")[-2])
    with app.app_context():
        qs = db.session.get(Dataset, ds_id).questions
    assert qs, "the cryptic Arabic headers must raise questions"
    col = qs[0]["column"]
    r = c.post(f"/app/{slug}/data/{ds_id}/column/{col}", data={"option": 0}, headers={"X-Requested-With": "fetch", "Accept": "application/json"})
    body = r.get_json()
    assert r.status_code == 200 and body["column"]["state"] == "user" and body["column"]["confidence"] == 1.0
    with app.app_context():
        ds = db.session.get(Dataset, ds_id)
        assert col not in [q["column"] for q in ds.questions]


def test_confirm_needs_a_date_and_a_number(app, owner):
    c, slug = owner
    r = upload(c, slug, "sales_by_branch.xlsx")
    ds_id = int(r.headers["Location"].split("/")[-2])
    with app.app_context():
        ds = db.session.get(Dataset, ds_id)
        for col in [c_ for c_ in ds.columns if c_["role"] == "date"]:
            from app.modules.data import service
            service.edit_column(ds, col["index"], role="ignore")
        db.session.commit()
    r = c.post(f"/app/{slug}/data/{ds_id}/confirm", follow_redirects=True)
    assert "عمودًا واحدًا على أنه التاريخ" in r.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(Dataset, ds_id).status == "draft"


def test_reading_options_reanalyse_the_file(app, owner):
    c, slug = owner
    r = upload(c, slug, "ventes_2025_mensuel.xlsx")
    ds_id = int(r.headers["Location"].split("/")[-2])
    page = c.get(f"/app/{slug}/data/{ds_id}/map").get_data(as_text=True)
    assert "مجموع، مُهمَل" in page and "الأشهر موزعة على الأعمدة" in page           # the formula Total row is struck out in the sheet
    assert c.post(f"/app/{slug}/data/{ds_id}/analyze", data={"year": 2024}).status_code == 302
    with app.app_context():
        ds = db.session.get(Dataset, ds_id)
        assert ds.layout == "wide"


def test_bad_uploads_are_refused_politely(app, owner):
    c, slug = owner
    r = c.post(f"/app/{slug}/data/upload", data={"file": (io.BytesIO(b"hello"), "notes.docx")}, content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200 and "نوع الملف غير مدعوم" in r.get_data(as_text=True)
    r = c.post(f"/app/{slug}/data/upload", data={}, content_type="multipart/form-data", follow_redirects=True)
    assert "اختر ملفًا أولًا" in r.get_data(as_text=True)


def test_files_and_series_are_private_to_their_organization(app, client):
    register(client, "a@example.com", "Org A")
    r = client.post("/app/org-a/data/upload", data={"file": sample("sales_by_branch.xlsx")}, content_type="multipart/form-data")
    ds_id = int(r.headers["Location"].split("/")[-2])
    client.post(f"/app/org-a/data/{ds_id}/confirm")
    client.post("/logout")
    other = app.test_client()
    register(other, "b@example.com", "Org B")
    assert other.get(f"/app/org-b/data/{ds_id}").status_code == 404
    assert other.get(f"/app/org-b/data/{ds_id}/map").status_code == 404
    with app.app_context():
        sid = Series.query.first().id
    assert other.get(f"/app/org-b/data/series/{sid}").status_code == 404
    assert other.get(f"/app/org-b/data/reality/check?series={sid}&target=1&end=2099-01-01").status_code == 200   # no leak: it renders the "not found" panel
    assert "اختر إحدى سلاسلك".encode() in other.get(f"/app/org-b/data/reality/check?series={sid}&target=1&end=2099-01-01").data


def test_viewers_cannot_upload(app, demo):
    c = app.test_client()
    r = c.post("/app/demo/data/upload", data={"file": sample("sales_by_branch.xlsx")}, content_type="multipart/form-data")
    assert r.status_code in (302, 401, 403)
    assert c.get("/app/demo/data/").status_code == 200


def test_demo_has_data_and_its_goals_are_checked_against_it(app, demo):
    c = app.test_client()
    page = c.get("/app/demo/data/").get_data(as_text=True)
    assert "بيانات التشغيل الشهرية" in page
    from app.modules.data.models import Dataset
    with app.app_context():
        ds_id = Dataset.query.first().id
    assert "هامش الربح الإجمالي" in c.get(f"/app/demo/data/{ds_id}").get_data(as_text=True)
    with app.app_context():
        assert Link.query.filter_by(kind="measured_by").count() == 3          # three key results per demo organization
    goals = c.get("/app/demo/goals/").get_data(as_text=True)
    assert goals
    from app.modules.goals.models import Objective
    with app.app_context():
        oid = Objective.query.filter_by(org_id=Objective.query.filter(Objective.title == "تشغيل أسرع وأكثر موثوقية").first().org_id).first().id
    html = c.get(f"/app/demo/goals/{oid}").get_data(as_text=True)
    assert 'title="افتح فحص الواقعية لهذه النتيجة الرئيسية"' in html


def test_reality_endpoint_returns_a_verdict_fragment_and_never_calls_a_cloud_model_for_demo(app, demo):
    c = app.test_client()
    with app.app_context():
        sid = Series.query.filter(Series.name == "هامش الربح الإجمالي %", Series.dimension.is_(None)).first().id
    html = c.get(f"/app/demo/data/reality/check?series={sid}&target=40&end={END}").get_data(as_text=True)
    assert "غير واقعي" in html and "<svg" in html and "اطلب من الذكاء الاصطناعي الشرح" in html
    html = c.get(f"/app/demo/data/reality/check?series={sid}&target=28&end={END}&ai=1").get_data(as_text=True)
    assert "القواعد المدمجة" in html


def test_reality_asks_for_missing_input_instead_of_failing(app, demo):
    c = app.test_client()
    assert c.get("/app/demo/data/reality/check").status_code == 200
    assert c.get("/app/demo/data/reality/check?series=999&target=1&end=2099-01-01").status_code == 200
    with app.app_context():
        sid = Series.query.filter(Series.name == "هامش الربح الإجمالي %", Series.dimension.is_(None)).first().id
    assert "بعد اليوم".encode() in c.get(f"/app/demo/data/reality/check?series={sid}&target=1&end=2001-01-01").data


def test_key_result_gets_linked_to_a_series_from_the_goal_form(app, owner):
    c, slug = owner
    r = upload(c, slug, "sales_by_branch.xlsx")
    ds_id = int(r.headers["Location"].split("/")[-2])
    c.post(f"/app/{slug}/data/{ds_id}/confirm")
    with app.app_context():
        sid = Series.query.filter_by(dimension=None).first().id
    r = c.post(f"/app/{slug}/goals/new", data={"title": "Grow", "kr_title": ["Revenue", "", ""], "kr_start": ["1", "", ""], "kr_target": ["2", "", ""],
                                               "kr_unit": ["", "", ""], "kr_series": [str(sid), "", ""], "end_date": "2099-12-31"})
    assert r.status_code == 302
    with app.app_context():
        l = Link.query.filter_by(kind="measured_by").one()
        assert l.target_id == sid
    # removing the dataset removes the link, not the goal
    c.post(f"/app/{slug}/data/{ds_id}/delete")
    with app.app_context():
        assert Link.query.filter_by(kind="measured_by").count() == 0
        from app.modules.goals.models import KeyResult
        assert KeyResult.query.count() == 1


def test_indicator_tracks_confirmed_data_and_can_return_to_manual_mode(app, owner):
    c, slug = owner
    r = upload(c, slug, "sales_by_branch.xlsx")
    ds_id = int(r.headers["Location"].split("/")[-2])
    c.post(f"/app/{slug}/data/{ds_id}/confirm")
    with app.app_context():
        source = Series.query.filter_by(dimension=None).first()
        sid = source.id
        initial_latest = source.latest[1]

    created = c.post(f"/app/{slug}/goals/indicators/new", data={
        "name": "Sales KPI", "target_value": "9999", "baseline_value": "100",
        "metric_type": "number", "unit_label": "DZD", "direction": "higher_better",
        "frequency": "monthly", "series_id": str(sid),
    })
    assert created.status_code == 302
    indicator_id = int(created.headers["Location"].rstrip("/").split("/")[-1])

    with app.app_context():
        from app.modules.goals.models import Indicator, IndicatorValue
        ind = db.session.get(Indicator, indicator_id)
        values = IndicatorValue.query.filter_by(indicator_id=indicator_id).order_by(IndicatorValue.period_date).all()
        assert Link.query.filter_by(org_id=ind.org_id, source_type="indicator", source_id=indicator_id,
                                    target_type="series", target_id=sid, kind="measured_by").count() == 1
        assert values and values[-1].value == initial_latest
        assert all(v.note == f"@data:{sid}" for v in values)

        source = db.session.get(Series, sid)
        changed_latest = initial_latest + 25
        source.points = [*source.points[:-1], [source.points[-1][0], changed_latest]]
        from flask import current_app
        current_app.extensions["modules"].hook("series.updated", series=[source], user_id=None)
        db.session.flush()
        values = IndicatorValue.query.filter_by(indicator_id=indicator_id).order_by(IndicatorValue.period_date).all()
        assert values[-1].value == changed_latest

    edited = c.post(f"/app/{slug}/goals/indicators/{indicator_id}/edit", data={
        "name": "Sales KPI", "target_value": "9999", "baseline_value": "100",
        "metric_type": "number", "unit_label": "DZD", "direction": "higher_better",
        "frequency": "monthly", "series_id": "",
    })
    assert edited.status_code == 302
    with app.app_context():
        from app.modules.goals.models import IndicatorValue
        assert not IndicatorValue.query.filter_by(indicator_id=indicator_id).filter(IndicatorValue.note.like("@data:%")).count()

    recorded = c.post(f"/app/{slug}/goals/indicators/{indicator_id}/value", data={
        "value": "123", "period_date": date.today().replace(day=1).isoformat(),
    })
    assert recorded.status_code == 302
    with app.app_context():
        row = IndicatorValue.query.filter_by(indicator_id=indicator_id).one()
        assert row.value == 123 and not row.note.startswith("@data:")


def test_ai_settings_page_and_consent_switch(app, owner, monkeypatch):
    c, slug = owner
    page = c.get(f"/app/{slug}/settings/ai").get_data(as_text=True)
    assert "القواعد المدمجة" in page and "لم يُعدّ أي نموذج سحابي" in page
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    page = c.get(f"/app/{slug}/settings/ai").get_data(as_text=True)
    assert "ai_consent" in page
    c.post(f"/app/{slug}/settings/ai", data={"ai_consent": "on"})
    with app.app_context():
        from app.core.models import Organization
        assert Organization.query.filter_by(slug=slug).one().settings["ai_consent"] is True
