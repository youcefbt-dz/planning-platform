"""Create realistic sample Excel files (for trying the import, and for tests). Writes to samples/.

  1. ventes_2025_mensuel.xlsx   French, months ACROSS the columns, title rows, a TOTAL row (the classic Excel layout)
  2. sales_by_branch.xlsx       English, one row per month and branch, long layout, with a total row
  3. المبيعات_والموظفون.xlsx      Arabic headers, two sheets, cryptic abbreviations, Algerian month names
"""
import random
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

OUT = Path(__file__).resolve().parents[1] / "samples"
OUT.mkdir(exist_ok=True)
rnd = random.Random(7)
SEASON = [0.86, 0.84, 0.95, 1.0, 1.04, 1.02, 0.9, 0.82, 1.06, 1.12, 1.15, 1.24]


def monthly(base, growth, noise=0.04, months=24, start=(2024, 1)):
    out, (y, m) = [], start
    for i in range(months):
        v = base * ((1 + growth) ** i) * SEASON[(m - 1) % 12] * (1 + rnd.uniform(-noise, noise))
        out.append((date(y, m, 1), round(v)))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def file1():
    wb = Workbook()
    ws = wb.active
    ws.title = "CA 2025"
    ws["A1"] = "Horizon Équipements — Chiffre d'affaires mensuel 2025 (DA)"
    ws["A1"].font = Font(bold=True, size=14)
    ws.merge_cells("A1:N1")
    heads = ["Famille", "Région", "Janv", "Févr", "Mars", "Avr", "Mai", "Juin", "Juil", "Août", "Sept", "Oct", "Nov", "Déc"]
    for c, h in enumerate(heads, 1):
        ws.cell(3, c, h).font = Font(bold=True)
        ws.cell(3, c).fill = PatternFill("solid", fgColor="DDE3FF")
    rows = [("Outillage", "Batna", 1_800_000, 0.012), ("Outillage", "Alger", 2_600_000, 0.02), ("Électrique", "Batna", 1_200_000, 0.008),
            ("Électrique", "Alger", 1_900_000, 0.015), ("Sécurité", "Constantine", 900_000, 0.03)]
    for r, (fam, reg, base, g) in enumerate(rows, 4):
        ws.cell(r, 1, fam)
        ws.cell(r, 2, reg)
        for i, (_, v) in enumerate(monthly(base, g, months=12, start=(2025, 1))):
            ws.cell(r, 3 + i, v)
    tr = 4 + len(rows)
    ws.cell(tr, 1, "Total")
    for c in range(3, 15):
        L = ws.cell(3, c).column_letter
        ws.cell(tr, c, f"=SUM({L}4:{L}{tr-1})")
    ws.cell(tr, 1).font = Font(bold=True)
    wb.save(OUT / "ventes_2025_mensuel.xlsx")


def file2():
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(["Month", "Branch", "Net sales", "Orders", "On-time delivery %"])
    branches = {"Batna": (1_500_000, 0.014), "Algiers": (2_300_000, 0.02), "Oran": (1_100_000, 0.01)}
    tot = {}
    for b, (base, g) in branches.items():
        for (d, v) in monthly(base, g):
            ws.append([d, b, v, round(v / 8200), round(88 + rnd.uniform(-4, 5) + (d.year - 2024) * 2.2, 1)])
    for c in ws["A"][1:]:
        c.number_format = "mmm-yy"
    ws.append(["Total", None, "=SUM(C2:C73)", "=SUM(D2:D73)", None])
    wb.save(OUT / "sales_by_branch.xlsx")


def file3():
    wb = Workbook()
    ws = wb.active
    ws.title = "المبيعات"
    ws.sheet_view.rightToLeft = True
    ws.append(["الشهر", "الفرع", "مب", "ك", "تكلفة"])
    months = ["جانفي", "فيفري", "مارس", "أفريل", "ماي", "جوان", "جويلية", "أوت", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
    for (yy, base) in ((2024, 1_400_000), (2025, 1_650_000)):
        for i, m in enumerate(months):
            v = round(base * SEASON[i] * (1 + rnd.uniform(-0.04, 0.04)))
            ws.append([f"{m} {yy}", "باتنة", v, round(v / 7900), round(v * 0.71)])
    ws2 = wb.create_sheet("الموظفون")
    ws2.append(["التاريخ", "عدد الموظفين", "نسبة الدوران %"])
    n = 38
    for i in range(24):
        n += rnd.choice([0, 0, 1, 1, -1])
        y, m = 2024 + i // 12, i % 12 + 1
        ws2.append([date(y, m, 1), n, round(19 - i * 0.2 + rnd.uniform(-1.2, 1.2), 1)])
    wb.save(OUT / "المبيعات_والموظفون.xlsx")


if __name__ == "__main__":
    file1(); file2(); file3()
    print(*sorted(p.name for p in OUT.iterdir()), sep="\n")
