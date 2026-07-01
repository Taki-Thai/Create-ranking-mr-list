"""Phase 1, Steps 37-39: build & push the active Dr user list."""

import pandas as pd

from .. import config
from ..sheet_utils import get_or_create_worksheet, overwrite_sheet_with_dataframe


def filter_active_dr_users(df_dractive_users):
    df = df_dractive_users.rename(columns={
        "オフィスユーザーID": "officeUserId",
        "ユーザー名": "name",
        "企業ID": "officeId",
        "事業所名": "hospitalName",
        "最終利用時刻": "last_access_date",
        "Updated Date": "last_message_date",
        "面会リクエスト日": "last_meeting_date",
    })

    today = pd.Timestamp.now().normalize()
    seven_days_ago = today - pd.DateOffset(days=7)

    last_access = pd.to_datetime(df["last_access_date"], errors="coerce").dt.normalize()
    last_msg = pd.to_datetime(df["last_message_date"], errors="coerce")
    last_meet = pd.to_datetime(df["last_meeting_date"], errors="coerce")

    df = df[
        (last_access >= seven_days_ago)
        & (last_msg.notna() | last_meet.notna())
        & (~df["hospitalName"].astype(str).str.contains(r"Dr\.JOY|テスト", na=False))
        & (~df["name"].astype(str).str.contains("test", case=False, na=False))
    ].copy()

    print(f"✓ df_dractive_users_filtered: {df.shape[0]:,} rows x {df.shape[1]} cols")
    return df


def push_active_dr_users_to_sheet(spreadsheet_out, df_dractive_users_filtered):
    ws_active = get_or_create_worksheet(spreadsheet_out, config.SHEET_ACTIVE_DR_USER)
    overwrite_sheet_with_dataframe(ws_active, df_dractive_users_filtered)
    print(f"✓ Pushed {df_dractive_users_filtered.shape[0]:,} rows to sheet '{config.SHEET_ACTIVE_DR_USER}'")
