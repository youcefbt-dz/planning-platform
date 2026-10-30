from app.modules.goals.factors import coverage, gap_to_target


def test_gap_is_measured_toward_the_goal():
    assert gap_to_target(120, 100, "higher_better") == 20
    assert gap_to_target(80, 100, "higher_better") == 0
    assert gap_to_target(6, 8, "lower_better") == 2
    assert gap_to_target(10, 8, "lower_better") == 0
    assert gap_to_target(50, None) == 0


def test_coverage_tiers_never_blend_certainty():
    f = lambda e, c: {"effect": e, "certainty": c}
    assert coverage(0, [])["status"] == "none_needed"
    assert coverage(20, [])["status"] == "none"
    assert coverage(20, [f(25, "confirmed")])["status"] == "covered"
    assert coverage(20, [f(10, "confirmed"), f(12, "probable")])["status"] == "likely"
    assert coverage(20, [f(5, "confirmed"), f(5, "probable"), f(12, "hoped")])["status"] == "hoped"
    assert coverage(20, [f(5, "confirmed"), f(5, "hoped")])["status"] == "partial"


def test_a_headwind_counts_against_the_plan_and_unproven_share_is_reported():
    c = coverage(20, [{"effect": 30, "certainty": "confirmed"}, {"effect": -15, "certainty": "probable"}])
    assert c["total"] == 15 and c["status"] == "partial"
    d = coverage(20, [{"effect": 10, "certainty": "confirmed"}, {"effect": 30, "certainty": "hoped"}])
    assert d["unproven"] == 0.75 and d["share_confirmed"] == 0.5 and d["share_all"] == 1.0
    assert c["headwind"] == -15 and c["confirmed"] == 15
