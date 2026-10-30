"""Writing relief: the pages offer clicks instead of blank boxes, and the endpoints behind them work with no model at all."""
from tests.conftest import register


def boot(client):
    r = register(client)
    return r.headers["Location"].split("/app/")[1].split("/")[0]


def test_goal_form_offers_an_idea_box_and_folds_the_secondary_fields(client):
    slug = boot(client)
    html = client.get(f"/app/{slug}/goals/new?classic=1").get_data(as_text=True)
    assert "data-assist=" in html and 'id="draft-intent"' in html
    assert '<details class="more"' in html and html.index('name="title"') < html.index('<details class="more"') < html.index('name="weight"')
    assert 'name="cycle_id"' in html and 'id="f-end_date"' in html            # still in the page, so the review and level scripts keep working


def test_draft_endpoint_answers_from_the_library_without_a_model(client):
    slug = boot(client)
    r = client.post(f"/app/{slug}/goals/draft", data={"intent": "نريد رفع المبيعات"})
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "data-pick-goal" in html and "الإيراد الشهري" in html and "القواعد المدمجة" in html
    assert "data-krs=" in html and "حلّله" not in html
    assert "اكتب كلمتين" in client.post(f"/app/{slug}/goals/draft", data={"intent": "x"}).get_data(as_text=True)
    assert "لم نجد صياغة" in client.post(f"/app/{slug}/goals/draft", data={"intent": "شيء غير مفهوم تمامًا"}).get_data(as_text=True)


def test_direction_draft_proposes_wording_for_the_chosen_sector_and_saves_nothing(client):
    slug = boot(client)
    r = client.post(f"/app/{slug}/settings/direction-draft", data={"sector": "health", "size": "small"})
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and 'data-target="#f-vision"' in html and 'data-target="#f-mission"' in html and 'data-mode="list"' in html and "الرعاية الصحية" in html
    page = client.get(f"/app/{slug}/settings/general").get_data(as_text=True)
    assert "data-assist=" in page and "direction-draft" in page


def test_update_boxes_have_quick_replies(client):
    slug = boot(client)
    r = client.post(f"/app/{slug}/goals/new?classic=1", data={"title": "تنمية مبيعاتنا نموًّا منتظمًا", "commitment": "committed"})
    assert r.status_code == 302
    detail = client.get(r.headers["Location"]).get_data(as_text=True)
    assert 'data-target="#ci-comment"' in detail and detail.count('data-mode="append"') == 5
