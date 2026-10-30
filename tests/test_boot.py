import re

import pytest

from tests.conftest import register


def test_landing_is_arabic_rtl(client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'lang="ar"' in html and 'dir="rtl"' in html


def test_demo_pages_render_without_leaked_keys(full_modules, demo, client):
    leak = re.compile(r">\s*(?:common|goals|initiatives|strategy|reports|site|status|settings|shell)\.[a-z_.]+\s*<")
    for slug in ("demo",):
        for path in ("", "goals/", "goals/tree", "goals/indicators", "initiatives/", "initiatives/board",
                     "initiatives/roadmap", "strategy/", "strategy/swot", "strategy/map", "reports/",
                     "reports/progress", "reports/indicators", "reports/initiatives", "search?q=a"):
            r = client.get(f"/app/{slug}/{path}")
            assert r.status_code == 200, path
            assert not leak.search(r.get_data(as_text=True)), path
    for path in ("settings/general", "settings/members", "settings/units", "settings/cycles"):
        assert client.get(f"/app/demo/{path}").status_code in (200, 302, 403), path


def test_demo_is_read_only(demo, client):
    r = client.post("/app/demo/goals/new", data={"title": "x"})
    assert r.status_code in (302, 403)


def test_csv_export(demo, client):
    r = client.get("/app/demo/reports/progress.csv")
    assert r.status_code == 200 and r.mimetype == "text/csv"
    assert r.data.startswith(b"\xef\xbb\xbf")  # BOM so Excel opens Arabic correctly


def test_register_and_full_flow(full_modules, client):
    r = register(client)
    assert r.status_code == 302
    assert "/welcome" in r.headers["Location"]  # first stop after sign-up: the welcome (model consent, then logo)
    slug = r.headers["Location"].split("/")[2]
    base = f"/app/{slug}"
    assert client.get(f"{base}/").status_code == 200
    r = client.post(f"{base}/goals/new", data={"title": "Grow", "kr_title": ["Revenue", ""], "kr_start": ["0", ""], "kr_target": ["100", ""], "kr_unit": ["k", ""]}, follow_redirects=False)
    assert r.status_code == 302
    gid = r.headers["Location"].rstrip("/").split("/")[-1]
    assert client.get(f"{base}/goals/{gid}").status_code == 200
    assert client.get(f"{base}/goals/{gid}/edit").status_code == 200
    assert client.get(f"{base}/goals/new", follow_redirects=True).status_code == 200
    assert client.post(f"{base}/goals/{gid}/checkin", data={"comment": "going well", "status": ""}).status_code == 302
    r = client.post(f"{base}/initiatives/new", data={"title": "Launch", "start_date": "2026-01-01", "end_date": "2026-12-31"})
    assert r.status_code == 302
    for p in ("initiatives/", "initiatives/board", "initiatives/roadmap", "strategy/", "strategy/swot", "strategy/map",
              "reports/", "reports/progress", "goals/indicators", "goals/indicators/new", "settings", "settings/members",
              "settings/units", "settings/cycles", "settings/general", "search?q=Gr"):
        assert client.get(f"{base}/{p}", follow_redirects=True).status_code == 200, p


def test_org_isolation(client, app):
    register(client, "a@example.com", "Org A")
    r = client.post("/app/org-a/goals/new", data={"title": "Secret"})
    assert r.status_code == 302
    gid = r.headers["Location"].rstrip("/").split("/")[-1]
    other = app.test_client()
    register(other, "b@example.com", "Org B")
    assert other.get(f"/app/org-a/goals/{gid}").status_code == 404      # member of B, not A
    assert other.get(f"/app/org-b/goals/{gid}").status_code == 404      # id belongs to A: scoped lookup
    anon = app.test_client()
    assert anon.get(f"/app/org-a/goals/{gid}").status_code == 302       # sent to login


def test_v11_ships_without_strategy_and_initiatives(demo, client):
    for p in ("initiatives/", "strategy/", "strategy/swot", "reports/initiatives"):
        assert client.get(f"/app/demo/{p}").status_code == 404, p
    html = client.get("/app/demo/").get_data(as_text=True)
    assert "/initiatives/" not in html and "/strategy/" not in html
    assert client.get("/app/demo/goals/").status_code == 200
