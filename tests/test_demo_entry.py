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
    goals_page = c.get("/app/demo/goals/")
    assert goals_page.status_code == 200
    assert "تحقيق نمو تجاري مربح" in goals_page.get_data(as_text=True)
    assert "رفع كفاءة التشغيل" in goals_page.get_data(as_text=True)
    tree_page = c.get("/app/demo/goals/tree")
    assert tree_page.status_code == 200
    assert "تحقيق نمو تجاري مربح" in tree_page.get_data(as_text=True)
    assert "رفع كفاءة التشغيل" in tree_page.get_data(as_text=True)
    assert c.get("/demo").status_code == 302                  # the second visit reuses it


def test_ensure_demo_is_idempotent(app):
    from app.core.demo import ensure_demo

    with app.app_context():
        a = ensure_demo("ar")
        assert ensure_demo("ar").id == a.id


def test_demo_entry_rebuilds_an_old_persistent_seed(app):
    from app.core.demo import DEMO_SEED_VERSION, create_demo
    from app.extensions import db
    from app.modules.goals.models import Objective

    with app.app_context():
        org = create_demo("ar")
        org.settings = {k: v for k, v in (org.settings or {}).items() if k != "demo_seed_version"}
        db.session.commit()

    response = app.test_client().get("/demo")
    assert response.status_code == 302

    with app.app_context():
        from app.core.models import Organization

        org = Organization.query.filter_by(slug="demo", is_demo=True).one()
        assert org.settings["demo_seed_version"] == DEMO_SEED_VERSION
        assert Objective.query.filter_by(org_id=org.id, parent_id=None).count() == 2


def test_the_demo_is_small_and_clear(demo, app):
    from app.core.models import OrgUnit
    from app.modules.goals.models import Indicator, KeyResult, Objective

    with app.app_context():
        assert Objective.query.filter(Objective.parent_id.is_(None)).count() == 2        # two institutional goals
        assert Objective.query.filter(Objective.parent_id.isnot(None)).count() == 9      # nine aligned department goals
        assert KeyResult.query.count() == 18 and Indicator.query.count() == 10
        assert OrgUnit.query.count() == 10
