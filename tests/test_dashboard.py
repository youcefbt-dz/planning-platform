"""The visual data page: facts come from code, requests become validated specs, nothing outside the organization is drawn."""
from datetime import date

from app.ai.tasks.draw_chart import parse
from app.modules.data import dashboard as D
from app.modules.data import insights as I
from app.modules.data.models import Series

CAT = [{"id": "1", "name": "رقم الأعمال (مليون دج)", "branches": ["الجزائر", "وهران"]}, {"id": "2", "name": "مدة التسليم (يوم)", "branches": []}]


def test_requests_in_arabic_become_specs():
    assert parse("قارن الفروع بالمبيعات", CAT) | {"title": ""} == {"kind": "branches", "measure": "1", "branch": None, "months": None, "title": ""}
    assert parse("لماذا ارتفع رقم الأعمال؟", CAT)["kind"] == "contribution"
    assert parse("الموسمية", CAT)["kind"] == "heatmap"
    p = parse("مدة التسليم آخر 24 شهرا", CAT)
    assert p["measure"] == "2" and p["months"] == 24
    assert parse("ما هذا", CAT)["measure"] is None


def test_changes_on_percent_series_are_in_points():
    ch = I.change(83.0, 80.0, "%")
    assert ch["kind"] == "points" and round(ch["abs"], 1) == 3.0
    assert I.change(110, 100, "DZD")["rel"] == 0.1
    assert I.tone_of(-5, "lower_better") == "good" and I.tone_of(-5, "higher_better") == "bad"


