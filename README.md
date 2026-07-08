# Create S Rank List (医薬連携事業部 / Pharma-Medical Liaison)

Batch pipeline that builds the **S-Rank List**: find MR (pharma reps) on the **Lite
Plan** who just purchased and look "stuck" (unread chat / no meeting response),
skip anyone already contacted in the last 30 days, classify each into an
opportunity **Pattern**, and write the result to Google Sheets. Runs headless on
GitHub Actions (`python -m src.main`) and, as a mirror, from `Colab Task.ipynb`.

> **This README is the overview.** The detailed, source-accurate documentation is
> layered:
> - [`CLAUDE.md`](CLAUDE.md) — repo map + working conventions + the "ask before
>   reading out of scope" rule (also the entry point for AI agents).
> - [`docs/`](docs/) — one file per module. Read only the one you're touching:
>   [gcp-and-config](docs/gcp-and-config.md), [drive-utils](docs/drive-utils.md),
>   [sheet-utils](docs/sheet-utils.md), [masters](docs/masters.md),
>   [s-rank](docs/s-rank.md), [orchestration-runtime](docs/orchestration-runtime.md).
>
> **Source of truth = `src/`.** `Colab Task.ipynb` is a generated mirror of `src/`
> (same logic, interactive Colab auth) — regenerate it from `src/`, don't hand-edit.

---

## 1. What it produces

| Deliverable | Goal | Output |
|---|---|---|
| **S-Rank List** (実行計画_フェーズ1) | Identify stuck new Lite-Plan MRs, tag each with a **Pattern**, and suggest hospitals where they can act | Sheet `Sランクリスト` (+ `acvite dr user`, `List_dr_LP_hospital`, `List_dr_without_LP_hospital`) and 3 BigQuery master tables |

Language note: code, sheet and column names are Japanese + Vietnamese (step
comments are `BƯỚC N` = "Step N"); this README is English with inline glosses.

---

## 2. Package layout (`src/`)

```
src/
├── config.py              # env secrets + static Drive/Sheet/BQ IDs and names        → docs/gcp-and-config.md
├── gcp_clients.py          # one service-account credential → Drive/gspread/BigQuery  → docs/gcp-and-config.md
├── drive_utils.py          # read/list CSVs from Shared Drive folders                 → docs/drive-utils.md
├── sheet_utils.py          # Sheets write patterns (overwrite vs column write-back)   → docs/sheet-utils.md
├── main.py                 # orchestrates the full run, in step order                 → docs/orchestration-runtime.md
└── pipeline/
    ├── mr_master.py         # Steps 1-12  → BigQuery `mr_master`                       ┐
    ├── hospital_master.py   # Steps 13-18 → BigQuery `hospital_master`                 ├ docs/masters.md
    ├── lp_label.py          # Steps 19-23 → BigQuery `lp_label_master`                 ┘
    ├── dr_active.py         # Steps 24-26 → write-back `面会リクエスト日` to `5.Dr user active` ┐
    ├── s_rank.py            # Steps 27-36 → `Sランクリスト` (incl. 30-day already-sent filter) ├ docs/s-rank.md
    ├── active_dr_user.py    # Steps 37-39 → `acvite dr user`                            │
    └── case_analysis.py     # Steps 40-46 → Case sheets + Pattern write-back            ┘
```

---

## 3. Processing flow (input → transform → output)

Run order (`main.py`): **masters → dr_active → s_rank → active_dr_user → case_analysis**.
`s_rank_df` (after the 30-day filter) is the single object that flows through
Pattern/Case classification.

1. **mr_master** (Steps 1-12): concat `pr_registration_officeusers_*.csv` +
   `handlingHospital_*.csv` → `df_prjoy_userinfo` with per-MR
   `assigned_hospital_count`. Push to BQ `mr_master`. (`Mr Master Info` sheet is
   **cleared only** — the write is intentionally disabled.)
2. **hospital_master** (Steps 13-18): `handling_hp` → `handling_hp_final`
   (MR↔hospital + start date) joined with `hp_master_df.csv` (prefecture, PIC
   count). Push to BQ `hospital_master`.
3. **lp_label** (Steps 19-23): `liteplan_payment.csv` → drop fully-cancelled →
   derive `is_first_purchase` (last 1 month) + `number_of_contract` → `lp_info`.
   Push to BQ `lp_label_master`.
4. **dr_active** (Steps 24-26): load `Dr_active_user.csv`, `dr_menkai_status.csv`
   (`面会ステータス=="FIXED"`), `dr_chat_status.csv`; enrich with latest chat date +
   `面会リクエスト日`; **write that column back** to `5.Dr user active`.
5. **s_rank** (Steps 27-36):
   - keep brand-new single-contract buyers with ≥2 hospitals, purchased within 15
     days; join MR menkai (`面会ステータス=="NEW"`) + aggregated MR chat status;
   - **S-rank condition:** chat unread ≥ 5 days old (**cond1**) OR menkai request ≥
     5 days old (**cond2**); add `S判定条件` = `メッセージ` / `面会` / `メッセージ・面会`;
   - **30-day already-sent filter:** drop any `officeUserId` present in the `Log`
     sheet with a `送信日時` within the last 30 days (so nobody is contacted twice in
     a 30-day window);
   - write `Sランクリスト`. The filtered `s_rank_df` flows into steps 6-7.
6. **active_dr_user** (Steps 37-39): active Drs (last access ≤ 7 days, has msg or
   meeting, exclude Dr.JOY/テスト/test) → `acvite dr user`.
