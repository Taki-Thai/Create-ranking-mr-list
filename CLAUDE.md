# CLAUDE.md — CREATE S RANK LIST

Batch pipeline (医薬連携事業部 / Pharma-Medical Liaison). Builds the **S-Rank List**:
find MR (pharma reps) on the Lite Plan who just bought and look "stuck" (unread
chat / no meeting response), classify each into an opportunity **Pattern**, and
write the result to Google Sheets. Runs headless on GitHub Actions (`python -m
src.main`) and, as a mirror, from `Colab Task.ipynb`.

> **Layered docs:** this file is the map. Read the per-module doc under `docs/`
> **only for the module you are touching** — do not read all of `src/` up front.

## Repo map

| Module | Files | Doc | One-liner |
|---|---|---|---|
| gcp-and-config | `src/config.py`, `src/gcp_clients.py` | [docs/gcp-and-config.md](docs/gcp-and-config.md) | Secrets + static resource IDs, and the 3 shared GCP clients (Drive/Sheets/BigQuery) from one service account |
| drive-utils | `src/drive_utils.py` | [docs/drive-utils.md](docs/drive-utils.md) | Read CSVs out of Google **Shared** Drive folders via the Drive API |
| sheet-utils | `src/sheet_utils.py` | [docs/sheet-utils.md](docs/sheet-utils.md) | Google Sheets write patterns: full-table overwrite vs single-column write-back |
| masters | `src/pipeline/mr_master.py`, `hospital_master.py`, `lp_label.py` | [docs/masters.md](docs/masters.md) | Build the 3 BigQuery master tables (Steps 1–23) |
| s-rank | `src/pipeline/dr_active.py`, `s_rank.py`, `active_dr_user.py`, `case_analysis.py` | [docs/s-rank.md](docs/s-rank.md) | Core business logic: S-rank filter, 30-day already-sent filter, Pattern/Case, Sheets output (Steps 24–46) |
| orchestration-runtime | `src/main.py`, `.github/workflows/data_creation.yml` | [docs/orchestration-runtime.md](docs/orchestration-runtime.md) | Full run order + how it runs on GitHub Actions |

`Colab Task.ipynb` is a generated mirror of `src/` (same logic, interactive Colab
auth). It is **not** documented separately — treat `src/` as the source of truth
and regenerate the notebook from it.

## Data sources & sinks (quick reference)
- **Sources:** CSVs in Shared Drive folders (`config.FOLDER_ID_*`) + Google Sheets.
- **Sinks:** BigQuery `PROJECT_ID.DATASET_ID.{mr_master,hospital_master,lp_label_master}`
  and Sheets (`Sランクリスト`, `acvite dr user`, `List_dr_LP_hospital`, `List_dr_without_LP_hospital`, write-back to `5.Dr user active`).
- **Date-sensitive:** windows are relative to run time (Lite-plan 1 month / 15 days,
  chat & menkai 5 days, Dr active 7 days, already-sent 30 days).

## Conventions (my working rules)
- **Shared Drive API:** always pass `supportsAllDrives=True` (and
  `includeItemsFromAllDrives=True` on list). Source CSVs live in Shared Drives.
- **Google Sheets:** prefer **column-scoped** writes (`write_column`) to preserve
  cell formatting; do **not** clear a whole sheet you don't own the full layout of.
  Full-table *derived output* sheets are the exception (they are clear+overwrite).
- **IDs:** normalize to `str` (and `.str.strip()`) before any join/compare — Sheets
  and CSV reads coerce numeric IDs inconsistently (float `.0`, camelCase vs lower).
- **Logging:** short `✓`/`⚠` one-liners with row counts. Do **not** print DataFrames
  or preview tables.
- **Style:** vibe coding — keep it simple, no over-engineering, no OOP when a plain
  function does. Mirror the surrounding module's style.

## Pipeline order (see docs/orchestration-runtime.md)
masters (mr → hospital → lp) → dr_active → s_rank → active_dr_user → case_analysis.
Each step's output feeds the next; `s_rank_df` after the 30-day filter is the
single object that flows through Pattern/Case classification.

---

## ⚠️ MANDATORY RULE
**Before reading any file outside the current task's scope, list the files you
intend to read and why, then wait for my approval.** Use this map + the relevant
`docs/` file first; only open source when the doc is insufficient.
