"""PDF text extraction and input validation helpers."""
import re

import PyPDF2


def extract_text_from_pdf(pdf_file) -> str:
    """Extract selectable text from a PDF. Scanned PDFs need OCR separately."""
    try:
        reader = PyPDF2.PdfReader(pdf_file, strict=False)
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:
                raise ValueError("This PDF is password-protected. Upload an unlocked PDF.") from exc
        pages = []
        for page in reader.pages:
            page_text = page.extract_text() or ""
            if page_text.strip():
                pages.append(page_text)
        text = "\n".join(pages).strip()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Could not read this PDF. Please upload a valid, non-corrupted PDF.") from exc
    if not text:
        raise ValueError("No selectable text was found. If this is a scanned PDF, run OCR first or upload a text-based PDF.")
    return text


def clean_text(text: str) -> str:
    """Normalize whitespace while preserving readable punctuation and casing."""
    text = (text or "").replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
