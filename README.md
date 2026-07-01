# Create-ranking-mr-list

Create list of Mr user that in the verge of cancelling liteplan service, ranking base on piority to deal and counter measure (nessesary information to send automation notification on Pr.JOY APP on behalf of Hospital)

---

## Colab Task.ipynb — Technical Reference

> **Audience:** AI agents / engineers maintaining this notebook in the future.
> **Language note:** Code and sheet/column names are in Japanese + Vietnamese; this README is in English. Japanese terms are translated inline where useful.
> **Last documented:** 2026-06-30. Notebook format: `nbformat 4`, 24 cells (22 code, 2 effectively empty/markdown).

---

## 1. Purpose & high-level overview

This notebook is a **Google Colab batch job** for the 医薬連携事業部 (Pharma-Medical Liaison Division). It builds two independent deliverables that feed sales/CS outreach:

| Pipeline | Goal | Output sheet(s) |
|---|---|---|
| **A. S-Rank List** (実行計画_フェーズ1) | Identify MR (pharma sales reps) on the **Lite Plan** who just purchased and look "stuck" (unread chat / no meeting response), then suggest hospitals where they can act. Tag each with a **Pattern**. | `Sランクリスト`, `acvite dr user`, `List_dr_LP_hospital`, `List_dr_without_LP_hospital` |

The pipeline uses **setup cells (0–5)** which authenticate, mount Drive, define paths/IDs, helper functions, and load master data.

### Data sources & sinks
- **Sources:** CSV files in Google **Shared Drives** (read via Drive API by folder ID), and several **Google Spreadsheets** (read via `gspread`).
- **Sinks:** **BigQuery** (`vn-da-498509.SD.*` tables) and **Google Sheets** (via `gspread` / `set_with_dataframe`).
- Two DataFrame libraries are used in parallel: **polars** (`pl`) in the master-data setup, **pandas** (`pd`) in the two pipelines. Do not assume one — check per cell.

### ⚠️ Important state/ordering notes for any agent editing this
- **Cells must run top-to-bottom.** Later cells depend on globals defined earlier (`lp_info`, `df_export`, `s_rank_df`, `handling_hp`, `worksheet_out`, etc.).
- The name **`handling_hp` is redefined** between pipelines. In cell 5 it is a **polars** master; in cell 7 it is **reassigned to a pandas** DataFrame loaded from `handlingHospital_*.csv`. Pipeline A (cells 7+) uses the pandas version.
- Several **write-to-sheet / write-to-BigQuery calls are commented out** (see §6). The notebook in its current state computes everything but only persists a subset. Treat commented blocks as intentional toggles, not dead code.
- `today = pd.Timestamp.now()` / `date.today()` is recomputed in multiple cells — the job is **date-sensitive** (windows like "≤15 days", "≥5 days", "last 7 days", "this month").

---

## 2. Setup section (cells 0–5)

### Cell 0 — markdown
Header: `⚙️ ライブラリー＆設定` (Libraries & Settings).

### Cell 1 — Library install & imports
- `pip install`: `japanize_matplotlib`, `plotly`, `icecream`, `connectorx==0.4.1`, `mojimoji`, `jpholiday`.
- Imports the full analytics stack: `pandas`, `polars as pl`, `numpy`, `gspread` + `gspread_dataframe`, Google API clients, `scipy`, `matplotlib`/`seaborn`/`plotly`, `sqlite3`, date libs (`datetime`, `dateutil`, `jpholiday`, `calendar`), `unicodedata`, `mojimoji`, etc.
- Sets up `creds, _ = default()` and `drive_service = build('drive','v3', ...)`.
- Defines `ic` (icecream debug print) with a fallback no-op.

### Cell 2 — Drive mount & auth
`gc = gspread.authorize(creds)`, `auth.authenticate_user()`, `drive.mount('/content/drive/')`. **`gc`** (gspread client) and the mounted Drive are used everywhere downstream.

