from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
import math
import re

from src.engine.agents import run_fallback_agent, run_risk_agent, run_technical_agent
import logging
from src.engine.judge import run_consensus_judge


def _tokenize(text: str) -> List[str]:
    return [token for token in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(token) > 1]


def _normalize_text(text: str) -> str:
    return " ".join((text or "").split())


@dataclass(frozen=True)
class VendorIndex:
    blocks: List[Dict[str, Any]]
    block_tokens: List[List[str]]
    block_token_counts: List[Counter]
    idf: Dict[str, float]
    avg_block_len: float
    block_texts_norm: List[str]

    @classmethod
    def build(cls, blocks: Sequence[Dict[str, Any]]) -> "VendorIndex":
        block_list = [dict(block) for block in blocks]
        block_tokens: List[List[str]] = []
        block_token_counts: List[Counter] = []
        block_texts_norm: List[str] = []
        doc_freq: Counter = Counter()
        total_len = 0

        for block in block_list:
            text = str(block.get("text", ""))
            tokens = _tokenize(text)
            token_counts = Counter(tokens)
            block_tokens.append(tokens)
            block_token_counts.append(token_counts)
            block_texts_norm.append(_normalize_text(text))
            total_len += len(tokens)
            doc_freq.update(set(tokens))

        total_docs = max(1, len(block_tokens))
        avg_block_len = total_len / total_docs if total_docs else 0.0
        idf = {
            token: math.log((total_docs + 1) / (1 + freq)) + 1
            for token, freq in doc_freq.items()
        }
        return cls(
            blocks=block_list,
            block_tokens=block_tokens,
            block_token_counts=block_token_counts,
            idf=idf,
            avg_block_len=avg_block_len,
            block_texts_norm=block_texts_norm,
        )


def _score_block_with_index(spec_counts: Counter, block_counts: Counter, block_len: int, index: VendorIndex) -> float:
    if not spec_counts or not block_counts:
        return 0.0
    common = set(spec_counts) & set(block_counts)
    if not common:
        return 0.0
    k1 = 1.5
    b = 0.75
    avg_len = max(1.0, index.avg_block_len)
    score = 0.0
    for token in common:
        idf = index.idf.get(token, 0.0)
        if idf == 0.0:
            continue
        term_freq = block_counts[token]
        denom = term_freq + k1 * (1 - b + b * (block_len / avg_len))
        score += idf * ((term_freq * (k1 + 1)) / denom)
    return score


def _verify_citation(citation: str, top_blocks_norm: Sequence[str], fallback: str = "") -> str:
    normalized = _normalize_text(citation)
    if not normalized:
        return fallback
    for block_text in top_blocks_norm:
        if normalized and normalized in block_text:
            return citation
    return fallback


def _top_blocks_from_index(spec_text: str, index: VendorIndex, limit: int = 5) -> Tuple[List[Dict[str, Any]], List[str]]:
    spec_tokens = _tokenize(spec_text)
    if not spec_tokens:
        return [], []
    spec_counts = Counter(spec_tokens)
    scored: List[Tuple[float, int]] = []
    for idx, block_counts in enumerate(index.block_token_counts):
        block_len = len(index.block_tokens[idx])
        score = _score_block_with_index(spec_counts, block_counts, block_len, index)
        scored.append((score, idx))
    scored.sort(key=lambda item: item[0], reverse=True)
    top_indices = [idx for _, idx in scored[:limit]]
    return [dict(index.blocks[idx]) for idx in top_indices], [index.block_texts_norm[idx] for idx in top_indices]


def _trim_context(context: str, max_chars: int = 4000) -> str:
    if len(context) <= max_chars:
        return context
    trimmed = context[:max_chars]
    sentence_end = max(trimmed.rfind("."), trimmed.rfind("!"), trimmed.rfind("?"))
    if sentence_end >= max_chars * 0.6:
        return trimmed[: sentence_end + 1]
    return trimmed.rstrip()


def dispatch_spec_vendor(
    spec: Dict[str, Any],
    vendor_id: str,
    blocks: List[Dict[str, Any]],
    vendor_index: Optional[VendorIndex] = None,
    model_name: str = "qwen2.5-coder:1.5b",
    top_k: int = 5,
    agents: List[str] | None = None,
    fast: bool = False,
) -> Dict[str, Any]:
    requirement = (
        spec.get("company_Requirement")
        or spec.get("company_requirement")
        or ""
    )
    logging.info(f"Dispatching spec {spec.get('Spec_ID','')} for vendor {vendor_id} using model {model_name}")
    if agents is None:
        agents = ["technical", "risk", "fallback"]
    if vendor_index is None:
        logging.warning("VendorIndex not provided; building per spec (slow path)")
        vendor_index = VendorIndex.build(blocks)
    top_blocks, top_blocks_norm = _top_blocks_from_index(requirement, vendor_index, limit=top_k)
    context = "\n\n".join(block.get("text", "") for block in top_blocks)
    context = _trim_context(context)

    if fast:
        # Quick heuristic: check token overlap between requirement and top block
        best = top_blocks[0] if top_blocks else {}
        spec_tokens = set(_tokenize(requirement))
        block_tokens = set(_tokenize(best.get("text", "")))
        overlap = spec_tokens & block_tokens
        score = (len(overlap) / max(1, len(spec_tokens))) if spec_tokens else 0.0
        status = "YES" if score >= 0.2 else "NO"
        confidence = float(min(0.99, max(0.0, score)))
        return {
            "spec_id": spec.get("Spec_ID", ""),
            "vendor_id": vendor_id,
            "status": status,
            "citation": best.get("text", ""),
            "reasoning": f"heuristic token overlap {len(overlap)} tokens",
            "confidence": confidence,
            "citation_page": best.get("page"),
            "citation_bbox": best.get("bbox"),
            "technical": {},
            "risk": {},
            "fallback": {},
            "top_blocks": top_blocks,
        }

    futures = {}
    results = {"technical": {}, "risk": {}, "fallback": {}}
    max_workers = max(1, len(agents))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        if "technical" in agents:
            futures["technical"] = executor.submit(run_technical_agent, context, requirement, model_name)
        if "risk" in agents:
            futures["risk"] = executor.submit(run_risk_agent, context, requirement, model_name)
        if "fallback" in agents:
            futures["fallback"] = executor.submit(run_fallback_agent, context, requirement, model_name)

        for name, fut in futures.items():
            try:
                results[name] = fut.result()
            except Exception:
                results[name] = {}

    # ensure we pass three arguments to judge; missing agents are passed as empty dicts
    judged = run_consensus_judge(
        results.get("technical", {}),
        results.get("risk", {}),
        results.get("fallback", {}),
        model_name,
    )
    best_block = top_blocks[0] if top_blocks else {}
    citation = _verify_citation(judged.get("citation", ""), top_blocks_norm, best_block.get("text", ""))
    return {
        "spec_id": spec.get("Spec_ID", ""),
        "vendor_id": vendor_id,
        "status": judged.get("status", "NO"),
        "citation": citation,
        "reasoning": judged.get("reasoning", ""),
        "confidence": float(judged.get("confidence", 0.0)),
        "citation_page": best_block.get("page"),
        "citation_bbox": best_block.get("bbox"),
        "technical": results.get("technical", {}),
        "risk": results.get("risk", {}),
        "fallback": results.get("fallback", {}),
        "top_blocks": top_blocks,
    }
