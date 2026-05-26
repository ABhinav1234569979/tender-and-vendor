from __future__ import annotations

from typing import Any, Dict, List, Optional
import json
import re

from src.engine.prompts import JUDGE_PROMPT
from src.engine.ollama_client import ollama_generate


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n|```$", "", cleaned.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except Exception:
            return None


def _decision_rule(technical: Dict[str, Any], risk: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    agents = [technical, risk, fallback]
    tech_status = str(technical.get("status", "NO")).strip().upper()
    risk_status = str(risk.get("status", "NO")).strip().upper()
    fallback_status = str(fallback.get("status", "NO")).strip().upper()
    status = "NEARLY OK"
    if tech_status == "YES" and (risk_status == "YES" or fallback_status == "YES"):
        status = "YES"
    elif tech_status == "NO" and risk_status == "NO":
        status = "NO"

    chosen = next(
        (agent for agent in agents if str(agent.get("status", "")).strip().upper() == status),
        fallback or risk or technical,
    )
    confidences = []
    for agent in agents:
        try:
            confidences.append(float(agent.get("confidence", 0.0) or 0.0))
        except (TypeError, ValueError):
            confidences.append(0.0)
    confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return {
        "status": status,
        "citation": chosen.get("citation", ""),
        "reasoning": f"Consensus rule applied: {status}. {chosen.get('reasoning', '')}".strip(),
        "confidence": confidence,
    }


def run_consensus_judge(technical: Dict[str, Any], risk: Dict[str, Any], fallback: Dict[str, Any], model_name: str = "llama3") -> Dict[str, Any]:
    payload = [technical, risk, fallback]
    prompt = JUDGE_PROMPT.format(agent_results=json.dumps(payload, ensure_ascii=False))
    text = ollama_generate(model=model_name, prompt=prompt, temperature=0.0)
    if text:
        parsed = _extract_json(text)
        if parsed:
            return {
                "status": parsed.get("status", "NO"),
                "citation": parsed.get("citation", ""),
                "reasoning": parsed.get("reasoning", ""),
                "confidence": float(parsed.get("confidence", 0.0)),
            }
    return _decision_rule(technical, risk, fallback)