### Cell 3 — Paths, spreadsheet keys, helpers (largest config cell)
Three logical blocks:
1. **Directory paths** into the Shared Drive (`dir_user_data`, `data_dir`, `main_dir`, `meeting_dir`, etc.) for the monitoring data lake.
2. **Spreadsheet keys & sheet names** — dozens of `*_key` constants (e.g. `medicaloffice_key`, `pharmacyoffice_key`, `info_key`, `master_key`) and output folder IDs. Also datetime format strings (`formetter*`) and `yyyymm_*` month-list helpers (rolling 3m/6m windows, `now = utcnow + 9h` for JST).
3. **Helper functions** (reused later):
   - `create_wb_ws(key, sheetnames)` → open workbook + worksheets.
   - `get_dataframe_from_spread(...)` / `get_pldf_from_spread(key, sheetnames, header_num)` → pull sheets into pandas / polars dicts.
   - `get_df_from_sqlite` / `get_pldf_from_sqlite` → read from a local SQLite db.
   - `drop_duplicate_rec(...)` → keep latest row per key (polars, sort by datetime).
   - Date utilities: `get_month_end_date`, `extract_date` (regex → normalized `yyyy-mm-dd`), `date_range`, `extract_time` (parse "N時間M分" → minutes).
   - `get_csv_data_from_folda` / `get_json_data_from_folda` → concat all files in a folder.
   - `create_bednum_class`, `calculate_devide` (safe divide).
   - **`save_csv_to_drive(df, filename, folder_id)`** → upsert a CSV into a Drive folder (search by name, then update-or-create via Drive API). Key utility for persisting outputs.

### Cell 4 — BASIC DATA (polars)
Loads and cleans the **user master**:
- `drjoyuser_raw_data`, `prjoyuser_raw_data` — all Dr.JOY / Pr.JOY office users (glob-read many CSVs, `.unique()`).
- `prjoyuser` — renamed/typed subset (plan type mapped via `subscription_mapping`, login date parsed).
- `master_user_df` — union of Dr.JOY + Pr.JOY core columns.
- `medical_office_df`, `hospital_df`, `pharmacy_office_df` — office masters from sheets.
- External/info sheets: `test_office_df`, `cop_office_df` (corporate-plan companies, incl. a Shionogi variant), `suzuken_group_df`, `bed_num_df`, `foreign_owned_df`.
- `profile_df` — Pr.JOY user profiles (sex/age/created, 担当都道府県 prefecture handling expanded from `"all"`, capital type 内資/外資).
- `billed_companies_df` — billable companies (`test=="0"` & `課金対象=="Yes"`), tagged 内資/外資.
- Uses `ic(...)` to log shapes throughout.

### Cell 5 — HANDLING HOSPITAL (polars)
Builds the **MR→hospital assignment master** and maintains assignment history:
- `handling_hp` (polars) — current assignment list, joined with Pr.JOY users and medical-office master, renamed via `handling_renamer`, `end` set to "now (JST)".
- `handling_hp_with_plan` — adds plan name (corporate vs lite/full) and last login.
- `handlingHospital_saved` — **persisted history** in `main_dir+"handlingHospital_saved.csv"`. Logic: compare previous keys (`pre_linkages`) vs current keys (`post_linkages`) to set each link's `end` (still active → end of day; dropped → previous end). Appends past records and **writes back to CSV only if row count grew** (`if len2 > len1`).

> **Note:** This polars `handling_hp` is **shadowed** by a pandas reload in cell 7. Cells 6+ (Pipeline A) do not use this polars version directly except through the saved CSV indirectly.

---

## 3. Pipeline A — S-Rank List (cells 6–23)

Markdown header cell 6: `実行計画_フェーズ1‐データ作成` (Execution plan phase 1 — data creation). Steps are labeled `BƯỚC N` (Vietnamese for "Step N") in comments.

### Cell 7 — `Tạo MR info` (Steps 1–12): build & push `mr_master`
- Re-auths, builds Drive `service`.
- Reads all `pr_registration_officeusers_YYYY.csv` (regex match) from `FOLDER_ID="14vPSh8..."` → `df_prjoy_userinfo` via helper `read_csv_from_drive(file_id, name)` (adds `_source_file`).
- Selects core columns (`officeUserId, created, userName, age, sex, jobName, officeId, officeName, officeType`).
- Reads `handlingHospital_YYYY.csv` from `FOLDER_ID_7` → **`handling_hp` (now pandas)**.
- **Step 9:** `mr_hospital_count` = per-MR distinct hospital count (`groupby officeuserid → nunique officeid`), renamed `assigned_hospital_count`.
- Joins count into `df_prjoy_userinfo`, drops rows with no count.
- **Step 11:** push `df_prjoy_userinfo` to **BigQuery** `vn-da-498509.SD.mr_master` (`WRITE_TRUNCATE`).
- **Step 12:** opens output spreadsheet `1FYceOW...` sheet `Mr Master Info`, clears it — **but the actual `worksheet.update(...)` is commented out** (data prepared, not written).

