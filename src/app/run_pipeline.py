from pathlib import Path
import logging
import json
import os
import uuid
from typing import Callable, Optional
from src.ingest.excel_parser import parse_master_excel
from src.ingest.pdf_parser import parse_pdf_blocks
from src.storage.db import init_db, get_connection
from src.engine.orchestrator import VendorIndex, dispatch_spec_vendor
from src.reporting.excel_report import build_excel_report
from src.utils.logging import setup_logging
from src.utils.paths import PROJECT_ROOT


def _load_blocks_from_db(cur, file_name: str) -> list[dict]:
    rows = cur.execute(
        "SELECT page, bbox, text FROM parsed_documents WHERE file_name=? ORDER BY page, doc_id",
        (file_name,),
    ).fetchall()
    blocks = []
    for page, bbox, text in rows:
        try:
            parsed_bbox = json.loads(bbox)
        except Exception:
            parsed_bbox = bbox
        blocks.append({"page": page, "bbox": parsed_bbox, "text": text})
    return blocks


def _citation_doc_id(vendor_id: str, top_blocks: list[dict]) -> str | None:
    if not top_blocks:
        return None
    page = top_blocks[0].get("page")
    return f"{vendor_id}:{page}:0" if page is not None else None


def _pick_master_workbook(cfg_in: Path) -> Path | None:
    preferred = cfg_in / "Tech_Comp_check_list.xlsx"
    if preferred.exists():
        return preferred
    candidates = sorted(
        path for path in cfg_in.glob("*.xlsx") if path.name.lower() != "tech_comp_check_list.xlsx"
    )
    return candidates[0] if candidates else None


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int = 0) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _update_progress(cur, conn, run_id: str, progress: float, message: str, progress_cb=None) -> None:
    """Write progress to DB and commit immediately so the API can read it."""
    cur.execute(
        "UPDATE pipeline_runs SET progress=?, message=?, updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
        (round(progress, 2), message, run_id),
    )
    conn.commit()
    if progress_cb:
        progress_cb(round(progress, 2), message)


