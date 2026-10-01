from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

Category = Literal["Services", "Matériel", "Télécom", "Transport", "Autre"]


def decimal_text(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("Le montant doit être une chaîne décimale.")
    try:
        amount = Decimal(value.strip())
    except InvalidOperation as exc:
        raise ValueError("Montant invalide.") from exc
    if not amount.is_finite() or abs(amount) > Decimal("999999999999.99"):
        raise ValueError("Montant invalide ou trop grand.")
    if amount != amount.quantize(Decimal("0.01")):
        raise ValueError("Utilisez au maximum deux décimales.")
    return format(amount.quantize(Decimal("0.01")), "f")


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supplier_name: str | None
    invoice_number: str | None
    invoice_date: str | None
    subtotal_ht: str | None
    tax_amount: str | None
    total_ttc: str | None


class EditableFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_max_length=4000)
    supplier_name: str | None = None
    supplier_ice: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    due_date: str | None = None
    currency: str | None = None
    subtotal_ht: str | None = None
    tax_amount: str | None = None
    total_ttc: str | None = None
    category: Category | None = None
    description: str | None = None
    notes: str | None = None

    @field_validator("subtotal_ht", "tax_amount", "total_ttc", mode="before")
    @classmethod
    def amounts(cls, value: object) -> str | None:
        return decimal_text(value)

    @field_validator("invoice_date", "due_date")
    @classmethod
    def dates(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("Date attendue au format AAAA-MM-JJ.") from exc
        if parsed.isoformat() != value:
            raise ValueError("Date attendue au format AAAA-MM-JJ.")
        return value

    @field_validator("currency")
    @classmethod
    def currencies(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        value = value.strip().upper()
        if len(value) != 3 or not value.isascii() or not value.isalpha():
            raise ValueError("Devise attendue sur trois lettres, par exemple MAD.")
        return value

    @field_validator("supplier_name", "supplier_ice", "invoice_number", "description", "notes")
    @classmethod
    def strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class Extraction(EditableFields):
    # Required nullable keys prevent an LLM response from silently omitting data.
    supplier_name: str | None
    supplier_ice: str | None
    invoice_number: str | None
    invoice_date: str | None
    due_date: str | None
    currency: str | None
    subtotal_ht: str | None
    tax_amount: str | None
    total_ttc: str | None
    category: Category | None
    description: str | None
    warnings: list[str]
    evidence: Evidence


def extraction_schema() -> dict:
    schema = Extraction.model_json_schema()
    # Notes are human-only and do not belong to the extraction contract.
    schema["properties"].pop("notes", None)
    schema["required"] = [key for key in schema["properties"]]
    # Anthropic structured output accepts only a subset of JSON Schema. Keep
    # application-side Pydantic limits, but do not send unsupported constraints.
    def compatible(node):
        if isinstance(node, dict):
            for key in ("maxLength", "minLength", "maximum", "minimum", "exclusiveMaximum", "exclusiveMinimum", "multipleOf", "maxItems", "minItems"):
                node.pop(key, None)
            for value in node.values():
                compatible(value)
        elif isinstance(node, list):
            for value in node:
                compatible(value)
    compatible(schema)
    return schema


def validation_errors(record: dict) -> list[str]:
    errors: list[str] = []
    required = {
        "supplier_name": "Le fournisseur est obligatoire.",
        "invoice_number": "Le numéro de facture est obligatoire.",
        "invoice_date": "La date de facture est obligatoire.",
        "currency": "La devise est obligatoire.",
        "subtotal_ht": "Le montant HT est obligatoire.",
        "tax_amount": "Le montant de TVA est obligatoire.",
        "total_ttc": "Le montant TTC est obligatoire.",
    }
    for field, message in required.items():
        if record.get(field) is None or record.get(field) == "":
            errors.append(message)
    amounts: dict[str, Decimal] = {}
    for field in ("subtotal_ht", "tax_amount", "total_ttc"):
        if record.get(field) is not None:
            amounts[field] = Decimal(record[field])
            if amounts[field] < 0:
                errors.append("Les montants doivent être positifs ou nuls.")
    if len(amounts) == 3 and abs(amounts["subtotal_ht"] + amounts["tax_amount"] - amounts["total_ttc"]) > Decimal("0.01"):
        errors.append("Le total HT + TVA doit correspondre au TTC (tolérance 0,01).")
    if record.get("invoice_date") and record.get("due_date") and record["due_date"] < record["invoice_date"]:
        errors.append("L’échéance ne peut pas précéder la date de facture.")
    return list(dict.fromkeys(errors))
