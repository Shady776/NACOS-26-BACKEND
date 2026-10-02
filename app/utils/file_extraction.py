"""
Pulls plain text out of a submitted file so the AI grader can read it,
regardless of what format the student uploaded — source code, plain text,
PDF, DOCX, or a ZIP of a small project.

This is intentionally conservative about size: AI grading sends the
extracted text straight into a prompt, so an unbounded extraction here
becomes a cost/abuse vector (e.g. a student zipping up a huge dataset
alongside their code). Every path below enforces a character cap.
"""

import io
import zipfile
from typing import Optional

import httpx
from docx import Document
from pypdf import PdfReader

# ── what counts as "plain text we can just decode and read" ──────────────────
# Source code + config/markup formats. Deliberately broad — "any file type,
# including code files" means covering the languages a CS department's
# students will actually submit, not just .py.
TEXT_EXTENSIONS = {
    # plain text / docs
    "txt", "md", "rst", "csv", "log",
    # config / data
    "json", "yaml", "yml", "xml", "toml", "ini", "env",
    # web
    "html", "htm", "css", "scss",
    # code
    "py", "js", "jsx", "ts", "tsx", "java", "c", "h", "cpp", "hpp", "cc",
    "cs", "go", "rb", "php", "swift", "kt", "kts", "rs", "scala", "r",
    "m", "pl", "lua", "dart", "sql", "sh", "bash", "ps1", "asm",
}

PDF_EXTENSIONS = {"pdf"}
DOCX_EXTENSIONS = {"docx"}
ARCHIVE_EXTENSIONS = {"zip"}

SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | PDF_EXTENSIONS | DOCX_EXTENSIONS | ARCHIVE_EXTENSIONS

# Hard caps — protect against huge prompts / decompression-bomb zips.
MAX_EXTRACTED_CHARS = 60_000          # ~enough for a substantial assignment, capped for cost/sanity
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024  # matches the upload size cap in file_validation.py
MAX_ZIP_ENTRY_UNCOMPRESSED_BYTES = 5 * 1024 * 1024   # skip any single absurdly-inflated entry
MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES = 25 * 1024 * 1024  # stop reading the zip once we've seen this much
MAX_ZIP_ENTRIES_READ = 200

# Directories inside a submitted zip that are never source the student wrote
ZIP_SKIP_DIR_PARTS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    ".idea", ".vscode", "dist", "build", ".next",
}


class ExtractionError(Exception):
    """Raised when no usable text could be pulled from the file."""


def _get_extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _truncate(text: str, label: str) -> str:
    if len(text) <= MAX_EXTRACTED_CHARS:
        return text
    return text[:MAX_EXTRACTED_CHARS] + f"\n\n[... truncated — {label} exceeded {MAX_EXTRACTED_CHARS} characters ...]"


async def fetch_file_bytes(url: str) -> bytes:
    """Download a submission file (Cloudinary secure_url) with a hard size cap."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            chunks = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise ExtractionError(
                        f"File exceeds the {MAX_DOWNLOAD_BYTES // (1024 * 1024)}MB download limit for AI grading"
                    )
                chunks.append(chunk)
            return b"".join(chunks)


def _extract_text(content: bytes) -> str:
    return content.decode("utf-8", errors="replace")


def _extract_pdf(content: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(content))
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
    except Exception as e:
        raise ExtractionError(f"Could not read this PDF — it may be corrupted ({e})")
    text = "\n\n".join(pages).strip()
    if not text:
        raise ExtractionError("Could not extract any text from this PDF (it may be a scanned image with no OCR text layer)")
    return text


def _extract_docx(content: bytes) -> str:
    try:
        document = Document(io.BytesIO(content))
        text = "\n".join(p.text for p in document.paragraphs).strip()
    except Exception as e:
        raise ExtractionError(f"Could not read this DOCX — it may be corrupted ({e})")
    if not text:
        raise ExtractionError("This DOCX file appears to be empty")
    return text


def _is_probably_binary(raw: bytes) -> bool:
    # crude but effective: real text files don't contain NUL bytes
    return b"\x00" in raw[:1024]


def _extract_zip(content: bytes) -> str:
    sections = []
    total_uncompressed = 0
    entries_read = 0

    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise ExtractionError("This ZIP file is corrupted or not a valid archive")

    for info in zf.infolist():
        if entries_read >= MAX_ZIP_ENTRIES_READ:
            sections.append(f"\n[... stopped after {MAX_ZIP_ENTRIES_READ} files — archive has more ...]")
            break

        # skip directories
        if info.is_dir():
            continue

        # skip build/dependency/vcs noise so the AI reads the student's actual code
        parts = set(info.filename.replace("\\", "/").split("/"))
        if parts & ZIP_SKIP_DIR_PARTS:
            continue

        ext = _get_extension(info.filename)
        if ext not in TEXT_EXTENSIONS:
            continue  # skip binaries, images, compiled artifacts, etc. inside the zip

        # decompression-bomb guard: check declared uncompressed size before reading
        if info.file_size > MAX_ZIP_ENTRY_UNCOMPRESSED_BYTES:
            continue
        if total_uncompressed + info.file_size > MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES:
            sections.append("\n[... stopped — archive contents exceeded the total size limit for AI grading ...]")
            break

        try:
            raw = zf.read(info)
        except Exception:
            continue

        if _is_probably_binary(raw):
            continue

        total_uncompressed += info.file_size
        entries_read += 1
        sections.append(f"--- {info.filename} ---\n{raw.decode('utf-8', errors='replace')}")

    if not sections:
        raise ExtractionError("No readable source/text files were found inside this ZIP")

    return "\n\n".join(sections)


def extract_gradable_text(content: bytes, filename: str) -> str:
    """
    Extracts plain text from a submission file for the AI grader.
    Raises ExtractionError with a clear, user-facing reason if it can't.
    """
    ext = _get_extension(filename)

    if ext in PDF_EXTENSIONS:
        text = _extract_pdf(content)
        label = "PDF"
    elif ext in DOCX_EXTENSIONS:
        text = _extract_docx(content)
        label = "DOCX"
    elif ext in ARCHIVE_EXTENSIONS:
        text = _extract_zip(content)
        label = "ZIP contents"
    elif ext in TEXT_EXTENSIONS:
        text = _extract_text(content)
        label = "file"
    else:
        raise ExtractionError(
            f"AI grading doesn't support .{ext} files yet. "
            f"Supported: code/text files, PDF, DOCX, and ZIP archives of code."
        )

    return _truncate(text, label)