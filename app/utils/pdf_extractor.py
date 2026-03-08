"""
PDF text extraction utility.
"""

import io
from typing import Optional

from loguru import logger

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None
    logger.warning("pypdf not installed, PDF extraction will not work")


def extract_text_from_pdf(pdf_bytes: bytes, max_pages: int = 10) -> Optional[str]:
    """
    Extract text content from a PDF file.

    Args:
        pdf_bytes: PDF file content as bytes
        max_pages: Maximum number of pages to extract (to limit token usage)

    Returns:
        Extracted text or None if extraction failed
    """
    if PdfReader is None:
        logger.error("pypdf not installed")
        return None

    try:
        pdf_file = io.BytesIO(pdf_bytes)
        reader = PdfReader(pdf_file)

        text_parts = []
        pages_to_read = min(len(reader.pages), max_pages)

        for i in range(pages_to_read):
            page = reader.pages[i]
            page_text = page.extract_text()
            if page_text:
                text_parts.append(f"--- Página {i + 1} ---\n{page_text}")

        if len(reader.pages) > max_pages:
            text_parts.append(
                f"\n[... {len(reader.pages) - max_pages} páginas adicionales no extraídas ...]"
            )

        full_text = "\n\n".join(text_parts)

        # Clean up the text
        full_text = clean_extracted_text(full_text)

        logger.debug(f"Extracted {len(full_text)} chars from PDF ({pages_to_read} pages)")
        return full_text

    except Exception as e:
        logger.error(f"Failed to extract text from PDF: {e}")
        return None


def clean_extracted_text(text: str) -> str:
    """
    Clean extracted PDF text.

    Args:
        text: Raw extracted text

    Returns:
        Cleaned text
    """
    if not text:
        return ""

    # Remove excessive whitespace
    lines = text.split("\n")
    cleaned_lines = []

    for line in lines:
        # Strip trailing/leading whitespace
        line = line.strip()

        # Skip empty lines if the previous line was also empty
        if not line and cleaned_lines and not cleaned_lines[-1]:
            continue

        cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


def is_pdf(content: bytes) -> bool:
    """
    Check if content is a PDF file.

    Args:
        content: File content as bytes

    Returns:
        True if content appears to be a PDF
    """
    return content[:4] == b"%PDF"
