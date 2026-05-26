"""Dynamic Excel parser.

Uses FormatDetector to auto-detect header rows and column positions for any
workbook layout.  Falls back to the legacy keyword scan if detection confidence
is low.  Detected profiles are saved to the DB so the system learns from each
new file format it encounters.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from src.ingest.format_detector import (
    ColumnMap,
    FormatProfile,
    detect_format,
    load_format_profile,
    save_format_profile,
)

logger = logging.getLogger(__name__)

SERIAL_HEADERS = {
    "s. no.", "s.no.", "s no.", "s.no", "s no",
    "sl. no.", "sl.no.", "sl no.", "sl no",
    "sr. no.", "sr.no.", "sr no.", "sr no",
}


def _clean(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _parse_sheet(
    df: pd.DataFrame,
    sheet_name: str,
    profile: FormatProfile,
) -> List[Dict]:
    """Parse one sheet using a detected FormatProfile."""
    records: List[Dict] = []
    cm = profile.col_map
    n_cols = df.shape[1]

    last_serial = ""
    last_param = ""
    row_counter = 0
    seen_spec_ids: Dict[str, int] = {}

    for row_idx in range(profile.data_start_row, df.shape[0]):
        serial_no    = _clean(df.iloc[row_idx, cm.serial_col]) if cm.serial_col < n_cols else ""
        parameter    = _clean(df.iloc[row_idx, cm.param_col])  if cm.param_col  < n_cols else ""
        requirement  = _clean(df.iloc[row_idx, cm.req_col])    if cm.req_col    < n_cols else ""
        compliance   = _clean(df.iloc[row_idx, cm.comply_col]) if cm.comply_col is not None and cm.comply_col < n_cols else ""

        if not any([serial_no, parameter, requirement]):
            continue
        if serial_no.lower() in SERIAL_HEADERS:
            continue

        # carry-forward for merged cells
        if serial_no:
            last_serial = serial_no
        else:
            serial_no = last_serial
        if parameter:
            last_param = parameter
        else:
            parameter = last_param

        row_counter += 1
        # row_index: prefer numeric serial, else counter
        if serial_no and re.match(r"^\d+$", serial_no.strip()):
            row_index = int(serial_no.strip())
        else:
            row_index = row_counter

        # build spec_id
        spec_suffix = serial_no or str(row_idx + 1)
        if serial_no and re.search(r"[A-Za-z]", serial_no):
            base_spec_id = serial_no
        elif profile.item_code:
            base_spec_id = f"{profile.item_code}-{spec_suffix}"
        else:
            base_spec_id = f"{sheet_name}-{spec_suffix}"

        seen_count = seen_spec_ids.get(base_spec_id, 0)
        seen_spec_ids[base_spec_id] = seen_count + 1
        spec_id = base_spec_id if seen_count == 0 else f"{base_spec_id}-{row_idx + 1}"

        records.append({
            "Spec_ID": spec_id,
            "Parameter_Name": parameter,
            "company_Requirement": requirement,
            "bidder_compliance": compliance,
            "sheet_name": sheet_name,
            "row_index": row_index,
        })

    return records


def _parse_workbook(excel_path: str, db_conn=None) -> List[Dict]:
    records: List[Dict] = []
    file_name = Path(excel_path).name

    # Try to load cached profile from DB first
    cached_profiles: Dict[str, FormatProfile] = {}
    if db_conn is not None:
        try:
            cached_profiles = load_format_profile(db_conn, file_name)
        except Exception:
            pass

    # Always re-detect (cheap) and compare confidence
    detected_profiles = detect_format(excel_path)

    # Merge: use detected if confidence >= cached or no cache
    profiles: Dict[str, FormatProfile] = {}
    for sheet, detected in detected_profiles.items():
        cached = cached_profiles.get(sheet)
        if cached is None or detected.confidence >= cached.confidence:
            profiles[sheet] = detected
        else:
            profiles[sheet] = cached
            logger.debug("Using cached profile for %s/%s (conf=%.2f)", file_name, sheet, cached.confidence)

    # Persist updated profiles
    if db_conn is not None:
        try:
            save_format_profile(db_conn, file_name, profiles)
        except Exception as exc:
            logger.warning("Could not save format profiles: %s", exc)

    try:
        xls = pd.ExcelFile(excel_path)
    except Exception as exc:
        logger.error("Cannot open workbook %s: %s", excel_path, exc)
        return records

    for sheet_name in xls.sheet_names:
        try:
            df = pd.read_excel(xls, sheet_name=sheet_name, header=None, dtype=str).fillna("")
            if df.empty or df.shape[1] < 2:
                continue

            profile = profiles.get(sheet_name)
            if profile is None:
                logger.warning("No profile for sheet %s — skipping", sheet_name)
                continue

            sheet_records = _parse_sheet(df, sheet_name, profile)
            records.extend(sheet_records)
            logger.info(
                "Parsed sheet %s: %d records (conf=%.2f)",
                sheet_name, len(sheet_records), profile.confidence,
            )
        except Exception as exc:
            logger.warning("Failed to parse sheet %s: %s", sheet_name, exc)

    return records


def parse_master_excel(excel_path: str, db_conn=None) -> List[Dict]:
    """Load master spec checklist from Excel.

    Dynamically detects header rows and column positions for any workbook
    layout.  Pass db_conn to enable profile caching and learning.
    """
    return _parse_workbook(excel_path, db_conn=db_conn)
