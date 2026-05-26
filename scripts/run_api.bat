@echo off
REM Activate venv and run Uvicorn for FastAPI app
SETLOCAL
IF EXIST .venv\Scripts\activate.bat (
  call .venv\Scripts\activate.bat
) ELSE (
  REM fallback: use python executable directly
  echo "venv activate script not found; using .venv python"
)
.
set FAST_MODE=1
set FAST_PDF_PAGES=10
set FAST_SPEC_LIMIT=25
set FAST_SKIP_OCR=1
set FAST_TOP_K=3
set FAST_VENDOR_LIMIT=1
set FAST_BLOCK_LIMIT=300
set FAST_REUSE_PARSED=1
%~dp0.venv\Scripts\python.exe -m uvicorn src.app.api:app --host 127.0.0.1 --port 8088
ENDLOCAL
  