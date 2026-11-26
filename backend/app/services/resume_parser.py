"""
Resume Parser Service — Extracts and normalizes text from PDF and DOCX documents.
"""

import io
import os
import re
import zipfile

import docx
import pypdf
import pypdf.errors


# ---------------------------------------------------------------------------
# Constants & Configuration
# ---------------------------------------------------------------------------

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_EXTRACTED_TEXT_CHARS = 100_000
ALLOWED_EXTENSIONS = {".pdf", ".docx"}

# Magic byte signatures
PDF_MAGIC = b"%PDF"
ZIP_MAGIC = b"PK\x03\x04"


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------

class ResumeParserError(Exception):
    """Base exception for resume parsing failures."""
    pass


class UnsupportedFileTypeError(ResumeParserError):
    """Raised when file extension or MIME signature is not supported."""
    pass


class FileTooLargeError(ResumeParserError):
    """Raised when file exceeds the maximum allowed upload size."""
    pass


class EmptyFileError(ResumeParserError):
    """Raised when an uploaded file is empty (0 bytes)."""
    pass


class CorruptedFileError(ResumeParserError):
    """Raised when file structure cannot be read or unzipped."""
    pass


class NoExtractableTextError(ResumeParserError):
    """Raised when document is valid format but contains no extractable text."""
    pass


# ---------------------------------------------------------------------------
# Text Normalization
# ---------------------------------------------------------------------------

def normalize_text(text: str) -> str:
    """
    Clean and normalize extracted resume text without destroying structure.

    - Unifies line breaks (\r\n -> \n)
    - Strips non-printable control characters except standard whitespace
    - Normalizes consecutive blank lines to at most 2
    - Strips whitespace at end of lines
    - Trims outer text
    """
    if not text:
        return ""

    # Unify line breaks
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Clean unprintable control characters (except \n, \t)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    # Strip line-trailing whitespace and collapse internal repeated spaces/tabs
    lines = [re.sub(r"[ \t]+", " ", line).rstrip() for line in text.split("\n")]
    text = "\n".join(lines)

    # Collapse excessive blank lines (3+ into 2)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


# ---------------------------------------------------------------------------
# Format Extractors
# ---------------------------------------------------------------------------

def extract_text_from_pdf(content: bytes) -> str:
    """
    Extract text from a PDF binary payload using pypdf.

    Iterates over all pages, extracting and concatenating text blocks.
    Raises CorruptedFileError if unreadable, or NoExtractableTextError if empty.
    """
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
    except (pypdf.errors.PdfReadError, Exception) as exc:
        raise CorruptedFileError(
            f"Unable to read PDF structure: corrupted or malformed file ({str(exc)})"
        ) from exc

    page_texts = []
    extracted_chars = 0
    try:
        for page in reader.pages:
            try:
                page_text = (page.extract_text() or "").strip()
            except Exception:
                # Continue reading remaining pages even if an individual page has issues
                continue
            if page_text:
                extracted_chars += len(page_text) + (2 if page_texts else 0)
                if extracted_chars > MAX_EXTRACTED_TEXT_CHARS:
                    raise FileTooLargeError("The resume contains too much text.")
                page_texts.append(page_text)
    except FileTooLargeError:
        raise
    except Exception as exc:
        raise CorruptedFileError(f"Error parsing PDF pages: {str(exc)}") from exc

    full_text = "\n\n".join(page_texts).strip()
    if not full_text:
        raise NoExtractableTextError(
            "PDF contains no extractable text. Scanned or image-only PDFs are not supported."
        )

    return normalize_text(full_text)


def extract_text_from_docx(content: bytes) -> str:
    """
    Extract text from a DOCX binary payload using python-docx.

    Extracts paragraphs and tables (common in resumes for skills/education).
    Raises CorruptedFileError if corrupted or NoExtractableTextError if empty.
    """
    try:
        # Bound DOCX expansion before handing XML to python-docx.
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > 2000 or sum(entry.file_size for entry in entries) > 50 * 1024 * 1024:
                raise FileTooLargeError("The expanded document is too large.")
            if any(entry.flag_bits & 1 for entry in entries):
                raise CorruptedFileError("Encrypted documents are not supported.")
        doc = docx.Document(io.BytesIO(content))
    except ResumeParserError:
        raise
    except (zipfile.BadZipFile, Exception) as exc:
        raise CorruptedFileError(
            f"Unable to read DOCX structure: corrupted or invalid archive ({str(exc)})"
        ) from exc

    parts = []

    # Extract all document paragraphs
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            parts.append(text)

    # Extract all table cells
    for table in doc.tables:
        for row in table.rows:
            row_cells = []
            for cell in row.cells:
                cell_text = cell.text.strip()
                if cell_text and cell_text not in row_cells:
                    row_cells.append(cell_text)
            if row_cells:
                parts.append(" | ".join(row_cells))

    full_text = "\n".join(parts).strip()
    if not full_text:
        raise NoExtractableTextError(
            "DOCX document contains no readable text or paragraphs."
        )

    if len(full_text) > MAX_EXTRACTED_TEXT_CHARS:
        raise FileTooLargeError("The resume contains too much text.")
    return normalize_text(full_text)


# ---------------------------------------------------------------------------
# High-Level Parsing Pipeline
# ---------------------------------------------------------------------------

def parse_resume_file(filename: str, content: bytes) -> tuple[str, str]:
    """
    Validate and extract raw text from an uploaded resume file.

    Parameters
    ----------
    filename : str
        Original filename of the upload (e.g., 'resume.pdf').
    content : bytes
        Binary payload of the uploaded file.

    Returns
    -------
    tuple[str, str]
        (normalized_extracted_text, file_type) where file_type is 'pdf' or 'docx'.

    Raises
    ------
    EmptyFileError
        If content is empty (0 bytes).
    FileTooLargeError
        If content exceeds 10 MB.
    UnsupportedFileTypeError
        If extension or signature is not .pdf or .docx.
    CorruptedFileError
        If binary content fails parser decoding.
    NoExtractableTextError
        If file contains no extractable text.
    """
    # 1. Size validations
    if not content or len(content) == 0:
        raise EmptyFileError("Uploaded file is empty (0 bytes).")

    if len(content) > MAX_FILE_SIZE_BYTES:
        raise FileTooLargeError(
            f"File size ({len(content) / (1024 * 1024):.1f} MB) exceeds maximum allowed 10 MB."
        )

    # 2. Extension check
    _, ext = os.path.splitext(filename or "")
    ext_lower = ext.lower()
    if ext_lower not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            f"Unsupported file extension '{ext}'. Only PDF (.pdf) and DOCX (.docx) files are supported."
        )

    # 3. Signature (Magic bytes) & Extraction
    if ext_lower == ".pdf":
        if not content.startswith(PDF_MAGIC):
            raise CorruptedFileError(
                "Invalid PDF file signature. The file does not appear to be a valid PDF document."
            )
        text = extract_text_from_pdf(content)
        return text, "pdf"

    elif ext_lower == ".docx":
        if not content.startswith(ZIP_MAGIC):
            raise CorruptedFileError(
                "Invalid DOCX file signature. The file does not appear to be a valid DOCX document."
            )
        text = extract_text_from_docx(content)
        return text, "docx"

    # Should not reach here due to extension check
    raise UnsupportedFileTypeError(f"Unsupported file format '{ext}'.")

