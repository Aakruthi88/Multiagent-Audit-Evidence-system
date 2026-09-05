import fitz  # PyMuPDF
import pdfplumber
from pathlib import Path
from app.core.logging import logger

class PDFService:
    @staticmethod
    def extract_text(file_path: str) -> str:
        """
        Extracts raw text from PDF file using PyMuPDF (fitz) with pdfplumber fallback.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found at {file_path}")

        raw_text = ""
        # 1. Try PyMuPDF (fitz) - fast and reliable
        try:
            doc = fitz.open(file_path)
            pages_text = []
            for page in doc:
                text = page.get_text("text")
                if text and text.strip():
                    pages_text.append(text.strip())
            doc.close()
            raw_text = "\n\n".join(pages_text)
        except Exception as e:
            logger.warning(f"PyMuPDF extraction failed for {file_path}: {e}")

        # 2. Fallback to pdfplumber if PyMuPDF yielded < 20 chars
        if len(raw_text.strip()) < 20:
            try:
                with pdfplumber.open(file_path) as pdf:
                    pages_text = []
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text and text.strip():
                            pages_text.append(text.strip())
                    fallback_text = "\n\n".join(pages_text)
                    if len(fallback_text.strip()) > len(raw_text.strip()):
                        raw_text = fallback_text
            except Exception as e:
                logger.warning(f"pdfplumber extraction failed for {file_path}: {e}")

        logger.info(f"Extracted {len(raw_text)} characters from {path.name}")
        return raw_text.strip()

pdf_service = PDFService()
