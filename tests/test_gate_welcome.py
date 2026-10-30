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
    assert r.status_code == 302 and r.headers["Location"].endswith(f"{base}/")       # straight to the overview
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
