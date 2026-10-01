import asyncio
import csv
import hashlib
import io
import json
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import fitz
import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.app import MAX_BYTES, create_app
from backend.providers import ExtractionUnavailable, Settings, extract_live, parse_extraction


def fields(**updates):
    base = {"supplier_name": "Atlas Fictif", "supplier_ice": None, "invoice_number": "DEMO-001", "invoice_date": "2026-09-01", "due_date": None, "currency": "MAD", "subtotal_ht": "1000.00", "tax_amount": "200.00", "total_ttc": "1200.00", "category": "Services", "description": "Prestation fictive", "warnings": ["Échéance absente : vérifier le document."], "evidence": {"supplier_name": "Atlas Fictif", "invoice_number": "DEMO-001", "invoice_date": "2026-09-01", "subtotal_ht": "1000.00", "tax_amount": "200.00", "total_ttc": "1200.00"}}
    base.update(updates)
    return base


def pdf(pages=1):
    with fitz.open() as document:
        for number in range(pages):
            page = document.new_page()
            page.insert_text((50, 50), f"DEMONSTRATION - FACTURE FICTIVE {number}")
        return document.tobytes()


def png():
    output = io.BytesIO()
    Image.new("RGB", (50, 50), "white").save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def setup(tmp_path):
    examples = tmp_path / "examples"
    examples.mkdir()
    document = pdf()
    (examples / "demo.pdf").write_bytes(document)
    (examples / "manifest.json").write_text(json.dumps([{"filename": "demo.pdf", "fields": fields()}]), encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "data", examples_dir=examples)
    application = create_app(settings)
    with TestClient(application) as client:
        yield client, application, settings, document


def import_invoice(client):
    response = client.post("/api/demo")
    assert response.status_code == 200
    return response.json()["items"][0]


def test_demo_idempotence_documents_and_no_supplier_before_approval(setup):
    client, application, _, document = setup
    invoice = import_invoice(client)
    assert invoice["due_date"] is None
    assert invoice["status"] == "pending_review"
    assert invoice["provider"] == "demo"
    assert invoice["validation_errors"] == []
    assert client.get("/api/invoices").json()["summary"]["unpaid_mad"] == "0.00"
    repeated = import_invoice(client)
    assert repeated["id"] == invoice["id"]
    assert client.get("/api/invoices").json()["suppliers"] == []
    downloaded = client.get(invoice["document_url"])
    assert downloaded.content == document
    assert downloaded.headers["content-type"] == "application/pdf"
    with application.state.store.connect() as connection:
        events = connection.execute("SELECT event_type FROM invoice_events").fetchall()
    assert [row[0] for row in events] == ["extraction"]


def test_lifecycle_corrections_payment_and_audit(setup):
    client, application, _, _ = setup
    invoice = import_invoice(client)
    route = "/api/invoices/" + invoice["id"]
    assert client.post(route + "/payment").status_code == 422
    approved = client.post(route + "/approve").json()
    assert approved["status"] == "validated"
    assert client.get("/api/invoices").json()["suppliers"] == [{"name": "Atlas Fictif", "ice": None, "invoice_count": 1}]
    assert client.patch(route, json={"notes": "Pièce vérifiée"}).json()["status"] == "validated"
    corrected = client.patch(route, json={"supplier_name": "Atlas Corrigé"}).json()
    assert corrected["status"] == "pending_review"
    assert client.get("/api/invoices").json()["suppliers"] == []
    assert client.post(route + "/approve").json()["status"] == "validated"
    paid = client.post(route + "/payment").json()
    assert paid["status"] == "paid" and paid["paid_at"]
    assert client.post(route + "/payment").json()["paid_at"] == paid["paid_at"]
    assert client.patch(route, json={"notes": "Modification refusée"}).status_code == 409
    assert client.get("/api/invoices").json()["summary"]["unpaid_mad"] == "0.00"
    with application.state.store.connect() as connection:
        events = connection.execute("SELECT event_type,payload_json FROM invoice_events ORDER BY occurred_at").fetchall()
    assert [row[0] for row in events] == ["extraction", "approval", "correction", "correction", "approval", "payment"]
    assert json.loads(events[3][1])["changes"]["supplier_name"] == {"before": "Atlas Fictif", "after": "Atlas Corrigé"}


