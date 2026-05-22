from typing import List, Dict
import pandas as pd


def parse_master_excel(excel_path: str) -> List[Dict]:
    """Load master spec checklist from Excel.

    Expects columns: Spec_ID, Parameter_Name, BHEL_Requirement (case-insensitive).
    Returns list of dicts.
    """
    df = pd.read_excel(excel_path, dtype=str)
    # Normalize column names
    cols = {c.lower(): c for c in df.columns}
    def get(col):
        return df[cols[col]] if col in cols else None

    # Try several common names
    spec_col = cols.get("spec_id") or cols.get("spec") or list(df.columns)[0]
    name_col = cols.get("parameter_name") or cols.get("parameter") or list(df.columns)[1]
    req_col = cols.get("bhel_requirement") or cols.get("requirement") or list(df.columns)[2]

    records = []
    for _, row in df.iterrows():
        records.append({
            "Spec_ID": str(row[spec_col]),
            "Parameter_Name": str(row[name_col]),
            "BHEL_Requirement": str(row[req_col]),
        })
    return records
