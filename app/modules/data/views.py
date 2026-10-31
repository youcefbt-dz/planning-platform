"""Data routes: upload a spreadsheet, see it like a spreadsheet, confirm what the columns mean, browse series, check a target."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from flask import abort, current_app, flash, g, jsonify, redirect, render_template, request, send_from_directory, url_for

from flask_login import current_user

from app import ai
from app.core import forms as F
from app.core.charts import line_chart
from app.modules.data.chart import quality_chart
from app.core.i18n import t, tn
from app.core.permissions import require
from app.core.models import Link
from app.core.services import entity_title, entity_url, log_activity
from app.extensions import db
from app.modules.data import bp, reality, service
from app.modules.data import dashboard as dash
from app.modules.data.ingest.reader import EXTENSIONS, MAX_BYTES, ReadError
from app.modules.data.models import Dataset, Series

SAMPLES = Path(__file__).resolve().parents[3] / "samples"


def _dataset(id: int) -> Dataset:
    return F.get_scoped(Dataset, id)


def _series(id: int) -> Series:
    return F.get_scoped(Series, id)


def _ai_state() -> dict:
    """What the user should know before data is analysed: who will read it, and whether consent is missing."""
    hub = ai.get_hub()
    status = hub.status()
    external = [s for s in status if s["available"] and not s["local"] and s["name"] != "offline"]
    local = [s for s in status if s["available"] and s["local"] and s["name"] != "offline"]
    consent = ai.org_consent(g.org)
    return {"external": bool(external), "local": bool(local), "consent": consent, "needs_consent": bool(external) and not local and not consent,
            "names": [s["name"] for s in (local or external)]}


# -- the visual page ------------------------------------------------------------------------------------------------------------------
@bp.get("/dashboard")
def dashboard():
    """Measure tabs, what deserves attention, the main chart, then drivers / branches / season. (Typed requests live on their own page: /data/ask.)"""
    if request.args.get("q"):
        return redirect(url_for("data.ask", q=request.args["q"], m=request.args.get("m")))
    series = service.org_series(g.org.id)
    ms = dash.measures(series)
    ctx = {"ms": ms, "ai_state": _ai_state(), "samples": sorted(p.name for p in SAMPLES.glob("*.xlsx")), "max_mb": MAX_BYTES // (1024 * 1024), "exts": EXTENSIONS}
    if not ms:
        return render_template("data/dashboard.html", no_data=True, **ctx)
    tabs = dash.tabs(ms)
    sel = next((m for m in ms if m.id == request.args.get("m")), ms[0])
    layout = {k: dash.build(sp, ms, g.org.id) for k, sp in dash.default_specs(sel).items()}
    layout = {k: v for k, v in layout.items() if v}
    return render_template("data/dashboard.html", no_data=False, tabs=tabs, sel=sel, sel_tab=next((x for x in tabs if x["m"].id == sel.id), None), found=dash.attention(sel),
                           main=layout.get("main"), drivers=layout.get("drivers"), branches=layout.get("branches"), season=layout.get("season"),
                           can_goal=current_app.extensions["modules"].is_enabled("goals"), **ctx)


# -- the chart page: pick a measure, pick a shape, adjust -----------------------------------------------------------------------------------
CHART_KINDS = (  # (kind, icon, needs branches, needs a second measure, which options apply)
    ("trend", "chart-line", False, False, ("branch", "months")),
    ("bars", "chart-bar", False, False, ("branch", "months", "by")),
    ("growth", "trending-up", False, False, ("branch", "months", "by")),
    ("cumulative", "chart-area", False, False, ("branch", "months")),
    ("branches", "layout-grid", True, False, ("months",)),
    ("contribution", "chart-dots", True, False, ("months",)),
    ("share", "chart-donut", True, False, ()),
    ("ranking", "list-numbers", True, False, ()),
    ("stacked", "chart-area", True, False, ("months",)),
    ("heatmap", "calendar", False, False, ()),
    ("compare", "arrows-diff", False, True, ("months",)),
    ("scatter", "chart-dots", False, True, ()),
    ("table", "table", False, False, ("branch", "months")),
    ("kpi", "target", False, False, ("branch",)),
)


@bp.get("/charts")
def charts():
    ms = dash.measures(service.org_series(g.org.id))
    if not ms:
        return render_template("data/charts.html", no_data=True, ms=ms)
    sel = next((m for m in ms if m.id == request.args.get("m")), ms[0])
    kind = request.args.get("kind") if request.args.get("kind") in dash.KINDS else "trend"
    others = [m for m in ms if m.id != sel.id]
    info = {k: (i, nb, n2, opts) for k, i, nb, n2, opts in CHART_KINDS}
    def usable(k):
        _, nb, n2, _o = info[k]
        return not (nb and len(sel.branches) < 2) and not (n2 and not others)
    if not usable(kind):
        kind = "trend"
    raw = {"kind": kind, "measure": sel.id, "branch": request.args.get("branch") or None, "months": request.args.get("months", type=int),
           "by": request.args.get("by") or None, "measure2": request.args.get("m2") or (others[0].id if others else None)}
    spec = dash.validate_spec(raw, ms)
    chart = dash.build(spec, ms, g.org.id) if spec else None
    return render_template("data/charts.html", no_data=False, ms=ms, sel=sel, kind=kind, kinds=CHART_KINDS, usable={k: usable(k) for k in info}, others=others,
                           opts=info[kind][3], chart=chart, spec=spec or {}, args=raw)


# -- the assistant: its own page ---------------------------------------------------------------------------------------------------------------
@bp.get("/ask")
def ask():
    ms = dash.measures(service.org_series(g.org.id))
    if not ms:
        return render_template("data/ask.html", no_data=True, ms=ms, ai_hint=_ai_state())
    sel = next((m for m in ms if m.id == request.args.get("m")), ms[0])
    return render_template("data/ask.html", no_data=False, ms=ms, sel=sel, ai_hint=_ai_state(), ask=_ask(ms), q=request.args.get("q", ""), examples=_examples(ms))


def _examples(ms) -> list[str]:
    m = ms[0]
    out = [t("data.dash.ex_why", name=m.short)]
    if len(m.branches) >= 2:
        out.append(t("data.dash.ex_branches", name=m.short))
    out.append(t("data.dash.ex_season", name=m.short))
    if len(ms) > 1:
        out.append(t("data.dash.ex_all"))
    return out


def _why_rules(res) -> dict | None:
    """Why the built-in rules answered instead of a model, in terms the owner can act on (None when a model answered)."""
    if res.provider not in ("offline", "") and not res.fell_back:
        return None
    st = ai.get_hub().status()
    configured = any(x["available"] and x["name"] != "offline" for x in st)
    errs = " ".join(res.errors or [])
    if "consent" in errs:
        return {"code": "consent", "action": can_manage()}
    if "demo" in errs:
        return {"code": "demo"}
    if "quota" in errs:
        return {"code": "quota"}
    if configured:
        return {"code": "failed", "detail": (res.errors or [""])[-1][:120]}
    return {"code": "none"}


def can_manage() -> bool:
    from app.core.permissions import can as _can

    try:
        return bool(_can("settings.manage"))
    except Exception:
        return False


def _ask(ms) -> dict | None:
    """What a typed request turns into: up to three charts, two measures compared, or one question when it is unclear. The model (or the built-in rules)
    only proposes specs; `validate_spec` decides what is drawn and every sentence is computed."""
    q = (request.args.get("q") or "").strip()[:200]
    if not q:
        return None
    catalog = [{"id": m.id, "name": m.name, "unit": m.unit, "months": len(m.pts), "branches": [b.dimension for b in m.branches]} for m in ms]
    res = ai.run("draw_chart", {"request": q, "catalog": catalog})
    model = res.provider not in ("offline", "") and not res.fell_back
    why = _why_rules(res)
    data = res.data if isinstance(res.data, dict) else {}
    charts = []
    for raw in data.get("charts") or []:
        spec = dash.validate_spec(raw, ms)
        c = dash.build(spec, ms, g.org.id) if spec else None
        if c:
            charts.append(c)
    if charts:
        return {"charts": charts, "q": q, "model": model, "why": why, "note": data.get("note")}
    if data.get("ask"):
        names = [n for n in data.get("choices") or []][:5]
        return {"ask": True, "q": q, "model": model, "why": why, "missing": data.get("missing") or [],
                "choices": [{"label": n, "href": url_for("data.ask", q=_follow_up(q, n, data.get("ask")), m=request.args.get("m"))} for n in names]}
    known = any(m.id == str(raw.get("measure")) for raw in (data.get("charts") or []) for m in ms)
    return {"error": "unavailable" if known else "none", "q": q, "model": model, "why": why}


def _follow_up(q: str, choice: str, kind) -> str:
    """The query a clicked choice sends: a pair becomes an explicit comparison of two names, a single name is added to the request."""
    if kind == "pair":
        return f"قارن بين {choice}"
    return f"{q} {choice}"


# -- index / upload ------------------------------------------------------------------------------------------------
@bp.get("/")
def index():
    datasets = Dataset.query.filter_by(org_id=g.org.id).order_by(Dataset.id.desc()).all()
    series = service.org_series(g.org.id)
    return render_template("data/index.html", datasets=datasets, series=series, ai_state=_ai_state(), samples=sorted(p.name for p in SAMPLES.glob("*.xlsx")),
                           max_mb=MAX_BYTES // (1024 * 1024), exts=EXTENSIONS)


@bp.get("/sample/<path:name>")
def sample(name):
    if name not in {p.name for p in SAMPLES.glob("*.xlsx")}:
        abort(404)
    return send_from_directory(SAMPLES, name, as_attachment=True)


@bp.post("/upload")
@require("data.edit")
def upload():
    f = request.files.get("file")
    if not f or not f.filename:
        flash(t("data.errors.no_file"), "error")
        return redirect(url_for("data.index"))
    return _ingest(f.read(MAX_BYTES + 1), f.filename)


@bp.post("/upload-sample/<path:name>")
@require("data.edit")
def upload_sample(name):
    if name not in {p.name for p in SAMPLES.glob("*.xlsx")}:
        abort(404)
    return _ingest((SAMPLES / name).read_bytes(), name)


def _ingest(raw: bytes, filename: str):
    """Read the file; every sheet that holds a table becomes its own dataset (tied together by a group), the rest are listed and can be added later."""
    import secrets

    from app.modules.data.ingest.reader import read_file

    uid = current_user.id if current_user.is_authenticated else None
    try:
        sheets = read_file(raw, filename)
        wanted = service.table_sheets(sheets)
        group = secrets.token_hex(6) if len(wanted) > 1 else ""
        made = []
        for n, i in enumerate(wanted):
            d = service.make_sheet_dataset(g.org.id, uid, raw, filename, sheets, i, group=group, multi=len(wanted) > 1)
            if n == 0 or service.has_data_columns(d):
                made.append(d)
            else:                                        # a notes / legend sheet: nothing to follow in it
                service.delete_file(d)
        if len(made) == 1:
            made[0].meta = {k: v for k, v in (made[0].meta or {}).items() if k != "group"}
            if len(wanted) > 1:
                made[0].name = Path(filename).stem[:150] or "data"
        for d in made:
            db.session.add(d)
            db.session.flush()
            service.add_version(d, d.filename, d.stored_as, d.created_by)
            log_activity("created", "dataset", d.id, d.name)
    except ReadError as e:
        db.session.rollback()
        flash(t(f"data.errors.{e}"), "error")
        return redirect(url_for("data.index"))
    db.session.commit()
    if len(made) > 1:
        flash(t("data.flash.sheets", n=len(made), names="، ".join((d.meta or {}).get("sheet_name", "") for d in made)), "success")
    return redirect(url_for("data.map", id=made[0].id))


@bp.post("/<int:id>/add-sheet/<int:idx>")
@require("data.edit")
def add_sheet(id, idx):
    """Turn one more sheet of the same file into its own dataset (a sheet that was not taken automatically)."""
    import secrets

    ds = _dataset(id)
    try:
        sheets = service.load_sheets(ds)
        raw = service.file_path(ds).read_bytes()
    except ReadError:
        flash(t("data.errors.missing"), "error")
        return redirect(url_for("data.map", id=ds.id))
    if idx >= len(sheets) or any(d.sheet_index == idx for d in service.siblings(ds)):
        return redirect(url_for("data.map", id=ds.id))
    group = (ds.meta or {}).get("group")
    if not group:                                        # the file becomes a group of two now
        group = secrets.token_hex(6)
        ds.meta = {**(ds.meta or {}), "group": group}
        stem = Path(ds.filename).stem[:120] or "data"
        ds.name = f"{stem} — {sheets[ds.sheet_index].name}"[:150]
    new = service.make_sheet_dataset(g.org.id, current_user.id if current_user.is_authenticated else None, raw, ds.filename, sheets, idx, group=group, multi=True)
    db.session.add(new)
    db.session.flush()
    service.add_version(new, new.filename, new.stored_as, new.created_by)
    log_activity("created", "dataset", new.id, new.name)
    db.session.commit()
    return redirect(url_for("data.map", id=new.id))


# -- the spreadsheet view ----------------------------------------------------------------------------------------
@bp.get("/<int:id>/map")
def map(id):
    ds = _dataset(id)
    try:
        view = service.grid_view(ds)
    except ReadError:
        flash(t("data.errors.missing"), "error")
        return redirect(url_for("data.index"))
    report = service.quality_report(ds)
    cols = ds.columns or []
    return render_template("data/map.html", ds=ds, view=view, cards=service.column_cards(ds), n_questions=len(ds.questions or []),
                           counts={r: sum(1 for c in cols if c["role"] == r) for r in service.ROLES},
                           ready_error=service.check_ready(ds), report=report, open_findings=service.open_findings(report),
                           quality_chart=quality_chart, ai_state=_ai_state(), roles=service.ROLES, aggs=("sum", "avg", "last"), sheet_tabs=service.sheet_tabs(ds))


@bp.post("/<int:id>/analyze")
@require("data.edit")
def analyze(id):
    """Change which sheet / header row / year is used and let the AI read the table again."""
    ds = _dataset(id)
    sheet = F.integer("sheet")
    if sheet is not None and (ds.status == "ready" or (ds.meta or {}).get("group")):
        sheet = None                                      # each sheet has its own dataset now: switching here would overwrite this one
    if sheet is not None:
        ds.sheet_index, ds.header_row = max(0, sheet), None
    hr = F.integer("header_pick") or F.integer("header_row")
    if hr is not None:
        ds.header_row = max(0, hr - 1)                   # the user counts rows from 1, like the file does
    if "header_auto" in request.form:
        ds.header_row = None
    year = F.integer("year")
    if "year" in request.form:
        ds.year_hint = year if year and 1990 <= year <= 2100 else None
    try:
        service.analyze(ds)
    except ReadError:
        flash(t("data.errors.missing"), "error")
    db.session.commit()
    return redirect(url_for("data.map", id=ds.id))


@bp.post("/<int:id>/explain")
@require("data.edit")
def explain(id):
    """The user explains the file / its columns to the model. Autosaved while typing (`save_only`); with `reread` the model reads the file again."""
    ds = _dataset(id)
    notes = {int(k[5:]): v for k, v in request.form.items() if k.startswith("note_") and k[5:].isdigit()}
    service.save_notes(ds, file_note=request.form.get("file_note") if "file_note" in request.form else None, col_notes=notes)
    if request.form.get("save_only"):
        db.session.commit()
        return jsonify(ok=True)
    try:
        service.analyze(ds, keep_user=True)
    except ReadError:
        flash(t("data.errors.missing"), "error")
        return redirect(url_for("data.map", id=ds.id))
    db.session.commit()
    if (ds.meta or {}).get("provider") in (None, "offline"):
        flash(t("data.explain.no_model"), "info")
    else:
        flash(t("data.explain.reread_done"), "success")
    return redirect(url_for("data.map", id=ds.id))


@bp.post("/<int:id>/column/<int:idx>")
@require("data.edit")
def column(id, idx):
    """Answer a question about a column, or change what it is. JSON for the page script, a redirect without it."""
    ds = _dataset(id)
    opt = F.integer("option")
    if opt is not None:
        col = service.answer_question(ds, idx, opt)
    else:
        col = service.edit_column(ds, idx, role=F.s("role"), label=F.s("label"), unit=F.s("unit") if "unit" in request.form else None,
                                  aggregation=F.s("aggregation"), direction=F.s("direction"))
    if col is None:
        abort(404)
    db.session.commit()
    if request.accept_mimetypes.best == "application/json" or request.headers.get("X-Requested-With") == "fetch":
        left = len(ds.questions or [])
        return jsonify(ok=True, column=col, remaining=left, remaining_label=tn("data.questions_open", left) if left else t("data.questions_none"),
                       ready=service.check_ready(ds) is None,
                       roles={r: t(f"data.role.{r}") for r in service.ROLES},
                       aggregation_label=t(f"data.agg_short.{col.get('aggregation') or 'none'}"))
    return redirect(url_for("data.map", id=ds.id) + f"#col-{idx}")


@bp.post("/<int:id>/fix")
@require("data.edit")
def fix(id):
    """The user's decision about something odd in a column (fill a gap, keep a jump, convert a running total…)."""
    ds = _dataset(id)
    col = F.integer("column")
    if col is None or not service.set_fix(ds, col, F.s("code"), F.s("option"), F.s("period") or None):
        abort(400)
    db.session.commit()
    return redirect(url_for("data.map", id=ds.id) + "#quality")


