"""Phase 1, Steps 19-23: build & push `lp_label_master` (Lite Plan purchases)."""

import pandas as pd
from google.cloud import bigquery

from .. import config
from ..drive_utils import list_files_in_folder, read_csv_from_drive


def build_lp_info(drive_service):
    files = list_files_in_folder(drive_service, config.FOLDER_ID_LITEPLAN, exact_name="liteplan_payment.csv")
    if not files:
        raise FileNotFoundError("liteplan_payment.csv not found in Drive folder")

    lp_info = read_csv_from_drive(drive_service, files[0]["id"], files[0]["name"])
    print(f"✓ lp_info raw: {lp_info.shape[0]:,} rows x {lp_info.shape[1]} cols")

    # drop rows where both cancellation-date columns are non-null (fully cancelled)
    lp_info = lp_info[lp_info["解除予約日"].isna() | lp_info["解除完了日"].isna()]

    lp_info = lp_info.assign(
        key=lp_info["ユーザーID"].astype(str) + "_" + lp_info["ライト購入施設ID"].astype(str)
    )
    lp_info = lp_info.assign(購入時刻=pd.to_datetime(lp_info["購入時刻"], errors="coerce"))

    today = pd.Timestamp.now().normalize()
    one_month_ago = today - pd.DateOffset(months=1)
    lp_info = lp_info.assign(
        is_first_purchase=lp_info["購入時刻"].between(one_month_ago, today)
    )
    lp_info = lp_info.assign(
        number_of_contract=lp_info["ユーザーID"].map(lp_info["ユーザーID"].value_counts())
    )

    lp_info = (
        lp_info[["ユーザーID", "氏名", "ライト購入施設ID", "購入時刻", "is_first_purchase", "number_of_contract"]]
        .rename(columns={
            "ユーザーID": "officeuserid",
            "氏名": "mr_name",
            "ライト購入施設ID": "officeid",
            "購入時刻": "purchase_date",
        })
    )
    print(f"✓ lp_info final: {lp_info.shape[0]:,} rows x {lp_info.shape[1]} cols")

    return lp_info


def push_lp_label_master_to_bigquery(bq_client, lp_info):
    table_id = f"{config.PROJECT_ID}.{config.DATASET_ID}.{config.BQ_TABLE_LP_LABEL_MASTER}"
    job = bq_client.load_table_from_dataframe(
        lp_info,
        table_id,
        job_config=bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            autodetect=True,
        ),
    )
    job.result()
    print(f"✓ Pushed {lp_info.shape[0]:,} rows to {table_id}")
