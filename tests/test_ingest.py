"""Reading spreadsheets: parsers, layouts, totals, wide files, profiles."""
from datetime import date
from pathlib import Path

import pytest

from app.modules.data.ingest.parsers import is_total_label, parse_number, parse_period
from app.modules.data.ingest.reader import ReadError, read_file
from app.modules.data.ingest.table import build_table, col_letter, profile_columns

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def load(name):
    return read_file((SAMPLES / name).read_bytes(), name)


@pytest.mark.parametrize("raw,val", [("1 234,5", 1234.5), ("1.234,50", 1234.5), ("1,234.50", 1234.5), ("12%", 12.0), ("٣٤٥", 345.0), ("(120)", -120.0), (7, 7.0)])
def test_numbers_in_french_arabic_and_english_formats(raw, val):
    got = parse_number(raw)
    assert got is not None and got[0] == pytest.approx(val)


@pytest.mark.parametrize("raw", ["abc", "", None, "N/A"])
def test_not_numbers(raw):
    assert parse_number(raw) is None


@pytest.mark.parametrize("raw,expected", [("2025-03", (date(2025, 3, 1), "month")), ("mars 2025", (date(2025, 3, 1), "month")),
                                           ("جانفي 2024", (date(2024, 1, 1), "month")), ("2025", (date(2025, 1, 1), "year")), ("T2 2025", (date(2025, 4, 1), "quarter"))])
def test_periods(raw, expected):
    assert parse_period(raw) == expected


def test_total_labels():
    assert is_total_label("Total") and is_total_label("المجموع") and is_total_label("TOTAL GÉNÉRAL")
    assert not is_total_label("Totalement")


def test_column_letters():
    assert [col_letter(i) for i in (0, 25, 26, 27, 701, 702)] == ["A", "Z", "AA", "AB", "ZZ", "AAA"]


def test_long_sample_total_row_is_left_out():
    sh = load("sales_by_branch.xlsx")[0]
    t = build_table(sh.grid, sheet_name=sh.name, filename="sales_by_branch.xlsx")
    assert t.layout == "long" and len(t.rows) == 72 and t.excluded and t.excluded[0]["reason"] == "total"


def test_wide_sample_months_across_columns_become_rows():
    sh = load("ventes_2025_mensuel.xlsx")[0]
    t = build_table(sh.grid, sheet_name=sh.name, filename="ventes_2025_mensuel.xlsx")
    assert t.layout == "wide" and t.header_row == 2          # a title banner sits above the header
    assert len(t.rows) == 60 and {r[-2].year for r in t.rows} == {2025}
    assert t.excluded                                          # the formula "Total" row


def test_arabic_sample_has_a_second_sheet_and_dates_are_recognised():
    sheets = load("المبيعات_والموظفون.xlsx")
    assert len(sheets) == 2
    t = build_table(sheets[0].grid)
    prof = profile_columns(t.headers, t.rows)
    assert prof[0]["type"] == "date" and prof[2]["type"] == "number"


def test_profile_measures_instead_of_guessing():
    prof = profile_columns(["d", "n", "t"], [[date(2025, 1, 1), 5, "x"], [date(2025, 2, 1), 7, "y"], [date(2025, 3, 1), 9, "x"]])
    assert [p["type"] for p in prof] == ["date", "number", "text"]
    assert prof[1]["min"] == 5 and prof[1]["max"] == 9 and prof[2]["distinct"] == 2


def test_unsupported_and_corrupt_files_have_clean_errors():
    with pytest.raises(ReadError) as e:
        read_file(b"x", "a.docx")
    assert str(e.value) == "unsupported"
    with pytest.raises(ReadError) as e:
        read_file(b"not a zip", "a.xlsx")
    assert str(e.value) == "corrupt"
    with pytest.raises(ReadError) as e:
        read_file(b"x" * (9 * 1024 * 1024), "a.csv")
    assert str(e.value) == "too_big"


def test_csv_semicolon_and_decimal_comma():
    sheets = read_file("Mois;Ventes\n2025-01;1 200,5\n2025-02;1 300,0\n2025-03;1 410,2\n".encode("utf-8"), "v.csv")
    t = build_table(sheets[0].grid)
    prof = profile_columns(t.headers, t.rows)
    assert [p["type"] for p in prof] == ["date", "number"]
