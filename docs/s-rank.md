# docs/s-rank — S-rank list & opportunity patterns (Steps 24–46)

Covers `src/pipeline/dr_active.py`, `s_rank.py`, `active_dr_user.py`,
`case_analysis.py`. This is the core business logic: from Dr/MR activity, find the
"stuck" new Lite-Plan MRs (the **S-rank** list), skip anyone contacted in the last
30 days, then classify each into an opportunity **Pattern** and write everything to
the output workbook (`SPREADSHEET_ID_OUT`).

Run order (from `main.py`):
`dr_active` → `s_rank` → `active_dr_user` → `case_analysis`.

---

## dr_active.py — Steps 24–26

Loads Dr activity CSVs, enriches the Dr-active table with latest chat + meeting
dates, and writes the meeting-request date back to `5.Dr user active`.

- **`load_dr_activity_data(drive_service) -> (df_dractive_users, df_menkai, df_dr_chat)`**
  - `Dr_active_user.csv` → `df_dractive_users` (strip `オフィスユーザーID`).
  - `dr_menkai_status.csv` → `df_menkai`, **filtered to `面会ステータス=="FIXED"`**.
  - `dr_chat_status.csv` → `df_dr_chat` (strip `送信者ID`).
- **`enrich_dr_active_users(df_dractive_users, df_menkai, df_dr_chat)`**
  - Merge latest chat `Updated Date` per sender (`送信者ID → オフィスユーザーID`).
  - Merge latest `リクエスト日時 Date` per Dr (`Dr Office User ID`) as
    **`面会リクエスト日`**. Drops pre-existing copies of these columns first.
