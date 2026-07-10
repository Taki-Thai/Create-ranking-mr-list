"""Phase 1, Steps 40-46: Case 1 / Case 2 opportunity detection, Pattern + suggested hospital name."""

import pandas as pd

from .. import config
from ..sheet_utils import get_or_create_worksheet, overwrite_sheet_with_dataframe, write_column


def build_case1_active_dr_at_lp_hospital(s_rank_df, df_dractive_users_filtered):
    """Step 40: active Drs at the hospital the S-rank MR just got a Lite Plan purchase at."""
    s_rank_officeids = set(s_rank_df["officeid"].astype(str).unique())

    df_active_dr_at_mr_hp = df_dractive_users_filtered[
        df_dractive_users_filtered["officeId"].astype(str).isin(s_rank_officeids)
    ].copy()

    print(f"✓ df_active_dr_at_mr_hp: {df_active_dr_at_mr_hp.shape[0]:,} rows, "
          f"{df_active_dr_at_mr_hp['officeId'].nunique():,} unique hospitals")
    return df_active_dr_at_mr_hp


def push_case1_to_sheet(spreadsheet_out, df_active_dr_at_mr_hp):
    """Step 41."""
    ws_case1 = get_or_create_worksheet(spreadsheet_out, config.SHEET_CASE1)
    overwrite_sheet_with_dataframe(ws_case1, df_active_dr_at_mr_hp)
    print(f"✓ Pushed {df_active_dr_at_mr_hp.shape[0]:,} rows to sheet '{config.SHEET_CASE1}'")


def build_case2_hospitals_without_lp(s_rank_df, handling_hp_final, df_dractive_users):
    """Step 42-43: hospitals an S-rank MR covers but that are NOT the Lite-Plan hospital
    in s_rank_df, joined against active Drs at each such hospital."""
    s_rank_userids = set(s_rank_df["officeuserid"].astype(str).unique())
    s_rank_pairs = set(zip(s_rank_df["officeuserid"].astype(str), s_rank_df["officeid"].astype(str)))

    df_case2 = handling_hp_final[
        handling_hp_final["officeUserId"].astype(str).isin(s_rank_userids)
        & ~handling_hp_final.apply(
            lambda r: (str(r["officeUserId"]), str(r["officeId"])) in s_rank_pairs, axis=1
        )
    ].copy()
    print(f"✓ df_case2: {df_case2.shape[0]:,} rows, "
          f"{df_case2['officeUserId'].nunique():,} unique MRs, {df_case2['officeId'].nunique():,} unique hospitals")

    df_case2 = df_case2.rename(columns={"officeUserId": "MrOfficeUserId"})

    dr_for_case2 = df_dractive_users.rename(columns={
        "企業ID": "officeId",
        "オフィスユーザーID": "dr_officeUserId",
    })[["officeId", "dr_officeUserId"]].copy()

    dr_for_case2["officeId"] = dr_for_case2["officeId"].astype(str).str.strip()
    df_case2["officeId"] = df_case2["officeId"].astype(str).str.strip()
    df_case2["MrOfficeUserId"] = df_case2["MrOfficeUserId"].astype(str).str.strip()

    df_case2 = df_case2.merge(dr_for_case2, on="officeId", how="inner")

    hp_name_map = (
        df_dractive_users[["企業ID", "事業所名"]]
        .rename(columns={"企業ID": "officeId", "事業所名": "officeName"})
        .drop_duplicates(subset=["officeId"])
    )
    hp_name_map["officeId"] = hp_name_map["officeId"].astype(str).str.strip()

    df_case2 = df_case2.merge(hp_name_map, on="officeId", how="left")
    print(f"✓ df_case2 after Dr join: {df_case2.shape[0]:,} rows, "
          f"{df_case2['dr_officeUserId'].notna().sum():,} matched Drs")

    return df_case2


def push_case2_to_sheet(spreadsheet_out, df_case2):
    """Step 44."""
    ws_case2 = get_or_create_worksheet(spreadsheet_out, config.SHEET_CASE2)
    overwrite_sheet_with_dataframe(ws_case2, df_case2)
    print(f"✓ Pushed {df_case2.shape[0]:,} rows to sheet '{config.SHEET_CASE2}'")


