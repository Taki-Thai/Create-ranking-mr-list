"""Phase 1, Steps 27-36: filter new Lite Plan buyers, join menkai/chat status, build & push s_rank_df."""

import pandas as pd

from .. import config
from ..drive_utils import load_csv_by_name
from ..sheet_utils import get_or_create_worksheet, overwrite_sheet_with_dataframe


def filter_new_lite_plan_purchases(lp_info, df_prjoy_userinfo):
    """Step 27-29: brand-new, single-contract Lite Plan buyers with >=2 assigned
    hospitals, purchased within the last 15 days."""
    lp_info_new = lp_info[
        (lp_info["is_first_purchase"] == True) & (lp_info["number_of_contract"] == 1)
    ].copy()
    print(f"✓ lp_info_new after is_first_purchase/number_of_contract filter: {lp_info_new.shape[0]:,} rows")

    lp_info_new = lp_info_new.merge(
        df_prjoy_userinfo[["officeUserId", "assigned_hospital_count"]],
        left_on="officeuserid",
        right_on="officeUserId",
        how="left",
    ).drop(columns=["officeUserId"])

    lp_info_new = lp_info_new[lp_info_new["assigned_hospital_count"] >= 2].copy()

    lp_info_new = lp_info_new.assign(
        purchase_date=pd.to_datetime(lp_info_new["purchase_date"], errors="coerce").dt.normalize()
    )
    today = pd.Timestamp.now().normalize()
    lp_info_new = lp_info_new[(today - lp_info_new["purchase_date"]).dt.days <= 15]
    print(f"✓ lp_info_new after assigned_hospital_count/purchase_date filter: {lp_info_new.shape[0]:,} rows")

    return lp_info_new


def join_menkai_and_chat(drive_service, lp_info_new):
    """Step 30-33: join latest MR menkai request date and aggregated MR chat status."""
    df_mr_menkai_raw = load_csv_by_name(drive_service, config.FOLDER_ID_DR_ACTIVITY, "dr_menkai_status.csv")

    df_mr_menkai = df_mr_menkai_raw.copy()
    df_mr_menkai["Mr Office User ID"] = df_mr_menkai["Mr Office User ID"].astype(str).str.strip()
    df_mr_menkai = df_mr_menkai[df_mr_menkai["面会ステータス"] == "NEW"]

    if "リクエスト日時 Date" in lp_info_new.columns:
        lp_info_new = lp_info_new.drop(columns=["リクエスト日時 Date"])

    menkai_mr_map = (
        df_mr_menkai[["Mr Office User ID", "リクエスト日時 Date"]]
        .rename(columns={"Mr Office User ID": "officeuserid"})
        .groupby("officeuserid", as_index=False)["リクエスト日時 Date"]
        .max()
    )
    lp_info_new = lp_info_new.merge(menkai_mr_map, on="officeuserid", how="left")

    df_mr_chat_raw = load_csv_by_name(drive_service, config.FOLDER_ID_DR_ACTIVITY, "mr_chat_status.csv")
    df_mr_chat = df_mr_chat_raw.copy()
    df_mr_chat["送信者ID"] = df_mr_chat["送信者ID"].astype(str).str.strip()

    chat_cols = ["送信者ID", "未読のメッセージ数", "既読者ID", "Updated Date"]
    for col in ["未読のメッセージ数", "既読者ID", "Updated Date"]:
        if col in lp_info_new.columns:
            lp_info_new = lp_info_new.drop(columns=[col])

    chat_map = (
        df_mr_chat[chat_cols]
        .rename(columns={"送信者ID": "officeuserid"})
        .groupby("officeuserid", as_index=False)
        .agg({"未読のメッセージ数": "sum", "既読者ID": "last", "Updated Date": "max"})
    )
    lp_info_new = lp_info_new.merge(chat_map, on="officeuserid", how="left")
    print(f"✓ lp_info_new after menkai/chat join: {lp_info_new.shape[0]:,} rows x {lp_info_new.shape[1]} cols")

    return lp_info_new, df_mr_menkai_raw, df_mr_chat_raw


def overwrite_menkai_and_chat_sheets(spreadsheet_main, df_mr_menkai_raw, df_mr_chat_raw):
    """Step 34: overwrite the raw menkai/chat sheets with the freshly-read CSVs."""
    ws_menkai_mr = spreadsheet_main.worksheet(config.SHEET_MENKAI_MR)
    overwrite_sheet_with_dataframe(ws_menkai_mr, df_mr_menkai_raw, cast_to_str=False)
    print(f"✓ Overwrote sheet '{config.SHEET_MENKAI_MR}' ({df_mr_menkai_raw.shape[0]:,} rows)")

    ws_chat_mr = spreadsheet_main.worksheet(config.SHEET_CHAT_MR)
    overwrite_sheet_with_dataframe(ws_chat_mr, df_mr_chat_raw, cast_to_str=False)
    print(f"✓ Overwrote sheet '{config.SHEET_CHAT_MR}' ({df_mr_chat_raw.shape[0]:,} rows)")


def build_s_rank_df(lp_info_new):
    """Step 35: rows with a stuck (unread) chat >=5 days old OR a stuck menkai request >=5 days old."""
    today = pd.Timestamp.now().normalize()
    updated_date = pd.to_datetime(lp_info_new["Updated Date"], errors="coerce").dt.normalize()
    request_date = pd.to_datetime(lp_info_new["リクエスト日時 Date"], errors="coerce").dt.normalize()

    cond1 = (
        ((today - updated_date).dt.days >= 5)
        & (lp_info_new["既読者ID"].isna() | (lp_info_new["既読者ID"].astype(str).str.strip() == ""))
    )
    cond2 = (today - request_date).dt.days >= 5

    s_rank_df = lp_info_new[cond1 | cond2].copy()
    print(f"✓ s_rank_df: {s_rank_df.shape[0]:,} rows (cond1={cond1.sum():,}, cond2={cond2.sum():,})")

    return s_rank_df


def push_s_rank_to_sheet(gspread_client, s_rank_df):
    """Step 36: push s_rank_df to the 'Sランクリスト' output sheet."""
    spreadsheet_out = gspread_client.open_by_key(config.SPREADSHEET_ID_OUT)
    ws_out = get_or_create_worksheet(spreadsheet_out, config.SHEET_S_RANK)

    s_rank_df = s_rank_df.rename(
        columns={
            "リクエスト日時 Date": "Request meeting time",
            "未読のメッセージ数": "Unread message",
            "既読者ID": "reader_id",
        },
        errors="ignore",
    )
    overwrite_sheet_with_dataframe(ws_out, s_rank_df)
    print(f"✓ Pushed {s_rank_df.shape[0]:,} rows to sheet '{config.SHEET_S_RANK}'")

    return spreadsheet_out, s_rank_df
