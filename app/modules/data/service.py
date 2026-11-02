"""Data module logic (no routes): file -> table -> AI mapping -> series, and the grid shown on the mapping page.

Flow:   upload  ->  analyze()  ->  [user answers / edits columns]  ->  confirm()  ->  Series rows
The mapping is stored on the Dataset (`columns`, `questions`) so it survives reloads and can be re-opened later.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from pathlib import Path

from flask import current_app, g

from app import ai
from app.core.models import Link
from app.extensions import db
from app.modules.data.ingest.parsers import parse_number, parse_period
from app.modules.data.ingest.reader import ReadError, Sheet, read_file
from app.modules.data.ingest.table import Table, build_table, col_letter, profile_columns
from app.modules.data import quality
from app.modules.data.models import Dataset, DatasetVersion, Series
from app.modules.data.series import build_series

ROLES = ("date", "measure", "dimension", "ignore")
AGGS = ("sum", "avg", "last", "none")
VIEW_ROWS, VIEW_COLS = 60, 40
ASK_BELOW = 0.6


# -- files -----------------------------------------------------------------------------------------------
def upload_dir(org_id: int) -> Path:
    p = Path(current_app.instance_path) / "uploads" / str(org_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def store_file(org_id: int, data: bytes, filename: str) -> str:
    ext = Path(filename).suffix.lower()[:6] or ".bin"
    name = f"{uuid.uuid4().hex}{ext}"
    (upload_dir(org_id) / name).write_bytes(data)
    return name


def file_path(ds: Dataset) -> Path | None:
    return (upload_dir(ds.org_id) / ds.stored_as) if ds.stored_as else None


def load_sheets(ds: Dataset) -> list[Sheet]:
    p = file_path(ds)
    if not p or not p.is_file():
        raise ReadError("missing")
    return read_file(p.read_bytes(), ds.filename)


def delete_file(ds: Dataset) -> None:
    p = file_path(ds)
    if p and p.is_file():
        p.unlink()


# -- one file, several sheets: every sheet that holds a table becomes its own dataset (own columns, own series), tied by `meta.group` --------------------
MIN_TABLE_ROWS = 3


def table_sheets(sheets: list[Sheet]) -> list[int]:
    """Indexes of the sheets that look like a table (a header and at least two rows); the first sheet when none does."""
    return [i for i, sh in enumerate(sheets) if len(sh.grid) >= MIN_TABLE_ROWS] or [0]


def has_data_columns(ds: Dataset) -> bool:
    """A sheet is worth keeping when it has a measure (numbers to follow) — a notes or legend sheet has none."""
    return any(c.get("role") == "measure" for c in ds.columns or [])


def make_sheet_dataset(org_id: int, user_id, raw: bytes, filename: str, sheets: list[Sheet], idx: int, *, group: str = "", multi: bool = False) -> Dataset:
    """A dataset for sheet `idx` of an uploaded file: its own copy of the file (so deleting one sheet never breaks another), analyzed and not yet saved."""
    stem = Path(filename).stem[:120] or "data"
    ds = Dataset(org_id=org_id, created_by=user_id, filename=filename[:200], name=(f"{stem} — {sheets[idx].name}" if multi else stem)[:150])
    ds.stored_as = store_file(org_id, raw, filename)
    ds.sheet_index = idx
    ds.meta = {"group": group} if group else {}
    analyze(ds, sheets)
    return ds


def siblings(ds: Dataset) -> list[Dataset]:
    """The datasets that came from the same file (including `ds`), in sheet order."""
    group = (ds.meta or {}).get("group")
    if not group:
        return [ds]
    rows = Dataset.query.filter_by(org_id=ds.org_id).order_by(Dataset.sheet_index, Dataset.id).all()
    return [d for d in rows if (d.meta or {}).get("group") == group]


def sheet_tabs(ds: Dataset) -> list[dict]:
    """Every sheet of the file as a tab: {name, index, ds (its dataset or None), current}. Sheets without a dataset can be added with one click."""
    names = (ds.meta or {}).get("sheets") or []
    by_sheet = {d.sheet_index: d for d in siblings(ds)}
    return [{"name": n, "index": i, "ds": by_sheet.get(i), "current": by_sheet.get(i) is not None and by_sheet[i].id == ds.id} for i, n in enumerate(names)]


# -- table -----------------------------------------------------------------------------------------------
def current_table(ds: Dataset, sheets: list[Sheet] | None = None) -> tuple[Sheet, Table]:
    sheets = sheets or load_sheets(ds)
    sh = sheets[min(max(ds.sheet_index or 0, 0), len(sheets) - 1)]
    return sh, build_table(sh.grid, header_row=ds.header_row, sheet_name=sh.name, filename=ds.filename, year=ds.year_hint)


def _plain(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


def _strided(rows: list[list], cap: int = 400) -> list[list]:
    if len(rows) <= cap:
        return rows
    step = len(rows) / cap
    return [rows[int(i * step)] for i in range(cap)]


NOTE_MAX = 400          # characters of explanation per column
FILE_NOTE_MAX = 800     # characters of explanation about the whole file


def notes_for_table(ds: Dataset, headers) -> dict[int, str]:
    """The user's explanations that still apply to this reading: same column position AND same header text.
    (After the user switches sheet or header row, a note written for another column must not follow the position.)"""
    out: dict[int, str] = {}
    for k, v in ((ds.meta or {}).get("col_notes") or {}).items():
        try:
            i = int(k)
        except (TypeError, ValueError):
            continue
        if isinstance(v, dict) and v.get("t") and i < len(headers) and str(headers[i]) == v.get("h"):
            out[i] = v["t"]
    return out


def save_notes(ds: Dataset, *, file_note: str | None = None, col_notes: dict[int, str] | None = None) -> None:
    """Keep what the user wrote to explain the file / its columns to the model. Only the fields given are touched."""
    meta = dict(ds.meta or {})
    if file_note is not None:
        meta["file_note"] = file_note.strip()[:FILE_NOTE_MAX]
    store = dict(meta.get("col_notes") or {})
    cols = {c["index"]: c for c in ds.columns or []}
    for idx, text in (col_notes or {}).items():
        c = cols.get(idx)
        if c is None:
            continue
        text = (text or "").strip()[:NOTE_MAX]
        if text:
            store[str(idx)] = {"t": text, "h": str(c.get("header", ""))}
        else:
            store.pop(str(idx), None)
    meta["col_notes"] = store
    ds.meta = meta


def column_cards(ds: Dataset) -> list[dict]:
    """One card per column for the mapping page: the column, its sheet letter, its open question and the user's note.
    Columns that still need an answer come first."""
    qs = {q["column"]: q for q in ds.questions or []}
    store = (ds.meta or {}).get("col_notes") or {}
    cards = []
    for c in ds.columns or []:
        i = c["index"]
        n = store.get(str(i))
        note = n["t"] if isinstance(n, dict) and n.get("h") == str(c.get("header", "")) else ""
        cards.append({"col": c, "idx": i, "letter": letter_of(ds, i), "q": qs.get(i), "note": note, "about": describe_column(c), "meaning": c.get("meaning") or ""})
    cards.sort(key=lambda x: (0 if x["q"] else 1, x["idx"]))
    return cards


def describe_column(c: dict) -> str:
    """Two or three plain sentences on what a column is and what the product will do with it (from the mapping, not from a model)."""
    from app.core import i18n
    from app.core.formatting import unit_text

    ex = "، ".join(str(x) for x in (c.get("examples") or [])[:3])
    role = c.get("role")
    if role == "date":
        return i18n.t("data.about_col.date", ex=ex)
    if role == "dimension":
        return i18n.t("data.about_col.dimension", ex=ex)
    if role == "measure":
        unit = unit_text(c.get("unit"))
        head = i18n.t("data.about_col.measure_unit" if unit else "data.about_col.measure", unit=unit, ex=ex)
        agg = i18n.t(f"data.about_col.agg_{c.get('aggregation') if c.get('aggregation') in ('sum', 'avg', 'last') else 'sum'}")
        return f"{head} {agg} {i18n.t('data.about_col.' + ('lower' if c.get('direction') == 'lower_better' else 'higher'))}"
    return i18n.t("data.about_col.ignore")


def analyze(ds: Dataset, sheets: list[Sheet] | None = None, runner=None, keep_user: bool = False) -> None:
    """(Re)read the chosen sheet, measure every column, and ask the AI (or the rules) what each column means.
    The user's explanations (file note + per-column notes) go to the model with the data. With keep_user=True the columns the
    user already decided by hand are kept exactly as they are."""
    sheets = sheets or load_sheets(ds)
    sh, table = current_table(ds, sheets)
    prof = profile_columns(table.headers, table.rows)
    old_cols = {c["index"]: c for c in ds.columns or []}
    old_meta = ds.meta or {}
    notes = notes_for_table(ds, table.headers)
    file_note = str(old_meta.get("file_note") or "")
    inputs = {"sheet": sh.name, "layout": table.layout, "headers": table.headers, "row_count": len(table.rows), "profile": prof,
              "rows": [[_plain(c) for c in r] for r in _strided(table.rows)]}
    if notes or file_note:
        inputs["notes"] = {"file": file_note, "columns": notes}
    res = (runner or (lambda i: ai.run("map_columns", i)))(inputs)
    out = res.data
    by_idx = {p["index"]: p for p in prof}
    cols = []
    for c in out["columns"]:
        header = str(table.headers[c["index"]] if c["index"] < len(table.headers) else "")
        pr = by_idx[c["index"]]
        new = {**c, "state": "ai", "type": pr["type"], "examples": pr["examples"][:3], "header": header, "distinct": pr.get("distinct"),
               **({"min": pr["min"], "max": pr["max"]} if pr.get("min") is not None and pr.get("max") is not None else {})}
        if c["index"] in notes:
            new["explained"] = True
        old = old_cols.get(c["index"])
        if keep_user and old and old.get("state") == "user" and old.get("header") == header:
            new = old                                   # a decision the user took by hand is never overwritten
        cols.append(new)
    kept = {c["index"] for c in cols if c.get("state") == "user"} if keep_user else set()
    ds.columns = cols
    ds.questions = [q for q in out["questions"] if q["column"] not in kept]
    ds.summary = out["table_summary"]
    ds.layout = table.layout
    tnotes = list(dict.fromkeys([*table.notes, *sh.notes]))
    ds.meta = {"sheets": [s.name for s in sheets], "provider": res.provider, "model": res.model, "external": res.external,
               "fell_back": res.fell_back, "errors": res.errors[:3], "rows": len(table.rows), "excluded": len(table.excluded),
               "header_row": table.header_row, "assumed_year": table.assumed_year, "truncated": sh.truncated, "notes": tnotes,
               "title": table.title, "ai_ms": res.ms, "phys": table.phys,
               "col_notes": old_meta.get("col_notes") or {}, "file_note": file_note, "sheet_name": sh.name,
               "highlights": out.get("highlights") or [],
               **({"group": old_meta["group"]} if old_meta.get("group") else {})}


# -- column editing --------------------------------------------------------------------------------------
def _col(ds: Dataset, idx: int) -> dict | None:
    return next((c for c in ds.columns or [] if c["index"] == idx), None)


def edit_column(ds: Dataset, idx: int, *, role: str | None = None, label: str | None = None, unit: str | None = None,
                aggregation: str | None = None, direction: str | None = None) -> dict | None:
    cols = [dict(c) for c in ds.columns or []]
    c = next((c for c in cols if c["index"] == idx), None)
    if c is None:
        return None
    before = c.get("role")
    if role in ROLES:
        c["role"] = role
    if label is not None and label.strip():
        c["label"] = label.strip()[:80]
    if unit is not None:
        c["unit"] = unit.strip()[:12]
    if aggregation in AGGS:
        c["aggregation"] = aggregation
    if direction in ("higher_better", "lower_better"):
        c["direction"] = direction
    if c["role"] == "measure" and c.get("aggregation") in (None, "none"):
        c["aggregation"] = "sum"
    if c["role"] != "measure":
        c["aggregation"], c["unit"] = "none", ""
    c.update(confidence=1.0, state="user", reason="user")
    if c["role"] != before or c.get("label") != (next((o for o in ds.columns or [] if o["index"] == idx), {}) or {}).get("label"):
        from app.ai.tasks.map_columns import rule_meaning       # what the column was said to mean no longer holds: say it again from the new role

        prof = {"type": c.get("type"), "min": c.get("min"), "max": c.get("max"), "distinct": c.get("distinct"), "examples": c.get("examples") or []}
        c["meaning"] = rule_meaning(c.get("header", ""), c, prof, "ar")
    ds.columns = cols
    ds.questions = [q for q in ds.questions or [] if q["column"] != idx]
    return c


def answer_question(ds: Dataset, idx: int, option: int) -> dict | None:
    q = next((q for q in ds.questions or [] if q["column"] == idx), None)
    if q is None or not (0 <= option < len(q["options"])):
        return None
    o = q["options"][option]
    return edit_column(ds, idx, role=o["role"], unit=o.get("unit", ""), aggregation=o.get("aggregation"))


def open_questions(ds: Dataset) -> list[dict]:
    cols = {c["index"]: c for c in ds.columns or []}
    return [{**q, "col": cols.get(q["column"]), "letter": letter_of(ds, q["column"])} for q in ds.questions or [] if q["column"] in cols]


def letter_of(ds: Dataset, logical_idx: int) -> str:
    """The spreadsheet letter of the first file column a logical column comes from (for wide files: the first month column)."""
    phys = (ds.meta or {}).get("phys") or []
    return col_letter(phys[logical_idx][0]) if logical_idx < len(phys) and phys[logical_idx] else col_letter(logical_idx)


def check_ready(ds: Dataset) -> str | None:
    """An error code when the mapping cannot produce series yet."""
    roles = [c["role"] for c in ds.columns or []]
    if "date" not in roles:
        return "needs_date"
    if "measure" not in roles:
        return "needs_measure"
    return None


# -- the grid shown on the mapping page ------------------------------------------------------------------
def grid_view(ds: Dataset, sheets: list[Sheet] | None = None) -> dict:
    """Everything the template needs to draw the file like a spreadsheet, annotated with what was understood."""
    sheets = sheets or load_sheets(ds)
    sh, table = current_table(ds, sheets)
    cols = {c["index"]: c for c in ds.columns or []}
    width = min(VIEW_COLS, len(sh.grid[0]) if sh.grid else 0)
    # grid column -> logical column (months of a wide file all map to the value column)
    owner: dict[int, int] = {}
    for li, phys in enumerate(table.phys):
        for pc in phys:
            owner[pc] = li                       # later wins: months belong to the value column, not the "Date" helper
    value_li = len(table.phys) - 1
    months = set(table.phys[-1]) if table.layout == "wide" and table.phys else set()
    hr = table.header_row
    excluded = {e["row"] for e in table.excluded}

    annotations = []
    for pc in range(width):
        li = owner.get(pc)
        c = cols.get(li) if li is not None else None
        a = {"letter": col_letter(pc), "index": pc, "col": c, "logical": li, "month": pc in months}
        a["unsure"] = bool(c and c["confidence"] < ASK_BELOW and c["state"] != "user")
        annotations.append(a)

    groups: list[dict] = []                      # annotation cards; the month columns of a wide file share one card
    for a in annotations:
        if groups and a["month"] and groups[-1]["month"] and groups[-1]["logical"] == a["logical"]:
            groups[-1]["span"] += 1
            groups[-1]["letters"].append(a["letter"])
        else:
            groups.append({**a, "span": 1, "letters": [a["letter"]]})

    rows = []
    for ri, row in enumerate(sh.grid[:VIEW_ROWS]):
        kind = "pre" if ri < hr else "head" if ri == hr else "total" if ri in excluded else "body"
        cells = []
        for pc in range(width):
            v = row[pc] if pc < len(row) else None
            cls = []
            a = annotations[pc]
            c = a["col"]
            if kind == "body" and c and v not in (None, ""):
                if c["role"] == "measure" and parse_number(v) is None:
                    cls.append("bad")
                elif c["role"] == "date" and not a["month"] and parse_period(v) is None:
                    cls.append("bad")
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                cls.append("n")
            cells.append({"v": _plain(v), "cls": " ".join(cls)})
        rows.append({"n": ri + 1, "kind": kind, "cells": cells})
    return {"sheet": sh, "annotations": annotations, "groups": groups, "rows": rows, "more_rows": max(0, len(sh.grid) - VIEW_ROWS),
            "more_cols": max(0, (len(sh.grid[0]) if sh.grid else 0) - VIEW_COLS), "table": table, "header_row": hr}


# -- series ----------------------------------------------------------------------------------------------
def confirm(ds: Dataset, user_id: int | None = None) -> tuple[int, int, int]:
    """Build / refresh the series of a dataset. Series that already exist keep their id (goals may point to them).
    Records what changed against the previous data in the dataset's version history, then tells other modules (hook "series.updated")."""
    err = check_ready(ds)
    if err:
        raise ValueError(err)
    _, table = current_table(ds)
    date_col = next(c for c in ds.columns if c["role"] == "date")
    kind = date_col.get("date_kind") or _date_kind(table, date_col["index"])
    built = build_series(table, ds.columns, date_kind=kind, fixes=ds.fixes or {})
    existing = {(s.name, s.dimension): s for s in ds.series}
    before = {key: s.pairs() for key, s in existing.items()}
    keep, added = set(), 0
    for sd in built:
        key = (sd.name[:200], sd.dimension)
        pts = [[p.isoformat(), round(v, 6)] for p, v in sd.points]
        s = existing.get(key)
        if s is None:
            s = Series(org_id=ds.org_id, dataset_id=ds.id, name=sd.name[:200], dimension=sd.dimension)
            db.session.add(s)
            added += 1
        s.unit, s.direction, s.aggregation, s.period_months, s.points = sd.unit, sd.direction, sd.aggregation, sd.period_months, pts
        keep.add(key)
    removed = 0
    for key, s in existing.items():
        if key not in keep:
            Link.query.filter_by(org_id=ds.org_id, target_type="series", target_id=s.id).delete()
            db.session.delete(s)
            removed += 1
    ds.status = "ready"
    db.session.flush()
    after = {(s.name, s.dimension): s.pairs() for s in ds.series}
    ver = current_version(ds, create=True)
    ver.confirmed = True
    ver.diff = diff_series(before, after, first=not before)
    ds.meta = {**(ds.meta or {}), "fixes_applied": sum(1 for v in (ds.fixes or {}).values() if v)}
    db.session.flush()
    current_app.extensions["modules"].hook("series.updated", series=list(ds.series), user_id=user_id)
    return added, len(keep) - added, removed


