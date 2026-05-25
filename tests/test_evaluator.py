from src.evaluator import MultiAgentEvaluator


def test_evaluate_spec_reads_status_key(monkeypatch):
    evaluator = MultiAgentEvaluator()
    evaluator._generate = lambda **kwargs: {
        "response": '{"status": "YES", "citation": "quoted", "reasoning": "matched", "confidence": 0.8}'
    }

    result = evaluator.evaluate_spec("vendorA", {"company_Requirement": "Must comply"}, "Vendor complies.")

    assert result.status == "YES"
    assert result.citation == "quoted"
