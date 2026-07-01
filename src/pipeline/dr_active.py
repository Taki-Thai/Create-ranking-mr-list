"""Phase 1, Steps 24-26: load Dr active/menkai/chat status, write back meeting request date."""

from .. import config
from ..drive_utils import load_csv_by_name
from ..sheet_utils import write_column


def load_dr_activity_data(drive_service):
    df_dractive_users = load_csv_by_name(drive_service, config.FOLDER_ID_DR_ACTIVITY, "Dr_active_user.csv")
    df_dractive_users["オフィスユーザーID"] = df_dractive_users["オフィスユーザーID"].astype(str).str.strip()

    df_menkai = load_csv_by_name(drive_service, config.FOLDER_ID_DR_ACTIVITY, "dr_menkai_status.csv")
    df_menkai["Dr Office User ID"] = df_menkai["Dr Office User ID"].astype(str).str.strip()
    df_menkai = df_menkai[df_menkai["面会ステータス"].astype(str).str.strip() == "FIXED"]
    print(f"✓ df_menkai filtered to 面会ステータス=='FIXED': {df_menkai.shape[0]:,} rows")

    df_dr_chat = load_csv_by_name(drive_service, config.FOLDER_ID_DR_ACTIVITY, "dr_chat_status.csv")
    df_dr_chat["送信者ID"] = df_dr_chat["送信者ID"].astype(str).str.strip()

    print(f"✓ df_dractive_users: {df_dractive_users.shape[0]:,} rows x {df_dractive_users.shape[1]} cols")
    print(f"✓ df_menkai        : {df_menkai.shape[0]:,} rows x {df_menkai.shape[1]} cols")
    print(f"✓ df_dr_chat       : {df_dr_chat.shape[0]:,} rows x {df_dr_chat.shape[1]} cols")

    return df_dractive_users, df_menkai, df_dr_chat


def enrich_dr_active_users(df_dractive_users, df_menkai, df_dr_chat):
    """Merge latest chat 'Updated Date' and latest 面会リクエスト日 (meeting request date) per Dr."""
    if "Updated Date" in df_dractive_users.columns:
        df_dractive_users = df_dractive_users.drop(columns=["Updated Date"])

    chat_map_dr = (
        df_dr_chat[["送信者ID", "Updated Date"]]
        .groupby("送信者ID", as_index=False)["Updated Date"]
        .max()
        .rename(columns={"送信者ID": "オフィスユーザーID"})
    )
    df_dractive_users = df_dractive_users.merge(chat_map_dr, on="オフィスユーザーID", how="left")

    if "面会リクエスト日" in df_dractive_users.columns:
        df_dractive_users = df_dractive_users.drop(columns=["面会リクエスト日"])

    menkai_map = (
        df_menkai[["Dr Office User ID", "リクエスト日時 Date"]]
        .groupby("Dr Office User ID", as_index=False)["リクエスト日時 Date"]
        .max()
        .rename(columns={
            "Dr Office User ID": "オフィスユーザーID",
            "リクエスト日時 Date": "面会リクエスト日",
        })
    )
    df_dractive_users = df_dractive_users.merge(menkai_map, on="オフィスユーザーID", how="left")

    print(f"✓ df_dractive_users enriched: {df_dractive_users.shape[0]:,} rows x {df_dractive_users.shape[1]} cols")
    return df_dractive_users


def write_back_meeting_request_date(spreadsheet_main, df_dractive_users):
    ws_dractive = spreadsheet_main.worksheet(config.SHEET_DR_USER_ACTIVE)
    values = df_dractive_users["面会リクエスト日"].fillna("").tolist()
    col_idx = write_column(ws_dractive, "面会リクエスト日", values)
    print(f"✓ Wrote '面会リクエスト日' -> column {col_idx} of sheet '{config.SHEET_DR_USER_ACTIVE}' ({len(values):,} rows)")
