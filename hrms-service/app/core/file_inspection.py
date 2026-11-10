"""Checks an uploaded file's real format from its content, not from its name or the browser's claim.

Only formats listed here can be accepted. Each format is recognised by its leading signature and a
structural end marker, so a renamed executable, a truncated file or an HTML file called .pdf is refused.
Adding a format means adding a checker here (and a test); document types may only allow these.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FileFormat:
    extensions: tuple[str, ...]
    content_type: str
    previewable: bool


PDF = FileFormat((".pdf",), "application/pdf", True)
JPEG = FileFormat((".jpg", ".jpeg"), "image/jpeg", True)
PNG = FileFormat((".png",), "image/png", True)

FORMATS = (PDF, JPEG, PNG)
SUPPORTED_EXTENSIONS = tuple(sorted(e for f in FORMATS for e in f.extensions))
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _is_pdf(data: bytes) -> bool:
    # Header within the first 1 KB (per the PDF spec) and an end-of-file marker near the end.
    return b"%PDF-" in data[:1024] and b"%%EOF" in data[-2048:]


def _is_jpeg(data: bytes) -> bool:
    return data[:3] == b"\xff\xd8\xff" and data.rstrip(b"\x00\r\n")[-2:] == b"\xff\xd9"


def _is_png(data: bytes) -> bool:
    return data[:8] == PNG_SIGNATURE and b"IEND" in data[-16:]


_CHECKS = ((PDF, _is_pdf), (JPEG, _is_jpeg), (PNG, _is_png))


def detect(data: bytes) -> FileFormat | None:
    """The format the content really is, or None when it is none of the supported formats."""
    for fmt, check in _CHECKS:
        if check(data):
            return fmt
    return None


def format_for_extension(extension: str) -> FileFormat | None:
    ext = extension.lower()
    return next((f for f in FORMATS if ext in f.extensions), None)


def extension_of(file_name: str) -> str:
    dot = file_name.rfind(".")
    return file_name[dot:].lower() if dot > 0 else ""


def safe_file_name(raw: str | None) -> str:
    """The name shown to users and sent back on download: base name only, no control or path characters."""
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(c for c in name if c.isprintable() and c not in '<>:"|?*').strip(" .")
    if len(name) > 200:
        ext = extension_of(name)
        name = name[: 200 - len(ext)] + ext
    return name or "document"
