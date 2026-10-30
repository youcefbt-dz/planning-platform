"""A raw grid -> a clean LONG table (one row per observation), whatever the layout.

Handles: title rows above the header, merged cells, 'Total' rows, duplicated / empty headers, and the very common
WIDE layout where the months run across the columns (Jan | Feb | … | Dec) which is turned into (…, Date, Value) rows.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.modules.data.ingest.parsers import fold, is_total_label, month_of, parse_number, parse_period


def col_letter(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _is_text(v) -> bool:
    return isinstance(v, str) and bool(v.strip()) and parse_number(v) is None


@dataclass
class Table:
    headers: list[str]
    rows: list[list]                       # long-format rows, aligned with headers
    layout: str = "long"                   # long | wide
    header_row: int = 0                    # 0-based grid row of the header
    phys: list[list[int]] = field(default_factory=list)      # per logical column: grid columns it comes from
    excluded: list[dict] = field(default_factory=list)       # [{"row": grid row, "reason": "total"}]
    notes: list[str] = field(default_factory=list)
    title: str = ""
    assumed_year: int | None = None        # months without a year: which year was assumed
    row_refs: list[int] = field(default_factory=list)        # grid row of each long row (for highlighting)


def detect_header_row(grid: list[list]) -> int:
    """The first row, among the first 30, that looks like column titles: several text cells, followed by filled rows."""
    width = max((len(r) for r in grid), default=0)
    best, best_score = 0, -1.0
    for i, row in enumerate(grid[:30]):
        texts = sum(1 for v in row if _is_text(v))
        filled = sum(1 for v in row if not _blank(v))
        if texts < 2 or texts < 0.5 * max(1, filled):
            continue
        nxt = grid[i + 1 : i + 4]
        if not nxt:
            continue
        fill_next = sum(sum(1 for v in r if not _blank(v)) for r in nxt) / (len(nxt) * max(1, filled))
        score = texts + 3 * min(1.0, fill_next) + (0.5 if i == 0 else 0)
        if fill_next >= 0.5 and score > best_score + 1e-9:
            best, best_score = i, score
            if texts >= 0.8 * width:       # an unmistakable header: stop looking
                break
    return best


def _clean_headers(raw: list, width: int) -> list[str]:
    out, seen = [], {}
    for c in range(width):
        v = raw[c] if c < len(raw) else None
        h = re.sub(r"\s+", " ", str(v).strip()) if not _blank(v) else col_letter(c)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            h = str(int(v)) if float(v).is_integer() else str(v)
        n = seen.get(h, 0)
        seen[h] = n + 1
        out.append(h if n == 0 else f"{h} ({n + 1})")
    return out


def _title_above(grid, header_row) -> str:
    for r in range(header_row - 1, -1, -1):
        cells = [str(v).strip() for v in grid[r] if _is_text(v)]
        if cells:
            return cells[0][:80]
    return ""


def _year_hint(grid, header_row, sheet_name="", filename="") -> int | None:
    for blob in [" ".join(str(v) for r in grid[: header_row + 1] for v in r if v is not None), sheet_name, filename]:
        m = re.findall(r"(?<!\d)(20\d{2}|19\d{2})(?!\d)", blob)
        if m:
            return int(m[-1])
    return None


def build_table(grid: list[list], *, header_row: int | None = None, sheet_name: str = "", filename: str = "", year: int | None = None) -> Table:
    if not grid:
        return Table([], [])
    hr = detect_header_row(grid) if header_row is None else max(0, min(header_row, len(grid) - 1))
    width = max(len(r) for r in grid)
    raw_header = list(grid[hr]) + [None] * (width - len(grid[hr]))
    body = [(i, r) for i, r in enumerate(grid[hr + 1 :], start=hr + 1)]
    title = _title_above(grid, hr)

    # months across the columns?  (Jan | Feb | … or dates in the header)
    date_cols = [c for c in range(width) if _header_period(raw_header[c]) is not None]
    month_only = [c for c in date_cols if _header_period(raw_header[c])[1] == "monthname"]
    if len(date_cols) >= 3 and len(date_cols) >= 0.4 * max(1, sum(1 for v in raw_header if not _blank(v))):
        return _unpivot(grid, hr, raw_header, body, date_cols, month_only, width, sheet_name, filename, title, year)

    headers = _clean_headers(raw_header, width)
    t = Table(headers=headers, rows=[], layout="long", header_row=hr, phys=[[c] for c in range(width)], title=title)
    for gi, r in body:
        r = list(r) + [None] * (width - len(r))
        if all(_blank(v) for v in r):
            continue
        first = next((v for v in r if not _blank(v)), None)
        if is_total_label(first):
            t.excluded.append({"row": gi, "reason": "total"})
            continue
        t.rows.append(r[:width])
        t.row_refs.append(gi)
    return t


def _header_period(v):
    """-> (date, kind) for a header cell that is a date / month name, else None.  Pure month names give kind 'monthname'."""
    if _blank(v):
        return None
    if not isinstance(v, str) and not hasattr(v, "year"):
        return None
    p = parse_period(v)
    if p and p[1] in ("day", "month", "quarter"):
        return p
    if isinstance(v, str) and (m := month_of(v)):
        return (date(2000, m, 1), "monthname")
    return None


def _unpivot(grid, hr, raw_header, body, date_cols, month_only, width, sheet_name, filename, title, year):
    id_cols = [c for c in range(width) if c not in date_cols and not _blank(raw_header[c])]
    # the identifier columns are the leading non-date columns that hold text
    id_cols = [c for c in id_cols if c < min(date_cols)] or id_cols[:1]
    assumed = None
    # a year row just above the months ("2025" merged over Jan..Dec) gives the year
    year_row = [grid[hr - 1][c] if hr > 0 and c < len(grid[hr - 1]) else None for c in range(width)] if hr > 0 else []
    cols = []                                  # (grid col, date)
    for c in date_cols:
        p = _header_period(raw_header[c])
        if p[1] == "monthname":
            y = None
            yr = year_row[c] if year_row else None
            if yr is not None and parse_period(yr) and parse_period(yr)[1] == "year":
                y = parse_period(yr)[0].year
            if y is None:
                y = year or _year_hint(grid, hr + 1, sheet_name, filename)
            if y is None:
                y = date.today().year - 1      # nothing says which year: assume last year and tell the user
                assumed = y
            cols.append((c, date(y, p[0].month, 1), "month"))
        else:
            cols.append((c, p[0], p[1]))
    kind = "month" if any(k in ("month", "day") for _, _, k in cols) else cols[0][2]
    value_name = title or sheet_name or "Value"
    headers = _clean_headers(raw_header, width)
    id_headers = [headers[c] for c in id_cols] or ["—"]
    t = Table(headers=id_headers + ["Date", value_name], rows=[], layout="wide", header_row=hr,
              phys=[[c] for c in id_cols] + [[c for c, _, _ in cols], [c for c, _, _ in cols]], title=title, assumed_year=assumed)
    for gi, r in body:
        r = list(r) + [None] * (width - len(r))
        if all(_blank(v) for v in r):
            continue
        first = next((v for v in r if not _blank(v)), None)
        if is_total_label(first):
            t.excluded.append({"row": gi, "reason": "total"})
            continue
        ids = [r[c] for c in id_cols] or ["—"]
        for c, d, _ in cols:
            if not _blank(r[c]):
                t.rows.append([*ids, d, r[c]])
                t.row_refs.append(gi)
    return t


def profile_columns(headers: list[str], rows: list[list]) -> list[dict]:
    """Measured facts about every column (type, distinct values, range, examples). The AI and the rules both start from these."""
    out = []
    n = len(rows)
    for c, h in enumerate(headers):
        vals = [r[c] for r in rows if c < len(r) and not _blank(r[c])]
        prof = {"index": c, "rows": n, "nulls": round(1 - len(vals) / n, 3) if n else 1.0, "distinct": len({str(v) for v in vals}),
                "type": "empty", "examples": [], "percent_sign": False}
        if vals:
            hf = fold(h)
            periods = [parse_period(v) for v in vals]
            nums = [parse_number(v) for v in vals]
            share_date = sum(1 for p in periods if p) / len(vals)
            share_num = sum(1 for x in nums if x is not None) / len(vals)
            plain_years = all(isinstance(v, (int, float)) and float(v).is_integer() and 1990 <= v <= 2100 for v in vals)
            if share_date >= 0.8 and (not plain_years or any(k in hf for k in ("annee", "year", "سنه", "عام"))):
                prof["type"] = "date"
                ds = sorted(p[0] for p in periods if p)
                prof["min"], prof["max"] = ds[0].isoformat(), ds[-1].isoformat()
                prof["date_kind"] = _dominant_kind([p[1] for p in periods if p])
            elif share_num >= 0.8:
                prof["type"] = "number"
                xs = [x[0] for x in nums if x is not None]
                prof["min"], prof["max"] = min(xs), max(xs)
                prof["percent_sign"] = sum(1 for x in nums if x and x[1]) >= 0.5 * len(xs)
            else:
                prof["type"] = "text"
            seen = []
            for v in vals:
                s = v.date().isoformat() if hasattr(v, "date") else str(v)
                if s not in seen:
                    seen.append(s)
                if len(seen) >= 5:
                    break
            prof["examples"] = seen
        out.append(prof)
    return out


def _dominant_kind(kinds):
    order = ["day", "month", "quarter", "year"]
    return max(set(kinds), key=lambda k: (kinds.count(k), -order.index(k)))
