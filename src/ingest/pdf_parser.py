from typing import List, Dict
import fitz


def parse_pdf_blocks(pdf_path: str) -> List[Dict]:
    """Extract layout-aware text blocks from a PDF using PyMuPDF.

    Returns a list of dicts: {"page": int, "bbox": [x0,y0,x1,y1], "text": str}
    """
    doc = fitz.open(pdf_path)
    blocks: List[Dict] = []
    for page_no, page in enumerate(doc, start=1):
        for b in page.get_text("blocks"):
            x0, y0, x1, y1, text, block_no, block_type = b
            text = text.strip()
            if not text:
                continue
            blocks.append({"page": page_no, "bbox": [x0, y0, x1, y1], "text": text})
    return blocks
