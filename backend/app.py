from __future__ import annotations

import csv
import hashlib
import io
import json
import ntpath
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import fitz
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from .models import EditableFields, Extraction, validation_errors
from .providers import ExtractionUnavailable, Settings, extract_live, parse_extraction

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 10 * 1024 * 1024
SUPPORTED = ["application/pdf", "image/png", "image/jpeg"]
# History exposes only the payload keys each event type is known to write.
EVENT_PAYLOAD_KEYS = {
    "extraction": ("provider", "filename", "warnings"),
    "correction": ("changes",),
    "approval": ("status_from", "status_to", "supplier_id"),
    "payment": ("status_from", "status_to"),
}


class DuplicateInvoice(Exception):
    def __init__(self, existing_id: str):
        self.existing_id = existing_id


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    raw_data = Path(os.getenv("INVOICE_DATA_DIR", "data"))
    return Settings(
        provider=os.getenv("INVOICE_PROVIDER", "demo").strip().lower(),
        anthropic_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5").strip(),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip(),
        ollama_model=os.getenv("OLLAMA_MODEL", "").strip(),
        data_dir=raw_data if raw_data.is_absolute() else PROJECT_ROOT / raw_data,
        examples_dir=PROJECT_ROOT / "examples",
    )


def inspect_document(data: bytes) -> tuple[str, str]:
    if not data or len(data) > MAX_BYTES:
        raise HTTPException(422, "Le fichier doit être non vide et ne pas dépasser 10 Mio.")
    if data.startswith(b"%PDF-"):
        try:
            with fitz.open(stream=data, filetype="pdf") as document:
                if document.needs_pass:
                    raise HTTPException(422, "Les PDF protégés par mot de passe ne sont pas pris en charge.")
                if document.page_count < 1 or document.page_count > 10:
                    raise HTTPException(422, "Le PDF doit contenir entre 1 et 10 pages.")
                for page in document:
                    # Force page parsing, rather than trusting only the header.
                    if page.rect.is_empty:
                        raise ValueError("invalid page")
            return "application/pdf", ".pdf"
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(422, "Le PDF est invalide ou illisible.") from exc
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        expected, mime, suffix = "PNG", "image/png", ".png"
    elif data.startswith(b"\xff\xd8\xff"):
        expected, mime, suffix = "JPEG", "image/jpeg", ".jpg"
    else:
        raise HTTPException(422, "Importez un PDF, PNG ou JPEG valide.")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != expected or image.width * image.height > 40_000_000:
                raise ValueError("invalid dimensions or format")
            image.verify()
        # A second open/load catches truncated image data missed by verify.
        with Image.open(io.BytesIO(data)) as image:
            image.load()
        return mime, suffix
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "L’image est invalide, trop grande ou illisible.") from exc


