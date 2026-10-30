"""Goal quality rules: what professional OKR practice would flag, in three languages."""
from app.modules.goals.coach import review, starts_with_activity

GOOD_OBJ = {"title": "Become the preferred supplier of our region", "rationale": "Customers who trust us reorder more often and refer others.", "has_horizon": True, "has_owner": True}


def codes(r, level=None):
    return {x["code"] for x in r["open"] if level in (None, x["level"])}


def kr(title="Monthly revenue", **kw):
    return {"title": title, "type": "increase", "start": 100, "target": 150, "unit": "k DZD", "measured": True, **kw}


def test_a_well_written_goal_passes_everything():
    r = review(GOOD_OBJ, [kr(), kr("On-time delivery rate", start=80, target=95, unit="%")], has_series=True)
    assert r["open"] == [] and r["passed"] == r["total"]


def test_activities_are_not_results_in_three_languages():
    for t in ("Launch the new website", "Publish 3 blog posts", "Lancer le nouveau site", "Mettre en place un CRM", "إطلاق الموقع الجديد", "تنفيذ حملة إعلانية", "نفّذ خطة التدريب"):
        assert starts_with_activity(t), t
    for t in ("Monthly revenue", "Taux de livraison à temps", "حصة السوق في المنطقة", "Customer churn"):
        assert not starts_with_activity(t), t


def test_objective_problems_are_found():
    r = review({"title": "Growth", "rationale": "", "has_horizon": False, "has_owner": False}, [])
    assert {"title_short", "why", "horizon", "owner", "kr_none"} <= codes(r)
    assert "kr_none" in codes(r, "error")
    assert "title_number" in codes(review({**GOOD_OBJ, "title": "Reach 10 million in sales this year"}, [kr(), kr("Churn")]))
    assert "title_empty" in codes(review({**GOOD_OBJ, "title": ""}, [kr(), kr("x")]))


def test_key_result_problems_are_found():
    r = review(GOOD_OBJ, [kr("Launch loyalty programme"), kr("Revenue", start=100, target=100), kr("Churn", type="decrease", start=5, target=8, unit="%"), kr("Margin", unit="", measured=False)], has_series=True)
    assert {"kr_activity", "kr_span", "kr_direction", "kr_unit", "kr_measured"} <= codes(r)
    assert "kr_span" in codes(r, "error")


def test_binary_and_milestone_keep_a_softer_rule_and_need_no_unit():
    r = review(GOOD_OBJ, [kr("Launch the ERP", type="milestone", start=0, target=4, unit="", measured=False), kr("ISO 27001 certified", type="binary", start=0, target=1, unit="", measured=False)], has_series=True)
    assert "kr_activity_soft" in codes(r, "info") and "kr_unit" not in codes(r) and "kr_measured" not in codes(r)


def test_a_target_beyond_history_must_be_explained():
    base = [kr(verdict="unrealistic", factors=0), kr("Margin", verdict="realistic")]
    assert "kr_needs_factors" in codes(review(GOOD_OBJ, base))
    assert "kr_needs_factors" not in codes(review(GOOD_OBJ, [kr(verdict="unrealistic", factors=2), kr("Margin")]))
    assert "kr_beyond_history" in codes(review(GOOD_OBJ, [kr(verdict="stretch", factors=0), kr("Margin")]))


def test_too_many_or_duplicate_key_results():
    many = [kr(f"Metric {i}") for i in range(6)]
    assert "kr_many" in codes(review(GOOD_OBJ, many))
    assert "kr_duplicate" in codes(review(GOOD_OBJ, [kr("Revenue"), kr("revenue")]))
    assert "kr_one" in codes(review(GOOD_OBJ, [kr()]))
