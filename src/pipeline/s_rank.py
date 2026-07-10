"""Phase 1, Steps 27-36: filter new Lite Plan buyers, join menkai/chat status, build & push s_rank_df."""

import gspread
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
    """Step 30-33: join latest MR menkai request date and aggregated MR chat status.

    The raw menkai/chat CSVs are only used in-memory here; they are no longer
    mirrored to tracking sheets (data outgrew the Sheets cell limit).
    """
    df_mr_menkai_raw = load_csv_by_name(drive_service, config.FOLDER_ID_DR_ACTIVITY, "dr_menkai_status.csv")

    df_mr_menkai = df_mr_menkai_raw.copy()
    df_mr_menkai["Mr Office User ID"] = df_mr_menkai["Mr Office User ID"].astype(str).str.strip()
    df_mr_menkai["面会ステータス"] = df_mr_menkai["面会ステータス"].astype(str).str.strip()

    # Chỉ giữ menkai do MR gửi (loại record DR/MD gửi cho MR). Phải chạy TRƯỚC mọi
    # count/aggregate ở phía MR — nếu không, menkai do DR/MD tạo bị đếm nhầm vào hoạt
    # động của MR và có thể che khuất menkai MR đang stuck (bug ngầm trước đây).
    df_mr_menkai["リクエスト元"] = df_mr_menkai["リクエスト元"].astype(str).str.strip()
    df_mr_menkai = df_mr_menkai[df_mr_menkai["リクエスト元"] == "MR"]
    print(f"✓ df_mr_menkai filtered to リクエスト元=='MR': {df_mr_menkai.shape[0]:,} rows")

    # Total FIXED / NEW menkai request counts per MR (from all rows, before the NEW-only
    # filter below). These two columns ride along to the Sランクリスト output sheet.
    # FIXED count also includes CANCELED (Measuring §8: CANCELED = Dr đã có động thái,
    # tương đương FIXED về mặt "menkai đã được Dr phản hồi").
    fixed_count = (
        df_mr_menkai[df_mr_menkai["面会ステータス"].isin(["FIXED", "CANCELED"])]
        .groupby("Mr Office User ID").size().rename("menkai_fixed_count")
    )
    new_count = (
        df_mr_menkai[df_mr_menkai["面会ステータス"] == "NEW"]
        .groupby("Mr Office User ID").size().rename("menkai_new_count")
    )
    menkai_counts = (
        pd.concat([fixed_count, new_count], axis=1)
        .fillna(0).astype(int)
        .reset_index()
        .rename(columns={"Mr Office User ID": "officeuserid"})
    )

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

    for col in ["menkai_fixed_count", "menkai_new_count"]:
        if col in lp_info_new.columns:
            lp_info_new = lp_info_new.drop(columns=[col])
    lp_info_new = lp_info_new.merge(menkai_counts, on="officeuserid", how="left")
    lp_info_new["menkai_fixed_count"] = lp_info_new["menkai_fixed_count"].fillna(0).astype(int)
    lp_info_new["menkai_new_count"] = lp_info_new["menkai_new_count"].fillna(0).astype(int)

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

    return lp_info_new


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

    mask = cond1 | cond2
    s_rank_df = lp_info_new[mask].copy()

    # S判定条件: which condition(s) qualified this row for rank S -
    # cond1 (stuck unread chat) -> "メッセージ", cond2 (stuck menkai request) -> "面会".
    def _judge(has_chat, has_menkai):
        labels = []
        if has_chat:
            labels.append("メッセージ")
        if has_menkai:
            labels.append("面会")
        return "・".join(labels)

    s_rank_df["S判定条件"] = [
        _judge(bool(a), bool(b)) for a, b in zip(cond1[mask], cond2[mask])
    ]
    print(f"✓ s_rank_df: {s_rank_df.shape[0]:,} rows (cond1={cond1.sum():,}, cond2={cond2.sum():,})")

    return s_rank_df


SENT_WINDOW_DAYS = 30