def test_missing_amounts_arithmetic_due_date_and_decimal_precision(setup):
    client, _, _, _ = setup
    invoice = import_invoice(client)
    route = "/api/invoices/" + invoice["id"]
    client.patch(route, json={"total_ttc": None, "supplier_name": None})
    failure = client.post(route + "/approve")
    assert failure.status_code == 422 and len(failure.json()["errors"]) == 2
    client.patch(route, json={"supplier_name": "Atlas", "subtotal_ht": "0.10", "tax_amount": "0.20", "total_ttc": "0.30", "due_date": "2026-08-01"})
    assert "échéance" in client.post(route + "/approve").json()["errors"][0].lower()
    client.patch(route, json={"due_date": None})
    assert client.post(route + "/approve").status_code == 200
    client.patch(route, json={"total_ttc": "0.32"})
    assert client.post(route + "/approve").status_code == 422
    client.patch(route, json={"total_ttc": "0.30", "tax_amount": "-0.20"})
    assert client.post(route + "/approve").status_code == 422
    for bad in ("NaN", "Infinity", "1.001", "abc", 1.2):
        assert client.patch(route, json={"total_ttc": bad}).status_code == 422
    assert client.patch(route, json={"invoice_date": "2026-02-30"}).status_code == 422
    assert client.patch(route, json={"currency": "wrong"}).status_code == 422


def test_sha_duplicate_and_unknown_demo_do_not_fabricate(setup):
    client, _, _, document = setup
    first = client.post("/api/invoices/upload", files={"file": ("renamed.pdf", document, "application/pdf")})
    assert first.status_code == 200
    duplicate = client.post("/api/invoices/upload", files={"file": ("another.pdf", document, "application/pdf")})
    assert duplicate.status_code == 409
    assert duplicate.json()["existing_id"] == first.json()["id"]
    unknown = client.post("/api/invoices/upload", files={"file": ("personal.png", png(), "image/png")})
    assert unknown.status_code == 503
    assert client.get("/api/invoices").json()["summary"]["invoice_count"] == 1


@pytest.mark.parametrize("filename,body", [("fake.pdf", b"hello"), ("fake.png", b"\x89PNG\r\n\x1a\ninvalid"), ("fake.jpg", b"\xff\xd8\xffinvalid"), ("empty.pdf", b""), ("oversize.pdf", b"%PDF-" + b"0" * MAX_BYTES)])
def test_invalid_signature_empty_and_size_limits(setup, filename, body):
    client, _, _, _ = setup
    assert client.post("/api/invoices/upload", files={"file": (filename, body)}).status_code == 422
    assert client.get("/api/invoices").json()["items"] == []


def test_pdf_page_limit_and_password(setup):
    client, _, _, _ = setup
    assert client.post("/api/invoices/upload", files={"file": ("long.pdf", pdf(11))}).status_code == 422
    with fitz.open(stream=pdf(), filetype="pdf") as document:
        locked = document.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="password")
    assert client.post("/api/invoices/upload", files={"file": ("locked.pdf", locked)}).status_code == 422


def test_dashboard_filters_currency_and_csv_injection(setup):
    client, _, _, _ = setup
    invoice = import_invoice(client)
    route = "/api/invoices/" + invoice["id"]
    client.patch(route, json={"supplier_name": "=HYPERLINK(\"bad\")", "currency": "EUR", "due_date": (date.today() - timedelta(days=1)).isoformat(), "notes": "\t=evil()"})
    assert client.get("/api/invoices").json()["summary"]["overdue_count"] == 0
    assert client.post(route + "/approve").status_code == 200
    result = client.get("/api/invoices", params={"search": "missing"}).json()
    assert result["items"] == []
    assert result["summary"]["invoice_count"] == 1
    assert result["summary"]["total_mad"] == "0.00"
    assert result["summary"]["overdue_count"] == 1
    assert len(client.get("/api/invoices", params={"search": "hyperlink", "status": "validated"}).json()["items"]) == 1
    csv_response = client.get("/api/export.csv")
    assert csv_response.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(csv_response.content.decode("utf-8-sig")), delimiter=";"))
    assert rows[1][1].startswith("'=")
    assert rows[1][12].startswith("'=")  # Field whitespace is trimmed before storage.