@bp.post("/<int:id>/update")
@require("data.edit")
def update(id):
    """Upload a newer version of the same file: the earlier decisions carry over and only what is new is asked."""
    ds = _dataset(id)
    f = request.files.get("file")
    if not f or not f.filename:
        flash(t("data.errors.no_file"), "error")
        return redirect(url_for("data.detail", id=ds.id))
    try:
        mode = service.update_dataset(ds, f.read(MAX_BYTES + 1), f.filename, current_user.id if current_user.is_authenticated else None)
    except ReadError as e:
        db.session.rollback()
        flash(t(f"data.errors.{e}"), "error")
        return redirect(url_for("data.detail", id=ds.id))
    log_activity("updated", "dataset", ds.id, ds.name)
    db.session.commit()
    if mode == "auto":
        flash(t("data.update.flash_auto"), "success")
        return redirect(url_for("data.detail", id=ds.id) + "#changes")
    flash(t("data.update.flash_review"), "info")
    return redirect(url_for("data.map", id=ds.id))


@bp.post("/<int:id>/confirm")
@require("data.edit")
def confirm(id):
    ds = _dataset(id)
    try:
        added, updated, removed = service.confirm(ds, user_id=current_user.id if current_user.is_authenticated else None)
    except ValueError as e:
        flash(t(f"data.errors.{e}"), "error")
        return redirect(url_for("data.map", id=ds.id))
    except ReadError:
        flash(t("data.errors.missing"), "error")
        return redirect(url_for("data.map", id=ds.id))
    log_activity("confirmed", "dataset", ds.id, ds.name)
    db.session.commit()
    flash(t("data.flash.confirmed", n=added + updated), "success")
    nxt = next((d for d in service.siblings(ds) if d.id != ds.id and d.status == "draft"), None)
    if nxt:
        flash(t("data.flash.next_sheet", name=(nxt.meta or {}).get("sheet_name", nxt.name)), "info")
        return redirect(url_for("data.map", id=nxt.id))
    return redirect(url_for("data.detail", id=ds.id))