def office_ids_sent_recently(spreadsheet_out):
    """Office user IDs already logged (sent) within the last SENT_WINDOW_DAYS days, from the 'Log' sheet.

    The Log sheet mirrors the output rows plus a 送信日時 timestamp written when each
    row is appended. Anyone whose 送信日時 is within the last 30 days (up to now) has
    already been contacted recently and must not be sent again, so we exclude them
    from the push. The Log labels its id column 'officeUserId' (camelCase) while
    s_rank_df uses 'officeuserid'; we match it case-insensitively. Fails safe
    (returns an empty set) if the Log sheet or its expected columns are absent.
    """
    try:
        ws_log = spreadsheet_out.worksheet(config.SHEET_LOG)
    except gspread.exceptions.WorksheetNotFound:
        print(f"⚠ Log sheet '{config.SHEET_LOG}' not found - skipping already-sent filter")
        return set()

    records = ws_log.get_all_records()
    if not records:
        return set()

    log_df = pd.DataFrame(records)
    id_col = next((c for c in log_df.columns if str(c).strip().lower() == "officeuserid"), None)
    if "送信日時" not in log_df.columns or id_col is None:
        print("⚠ Log sheet missing 'officeUserId' or '送信日時' - skipping already-sent filter")
        return set()

    # format="mixed" parses each 送信日時 value independently, so a stray date-only or
    # differently-formatted cell doesn't silently become NaT and slip through the filter.
    sent = pd.to_datetime(log_df["送信日時"], errors="coerce", format="mixed")
    today = pd.Timestamp.now().normalize()
    days_since = (today - sent.dt.normalize()).dt.days
    recent = days_since.between(0, SENT_WINDOW_DAYS)  # sent within the last 30 days (future dates excluded)
    ids = log_df.loc[recent, id_col].astype(str).str.strip()
    ids = set(ids[ids != ""])
    print(f"✓ {len(ids):,} officeuserid(s) sent within the last {SENT_WINDOW_DAYS} days (from '{config.SHEET_LOG}')")
    return ids


def push_s_rank_to_sheet(gspread_client, s_rank_df):
    """Step 36: push s_rank_df to the 'Sランクリスト' output sheet.

    Before writing, drop any officeuserid that was already sent within the last 30
    days (present in the 'Log' sheet with a 送信日時 in that window) so nobody is
    contacted twice inside a 30-day window.
    """
    spreadsheet_out = gspread_client.open_by_key(config.SPREADSHEET_ID_OUT)
    ws_out = get_or_create_worksheet(spreadsheet_out, config.SHEET_S_RANK)

    already_sent = office_ids_sent_recently(spreadsheet_out)
    if already_sent:
        before = len(s_rank_df)
        s_rank_df = s_rank_df[
            ~s_rank_df["officeuserid"].astype(str).str.strip().isin(already_sent)
        ].copy()
        print(f"✓ Excluded {before - len(s_rank_df):,} row(s) sent within the last {SENT_WINDOW_DAYS} days; {len(s_rank_df):,} remain")

    s_rank_df = s_rank_df.drop(
        columns=["is_first_purchase", "number_of_contract", "assigned_hospital_count"],
        errors="ignore",
    )
    s_rank_df = s_rank_df.rename(
        columns={
            "リクエスト日時 Date": "Request meeting time",
            "未読のメッセージ数": "Unread message",
            "既読者ID": "reader_id",
        },
        errors="ignore",
    )

    # Keep S判定条件 as the last data column so it sits directly before the
    # Pattern column that write_back_pattern_and_suggestion appends afterwards.
    if "S判定条件" in s_rank_df.columns:
        ordered = [c for c in s_rank_df.columns if c != "S判定条件"] + ["S判定条件"]
        s_rank_df = s_rank_df[ordered]

    overwrite_sheet_with_dataframe(ws_out, s_rank_df)
    print(f"✓ Pushed {s_rank_df.shape[0]:,} rows to sheet '{config.SHEET_S_RANK}'")

    return spreadsheet_out, s_rank_df
