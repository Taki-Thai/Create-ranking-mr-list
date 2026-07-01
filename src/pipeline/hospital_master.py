"""Phase 1, Steps 13-18: build & push `hospital_master` (MR<->hospital assignments)."""

from google.cloud import bigquery

from .. import config
from ..drive_utils import list_files_in_folder, read_csv_from_drive


def build_hospital_master(drive_service, handling_hp):
    handling_hp_final = (
        handling_hp[["officeuserid", "officeid", "start"]]
        .rename(columns={
            "officeuserid": "officeUserId",
            "officeid": "officeId",
            "start": "assigned_start_date",
        })
    )
    print(f"✓ handling_hp_final: {handling_hp_final.shape[0]:,} rows x {handling_hp_final.shape[1]} cols")

    hp_master_files = list_files_in_folder(
        drive_service, config.FOLDER_ID_HP_MASTER, exact_name="hp_master_df.csv"
    )
    if not hp_master_files:
        raise FileNotFoundError("hp_master_df.csv not found in Drive folder")

    hp_master_df = read_csv_from_drive(drive_service, hp_master_files[0]["id"], hp_master_files[0]["name"])
    hp_master_df = (
        hp_master_df[["officeId", "都道府県", "全担当者数"]]
        .rename(columns={"都道府県": "prefecture", "全担当者数": "assigned_pic_count"})
    )

    handling_hp_final = handling_hp_final.merge(hp_master_df, on="officeId", how="left")
    print(f"✓ handling_hp_final after join: {handling_hp_final.shape[0]:,} rows x {handling_hp_final.shape[1]} cols")

    return handling_hp_final


def push_hospital_master_to_bigquery(bq_client, handling_hp_final):
    table_id = f"{config.PROJECT_ID}.{config.DATASET_ID}.{config.BQ_TABLE_HOSPITAL_MASTER}"
    job = bq_client.load_table_from_dataframe(
        handling_hp_final,
        table_id,
        job_config=bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            autodetect=True,
        ),
    )
    job.result()
    print(f"✓ Pushed {handling_hp_final.shape[0]:,} rows to {table_id}")
