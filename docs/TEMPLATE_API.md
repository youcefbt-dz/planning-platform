# Template API

Everything a template may call. Helpers marked **(global)** also work inside imported macros (`{% from "components/ui.html" import … %}`),
because Jinja macros do not see context-processor values.

| Name | What it does |
|---|---|
| `t(key, **params)` **(global)** | translate; fallback chain lang → en → key (a miss is logged as `i18n miss`) |
| `tn(key, n, **params)` **(global)** | plural-aware (CLDR; Arabic has 6 forms); `{n}` is always available |
| `th(key, **params)` | like `t` but the catalog string may hold trusted markup; params are escaped |
| `n(x)` `pct(x)` `d(date, 'day'/'medium'/'long')` `val(x, unit)` **(global)** | number / percent / date / value with unit, localized (Latin digits by default) |
| `bdi(text)` **(global)** | wraps text in `<bdi>` for mixed-direction safety |
| `icon(name, size, cls, flip, title)` **(global)** | inline Tabler SVG; `flip=true` mirrors arrows in RTL |
| `logo(kind, tone, cls)` **(global)** | `kind` full/mark, `tone` on_light/on_dark; falls back to text |
| `opts(rows, 'id', 'name')` `topts(codes, 'prefix.')` **(global)** | `<select>` options from rows / from coded values with translated labels (Jinja has no list comprehensions) |
| `can(permission)` **(global)** | role check against module manifests; always false for write permissions in read-only demos |
| `STATUS_ICONS`, `lang_url(code)` **(global)** | status → icon name; same page in another language |
| `brand`, `brand_name`, `brand_short`, `brand_css` | identity from `config/brand.yaml` |
| `lang`, `dir`, `LANGS`, `LANG_NAMES` | current language and direction |
| `org`, `role`, `read_only`, `me`, `my_orgs()` | request context |
| `modules` | registry — use `modules.is_enabled('x')` to guard optional links |
| `nav`, `create_actions` | only inside an organization (built from module manifests) |

Components: `components/ui.html` (csrf, badge, dot, meter, avatar, stackbar, legend, empty, field, textarea, select, flashes, delete_button, status_select) and
`components/shapes.html` (hero_bg, blob, footer_bg, subscribe_wave, dots — recolorable via CSS variables).
