# Pilar — strategy execution platform (working name)

> **"Pilar" / «بيلار» is a placeholder.** The name and the logos are fully swappable from one file
> (`config/brand.yaml`). See [Rebranding](#rebranding-in-five-minutes).

Enterprise planning (التخطيط كوظيفة إدارية) as a web product: **strategy → goals (OKR) → indicators (KPI) → initiatives → follow-up → reports**,
for mid-size and growing companies. Arabic (default, RTL), English and French are first-class.

Stack: Flask 3 app factory · SQLAlchemy 2 · Flask-Migrate · Flask-Login · server-rendered Jinja · vanilla JS · own CSS (logical properties, no framework).

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env     # optional: AI keys go here (flask run loads it)
export FLASK_APP=wsgi.py
flask db upgrade            # create the database (SQLite by default; set DATABASE_URL for Postgres)
flask seed-demo             # builds the 3 read-only demo workspaces (ar / en / fr)
flask run                   # http://localhost:5000  — /demo opens the sample workspace (Data tab: try the sample Excel files)
pytest                      # rules, i18n parity, glossary, isolation, module on/off, upload→AI→reality check
```

---

# DIRECTIVES — read this before changing anything

This section is the owner's brief, written so that **any person or AI** can continue the work without asking him again.
The owner is Youcef: an Arabic-speaking Financial Management student (Algeria) building this alone. If you are an AI assistant, these are standing instructions.

## 1. What the product is — and is not

- A **strategy-execution platform** in the family of Perdoo, Cascade and Profit.co: strategy, goals/OKR/KPI, initiatives, follow-up, reports.
- Target: **mid-size and growing companies**. Modular. Global (not Algeria-only), but Arabic must be excellent.
- **Rejected ideas — do not build them:** a financial-plan generator, a Pigment-style finance-centric product, a plan *simulator*.
- **Functionality is borrowed first, innovated second.** Do not design features out of your own head. Before adding a feature, look at how
  Perdoo, Cascade, Profit.co, Asana Goals, Lattice, Weekdone, Quantive do it, take what works, then improve. Cite what you studied in the PR/commit.
  Domain rules already decided are in [docs/DOMAIN_RULES.md](docs/DOMAIN_RULES.md).
- Research is a core strength of this project. When unsure, research, then decide, then write the decision down in `docs/`.

## 2. Identity — follow the SaaSpal template strongly

- The visual identity comes from the **SaaSpal** HTML template (the owner chose it). **Follow it closely and distinctively. Do NOT invent a new identity.**
  Tokens: primary `#5864FF`, link/text-primary `#4652EA`, navy `#162447`, body `#5B657E`, accent yellow `#FDD446`, lavender tint `#F3F5FF`.
  Signature moves (landing): saturated-blue hero cut by a white wave, pill buttons, lavender circular icon wells, organic blobs with dot grids,
  a blue subscribe band with a wave, a blue footer with a blob wave, yellow underline on nav hover/active.
- **Avoid AI-design patterns:** no gradient washes as decoration, no identical rounded-card grids with the same soft shadow, no tracked ALL-CAPS eyebrow
  above every heading, no fade-and-slide entrances, no `A · B · C` meta strings as decoration, no invented testimonials, logos, prices or statistics.
- The **app** (after the landing page) is a modern **GitHub-like** interface in the *same* identity: navy header, `/` search, underline tabs, boxes with rows.
  Better than GitHub, but **not complex**. **No heavy animation** — motion only answers a user action.
- **In-app identity (the landing page's own pieces, no invented motifs):** every page opens with a blue hero card (wave + organic blob + dot grid, white pill actions, short yellow rule under the title); content sits on the lavender canvas in white cards (24px) with circular lavender icon wells; figures are circular wells like the landing promises; gauge panel is the hero blue; bullets are blue discs with a soft glow; the band above stays flat (no wave) with the floating white pill tab-track; the "thinking" card (`.think`, template `#think-tpl`) shows every wait on the AI.
- Status colors (on track / at risk / off track / …) are **reserved**: never reuse them for decoration, always show them with **icon + label**.
- Fonts: headings `Arimo`, body `Open Sans`, Arabic `IBM Plex Sans Arabic` (all self-hosted, OFL/Apache). Simple, professional, modern.
- Details and tokens: [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md).
- Note: the *navy-only* palette in the owner's other project (MarketLab) does **not** apply here.

## 3. Architecture — extremely flexible, professional, never primitive

The owner must be able to **add, change and delete freely**:

| To change… | Do this | Touch code? |
|---|---|---|
| Product name, logos, colors, fonts | edit `config/brand.yaml`, drop SVGs in `app/static/brand/` | no |
| Switch a feature on/off or reorder the nav | edit `config/modules.yaml` | no |
| Add a feature | new package `app/modules/<id>/` with a `manifest` ([docs/ADDING_A_MODULE.md](docs/ADDING_A_MODULE.md)) | only that package |
| Switch AI provider/model, point to a local model | `config/ai.yaml` + env vars; add a provider/task by dropping a file in `app/ai/providers|tasks/` ([docs/AI.md](docs/AI.md)) | no / one file |
| Add/rename a word, add a language | edit YAML catalogs in `i18n/` folders | no |
| Change status thresholds / check-in cadence | `config/modules.yaml → defaults` (per-organization override in Settings) | no |

Rules that keep this true:

1. **Modules never import each other's internals.** Cross-module relations go through the core `Link` table; check-ins and the activity feed are generic
   `(entity_type, entity_id)`; entity types are registered by each manifest (`EntityType`). Optional links to another module must be guarded with
   `modules.is_enabled(...)` or `can(...)`. `tests/test_brand_modules.py` switches every module off in turn and crawls the app — keep it green.
2. **The database schema is global:** every module's models are always imported, so toggling a module never hides or drops tables. Use Alembic (`flask db migrate`).
3. **Everything is under `/app/<org_slug>/…`** and every query is organization-scoped (`get_scoped(Model, id)`). Never fetch by bare id. Demo workspaces are read-only for anonymous users.
4. **Pure rules live in `app/core/progress.py`** (no Flask, no DB) and are unit-tested. Views stay thin.
5. **No hard-coded product name, logo path, color or label** in templates or Python. Use `brand.*`, `logo()`, `t('key')`, CSS variables.
6. Server-rendered Jinja + vanilla JS. No front-end framework, no build step. CSS uses **logical properties** (`margin-inline-start`, `inset-inline-end`…) so RTL is free.
7. **AI: code decides, the model explains.** Verdicts and numbers come from tested code (`app/modules/data/realism.py`); models only read headers and put verdicts into words, and their answers are validated against measured facts. Every AI feature has an offline fallback. Cloud calls need the organization's consent and are audited. Call it only through `ai.run(...)` / `ai.get_hub()` — see [docs/AI.md](docs/AI.md).
8. **Modules talk through hooks, not imports.** A module may publish a hook (`Manifest.hooks`, `modules.hook(name, ...)`; errors are swallowed) and expose template helpers that other templates test with `x is defined`. A module's templates and i18n keys are used only by that module (shared partials live in core). Example: goals fires `key_result.saved`; the data module listens and links the key result to a series.
9. Template helpers and their rules: [docs/TEMPLATE_API.md](docs/TEMPLATE_API.md). Jinja has **no list comprehensions** — use `opts()` / `topts()`.

## 4. Language rules — Arabic terminology must be correct

- The default language is **Arabic (RTL)**. English and French must always have the same keys (`flask i18n-check`, `tests/test_i18n.py`).
- **Never improvise Arabic terms.** Research, then record the decision in [`app/i18n/glossary.yaml`](app/i18n/glossary.yaml) (term, ar/en/fr, `avoid_ar`, `confidence`).
  `avoid_ar` is enforced by a test: transliterations like *أوكيار، داشبورد، تشيك إن، ميلستون، ستيك هولدر، ورك سبيس، سكور كارد* must never appear in the Arabic UI.
- Core vocabulary: الهدف · النتيجة الرئيسية · المبادرة · المؤشر / مؤشر الأداء الرئيسي · المَعلَم · المواءمة · خط الأساس · المستهدف · المسؤول · الدورة ·
  الوحدة التنظيمية · المؤسسة · مساحة العمل · لوحة المؤشرات. Statuses: على المسار / معرَّض للخطر / خارج المسار / لم يبدأ / معلَّق / مكتمل / ملغى.
  Balanced Scorecard: المنظور المالي · منظور العملاء · منظور العمليات الداخلية · منظور التعلّم والنمو.
- "Unit of measure" is **وحدة القياس**, to avoid clashing with **الوحدة التنظيمية** (organizational unit).
- Terms marked `confidence: review` in the glossary still need a native management-control reader (المسؤول vs المالك, لوحة المؤشرات vs لوحة القيادة, مطَّلع).
- Digits are **Latin by default** (`defaults.digits`); dates are composed from Babel month names; use `n() pct() d() val()` — never format numbers by hand.
- Wrap mixed-direction fragments (names, cycle labels, date ranges) in `<bdi>` — the `bdi()` helper and templates already do this; keep doing it.
- Plural tables use CLDR keys (`zero/one/two/few/many/other`); Arabic needs all six. A dict whose keys are all CLDR names is a plural leaf, so never name a namespace `one` or `two`.
- Copy style: plain verbs, sentence case, no promotional filler; errors say what to do; empty states invite an action.

## 5. Process — how to work on this project

1. **Research first, then build** (see §1). Surprise the owner with what you learned from real products ("ابهرني").
2. **Boot and look.** Run the app, crawl it (`PYTHONPATH=. python scripts/crawl.py`), and screenshot RTL **and** LTR **and** mobile (`scripts/make_screenshots.py`) before calling anything done.
3. **Critique your own work candidly** and fix at once; the owner gives blunt design feedback and expects corrections applied without defending the earlier choice.
4. **Keep the tests green** (`pytest`) and the catalogs in parity. Add a test with every rule you add.
5. Never fabricate content on the public site: no fake clients, reviews, pricing or numbers. The call to action is the demo or the waitlist.
6. Record durable decisions in `docs/` (and, for AI assistants, in memory). Keep this README current — it is the contract.

## 6. Rebranding in five minutes

1. Edit `config/brand.yaml`: `name` (per language), `name_short`, `domain`, `colors`, `fonts`, set `placeholder: false` (this removes the dev footer notice).
2. Put your logos in `app/static/brand/` and point to them in `logos:` — **two families**, each with `on_light` and `on_dark`:
   `full` (symbol + name; landing, auth pages, reports) and `mark` (symbol only; app header on mobile, avatars), plus `favicon`.
   A per-language override is supported (see the `ar:` entry under `full`). Missing files fall back to the text name — nothing breaks.
3. Regenerate the landing screenshots: `flask run &` then `python scripts/make_screenshots.py`.
4. (Optional) `python scripts/make_logos.py` regenerates the *placeholder* logos from the current name/colors.

## Repository map

```
config/brand.yaml        identity (single source)        config/modules.yaml   features on/off + defaults
app/__init__.py          app factory + template API       app/core/             rules, i18n, brand, icons, models, permissions
app/modules/<id>/        goals · data · initiatives · strategy · reports   (manifest, models, views, templates, i18n, seed)
app/ai/                  pluggable AI layer (providers/, tasks/)         app/site/             landing + waitlist     app/auth/  sign-in/up
app/templates/           layouts + components (ui.html, shapes.html)
app/static/              css (tokens/base/app/marketing), js, fonts, icons (Tabler), brand logos, img/shots
scripts/                 make_logos · make_screenshots · crawl · audit_keys        tests/   pytest        docs/   decisions
```

## Status and open items

- Working: **data module** (upload an Excel/CSV → grid view with an AI note above every column, questions when it is unsure → confirmed time series → reality check of targets, also live inside the goal form), pluggable AI layer with consent, quota and audit, landing, auth, demo workspaces (ar/en/fr), goals (objectives, key results, indicators, alignment tree), initiatives (list, board, roadmap, milestones),
  strategy (foundation, SWOT, strategy map), reports (progress, indicators, initiatives; print + CSV), settings (general, members, units, cycles).
- **Verify the SaaSpal license** before any public launch — the supplied "free-lite" zip carries no license file. See [THIRD_PARTY.md](THIRD_PARTY.md).
- **Native review** of the glossary terms marked `review`.
- **Needs a real-world test:** live AI calls (`ANTHROPIC_API_KEY`, or `AI_LOCAL_BASE_URL` + `AI_LOCAL_MODEL`) were only tested against local fake servers.
- Next, in this order: editable cells in the grid; AI-drawn charts from goals (chart-spec design in docs/AI.md); a local-model recommendation flow for companies.
- Not built yet (ideas to research before building): notifications/reminders for stale updates, comments/mentions, integrations, per-organization language/digit settings UI, exports to PowerPoint/PDF, SSO.

## الإصدار 2 (V2) — ما تغيّر
- واجهة عربية فقط، بهوية PlanWise ونفس لغة الصفحة التعريفية.
- ملف المؤسسة (الشعار، القطاع، العملة، الرؤية والرسالة والقيم) في الإعدادات.
- صفحة البيانات: فهم الأعمدة، لوحة مرئية يحسب الكودُ أرقامها، وصندوق طلبات بالعربية.
- صياغة الهدف: من بياناتك أو من خارجها ← حكم الواقعية من تاريخك ← الرافعات ← حفظ بعنوان قابل للقياس.
- صفحة الهدف: مسار الفعلي/المطلوب/المتوقع، تفكيك الفروع، متابعة الرافعات، سجل القرارات وتغييرات المستهدف.
- الفريق وروابط الدعوة (7 أيام، لمرة واحدة).
- «المخطط» (`app/modules/orgmap`) وتقرير «ملف المؤسسة» (يبدأ بالمخطط) مع تصدير SVG.
- ترحيلات قاعدة البيانات الجديدة: `flask db upgrade`.


## Deploying on Render
1. Push the folder to GitHub (the `.env` and `instance/` are ignored on purpose).
2. Render → New → Blueprint → pick the repo. `render.yaml` creates the web service and a PostgreSQL database and sets `DATABASE_URL` for you.
   Without the Blueprint: Build `pip install -r requirements.txt`, Start `bash scripts/start.sh`, and set `SECRET_KEY` and `DATABASE_URL`.
3. Add the AI keys (`GROQ_API_KEY`, …) under Environment — never in the repo.
SQLite works on Render only with a paid persistent disk (mount it at `instance/`); otherwise every deploy starts with an empty database.
Files people upload (data files, logos) live in `instance/` too, so they need that disk as well.
