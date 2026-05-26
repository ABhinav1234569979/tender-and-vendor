@echo off
REM Activate venv and run Uvicorn for FastAPI app
SETLOCAL

IF EXIST .venv\Scripts\activate.bat (
  call .venv\Scripts\activate.bat
) ELSE (
  echo venv activate script not found; using .venv python directly
)

REM ── Pipeline tuning ────────────────────────────────────────────────────────
set FAST_MODE=0
set FAST_PDF_PAGES=0
set FAST_SPEC_LIMIT=0
set FAST_SKIP_OCR=1
set FAST_TOP_K=2
set FAST_VENDOR_LIMIT=0
set FAST_BLOCK_LIMIT=0
set FAST_REUSE_PARSED=1
set PIPELINE_EVAL_WORKERS=6
set LLM_MAX_CONCURRENT=2
set LLM_ONLY_UNCERTAIN=1

REM Company LLM server (LM Studio)
set LLM_BACKEND=lmstudio
set OLLAMA_HOST=http://10.5.65.131:1234
set OLLAMA_MODEL=qwen3.6-35b-a3b
set OLLAMA_TIMEOUT=120
set OLLAMA_CACHE=1
set OLLAMA_CACHE_MAX=2000
set OLLAMA_KEEP_ALIVE=30m
set OLLAMA_NUM_CTX=1536
set OLLAMA_WARMUP=1

REM ── Network access ─────────────────────────────────────────────────────────
REM Comma-separated IPs/hostnames allowed to call the API.
set ALLOWED_HOSTS=127.0.0.1,::1,localhost,10.5.51.82

REM Bind to all interfaces so LAN clients can reach the API.
.venv\Scripts\python.exe -m uvicorn src.app.api:app --host 0.0.0.0 --port 8088

ENDLOCAL
