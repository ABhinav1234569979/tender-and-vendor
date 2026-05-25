import sqlite3

from fastapi.testclient import TestClient

from src.app import api


def test_api_operational_endpoints(tmp_path, monkeypatch):
    incoming = tmp_path / "data" / "incoming"
    parsed = tmp_path / "data" / "parsed"
    output = tmp_path / "data" / "output"
    incoming.mkdir(parents=True)
    parsed.mkdir(parents=True)
    output.mkdir(parents=True)
    (incoming / "vendorA.pdf").write_bytes(b"%PDF-1.4\n")
    (incoming / "Tech_Comp_check_list.xlsx").write_bytes(b"xlsx")

    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    api.app.dependency_overrides[api.require_localhost] = lambda: None
    api.app.dependency_overrides[api.get_current_user] = lambda: {
        "username": "admin",
        "full_name": "Administrator",
        "disabled": False,
    }

    api._ensure_app_db()
    conn = sqlite3.connect(str(parsed / "app.db"))
    try:
        conn.execute(
            "INSERT INTO pipeline_runs (run_id, status, progress, message, error) VALUES (?, ?, ?, ?, ?)",
            ("run-1", "completed", 100, "done", ""),
        )
        conn.execute(
            "INSERT INTO compliance_matrix (spec_id, vendor_id, status, citation, reasoning, confidence) VALUES (?, ?, ?, ?, ?, ?)",
            ("S1", "vendorA", "YES", "cite", "ok", 0.9),
        )
        conn.execute(
            "INSERT INTO parsed_documents (doc_id, file_name, page, bbox, text) VALUES (?, ?, ?, ?, ?)",
            ("doc-1", "vendorA.pdf", 1, "[]", "text"),
        )
        conn.execute(
            "INSERT INTO audit_log (action, entity_type, entity_id, details) VALUES (?, ?, ?, ?)",
            ("test", "run", "run-1", "{}"),
        )
        conn.execute(
            "INSERT INTO training_queue (spec_id, vendor_id, doc_id, page, bbox, excerpt, label) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("S1", "vendorA", "doc-1", 1, "[]", "text", "YES"),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        client = TestClient(api.app)
        for path in [
            "/health",
            "/me",
            "/files",
            "/runs",
            "/runs/run-1",
            "/status/run-1",
            "/results",
            "/results?vendor_id=vendorA&status_filter=YES",
            "/summary",
            "/parsed-document/doc-1",
            "/audit-log",
            "/training-queue",
        ]:
            response = client.get(path)
            assert response.status_code == 200, response.text

        response = client.post(
            "/override",
            json={
                "spec_id": "S1",
                "vendor_id": "vendorA",
                "new_status": "NO",
                "justification": "manual test",
            },
        )
        assert response.status_code == 200, response.text
    finally:
        api.app.dependency_overrides.clear()
