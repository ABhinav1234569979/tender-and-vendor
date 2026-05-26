"""Run a full pipeline pass for the current data/incoming files.

This clears compliance rows for the current incoming vendor PDFs so the
pipeline re-evaluates every spec/vendor pair, while keeping parsed PDF text
cached for speed.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.app.run_pipeline import main
from src.storage.db import get_connection, init_db
from src.utils.paths import PROJECT_ROOT


def _set_defaults() -> None:
    # Production-style: real LLM for uncertain pairs only, parallel workers.
    os.environ["FAST_MODE"] = "0"
    os.environ["FAST_REUSE_PARSED"] = "1"
    os.environ["FAST_SKIP_OCR"] = "1"
    os.environ["FAST_VENDOR_LIMIT"] = "0"
    os.environ["FAST_SPEC_LIMIT"] = "0"
    os.environ["FAST_PDF_PAGES"] = "0"
    os.environ["FAST_TOP_K"] = "2"
    os.environ["PIPELINE_EVAL_WORKERS"] = "6"
    os.environ["LLM_MAX_CONCURRENT"] = "2"
    os.environ["LLM_ONLY_UNCERTAIN"] = "1"
    os.environ.setdefault("LLM_BACKEND", "lmstudio")
    os.environ.setdefault("OLLAMA_HOST", "http://10.5.65.131:1234")
    # Instruct model: faster, fewer wasted reasoning tokens than qwen3.6-35b-a3b
    os.environ.setdefault("OLLAMA_MODEL", "qwen3-30b-a3b-instruct-2507")
    os.environ.setdefault("OLLAMA_TIMEOUT", "120")
    os.environ.setdefault("OLLAMA_KEEP_ALIVE", "30m")
    os.environ.setdefault("OLLAMA_NUM_CTX", "1536")


def _clear_current_vendor_results() -> int:
    incoming = PROJECT_ROOT / "data" / "incoming"
    vendors = [path.stem for path in incoming.glob("*.pdf")]
    if not vendors:
        return 0

    db_path = PROJECT_ROOT / "data" / "parsed" / "app.db"
    init_db(str(db_path))
    placeholders = ",".join("?" for _ in vendors)
    conn = get_connection(str(db_path))
    try:
        before = conn.execute(
            f"SELECT COUNT(*) FROM compliance_matrix WHERE vendor_id IN ({placeholders})",
            vendors,
        ).fetchone()[0]
        conn.execute(
            f"DELETE FROM compliance_matrix WHERE vendor_id IN ({placeholders})",
            vendors,
        )
        conn.commit()
        return int(before)
    finally:
        conn.close()


if __name__ == "__main__":
    _set_defaults()
    cleared = _clear_current_vendor_results()
    run_id = f"manual-full-{uuid.uuid4()}"
    print(f"Cleared {cleared} existing compliance rows")
    print(f"Starting full pipeline run: {run_id}")
    main(run_id=run_id)
    print(f"Completed full pipeline run: {run_id}")