### Cell 8 — `Master bệnh viện phụ trách` (Steps 13–18): build & push `hospital_master`
- `handling_hp_final` = `handling_hp[[officeuserid, officeid, start]]` renamed to `officeUserId/officeId/assigned_start_date`.
- Loads `hp_master_df.csv` (folder `1WgUeo...`) → keeps `officeId, 都道府県→prefecture, 全担当者数→assigned_pic_count`; left-joins into `handling_hp_final`.
- Loads `hospital_name_prefecture.csv` (just printed, used as reference).
- **Step 18:** push `handling_hp_final` to BigQuery `SD.hospital_master` (`WRITE_TRUNCATE`, autodetect).

### Cell 9 — `Liteplan` (Steps 19–22): build `lp_info`
- Loads `liteplan_payment.csv` (folder `10GZeX...`) → `lp_info`.
- **Step 20:** drop rows where **both** cancellation columns present (`解除予約日` *and* `解除完了日` non-null are removed; keeps rows where at least one is NaN → i.e. not fully cancelled).
- **Step 21:** derive columns:
  - `key = ユーザーID + "_" + ライト購入施設ID`.
  - parse `購入時刻` → datetime.
  - `is_first_purchase` = purchase within the **last 1 month**.
  - `number_of_contract` = count of that user's `ユーザーID` across the table.
- **Step 22:** select & rename to `officeuserid, mr_name, officeid, purchase_date, is_first_purchase, number_of_contract`.

### Cell 10 — Step 23: push `lp_info` → BigQuery `SD.lp_label_master`.

### Cell 11 — `5.Dr user active` (Steps 24–25): load Dr active + menkai + chat
- Opens main spreadsheet `1FYceOW...` as `spreadsheet_main` (used for write-back in cell 12).
- Loads 3 CSVs from `FOLDER_ID_DR="123W8y..."` via `load_csv_by_name`:
  - `Dr_active_user.csv` → `df_dractive_users`
  - `dr_menkai_status.csv` → `df_menkai` (**filtered to `面会ステータス=="FIXED"`**)
  - `dr_chat_status.csv` → `df_dr_chat`
- **Step 24b:** merge latest `Updated Date` (per chat sender `送信者ID`) into `df_dractive_users`.
- **Step 25:** merge latest `リクエスト日時 Date` (per `Dr Office User ID`) as **`面会リクエスト日`** (meeting request date) into `df_dractive_users`.

### Cell 12 — Step 26: write `面会リクエスト日` column back to sheet `5.Dr user active` (column-targeted update via `R2C{idx}` notation).

### Cell 13 — Steps 27–28: start S-rank filtering (`XỬ LÝ LẤY S RANK`)
- **Step 27:** `lp_info_new` = `lp_info` where `is_first_purchase==True` AND `number_of_contract==1` (brand-new single-contract Lite Plan buyers).
- **Step 28:** join `assigned_hospital_count` from `df_prjoy_userinfo`.

### Cell 14 — Step 29: filter `assigned_hospital_count >= 2` AND `purchase_date` within **last 15 days**.

### Cell 15 — Steps 30–33: join MR menkai & chat status
- **Step 30:** reload `dr_menkai_status.csv` → `df_mr_menkai_raw`; `df_mr_menkai` filtered to `面会ステータス=="NEW"`.
- **Step 31:** merge latest `リクエスト日時 Date` per MR (`Mr Office User ID`) into `lp_info_new`.
- **Step 32:** load `mr_chat_status.csv` → `df_mr_chat_raw` / `df_mr_chat`.
- **Step 33:** per MR aggregate chat (`未読のメッセージ数` sum, `既読者ID` last, `Updated Date` max) → merge into `lp_info_new`.

### Cell 16 — Step 34: write the two raw CSVs back to sheets
`df_mr_menkai_raw` → sheet `4.5 面会リクエスト(MR)`; `df_mr_chat_raw` → sheet `4.メッセージ （MR)` (both `clear()` + `set_with_dataframe`). **This write is active (not commented).**

### Cell 17 — Step 35: build `s_rank_df` (the core S-rank condition)
`today` vs `Updated Date` (chat) and `リクエスト日時 Date` (menkai):
- **cond1** (stuck chat): chat `Updated Date` ≥ 5 days old **AND** `既読者ID` empty (unread).
- **cond2** (stuck menkai): menkai request ≥ 5 days old.
- `s_rank_df = lp_info_new[cond1 | cond2]`.

