"""Synthetic files for the document tests. No real employee document is used anywhere in the tests."""

from app.core.file_inspection import PNG_SIGNATURE

PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"
PNG = PNG_SIGNATURE + b"\x00\x00\x00\rIHDR" + b"\x00" * 17 + b"\x00\x00\x00\x00IEND\xaeB`\x82"
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 32 + b"\xff\xd9"
HTML = b"<html><script>alert(1)</script></html>"
EXE = b"MZ\x90\x00" + b"\x00" * 60

DOCS = "/api/v1/hr/employees/{eid}/documents"


def files(name: str, content: bytes, content_type: str = "application/octet-stream") -> dict:
    return {"file": (name, content, content_type)}


async def upload(client, employee_id: str, type_id: str, headers: dict, *, name: str = "offer.pdf", content: bytes = PDF, **fields):
    data = {"documentTypeId": type_id, **{k: v for k, v in fields.items() if v is not None}}
    return await client.post(DOCS.format(eid=employee_id), data=data, files=files(name, content), headers=headers)
