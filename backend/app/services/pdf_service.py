from app.services.parsers.text_utils import extract_pdf_text

class PDFService:
    @staticmethod
    def extract_text(file_path: str) -> str:
        """
        Extracts raw text from PDF file using PyMuPDF (fitz) with pdfplumber fallback.
        Delegates to centralized extract_pdf_text implementation.
        """
        return extract_pdf_text(file_path)

pdf_service = PDFService()
