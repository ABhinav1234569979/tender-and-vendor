from src.engine.orchestrator import VendorIndex, _score_block_with_index, _top_blocks_from_index, dispatch_spec_vendor


def test_score_block_and_top_blocks():
    spec_text = "Must withstand 600C"
    blocks = [
        {"text": "This material can withstand 600C under load.", "page": 1, "bbox": [0, 0, 10, 10]},
        {"text": "No relevant data here.", "page": 2, "bbox": [0, 0, 5, 5]},
    ]

    index = VendorIndex.build(blocks)
    from collections import Counter
    from src.engine.orchestrator import _tokenize
    spec_counts = Counter(_tokenize(spec_text))
    score = _score_block_with_index(spec_counts, index.block_token_counts[0], len(index.block_tokens[0]), index)
    assert score > 0.0

    top, _ = _top_blocks_from_index(spec_text, index, limit=2)
    assert len(top) == 2
    assert top[0]["text"].startswith("This material")


def test_dispatch_fast_mode():
    spec = {"Spec_ID": "S1", "company_Requirement": "Must withstand 600C"}
    blocks = [
        {"text": "This material can withstand 600C", "page": 1, "bbox": [0, 0, 1, 1]},
        {"text": "Nothing here", "page": 2, "bbox": [0, 0, 1, 1]},
    ]

    res = dispatch_spec_vendor(spec, "vendorA", blocks, top_k=2, fast=True)

    assert res["spec_id"] == "S1"
    assert "status" in res and "confidence" in res
    assert isinstance(res["top_blocks"], list)


def test_top_blocks_returns_copies_and_verifies_citation(monkeypatch):
    spec = {"Spec_ID": "S3", "company_Requirement": "Must include TPM module"}
    blocks = [{"text": "Device includes TPM module.", "page": 0, "bbox": [0, 0, 1, 1]}]

    monkeypatch.setattr(
        "src.engine.orchestrator.run_technical_agent",
        lambda *a, **k: {"status": "YES", "confidence": 0.9, "citation": "invented citation"},
    )
    monkeypatch.setattr(
        "src.engine.orchestrator.run_risk_agent",
        lambda *a, **k: {"status": "YES", "confidence": 0.8, "citation": "invented citation"},
    )
    monkeypatch.setattr(
        "src.engine.orchestrator.run_fallback_agent",
        lambda *a, **k: {"status": "NO", "confidence": 0.1, "citation": ""},
    )
    monkeypatch.setattr(
        "src.engine.orchestrator.run_consensus_judge",
        lambda *a, **k: {"status": "YES", "confidence": 0.9, "citation": "invented citation", "reasoning": "mocked"},
    )

    res = dispatch_spec_vendor(spec, "vendorA", blocks, top_k=1, fast=False)

    assert res["citation"] == "Device includes TPM module."
    assert res["top_blocks"][0] is not blocks[0]


def test_dispatch_full_mode_with_mocked_agents(monkeypatch):
    spec = {"Spec_ID": "S2", "company_Requirement": "Must be certified"}
    blocks = [{"text": "Certified to standard X", "page": 1, "bbox": []}]

    monkeypatch.setattr("src.engine.orchestrator.run_technical_agent", lambda *a, **k: {"status": "YES", "confidence": 0.9, "citation": "t"})
    monkeypatch.setattr("src.engine.orchestrator.run_risk_agent", lambda *a, **k: {"status": "NO", "confidence": 0.1, "citation": "r"})
    monkeypatch.setattr("src.engine.orchestrator.run_fallback_agent", lambda *a, **k: {"status": "NEARLY OK", "confidence": 0.5, "citation": "f"})
    monkeypatch.setattr("src.engine.orchestrator.run_consensus_judge", lambda tech, risk, fb, model_name=None: {"status": "YES", "confidence": 0.9, "citation": "t", "reasoning": "mocked"})

    res = dispatch_spec_vendor(spec, "vendorB", blocks, top_k=1, fast=False)

    assert res["status"] == "YES"
    assert res["technical"]["status"] == "YES"
    assert res["risk"]["status"] == "NO"
    assert res["fallback"]["status"] == "NEARLY OK"