# -- dataset / series --------------------------------------------------------------------------------------------
@bp.get("/<int:id>")
def detail(id):
    ds = _dataset(id)
    if ds.status != "ready":
        return redirect(url_for("data.map", id=ds.id))
    versions = sorted(ds.versions, key=lambda v: -v.number)
    last = next((v for v in versions if v.confirmed and v.diff), None)
    affected = []
    if last and not last.diff.get("first"):
        for sr in service.affected_series(last.diff, ds):
            for l in Link.query.filter_by(org_id=g.org.id, target_type="series", target_id=sr.id, kind="measured_by", source_type="key_result").all():
                url = entity_url("key_result", l.source_id)
                if url:
                    affected.append({"title": entity_title("key_result", l.source_id), "url": url, "series": sr.name})
    return render_template("data/detail.html", ds=ds, series=ds.series, versions=versions, last=last, affected=affected)


@bp.post("/<int:id>/delete")
@require("data.delete")
def delete(id):
    ds = _dataset(id)
    name = ds.name
    service.delete_dataset(ds)
    log_activity("deleted", "dataset", id, name)
    db.session.commit()
    flash(t("data.flash.deleted"), "success")
    return redirect(url_for("data.index"))


@bp.post("/series/<int:id>/rename")
@require("data.edit")
def rename_series(id):
    """Give an indicator the name people use. Its branches follow ("<name> — <branch>") and the column keeps the name for the next upload."""
    s = _series(id)
    new = F.s("name", maxlen=120)
    if not new or s.dimension is not None:
        flash(t("data.rename.invalid"), "error")
        return redirect(url_for("data.series", id=s.id))
    old = s.name
    for other in Series.query.filter_by(dataset_id=s.dataset_id).all():
        if other.id == s.id:
            other.name = new
        elif other.dimension is not None and other.name.startswith(old + " — "):
            other.name = new + " — " + other.name[len(old) + 3:]
    ds = s.dataset
    cols = [dict(c) for c in ds.columns or []]
    for c in cols:
        if c.get("label") == old:
            c["label"] = new
    ds.columns = cols
    db.session.commit()
    flash(t("data.rename.done"), "success")
    return redirect(url_for("data.series", id=s.id))


