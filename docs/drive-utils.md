# docs/drive-utils — reading CSVs from Google Drive

Covers `src/drive_utils.py`. Four small helpers that pull CSV files out of Google
**Shared** Drive folders via the Drive API and return pandas DataFrames. Every
master/activity CSV the pipeline consumes comes through here.

---

## Flow

```
folder_id (+ exact name or regex) ──> list_files_in_folder ──> file metadata (id, name)
file id ──> read_csv_from_drive ──> BytesIO download ──> pd.read_csv ──> DataFrame (+ _source_file)
```

Two convenience wrappers sit on top:
- `load_csv_by_name` — exactly one file, by exact name.
- `load_and_concat_csvs` — many files matching a regex, concatenated.

---

## Functions

### `list_files_in_folder(drive_service, folder_id, name_pattern=None, exact_name=None)`
Builds the query `'{folder_id}' in parents and trashed=false` (plus
`and name='{exact_name}'` when given), calls `files().list(...)` with
`supportsAllDrives=True, includeItemsFromAllDrives=True`, `pageSize=100`,
`fields="files(id, name)"`. If `name_pattern` (a **compiled** regex) is passed,
filters client-side with `pattern.match(name)`. Returns the files **sorted by
name**.

### `read_csv_from_drive(drive_service, file_id, file_name) -> DataFrame`
`files().get_media(...)` → `MediaIoBaseDownload` loop into a `BytesIO` →
`pd.read_csv(buffer)`. Adds a `_source_file` column = `file_name` so concatenated
frames stay traceable to their origin file.

### `load_csv_by_name(drive_service, folder_id, filename) -> DataFrame`
Finds the single file by `exact_name`, **raises `FileNotFoundError`** if absent,
reads it, then **drops `_source_file` and `Unnamed: 0`** (`errors="ignore"`).
Use for single-file masters (e.g. `liteplan_payment.csv`, `hp_master_df.csv`,
`Dr_active_user.csv`).

### `load_and_concat_csvs(drive_service, folder_id, name_pattern) -> DataFrame`
Lists files matching the regex, reads each (printing a `⚠` and skipping any that
error), and `pd.concat(..., ignore_index=True)`. Returns an **empty DataFrame** if
nothing matched. Keeps `_source_file`. Use for year-sharded files like
`pr_registration_officeusers_2024.csv` + `..._2025.csv`.

---

## Gotchas
- **`pageSize=100`, no pagination.** A folder with **more than 100 files** silently
  truncates. Today's folders are small; if a source folder grows, add paging on
  `nextPageToken` here.
- **`name_pattern` must be a compiled regex** (`re.compile(...)`), and matching uses
  `.match` (anchored at start) — the masters module anchors patterns with `^...$`.
- **`_source_file` asymmetry:** `read_csv_from_drive` and `load_and_concat_csvs`
  keep `_source_file`; `load_csv_by_name` drops it. If you switch a caller between
  the two, expect the column set to change.
- **`load_and_concat_csvs` swallows per-file read errors** (prints `⚠`, continues).
  A partial concat can look "successful" — check the printed file count.
- **`Unnamed: 0`** (a stray CSV index column) is dropped only by `load_csv_by_name`.
- **Shared Drive flags are mandatory** — without `supportsAllDrives=True` /
  `includeItemsFromAllDrives=True` the listing returns nothing for Shared Drives.

## Dependencies
- Depends on: a Drive service from [gcp-and-config](gcp-and-config.md); `pandas`.
- Depended on by: [masters](masters.md) (`load_and_concat_csvs`,
  `list_files_in_folder` + `read_csv_from_drive` for `hp_master_df.csv`) and
  [s-rank](s-rank.md) (`load_csv_by_name`).