7. **case_analysis** (Steps 40-46): **Case 1** = active Drs at the S-rank MR's
   purchased hospital → `List_dr_LP_hospital`; **Case 2** = other hospitals the MR
   covers with active Drs → `List_dr_without_LP_hospital`; then assign **Pattern**
   and `suggest_hospital_name`, written back to `Sランクリスト`.

> **Pattern semantics:**
> - **Pattern Sα-1** — the purchased hospital has active Drs to engage now (Case 1).
> - **Pattern Sα-2** — MR has *other* covered hospitals with active Drs (Case 2; listed in `suggest_hospital_name`).
> - **Pattern Sα-3** — both opportunities exist.
> - **Pattern 0** — no active-Dr opportunity found.

Full step-by-step (functions, gotchas, dependencies) lives in
[docs/masters.md](docs/masters.md) and [docs/s-rank.md](docs/s-rank.md).

---

## 4. Data sources & sinks

### Sources — CSVs in Shared Drive folders
| Folder ID | Holds | Read by |
|---|---|---|
| `14vPSh8Jqmf9N1iPmQKzar-W_crGr4-Px` | `pr_registration_officeusers_*.csv` | mr_master |
| `1Dfr-Pbax7CfBBBfBfVT-3HhhZvZwWoFI` | `handlingHospital_*.csv` | mr_master |
| `1WgUeoddIxwV_4qwscCcgor4CUPvpvvqS` | `hp_master_df.csv` | hospital_master |
| `10GZeXE0AYTekK-A7Wv1kfMSLu4mwijFw` | `liteplan_payment.csv` | lp_label |
| `123W8yRftyjPNFK_7wcn87uCyEwRCAwmh` | `Dr_active_user.csv`, `dr_menkai_status.csv`, `dr_chat_status.csv`, `mr_chat_status.csv` | dr_active, s_rank |

### Sinks — BigQuery (project `vn-da-498509`, dataset `SD`)
| Table | Written by | Contents |
|---|---|---|
| `mr_master` | mr_master | Pr.JOY MR users + `assigned_hospital_count` |
| `hospital_master` | hospital_master | MR↔hospital assignments + prefecture / PIC count |
| `lp_label_master` | lp_label | Lite Plan purchases + `is_first_purchase`, `number_of_contract` |

### Sinks — Google Sheets
| Sheet | Spreadsheet | Written by | Mode |
|---|---|---|---|
| `Mr Master Info` | `1FYceOW…` (MAIN) | mr_master | clear only (write disabled) |
| `5.Dr user active` | `1FYceOW…` (MAIN) | dr_active | column write-back (`面会リクエスト日`) |
| `Log` | `1oEIr4…` (OUT) | *(external)* | **read only** — 30-day already-sent filter |
| `Sランクリスト` | `1oEIr4…` (OUT) | s_rank + case_analysis | overwrite + `Pattern`/`suggest_hospital_name` write-back |
| `acvite dr user` | `1oEIr4…` (OUT) | active_dr_user | overwrite (name intentionally misspelled "acvite") |
| `List_dr_LP_hospital` | `1oEIr4…` (OUT) | case_analysis | overwrite |
| `List_dr_without_LP_hospital` | `1oEIr4…` (OUT) | case_analysis | overwrite |

**Date-sensitive:** windows are relative to run time — Lite-plan 1 month / 15 days,
chat & menkai 5 days, Dr active 7 days, already-sent 30 days (`SENT_WINDOW_DAYS`).

---

## 5. Credentials

Runs headless in CI (no interactive Colab auth), so **Drive, Sheets, and BigQuery
are all authenticated with the same service account**. Before running:

1. Create a GCP service-account JSON key with BigQuery Data Editor + Job User on
   the target project.
2. Share every source Drive folder and output Spreadsheet (§4) with the service
   account's `client_email` (Viewer/Editor).
3. Set repository secrets `GCP_SERVICE_ACCOUNT_KEY` (full JSON), `PROJECT_ID`,
   `DATASET_ID`. See [`.env.example`](.env.example) for local runs.

A "file not found" from Drive is almost always a **sharing** problem, not a code
bug. Details in [docs/gcp-and-config.md](docs/gcp-and-config.md).

---

## 6. Running

- **Locally:** `pip install -r requirements.txt`, export the three env vars, then
  `python -m src.main`.
- **CI:** [`.github/workflows/data_creation.yml`](.github/workflows/data_creation.yml)
  runs it on `workflow_dispatch` and a daily schedule (07:37 JST, Mon–Fri).
- **Colab:** open `Colab Task.ipynb` and Run all — it mirrors `src/` but
  authenticates as the running Google account (no service-account key). It is a
  **generated** file; change logic in `src/` and regenerate, never hand-edit.

Run order and the objects threaded between steps are in
[docs/orchestration-runtime.md](docs/orchestration-runtime.md).

---

## 7. Conventions (see CLAUDE.md for the full list)

- **Shared Drive API:** always `supportsAllDrives=True` (+ `includeItemsFromAllDrives=True` on list).
- **Sheets:** prefer column-scoped `write_column` to preserve formatting; only
  clear+overwrite sheets the pipeline fully owns.
- **IDs:** normalize to `str` + `.str.strip()` before any join/compare.
- **Logging:** short `✓`/`⚠` one-liners with row counts; never print DataFrames.
- **Style:** vibe coding — simple, no over-engineering, no OOP when a function does.

---

## Note on history

Earlier this repo was a single 24-cell Colab notebook that also contained a
**polars** master-data setup (user/office masters, `save_csv_to_drive`, SQLite
helpers) and a raw-CSV-to-sheet mirror step. **Only the S-Rank pipeline was ported
to `src/`**; that polars setup and the mirror step are **not** part of the current
code. If you see references to them elsewhere, treat `src/` + `docs/` as
authoritative.