def main(run_id: str | None = None, progress_cb: Optional[Callable[[float, str], None]] = None) -> None:
    setup_logging()
    logging.info("Starting pipeline")

    cfg_in = PROJECT_ROOT / "data" / "incoming"
    cfg_parsed = PROJECT_ROOT / "data" / "parsed"
    cfg_out = PROJECT_ROOT / "data" / "output"
    cfg_db = cfg_parsed / "app.db"

    cfg_parsed.mkdir(parents=True, exist_ok=True)
    cfg_out.mkdir(parents=True, exist_ok=True)

    init_db(str(cfg_db))
    run_id = run_id or str(uuid.uuid4())

    # locate master spec
    master = _pick_master_workbook(cfg_in)
    if master is None:
        logging.error("No master spec .xlsx found in data/incoming")
        return
    specs = parse_master_excel(str(master))

    fast_mode = _bool_env("FAST_MODE")
    if fast_mode:
        os.environ.setdefault("FAST_SKIP_OCR", "1")
        os.environ.setdefault("FAST_PDF_PAGES", "10")
        os.environ.setdefault("FAST_SPEC_LIMIT", "25")
        os.environ.setdefault("FAST_TOP_K", "3")
        os.environ.setdefault("FAST_VENDOR_LIMIT", "1")
        os.environ.setdefault("FAST_BLOCK_LIMIT", "300")
        os.environ.setdefault("FAST_REUSE_PARSED", "1")

    spec_limit = _int_env("FAST_SPEC_LIMIT", 0)
    if spec_limit and len(specs) > spec_limit:
        specs = specs[:spec_limit]
        logging.info("Limiting specs to %s", spec_limit)

    top_k = _int_env("FAST_TOP_K", 3 if fast_mode else 5)

    # locate vendor pdfs
    vendor_files = list(cfg_in.glob("*.pdf"))
    if not vendor_files:
        logging.error("No vendor PDFs found in data/incoming")
        return

    vendor_limit = _int_env("FAST_VENDOR_LIMIT", 0)
    if vendor_limit and len(vendor_files) > vendor_limit:
        vendor_files = vendor_files[:vendor_limit]
        logging.info("Limiting vendors to %s", vendor_limit)

    n_vendors = len(vendor_files)
    n_specs = len(specs)

    # Phase weights: parsing = 20%, evaluation = 70%, report = 10%
    PARSE_WEIGHT = 20.0
    EVAL_WEIGHT = 70.0
    # REPORT_WEIGHT = 10.0  (remainder)

    conn = get_connection(str(cfg_db))
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO pipeline_runs (run_id, status, progress, message, error, updated_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
        (run_id, "running", 0.0, "Pipeline started", ""),
    )
    cur.execute(
        "INSERT INTO audit_log (action, entity_type, entity_id, details) VALUES (?, ?, ?, ?)",
        ("pipeline_start", "run", run_id, json.dumps({"master": master.name, "vendors": [v.name for v in vendor_files]})),
    )
    cur.execute("DELETE FROM master_specs WHERE source_file=?", (master.name,))
    for index, spec in enumerate(specs, start=1):
        cur.execute(
            "INSERT OR REPLACE INTO master_specs (source_file, sheet_name, spec_id, parameter_name, company_requirement, row_index) VALUES (?, ?, ?, ?, ?, ?)",
            (
                master.name,
                spec.get("sheet_name", ""),
                spec.get("Spec_ID", ""),
                spec.get("Parameter_Name", ""),
                spec.get("company_Requirement") or spec.get("company_requirement", ""),
                spec.get("row_index", index),
            ),
        )
    conn.commit()
    _update_progress(cur, conn, run_id, 1.0, f"Loaded {n_specs} specs, {n_vendors} vendor PDFs", progress_cb)

    existing_pairs = set(
        cur.execute("SELECT spec_id, vendor_id FROM compliance_matrix").fetchall()
    )

    total_pairs = max(1, n_vendors * n_specs)
    processed_pairs = 0

    try:
        # ── Phase 1: Parse all vendor PDFs ──────────────────────────────────
        parsed_blocks: dict[str, list[dict]] = {}
        for v_idx, v in enumerate(vendor_files):
            vendor_id = v.stem
            parse_start_pct = PARSE_WEIGHT * (v_idx / n_vendors)
            parse_end_pct   = PARSE_WEIGHT * ((v_idx + 1) / n_vendors)

            _update_progress(
                cur, conn, run_id,
                parse_start_pct,
                f"Parsing PDF {v_idx + 1}/{n_vendors}: {v.name}",
                progress_cb,
            )
            logging.info(f"Parsing vendor file: {v.name}")

            reuse_parsed = _bool_env("FAST_REUSE_PARSED")
            db_blocks = None
            if reuse_parsed:
                existing_count = cur.execute(
                    "SELECT COUNT(*) FROM parsed_documents WHERE file_name=?",
                    (v.name,),
                ).fetchone()[0]
                if existing_count:
                    db_blocks = _load_blocks_from_db(cur, v.name)
                    logging.info("Reusing %s parsed blocks for %s", len(db_blocks), v.name)
                    cur.execute(
                        "INSERT OR REPLACE INTO audit_log (action, entity_type, entity_id, details) VALUES (?, ?, ?, ?)",
                        ("parse_pdf", "vendor", vendor_id, json.dumps({"file": v.name, "pages": len(db_blocks), "reused": True})),
                    )

            if db_blocks is None:
                blocks = parse_pdf_blocks(str(v))
                cur.execute(
                    "INSERT OR REPLACE INTO audit_log (action, entity_type, entity_id, details) VALUES (?, ?, ?, ?)",
                    ("parse_pdf", "vendor", vendor_id, json.dumps({"file": v.name, "pages": len(blocks)})),
                )
                for i, b in enumerate(blocks):
                    doc_id = f"{vendor_id}:{b['page']}:{i}"
                    cur.execute(
                        "INSERT OR REPLACE INTO parsed_documents (doc_id, file_name, page, bbox, text) VALUES (?, ?, ?, ?, ?)",
                        (doc_id, v.name, b["page"], str(b["bbox"]), b["text"]),
                    )
                db_blocks = blocks

            block_limit = _int_env("FAST_BLOCK_LIMIT", 0)
            if block_limit and len(db_blocks) > block_limit:
                db_blocks = db_blocks[:block_limit]

            parsed_blocks[vendor_id] = db_blocks
            _update_progress(
                cur, conn, run_id,
                parse_end_pct,
                f"Parsed {v.name} — {len(db_blocks)} blocks",
                progress_cb,
            )

        # ── Phase 2: Evaluate spec/vendor pairs ─────────────────────────────
        for v_idx, v in enumerate(vendor_files):
            vendor_id = v.stem
            db_blocks = parsed_blocks[vendor_id]
            vendor_index = VendorIndex.build(db_blocks)

            for s_idx, spec in enumerate(specs):
                spec_id = spec.get("Spec_ID", "")

                # compute precise progress within eval phase
                pair_idx = v_idx * n_specs + s_idx
                eval_pct = PARSE_WEIGHT + EVAL_WEIGHT * (pair_idx / total_pairs)

                if (spec_id, vendor_id) in existing_pairs:
                    processed_pairs += 1
                    _update_progress(
                        cur, conn, run_id,
                        PARSE_WEIGHT + EVAL_WEIGHT * (processed_pairs / total_pairs),
                        f"Skipped {processed_pairs}/{total_pairs} pairs (cached)",
                        progress_cb,
                    )
                    continue

                # emit progress BEFORE the (potentially slow) dispatch call
                _update_progress(
                    cur, conn, run_id,
                    eval_pct,
                    f"Evaluating pair {pair_idx + 1}/{total_pairs} — {vendor_id} × {spec_id}",
                    progress_cb,
                )

                result = dispatch_spec_vendor(
                    spec,
                    vendor_id,
                    db_blocks,
                    vendor_index=vendor_index,
                    top_k=top_k,
                    fast=fast_mode,
                )
                citation_bbox = result.get("citation_bbox")
                if citation_bbox is not None:
                    citation_bbox = json.dumps(citation_bbox)
                top_blocks = result.get("top_blocks", [])
                cur.execute(
                    "INSERT OR REPLACE INTO compliance_matrix (spec_id, vendor_id, status, citation, citation_doc_id, citation_excerpt, citation_page, citation_bbox, reasoning, confidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        result["spec_id"],
                        result["vendor_id"],
                        result["status"],
                        result["citation"],
                        _citation_doc_id(vendor_id, top_blocks),
                        result["citation"][:1000],
                        result.get("citation_page"),
                        citation_bbox,
                        result["reasoning"],
                        result["confidence"],
                    ),
                )
                processed_pairs += 1
                _update_progress(
                    cur, conn, run_id,
                    PARSE_WEIGHT + EVAL_WEIGHT * (processed_pairs / total_pairs),
                    f"Evaluated {processed_pairs}/{total_pairs} pairs — {vendor_id} × {spec_id} → {result['status']}",
                    progress_cb,
                )

        # ── Phase 3: Build report ────────────────────────────────────────────
        _update_progress(cur, conn, run_id, 91.0, "Building Excel report…", progress_cb)
        cur.execute(
            "INSERT INTO audit_log (action, entity_type, entity_id, details) VALUES (?, ?, ?, ?)",
            ("pipeline_complete", "run", run_id, json.dumps({"output": str(cfg_out / "vendor_comparison_matrix.xlsx")})),
        )
        conn.commit()

    except Exception as exc:
        cur.execute(
            "UPDATE pipeline_runs SET status=?, error=?, message=?, updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
            ("failed", str(exc), "Pipeline failed", run_id),
        )
        conn.commit()
        raise
    finally:
        conn.close()

    # build report (outside the connection so it doesn't hold the lock)
    out_path = cfg_out / "vendor_comparison_matrix.xlsx"
    build_excel_report(str(out_path), db_path=str(cfg_db))
    logging.info(f"Report written to {out_path}")

    # final status update
    conn2 = get_connection(str(cfg_db))
    try:
        conn2.execute(
            "UPDATE pipeline_runs SET status=?, progress=?, message=?, updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
            ("completed", 100.0, "Pipeline completed", run_id),
        )
        conn2.commit()
    finally:
        conn2.close()
    if progress_cb:
        progress_cb(100.0, "Pipeline completed")
