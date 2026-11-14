"""Speech presentation cannot weaken the existing grounded-answer boundary."""
from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas import Calculation, DraftAnswer, Operand
from test_backend import FakeProvider, evidence, upload


def test_spoken_fields_are_prepared_after_calculation_validation(tmp_path):
    draft = DraftAnswer(status="answered", answer="The two window widths total {result} m; installation clearance is unknown.",
                        evidence=[evidence()], missing_information=["Installation clearance"],
                        next_action="Check a dimensioned window schedule.",
                        calculation=Calculation(operation="sum", operands=[Operand(value=1.2, evidence_index=0), Operand(value=1.5, evidence_index=0)], unit="m"))
    provider = FakeProvider(draft=draft)
    with TestClient(create_app(provider_factory=lambda: provider, storage_root=tmp_path)) as client:
        document = upload(client)
        response = client.post("/api/ask", json={"document_id": document["document_id"], "question": "What is the total window width?"})
    assert response.status_code == 200
    result = response.json()
    assert result["answer"] == "The two window widths total 2.7 m; installation clearance is unknown."
    assert result["evidence"] == [evidence()]
    for field in ("spoken_answer", "spoken_answer_with_details"):
        assert "2.7 m" in result[field]
        assert "installation clearance is unknown" in result[field]
        assert "Installation clearance" in result[field]
        assert "Check a dimensioned window schedule." in result[field]
        assert "{result}" not in result[field]
    assert [name for name, _ in provider.calls] == ["gate", "answer"]


def test_speech_preparation_failure_preserves_written_answer_and_evidence(tmp_path, monkeypatch):
    def broken_formatter(*args, **kwargs):
        raise RuntimeError("not exposed")
    monkeypatch.setattr("app.main.prepare_spoken_answer", broken_formatter)
    provider = FakeProvider()
    with TestClient(create_app(provider_factory=lambda: provider, storage_root=tmp_path)) as client:
        document = upload(client)
        response = client.post("/api/ask", json={"document_id": document["document_id"], "question": "How many windows?"})
    assert response.status_code == 200
    result = response.json()
    assert result["answer"] == "0 windows"
    assert result["evidence"] == [evidence()]
    assert result["spoken_answer"] is None
    assert result["spoken_answer_with_details"] is None
    assert "not exposed" not in response.text