def _date_kind(table: Table, idx: int) -> str | None:
    prof = profile_columns(table.headers, table.rows)
    return prof[idx].get("date_kind") if idx < len(prof) else None


def delete_dataset(ds: Dataset) -> None:
    for s in ds.series:
        Link.query.filter_by(org_id=ds.org_id, target_type="series", target_id=s.id).delete()
    delete_file(ds)
    db.session.delete(ds)


# -- linking goals to series -------------------------------------------------------------------------------
def linked_series_id(org_id: int, kr_id: int) -> int | None:
    l = Link.query.filter_by(org_id=org_id, source_type="key_result", source_id=kr_id, target_type="series", kind="measured_by").first()
    return l.target_id if l else None


def set_kr_series(org_id: int, kr_id: int, series_id: int | None) -> None:
    Link.query.filter_by(org_id=org_id, source_type="key_result", source_id=kr_id, target_type="series", kind="measured_by").delete()
    if series_id and (s := db.session.get(Series, series_id)) and s.org_id == org_id:
        db.session.add(Link(org_id=org_id, source_type="key_result", source_id=kr_id, target_type="series", target_id=s.id, kind="measured_by"))


def org_series(org_id: int) -> list[Series]:
    return (Series.query.join(Dataset, Series.dataset_id == Dataset.id)
            .filter(Series.org_id == org_id).order_by(Dataset.id, Series.id).all())   # a dataset waiting for a newer file's review keeps its series