- **`write_back_meeting_request_date(spreadsheet_main, df_dractive_users)`** — uses
  `sheet_utils.write_column("面会リクエスト日", ...)` on `5.Dr user active`
  (column-scoped, preserves the sheet's format).

**Gotchas**
- Menkai is filtered **`FIXED`** here (the Dr side). In `s_rank.join_menkai_and_chat`
  the *same CSV* is filtered **`NEW`** (the MR side) — different status, same file.
- `df_dractive_users` keeps its **original Japanese column names** and is passed on
  to `active_dr_user` and `case_analysis` (which each rename it differently).
- The write-back is positional (`write_column`) — assumes row order matches the sheet.

---

## s_rank.py — Steps 27–36 → `Sランクリスト`

The heart of the pipeline. Turns `lp_info` (from masters) into the final `s_rank_df`.

### Flow
```
lp_info ─filter_new_lite_plan_purchases→ lp_info_new ─join_menkai_and_chat→ (+menkai/chat)
        ─build_s_rank_df→ s_rank_df (+S判定条件) ─push_s_rank_to_sheet→ (−30-day-sent) → Sランクリスト
```

### Functions
- **`filter_new_lite_plan_purchases(lp_info, df_prjoy_userinfo)`** (Steps 27–29):
  keep `is_first_purchase==True & number_of_contract==1`; left-merge
  `assigned_hospital_count`; keep `>=2`; keep `purchase_date` within the **last 15
  days** (normalized-day diff).
- **`join_menkai_and_chat(drive_service, lp_info_new)`** (Steps 30–33):
  - `dr_menkai_status.csv` filtered **`NEW`** → latest `リクエスト日時 Date` per MR
    (`Mr Office User ID → officeuserid`).
  - **Also** (from the *unfiltered* menkai CSV, before the NEW-only filter) counts
    per MR of `面会ステータス=="FIXED"` and `=="NEW"` → columns
    **`menkai_fixed_count`** / **`menkai_new_count`** (missing → 0, int). These ride
    along `s_rank_df` all the way to the `Sランクリスト` sheet.
  - `mr_chat_status.csv` → per-MR aggregate: `未読のメッセージ数` **sum**,
    `既読者ID` **last**, `Updated Date` **max**.
  - Drops any pre-existing copies before each merge (idempotent re-join).
- **`build_s_rank_df(lp_info_new)`** (Step 35): the S-rank condition, vs
  `today = now().normalize()`:
  - **cond1 (stuck chat):** chat `Updated Date` ≥ 5 days old **AND** `既読者ID`
    empty/blank (unread).
  - **cond2 (stuck menkai):** `リクエスト日時 Date` ≥ 5 days old.
  - `s_rank_df = lp_info_new[cond1 | cond2]`.
  - Adds **`S判定条件`**: `メッセージ` (cond1), `面会` (cond2), or `メッセージ・面会`
    (both) — built by zipping `cond1[mask]`/`cond2[mask]` positionally.
- **`office_ids_sent_recently(spreadsheet_out)`** — reads the **`Log`** sheet
  (`SHEET_LOG`, same output workbook) and returns the set of office-user IDs whose
  `送信日時` is within the **last `SENT_WINDOW_DAYS` (30) days** up to now:
  - Log id column is `officeUserId` (camelCase) — matched **case-insensitively** to
    `s_rank_df.officeuserid`.
  - `送信日時` parsed with `format="mixed"` (per-value) so odd formats don't become
    NaT and slip through; future-dated rows are excluded (`days_since.between(0,30)`).
  - **Fails safe** (returns `set()` with a `⚠`) if the sheet or its
    `officeUserId`/`送信日時` columns are missing.
- **`push_s_rank_to_sheet(gspread_client, s_rank_df) -> (spreadsheet_out, s_rank_df)`**
  (Step 36):
  1. **Exclude** ids from `office_ids_sent_recently` (the 30-day already-sent filter).
  2. Drop `is_first_purchase / number_of_contract / assigned_hospital_count`.
  3. Rename `リクエスト日時 Date→Request meeting time`, `未読のメッセージ数→Unread message`,
     `既読者ID→reader_id`.
  4. Reorder so **`S判定条件` is the last data column** (so the `Pattern` column
     `case_analysis` appends lands directly after it).
  5. `overwrite_sheet_with_dataframe` to `Sランクリスト`.
  - Returns `spreadsheet_out` (reused by later steps) and the **filtered** `s_rank_df`.

### Gotchas
- **The returned `s_rank_df` is the filtered one** — Case1/Case2/Pattern all run on
  post-30-day-filter rows, keeping the sheet, Pattern write-back, and Case analysis
  mutually consistent. Don't reintroduce the unfiltered frame downstream.
- **Tune the window via `SENT_WINDOW_DAYS`** (module constant). `between(0, 30)` is
  **inclusive** — exactly-30-days-ago is still excluded.
- `S判定条件` alignment relies on `zip(cond1[mask], cond2[mask])` following the same
  row order as `lp_info_new[mask]` — it does; don't reorder before assigning it.
- Final sheet column order: `… , S判定条件, Pattern, suggest_hospital_name` (last two
  appended later by `write_column`).

---

## active_dr_user.py — Steps 37–39 → `acvite dr user`

- **`filter_active_dr_users(df_dractive_users)`**: rename Japanese → English
  (`officeUserId, name, officeId, hospitalName, last_access_date,
  last_message_date=Updated Date, last_meeting_date=面会リクエスト日`), then keep rows
  where `last_access_date` within the **last 7 days** AND (has message date OR
  meeting date) AND hospital not matching `Dr\.JOY|テスト` AND name not containing
  `test`.
- **`push_active_dr_users_to_sheet(spreadsheet_out, df)`**: overwrite
  `acvite dr user` (note the intentional "acvite" spelling).

**Gotcha:** input is the enriched `df_dractive_users` (Japanese columns) from
dr_active; the filtered/renamed result feeds Case 1.

---

## case_analysis.py — Steps 40–46 → Case sheets + Pattern

Two opportunity cases, then the Pattern label and suggested hospitals.

- **`build_case1_active_dr_at_lp_hospital(s_rank_df, df_dractive_users_filtered)`**
  (Step 40): active Drs whose `officeId` ∈ the S-rank MRs' purchased-hospital IDs
  (`s_rank_df.officeid`). → sheet `List_dr_LP_hospital`.
- **`build_case2_hospitals_without_lp(s_rank_df, handling_hp_final, df_dractive_users)`**
  (Steps 42–43): from `handling_hp_final`, rows where `officeUserId` is an S-rank MR
  but the `(officeUserId, officeId)` pair is **not** in `s_rank_df` (i.e. *other*
  hospitals the MR covers). Rename `officeUserId→MrOfficeUserId`; **inner-join**
  active Drs by `officeId`; attach `officeName`. → sheet `List_dr_without_LP_hospital`.
- **`assign_pattern(s_rank_df, df_active_dr_at_mr_hp, df_case2)`** (Step 45):
  - in Case1 **and** Case2 → **`Pattern Sα-3`**
  - Case1 only → **`Pattern Sα-1`**
  - Case2 only → **`Pattern Sα-2`**
  - neither → **`Pattern 0`**
- **`assign_suggested_hospital_name(s_rank_df, df_case2, max_hospitals=3)`** (Step 45b):
  for `Pattern Sα-2`/`Sα-3` rows, list up to **3** Case2 hospitals for that MR,
  ordered by Dr count desc; **blanked** for other patterns.
- **`write_back_pattern_and_suggestion(spreadsheet_out, s_rank_df)`** (Step 46):
  `write_column` for `Pattern` then `suggest_hospital_name` on `Sランクリスト`.

### Gotchas
- **Case 2 uses the *raw* `df_dractive_users`** (original Japanese columns `企業ID`,
  `事業所名`, `オフィスユーザーID`), **not** the filtered/renamed active-Dr frame. Mixing
  them up breaks the join. Case 1 uses the **filtered** frame.
- Depends on `handling_hp_final` from [masters](masters.md) (hospital_master).
- Pattern labels are `Pattern Sα-1/Sα-2/Sα-3` + `Pattern 0`. If you rename them,
  update `assign_suggested_hospital_name`'s `isin([...])` check too, plus README and
  the notebook.
- Both write-backs are positional (`write_column`) against the sheet that
  `push_s_rank_to_sheet` wrote — order must match, which is why the same filtered
  `s_rank_df` is threaded through.

---

## Module dependency summary
- **Inputs:** `lp_info`, `df_prjoy_userinfo`, `handling_hp_final` (from masters).
- **Internal thread:** `df_dractive_users` (dr_active) → active_dr_user + case_analysis;
  `s_rank_df` (s_rank, filtered) → active_dr_user's Case1 + case_analysis + Pattern.
- **Utils:** [drive-utils](drive-utils.md) for CSV reads, [sheet-utils](sheet-utils.md)
  for every write, [gcp-and-config](gcp-and-config.md) for IDs/clients.
