# Adding a module

A module is a package `app/modules/<id>/`. The registry discovers it automatically; `config/modules.yaml` decides whether it is enabled.
Nothing outside the package needs editing (except the toggle).

```
app/modules/risks/
  __init__.py      blueprint + manifest          models.py   SQLAlchemy models (org_id on every table)
  views.py         routes (thin)                 service.py  queries/rules (pure where possible)
  templates/risks/ page templates                i18n/{ar,en,fr}.yaml   keys auto-prefixed "risks."
  seed.py          optional demo data            widgets.py  optional overview cards
```

## 1. Blueprint + manifest (`__init__.py`)

```python
from flask import Blueprint
from app.core.modules import CreateAction, EntityType, Manifest, Tab, Widget

bp = Blueprint("risks", __name__, url_prefix="/app/<org_slug>/risks", template_folder="templates")
from app.modules.risks import models, views  # noqa  (models must be imported here)

manifest = Manifest(
    id="risks", label_key="risks.module", icon="alert-triangle",
    blueprint=bp, home_endpoint="risks.index",
    tabs=[Tab("risks.tabs.list", "risks.index", "list-details", match=("risks.detail",))],
    depends_on=[],                 # hard: refused at boot if disabled
    optional_depends=["goals"],    # soft: only switches UI affordances (check modules.is_enabled)
    permissions={"risks.edit": "member", "risks.delete": "admin"},
    create=[CreateAction("risks.create", "risks.new", "alert-triangle", "risks.edit")],
    entities=[EntityType("risk", "risks.entity", "alert-triangle", loader, title_fn, "risks.detail")],
    # widgets=[Widget("risks_top", "risks/widget_top.html", loader_fn, order=45, span=1)],
    # search=search_provider,  seed=seed_fn,
)
```

## 2. Rules every module follows

- Every table has `org_id`; every route is under `/app/<org_slug>/…`; load rows with `get_scoped(Model, id)`; guard writes with `@require("risks.edit")`.
- Use the generic infrastructure instead of new tables where possible: `Link` (relations to other modules), `CheckIn` (updates), `Activity` (feed) — keyed by `(entity_type, entity_id)`.
- Never import another module's models/views. To reference another module, go through the registry (`entity_title/entity_url` in `app/core/services.py`) and guard links with `modules.is_enabled("goals")`.
- All strings through `t()`; add keys to **all three** catalogs; if you use an Arabic term that is new, add it to `app/i18n/glossary.yaml` first.
- Use components from `components/ui.html` (badge, meter, box rows, empty states) and tokens from `tokens.css`. No new colors.
- **Hooks, not imports.** To react to another module, listen to a hook declared in your manifest (`hooks={"key_result.saved": fn}`); to offer something, fire `modules.hook("<entity>.<event>", obj, **ctx)` (errors in listeners are swallowed). To show another module's data in a template, test a context helper with `x is defined` (see `data_series_options` in goals templates) so the page still renders when that module is off.
- **Templates and i18n keys belong to one module.** Never include another module's template or use its keys; put shared partials in `app/templates/components/` (e.g. `line_chart.html`).
- AI features go through `ai.run(...)` ([AI.md](AI.md)); give every task an offline fallback.
- New tables → `flask db migrate -m "risks"` then `flask db upgrade`.

## 3. Enable and verify

```yaml
# config/modules.yaml
modules:
  risks: { enabled: true, order: 35 }
```

`pytest` (the module on/off test crawls the app with each module disabled), `flask i18n-check`, `python scripts/audit_keys.py`, `PYTHONPATH=. python scripts/crawl.py`.

## Deleting a module

Set `enabled: false`, or remove the package. Tables stay until you write a migration to drop them — a toggle never destroys data.
