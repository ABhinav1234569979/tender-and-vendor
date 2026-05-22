from pathlib import Path
import logging
from src.ingest.excel_parser import parse_master_excel
from src.ingest.pdf_parser import parse_pdf_blocks
from src.storage.db import init_db, get_connection
from src.evaluator import MultiAgentEvaluator
from src.reporting.excel_report import build_excel_report
from src.utils.logging import setup_logging
from src.utils.paths import PROJECT_ROOT


def main() -> None:
    setup_logging()
    logging.info("Starting pipeline")

    cfg_in = PROJECT_ROOT / "data" / "incoming"
    cfg_parsed = PROJECT_ROOT / "data" / "parsed"
    cfg_out = PROJECT_ROOT / "data" / "output"
    cfg_db = cfg_parsed / "app.db"

    cfg_parsed.mkdir(parents=True, exist_ok=True)
    cfg_out.mkdir(parents=True, exist_ok=True)

    init_db(str(cfg_db))

    # locate master spec
    master_candidates = list(cfg_in.glob("*.xlsx"))
    if not master_candidates:
        logging.error("No master spec .xlsx found in data/incoming")
        return
    master = master_candidates[0]
    specs = parse_master_excel(str(master))

    # locate vendor pdfs
    vendor_files = list(cfg_in.glob("*.pdf"))
    if not vendor_files:
        logging.error("No vendor PDFs found in data/incoming")
        return

    evaluator = MultiAgentEvaluator()

    # Simple parse and evaluate loop
    conn = get_connection(str(cfg_db))
    cur = conn.cursor()

    for v in vendor_files:
        vendor_id = v.stem
        logging.info(f"Parsing vendor file: {v.name}")
        blocks = parse_pdf_blocks(str(v))
        # concatenate text for evaluation context
        context = "\n\n".join(b["text"] for b in blocks)

        for spec in specs:
            res = evaluator.evaluate_spec(vendor_id, spec, context)
            cur.execute(
                "INSERT OR REPLACE INTO compliance_matrix (spec_id, vendor_id, status, citation, reasoning, confidence) VALUES (?, ?, ?, ?, ?, ?)",
                (spec["Spec_ID"], vendor_id, res.status, res.citation, res.reasoning, res.confidence),
            )
        conn.commit()

    conn.close()

    # build report
    out_path = cfg_out / "vendor_comparison_matrix.xlsx"
    build_excel_report(str(out_path))
    logging.info(f"Report written to {out_path}")


if __name__ == "__main__":
    main()
