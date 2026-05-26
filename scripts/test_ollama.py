"""Quick smoke-test for the LLM client (LM Studio or Ollama)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.engine.ollama_client import (
    LLM_BACKEND,
    OLLAMA_HOST,
    default_model,
    is_healthy,
    list_models,
    ollama_generate,
    pick_best_model,
)

print(f"Backend: {LLM_BACKEND}")
print(f"Host: {OLLAMA_HOST}")
healthy = is_healthy()
print(f"Healthy: {healthy}")
models = list_models()
print(f"Models ({len(models)}): {models[:5]}{'...' if len(models) > 5 else ''}")
if models:
    print(f"Best pick: {pick_best_model(models)}")
print(f"Using: {default_model()}")

if healthy:
    result = ollama_generate(
        default_model(),
        'Return only this JSON: {"status":"YES","citation":"test","reasoning":"ok","confidence":1.0}',
        temperature=0.0,
        max_tokens=80,
    )
    print(f"Generate: {result}")
    result2 = ollama_generate(
        default_model(),
        'Return only this JSON: {"status":"YES","citation":"test","reasoning":"ok","confidence":1.0}',
        temperature=0.0,
        max_tokens=80,
    )
    print(f"Cache hit: {result2 == result}")
else:
    print("LLM not reachable — heuristic fallback will be used")