@bp.get("/series/<int:id>")
def series(id):
    s = _series(id)
    pts = s.pairs()
    chart = line_chart(pts) if len(pts) > 1 else None
    vals = [v for _, v in pts]
    stats = {"n": len(vals), "first": pts[0][0] if pts else None, "last": pts[-1][0] if pts else None, "latest": vals[-1] if vals else None,
             "min": min(vals) if vals else None, "max": max(vals) if vals else None, "mean": sum(vals) / len(vals) if vals else None}
    linked = _linked_krs(s)
    return render_template("data/series.html", s=s, chart=chart, stats=stats, rows=list(reversed(pts)), linked=linked)


def _linked_krs(s: Series) -> list:
    from app.core.models import Link

    out = []
    if not current_app.extensions["modules"].is_enabled("goals"):
        return out
    from app.modules.goals.models import KeyResult

    for l in Link.query.filter_by(org_id=g.org.id, target_type="series", target_id=s.id, kind="measured_by", source_type="key_result").all():
        kr = db.session.get(KeyResult, l.source_id)
        if kr:
            out.append(kr)
    return out


# -- reality check --------------------------------------------------------------------------------------------------
def _num_arg(name):
    v = F.norm(request.args.get(name) or "").replace(" ", "")
    if "," in v and "." not in v:
        v = v.replace(",", ".")
    try:
        return float(v) if v else None
    except ValueError:
        return None


