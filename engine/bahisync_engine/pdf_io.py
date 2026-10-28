"""Opening statement PDFs (including password-protected ones) and reading words.

Text PDFs are read from their text layer. Scanned PDFs (no text layer) fall back
to OCR with Tesseract, producing the same Word objects so the layout parser
does not care where words came from.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import pdfplumber
import pikepdf

from .models import Word


class PasswordRequired(Exception):
    """The PDF is encrypted and no (or a wrong) password was given."""


class UnreadablePDF(Exception):
    pass


class ScannedUnsupported(Exception):
    """A scanned PDF arrived but OCR tools (tesseract/poppler) aren't installed."""


@dataclass
class PageWords:
    page: int
    width: float
    words: list[Word]


def decrypt(pdf_bytes: bytes, password: str | None) -> bytes:
    """Return an unencrypted copy of the PDF bytes."""
    try:
        with pikepdf.open(io.BytesIO(pdf_bytes), password=password or "") as pdf:
            if not pdf.is_encrypted:
                return pdf_bytes
            out = io.BytesIO()
            pdf.save(out)
            return out.getvalue()
    except pikepdf.PasswordError as exc:
        raise PasswordRequired("This statement is password-protected.") from exc
    except pikepdf.PdfError as exc:
        raise UnreadablePDF(f"Not a readable PDF: {exc}") from exc


def read_words(pdf_bytes: bytes, ocr: bool = True) -> tuple[list[PageWords], bool, str]:
    """Return (pages, used_ocr, first_page_text)."""
    pages: list[PageWords] = []
    first_text = ""
    try:
        doc = pdfplumber.open(io.BytesIO(pdf_bytes))
    except Exception as exc:  # pdfplumber raises several types
        raise UnreadablePDF(f"Not a readable PDF: {exc}") from exc

    with doc:
        for i, page in enumerate(doc.pages, start=1):
            raw = page.extract_words(keep_blank_chars=False, use_text_flow=False, x_tolerance=1.5)
            words = [
                Word(w["text"], float(w["x0"]), float(w["x1"]), float(w["top"]), float(w["bottom"]), i)
                for w in raw
            ]
            pages.append(PageWords(i, float(page.width), words))
            if i == 1:
                first_text = page.extract_text() or ""

    if sum(len(p.words) for p in pages) >= 20 or not ocr:
        return pages, False, first_text

    if not ocr_available():
        raise ScannedUnsupported(
            "This looks like a scanned statement. Scanned PDFs aren't supported online yet; "
            "download the statement from net banking as a PDF instead."
        )
    return _ocr_pages(pdf_bytes)


def ocr_available() -> bool:
    import shutil

    return bool(shutil.which("tesseract") and shutil.which("pdftoppm"))


def _ocr_pages(pdf_bytes: bytes) -> tuple[list[PageWords], bool, str]:
    """OCR every page. Requires the tesseract and poppler binaries."""
    import pytesseract
    from pdf2image import convert_from_bytes

    dpi = 300
    images = convert_from_bytes(pdf_bytes, dpi=dpi)
    scale = 72 / dpi  # convert pixels back to PDF points so thresholds stay the same
    pages: list[PageWords] = []
    first_text = ""
    for i, img in enumerate(images, start=1):
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, config="--psm 6")
        words: list[Word] = []
        for j, text in enumerate(data["text"]):
            text = (text or "").strip()
            if not text or float(data["conf"][j]) < 30:
                continue
            x0 = data["left"][j] * scale
            top = data["top"][j] * scale
            words.append(
                Word(text, x0, x0 + data["width"][j] * scale, top, top + data["height"][j] * scale, i)
            )
        pages.append(PageWords(i, img.width * scale, words))
        if i == 1:
            first_text = pytesseract.image_to_string(img)
    return pages, True, first_text