class Store:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.documents = self.directory / "documents"
        self.documents.mkdir(parents=True, exist_ok=True)
        self.database = self.directory / "invoices.sqlite3"
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS suppliers (
                    id TEXT PRIMARY KEY, identity_key TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL, ice TEXT
                );
                CREATE TABLE IF NOT EXISTS invoices (
                    id TEXT PRIMARY KEY, sha256 TEXT UNIQUE NOT NULL,
                    document_name TEXT NOT NULL, mime TEXT NOT NULL,
                    record_json TEXT NOT NULL, supplier_id TEXT REFERENCES suppliers(id)
                );
                CREATE TABLE IF NOT EXISTS invoice_events (
                    id TEXT PRIMARY KEY, invoice_id TEXT NOT NULL REFERENCES invoices(id),
                    event_type TEXT NOT NULL CHECK(event_type IN ('extraction','correction','approval','payment')),
                    occurred_at TEXT NOT NULL, payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS invoice_events_invoice ON invoice_events(invoice_id, occurred_at);
            """)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def all(self) -> list[dict]:
        with self.connect() as connection:
            records = [json.loads(row[0]) for row in connection.execute("SELECT record_json FROM invoices")]
        return sorted(records, key=lambda record: record["created_at"], reverse=True)

    def get(self, invoice_id: str) -> dict:
        with self.connect() as connection:
            row = connection.execute("SELECT record_json FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Facture introuvable.")
        return json.loads(row[0])

    def duplicate(self, sha: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute("SELECT id FROM invoices WHERE sha256 = ?", (sha,)).fetchone()
        return row[0] if row else None

    @staticmethod
    def event(connection: sqlite3.Connection, invoice_id: str, event_type: str, payload: dict) -> None:
        connection.execute("INSERT INTO invoice_events VALUES (?, ?, ?, ?, ?)", (str(uuid4()), invoice_id, event_type, now(), json.dumps(payload, ensure_ascii=False)))

    def insert(self, data: bytes, filename: str, mime: str, suffix: str, fields: Extraction, provider: str) -> dict:
        sha = hashlib.sha256(data).hexdigest()
        record_id, created = str(uuid4()), now()
        record = fields.model_dump()
        record.pop("notes", None)
        # Unknown values remain null. Descriptions and human notes are display strings.
        record["description"] = record.get("description") or ""
        record.update(id=record_id, status="pending_review", provider=provider, filename=filename, notes="", created_at=created, updated_at=created, paid_at=None)
        document_name = sha + suffix
        (self.documents / document_name).write_bytes(data)
        try:
            with self.connect() as connection:
                connection.execute("INSERT INTO invoices VALUES (?, ?, ?, ?, ?, NULL)", (record_id, sha, document_name, mime, json.dumps(record, ensure_ascii=False)))
                self.event(connection, record_id, "extraction", {"provider": provider, "filename": filename, "warnings": record["warnings"]})
        except sqlite3.IntegrityError as exc:
            existing_id = self.duplicate(sha)
            if existing_id:
                raise DuplicateInvoice(existing_id) from exc
            raise
        return record

    def save(self, record: dict, event_type: str | None = None, payload: dict | None = None, approve: bool = False) -> None:
        record["updated_at"] = now()
        with self.connect() as connection:
            supplier_id = None
            if approve:
                identity = "ice:" + record["supplier_ice"] if record.get("supplier_ice") else "name:" + " ".join(record["supplier_name"].casefold().split())
                supplier = connection.execute("SELECT id FROM suppliers WHERE identity_key = ?", (identity,)).fetchone()
                supplier_id = supplier[0] if supplier else str(uuid4())
                connection.execute("INSERT INTO suppliers(id, identity_key, name, ice) VALUES (?, ?, ?, ?) ON CONFLICT(identity_key) DO UPDATE SET name=excluded.name, ice=excluded.ice", (supplier_id, identity, record["supplier_name"], record.get("supplier_ice")))
                connection.execute("UPDATE invoices SET record_json = ?, supplier_id = ? WHERE id = ?", (json.dumps(record, ensure_ascii=False), supplier_id, record["id"]))
            elif record["status"] == "pending_review":
                connection.execute("UPDATE invoices SET record_json = ?, supplier_id = NULL WHERE id = ?", (json.dumps(record, ensure_ascii=False), record["id"]))
            else:
                connection.execute("UPDATE invoices SET record_json = ? WHERE id = ?", (json.dumps(record, ensure_ascii=False), record["id"]))
            if event_type:
                payload = dict(payload or {})
                if approve:
                    payload["supplier_id"] = supplier_id
                self.event(connection, record["id"], event_type, payload)

    def history(self, invoice_id: str) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute("SELECT id, event_type, occurred_at, payload_json FROM invoice_events WHERE invoice_id = ? ORDER BY occurred_at ASC, id ASC", (invoice_id,)).fetchall()
        events = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except ValueError:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            keys = EVENT_PAYLOAD_KEYS.get(row["event_type"], ())
            events.append({"id": row["id"], "event_type": row["event_type"], "occurred_at": row["occurred_at"], "payload": {key: payload[key] for key in keys if key in payload}})
        return events

    def suppliers(self) -> list[dict]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT s.name, s.ice, count(i.id) AS invoice_count FROM suppliers s JOIN invoices i ON i.supplier_id=s.id GROUP BY s.id ORDER BY s.name COLLATE NOCASE")]


def present(record: dict) -> dict:
    result = dict(record)
    result["document_url"] = f"/api/invoices/{record['id']}/document"
    result["validation_errors"] = validation_errors(record)
    today = datetime.now(ZoneInfo("Africa/Casablanca")).date().isoformat()
    result["overdue"] = bool(record["status"] == "validated" and record.get("due_date") and record["due_date"] < today)
    return result


def summary(records: list[dict]) -> dict:
    total = Decimal("0")
    unpaid = Decimal("0")
    for record in records:
        if record.get("currency") == "MAD" and record.get("total_ttc") is not None:
            total += Decimal(record["total_ttc"])
            if record["status"] == "validated":
                unpaid += Decimal(record["total_ttc"])
    return {"invoice_count": len(records), "pending_review": sum(r["status"] == "pending_review" for r in records), "validated": sum(r["status"] == "validated" for r in records), "paid": sum(r["status"] == "paid" for r in records), "total_mad": format(total, ".2f"), "unpaid_mad": format(unpaid, ".2f"), "overdue_count": sum(present(r)["overdue"] for r in records)}


def load_fixtures(settings: Settings) -> list[tuple[str, bytes, Extraction]]:
    try:
        manifest = json.loads((settings.examples_dir / "manifest.json").read_text(encoding="utf-8-sig"))
        if not isinstance(manifest, list) or not manifest:
            raise ValueError("invalid manifest")
        fixtures = []
        for entry in manifest:
            filename = entry["filename"]
            path = (settings.examples_dir / filename).resolve()
            if path.parent != settings.examples_dir.resolve() or not isinstance(filename, str):
                raise ValueError("unsafe filename")
            fields = parse_extraction(json.dumps(entry["fields"]))
            fixtures.append((filename, path.read_bytes(), fields))
        return fixtures
    except (OSError, KeyError, TypeError, ValueError, ExtractionUnavailable) as exc:
        raise ExtractionUnavailable("Les exemples de démonstration sont absents ou invalides.") from exc


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or read_settings()
    store = Store(settings.data_dir)
    application = FastAPI(title="Factures Maroc", version="1.0.0")
    application.state.store = store
    application.state.settings = settings

    @application.exception_handler(DuplicateInvoice)
    async def duplicate_invoice(_request, exc: DuplicateInvoice):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=409, content={"detail": "Ce document a déjà été importé.", "existing_id": exc.existing_id})

    @application.exception_handler(ExtractionUnavailable)
    async def unavailable(_request, exc: ExtractionUnavailable):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @application.get("/api/health")
    def health():
        return {"status": "ok"}

    @application.get("/api/config")
    def configuration():
        return {"provider": settings.provider, "model": settings.model, "configured": settings.configured, "demo": settings.provider == "demo", "max_upload_mb": 10, "supported_types": SUPPORTED, "agency": "Agence Maroc"}

    @application.get("/api/invoices")
    def list_invoices(search: str = "", status: str = "", category: str = ""):
        all_records = store.all()
        search = search.casefold().strip()
        records = [r for r in all_records if (not status or r["status"] == status) and (not category or r.get("category") == category) and (not search or search in " ".join(str(r.get(k) or "") for k in ("supplier_name", "supplier_ice", "invoice_number", "description", "filename")).casefold())]
        return {"items": [present(r) for r in records], "summary": summary(all_records), "suppliers": store.suppliers()}

    @application.post("/api/invoices/upload")
    async def upload(file: UploadFile = File(...)):
        chunks, size = [], 0
        try:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(422, "Le fichier ne doit pas dépasser 10 Mio.")
                chunks.append(chunk)
        finally:
            await file.close()
        data = b"".join(chunks)
        mime, suffix = inspect_document(data)
        sha = hashlib.sha256(data).hexdigest()
        existing = store.duplicate(sha)
        if existing:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=409, content={"detail": "Ce document a déjà été importé.", "existing_id": existing})
        if settings.provider == "demo":
            fixtures = load_fixtures(settings)
            matching = [fields for _, contents, fields in fixtures if hashlib.sha256(contents).hexdigest() == sha]
            if not matching:
                raise ExtractionUnavailable("En mode démonstration, importez un document du dossier examples. Pour vos propres factures, configurez Anthropic ou Ollama.")
            fields = matching[0]
        else:
            fields = await extract_live(data, mime, settings, transport)
        filename = ntpath.basename(file.filename or "facture" + suffix)[:240]
        return present(store.insert(data, filename, mime, suffix, fields, settings.provider))

    @application.post("/api/demo")
    def demo():
        fixtures = load_fixtures(settings)
        # Validate every example before modifying the database.
        inspected = [(filename, data, fields, *inspect_document(data)) for filename, data, fields in fixtures]
        result, imported = [], 0
        for filename, data, fields, mime, suffix in inspected:
            existing = store.duplicate(hashlib.sha256(data).hexdigest())
            if existing:
                result.append(present(store.get(existing)))
            else:
                result.append(present(store.insert(data, filename, mime, suffix, fields, "demo")))
                imported += 1
        return {"items": result, "message": f"{imported} facture(s) fictive(s) importée(s). Les exemples déjà présents ont été conservés."}

    @application.get("/api/export.csv")
    def export():
        output = io.StringIO(newline="")
        writer = csv.writer(output, delimiter=";")
        fields = ["invoice_number", "supplier_name", "supplier_ice", "invoice_date", "due_date", "currency", "subtotal_ht", "tax_amount", "total_ttc", "category", "status", "description", "notes", "paid_at"]
        writer.writerow(["Numéro", "Fournisseur", "ICE", "Date facture", "Échéance", "Devise", "HT", "TVA", "TTC", "Catégorie", "Statut", "Description", "Notes", "Paiement"])
        def safe_cell(value):
            text = str(value) if value is not None else ""
            return "'" + text if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")) or text.startswith(("\t", "\r", "\n")) else text
        for record in store.all():
            writer.writerow([safe_cell(record.get(field)) for field in fields])
        return Response(content=("\ufeff" + output.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="factures-maroc.csv"'})

    @application.get("/api/invoices/{invoice_id}")
    def get_invoice(invoice_id: str):
        return present(store.get(invoice_id))

    @application.get("/api/invoices/{invoice_id}/history")
    def invoice_history(invoice_id: str):
        store.get(invoice_id)
        return {"invoice_id": invoice_id, "events": store.history(invoice_id)}

    @application.patch("/api/invoices/{invoice_id}")
    def update_invoice(invoice_id: str, fields: EditableFields):
        record = store.get(invoice_id)
        if record["status"] == "paid":
            raise HTTPException(409, "Une facture payée ne peut plus être modifiée.")
        changes = {}
        for key, value in fields.model_dump(exclude_unset=True).items():
            if key in ("description", "notes"):
                value = value or ""
            if record.get(key) != value:
                changes[key] = {"before": record.get(key), "after": value}
                record[key] = value
        if changes:
            if any(key != "notes" for key in changes):
                record["status"] = "pending_review"
            store.save(record, "correction", {"changes": changes})
        return present(record)

    @application.post("/api/invoices/{invoice_id}/approve")
    def approve(invoice_id: str):
        record = store.get(invoice_id)
        if record["status"] in ("validated", "paid"):
            return present(record)
        errors = validation_errors(record)
        if errors:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=422, content={"detail": "Corrigez les champs avant de valider la facture.", "errors": errors})
        record["status"] = "validated"
        store.save(record, "approval", {"status_from": "pending_review", "status_to": "validated"}, approve=True)
        return present(record)

    @application.post("/api/invoices/{invoice_id}/payment")
    def payment(invoice_id: str):
        record = store.get(invoice_id)
        if record["status"] == "paid":
            return present(record)
        if record["status"] != "validated":
            raise HTTPException(422, "Validez la facture avant d’enregistrer le paiement.")
        record.update(status="paid", paid_at=now())
        store.save(record, "payment", {"status_from": "validated", "status_to": "paid"})
        return present(record)

    @application.get("/api/invoices/{invoice_id}/document")
    def document(invoice_id: str):
        store.get(invoice_id)
        with store.connect() as connection:
            row = connection.execute("SELECT document_name, mime FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        path = (store.documents / row[0]).resolve()
        if path.parent != store.documents or not path.is_file():
            raise HTTPException(404, "Document introuvable.")
        return FileResponse(path, media_type=row[1], headers={"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff"})

    application.mount("/", StaticFiles(directory=PROJECT_ROOT / "web", html=True, check_dir=False), name="web")
    return application


app = create_app()