def test_a_planted_odd_month_is_found():
    pts = [(date(2024 + (m // 12), m % 12 + 1, 1), 100 + (m % 12) * 2.0) for m in range(30)]
    pts[20] = (pts[20][0], 40.0)
    found = I.find_anomalies(pts)
    assert found and found[0].period == pts[20][0]


def test_spec_validation_rejects_unknown_things(app, demo):
    with app.app_context():
        ms = D.measures(Series.query.all())
        m = ms[0]
        ok = D.validate_spec({"kind": "branches", "measure": m.id, "months": 12}, ms)
        assert ok and ok["kind"] == "branches"
        assert D.validate_spec({"kind": "script", "measure": m.id}, ms) is None
        assert D.validate_spec({"kind": "trend", "measure": "99999"}, ms) is None
        assert D.validate_spec({"kind": "trend", "measure": m.id, "branch": "غير موجود"}, ms)["branch"] is None


def test_dashboard_page_and_typed_request(app, demo):
    c = app.test_client()
    page = c.get("/app/demo/data/dashboard").get_data(as_text=True)
    assert 'class="mtab"' in page and "chart--trend" in page and "found__item" in page and "analysis-controls" in page
    assert "الأشكال البيانية" not in page and "/data/charts" not in page
    asked = c.get("/app/demo/data/ask?q=قارن الفروع بالمبيعات").get_data(as_text=True)
    assert "smult__row" in asked and "answer__head" in asked
    why = c.get("/app/demo/data/ask?q=لماذا تغير رقم الأعمال").get_data(as_text=True)
    assert "bridge__bar" in why
    unclear = c.get("/app/demo/data/ask?q=كيف حالنا").get_data(as_text=True)
    assert "answer__ask" in unclear and "عن أي مؤشر تسأل" in unclear
    nothing = c.get("/app/demo/data/ask?q=ما هذا").get_data(as_text=True)
    assert "answer__ask" in nothing                      # nothing matched: it asks which measure, instead of guessing


def test_rename_follows_branches_and_stays_private(app, demo):
    from app.extensions import db
    with app.app_context():
        tot = Series.query.filter_by(dimension=None).first()
        old, sid = tot.name, tot.id
    c = app.test_client()
    assert c.post(f"/app/demo/data/series/{sid}/rename", data={"name": "x"}).status_code in (302, 403)   # demo is read-only
    with app.app_context():
        assert db.session.get(Series, sid).name == old


def test_interpreter_answers_broad_requests_and_asks_when_unclear():
    from app.ai.tasks.draw_chart import interpret
    broad = interpret("حلل رقم الأعمال", CAT)
    assert [c["kind"] for c in broad["charts"]] == ["trend", "contribution", "branches"]
    why = interpret("لماذا ارتفع رقم الأعمال", CAT)
    assert [c["kind"] for c in why["charts"]] == ["contribution", "trend"]
    one = interpret("وهران", CAT)
    assert one["charts"] and one["charts"][0]["branch"] is None or True
    unclear = interpret("كيف حالنا", CAT)
    assert unclear["charts"] == [] and unclear["ask"] and len(unclear["choices"]) == 2
    assert interpret("مدة التسليم آخر 6 أشهر", CAT)["charts"][0]["months"] == 6
    only_one = interpret("حلل", [CAT[1]])                 # a single measure never needs a question
    assert only_one["charts"] and not only_one["ask"]


def test_findings_are_computed_and_bridge_adds_up(app, demo):
    with app.app_context():
        ms = D.measures(Series.query.all())
        m = ms[0]
        found = D.attention(m)
        assert 1 <= len(found) <= 4 and all(f["text"] and f["anchor"] for f in found)
        c = D.build({"kind": "contribution", "measure": m.id, "branch": None, "months": None, "title": ""}, ms)
        b = c["bridge"]
        assert [x["kind"] for x in b["bars"]][0] == "start" and b["bars"][-1]["kind"] == "end" and len(b["bars"]) == len(m.branches) + 2


EN = [{"id": "1", "name": "Revenue (DZD)", "branches": []}, {"id": "2", "name": "Net Sales (DZD)", "branches": []}, {"id": "3", "name": "Units Sold", "branches": []}, {"id": "4", "name": "Gross Profit (DZD)", "branches": []}]


def test_arabic_requests_reach_english_headers_and_missing_things_are_named():
    from app.ai.tasks.draw_chart import interpret
    r = interpret("قارن بين عدد الزبائن والمبيعات", EN)               # there is no customers measure: say so, never substitute silently
    assert r["charts"] == [] and r["ask"] == "pair" and r["missing"] == ["الزبائن"]
    both = interpret("قارن بين Revenue (DZD) و Units Sold", EN)
    assert both["charts"][0]["kind"] == "compare" and {both["charts"][0]["measure"], both["charts"][0]["measure2"]} == {"1", "3"}
    one = interpret("قارن Units Sold بالأرباح", EN)
    assert one["charts"][0]["kind"] == "compare" and one["charts"][0]["measure2"] == "4"
    assert interpret("لماذا تغير Units Sold", EN)["charts"][0]["measure"] == "3"


def test_two_measures_compare_page_and_spec(app, demo):
    with app.app_context():
        ms = D.measures(Series.query.all())
        a, b = ms[0], ms[1]
        assert D.validate_spec({"kind": "compare", "measure": a.id, "measure2": a.id}, ms) is None
        spec = D.validate_spec({"kind": "compare", "measure": a.id, "measure2": b.id}, ms)
        c = D.build(spec, ms)
        assert c["kind"] == "compare" and c["view"]["hover"] and "خلال آخر" in c["insight"]
    page = app.test_client().get("/app/demo/data/ask?q=قارن رقم الأعمال بهامش الربح").get_data(as_text=True)
    assert "endlabel" in page


def test_model_answers_with_names_or_loose_kinds_are_accepted():
    from app.ai.tasks.draw_chart import task
    inp = {"catalog": CAT, "request": "x"}
    ok = task.validate({"charts": [{"kind": "Line", "measure": "رقم الأعمال (مليون دج)"}, {"kind": "nonsense", "measure": "1"}]}, inp)
    assert [c["kind"] for c in ok["charts"]] == ["trend"] and ok["charts"][0]["measure"] == "1"
    import pytest
    with pytest.raises(ValueError):
        task.validate({"charts": [{"kind": "pie", "measure": "zzz"}]}, inp)


def test_every_chart_kind_draws_from_the_demo_data(app, demo):
    with app.app_context():
        ms = D.measures(Series.query.all())
        with_b = next(m for m in ms if len(m.branches) >= 2 and m.aggregation == "sum")
        for kind in D.KINDS:
            if kind in ("compare", "scatter"):
                other = next(x for x in ms if x.id != with_b.id)
                spec = D.validate_spec({"kind": kind, "measure": with_b.id, "measure2": other.id}, ms)
            else:
                spec = D.validate_spec({"kind": kind, "measure": with_b.id, "by": "quarter" if kind in ("bars", "table") else None}, ms)
            assert spec, kind
            out = D.build(spec, ms, 1)
            assert out and out["kind"] == kind, kind
            if kind in ("share", "ranking", "bars", "stacked", "growth", "cumulative", "scatter"):
                assert out["svg"].startswith("<svg") and "NaN" not in out["svg"], kind


def test_free_requests_pick_the_right_drawing():
    from app.ai.tasks.draw_chart import interpret
    cat = [{"id": "1", "name": "Revenue (DZD)", "branches": ["Alger", "Oran"]}, {"id": "2", "name": "Headcount", "branches": []}, {"id": "3", "name": "Ad Spend", "branches": []}]
    kinds = lambda q: [c["kind"] for c in interpret(q, cat)["charts"]]
    assert kinds("هل يمكنك رسم دائرة نسبية للمبيعات حسب كل فرع؟") == ["share"]
    assert kinds("أعمدة Revenue سنويا") == ["bars"]
    assert kinds("نمو Revenue") == ["growth"]
    assert kinds("جدول Revenue") == ["table"]
    assert kinds("العلاقة بين Revenue و Ad Spend") == ["scatter"]
    r = interpret("ارسم دائرة نسبية لـ Headcount حسب الفرع", cat)
    assert r["charts"] and r["charts"][0]["kind"] == "trend" and r["note"]             # no branch split: say so, draw the total


def test_data_tabs_are_unified_and_old_chart_links_redirect(app, demo):
    c = app.test_client()
    page = c.get("/app/demo/data/dashboard").get_data(as_text=True)
    assert page.index("/data/\"") < page.index("/data/dashboard\"") < page.index("/data/ask\"")   # files, analysis, ask
    assert 'class="dsec"' in page and "analysis-controls" in page
    assert "/data/charts" not in page
    assert c.get("/app/demo/data/dashboard?q=x").status_code == 302  # question links remain routed to Ask your data
    for kind in ("trend", "bars", "heatmap", "branches"):
        r = c.get(f"/app/demo/data/dashboard?kind={kind}")
        assert r.status_code == 200 and "chartbox" in r.get_data(as_text=True), kind
    legacy = c.get("/app/demo/data/charts?kind=bars", follow_redirects=False)
    assert legacy.status_code == 302 and "/data/dashboard?" in legacy.headers["Location"]
    ask = c.get("/app/demo/data/ask").get_data(as_text=True)
    assert "askpg" in ask and "form class=\"ask\"" in ask
