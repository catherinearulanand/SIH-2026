"""Strict schema for the supplied synthetic CSV. Adapted from the uploaded importer."""
from . import clock
import csv
import io
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

COLUMNS = (
    "event_id", "site_id", "item_id", "batch_id", "event_type", "quantity",
    "base_unit", "occurred_at", "expiry_date", "source_ref",
)
KINDS = {"OPENING", "RECEIPT", "ISSUE", "QUARANTINE", "RELEASE", "DAMAGE", "EXPIRE"}
MAX_BYTES = 2_000_000
MAX_ROWS = 5000
ID_RE = re.compile(r"^[A-Z0-9_:-]{1,48}$")
REF_RE = re.compile(r"^[A-Za-z0-9_./:-]{1,80}$")
ITEMS = {
    "WATER_1L": {"unit": "BOTTLE", "expiry_required": True},
    "RATIONS_DRY": {"unit": "PACK", "expiry_required": True},
    "BANDAGE_STD": {"unit": "PACK", "expiry_required": True},
}
SITES = {"DEMO_A", "DEMO_B"}
SOURCE_ID = "SIH_SYNTHETIC_CSV"


def parse(csv_text):
    errors = []
    if not isinstance(csv_text, str):
        return [], [{"row": 0, "field": "csv_text", "message": "Expected CSV text"}]
    if len(csv_text.encode("utf-8")) > MAX_BYTES:
        return [], [{"row": 0, "field": "csv_text", "message": "Maximum 2 MB"}]
    if "\x00" in csv_text:
        return [], [{"row": 0, "field": "csv_text", "message": "NUL byte rejected"}]
    try:
        reader = csv.DictReader(io.StringIO(csv_text, newline=""), strict=True)
        if reader.fieldnames != list(COLUMNS):
            return [], [{"row": 1, "field": "header", "message": "Columns must match the published schema exactly"}]
        rows = []
        seen = {}
        for number, raw in enumerate(reader, start=2):
            if number > MAX_ROWS + 1:
                errors.append({"row": number, "field": "csv_text", "message": "Maximum 5000 records"})
                break
            row = {key: (raw.get(key) or "").strip() for key in COLUMNS}
            if None in raw or any(raw.get(key) is None for key in COLUMNS):
                errors.append({"row": number, "field": "columns", "message": "Missing or extra column"})
                continue
            for key in ("event_id", "batch_id"):
                if not ID_RE.fullmatch(row[key]):
                    errors.append({"row": number, "field": key, "message": "Use 1–48 uppercase letters, digits, underscore, colon or hyphen"})
            if row["site_id"] not in SITES:
                errors.append({"row": number, "field": "site_id", "message": "Unknown fictional site"})
            item = ITEMS.get(row["item_id"])
            if not item:
                errors.append({"row": number, "field": "item_id", "message": "Unknown item"})
            elif row["base_unit"] != item["unit"]:
                errors.append({"row": number, "field": "base_unit", "message": f"Expected {item['unit']}"})
            if row["event_type"] not in KINDS:
                errors.append({"row": number, "field": "event_type", "message": "Unsupported event type"})
            try:
                value = Decimal(row["quantity"])
                if not value.is_finite() or value != value.to_integral_value() or not 0 < value <= 10_000_000:
                    raise InvalidOperation
                row["quantity"] = str(int(value))
            except (InvalidOperation, ValueError):
                errors.append({"row": number, "field": "quantity", "message": "Expected positive integer up to 10,000,000"})
            try:
                when = datetime.fromisoformat(row["occurred_at"].replace("Z", "+00:00"))
                if when.tzinfo is None or when.utcoffset() is None:
                    raise ValueError
                if when > clock.utcnow():
                    raise ValueError
                row["occurred_at"] = when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            except ValueError:
                errors.append({"row": number, "field": "occurred_at", "message": "Expected timezone-aware ISO 8601 timestamp"})
            try:
                expiry = date.fromisoformat(row["expiry_date"])
                if row["event_type"] not in ("EXPIRE", "DAMAGE", "QUARANTINE") and row["occurred_at"].endswith("Z") and expiry < date.fromisoformat(row["occurred_at"][:10]):
                    raise ValueError
            except ValueError:
                errors.append({"row": number, "field": "expiry_date", "message": "Expected valid YYYY-MM-DD on or after event date"})
            if not REF_RE.fullmatch(row["source_ref"]):
                errors.append({"row": number, "field": "source_ref", "message": "Expected short plain reference"})
            if row["event_id"] in seen:
                errors.append({"row": number, "field": "event_id", "message": f"Repeated in CSV (first row {seen[row['event_id']]})"})
            seen[row["event_id"]] = number
            rows.append(row)
    except csv.Error as exc:
        errors.append({"row": 0, "field": "csv_text", "message": f"Malformed CSV: {str(exc)[:100]}"})
        rows = []
    if not rows and not errors:
        errors.append({"row": 2, "field": "csv_text", "message": "At least one event is required"})
    return rows, errors
