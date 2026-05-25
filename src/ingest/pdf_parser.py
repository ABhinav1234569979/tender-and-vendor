
from typing import List, Dict
from pathlib import Path
import fitz
import os
import logging
import shutil

from PIL import Image
import pytesseract


# Allow override via environment variable (bytes). Defaults to 200 MB.
try:
    MAX_PDF_BYTES = int(os.environ.get("MAX_PDF_BYTES", 200 * 1024 * 1024))
except Exception:
    MAX_PDF_BYTES = 200 * 1024 * 1024


def _tesseract_available() -> bool:
    cmd = getattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract")
    return Path(cmd).exists() or shutil.which(cmd) is not None


def parse_pdf_blocks(pdf_path: str) -> List[Dict]:
    """Extract layout-aware text blocks from a PDF using PyMuPDF.

    Returns a list of dicts: {"page": int, "bbox": [x0,y0,x1,y1], "text": str}
    """
    p = Path(pdf_path)
    if not p.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    size = p.stat().st_size
    if size > MAX_PDF_BYTES:
        raise ValueError(f"PDF too large ({size} bytes) — exceeds {MAX_PDF_BYTES} byte limit")

    doc = fitz.open(pdf_path)
    blocks: List[Dict] = []
    ocr_available = _tesseract_available()
    ocr_skip_logged = False
    for page_no, page in enumerate(doc, start=1):
        page_blocks = []
        for b in page.get_text("blocks"):
            x0, y0, x1, y1, text, block_no, block_type = b
            text = text.strip()
            if not text:
                continue
            page_blocks.append({"page": page_no, "bbox": [x0, y0, x1, y1], "text": text})

        if not page_blocks:
            # OCR fallback for scanned pages
            if not ocr_available:
                if not ocr_skip_logged:
                    logging.warning("OCR skipped for %s: tesseract is not installed or not in PATH", pdf_path)
                    ocr_skip_logged = True
                continue
            try:
                pix = page.get_pixmap(dpi=200)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                ocr_text = pytesseract.image_to_string(img).strip()
                if ocr_text:
                    page_blocks.append({
                        "page": page_no,
                        "bbox": [0, 0, pix.width, pix.height],
                        "text": ocr_text,
                    })
            except Exception as exc:
                logging.warning("OCR failed on page %s of %s: %s", page_no, pdf_path, exc)

        blocks.extend(page_blocks)
    blocks.sort(key=lambda block: (block["page"], block["bbox"][1], block["bbox"][0]))
    return blocks
