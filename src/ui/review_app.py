import streamlit as st
import sqlite3
import pandas as pd
from src.utils.paths import PROJECT_ROOT


def run() -> None:
    st.set_page_config(layout="wide", page_title="BHEL Review Console")
    st.title("BHEL Vendor Compliance Review")

    db_path = PROJECT_ROOT / "data" / "parsed" / "app.db"
    conn = sqlite3.connect(str(db_path))
    df = pd.read_sql_query("SELECT * FROM compliance_matrix", conn)

    if df.empty:
        st.info("No audit data found. Run the pipeline first.")
        return

    st.dataframe(df)

    st.markdown("---")
    st.subheader("Override a cell")
    spec = st.text_input("Spec ID")
    vendor = st.text_input("Vendor ID")
    new_status = st.selectbox("New status", ["YES", "NEARLY OK", "NO"])
    justification = st.text_area("Justification")

    if st.button("Apply Override"):
        if not spec or not vendor or not justification:
            st.error("Spec, Vendor and justification required")
        else:
            cur = conn.cursor()
            # fetch original
            cur.execute("SELECT status FROM compliance_matrix WHERE spec_id=? AND vendor_id=?", (spec, vendor))
            row = cur.fetchone()
            original = row[0] if row else "UNKNOWN"
            # update
            cur.execute("UPDATE compliance_matrix SET status=?, reasoning=? WHERE spec_id=? AND vendor_id=?", (new_status, f"[OVERRIDE] {justification}", spec, vendor))
            cur.execute("INSERT INTO autonomous_feedback_loop (spec_id, vendor_id, original_status, corrected_status, justification, context) VALUES (?, ?, ?, ?, ?, ?)", (spec, vendor, original, new_status, justification, ""))
            conn.commit()
            st.success("Override applied")


if __name__ == "__main__":
    run()
