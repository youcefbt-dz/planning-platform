# The AI layer (`app/ai/`)

One small package, built to be **swapped, extended and switched off** without touching the rest of the product.
It answers two questions today: *what does each column of this spreadsheet mean?* (`map_columns`) and *why is this target realistic or not?* (`explain_reality`).

## The rule that matters most

**Code decides, the model explains.** Numbers and verdicts (realistic / ambitious / stretch / unrealistic) are computed by `app/modules/data/realism.py`,
a deterministic, unit-tested engine. A model only (a) reads headers and (b) puts the verdict into words. Both tasks check the model's answer against
the measured facts and **reject it** if it invents a number or claims something the data does not support. With no model at all, every feature still works
through a rule-based fallback (`offline`).

## Layout

```
config/ai.yaml                 which providers, in which order, which model per task, privacy limits
app/ai/__init__.py             public API:  ai.run(task, inputs, ...)   ai.get_hub()
app/ai/base.py                 contracts: Provider, Task, AIRequest, AIResult
app/ai/hub.py                  discovery, the chain, the privacy gate, quota, audit
app/ai/privacy.py              sampling and clipping of what may be sent
app/ai/models.py               AICall (audit table)
app/ai/providers/*.py          one file per provider        (auto-discovered)
app/ai/tasks/*.py              one file per task            (auto-discovered)
app/ai/i18n/{ar,en,fr}.yaml    texts of the fallbacks (prefix `ai.`)
```

## Providers

| name | what | data leaves the machine? |
|---|---|---|
| `openai_compat` | any OpenAI-compatible endpoint: Ollama, LM Studio, vLLM, llama.cpp. **The recommended option for companies.** | no (`local: true`) |
| `gemini` | Google Gemini through the REST API: structured JSON, function calling for the agent, several models in `GEMINI_MODEL` (own quota each). **First cloud choice.** | yes (`local: false`) |
| `groq` | Groq cloud, fast inference with a free tier (OpenAI wire format; own key and model) | yes (`local: false`) |
| `xai` | Grok through the xAI API (OpenAI wire format; same code as `openai_compat`, own key and model) | yes (`local: false`) |
| `anthropic` | Claude through the Messages API with a forced tool call, so the reply is always structured | yes (`local: false`) |
| `offline` | rules only; always last | no |

### Configure (no code)

```
GEMINI_API_KEY=...  GEMINI_MODEL=model-a,model-b           # Gemini (cloud): best first; a limited model is skipped at once
GROQ_API_KEY=...  GROQ_MODEL=<model id from console.groq.com/docs/models>   # Groq (cloud)
XAI_API_KEY=...  XAI_MODEL=<name from your xAI console>   # Grok (cloud)
ANTHROPIC_API_KEY=...                      # Claude (cloud). Keys live in the environment, never in files or code
AI_LOCAL_BASE_URL=http://localhost:11434/v1
AI_LOCAL_MODEL=qwen2.5:14b-instruct
AI_LOCAL_API_KEY=                          # optional
```

`config/ai.yaml → chain` is tried in order; the first provider that is **available** (key/URL present) and **allowed** (privacy gate) answers.
If it fails, the next one is tried and the result is flagged `fell_back=True` so the interface can say so honestly.
Models can differ per task (`models: {default: ..., explain_reality: ...}`).

**Limits never reach the person.** A provider that answers 429/503 raises `RateLimited`; the hub parks it for the time the server asked (5 s to 15 min)
and the same request, and the next ones, go straight to the next provider in the chain (Gemini → Grok → …). Inside Gemini the same happens per model.

### Add a provider (5 minutes)

Create `app/ai/providers/<name>.py`:

```python
from app.ai.base import Provider, ProviderError

class MyProvider(Provider):
    name = "mine"
    def available(self, cfg): return bool(cfg.get("base_url"))
    def complete(self, req, cfg):
        # req.system, req.user, req.schema (JSON schema), req.max_tokens, req.temperature, req.timeout
        # return (parsed_json_dict, model_name) or raise ProviderError
        ...
provider = MyProvider()
```

Then add a `providers.mine` block (with `local: true|false`) and put `mine` in `chain`. Nothing else is registered anywhere.

## Tasks

A task knows **what to ask, how to check the answer and what to do without a model**.

```python
from app.ai.base import Task

class MyTask(Task):
    name = "my_task"
    schema = {...}                       # JSON schema of the answer
    def prompt(self, inputs, lang): return system, user
    def validate(self, data, inputs):    # repair or raise ValueError to reject
        return data
    def fallback(self, inputs, lang):    # deterministic answer, used when no model is allowed/available/valid
        return {...}
task = MyTask()
```

Add `tasks.my_task: {enabled: true, max_tokens: ..., temperature: ...}` to `config/ai.yaml` and call
`ai.run("my_task", inputs, lang=..., org=..., user=..., consent=..., read_only=...)`. The result is an `AIResult(data, provider, model, external, fell_back, errors, ms)`.

## Privacy gate (enforced in `hub.py`, tested in `tests/test_ai.py`)

