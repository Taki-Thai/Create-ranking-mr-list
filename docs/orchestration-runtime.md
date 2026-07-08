# docs/orchestration-runtime — run order & CI

Covers `src/main.py` (the orchestrator) and `.github/workflows/data_creation.yml`
(how it runs headless). `Colab Task.ipynb` is a generated mirror and is out of
scope by request — regenerate it from `src/`, don't hand-edit it.

---

## `src/main.py` — orchestration

Entry point: `python -m src.main` → `main()`. It builds the three GCP clients once
(from [gcp-and-config](gcp-and-config.md)) and runs the pipeline strictly in cell
order. There is **no branching or retry** — it's a linear script; a failure aborts
the run.

### Exact sequence
```
drive_service, gspread_client, bq_client = get_*()                 # gcp_clients

# masters (docs/masters.md)
df_prjoy_userinfo, handling_hp = mr_master.build_mr_master(...)
mr_master.push_mr_master_to_bigquery(...)
mr_master.prepare_mr_master_info_sheet(...)                        # clear only
handling_hp_final = hospital_master.build_hospital_master(handling_hp)
hospital_master.push_hospital_master_to_bigquery(...)
lp_info = lp_label.build_lp_info(...)
lp_label.push_lp_label_master_to_bigquery(...)

# s-rank (docs/s-rank.md)
spreadsheet_main = gspread_client.open_by_key(SPREADSHEET_ID_MAIN)
df_dractive_users, df_menkai, df_dr_chat = dr_active.load_dr_activity_data(...)
df_dractive_users = dr_active.enrich_dr_active_users(...)
dr_active.write_back_meeting_request_date(spreadsheet_main, ...)

lp_info_new = s_rank.filter_new_lite_plan_purchases(lp_info, df_prjoy_userinfo)
lp_info_new = s_rank.join_menkai_and_chat(...)
s_rank_df   = s_rank.build_s_rank_df(lp_info_new)
spreadsheet_out, s_rank_df = s_rank.push_s_rank_to_sheet(...)      # ← 30-day filter here

df_dractive_users_filtered = active_dr_user.filter_active_dr_users(df_dractive_users)
active_dr_user.push_active_dr_users_to_sheet(spreadsheet_out, ...)

df_active_dr_at_mr_hp = case_analysis.build_case1_active_dr_at_lp_hospital(s_rank_df, df_dractive_users_filtered)
case_analysis.push_case1_to_sheet(...)
df_case2 = case_analysis.build_case2_hospitals_without_lp(s_rank_df, handling_hp_final, df_dractive_users)
case_analysis.push_case2_to_sheet(...)

s_rank_df = case_analysis.assign_pattern(s_rank_df, df_active_dr_at_mr_hp, df_case2)
s_rank_df = case_analysis.assign_suggested_hospital_name(s_rank_df, df_case2)
case_analysis.write_back_pattern_and_suggestion(spreadsheet_out, s_rank_df)
```

### Data threaded between steps (why order is fixed)
| Object | Produced by | Consumed by |
|---|---|---|
| `handling_hp` | `build_mr_master` | `build_hospital_master` |
| `handling_hp_final` | `build_hospital_master` | `build_case2_hospitals_without_lp` |
| `df_prjoy_userinfo` | `build_mr_master` | `filter_new_lite_plan_purchases` |
| `lp_info` | `build_lp_info` | `filter_new_lite_plan_purchases` |
| `df_dractive_users` (raw, JP cols) | `enrich_dr_active_users` | `filter_active_dr_users`, `build_case2` |
| `s_rank_df` (30-day filtered) | `push_s_rank_to_sheet` | Case1/Case2, Pattern, suggestion |
| `spreadsheet_out` | `push_s_rank_to_sheet` | all later sheet writes |

**Gotchas**
- The pipeline is **date-sensitive** — re-running on a different day changes results
  (windows: 1 month / 15 days / 5 days / 7 days / 30 days).
- `df_dractive_users` (raw) and `df_dractive_users_filtered` are **both** live after
  `active_dr_user` — Case 2 needs the raw one, Case 1 needs the filtered one.
- `main()` is not idempotent across the day but **is** overwrite-based per run
  (BigQuery `WRITE_TRUNCATE`, Sheets clear+overwrite / column write-back).

---

## `.github/workflows/data_creation.yml` — CI

- **Triggers:** `workflow_dispatch` (manual) + `schedule` cron `37 22 * * 0-4`.
  Cron is UTC; this is **07:37 JST, Mon–Fri** (JST = UTC+9, so 22:37 UTC the prior
  day, weekday field shifted back one day → Sun–Thu UTC = Mon–Fri JST).
- **Job `run-pipeline`** on `ubuntu-latest`:
  1. `actions/checkout@v4`
  2. `actions/setup-python@v5` with Python **3.11**
  3. `pip install -r requirements.txt`
  4. `python -m src.main` with env `GCP_SERVICE_ACCOUNT_KEY`, `PROJECT_ID`,
     `DATASET_ID` injected from **repository secrets**.

**Gotchas**
- Secrets must exist in the repo settings (`GCP_SERVICE_ACCOUNT_KEY`, `PROJECT_ID`,
  `DATASET_ID`); a missing one makes `config` raise at import (see
  [gcp-and-config](gcp-and-config.md)).
- To change the schedule, edit the cron **in UTC** and re-derive the JST offset
  (and the weekday shift) — the comment in the YAML explains it.
- Python is pinned to 3.11 in CI; `requirements.txt` uses lower-bound pins
  (`pandas>=2.0.0`, etc.), so CI resolves the latest compatible versions.

## Dependencies
- `main.py` depends on **every** other module.
- The workflow depends only on `requirements.txt` + repo secrets.
