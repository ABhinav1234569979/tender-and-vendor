.\.venv\Scripts\Activate.ps1
$env:FAST_MODE = "1"
$env:FAST_PDF_PAGES = "10"
$env:FAST_SPEC_LIMIT = "25"
$env:FAST_SKIP_OCR = "1"
$env:FAST_TOP_K = "3"
$env:FAST_VENDOR_LIMIT = "1"
$env:FAST_BLOCK_LIMIT = "300"
$env:FAST_REUSE_PARSED = "1"
uvicorn src.app.api:app --host 127.0.0.1 --port 8088
