"""Smoke-test company LM Studio server."""
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

HOST = os.environ.get("OLLAMA_HOST", "http://10.5.65.131:1234")


def list_models() -> list[str]:
    with urllib.request.urlopen(f"{HOST}/v1/models", timeout=15) as resp:
        data = json.loads(resp.read().decode())
    return [m["id"] for m in data.get("data", []) if m.get("id")]


def chat(model: str, system: str, user: str) -> dict:
    body = json.dumps(
        {"model": model, "system_prompt": system, "input": user}
    ).encode()
    req = urllib.request.Request(
        f"{HOST}/api/v1/chat",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode())


if __name__ == "__main__":
    from src.engine.ollama_client import pick_best_model, ollama_generate, is_healthy

    print("Host:", HOST)
    models = list_models()
    print("Models:", models)
    best = pick_best_model(models)
    print("Best:", best)
    print("Healthy:", is_healthy())
    out = chat(
        best,
        'Reply with JSON only: {"status":"YES","confidence":0.9}',
        "Does vendor meet 600C requirement? Evidence: rated 650C.",
    )
    print("Chat keys:", list(out.keys()))
    print("Chat sample:", json.dumps(out, indent=2)[:1200])
    gen = ollama_generate(
        best,
        'Return only JSON: {"status":"YES","citation":"x","reasoning":"y","confidence":0.9}',
        temperature=0.0,
        max_tokens=80,
    )
    print("ollama_generate:", gen)
