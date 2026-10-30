"""The auth shell: the living stage and a plain, accessible form that keeps working without JS."""


def test_login_shell_and_fields(client):
    html = client.get("/login").get_data(as_text=True)
    assert 'class="auth-experience' in html
    assert "data-auth-form" in html
    assert 'name="email"' in html and 'name="password"' in html
    assert "data-auth-eye" in html
    assert "auth-stage" in html


def test_register_fields_and_org_hint(client):
    html = client.get("/register").get_data(as_text=True)
    for name in ("org_name", "name", "email", "password"):
        assert f'name="{name}"' in html
    assert "auth-grid" in html
    assert 'autocomplete="organization"' in html


def test_failed_login_keeps_email(client):
    r = client.post("/login", data={"email": "nobody@example.com", "password": "wrong-password"})
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "nobody@example.com" in html
    assert 'class="auth-experience' in html


def test_invalid_invite_still_has_shell(client):
    r = client.get("/join/not-a-real-token")
    assert r.status_code == 404
    assert 'class="auth-experience' in r.get_data(as_text=True)
