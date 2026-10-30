# Design system

Source of truth for identity: **SaaSpal** (see README §2). Tokens live in `app/static/css/tokens.css`; brand colors/fonts come from `config/brand.yaml` as `--brand-*` variables
(tints are derived with `color-mix`, so changing three brand values re-themes everything).

**Marketing** (`marketing.css`, `layouts/site.html`): blue hero cut by a white wave; pill buttons; lavender circular icon wells; organic blobs + dot grids around product screenshots;
blue subscribe band; blue footer with blob wave; yellow underline on nav hover/active. Shapes are inline SVG macros (`components/shapes.html`).

**App** (`app.css`, `layouts/app.html`): navy header with organization switcher, `/` search, create menu, language and user menus; module tabs with yellow active underline; sub-tabs;
`box` + `box-row` lists; status badge (icon + label); `meter` (progress with expected marker); `stackbar` (2 px gaps); tiles; timeline; board; roadmap; SWOT; strategy map (SVG connectors
drawn by `strategy-map.js`, bowed around skipped perspectives); server-rendered SVG line chart with tooltip; print styles for reports.

**Rules**
- Status colors are reserved (on track green, at risk amber, off track red, plus neutral/violet/blue for the rest) and always paired with an icon and a label.
- One radius scale, one shadow scale (`--r-*`, `--shadow-*`); spacing from `--sp-*`. No gradients as decoration. No entrance animations.
- Logical CSS properties only. Test every screen in `ar` (RTL), `en`, `fr` and at 390 px width.
- Charts follow the dataviz rules: one axis, thin marks, recessive grid, legend for ≥ 2 series, a table behind every chart.
- Typography: Arimo (headings) / Open Sans (body) / IBM Plex Sans Arabic (fallback and Arabic). Change them only in `brand.yaml`.