def assign_pattern(s_rank_df, df_active_dr_at_mr_hp, df_case2):
    """Step 45: Pattern Sα-1 = Case1 only, Pattern Sα-2 = Case2 only, Pattern Sα-3 = both, Pattern 0 = neither."""
    case1_officeids = set(df_active_dr_at_mr_hp["officeId"].astype(str).unique())
    case2_mrids = set(df_case2["MrOfficeUserId"].astype(str).unique())

    def _pattern(row):
        in_case1 = str(row["officeid"]) in case1_officeids
        in_case2 = str(row["officeuserid"]) in case2_mrids
        if in_case1 and in_case2:
            return "Pattern Sα-3"
        elif in_case1:
            return "Pattern Sα-1"
        elif in_case2:
            return "Pattern Sα-2"
        return "Pattern 0"

    s_rank_df = s_rank_df.copy()
    s_rank_df["Pattern"] = s_rank_df.apply(_pattern, axis=1)
    print("✓ Pattern distribution:")
    print(s_rank_df["Pattern"].value_counts(dropna=False).to_string())

    return s_rank_df


def assign_suggested_hospital_name(s_rank_df, df_case2, max_hospitals=3):
    """Step 45b: for Pattern Sα-2/Sα-3 rows, list up to `max_hospitals` Case2 hospitals for
    that MR - both their names (suggest_hospital_name) and matching officeIds
    (suggest_hospital_officeid), same order, ranked by Dr count desc."""
    # Dr-row count per (MR, hospital) -> rank hospitals within each MR. Grouping by
    # officeId+officeName together keeps the name/id lists aligned when joined below.
    ranked = (
        df_case2[["MrOfficeUserId", "officeId", "officeName"]]
        .dropna(subset=["officeName"])
        .groupby(["MrOfficeUserId", "officeId", "officeName"])
        .size()
        .reset_index(name="dr_count")
        .sort_values(["MrOfficeUserId", "dr_count"], ascending=[True, False])
    )

    def _topn_join(group, col):
        return ", ".join(group[col].astype(str).head(max_hospitals))

    suggest_map = (
        ranked.groupby("MrOfficeUserId")
        .apply(lambda g: pd.Series({
            "suggest_hospital_name": _topn_join(g, "officeName"),
            "suggest_hospital_officeid": _topn_join(g, "officeId"),
        }))
        .reset_index()
        .rename(columns={"MrOfficeUserId": "officeuserid"})
    )

    suggest_cols = ["suggest_hospital_name", "suggest_hospital_officeid"]
    s_rank_df = s_rank_df.copy()
    s_rank_df = s_rank_df.drop(columns=[c for c in suggest_cols if c in s_rank_df.columns])

    s_rank_df = s_rank_df.merge(suggest_map, on="officeuserid", how="left")
    # When df_case2 is empty, groupby().apply() never runs, so suggest_map lacks
    # these columns and the merge doesn't add them. Guarantee they exist as string
    # columns; otherwise the masked assignment below creates them as numpy void
    # dtype on a 0-row frame, which later breaks .fillna() in the write-back.
    for c in suggest_cols:
        if c not in s_rank_df.columns:
            s_rank_df[c] = ""
        s_rank_df[c] = s_rank_df[c].fillna("").astype(str)
    other = ~s_rank_df["Pattern"].isin(["Pattern Sα-2", "Pattern Sα-3"])
    s_rank_df.loc[other, suggest_cols] = ""

    return s_rank_df


def write_back_pattern_and_suggestion(spreadsheet_out, s_rank_df):
    """Step 46: write both Pattern and suggest_hospital_name columns back to the sheet."""
    ws_out = spreadsheet_out.worksheet(config.SHEET_S_RANK)
    for column_name in ["Pattern", "suggest_hospital_name", "suggest_hospital_officeid"]:
        # astype("object") first so fillna takes the object path (not np.isnan):
        # a 0-row frame can leave a column as numpy void/numeric dtype, which
        # otherwise breaks fillna with "ufunc 'isnan' not supported".
        values = s_rank_df[column_name].astype("object").fillna("").tolist()
        col_idx = write_column(ws_out, column_name, values)
        print(f"✓ Wrote '{column_name}' -> column {col_idx} of sheet '{config.SHEET_S_RANK}' ({len(values):,} rows)")
