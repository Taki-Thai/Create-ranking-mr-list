"""Helpers for reading CSV files out of Google Drive folders via the Drive API."""

import io

import pandas as pd
from googleapiclient.http import MediaIoBaseDownload


def list_files_in_folder(drive_service, folder_id, name_pattern=None, exact_name=None):
    query = f"'{folder_id}' in parents and trashed=false"
    if exact_name:
        query += f" and name='{exact_name}'"

    results = drive_service.files().list(
        q=query,
        fields="files(id, name)",
        pageSize=100,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()

    files = results.get("files", [])
    if name_pattern:
        files = [f for f in files if name_pattern.match(f["name"])]
    return sorted(files, key=lambda f: f["name"])


def read_csv_from_drive(drive_service, file_id, file_name) -> pd.DataFrame:
    request = drive_service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buffer.seek(0)

    df = pd.read_csv(buffer)
    df["_source_file"] = file_name
    return df


def load_csv_by_name(drive_service, folder_id, filename) -> pd.DataFrame:
    """Find a single file by exact name in a folder and read it as a DataFrame."""
    files = list_files_in_folder(drive_service, folder_id, exact_name=filename)
    if not files:
        raise FileNotFoundError(f"'{filename}' not found in Drive folder '{folder_id}'")
    df = read_csv_from_drive(drive_service, files[0]["id"], files[0]["name"])
    return df.drop(columns=["_source_file", "Unnamed: 0"], errors="ignore")


def load_and_concat_csvs(drive_service, folder_id, name_pattern) -> pd.DataFrame:
    """Find all files matching a regex pattern in a folder and concat them into one DataFrame."""
    files = list_files_in_folder(drive_service, folder_id, name_pattern=name_pattern)
    print(f"✓ Found {len(files)} matching file(s) in folder {folder_id}")

    dfs = []
    for f in files:
        try:
            dfs.append(read_csv_from_drive(drive_service, f["id"], f["name"]))
        except Exception as e:
            print(f"⚠ Failed to read {f['name']}: {e}")

    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
