"""Builds shared GCP clients from a single service-account credential.

Drive, Sheets (via gspread) and BigQuery are all authenticated with the same
service account (GCP_SERVICE_ACCOUNT_KEY) since this pipeline runs headless
in GitHub Actions - there is no interactive Colab auth available there.

For this to work, the service account's client_email must be shared as a
collaborator on the source Drive folders / Spreadsheets referenced in
config.py, and granted BigQuery Data Editor + Job User on the target project.
"""

import json
from functools import lru_cache

import gspread
from google.cloud import bigquery
from google.oauth2 import service_account
from googleapiclient.discovery import build

from . import config

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/bigquery",
]


@lru_cache(maxsize=1)
def get_credentials() -> service_account.Credentials:
    info = json.loads(config.GCP_SERVICE_ACCOUNT_KEY)
    return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)


@lru_cache(maxsize=1)
def get_drive_service():
    return build("drive", "v3", credentials=get_credentials())


@lru_cache(maxsize=1)
def get_gspread_client() -> gspread.Client:
    return gspread.authorize(get_credentials())


@lru_cache(maxsize=1)
def get_bigquery_client() -> bigquery.Client:
    return bigquery.Client(project=config.PROJECT_ID, credentials=get_credentials())
