"""Sign-in pages (split layout) and the first-run welcome: model consent, then logo, then the profile page."""
from tests.conftest import register


def _slug(r):
    return r.headers["Location"].split("/")[2]


def test_gate_pages_render(client):
    for path in ("/login", "/register"):
        html = client.get(path).get_data(as_text=True)
        assert "data-gate" in html and "gate.js" in html and "data-scene" in html
    assert 'data-live="org"' in client.get("/register").get_data(as_text=True)


def test_failed_login_marks_error_for_the_scene(client):
    r = client.post("/login", data={"email": "nobody@example.com", "password": "wrong-pass-1"})
    assert r.status_code == 200 and 'data-error="1"' in r.get_data(as_text=True)


def test_welcome_flow_runs_once(full_modules, client):
    r = register(client)
    slug, base = _slug(r), f"/app/{_slug(r)}"
    assert r.headers["Location"].endswith("/welcome")
    page = client.get(f"{base}/welcome")
    assert page.status_code == 200 and "data-wm" in page.get_data(as_text=True)
    r = client.post(f"{base}/welcome", data={"choice": "deny"})                      # no cloud model configured in tests: the answer is still recorded
    assert r.status_code == 302 and r.headers["Location"].endswith("/welcome/logo")
    assert client.get(f"{base}/welcome/logo").status_code == 200
    r = client.post(f"{base}/welcome/logo", data={"skip": "1"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/welcome/direction")
    page = client.get(f"{base}/welcome/direction").get_data(as_text=True)
    assert "data-assist" in page and 'id="f-vision"' in page
    r = client.post(f"{base}/welcome/direction", data={"sector": "trade", "vision": "أن نكون الأوائل", "mission": "نخدم عملاءنا", "values": "الجودة، الأمانة"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/welcome/members")
    assert client.get(f"{base}/welcome/members").status_code == 200
    r = client.post(f"{base}/welcome/members", data={"action": "continue"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/welcome/units")
    assert client.get(f"{base}/welcome/units").status_code == 200
    r = client.post(f"{base}/welcome/units", data={"action": "finish"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/welcome/ready")
    ready = client.get(f"{base}/welcome/ready").get_data(as_text=True)
    assert "data-ready" in ready and "نجهّز مساحة العمل" in ready and "فتح لوحة التحكم" in ready
    assert f'href="{base}/"' in ready
    with client.application.app_context():
        from app.core import profile as P
        from app.core.models import Organization
        prof = P.profile(Organization.query.filter_by(slug=slug).first())
        assert prof["vision"] == "أن نكون الأوائل" and prof["sector"] == "trade" and prof["values"] == "الجودة، الأمانة"
    client.post("/logout")                                                            # next sign-in goes straight to the overview
    r = client.post("/login", data={"email": "a@example.com", "password": "correct-horse"})
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/app/{slug}/")


def test_welcome_can_be_skipped_entirely(full_modules, client):
    r = register(client)
    base = f"/app/{_slug(r)}"
    r = client.post(f"{base}/welcome/skip")
    assert r.status_code == 302 and r.headers["Location"].endswith(f"{base}/")
    assert client.get("/app").headers["Location"].endswith(f"{base}/")


def test_a_half_finished_welcome_resumes_where_it_stopped(full_modules, client):
    r = register(client)
    base = f"/app/{_slug(r)}"
    client.post(f"{base}/welcome", data={"choice": "deny"})
    client.post("/logout")
    r = client.post("/login", data={"email": "a@example.com", "password": "correct-horse"})
    assert r.headers["Location"].endswith("/welcome/logo")                            # step 1 is answered, so it resumes at the logo
    client.post(f"{base}/welcome/logo", data={"skip": "1"})
    client.post("/logout")
    r = client.post("/login", data={"email": "a@example.com", "password": "correct-horse"})
    assert r.headers["Location"].endswith("/welcome/direction")


def test_welcome_adds_team_and_units_before_workspace(full_modules, client):
    from app.core.models import Membership, Organization, OrgUnit, User

    r = register(client, email="owner@example.com", org="North Star")
    slug = _slug(r)
    base = f"/app/{slug}"
    client.post(f"{base}/welcome", data={"choice": "deny"})
    client.post(f"{base}/welcome/logo", data={"skip": "1"})
    client.post(f"{base}/welcome/direction", data={"sector": "services", "vision": "نمو مستدام"})

    page = client.get(f"{base}/welcome/members")
    assert page.status_code == 200 and "owner@example.com" in page.get_data(as_text=True)
    r = client.post(f"{base}/welcome/members", data={"action": "invite", "role": "member"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/welcome/members")
    page = client.get(f"{base}/welcome/members")
    html = page.get_data(as_text=True)
    assert "رمز QR" in html and "/settings/members/invite/" in html and "qr.svg" in html
    with client.application.app_context():
        from app.core.models import Invite
        invite = Invite.query.order_by(Invite.id.desc()).first()
        invite_id = invite.id
    qr = client.get(f"{base}/settings/members/invite/{invite_id}/qr.svg")
    assert qr.status_code == 200 and b"<svg" in qr.data
    r = client.post(f"{base}/welcome/members", data={"action": "add", "name": "Mona Saleh", "email": "mona@example.com", "title": "مديرة المبيعات", "role": "member"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/welcome/members")
    r = client.post(f"{base}/welcome/members", data={"action": "continue"})
    assert r.headers["Location"].endswith("/welcome/units")

    with client.application.app_context():
        org = Organization.query.filter_by(slug=slug).first()
        member = Membership.query.filter_by(org_id=org.id).join(User).filter(User.email == "mona@example.com").first()
        assert member is not None and member.title == "مديرة المبيعات"
        member_id = member.user_id

    r = client.post(f"{base}/welcome/units", data={"action": "add", "name": "المبيعات", "kind": "department", "head_id": str(member_id)})
    assert r.status_code == 302
    with client.application.app_context():
        org = Organization.query.filter_by(slug=slug).first()
        unit = OrgUnit.query.filter_by(org_id=org.id, name="المبيعات").first()
        member = Membership.query.filter_by(org_id=org.id, user_id=member_id).first()
        assert unit is not None and unit.head_id == member_id and member.unit_id == unit.id

    r = client.post(f"{base}/welcome/units", data={"action": "finish"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/welcome/ready")
    assert client.get(f"{base}/welcome/ready").status_code == 200
    r = client.post("/logout")
    r = client.post("/login", data={"email": "owner@example.com", "password": "correct-horse"})
    assert r.status_code == 302 and r.headers["Location"].endswith(f"{base}/")
