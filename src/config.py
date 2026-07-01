"""Environment-driven configuration for the Phase 1 (S-Rank List) data pipeline.

Secrets (service account key, project, dataset) are read from environment
variables so nothing sensitive is hardcoded. Resource identifiers below
(Drive folder IDs, Spreadsheet keys, sheet/table names) are not secrets -
they are stable references to the org's existing Drive/Sheets/BigQuery
resources and are kept as constants.
"""

import os


def get_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required environment variable '{name}' is not set")
    return value


# ── Secrets (mapped from GitHub Actions secrets) ──
GCP_SERVICE_ACCOUNT_KEY = get_env("GCP_SERVICE_ACCOUNT_KEY")
PROJECT_ID = get_env("PROJECT_ID")
DATASET_ID = get_env("DATASET_ID")

# ── BigQuery table names ──
BQ_TABLE_MR_MASTER = "mr_master"
BQ_TABLE_HOSPITAL_MASTER = "hospital_master"
BQ_TABLE_LP_LABEL_MASTER = "lp_label_master"

# ── Drive folder IDs (source CSVs) ──
FOLDER_ID_MR_INFO = "14vPSh8Jqmf9N1iPmQKzar-W_crGr4-Px"
FOLDER_ID_HANDLING_HOSPITAL = "1Dfr-Pbax7CfBBBfBfVT-3HhhZvZwWoFI"
FOLDER_ID_HP_MASTER = "1WgUeoddIxwV_4qwscCcgor4CUPvpvvqS"
FOLDER_ID_LITEPLAN = "10GZeXE0AYTekK-A7Wv1kfMSLu4mwijFw"
FOLDER_ID_DR_ACTIVITY = "123W8yRftyjPNFK_7wcn87uCyEwRCAwmh"

# ── Spreadsheet IDs (sinks) ──
SPREADSHEET_ID_MAIN = "1FYceOW233uL6fThahPHmaecJAhNKdwedHmrVocYsS_I"
SPREADSHEET_ID_OUT = "1oEIr4zbl8YPrbiPqXXL1KQ-DAD1JV4lGeuZw64O8pfg"

# ── Sheet names ──
SHEET_MR_MASTER_INFO = "Mr Master Info"
SHEET_DR_USER_ACTIVE = "5.Dr user active"
SHEET_MENKAI_MR = "4.5 面会リクエスト(MR)"
SHEET_CHAT_MR = "4.メッセージ （MR)"
SHEET_S_RANK = "Sランクリスト"
SHEET_ACTIVE_DR_USER = "acvite dr user"
SHEET_CASE1 = "List_dr_LP_hospital"
SHEET_CASE2 = "List_dr_without_LP_hospital"
