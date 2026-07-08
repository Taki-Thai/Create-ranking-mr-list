# docs/masters — BigQuery master tables (Steps 1–23)

Covers `src/pipeline/mr_master.py`, `hospital_master.py`, `lp_label.py`. Each builds
one master DataFrame from Drive CSVs and pushes it to BigQuery with
`WRITE_TRUNCATE` (full replace each run). Two of the three also hand a DataFrame to
later steps in-memory.

Run order (from `main.py`): `mr_master` → `hospital_master` → `lp_label`.

---

## mr_master.py — Steps 1–12 → BQ `mr_master`

### Flow
`pr_registration_officeusers_YYYY.csv` (many) + `handlingHospital_YYYY.csv` (many)
→ per-MR hospital count → `df_prjoy_userinfo` (+ `assigned_hospital_count`) → BigQuery.

### Functions
- **`build_mr_master(drive_service) -> (df_prjoy_userinfo, handling_hp)`**
  - `load_and_concat_csvs(FOLDER_ID_MR_INFO, FILE_PATTERN_MR_INFO)` where the pattern
    is `^pr_registration_officeusers_\d{4}\.csv$`; keep `MR_INFO_COLUMNS`
    (`officeUserId, created, userName, age, sex, jobName, officeId, officeName, officeType`).
  - `load_and_concat_csvs(FOLDER_ID_HANDLING_HOSPITAL, ^handlingHospital_\d{4}\.csv$)`
    → **`handling_hp`** (lowercase columns `officeuserid`, `officeid`, `start`, ...).
  - `assigned_hospital_count` = `handling_hp.groupby("officeuserid")["officeid"].nunique()`.
  - Left-merge count onto `df_prjoy_userinfo` (`officeUserId` ↔ `officeuserid`), drop
    the join key, then **drop MRs with no count** (`assigned_hospital_count` NaN).
  - Returns both frames: `df_prjoy_userinfo` (used by s_rank) and **`handling_hp`**
    (used by hospital_master).
- **`push_mr_master_to_bigquery(bq_client, df_prjoy_userinfo)`** — `WRITE_TRUNCATE`
  load to `PROJECT_ID.DATASET_ID.mr_master`.
- **`prepare_mr_master_info_sheet(gspread_client, df_prjoy_userinfo)`** — opens
  `Mr Master Info` and **only `clear()`s it**. The `worksheet.update(...)` is
  intentionally commented out (matches the source notebook — data prepared, not
  written).

### Gotchas
- `handling_hp` here uses **lowercase** `officeuserid`/`officeid`; hospital_master
  renames them to camelCase. Two spellings exist on purpose — mind which frame
  you're holding.
- The `Mr Master Info` write is disabled by design. To actually publish it,
  uncomment the block in `prepare_mr_master_info_sheet`.

---

## hospital_master.py — Steps 13–18 → BQ `hospital_master`

### Flow
`handling_hp` (from mr_master) → `handling_hp_final` (MR↔hospital + start date) join
`hp_master_df.csv` (prefecture, PIC count) → BigQuery.

### Functions
- **`build_hospital_master(drive_service, handling_hp) -> handling_hp_final`**
  - `handling_hp[["officeuserid","officeid","start"]]` renamed to
    `officeUserId / officeId / assigned_start_date`.
  - Reads single `hp_master_df.csv` (`FOLDER_ID_HP_MASTER`) via
    `list_files_in_folder(exact_name=...)` + `read_csv_from_drive` (raises
    `FileNotFoundError` if absent); keep `officeId`, `都道府県→prefecture`,
    `全担当者数→assigned_pic_count`; **left-merge** on `officeId`.
- **`push_hospital_master_to_bigquery(...)`** — `WRITE_TRUNCATE`, `autodetect=True`.

### Gotchas
- Consumes `handling_hp` from mr_master — **ordering dependency**. `handling_hp_final`
  (camelCase `officeUserId`/`officeId`) is returned and later reused by
  case_analysis' Case 2.
- Uses `read_csv_from_drive` directly, so the returned frame carries `_source_file`
  until columns are sub-selected.

---

## lp_label.py — Steps 19–23 → BQ `lp_label_master`

### Flow
`liteplan_payment.csv` → drop fully-cancelled → derive purchase flags → rename →
BigQuery. The returned `lp_info` is the **entry point for the whole S-rank filter**.

### `build_lp_info(drive_service) -> lp_info`
- Read single `liteplan_payment.csv` (`FOLDER_ID_LITEPLAN`).
- **Cancellation filter:** keep rows where `解除予約日` **or** `解除完了日` is NaN
  (`isna() | isna()`) — i.e. drop rows where **both** cancellation dates are set
  (fully cancelled).
- Derive: `key = ユーザーID + "_" + ライト購入施設ID`; `購入時刻 → datetime`;
  **`is_first_purchase`** = `購入時刻` within the **last 1 month** (relative to now);
  **`number_of_contract`** = count of the user's `ユーザーID` across the table
  (via `value_counts` map).
- Select + rename to `officeuserid, mr_name, officeid, purchase_date,
  is_first_purchase, number_of_contract`.
- **`push_lp_label_master_to_bigquery(...)`** — `WRITE_TRUNCATE`, `autodetect=True`.

### Gotchas
- The cancellation filter is inclusive-OR on NaN — a row with only a *reservation*
  date (`解除予約日`) but no completion is **kept**. Read it as "not yet fully
  cancelled".
- `is_first_purchase` / `number_of_contract` are computed here but **consumed in
  s_rank** (`filter_new_lite_plan_purchases`). Changing their definition changes who
  qualifies for the S-rank list.

---

## Cross-module dependencies
- **Produces (in-memory):** `df_prjoy_userinfo` → s-rank; `handling_hp` → hospital_master;
  `handling_hp_final` → case_analysis (Case 2); `lp_info` → s-rank.
- **Depends on:** [drive-utils](drive-utils.md) for all reads,
  [gcp-and-config](gcp-and-config.md) for IDs + BigQuery client,
  [sheet-utils](sheet-utils.md) (`get_or_create_worksheet`) for the disabled
  `Mr Master Info` clear.
