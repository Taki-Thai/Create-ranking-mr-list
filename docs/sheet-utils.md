# docs/sheet-utils — Google Sheets write patterns

Covers `src/sheet_utils.py`. Two distinct write strategies plus a small
column-cleaning helper. **Which one you pick matters for formatting** (see the
convention in `CLAUDE.md`).

---

## The two write strategies

| Helper | Scope | Preserves format? | Used for |
|---|---|---|---|
| `overwrite_sheet_with_dataframe` | **whole sheet** (`clear()` + write) | No — wipes the tab | Derived *output* tables the pipeline fully owns |
| `write_column` | **one column** (ranged `update`) | Yes — leaves other cells intact | Write-backs into shared/formatted sheets |

Rule of thumb: if the pipeline is the sole author of a sheet's contents, overwrite
is fine. If you are adding/updating **one column** on a sheet someone else formats
(e.g. `5.Dr user active`, or the `Pattern`/`suggest_hospital_name` columns on
`Sランクリスト`), use `write_column`.

---

## Functions

### `_drop_spurious_columns(df)`
Drops columns whose names start with `Unnamed:` or match `Column\s+\d+` (e.g.
`Column 12`). These appear when a DataFrame round-trips through Sheets.

### `get_or_create_worksheet(spreadsheet, title)`
Returns the worksheet, creating a 1×1 one via `add_worksheet` if
`gspread.exceptions.WorksheetNotFound`.

### `overwrite_sheet_with_dataframe(worksheet, df, cast_to_str=True)`
1. `worksheet.clear()` — **clears the entire tab**.
2. `_drop_spurious_columns` → `fillna("")` → (if `cast_to_str`) `astype(str)`.
3. Drops leftover `Column 12` / `Column 13`.
4. `set_with_dataframe(worksheet, df)` writes header + rows from A1.

`cast_to_str=True` (default) matches the source notebook's `.fillna("").astype(str)`
for every derived table. The two historical raw-CSV mirror writes used
`cast_to_str=False`; those writes are no longer part of the pipeline.

### `write_column(worksheet, column_name, values) -> int`
Reads row 1 headers. If `column_name` exists, targets that column; otherwise
creates it at `len(headers)+1` via `update_cell(1, col_idx, name)`. Then writes the
values with `worksheet.update([[v] for v in values], f"R2C{idx}:R{len(values)+1}C{idx}")`
(**R1C1 range notation**). Returns the 1-based column index. If `values` is empty
it returns early (an inverted `R2C:R1C` range would be invalid).

---

## Gotchas
- **`overwrite_sheet_with_dataframe` destroys formatting** (full `clear()`). Never
  use it on a sheet whose layout/format you must keep — use `write_column`.
- **`write_column` is positional:** it writes `values` starting at row 2 assuming
  **row order already matches the sheet**. Callers must pass values in the sheet's
  existing row order (this is how `dr_active` and `case_analysis` write back). A
  reordered DataFrame silently misaligns rows.
- **Everything is stringified** in `overwrite_sheet_with_dataframe` — numbers/dates
  land as text. Downstream consumers reading the sheet should expect strings (and
  re-`normalize` IDs; see the ID convention).
- **`Column 12`/`Column 13` are dropped twice** (in `_drop_spurious_columns` and an
  explicit `.drop`), a belt-and-suspenders guard against a specific recurring
  artifact — harmless, leave it.
- **gspread `update` arg order** is `(values, range_name)` here (gspread ≥6). Pin/
  install matches CI; don't flip the arguments.

## Dependencies
- Depends on: `gspread`, `gspread_dataframe.set_with_dataframe`.
- Depended on by: [masters](masters.md) (`get_or_create_worksheet` for the
  `Mr Master Info` clear) and [s-rank](s-rank.md) (all output writes +
  `write_column` write-backs).
