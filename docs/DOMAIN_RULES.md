# Domain rules (implemented in `app/core/progress.py`, tested in `tests/test_progress.py`)

These are modelled on how Perdoo, Cascade and Profit.co compute progress and status, simplified to rules a manager can explain in one sentence.

- **Key result progress** = clamp((current − start) / (target − start)). Works for decreasing targets (start 100 → target 0). No span → 1 if at target, else 0.
- **Objective progress** = weighted mean of its drivers. `progress_driver` ∈ `key_results` | `children` | `both` (average of the two). Weights default to 1.
- **Expected progress** is linear over the start→end dates of the objective (or its cycle).
- **Status** (derived) from `gap = (expected − actual) × 100` points: `on_track` if gap ≤ 10, `at_risk` if ≤ 25, otherwise `off_track`.
  Thresholds are configurable per organization (Settings → General) and in `config/modules.yaml`.
- Overrides, in order: lifecycle state `on_hold`/`cancelled` wins; progress ≥ 99.9 % → `completed`; a **manual status** in the latest update overrides the derived live
  status until a key result is updated after it; not yet started (or 0 % with 0 expected) → `not_started`.
- **Stale**: no update for more than `checkin_cadence_days` (default 14). A never-updated item is shown separately, not as stale.
- **Indicators (KPIs)**: attainment = latest / target (for *lower is better*: target / latest). Status: ≥ 95 % on track, ≥ 80 % at risk, else off track.
- **Cycles**: year → quarters (parent/child). "Current cycle" = the active cycle containing today (the narrowest). Overview counts include the current cycle and its parent.
- **Strategy map**: top-level objectives placed on the four Balanced Scorecard perspectives; cause→effect arrows are `Link(kind=supports)` rows.
- Demo data: seeds use *deltas against expected progress* so every demo always shows a healthy mix of statuses whatever the date.

## Reality check (implemented in `app/modules/data/realism.py`, tested in `tests/test_realism.py`)

Question: *given what this organization has actually done before, is this target realistic?* No external benchmark is used.

- **Required change** = the improvement from the starting value to the target, signed toward the goal's direction (*higher is better* / *lower is better*), over the months available.
  It is **relative** (%), or **absolute** when the series contains values ≤ 0, when forced, or when the unit is `%` (rates are judged in percentage points).
- **History** = every comparable window of the same length in the series (e.g. all 6-month spans). Their distribution gives *typical* (median), *p75*, *p90* and *best*.
- **Level** (from the required change): `realistic` ≤ p75 · `ambitious` ≤ p90 · `stretch` ≤ best × 1.15 · otherwise `unrealistic`.
  `insufficient` when there are fewer than 6 points or fewer than 3 windows — the engine says so instead of guessing.
- **Tolerance floor**: a flat history must not make 0.5 % look "unrealistic" — thresholds never go below 4 points (relative) or 5 % of the typical level (absolute).
- **Seasonality**: with ≥ 24 monthly points and a seasonal spread above 0.12, windows are compared de-seasonalized, and a `seasonal_end` note appears if the target month is seasonally high/low.
- **Notes** (shown as reasons): `already_met`, `scale_mismatch` (target / latest > 8 or < 0.125 — probably a unit mistake), `flat_history`, `declining_trend`, `volatile`, `few_windows`, `short_history`, `negative_values`, `start_differs`, `seasonal_end`.
- **Output**: level, required, `range` {low, typical, high, max} (the band history says is reachable), percentile of the target among windows, `facts` (every figure that may be quoted).
- The AI never changes these results; it explains them (`explain_reality`, with a number guard). Suggested targets are rounded to 3 significant digits.
- **Linking**: a key result is linked to a series with `Link(kind=measured_by)`; the goals page then shows the verdict chip, and the goal form shows it live.