### Cell 18 — Step 36: push `s_rank_df` → output spreadsheet `1oEIr4...` sheet **`Sランクリスト`** (renames `リクエスト日時 Date`→`面会リクエスト日時`, clears + writes). `spreadsheet_out` defined here is reused by later cells.

### Cell 19 — Steps 37–39: build & push `acvite dr user`
- Rename `df_dractive_users` columns to readable English (`officeUserId, name, officeId, hospitalName, last_access_date, last_message_date, last_meeting_date`).
- **Step 38 filter:** `last_access_date` within last 7 days, AND (has message date OR meeting date), AND not Dr.JOX/テスト hospital, AND name not containing "test".
- **Step 39:** push to sheet `acvite dr user` (note: sheet name is intentionally misspelled "acvite").

### Cell 20 — Steps 40–41: Case 1 — active Drs at S-rank MRs' hospitals
- `s_rank_officeids` = set of `officeid` in `s_rank_df`.
- `df_active_dr_at_mr_hp` = active Drs (`df_dractive_users_filtered`) whose `officeId` is in that set.
- Push to sheet **`List_dr_LP_hospital`**.

### Cell 21 — Steps 42–44: Case 2 — hospitals an S-rank MR covers but NOT in `s_rank_df`
- `df_case2` = rows of `handling_hp_final` where `officeUserId` is an S-rank MR but `(officeUserId, officeId)` pair is **not** in `s_rank_df`.
- Rename `officeUserId→MrOfficeUserId`; **inner-join** active Drs by `officeId`; attach `officeName`.
- Push to sheet **`List_dr_without_LP_hospital`**.

### Cell 22 — Steps 45–46: assign `Pattern` to `s_rank_df`
For each S-rank row, check membership in Case1 (`officeid` ∈ `df_active_dr_at_mr_hp`) and Case2 (`officeuserid` ∈ `df_case2.MrOfficeUserId`):
- in both → **Pattern 3**; only Case1 → **Pattern 1**; only Case2 → **Pattern 2**; neither → **Pattern 0**.
Then write the `Pattern` column back to `Sランクリスト`.

### Cell 23 — Step 45b/46: add `suggest_hospital_name`
- Build map `MrOfficeUserId → comma-joined officeName list` from `df_case2`, ordered by Dr count desc.
- Merge into `s_rank_df`; blank it out for rows **not** Pattern 2 or 3.
- Write **both** `Pattern` and `suggest_hospital_name` columns back to `Sランクリスト`.

> **Pattern semantics (business meaning):**
> - **Pattern 1** — MR's purchased hospital has active Drs to engage now.
> - **Pattern 2** — MR has *other* covered hospitals with active Drs (suggested in `suggest_hospital_name`).
> - **Pattern 3** — both opportunities exist.
> - **Pattern 0** — no active-Dr opportunity found.

---

## 5. Key identifiers reference

### BigQuery (project `vn-da-498509`, dataset `SD`)
| Table | Written by | Contents |
|---|---|---|
| `mr_master` | Cell 7 | Pr.JOY MR users + `assigned_hospital_count` |
| `hospital_master` | Cell 8 | MR↔hospital assignments + prefecture/PIC count |
| `lp_label_master` | Cell 10 | Lite Plan purchases + `is_first_purchase`, `number_of_contract` |

### Output spreadsheets
| Sheet name | Spreadsheet ID | Written by | Status |
|---|---|---|---|
| `Mr Master Info` | `1FYceOW233uL6fThahPHmaecJAhNKdwedHmrVocYsS_I` | Cell 7 | clear only (update commented) |
| `5.Dr user active` | (same `1FYceOW...`) | Cell 12 | **active** |
| `4.5 面会リクエスト(MR)`, `4.メッセージ （MR)` | (same) | Cell 16 | **active** |
| `Sランクリスト` | `1oEIr4zbl8YPrbiPqXXL1KQ-DAD1JV4lGeuZw64O8pfg` | Cells 18, 22, 23 | **active** |
| `acvite dr user` | (same `1oEIr4...`) | Cell 19 | **active** |
| `List_dr_LP_hospital` | (same) | Cell 20 | **active** |
| `List_dr_without_LP_hospital` | (same) | Cell 21 | **active** |

