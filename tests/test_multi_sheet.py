"""One Excel file with several sheets: every sheet that holds a table is analyzed on its own; the table and its columns share one section."""
import io
import re

from openpyxl import Workbook

from tests.conftest import register


def workbook():
    wb = Workbook()
    a = wb.active
    a.title = "المبيعات"
    a.append(["الشهر", "المبيعات"])
    for m in range(1, 13):
        a.append([f"2025-{m:02d}-01", 100 + m * 5])
    b = wb.create_sheet("المصاريف")
    b.append(["الشهر", "المصاريف"])
    for m in range(1, 13):
        b.append([f"2025-{m:02d}-01", 60 + m * 2])
    c = wb.create_sheet("ملاحظات")
    c.append(["هذه الورقة للشرح فقط"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload(client):
    r = register(client)
    slug = r.headers["Location"].split("/app/")[1].split("/")[0]
    r = client.post(f"/app/{slug}/data/upload", data={"file": (io.BytesIO(workbook()), "تقرير.xlsx")}, content_type="multipart/form-data")
    return slug, r


def test_each_table_sheet_becomes_its_own_dataset_and_a_notes_sheet_does_not(client):
    slug, r = upload(client)
    assert r.status_code == 302
    page = client.get(r.headers["Location"]).get_data(as_text=True)
    ids = set(re.findall(r"/data/(\d+)/map#columns", page))
    assert len(ids) == 2                                                      # sales + expenses, each a tab; «ملاحظات» is offered with "+"
    assert page.count("add-sheet/2") == 1 and "المصاريف" in page and "المبيعات" in page
    assert 'data-panel="preview"' not in page and 'class="grid"' in page and 'data-colrow="1"' in page   # table and columns in one section


def test_confirming_one_sheet_moves_to_the_next_and_keeps_both_series(client):
    slug, r = upload(client)
    first = r.headers["Location"]
    r2 = client.post(first.replace("/map", "/confirm"))
    assert r2.status_code == 302 and "/map" in r2.headers["Location"]         # the other sheet is still a draft: go straight to it
    r3 = client.post(r2.headers["Location"].replace("/map", "/confirm"))
    assert r3.status_code == 302 and "/map" not in r3.headers["Location"]     # all sheets done: the dataset page
    names = client.get(f"/app/{slug}/data/").get_data(as_text=True)
    assert "تقرير — المبيعات" in names and "تقرير — المصاريف" in names


def test_a_skipped_sheet_can_be_added_later_and_a_ready_dataset_ignores_sheet_switching(client):
    slug, r = upload(client)
    mid = int(re.search(r"/data/(\d+)/map", r.headers["Location"]).group(1))
    r2 = client.post(f"/app/{slug}/data/{mid}/add-sheet/2")
    assert r2.status_code == 302 and "/map" in r2.headers["Location"]
    client.post(f"/app/{slug}/data/{mid}/confirm")
    before = client.get(f"/app/{slug}/data/{mid}/map").get_data(as_text=True)
    client.post(f"/app/{slug}/data/{mid}/analyze", data={"sheet": "1"})       # the old in-place switch must not overwrite a confirmed sheet
    after = client.get(f"/app/{slug}/data/{mid}/map").get_data(as_text=True)
    assert before.count("data-colrow") == after.count("data-colrow")
