# Basic Architecture and Setup

## Basic Architecture

### Components
- Ingestor: PDF/Excel parsing, OCR for scans.
- Orchestrator: Spec-by-vendor dispatch and chunk selection.
- Agents: technical, risk, fallback.
- Consensus judge: final verdict with citations.
- Review UI: override and audit trail.
- Report engine: Excel matrix and summary output.

### Data Stores
- parsed_documents: parsed blocks with coordinates.
- compliance_matrix: evaluations and citations.
- autonomous_feedback_loop: human overrides.

### Data Flow
- Ingest -> parsed cache -> evaluate -> compliance matrix -> review overrides -> Excel output.

## Python venv (Windows)

### 1) Create venv
```powershell
python -m venv .venv
```

### 2) Activate venv
```powershell
.\.venv\Scripts\Activate.ps1
```

### 3) Upgrade pip
```powershell
python -m pip install --upgrade pip
```

## Required Installs

### Python packages
```powershell
pip install pymupdf pdfplumber pytesseract pandas openpyxl fastapi uvicorn streamlit ollama
```

### System installs
- Tesseract OCR (Windows). Install and add to PATH.
- Ollama (local model runtime).

## Notes
- Keep all paths local. Do not enable any network access.
- Use SQLite for single-user; switch to Postgres for multi-user server.
