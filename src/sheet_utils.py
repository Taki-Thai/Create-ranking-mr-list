"""Shared Google Sheets write patterns used throughout the pipeline.

Pipeline A always does clear + full overwrite for full-table sheets (idempotent
per run) and uses R{row}C{col}-ranged updates for single-column write-backs,
which assumes row order matches the existing sheet.
"""

import gspread
from gspread_dataframe import set_with_dataframe


def get_or_create_worksheet(spreadsheet, title: str):
    try:
        return spreadsheet.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=title, rows=1, cols=1)


def overwrite_sheet_with_dataframe(worksheet, df, cast_to_str: bool = True):
    """Clear a sheet and write the full DataFrame back.

    cast_to_str=True (the default, used for every derived/output table) matches the
    source notebook's `.fillna("").astype(str)` pattern. The two raw-CSV mirror
    writes (menkai/chat status -> their tracking sheets) only do `.fillna("")` in
    the original, so pass cast_to_str=False there to match.
    """
    worksheet.clear()
    df = df.fillna("")
    if cast_to_str:
        df = df.astype(str)
    set_with_dataframe(worksheet, df)


def write_column(worksheet, column_name: str, values: list) -> int:
    """Write a single column back to a sheet, creating the header if needed."""
    headers = worksheet.row_values(1)
    if column_name in headers:
        col_idx = headers.index(column_name) + 1
    else:
        col_idx = len(headers) + 1
        worksheet.update_cell(1, col_idx, column_name)

    if not values:
        # Nothing to write - R2C{col}:R1C{col} would be an inverted (invalid) range.
        return col_idx

    worksheet.update(
        [[v] for v in values],
        f"R2C{col_idx}:R{len(values) + 1}C{col_idx}",
    )
    return col_idx