def refresh_summary(ds: Dataset, lang: str) -> None:
    """Rule-based one-line description from the current mapping (used when no model wrote one, and by the demo seed)."""
    from app.core import i18n

    from app.ai.tasks.map_columns import describe

    ds.summary = describe(ds.columns or [], (ds.meta or {}).get("rows", 0), lang)


# -- understanding the table: what looks odd, and what the user decided ------------------------------------------
def quality_report(ds: Dataset) -> list[dict]:
    """Per measure column: the findings on the RAW series (with the user's decisions marked) and the series as it will be after the decisions."""
    if not ds.columns or check_ready(ds):
        return []
    _, table = current_table(ds)
    date_col = next(c for c in ds.columns if c["role"] == "date")
    kind = date_col.get("date_kind") or _date_kind(table, date_col["index"])
    raw = build_series(table, ds.columns, date_kind=kind)
    fixed = {(sd.column, sd.dimension): sd for sd in build_series(table, ds.columns, date_kind=kind, fixes=ds.fixes or {})}
    out = []
    for sd in raw:
        if sd.dimension is not None:
            continue
        fx = (ds.fixes or {}).get(str(sd.column)) or {}
        findings = quality.inspect(sd.points, sd.period_months, aggregation=sd.aggregation, fixes=fx)
        for f in findings:
            f.column, f.series = sd.column, sd.name
        after = fixed.get((sd.column, None))
        out.append({"column": sd.column, "label": sd.name, "unit": sd.unit, "findings": findings, "raw": sd.points, "after": after.points if after else [],
                    "changed": bool(fx)})
    return out


