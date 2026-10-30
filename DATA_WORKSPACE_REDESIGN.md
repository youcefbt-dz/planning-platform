# Data workspace redesign

The data review page now opens as a four-part workspace:

1. **Data workspace** — bounded spreadsheet preview with Arabic-aware search, row filters, column sorting, cell selection, on-page column metrics, numeric/category mini charts, and local statistical signals.
2. **Understand columns** — clearly separates AI/rule-based column suggestions from user decisions and existing clarification questions.
3. **Data quality** — preserves the project's existing quality checks and review decisions.
4. **Reading settings** — keeps header-row/year interpretation controls available without crowding the table.

Cell edits are submitted in a batch of up to 300 cells and saved as a new source-file revision. The previous file remains intact. The user must still review the detected column roles and confirm before applying the refreshed series to planning measures. CSV export is explicitly the current visible preview, not a claim that the entire file has been exported.

The live mini-chart, completeness/uniqueness counts, numeric range, and heuristic observations are calculated in the browser from rows currently visible in the preview. These quick observations do not send cell values to an external model. AI is responsible for proposing column meaning and surfacing uncertainty; the user retains control over mapping and confirmation.

The existing preview size remains capped at 60 rows and 40 columns to stay aligned with the data reader's preview contract. The UI displays when additional rows or columns exist.
