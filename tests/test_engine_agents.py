from src.engine.agents import run_technical_agent, run_fallback_agent
from src.engine.prompts import TECHNICAL_AGENT_PROMPT


def test_technical_agent_heuristic(monkeypatch):
    # ensure external model calls are bypassed so heuristic path is exercised
    monkeypatch.setattr("src.engine.agents._call_ollama", lambda *a, **k: None)

    context = "The material can withstand 600C continuously under load."
    requirement = "Must withstand 600C continuously."

    res = run_technical_agent(context, requirement)

    # heuristic should detect numeric evidence and return NEARLY OK
    assert res["status"] == "NEARLY OK"
    assert "citation" in res and res["citation"]


def test_fallback_agent_web_search(monkeypatch):
    # simulate no model response so heuristic path is exercised
    monkeypatch.setattr("src.engine.agents._call_ollama", lambda *a, **k: None)

    context = "Vendor document text with no direct match."
    requirement = "Equivalent spec acceptable alternative"

    res = run_fallback_agent(context, requirement)

    # heuristic should still return a structured response
    assert "status" in res and "confidence" in res


def test_prompt_template_injects_requirement_and_context():
    prompt = TECHNICAL_AGENT_PROMPT.format(requirement="Minimum 8 cores", context="Octa-core architecture")

    assert "Minimum 8 cores" in prompt
    assert "Octa-core architecture" in prompt
    assert '{"status": "YES|NO|NEARLY OK"' in prompt