- Demo and read-only workspaces **never** reach an external provider.
- A cloud provider needs the organization's consent (Settings → AI assistant; stored in `org.settings["ai_consent"]`).
- Only a **sample** is sent: headers plus a few rows (head, middle, tail), each cell clipped (`privacy.sample_rows`, `max_cell_chars`). Never the whole file.
- Per-organization daily quota of external calls (`external_calls_per_org_per_day`).
- Every call is audited in `AICall` (task, provider, model, duration, outcome and, for external calls, the exact preview of what was sent). Owners see the last calls in Settings → AI assistant.

## Where the AI is used today

| Task | Where | Guard |
|---|---|---|
| `map_columns` | Data → upload → map. Reads headers and a sample, proposes a role (date / number / category / ignore) and a confidence for each column, **asks the user** when confidence < 0.6 | each claim is validated against the measured profile of the column |
| `explain_reality` | Reality check panel ("Ask the AI to explain") | any number not in `facts` rejects the answer |

## Extending: AI-drawn charts (planned, not built)

Add a task `draw_chart` whose output is a **chart spec** (a small JSON: kind, series ids, period, annotations) and never code or SVG.
A renderer in core (next to `components/line_chart.html`) turns a validated spec into SVG, so a model can propose a distinctive visual
but can only use data the organization owns and shapes the product already knows how to draw. The same `validate` rule applies:
reject any series id or number not present in the supplied facts.

## Testing

`tests/test_ai.py` starts local fake HTTP servers for both wire formats, so providers, consent, quota, audit, sampling and fallback are covered
without network access. Live calls to a real API were not exercised in development (the sandbox blocked external hosts): do one real call after
setting a key and check the audit list.


## The voice of the AI (`app/ai/voice.py`)

A model told only "answer in Arabic" writes translated-sounding text. Every task therefore builds its system prompt with `voice.system(role, rules, lang, company=..., example=...)`:
one shared style guide (conclusion first, short sentences, name the exact thing with its unit, no filler, no markdown), the project glossary as a vocabulary
(and its `avoid_ar` list as a ban), the organization's sector and size (never its name), and one worked Arabic example.

Every string a model returns goes through `voice.clean()` (Latin digits, no markdown) and `voice.check_style()`, which rejects: filler openers («من الجدير بالذكر»…),
glossary-avoided terms (also with the Arabic prefixes: «الداشبورد»), Latin words the user never typed, characters of other scripts (Chinese/Cyrillic leaks) and emoji.
A bad item inside a list is dropped; a bad main sentence rejects the answer.

**One guided retry.** When our checks reject an answer, `hub.run` asks the same provider once more and tells it exactly why (invented figure, filler…), before falling back to rules.

## Offline wording is written by code, not poured into one template

`explain_reality`, `summarize_health`, `review_goal` and `draft_justification` build their offline text from the case: they name the thing measured, say from-what-to-what, never
repeat a figure between summary and reasons, agree in number (CLDR plurals), and end with a concrete next step. The pace comparison now comes from the same comparable windows as the verdict.

## "Click instead of type"

| Where | What | Task / source |
|---|---|---|
| Goal form | one typed line → up to 3 complete options (title, why, key results with type and unit; **never a figure**) | `draft_goal`, offline `app/ai/library.py` |
| Goal composer | typical outside factors as chips for the lever boxes | `library.levers` (no model call) |
| Settings → profile | vision / mission / values options for the sector; click to fill, nothing saved | `draft_direction`, offline `library.direction` |
| Update boxes (goals, initiatives) | five one-click replies (`quick_notes` macro) | none |
| Data → columns | the note box is folded; chips say the usual things (amount, thousands, count, percent) | none |

The front-end half is `static/js/assist.js` (`data-fill`, `data-assist`), loaded on every app page.


## draw_map (journey map)
Output is a **map spec** (family, ordered steps of fact ids, line colours, emphasis) — never SVG. `app/modules/orgmap/spec.py` validates every id against the facts; layout and drawing are code (`families/*.py`). Add a family by writing `families/<name>.py` with `layout(facts, spec, reveal) -> Canvas` and registering it in `spec.families()`.


## The assistant (`app/modules/agent`)

A conversation with a model that can call tools. The tools (`agent/tools.py`) read the organization as the current user may see it and return small JSON;
the model never computes a figure, it asks. `loop.py` runs the turns (max 8 steps) and enforces the rules in code:

* every figure of the final answer must trace to a tool result (or simple arithmetic on them); otherwise the model is told once to fix it, and what remains is shown to the person as "unverified";
* `propose_goal` only drafts: start and target come from the data (a level from the organization's own history), and a goal is created only when a person approves the card (`/assistant/apply`, which re-validates scope and figures);
* without an allowed model the person gets a briefing computed by code and the reason (consent, no key, daily limit, demo) — never a fake answer.

The assistant is presented as a small floating dock across workspace pages, rather than a top-level navigation section. The close (×) button only closes the chat panel; icon visibility is controlled separately from the member-accessible personal interface preferences page and stored in the current browser for each user/workspace. The former `/assistant/` page redirects to the workspace overview. Chat history is kept for the current browser session and shared by the dock across workspace pages.

Providers that can hold a tool conversation set `supports_chat = True` and implement `chat()` (openai_compat and anthropic do). Add a tool = one function and one entry in `TOOLS`.
Use a strong model: `models.agent` for Anthropic in `config/ai.yaml`; for Groq/Grok/local the model comes from the `*_MODEL` env var and must support tool calling (e.g. `openai/gpt-oss-120b`).
