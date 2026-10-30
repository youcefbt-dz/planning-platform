"""Files -> raw grids. xlsx / xlsm (openpyxl) and csv / tsv / txt. Merged cells are filled, formulas read as their last computed value."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS, MAX_COLS = 20000, 120
EXTENSIONS = (".xlsx", ".xlsm", ".csv", ".tsv", ".txt")


class ReadError(ValueError):
    """The file cannot be used; the message is a catalog key suffix (data.errors.<code>)."""


@dataclass
class Sheet:
    name: str
    grid: list[list]                      # rows of raw cell values (str / number / datetime / None), rectangular
    truncated: bool = False
    notes: list[str] = field(default_factory=list)


def read_file(data: bytes, filename: str) -> list[Sheet]:
    name = (filename or "").lower()
    if len(data) > MAX_BYTES:
        raise ReadError("too_big")
    if name.endswith((".xlsx", ".xlsm")):
        return _read_xlsx(data)
    if name.endswith((".csv", ".tsv", ".txt")):
        return [_read_csv(data, name)]
    raise ReadError("unsupported")


def _rectangular(rows: list[list]) -> list[list]:
    width = min(MAX_COLS, max((len(r) for r in rows), default=0))
    return [list(r[:width]) + [None] * (width - len(r[:width])) for r in rows]


def _read_xlsx(data: bytes) -> list[Sheet]:
    try:
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(data), data_only=True)        # data_only: the numbers Excel last calculated
    except Exception:
        raise ReadError("corrupt") from None
    sheets = []
    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            continue
        rows = []
        trunc = False
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= MAX_ROWS:
                trunc = True
                break
            rows.append(list(row))
        grid = _rectangular(rows)
        for rng in ws.merged_cells.ranges:                           # a merged "2025" over twelve month columns means 2025 for each of them
            r0, c0 = rng.min_row - 1, rng.min_col - 1
            wide = (rng.max_col - rng.min_col + 1) >= 0.8 * max(1, len(grid[0]) if grid else 1)
            if wide and rng.max_row == rng.min_row:           # a title banner across the whole sheet is not a header: leave it in one cell
                continue
            if r0 < len(grid) and c0 < len(grid[0] if grid else []):
                v = grid[r0][c0]
                for r in range(r0, min(rng.max_row, len(grid))):
                    for c in range(c0, min(rng.max_col, len(grid[0]))):
                        if grid[r][c] is None:
                            grid[r][c] = v
        grid = _trim(grid)
        if grid:
            sheets.append(Sheet(ws.title, grid, trunc))
    if not sheets:
        raise ReadError("empty")
    return sheets


def _read_csv(data: bytes, name: str) -> Sheet:
    text = None
    for enc in ("utf-8-sig", "cp1256", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None or not text.strip():
        raise ReadError("empty")
    head = text[:4096]
    delim = max(";,\t|", key=head.count) if any(d in head for d in ";,\t|") else ","
    if name.endswith(".tsv"):
        delim = "\t"
    rows = []
    trunc = False
    for i, row in enumerate(csv.reader(io.StringIO(text), delimiter=delim)):
        if i >= MAX_ROWS:
            trunc = True
            break
        rows.append([c if c != "" else None for c in row])
    grid = _trim(_rectangular(rows))
    if not grid:
        raise ReadError("empty")
    return Sheet("CSV", grid, trunc)


def _trim(grid: list[list]) -> list[list]:
    """Drop fully empty rows/columns at the END only: row numbers and column letters stay exactly as in the user's Excel (A1 = grid[0][0])."""
    def blank(v):
        return v is None or (isinstance(v, str) and not v.strip())

    while grid and all(blank(v) for v in grid[-1]):
        grid.pop()
    if not grid:
        return []
    width = max((c + 1 for r in grid for c, v in enumerate(r) if not blank(v)), default=0)
    return [r[:width] for r in grid]
