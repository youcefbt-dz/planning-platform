"""1.1 data: understand the table before relying on it, and update it with a newer file."""
import io

import openpyxl
import pytest

from app.extensions import db
from app.modules.data.models import Dataset, DatasetVersion
from tests.conftest import register

PER = [10, 12, 9, 11, 14, 13, 12, 15, 11, 10, 13, 16, 9, 12, 10, 11, 13, 12, 14, 10, 11, 12, 13, 15]


def xlsx(values, name="sales.xlsx", cumulative=False):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Month", "Sales"])
    run = 0
    for i, v in enumerate(values):
        run = v if (cumulative and i % 12 == 0) else (run + v if cumulative else v)
        ws.append([f"{2024 + i // 12}-{i % 12 + 1:02d}", run])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf, name


@pytest.fixture()
def owner(app, client):
    r = register(client)
    return client, r.headers["Location"].split("/app/")[1].split("/")[0]


def up(c, slug, values, **kw):
    return c.post(f"/app/{slug}/data/upload", data={"file": xlsx(values, **kw)}, content_type="multipart/form-data")


def dsid(r):
    return int(r.headers["Location"].split("/")[-2])


def test_running_totals_are_flagged_and_converted_only_when_the_user_decides(app, owner):
    c, slug = owner
    i = dsid(up(c, slug, PER, cumulative=True))
    page = c.get(f"/app/{slug}/data/{i}/map").get_data(as_text=True)
    assert 'id="quality"' in page and "مجاميع تراكمية" in page and "ملاحظة واحدة تنتظر قرارك" in page
    c.post(f"/app/{slug}/data/{i}/confirm")                      # confirming without deciding keeps the file as it is
    with app.app_context():
        assert [v for _, v in db.session.get(Dataset, i).series[0].pairs()][:3] == [10, 22, 31]
    assert c.post(f"/app/{slug}/data/{i}/fix", data={"column": 1, "code": "cumulative", "option": "to_period"}).status_code == 302
    page = c.get(f"/app/{slug}/data/{i}/map").get_data(as_text=True)
    assert "1 thing waits" not in page and 'aria-pressed="true"' in page
    c.post(f"/app/{slug}/data/{i}/confirm")
    with app.app_context():
        assert [v for _, v in db.session.get(Dataset, i).series[0].pairs()] == PER


def test_nonsense_decisions_are_refused(owner):
    c, slug = owner
    i = dsid(up(c, slug, PER))
    assert c.post(f"/app/{slug}/data/{i}/fix", data={"column": 1, "code": "cumulative", "option": "delete_everything"}).status_code == 400
    assert c.post(f"/app/{slug}/data/{i}/fix", data={"column": 1, "code": "jump", "option": "keep"}).status_code == 400   # a jump needs its period


def test_a_newer_file_keeps_decisions_and_shows_what_changed(app, owner):
    c, slug = owner
    i = dsid(up(c, slug, PER, cumulative=True))
    c.post(f"/app/{slug}/data/{i}/fix", data={"column": 1, "code": "cumulative", "option": "to_period"})
    c.post(f"/app/{slug}/data/{i}/confirm")
    newer = PER + [14, 13]
    newer[3] = 21                                                  # a revised past month
    r = c.post(f"/app/{slug}/data/{i}/update", data={"file": xlsx(newer, "sales_v2.xlsx", cumulative=True)}, content_type="multipart/form-data")
    assert r.status_code == 302 and r.headers["Location"].endswith("#changes")          # no new questions: refreshed straight away
    with app.app_context():
        ds = db.session.get(Dataset, i)
        assert [v for _, v in ds.series[0].pairs()] == newer           # the earlier decision (convert running totals) was carried over
        v2 = [v for v in ds.versions if v.number == 2][0]
        assert v2.confirmed and v2.diff["new_periods"] == 2 and v2.diff["revised_count"] >= 1
        assert v2.diff["revised"][0]["old"] == 11 and v2.diff["revised"][0]["new"] == 21
    page = c.get(f"/app/{slug}/data/{i}").get_data(as_text=True)
    assert "ما تغيّر في النسخة 2" in page and "سجل النسخ" in page


def test_an_update_that_loses_a_column_asks_before_replacing(app, owner):
    c, slug = owner
    i = dsid(up(c, slug, PER))
    c.post(f"/app/{slug}/data/{i}/confirm")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Month", "Turnover"])                               # renamed measure: not the same column any more
    for k, v in enumerate(PER):
        ws.append([f"{2024 + k // 12}-{k % 12 + 1:02d}", v])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    r = c.post(f"/app/{slug}/data/{i}/update", data={"file": (buf, "v2.xlsx")}, content_type="multipart/form-data")
    assert r.headers["Location"].endswith("/map")
    with app.app_context():
        ds = db.session.get(Dataset, i)
        assert ds.status == "draft" and ds.series                    # series stay (goals keep working) until the user confirms
        assert (ds.meta.get("update") or {}).get("lost")
