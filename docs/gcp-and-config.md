# docs/gcp-and-config — configuration & GCP clients

Covers `src/config.py` and `src/gcp_clients.py`: the foundation every other module
imports. `config` holds all secrets + static resource IDs; `gcp_clients` turns one
service-account credential into the three Google clients the pipeline uses.

---

## Flow

```
env vars ──> config (validated constants) ──┐
                                             ├─> gcp_clients.get_credentials() ──> Drive / gspread / BigQuery clients
GCP_SERVICE_ACCOUNT_KEY (JSON) ──────────────┘
```

There is no transform here — this module is pure wiring. `main.py` builds the
three clients once at start-up and passes them down to every pipeline step.

---

## `src/config.py`

### Secrets — read from the environment at import time
`get_env(name)` returns `os.environ[name]` and **raises `RuntimeError` if missing
or empty**. It is called at module top level, so:

- `GCP_SERVICE_ACCOUNT_KEY` — full service-account JSON as a single-line string.
- `PROJECT_ID` — GCP project hosting the BigQuery dataset.
- `DATASET_ID` — BigQuery dataset holding the master tables.

### Static (non-secret) constants
- **BQ tables:** `BQ_TABLE_MR_MASTER="mr_master"`, `BQ_TABLE_HOSPITAL_MASTER="hospital_master"`,
  `BQ_TABLE_LP_LABEL_MASTER="lp_label_master"`.
- **Drive folder IDs (source CSVs):** `FOLDER_ID_MR_INFO`, `FOLDER_ID_HANDLING_HOSPITAL`,
  `FOLDER_ID_HP_MASTER`, `FOLDER_ID_LITEPLAN`, `FOLDER_ID_DR_ACTIVITY`.
- **Spreadsheet IDs (sinks):** `SPREADSHEET_ID_MAIN` (write-back target for
  `5.Dr user active`), `SPREADSHEET_ID_OUT` (the S-rank output workbook + `Log`).
- **Sheet names:** `SHEET_MR_MASTER_INFO="Mr Master Info"`, `SHEET_DR_USER_ACTIVE="5.Dr user active"`,
  `SHEET_S_RANK="Sランクリスト"`, `SHEET_LOG="Log"`, `SHEET_ACTIVE_DR_USER="acvite dr user"`,
  `SHEET_CASE1="List_dr_LP_hospital"`, `SHEET_CASE2="List_dr_without_LP_hospital"`.

### Which constant is used where
| Constant | Consumer module |
|---|---|
| `FOLDER_ID_MR_INFO`, `FOLDER_ID_HANDLING_HOSPITAL` | masters (`mr_master`) |
| `FOLDER_ID_HP_MASTER` | masters (`hospital_master`) |
| `FOLDER_ID_LITEPLAN` | masters (`lp_label`) |
| `FOLDER_ID_DR_ACTIVITY` | s-rank (`dr_active`, `s_rank`) |
| `SPREADSHEET_ID_MAIN`, `SHEET_DR_USER_ACTIVE` | s-rank (`dr_active` write-back) |
| `SPREADSHEET_ID_OUT`, `SHEET_S_RANK`, `SHEET_LOG` | s-rank (`s_rank`) |
| `SHEET_ACTIVE_DR_USER` | s-rank (`active_dr_user`) |
| `SHEET_CASE1`, `SHEET_CASE2` | s-rank (`case_analysis`) |
| `PROJECT_ID`, `DATASET_ID`, `BQ_TABLE_*` | masters (all 3 BigQuery pushes) |

---

## `src/gcp_clients.py`

One service account authenticates **all three** services (headless CI has no
interactive Colab auth). Every builder is `@lru_cache(maxsize=1)` so the client is
created once and reused.

| Function | Returns | Notes |
|---|---|---|
| `get_credentials()` | `service_account.Credentials` | `json.loads(config.GCP_SERVICE_ACCOUNT_KEY)` → `from_service_account_info`, scoped to `SCOPES` |
| `get_drive_service()` | Drive v3 service | `build("drive","v3", credentials=...)` |
| `get_gspread_client()` | `gspread.Client` | `gspread.authorize(...)` |
| `get_bigquery_client()` | `bigquery.Client` | `project=config.PROJECT_ID` |

`SCOPES` = drive, spreadsheets, bigquery.

---

## Gotchas
- **Import-time failure:** importing `config` (directly or via any pipeline module)
  raises immediately if `GCP_SERVICE_ACCOUNT_KEY` / `PROJECT_ID` / `DATASET_ID`
  are unset. There is no lazy fallback — set the env (see `.env.example`) first.
- **Service account must be a collaborator:** its `client_email` needs Viewer/Editor
  on every `FOLDER_ID_*` and `SPREADSHEET_ID_*`, plus BigQuery Data Editor + Job
  User. A "file not found" from Drive is usually a *sharing* problem, not a code bug.
- **`SHEET_ACTIVE_DR_USER="acvite dr user"` is intentionally misspelled** — it
  matches the real sheet tab. Do not "fix" it.
- **IDs are not secrets:** folder/spreadsheet/sheet names are hardcoded on purpose
  (stable org resources). Only the three env vars are secret.
- **Colab mirror differs here only:** the notebook swaps the service-account
  credential for interactive Colab auth and hardcodes `PROJECT_ID`/`DATASET_ID`;
  everything downstream is identical.

## Dependencies
- Depended on by: **every** other module (all import `config`; `main` imports
  `gcp_clients`).
- Depends on: nothing internal.