def _date_arg(name):
    v = F.norm(request.args.get(name) or "")
    try:
        return date.fromisoformat(v) if v else None
    except ValueError:
        return None


def _check_from_args():
    """-> (result | None, error code | None). Shared by the page and the live fragment."""
    sid = request.args.get("series", type=int)
    if not sid:
        return None, None
    s = db.session.get(Series, sid)
    if not s or s.org_id != g.org.id:
        return None, "series"
    target, end = _num_arg("target"), _date_arg("end")
    if target is None or end is None:
        return None, "incomplete"
    start = _num_arg("start")
    pts = s.pairs()
    if start is None:
        start = pts[-1][1] if pts else None
    if start is None:
        return None, "series"
    res = reality.check(s, start=start, target=target, end_date=end, direction=request.args.get("direction") or None, goal=(request.args.get("goal") or "")[:160])
    if res.get("error"):
        return None, res["error"]
    if request.args.get("ai") == "1":
        res = reality.explain(res)
    return res, None


@bp.get("/reality")
def reality_page():
    """Moved: the reality check is part of goals. Old links keep working."""
    return redirect(url_for("goals.reality_page", **request.args.to_dict()))


@bp.get("/reality/check")
def reality_check():
    """HTML fragment for the live panel (goal forms and the reality page)."""
    result, err = _check_from_args()
    return render_template("data/_panel.html", result=result, err=err, args=request.args, ai_state=_ai_state())


