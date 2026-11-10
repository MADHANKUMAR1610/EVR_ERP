"""Server-side .xlsx/.csv support for the import (additions to contract B6, for API clients).

The frontend reads the file in the browser and sends rows as JSON; these helpers let any client do
the same on the server: download a template, and turn a file into the same rows (nothing is stored).

.xlsx safety: the file must be a real ZIP; the uncompressed size and entry count are checked before
opening (zip bombs); openpyxl reads it read-only with defusedxml (no XML entity expansion); macros,
formulas and other sheets are ignored (only cell values of the first worksheet are used).
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date, datetime

import defusedxml  # noqa: F401  (openpyxl uses defusedxml when it is installed)
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

from app.core.config import get_settings
from app.core.errors import PayloadTooLargeError, ValidationFailedError
from app.core.file_inspection import extension_of, safe_file_name
from app.schemas.import_schema import ImportFieldOut, ImportRowIn, ParsedFileOut
from app.services.import_rows import normalize_date

MAX_XLSX_UNCOMPRESSED = 50 * 1024 * 1024
MAX_XLSX_ENTRIES = 1000
MAX_COLUMNS = 100


def _file_error(message: str) -> ValidationFailedError:
    return ValidationFailedError(message, details=[{"field": "file", "message": message}])


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def auto_map(fields: list[ImportFieldOut], headers: list[str]) -> dict[str, int | None]:
    """Header → field, by label, key, last key segment or alias (the frontend's rule)."""
    used: set[int] = set()
    mapping: dict[str, int | None] = {}
    for f in fields:
        candidates = {_norm(x) for x in [f.label, f.key, f.key.split(".")[-1], *f.aliases]}
        index = next((i for i, h in enumerate(headers) if i not in used and _norm(h) in candidates), None)
        if index is not None:
            used.add(index)
        mapping[f.key] = index
    return mapping


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _read_csv(content: bytes) -> list[list[str]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise _file_error("Save the CSV file with UTF-8 encoding and try again.") from None
    if "\x00" in text:
        raise _file_error("This is not a valid CSV file.")
    try:
        return [[c.strip() for c in row] for row in csv.reader(io.StringIO(text))]
    except csv.Error:
        raise _file_error("The CSV file could not be read. Check that it is a valid CSV file.") from None


def _read_xlsx(content: bytes) -> list[list[str]]:
    if not content.startswith(b"PK"):
        raise _file_error("This is not a valid .xlsx file. Legacy .xls files are not supported: save as .xlsx or .csv.")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_XLSX_ENTRIES or sum(e.file_size for e in entries) > MAX_XLSX_UNCOMPRESSED:
                raise _file_error("The spreadsheet is too large when unpacked.")
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except ValidationFailedError:
        raise
    except Exception:  # noqa: BLE001 - any parser failure is a user-facing "cannot read"
        raise _file_error("The spreadsheet could not be read. Check that it is a valid .xlsx file (not password-protected).") from None
    try:
        sheet = workbook.worksheets[0]
        return [[_cell(v) for v in row[:MAX_COLUMNS]] for row in sheet.iter_rows(values_only=True)]
    finally:
        workbook.close()


def parse_file(file_name: str | None, content: bytes | None, fields: list[ImportFieldOut]) -> ParsedFileOut:
    settings = get_settings()
    name = safe_file_name(file_name)
    if content is None:
        raise _file_error("Choose a file to upload.")
    if len(content) > settings.import_max_file_bytes:
        limit = f"{settings.import_max_file_bytes / (1024 * 1024):g} MB"
        raise PayloadTooLargeError(f"The file is larger than {limit}.", details=[{"field": "file", "message": f"The file is larger than {limit}."}])
    extension = extension_of(name)
    if extension == ".csv":
        table = _read_csv(content)
    elif extension == ".xlsx":
        table = _read_xlsx(content)
    else:
        raise _file_error("Unsupported file type. Use .xlsx or .csv.")

    # The first non-empty row holds the column headings; row numbers are the spreadsheet's (header = its row).
    header_index = next((i for i, r in enumerate(table) if any(c for c in r)), None)
    if header_index is None:
        raise _file_error("The file is empty.")
    headers = table[header_index]
    while headers and not headers[-1]:
        headers = headers[:-1]
    mapping = auto_map(fields, headers)
    date_keys = {f.key for f in fields if f.type == "date"}
    rows: list[ImportRowIn] = []
    blank = 0
    for offset, cells in enumerate(table[header_index + 1 :], start=header_index + 2):
        if not any(c for c in cells):
            blank += 1
            continue
        values: dict[str, str] = {}
        for key, index in mapping.items():
            if index is None or index >= len(cells):
                continue
            value = cells[index]
            if key in date_keys and value:
                value = normalize_date(value) or value  # an invalid date is reported by validation, not dropped
            if value:
                values[key] = value[:500]
        rows.append(ImportRowIn(row_number=offset, values=values))
    if len(rows) > settings.import_max_rows:
        raise _file_error(f"The file has {len(rows)} rows; at most {settings.import_max_rows} can be imported at once.")
    if not rows:
        raise _file_error("The file has column headings but no rows.")
    mapped = {i for i in mapping.values() if i is not None}
    return ParsedFileOut(
        file_name=name,
        headers=headers,
        mapping=mapping,
        unmapped_columns=[h for i, h in enumerate(headers) if i not in mapped and h],
        missing_required_fields=[f.label for f in fields if f.required and mapping.get(f.key) is None],
        blank_rows_ignored=blank,
        rows=rows,
    )


def template(fields: list[ImportFieldOut], fmt: str) -> tuple[bytes, str, str]:
    """The import template generated from the same field list the frontend uses."""
    if fmt == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([f.label for f in fields])
        writer.writerow([f.example or "" for f in fields])
        return ("﻿" + buffer.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", "employee-import-template.csv"
    wb = Workbook()
    sheet = wb.active
    sheet.title = "Employees"
    sheet.append([f.label for f in fields])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    notes = wb.create_sheet("Instructions")
    notes.append(["Column", "Required", "Type", "Notes", "Example"])
    for cell in notes[1]:
        cell.font = Font(bold=True)
    for f in fields:
        detail = []
        if f.max_length:
            detail.append(f"at most {f.max_length} characters")
        if f.unique:
            detail.append("must be unique")
        if f.type == "date":
            detail.append("YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY or DD.MM.YYYY")
        if f.type == "reference":
            detail.append("code or name, as configured in HR setup")
        notes.append([f.label, "Yes" if f.required else "No", f.type, "; ".join(detail), f.example or ""])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "employee-import-template.xlsx"
