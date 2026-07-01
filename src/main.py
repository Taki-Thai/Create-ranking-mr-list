"""Entry point for Phase 1 (実行計画_フェーズ1‐データ作成) - S-Rank List data creation.

Mirrors the execution order of notebook cells 7-23: build the MR/hospital/Lite-Plan
BigQuery masters, load Dr/MR activity, compute the S-rank list, then classify each
S-rank MR into an opportunity Pattern and push everything to Google Sheets.

Run with: python -m src.main
"""

from . import config
from .gcp_clients import get_bigquery_client, get_drive_service, get_gspread_client
from .pipeline import (
    active_dr_user,
    case_analysis,
    dr_active,
    hospital_master,
    lp_label,
    mr_master,
    s_rank,
)


def main():
    drive_service = get_drive_service()
    gspread_client = get_gspread_client()
    bq_client = get_bigquery_client()

    # Steps 1-12: MR master
    df_prjoy_userinfo, handling_hp = mr_master.build_mr_master(drive_service)
    mr_master.push_mr_master_to_bigquery(bq_client, df_prjoy_userinfo)
    mr_master.prepare_mr_master_info_sheet(gspread_client, df_prjoy_userinfo)

    # Steps 13-18: hospital master
    handling_hp_final = hospital_master.build_hospital_master(drive_service, handling_hp)
    hospital_master.push_hospital_master_to_bigquery(bq_client, handling_hp_final)

    # Steps 19-23: lp label master
    lp_info = lp_label.build_lp_info(drive_service)
    lp_label.push_lp_label_master_to_bigquery(bq_client, lp_info)

    # Steps 24-26: Dr activity + write back meeting request date
    spreadsheet_main = gspread_client.open_by_key(config.SPREADSHEET_ID_MAIN)
    df_dractive_users, df_menkai, df_dr_chat = dr_active.load_dr_activity_data(drive_service)
    df_dractive_users = dr_active.enrich_dr_active_users(df_dractive_users, df_menkai, df_dr_chat)
    dr_active.write_back_meeting_request_date(spreadsheet_main, df_dractive_users)

    # Steps 27-36: S-rank list
    lp_info_new = s_rank.filter_new_lite_plan_purchases(lp_info, df_prjoy_userinfo)
    lp_info_new, df_mr_menkai_raw, df_mr_chat_raw = s_rank.join_menkai_and_chat(drive_service, lp_info_new)
    s_rank.overwrite_menkai_and_chat_sheets(spreadsheet_main, df_mr_menkai_raw, df_mr_chat_raw)
    s_rank_df = s_rank.build_s_rank_df(lp_info_new)
    spreadsheet_out, s_rank_df = s_rank.push_s_rank_to_sheet(gspread_client, s_rank_df)

    # Steps 37-39: active Dr users
    df_dractive_users_filtered = active_dr_user.filter_active_dr_users(df_dractive_users)
    active_dr_user.push_active_dr_users_to_sheet(spreadsheet_out, df_dractive_users_filtered)

    # Steps 40-44: Case 1 / Case 2 opportunity detection
    df_active_dr_at_mr_hp = case_analysis.build_case1_active_dr_at_lp_hospital(
        s_rank_df, df_dractive_users_filtered
    )
    case_analysis.push_case1_to_sheet(spreadsheet_out, df_active_dr_at_mr_hp)

    df_case2 = case_analysis.build_case2_hospitals_without_lp(s_rank_df, handling_hp_final, df_dractive_users)
    case_analysis.push_case2_to_sheet(spreadsheet_out, df_case2)

    # Steps 45-46: Pattern + suggested hospital name, write back
    s_rank_df = case_analysis.assign_pattern(s_rank_df, df_active_dr_at_mr_hp, df_case2)
    s_rank_df = case_analysis.assign_suggested_hospital_name(s_rank_df, df_case2)
    case_analysis.write_back_pattern_and_suggestion(spreadsheet_out, s_rank_df)

    print("✓ Phase 1 data creation pipeline completed successfully.")


if __name__ == "__main__":
    main()