@bp.get("/reality/options")
def reality_options():
    """Series the current organization can attach to a goal (JSON for forms that want to build their own select)."""
    return jsonify([{"id": s.id, "name": s.name, "unit": s.unit, "direction": s.direction, "latest": (s.latest[1] if s.latest else None)}
                    for s in service.org_series(g.org.id)])


@bp.get("/levels")
def levels():
    """Three defensible targets (conservative / ambitious / stretch) for a series and a date, from the organization's own history. JSON."""
    from app.modules.data import realism

    sid, end = request.args.get("series", type=int), _date_arg("end")
    s = db.session.get(Series, sid or 0)
    if not s or s.org_id != g.org.id or end is None:
        return jsonify(ok=False, error="series"), 400
    pts = s.pairs()
    start = _num_arg("start")
    start = start if start is not None else (pts[-1][1] if pts else None)
    if start is None or end <= date.today():
        return jsonify(ok=False, error="dates"), 400
    lv = realism.levels(pts, start=start, as_of=date.today(), end_date=end, direction=request.args.get("direction") or s.direction, period_months=s.period_months,
                        relative=False if (s.unit or "").strip() == "%" else None)
    if lv is None:
        return jsonify(ok=True, levels=None, series=s.name)
    return jsonify(ok=True, levels=lv, series=s.name, unit=s.unit, start=start, direction=request.args.get("direction") or s.direction)
