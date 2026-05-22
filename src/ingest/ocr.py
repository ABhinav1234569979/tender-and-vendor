import pytesseract
from PIL import Image
import fitz
from typing import Optional


def ocr_pdf_if_needed(pdf_path: str) -> Optional[str]:
    """Run OCR on all pages and return concatenated text. Requires Tesseract installed.

    If pages are digital (contain text), this function will still run OCR but caller may choose otherwise.
    """
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return None

    texts = []
    for page in doc:
        pix = page.get_pixmap(dpi=200)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        text = pytesseract.image_to_string(img)
        texts.append(text)
    return "\n".join(texts)
