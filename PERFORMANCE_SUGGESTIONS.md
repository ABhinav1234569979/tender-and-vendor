# Performance Suggestions for 10+ Vendor Runs

## Current Bottlenecks

The pipeline cost grows as:

```text
vendors x specifications x evaluation cost
```

For 10 vendors and 500 specs, that is 5,000 spec/vendor checks. Even a 1-second model call per pair becomes more than 80 minutes.

The main slow areas are:

- PDF parsing, especially first run and OCR.
- Repeating model calls for every spec/vendor pair.
- Sequential evaluation of pairs.
- Large prompt context sent to a small local model.
- Excel report generation after a large run.

## Changes Already Applied

- Reuses parsed PDF blocks from SQLite with `FAST_REUSE_PARSED=1`.
- Keeps Ollama warm using `OLLAMA_KEEP_ALIVE=30m`.
- Uses Ollama JSON mode to avoid empty/invalid responses.
- Uses a single-call compliance prompt instead of the old 3-agent + judge path for normal runs.
- Adds a quick evidence gate for obvious YES matches so many pairs avoid Ollama completely.
- Runs evaluation in a bounded worker pool with `PIPELINE_EVAL_WORKERS`.
- Keeps SQLite writes on the main thread to avoid DB locking problems.
- Updated API run scripts to process all vendors/specs by default.

## Recommended Production Settings

Use this for real 10-vendor runs:

```powershell
$env:FAST_MODE = "0"
$env:FAST_REUSE_PARSED = "1"
$env:FAST_SKIP_OCR = "1"
$env:FAST_VENDOR_LIMIT = "0"
$env:FAST_SPEC_LIMIT = "0"
$env:FAST_PDF_PAGES = "0"
$env:FAST_TOP_K = "2"
$env:PIPELINE_EVAL_WORKERS = "4"
$env:OLLAMA_KEEP_ALIVE = "30m"
$env:OLLAMA_NUM_CTX = "1536"
```

Why:

- `FAST_MODE=0` keeps the Ollama path available for ambiguous cases.
- `FAST_REUSE_PARSED=1` makes second and later runs much faster.
- `FAST_SKIP_OCR=1` avoids OCR unless scanned PDFs require it.
- `FAST_TOP_K=2` keeps prompts short.
- `PIPELINE_EVAL_WORKERS=4` gives parallelism without overwhelming a local machine.

## Fast Draft Mode

Use this only for first-pass/draft output:

```powershell
$env:FAST_MODE = "1"
$env:FAST_TOP_K = "2"
$env:PIPELINE_EVAL_WORKERS = "8"
```

This avoids Ollama for most decisions and is much faster, but accuracy is lower.

## Best Architecture for Much Faster Runs

The best production design is a two-stage evaluator:

1. Deterministic retrieval + rules classify obvious YES/NO.
2. Ollama only reviews uncertain or low-confidence cases.

Target:

- 70-90% of rows handled by deterministic/rule logic.
- 10-30% sent to Ollama.
- Human overrides continuously improve the rules.

This is better than sending every row to Ollama.

## Hardware/Model Suggestions

For faster local Ollama:

- Keep using `qwen2.5-coder:1.5b` for speed.
- Consider a small instruction model instead of a coder model for compliance reasoning, such as a 1.5B-3B instruct model if available locally.
- Avoid large 7B+ models unless you have a strong GPU.
- If CPU-only, more parallel Ollama calls can make things slower. Keep `PIPELINE_EVAL_WORKERS` around 2-4.

## Future High-Impact Improvements

Recommended next upgrades:

- Store evaluation cache keyed by `(spec text hash, vendor evidence hash)` so repeated reruns skip unchanged pairs.
- Add an "uncertain only" second pass: quick mode first, Ollama only for low confidence.
- Parse multiple PDFs in parallel.
- Add page-level vendor indexes and search only likely pages.
- Generate reports incrementally instead of rebuilding all vendor files every time.
- Add a UI toggle: `Draft`, `Balanced`, `Strict`.

## Practical Workflow

1. Upload all 10 vendor PDFs and the master Excel.
2. Run once with production settings.
3. Review uncertain/NO rows.
4. Override wrong rows in the UI.
5. Run `/retrain` or run the pipeline again.
6. Later runs become faster because parsed PDFs and learned rules are reused.