def test_provider_configuration_is_server_side_and_missing_access_is_503(tmp_path):
    settings = Settings(provider="anthropic", anthropic_key="", data_dir=tmp_path / "data")
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/invoices/upload", files={"file": ("image.png", png())})
        assert response.status_code == 503
        assert not client.get("/api/config").json()["configured"]
    settings = replace(settings, anthropic_key="secret-do-not-expose")
    with TestClient(create_app(settings)) as client:
        assert "secret-do-not-expose" not in client.get("/api/config").text


def test_anthropic_request_and_strict_response_parsing():
    captured = []
    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(fields())}]})
    settings = Settings(provider="anthropic", anthropic_key="test-secret")
    result = asyncio.run(extract_live(pdf(), "application/pdf", settings, httpx.MockTransport(handler)))
    assert result.total_ttc == "1200.00" and result.due_date is None
    body = json.loads(captured[0].content)
    assert captured[0].headers["x-api-key"] == "test-secret"
    assert body["messages"][0]["content"][1]["type"] == "document"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert "notes" not in body["output_config"]["format"]["schema"]["properties"]
    assert len(body["output_config"]["format"]["schema"]["required"]) == 13
    assert "maxLength" not in json.dumps(body["output_config"]["format"]["schema"])


def test_ollama_pdf_pages_and_schema_transport():
    captured = []
    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={"message": {"content": json.dumps(fields())}})
    settings = Settings(provider="ollama", ollama_model="vision-test")
    result = asyncio.run(extract_live(pdf(2), "application/pdf", settings, httpx.MockTransport(handler)))
    body = json.loads(captured[0].content)
    assert str(captured[0].url) == "http://localhost:11434/api/chat"
    assert body["stream"] is False
    assert len(body["messages"][0]["images"]) == 2
    assert body["format"]["additionalProperties"] is False
    assert result.invoice_number == "DEMO-001"


@pytest.mark.parametrize("content", ["not json", json.dumps({**fields(), "unexpected": "bad"}), json.dumps({**fields(), "total_ttc": "NaN"}), json.dumps({**fields(), "invoice_date": "2026-99-99"}), json.dumps({**fields(), "evidence": {}})])
def test_malformed_llm_output_rejected(content):
    with pytest.raises(ExtractionUnavailable):
        parse_extraction(content)


def test_provider_http_error_never_returns_credentials():
    def handler(request):
        return httpx.Response(401, json={"error": "test-secret; internal details"})
    with pytest.raises(ExtractionUnavailable) as failure:
        asyncio.run(extract_live(png(), "image/png", Settings(provider="anthropic", anthropic_key="test-secret"), httpx.MockTransport(handler)))
    assert "secret" not in str(failure.value)


def test_state_survives_application_restart(setup):
    client, _, settings, _ = setup
    invoice = import_invoice(client)
    client.patch("/api/invoices/" + invoice["id"], json={"notes": "Persistant"})
    with TestClient(create_app(settings)) as reopened:
        assert reopened.get("/api/invoices/" + invoice["id"]).json()["notes"] == "Persistant"
        assert reopened.get("/api/invoices/not-found").status_code == 404


def test_null_currency_never_inferred():
    extracted = parse_extraction(json.dumps(fields(currency=None, supplier_ice=None, due_date=None)))
    assert extracted.currency is None
    assert extracted.supplier_ice is None
    assert extracted.due_date is None


def test_supplier_names_collapse_whitespace_and_events_persist(setup):
    client, application, settings, _ = setup
    first = import_invoice(client)
    client.post("/api/invoices/" + first["id"] + "/approve")
    extraction = parse_extraction(json.dumps(fields(supplier_name="ATLAS   FICTIF", invoice_number="DEMO-002")))
    second = application.state.store.insert(pdf(2), "second.pdf", "application/pdf", ".pdf", extraction, "demo")
    assert client.post("/api/invoices/" + second["id"] + "/approve").status_code == 200
    assert len(client.get("/api/invoices").json()["suppliers"]) == 1
    assert client.get("/api/invoices").json()["suppliers"][0]["invoice_count"] == 2
    reopened = create_app(settings)
    with reopened.state.store.connect() as connection:
        events = connection.execute("SELECT invoice_id,event_type FROM invoice_events").fetchall()
    assert len(events) == 4
    assert set(row[0] for row in events) == {first["id"], second["id"]}


