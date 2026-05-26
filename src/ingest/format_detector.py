"""Dynamic Excel format detector.

Analyses any workbook and returns a normalised FormatProfile describing
where the header row is, which columns hold the serial number, parameter
name, requirement text, and compliance answer.  The profile is persisted
to the DB so the system learns from every new file it sees.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# ── keyword banks ────────────────────────────────────────────────────────────
_SERIAL_KEYWORDS   = {"s. no.", "s. no", "s.no.", "s.no", "sl. no.", "sl. no",
                      "sl.no.", "sl.no", "sr. no.", "sr. no", "sr.no.", "sr.no",
                      "sno", "serial", "#", "item no", "s no"}
_PARAM_KEYWORDS    = {"parameter", "feature", "item", "description", "particulars",
                      "specification name", "attribute"}
_REQ_KEYWORDS      = {"requirement", "specification", "detail", "spec", "criteria",
                      "technical spec", "detailed spec", "tender spec"}
_COMPLY_KEYWORDS   = {"compliance", "bidder", "y/n", "yes/no", "comply",
                      "vendor response", "response", "status"}
_REMARK_KEYWORDS   = {"remark", "comment", "note", "justification", "deviation"}
_PAGE_KEYWORDS     = {"page", "pg.", "ref", "reference", "doc ref"}


def _norm(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip().lower()
    return "" if s == "nan" else s


def _score_cell(cell_text: str, keywords: set) -> float:
    t = _norm(cell_text)
    if not t:
        return 0.0
    if keywords is _REQ_KEYWORDS and t.replace(" ", "_") in {"spec_id", "specid", "spec_id."}:
        return 0.0
    if keywords is _REQ_KEYWORDS and "requirement" in t:
        return 1.0
    for kw in keywords:
        if len(kw) <= 2 and t != kw:
            continue
        if kw in {"s. no", "s. no.", "s.no", "s.no.", "sl. no", "sl. no.", "sr. no", "sr. no."}:
            if t == kw or t.startswith(kw + " "):
                return 1.0
            continue
        if kw in t:
            return 1.0
    # partial word match
    words = re.findall(r"[a-z]+", t)
    for w in words:
        for kw in keywords:
            if w in kw or kw in w:
                return 0.5
    return 0.0


@dataclass
class ColumnMap:
    serial_col: int = 0
    param_col: int = 1
    req_col: int = 2
    comply_col: Optional[int] = None
    remark_col: Optional[int] = None
    page_col: Optional[int] = None


@dataclass
class FormatProfile:
    sheet_name: str
    header_row: int          # 0-based row index of the header
    data_start_row: int      # 0-based first data row
    col_map: ColumnMap
    item_code: str = ""
    confidence: float = 0.0  # 0-1 how confident we are in this detection

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FormatProfile":
        cm = ColumnMap(**d.pop("col_map"))
        return cls(col_map=cm, **d)


def _find_header_row(df: pd.DataFrame, max_scan: int = 20) -> Tuple[int, float]:
    """Return (row_index, confidence) of the most likely header row."""
    best_row = 0
    best_score = 0.0
    n_cols = min(df.shape[1], 12)
    for r in range(min(max_scan, df.shape[0])):
        row_vals = [_norm(df.iloc[r, c]) for c in range(n_cols)]
        has_serial = any(_score_cell(v, _SERIAL_KEYWORDS) > 0 for v in row_vals)
        has_param  = any(_score_cell(v, _PARAM_KEYWORDS)  > 0 for v in row_vals)
        has_req    = any(_score_cell(v, _REQ_KEYWORDS)    > 0 for v in row_vals)
        score = (has_serial * 0.3) + (has_param * 0.4) + (has_req * 0.3)
        if score > best_score:
            best_score = score
            best_row = r
    return best_row, best_score


def _detect_columns(header_vals: List[str]) -> Tuple[ColumnMap, float]:
    """Score each column against keyword banks and return best mapping."""
    scores: Dict[str, List[Tuple[float, int]]] = {
        "serial": [], "param": [], "req": [], "comply": [], "remark": [], "page": []
    }
    for idx, val in enumerate(header_vals):
        scores["serial"].append((_score_cell(val, _SERIAL_KEYWORDS), idx))
        scores["param"].append((_score_cell(val, _PARAM_KEYWORDS),   idx))
        scores["req"].append((_score_cell(val, _REQ_KEYWORDS),       idx))
        scores["comply"].append((_score_cell(val, _COMPLY_KEYWORDS), idx))
        scores["remark"].append((_score_cell(val, _REMARK_KEYWORDS), idx))
        scores["page"].append((_score_cell(val, _PAGE_KEYWORDS),     idx))

    def best(key: str, exclude: set = frozenset()) -> Tuple[Optional[int], float]:
        candidates = [(s, i) for s, i in scores[key] if i not in exclude and s > 0]
        if not candidates:
            return None, 0.0
        s, i = max(candidates, key=lambda item: (item[0], -item[1]))
        return i, s

    used: set = set()
    serial_col, s0 = best("serial")
    if serial_col is not None:
        used.add(serial_col)
    param_col, s1 = best("param", used)
    if param_col is not None:
        used.add(param_col)
    req_col, s2 = best("req", used)
    if req_col is not None:
        used.add(req_col)
    comply_col, s3 = best("comply", used)
    if comply_col is not None:
        used.add(comply_col)
    remark_col, s4 = best("remark", used)
    if remark_col is not None:
        used.add(remark_col)
    page_col, s5 = best("page", used)

    # fallback defaults
    n = len(header_vals)
    cm = ColumnMap(
        serial_col=serial_col if serial_col is not None else 0,
        param_col=param_col   if param_col  is not None else min(1, n - 1),
        req_col=req_col       if req_col    is not None else min(2, n - 1),
        comply_col=comply_col,
        remark_col=remark_col,
        page_col=page_col,
    )
    confidence = (s0 + s1 + s2) / 3.0
    return cm, confidence


def detect_format(excel_path: str) -> Dict[str, FormatProfile]:
    """Detect the format of every sheet in a workbook.

    Returns {sheet_name: FormatProfile}.
    """
    profiles: Dict[str, FormatProfile] = {}
    try:
        xls = pd.ExcelFile(excel_path)
    except Exception as exc:
        logger.error("Cannot open workbook %s: %s", excel_path, exc)
        return profiles

    for sheet in xls.sheet_names:
        try:
            df = pd.read_excel(xls, sheet_name=sheet, header=None, dtype=str).fillna("")
            if df.empty or df.shape[1] < 2:
                continue

            # extract item code from row 1 col 2 (common pattern)
            item_code = ""
            if df.shape[0] > 1 and df.shape[1] > 2:
                raw = _norm(df.iloc[1, 2])
                if re.match(r"^[a-z]{1,6}\d{1,6}$", raw):
                    item_code = raw.upper()

            header_row, hdr_conf = _find_header_row(df)
            header_vals = [_norm(df.iloc[header_row, c]) for c in range(df.shape[1])]
            col_map, col_conf = _detect_columns(header_vals)
            confidence = (hdr_conf + col_conf) / 2.0

            profiles[sheet] = FormatProfile(
                sheet_name=sheet,
                header_row=header_row,
                data_start_row=header_row + 1,
                col_map=col_map,
                item_code=item_code,
                confidence=confidence,
            )
            logger.info(
                "Sheet %s: header_row=%d conf=%.2f serial=%d param=%d req=%d",
                sheet, header_row, confidence,
                col_map.serial_col, col_map.param_col, col_map.req_col,
            )
        except Exception as exc:
            logger.warning("Format detection failed for sheet %s: %s", sheet, exc)

    return profiles


def save_format_profile(db_conn, file_name: str, profiles: Dict[str, FormatProfile]) -> None:
    """Persist detected format profiles to the format_profiles table."""
    db_conn.execute(
        "DELETE FROM format_profiles WHERE file_name=?", (file_name,)
    )
    for sheet, profile in profiles.items():
        db_conn.execute(
            "INSERT INTO format_profiles (file_name, sheet_name, profile_json) VALUES (?, ?, ?)",
            (file_name, sheet, json.dumps(profile.to_dict())),
        )
    db_conn.commit()


def load_format_profile(db_conn, file_name: str) -> Dict[str, FormatProfile]:
    """Load previously saved format profiles from DB."""
    rows = db_conn.execute(
        "SELECT sheet_name, profile_json FROM format_profiles WHERE file_name=?",
        (file_name,),
    ).fetchall()
    result: Dict[str, FormatProfile] = {}
    for sheet_name, profile_json in rows:
        try:
            d = json.loads(profile_json)
            result[sheet_name] = FormatProfile.from_dict(d)
        except Exception as exc:
            logger.warning("Could not load profile for %s/%s: %s", file_name, sheet_name, exc)
    return result
