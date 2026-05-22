from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class ParsedBlock:
    page: int
    bbox: List[float]
    text: str


class DocumentIngestor:
    def __init__(self, secure_dir: str) -> None:
        self.secure_dir = secure_dir

    def parse_pdf(self, pdf_path: str) -> List[ParsedBlock]:
        """Extract layout-aware blocks from a PDF."""
        raise NotImplementedError("PDF parsing not implemented yet.")

    def parse_excel(self, excel_path: str) -> List[Dict[str, str]]:
        """Load master spec rows from Excel."""
        raise NotImplementedError("Excel parsing not implemented yet.")