def open_findings(report: list[dict]) -> int:
    return sum(1 for r in report for f in r["findings"] if f.severity == "warn" and f.open)


def set_fix(ds: Dataset, column: int, code: str, option: str, period: str | None = None) -> bool:
    """Record the user's decision about one finding. option "reset" takes the decision back."""
    fixes = {k: dict(v) for k, v in (ds.fixes or {}).items()}
    fx = fixes.setdefault(str(column), {})
    allowed = {"gaps": ("interpolate", "zero", "leave"), "cumulative": ("to_period", "keep"), "partial_last": ("drop", "keep"), "jump": ("keep", "exclude")}
    if code not in allowed or (option != "reset" and option not in allowed[code]):
        return False
    if code == "jump":
        if not period:
            return False
        for k in ("confirmed", "exclude"):
            fx[k] = [p for p in fx.get(k, []) if p != period]
        if option != "reset":
            fx["confirmed" if option == "keep" else "exclude"].append(period)
    else:
        key = {"gaps": "gaps", "cumulative": "cumulative", "partial_last": "drop_last"}[code]
        if option == "reset":
            fx.pop(key, None)
        else:
            fx[key] = option
    fixes[str(column)] = {k: v for k, v in fx.items() if v not in ([], None)}
    ds.fixes = {k: v for k, v in fixes.items() if v}
    return True