def event_count(application):
    with application.state.store.connect() as connection:
        return connection.execute("SELECT count(*) FROM invoice_events").fetchone()[0]


def test_history_lists_events_in_order_with_exact_corrections(setup):
    client, application, settings, _ = setup
    invoice = import_invoice(client)
    assert client.patch(f"/api/invoices/{invoice['id']}", json={"supplier_name": "Atlas Corrigé", "due_date": "2026-10-01"}).status_code == 200
    assert client.post(f"/api/invoices/{invoice['id']}/approve").status_code == 200
    assert client.post(f"/api/invoices/{invoice['id']}/payment").status_code == 200
    before = event_count(application)
    response = client.get(f"/api/invoices/{invoice['id']}/history")
    assert response.status_code == 200
    body = response.json()
    assert body["invoice_id"] == invoice["id"]
    events = body["events"]
    assert [e["event_type"] for e in events] == ["extraction", "correction", "approval", "payment"]
    assert [e["occurred_at"] for e in events] == sorted(e["occurred_at"] for e in events)
    assert all(set(e) == {"id", "event_type", "occurred_at", "payload"} for e in events)
    assert events[0]["payload"] == {"provider": "demo", "filename": "demo.pdf", "warnings": ["Échéance absente : vérifier le document."]}
    assert events[1]["payload"] == {"changes": {"supplier_name": {"before": "Atlas Fictif", "after": "Atlas Corrigé"}, "due_date": {"before": None, "after": "2026-10-01"}}}
    assert events[2]["payload"]["status_from"] == "pending_review" and events[2]["payload"]["status_to"] == "validated" and events[2]["payload"]["supplier_id"]
    assert events[3]["payload"] == {"status_from": "validated", "status_to": "paid"}
    assert event_count(application) == before
    for method in ("post", "patch", "delete"):
        assert getattr(client, method)(f"/api/invoices/{invoice['id']}/history").status_code == 405
    assert event_count(application) == before
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get(f"/api/invoices/{invoice['id']}/history").json() == body


def test_history_isolation_unknown_empty_tie_order_and_no_secret(setup):
    client, application, settings, _ = setup
    first = import_invoice(client)
    store = application.state.store
    second = store.insert(pdf(2), "second.pdf", "application/pdf", ".pdf", parse_extraction(json.dumps(fields(invoice_number="DEMO-002"))), "demo")
    client.patch(f"/api/invoices/{second['id']}", json={"notes": "Vu"})
    first_events = client.get(f"/api/invoices/{first['id']}/history").json()
    second_events = client.get(f"/api/invoices/{second['id']}/history").json()
    assert first_events["invoice_id"] == first["id"] and second_events["invoice_id"] == second["id"]
    assert [e["event_type"] for e in first_events["events"]] == ["extraction"]
    assert [e["event_type"] for e in second_events["events"]] == ["extraction", "correction"]
    assert not {e["id"] for e in first_events["events"]} & {e["id"] for e in second_events["events"]}
    assert client.get("/api/invoices/inconnue/history").status_code == 404
    with store.connect() as connection:
        connection.execute("DELETE FROM invoice_events WHERE invoice_id = ?", (second["id"],))
        stamp = "2026-09-01T10:00:00+00:00"
        for event_id in ("bbbb", "aaaa", "cccc"):
            connection.execute("INSERT INTO invoice_events VALUES (?, ?, 'correction', ?, ?)", (event_id, first["id"], stamp, json.dumps({"changes": {}, "api_key": "x"})))
    assert client.get(f"/api/invoices/{second['id']}/history").json() == {"invoice_id": second["id"], "events": []}
    tied = [e for e in client.get(f"/api/invoices/{first['id']}/history").json()["events"] if e["occurred_at"] == stamp]
    assert [e["id"] for e in tied] == ["aaaa", "bbbb", "cccc"]
    assert all(e["payload"] == {"changes": {}} for e in tied)
    secret_settings = replace(settings, anthropic_key="sk-test-secret")
    with TestClient(create_app(secret_settings)) as secret_client:
        response = secret_client.get(f"/api/invoices/{first['id']}/history")
        assert response.status_code == 200 and "sk-test-secret" not in response.text
