"""Phase 1, Steps 1-12: build & push `mr_master` (Pr.JOY MR users + assigned hospital count)."""

import re

from google.cloud import bigquery

from .. import config
from ..drive_utils import load_and_concat_csvs
from ..sheet_utils import get_or_create_worksheet

FILE_PATTERN_MR_INFO = re.compile(r"^pr_registration_officeusers_\d{4}\.csv$")
FILE_PATTERN_HANDLING_HOSPITAL = re.compile(r"^handlingHospital_\d{4}\.csv$")

MR_INFO_COLUMNS = [
    "officeUserId", "created", "userName",
    "age", "sex", "jobName",
    "officeId", "officeName", "officeType",
]


def build_mr_master(drive_service):
    df_prjoy_userinfo = load_and_concat_csvs(drive_service, config.FOLDER_ID_MR_INFO, FILE_PATTERN_MR_INFO)
    print(f"✓ df_prjoy_userinfo: {df_prjoy_userinfo.shape[0]:,} rows x {df_prjoy_userinfo.shape[1]} cols")

    df_prjoy_userinfo = df_prjoy_userinfo[MR_INFO_COLUMNS]

    handling_hp = load_and_concat_csvs(
        drive_service, config.FOLDER_ID_HANDLING_HOSPITAL, FILE_PATTERN_HANDLING_HOSPITAL
    )
    print(f"✓ handling_hp: {handling_hp.shape[0]:,} rows x {handling_hp.shape[1]} cols")

    mr_hospital_count = (
        handling_hp
        .groupby("officeuserid")["officeid"]
        .nunique()
        .reset_index()
        .rename(columns={"officeid": "assigned_hospital_count"})
    )

    df_prjoy_userinfo = df_prjoy_userinfo.merge(
        mr_hospital_count,
        left_on="officeUserId",
        right_on="officeuserid",
        how="left",
    ).drop(columns=["officeuserid"])

    df_prjoy_userinfo = df_prjoy_userinfo[df_prjoy_userinfo["assigned_hospital_count"].notna()]
    print(f"✓ df_prjoy_userinfo after filtering: {df_prjoy_userinfo.shape[0]:,} rows x {df_prjoy_userinfo.shape[1]} cols")

    return df_prjoy_userinfo, handling_hp


def push_mr_master_to_bigquery(bq_client, df_prjoy_userinfo):
    table_id = f"{config.PROJECT_ID}.{config.DATASET_ID}.{config.BQ_TABLE_MR_MASTER}"
    job = bq_client.load_table_from_dataframe(
        df_prjoy_userinfo,
        table_id,
        job_config=bigquery.LoadJobConfig(write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE),
    )
    job.result()
    print(f"✓ Pushed {df_prjoy_userinfo.shape[0]:,} rows to {table_id}")


def prepare_mr_master_info_sheet(gspread_client, df_prjoy_userinfo):
    """Step 12: clears the Mr Master Info sheet. The actual worksheet.update() write is
    intentionally left disabled here, matching the original notebook's behavior."""
    spreadsheet = gspread_client.open_by_key(config.SPREADSHEET_ID_MAIN)
    worksheet = get_or_create_worksheet(spreadsheet, config.SHEET_MR_MASTER_INFO)
    worksheet.clear()

    # data = [df_prjoy_userinfo.columns.tolist()] + df_prjoy_userinfo.fillna("").astype(str).values.tolist()
    # worksheet.update(data, value_input_option="RAW")  # intentionally disabled, see README

    print(f"✓ Cleared sheet '{config.SHEET_MR_MASTER_INFO}' (write disabled, matches source notebook)")