# -- versions and what changed -------------------------------------------------------------------------------------
def current_version(ds: Dataset, create: bool = False) -> DatasetVersion | None:
    vs = sorted(ds.versions, key=lambda v: v.number)
    if vs:
        return vs[-1]
    return add_version(ds, ds.filename, ds.stored_as, ds.created_by) if create else None


def add_version(ds: Dataset, filename: str, stored_as: str, user_id: int | None) -> DatasetVersion:
    n = max([v.number for v in ds.versions] or [0]) + 1
    v = DatasetVersion(dataset_id=ds.id, number=n, filename=filename, stored_as=stored_as, uploaded_by=user_id)
    db.session.add(v)
    ds.versions.append(v)
    return v


def diff_series(before: dict, after: dict, *, first: bool = False) -> dict:
    """What a new file changed, series by series: new periods, REVISED past values (the part that can change a verdict), added/removed series."""
    new_periods, revised, changed = 0, [], set()
    firsts, lasts = [], []
    for key, pts in after.items():
        old = dict(before.get(key) or [])
        for d, v in pts:
            if d not in old:
                if old:
                    new_periods += 1
                    firsts.append(d)
                    lasts.append(d)
                    changed.add(key)
            elif abs(v - old[d]) > 1e-6 and (old[d] == 0 or abs(v - old[d]) / abs(old[d]) >= 0.001):
                pct = None if old[d] == 0 else (v - old[d]) / abs(old[d])
                revised.append({"series": key[0], "period": d.isoformat(), "old": old[d], "new": v, "pct": pct})
                changed.add(key)
    revised.sort(key=lambda r: -(abs(r["pct"]) if r["pct"] is not None else 9e9))
    return {"first": first, "series": len(after), "new_periods": new_periods, "first_new": min(firsts).isoformat() if firsts else None,
            "last_new": max(lasts).isoformat() if lasts else None, "revised_count": len(revised), "revised": revised[:30],
            "new_series": [k[0] for k in after if k not in before and before], "removed_series": [k[0] for k in before if k not in after],
            "changed_series": len(changed), "latest": _iso(max((p[-1][0] for p in after.values() if p), default=None))}


