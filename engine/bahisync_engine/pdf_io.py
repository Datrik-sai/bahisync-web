"""Opening statement PDFs (including password-protected ones) and reading words.

Text PDFs are read from their text layer. Scanned or image-only PDFs (no text
layer) fall back to OCR, producing the same Word objects so the layout parser
does not care where words came from.

OCR engines, in order:
  1. RapidOCR (PP-OCR models on onnxruntime, pip-installable; used on Vercel).
     The models ship inside the package, so nothing is downloaded and no page
     image leaves the process.
  2. Tesseract + Poppler, when those binaries are installed (Docker image).
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
    """A scanned PDF arrived but no OCR engine is installed."""


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


OCR_DPI = 200
MAX_OCR_PAGES = 12  # keeps a request inside the function time limit (~5 s a page)


def _rapidocr_installed() -> bool:
    try:
        import rapidocr  # noqa: F401
        import pypdfium2  # noqa: F401
    except Exception:
        return False
    return True


def _tesseract_installed() -> bool:
    import shutil

    return bool(shutil.which("tesseract") and shutil.which("pdftoppm"))


def ocr_available() -> bool:
    return _rapidocr_installed() or _tesseract_installed()


class TooManyScannedPages(UnreadablePDF):
    pass


def _ocr_pages(pdf_bytes: bytes) -> tuple[list[PageWords], bool, str]:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as doc:
        n = len(doc.pages)
    if n > MAX_OCR_PAGES:
        raise TooManyScannedPages(
            f"This scanned statement has {n} pages. Scanned PDFs are read with OCR, up to {MAX_OCR_PAGES} pages "
            "at a time: split it by month, or download the digital PDF from net banking."
        )
    if _rapidocr_installed():
        return _ocr_rapid(pdf_bytes)
    return _ocr_tesseract(pdf_bytes)


_RAPID = None


def _rapid_engine():
    """One engine per warm process; loading the models takes about a second."""
    global _RAPID
    if _RAPID is None:
        try:
            import onnxruntime

            onnxruntime.disable_telemetry_events()
        except Exception:
            pass
        from rapidocr import RapidOCR

        _RAPID = RapidOCR(params={"Global.log_level": "error"})
    return _RAPID


def _phrase_words(text: str, x0: float, x1: float, top: float, bottom: float, page: int) -> list[Word]:
    """RapidOCR returns phrases; split them into words with proportional x spans."""
    parts = text.split()
    if len(parts) <= 1:
        return [Word(text.strip(), x0, x1, top, bottom, page)] if text.strip() else []
    unit = (x1 - x0) / max(len(text), 1)
    out: list[Word] = []
    pos = 0
    for part in parts:
        start = text.index(part, pos)
        end = start + len(part)
        out.append(Word(part, x0 + start * unit, x0 + end * unit, top, bottom, page))
        pos = end
    return out


def _ocr_rapid(pdf_bytes: bytes) -> tuple[list[PageWords], bool, str]:
    import numpy as np
    import pypdfium2 as pdfium

    engine = _rapid_engine()
    doc = pdfium.PdfDocument(pdf_bytes)
    scale = 72 / OCR_DPI
    pages: list[PageWords] = []
    first_text = ""
    try:
        for i in range(min(len(doc), MAX_OCR_PAGES)):
            page = doc[i]
            image = np.array(page.render(scale=OCR_DPI / 72).to_pil().convert("RGB"))
            result = engine(image)
            words: list[Word] = []
            texts: list[str] = []
            for box, text, score in zip(result.boxes if result.boxes is not None else [], result.txts or [], result.scores or []):
                if not text or float(score) < 0.5:
                    continue
                xs = [pt[0] for pt in box]
                ys = [pt[1] for pt in box]
                words.extend(_phrase_words(text, min(xs) * scale, max(xs) * scale, min(ys) * scale, max(ys) * scale, i + 1))
                texts.append(text)
            pages.append(PageWords(i + 1, float(page.get_width()), words))
            if i == 0:
                first_text = "\n".join(texts)
    finally:
        doc.close()
    return pages, True, first_text


def _ocr_tesseract(pdf_bytes: bytes) -> tuple[list[PageWords], bool, str]:
    """OCR every page. Requires the tesseract and poppler binaries."""
    import pytesseract
    from pdf2image import convert_from_bytes

    dpi = 300
    images = convert_from_bytes(pdf_bytes, dpi=dpi, last_page=MAX_OCR_PAGES)
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
