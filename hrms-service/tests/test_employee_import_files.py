"""Module 4: template download, server-side .xlsx/.csv reading, and a large (2,000-row) import."""

import io
import time
import zipfile
from datetime import date

from openpyxl import Workbook, load_workbook
from sqlalchemy import func, select

from app.models.employee_model import Employee
from tests.employee_fixtures import org  # noqa: F401
from tests.test_employee_import import BASE, importer, row, run_all

HEADERS = ["Emp ID", "First Name", "Surname", "DOB", "Date of joining", "Dept", "Designation", "Employment type", "Status", "Notes"]


def xlsx(rows: list[list]) -> bytes:
    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


async def read(client, name: str, content: bytes, headers=None):
    return await client.post(f"{BASE}/file-rows", files={"file": (name, content, "application/octet-stream")}, headers=headers or importer())


async def test_templates_are_generated_from_the_field_list(client, org):
    r = await client.get(f"{BASE}/template", params={"format": "csv"}, headers=importer())
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and "employee-import-template.csv" in r.headers["content-disposition"]
    lines = r.content.decode("utf-8-sig").splitlines()
    assert lines[0].startswith("Employee ID,First name,Middle name,Last name") and len(lines) == 2
    r = await client.get(f"{BASE}/template", headers=importer(["hr.employees:import"]))
    wb = load_workbook(io.BytesIO(r.content))
    header = [c.value for c in wb["Employees"][1]]
    assert header[0] == "Employee ID" and "Email" not in header, "the template follows the caller's field permissions"
    notes = {row[0]: row for row in wb["Instructions"].iter_rows(min_row=2, values_only=True)}
    assert notes["Employee ID"][1] == "Yes" and "must be unique" in notes["Employee ID"][3] and notes["Middle name"][1] == "No"


async def test_xlsx_file_is_read_into_rows(client, org):
    content = xlsx([[], HEADERS, ["X-1", "Asha", "Rao", date(1994, 5, 21), "15/01/2024", "QA", "Engineer", "PERM", "active", "ignored"], [], ["X-2", "Bala", None, None, date(2024, 2, 1), "QA", "Engineer", "PERM", "active", None]])
    r = await read(client, "staff.xlsx", content)
    assert r.status_code == 200, r.text
    parsed = r.json()
    assert parsed["headers"] == HEADERS and parsed["unmappedColumns"] == ["Notes"] and parsed["blankRowsIgnored"] == 1
    assert parsed["mapping"]["employeeCode"] == 0 and parsed["mapping"]["personal.lastName"] == 2 and parsed["mapping"]["personal.email"] is None
    assert parsed["missingRequiredFields"] == []
    assert parsed["rows"][0] == {"rowNumber": 3, "values": {"employeeCode": "X-1", "personal.firstName": "Asha", "personal.lastName": "Rao", "personal.dateOfBirth": "1994-05-21",
                                                             "employment.joiningDate": "2024-01-15", "employment.department": "QA", "employment.designation": "Engineer",
                                                             "employment.employmentType": "PERM", "employment.status": "active"}}
    assert parsed["rows"][1]["rowNumber"] == 5 and parsed["rows"][1]["values"]["employment.joiningDate"] == "2024-02-01"
    v = (await client.post(f"{BASE}/validate", json={"rows": parsed["rows"]}, headers=importer())).json()
    assert [x["status"] for x in v["rows"]] == ["warning", "warning"]


async def test_csv_file_is_read_with_bom_and_reports_missing_columns(client, org):
    content = "﻿Employee ID,First name,Joining date\nC-1,Chitra,01.02.2024\nC-2,Dev,2024-02-31\n".encode()
    parsed = (await read(client, "staff.csv", content)).json()
    assert parsed["missingRequiredFields"] == ["Department", "Designation", "Employment type", "Employment status"]
    assert parsed["rows"][0]["values"]["employment.joiningDate"] == "2024-02-01"
    assert parsed["rows"][1]["values"]["employment.joiningDate"] == "2024-02-31", "an invalid date is kept and reported by validation, not dropped"


async def test_bad_files_are_refused(client, org, monkeypatch):
    from app.core.config import get_settings

    async def fails(name, content):
        r = await read(client, name, content)
        assert r.status_code == 422, r.text
        return r.json()["error"]["details"][0]["message"]

    assert await fails("old.xls", b"\xd0\xcf\x11\xe0") == "Unsupported file type. Use .xlsx or .csv."
    assert await fails("fake.xlsx", b"just text") == "This is not a valid .xlsx file. Legacy .xls files are not supported: save as .xlsx or .csv."
    assert await fails("broken.xlsx", b"PK\x03\x04garbage") == "The spreadsheet could not be read. Check that it is a valid .xlsx file (not password-protected)."
    assert await fails("latin1.csv", "Employee ID,Name\nA,Jos\xe9\n".encode("latin-1")) == "Save the CSV file with UTF-8 encoding and try again."
    assert await fails("empty.csv", b"\n\n") == "The file is empty."
    assert await fails("header-only.csv", b"Employee ID\n") == "The file has column headings but no rows."
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/worksheets/sheet1.xml", b"0" * (60 * 1024 * 1024))
    assert await fails("bomb.xlsx", bomb.getvalue()) == "The spreadsheet is too large when unpacked."
    monkeypatch.setattr(get_settings(), "import_max_rows", 2)
    assert await fails("many.csv", b"Employee ID\nA\nB\nC\n") == "The file has 3 rows; at most 2 can be imported at once."
    monkeypatch.setattr(get_settings(), "import_max_file_bytes", 2048)
    r = await read(client, "big.csv", b"Employee ID\n" + b"A\n" * 2000)
    assert r.status_code == 413 and r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert (await read(client, "a.csv", b"Employee ID\nA\n", headers=importer(["hr.employees:view"]))).status_code == 403


async def test_large_import_of_2000_rows(client, db, org):
    """The contract's maximum (2,000 rows): preview and background job, with timings for the report."""
    rows = [row(n, f"BULK-{n:05d}", personal__email=f"bulk{n}@example.com", work__attendanceId=f"B{n}") for n in range(2, 2002)]
    rows[10]["values"]["employeeCode"] = rows[5]["values"]["employeeCode"]  # one duplicate within the file
    rows[20]["values"]["employment.department"] = "Nowhere"  # one invalid row
    t0 = time.perf_counter()
    v = (await client.post(f"{BASE}/validate", json={"rows": rows}, headers=importer())).json()
    t_validate = time.perf_counter() - t0
    assert v["summary"] == {"total": 2000, "valid": 0, "warning": 1998, "duplicate": 1, "error": 1}
    job = (await client.post(BASE, json={"rows": rows, "skipDuplicates": True}, headers=importer())).json()
    assert job["progress"] == {"processed": 0, "total": 2000}
    t0 = time.perf_counter()
    await run_all(db)
    t_import = time.perf_counter() - t0
    done = (await client.get(f"{BASE}/{job['id']}", headers=importer())).json()
    assert done["status"] == "succeeded" and done["summary"] == {"created": 1998, "skipped": 1, "failed": 1} and done["progress"]["processed"] == 2000
    assert {f["rowNumber"] for f in done["failures"]} == {12, 22}
    assert await db.scalar(select(func.count()).select_from(Employee)) == 1998
    print(f"\nLARGE IMPORT: validate 2000 rows {t_validate:.1f}s, import job {t_import:.1f}s")
