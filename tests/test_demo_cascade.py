from datetime import date

from app.core.demo import create_demo
from app.core.models import Link, Membership, OrgUnit
from app.extensions import db
from app.modules.goals.models import Objective
from app.modules.goals.service import compute_objectives


def test_demo_has_two_institution_goals_cascading_to_nine_departments(app):
    today = date(2026, 11, 3)
    with app.app_context():
        org = create_demo("ar", today=today)
        root_unit = OrgUnit.query.filter_by(org_id=org.id, kind="company").one()
        departments = OrgUnit.query.filter_by(org_id=org.id, kind="department").all()
        assert len(departments) == 9
        assert all(u.parent_id == root_unit.id and u.head_id for u in departments)

        objectives = Objective.query.filter_by(org_id=org.id).all()
        institutional = [o for o in objectives if o.parent_id is None]
        assert len(institutional) == 2
        commercial = next(o for o in institutional if o.title.startswith("تحقيق نمو تجاري"))
        operational = next(o for o in institutional if o.title.startswith("رفع كفاءة التشغيل"))
        assert all(o.progress_driver == "children" for o in institutional)

        commercial_children = [o for o in objectives if o.parent_id == commercial.id]
        operational_children = [o for o in objectives if o.parent_id == operational.id]
        assert len(commercial_children) == 4
        assert len(operational_children) == 5
        assert {o.unit_id for o in commercial_children + operational_children} == {u.id for u in departments}

        views = compute_objectives(org, today=today)
        for root, children in ((commercial, commercial_children), (operational, operational_children)):
            expected = sum(views[o.id].progress for o in children) / len(children)
            assert abs(views[root.id].progress - expected) < 1e-9

        assert len(Link.query.filter_by(org_id=org.id, kind="depends_on").all()) == 4
        assert Membership.query.filter_by(org_id=org.id).count() == 19

        # These two product areas stay switched off in the shipped configuration.
        registry = app.extensions["modules"]
        assert not registry.is_enabled("strategy")
        assert not registry.is_enabled("initiatives")