### Input Drive folder IDs
| Folder ID | Holds |
|---|---|
| `14vPSh8Jqmf9N1iPmQKzar-W_crGr4-Px` | `pr_registration_officeusers_*.csv` |
| `1Dfr-Pbax7CfBBBfBfVT-3HhhZvZwWoFI` | `handlingHospital_*.csv`, `hospital_name_prefecture.csv` |
| `1WgUeoddIxwV_4qwscCcgor4CUPvpvvqS` | `hp_master_df.csv` |
| `10GZeXE0AYTekK-A7Wv1kfMSLu4mwijFw` | `liteplan_payment.csv` |
| `123W8yRftyjPNFK_7wcn87uCyEwRCAwmh` | `Dr_active_user.csv`, `dr_menkai_status.csv`, `dr_chat_status.csv`, `mr_chat_status.csv` |

---

## 6. Operational notes / gotchas for future edits

1. **To actually publish outputs**, uncomment the `worksheet.update(...)` block in cell 7. Cells 12, 16, 18–23 already write live.
2. **ID normalization:** Sheet reads can introduce trailing `.0` (float coercion). `normalize_id` / `normalize` strip it; apply consistently when joining IDs read from Sheets.
3. **Date windows are relative to run time** (JST = UTC+9 in setup). Re-running on a different day changes results: Lite-plan "1 month"/"15 days", chat/menkai "5 days", Dr active "7 days".
4. **`handling_hp` shadowing** (polars cell 5 → pandas cell 7) — be explicit about which you mean when editing.
5. **Idempotency:** Pipeline A sheets are **clear + overwrite**.
6. **`set_with_dataframe` vs `worksheet.update`**: the notebook uses `set_with_dataframe` for full-table writes and `R{r}C{c}` ranged `update` for single-column write-backs. Single-column writes assume row order matches the existing sheet.
7. Cells use Vietnamese `BƯỚC` (Step) and emoji print logging; the `ic(...)` calls log polars shapes. None of this affects logic — safe to keep.

---

## 7. Repository version of Phase 1 (`src/`)

Cells 7–23 (Pipeline A / 実行計画_フェーズ1‐データ作成) have been extracted out of the notebook into a
standalone, GitHub Actions-runnable package under [`src/`](src/). Phase 1 only depends on cells 1–2
(auth) and its own inline helpers — it does **not** use the polars master-data cells (3–5) — so nothing
else from the notebook was ported.

```
src/
├── config.py            # env vars (secrets) + static Drive/Sheet IDs, BQ table names
├── gcp_clients.py        # one service-account credential → drive_service, gspread client, bigquery client
├── drive_utils.py        # read/list CSVs from Drive folders
├── sheet_utils.py        # shared Sheets write patterns (clear+overwrite, single-column write-back)
├── main.py               # orchestrates the full Phase 1 run, in cell order
└── pipeline/
    ├── mr_master.py        # Steps 1-12  → BigQuery `mr_master`
    ├── hospital_master.py  # Steps 13-18 → BigQuery `hospital_master`
    ├── lp_label.py         # Steps 19-23 → BigQuery `lp_label_master`
    ├── dr_active.py        # Steps 24-26 → write-back to `5.Dr user active`
    ├── s_rank.py           # Steps 27-36 → `Sランクリスト`
    ├── active_dr_user.py   # Steps 37-39 → `acvite dr user`
    └── case_analysis.py    # Steps 40-46 → `List_dr_LP_hospital`, `List_dr_without_LP_hospital`, Pattern write-back
```

### Credentials

Because this runs headless in CI (no Colab interactive auth), **Drive, Sheets, and BigQuery are all
authenticated with the same service account**, not just BigQuery. Before running:

1. Create/obtain a GCP service account JSON key with BigQuery Data Editor + Job User on the target project.
2. Share every source Drive folder and Spreadsheet listed in §5 with that service account's `client_email`
   (as a Viewer/Editor, same as you would with a human collaborator).
3. Set these as GitHub repository secrets: `GCP_SERVICE_ACCOUNT_KEY` (the full JSON key), `PROJECT_ID`,
   `DATASET_ID`. See [`.env.example`](.env.example) for local runs.

### Running

- **Locally:** `pip install -r requirements.txt`, export the three env vars (or use a `.env` loader), then
  `python -m src.main`.
- **CI:** [`.github/workflows/data_creation.yml`](.github/workflows/data_creation.yml) runs it on
  `workflow_dispatch` and a daily schedule (adjust the cron to taste).
