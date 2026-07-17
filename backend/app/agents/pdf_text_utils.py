"""
Shared PDF -> text helper for the document-validation agents
(resume_validation_agent, bank_details_validation_agent,
ssn_validation_agent, signature_validation_agent).

Tries normal text extraction first (pdfplumber). If a page has no
extractable text (i.e. it's a scanned image, like the SSN-proof PDFs),
falls back to rendering that page and running OCR (easyocr) on it --
same approach as Mohan's original ssn_numeber_check.py script, just
made reusable instead of hardcoded to one file.

easyocr is loaded lazily and only once per process (it's a heavyweight
model load), so agents that never hit a scanned document never pay for it.
"""
import io
import pdfplumber
import fitz  # PyMuPDF -- only used for rendering pages for OCR
from PIL import Image
import numpy as np

_ocr_reader = None


def _get_ocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr
        _ocr_reader = easyocr.Reader(["en"], gpu=False)
    return _ocr_reader


def extract_text(pdf_path: str) -> str:
    """Returns all extractable text from the PDF, running OCR on any
    page that has no embedded text layer (scanned/flattened pages)."""
    full_text = ""

    with pdfplumber.open(pdf_path) as pdf:
        needs_ocr_pages = []
        for i, page in enumerate(pdf.pages):
            page_text = page.extract_text()
            if page_text and page_text.strip():
                full_text += page_text + "\n"
            else:
                needs_ocr_pages.append(i)

    if needs_ocr_pages:
        doc = fitz.open(pdf_path)
        reader = _get_ocr_reader()
        for i in needs_ocr_pages:
            page = doc[i]
            pix = page.get_pixmap(matrix=fitz.Matrix(3, 3))
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            result = reader.readtext(np.array(img), detail=0)
            full_text += " ".join(result) + "\n"
        doc.close()

    return full_text
