.\.venv\Scripts\Activate.ps1

# ── Pipeline tuning ──────────────────────────────────────────────────────────
$env:FAST_MODE         = "0"
$env:FAST_PDF_PAGES    = "0"
$env:FAST_SPEC_LIMIT   = "0"
$env:FAST_SKIP_OCR     = "1"
$env:FAST_TOP_K        = "2"
$env:FAST_VENDOR_LIMIT = "0"
$env:FAST_BLOCK_LIMIT  = "0"
$env:FAST_REUSE_PARSED = "1"
$env:PIPELINE_EVAL_WORKERS = "6"
$env:LLM_MAX_CONCURRENT    = "2"
$env:LLM_ONLY_UNCERTAIN    = "1"
$env:FAST_TOP_K            = "2"
$env:FAST_REUSE_PARSED     = "1"
$env:FAST_SKIP_OCR         = "1"

# ── Company LLM server (LM Studio) ───────────────────────────────────────────
$env:LLM_BACKEND       = "lmstudio"
$env:OLLAMA_HOST       = "http://10.5.65.131:1234"
$env:OLLAMA_MODEL      = "qwen3-30b-a3b-instruct-2507"
$env:OLLAMA_TIMEOUT    = "120"
$env:OLLAMA_CACHE      = "1"
$env:OLLAMA_CACHE_MAX  = "2000"
$env:OLLAMA_KEEP_ALIVE = "30m"
$env:OLLAMA_NUM_CTX    = "1536"
$env:OLLAMA_WARMUP     = "1"

# ── Network access ───────────────────────────────────────────────────────────
$env:ALLOWED_HOSTS = "127.0.0.1,::1,localhost,10.5.51.82"

uvicorn src.app.api:app --host 0.0.0.0 --port 8088
