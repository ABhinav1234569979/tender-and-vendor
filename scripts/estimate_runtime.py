"""Estimate full pipeline runtime from current data and observed rates."""
from __future__ import annotations

import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ingest.excel_parser import parse_master_excel
from src.storage.db import get_connection, init_db
from src.utils.paths import PROJECT_ROOT

incoming = PROJECT_ROOT / "data" / "incoming"
pdfs = list(incoming.glob("*.pdf"))
master = incoming / "Tech_Comp_check_list.xlsx"
specs = parse_master_excel(str(master)) if master.exists() else []
n_specs = len(specs)
n_vendors = len(pdfs)
total_pairs = n_specs * n_vendors

db = PROJECT_ROOT / "data" / "parsed" / "app.db"
init_db(str(db))
conn = get_connection(str(db))
cm_count = conn.execute("SELECT COUNT(*) FROM compliance_matrix").fetchone()[0]
reasonings = [r[0] or "" for r in conn.execute("SELECT reasoning FROM compliance_matrix").fetchall()]
runs = conn.execute(
    "SELECT run_id, status, progress, message, updated_at FROM pipeline_runs ORDER BY updated_at DESC LIMIT 5"
).fetchall()
conn.close()

paths = Counter()
for r in reasonings:
    if "Heuristic" in r:
        paths["heuristic"] += 1
    elif "Fast evidence" in r:
        paths["quick"] += 1
    elif "heuristic token" in r:
        paths["fast"] += 1
    elif "LLM" in r or "single-call" in r.lower():
        paths["llm"] += 1
    else:
        paths["other"] += 1

# Observed rates (from your LM Studio server tests)
SEC_HEURISTIC = 0.01
SEC_LLM_WARM = 30.0  # with thinking enabled on qwen3.6-35b-a3b
SEC_LLM_FAST = 12.0  # thinking off / warm
SEC_PARSE_REUSE = 5.0  # per PDF when blocks cached
SEC_PARSE_COLD = 120.0  # first-time PDF parse (rough)
SEC_REPORT = 30.0

llm_concurrent = int(os.environ.get("LLM_MAX_CONCURRENT", "2"))

# If we have completed rows, infer LLM fraction from "other" (likely LLM reasoning text)
done = max(1, cm_count)
llm_frac_observed = paths["other"] / done if done else 0.15
# Conservative default if sample is all heuristic so far
llm_frac = max(llm_frac_observed, 0.15)

remaining = total_pairs - cm_count
llm_remaining = int(remaining * llm_frac)
heur_remaining = remaining - llm_remaining

parse_sec = SEC_PARSE_REUSE * n_vendors if os.environ.get("FAST_REUSE_PARSED", "1") != "0" else SEC_PARSE_COLD * n_vendors
eval_sec = heur_remaining * SEC_HEURISTIC + (llm_remaining / llm_concurrent) * SEC_LLM_WARM
total_sec = parse_sec + eval_sec + SEC_REPORT

print("=== Incoming data ===")
print(f"Specs: {n_specs}")
print(f"Vendors: {n_vendors} ({', '.join(p.name for p in pdfs)})")
print(f"Total pairs: {total_pairs}")
print(f"Already in DB: {cm_count}")
print(f"Remaining pairs: {remaining}")
print()
print("=== Path mix in DB (completed rows) ===")
for k, v in paths.most_common():
    print(f"  {k}: {v}")
print()
print("=== Time estimate (remaining + report) ===")
print(f"Assumed LLM share of remaining: {llm_frac:.0%}")
print(f"LLM calls remaining (est): {llm_remaining}")
print(f"LLM concurrent slots: {llm_concurrent}")
print(f"Parse phase: ~{parse_sec/60:.1f} min")
print(f"Eval phase: ~{eval_sec/60:.1f} min ({eval_sec/3600:.1f} h)")
print(f"Report: ~{SEC_REPORT/60:.1f} min")
print(f"TOTAL (rough): ~{total_sec/60:.1f} min ({total_sec/3600:.1f} hours)")
print()
print("=== Scenarios for FULL run from scratch ===")
for label, llm_pct, sec_llm in [
    ("Best (80% heuristic, 12s LLM)", 0.20, SEC_LLM_FAST),
    ("Typical (70% heuristic, 30s LLM)", 0.30, SEC_LLM_WARM),
    ("Worst (all pairs need LLM, 30s)", 1.00, SEC_LLM_WARM),
]:
    llm_n = int(total_pairs * llm_pct)
    heur_n = total_pairs - llm_n
    sec = parse_sec + heur_n * SEC_HEURISTIC + (llm_n / llm_concurrent) * sec_llm + SEC_REPORT
    print(f"  {label}: ~{sec/3600:.1f} hours ({sec/60:.0f} min)")
