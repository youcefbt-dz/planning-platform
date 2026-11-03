"""The landing page's demo button must work on a fresh database (a new deploy has no demo organization until someone builds it)."""
from app.core.models import Organization


def test_the_demo_button_builds_the_sample_organization_on_first_visit(app):
    c = app.test_client()
    with app.app_context():
        assert Organization.query.filter_by(is_demo=True).count() == 0
    r = c.get("/demo")
    assert r.status_code == 302 and r.headers["Location"].endswith("/app/demo/")
    with app.app_context():
        assert Organization.query.filter_by(slug="demo", is_demo=True).count() == 1
    assert c.get("/app/demo/").status_code == 200            # readable by anyone, read-only
    assert c.get("/demo").status_code == 302                  # the second visit reuses it


def test_ensure_demo_is_idempotent(app):
    from app.core.demo import ensure_demo

    with app.app_context():
        a = ensure_demo("ar")
        assert ensure_demo("ar").id == a.id


def test_the_demo_is_small_and_clear(demo, app):
    from app.core.models import OrgUnit
    from app.modules.goals.models import Indicator, KeyResult, Objective

    with app.app_context():
        assert Objective.query.filter(Objective.parent_id.is_(None)).count() == 3        # three company goals…
        assert Objective.query.filter(Objective.parent_id.isnot(None)).count() == 2      # …and two department goals serving them
        assert KeyResult.query.count() == 10 and Indicator.query.count() == 3
        assert OrgUnit.query.count() == 3