def _iso(d):
    return d.isoformat() if d else None


def _norm_header(h) -> str:
    return " ".join(str(h or "").casefold().split())


def update_dataset(ds: Dataset, data: bytes, filename: str, user_id: int | None, runner=None) -> str:
    """Replace the file of an existing dataset with a newer version, keeping what the user already told us.

    Columns are matched by NAME (not position), the earlier mapping and decisions carry over, and only what is new is asked again.
    Returns "auto" when nothing needs the user and the series were refreshed, otherwise "review" (the map page opens with the remaining questions)."""
    old_cols = [dict(c) for c in ds.columns or []]
    old_fixes = {k: dict(v) for k, v in (ds.fixes or {}).items()}
    old_sheet = ((ds.meta or {}).get("sheets") or [None] * (ds.sheet_index + 1))[ds.sheet_index]
    sheets = read_file(data, filename)                       # raises ReadError before anything is touched
    if not ds.versions and ds.stored_as:
        add_version(ds, ds.filename, ds.stored_as, ds.created_by).confirmed = True
    stored = store_file(ds.org_id, data, filename)
    ds.filename, ds.stored_as = filename, stored
    names = [x.name for x in sheets]
    ds.sheet_index = names.index(old_sheet) if old_sheet in names else 0
    ds.header_row = None
    analyze(ds, sheets, runner=runner)
    by_header = {_norm_header(c.get("header")): c for c in old_cols if c.get("header")}
    new_fixes, matched = {}, set()
    for c in ds.columns:
        o = by_header.get(_norm_header(c.get("header")))
        if not o:
            continue
        matched.add(_norm_header(c.get("header")))
        for k in ("role", "label", "unit", "aggregation", "direction", "date_kind", "state", "confidence", "reason"):
            if k in o:
                c[k] = o[k]
        if str(o["index"]) in old_fixes:
            new_fixes[str(c["index"])] = old_fixes[str(o["index"])]
    carried = {c["index"] for c in ds.columns if _norm_header(c.get("header")) in matched}
    ds.questions = [q for q in ds.questions or [] if q["column"] not in carried]
    ds.fixes = new_fixes
    lost = [c for h, c in by_header.items() if h not in matched and c.get("role") in ("date", "measure")]
    add_version(ds, filename, stored, user_id)
    db.session.flush()
    if not ds.questions and not lost and not check_ready(ds):
        confirm(ds, user_id=user_id)
        return "auto"
    ds.status = "draft"
    ds.meta = {**(ds.meta or {}), "update": {"lost": [c.get("label") or c.get("header") for c in lost],
                                             "new": [c.get("label") or c.get("header") for c in ds.columns if _norm_header(c.get("header")) not in matched]}}
    return "review"


def affected_series(diff: dict | None, ds: Dataset) -> list[Series]:
    """Series whose data a version changed (new periods or revised values): the ones goals may need to re-check."""
    if not diff or diff.get("first"):
        return []
    names = {r["series"] for r in diff.get("revised", [])}
    if diff.get("new_periods"):
        names |= {s.name for s in ds.series}
    return [s for s in ds.series if s.name in names]
