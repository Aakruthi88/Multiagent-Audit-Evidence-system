"""
ReportExportService - backend/app/services/report_export_service.py
-------------------------------------------------------------------
Generates deterministic, presentation-ready Big-4 style Audit Workpaper PDFs.
All audit metrics, verification checks, financials, and findings are pulled
strictly from authoritative database records (AuditBundle, VerificationRun,
VerificationCheck, Discrepancy, PO, Invoice, GRN, BankStatement).

LLMs are NEVER called during PDF export. If a pre-existing AI executive summary
is present in the database, it is rendered in a dedicated, clearly separated
section with an authoritative disclaimer.
"""

import io
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy.orm import Session

from app.core.logging import logger
from app.models.models import (
    AuditBundle,
    AuditReport,
    BankStatement,
    BankTransaction,
    Discrepancy,
    Document,
    GRN,
    GRNLineItem,
    Invoice,
    InvoiceLineItem,
    POLineItem,
    PurchaseOrder,
    Report,
    User,
    Vendor,
    VerificationCheck,
    VerificationRun,
)

# ── Color Palette (Deloitte / Corporate Audit Theme) ───────────────────────────
C_NAVY_DARK = colors.HexColor("#0f172a")     # Slate 900
C_NAVY = colors.HexColor("#1e293b")          # Slate 800
C_PRIMARY = colors.HexColor("#312e81")       # Indigo 900
C_ACCENT = colors.HexColor("#4338ca")        # Indigo 700
C_LIGHT_BG = colors.HexColor("#f8fafc")      # Slate 50
C_BORDER = colors.HexColor("#e2e8f0")        # Slate 200
C_BORDER_DARK = colors.HexColor("#cbd5e1")   # Slate 300
C_TEXT_MAIN = colors.HexColor("#0f172a")     # Main text
C_TEXT_MUTED = colors.HexColor("#64748b")    # Slate 500
C_WHITE = colors.HexColor("#ffffff")

# Status / Risk Colors
C_PASS_BG = colors.HexColor("#ecfdf5")       # Green 50
C_PASS_TXT = colors.HexColor("#047857")      # Green 700
C_PASS_BORDER = colors.HexColor("#a7f3d0")   # Green 200

C_FAIL_BG = colors.HexColor("#fef2f2")       # Red 50
C_FAIL_TXT = colors.HexColor("#b91c1c")      # Red 700
C_FAIL_BORDER = colors.HexColor("#fecaca")   # Red 200

C_WARN_BG = colors.HexColor("#fffbeb")       # Amber 50
C_WARN_TXT = colors.HexColor("#b45309")      # Amber 700
C_WARN_BORDER = colors.HexColor("#fde68a")   # Amber 200

C_INFO_BG = colors.HexColor("#eff6ff")       # Blue 50
C_INFO_TXT = colors.HexColor("#1d4ed8")      # Blue 700
C_INFO_BORDER = colors.HexColor("#bfdbfe")   # Blue 200


class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas to compute total page count and add running headers/footers
    with 'Page X of Y' on every page.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count: int):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(C_TEXT_MUTED)

        # Running Header (on pages after the first)
        if self._pageNumber > 1:
            self.drawString(40, 760, "CONFIDENTIAL — MULTI-AGENT AUDIT EVIDENCE WORKPAPER")
            self.setStrokeColor(C_BORDER)
            self.setLineWidth(0.5)
            self.line(40, 752, 572, 752)

        # Running Footer (on all pages)
        self.setStrokeColor(C_BORDER)
        self.setLineWidth(0.5)
        self.line(40, 42, 572, 42)

        gen_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        self.drawString(40, 30, f"Generated: {gen_time} | Deloitte Audit Evidence Standard v1.0")
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(572, 30, page_str)
        self.restoreState()


class ReportExportService:
    """Service to assemble and compile structured database data into a PDF audit workpaper."""

    def __init__(self):
        self._setup_styles()

    def _setup_styles(self):
        base_styles = getSampleStyleSheet()
        self.styles = {}

        self.styles["Title"] = ParagraphStyle(
            "DocTitle",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=C_NAVY_DARK,
            spaceAfter=4,
        )

        self.styles["SubTitle"] = ParagraphStyle(
            "DocSubTitle",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13,
            textColor=C_TEXT_MUTED,
            spaceAfter=12,
        )

        self.styles["SectionHeading"] = ParagraphStyle(
            "SectionHeading",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11.5,
            leading=15,
            textColor=C_NAVY_DARK,
            spaceBefore=12,
            spaceAfter=6,
        )

        self.styles["Body"] = ParagraphStyle(
            "Body",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11.5,
            textColor=C_TEXT_MAIN,
        )

        self.styles["BodyBold"] = ParagraphStyle(
            "BodyBold",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11.5,
            textColor=C_TEXT_MAIN,
        )

        self.styles["TableHead"] = ParagraphStyle(
            "TableHead",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=C_NAVY_DARK,
        )

        self.styles["TableCell"] = ParagraphStyle(
            "TableCell",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=10.5,
            textColor=C_TEXT_MAIN,
        )

        self.styles["TableCellBold"] = ParagraphStyle(
            "TableCellBold",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10.5,
            textColor=C_TEXT_MAIN,
        )

        self.styles["TableCellCode"] = ParagraphStyle(
            "TableCellCode",
            parent=base_styles["Normal"],
            fontName="Courier",
            fontSize=7.5,
            leading=9.5,
            textColor=C_NAVY,
        )

        self.styles["BadgePass"] = ParagraphStyle(
            "BadgePass",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=C_PASS_TXT,
            alignment=1,  # Centered
        )

        self.styles["BadgeFail"] = ParagraphStyle(
            "BadgeFail",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=C_FAIL_TXT,
            alignment=1,
        )

        self.styles["BadgeWarn"] = ParagraphStyle(
            "BadgeWarn",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=C_WARN_TXT,
            alignment=1,
        )

        self.styles["BadgeNA"] = ParagraphStyle(
            "BadgeNA",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=C_TEXT_MUTED,
            alignment=1,
        )

        self.styles["Disclaimer"] = ParagraphStyle(
            "Disclaimer",
            parent=base_styles["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=7.5,
            leading=10,
            textColor=C_TEXT_MUTED,
        )

    def _fmt_curr(self, val: Any) -> str:
        """Format monetary amount in Indian Rupee format."""
        if val is None:
            return "—"
        try:
            d = Decimal(str(val))
            return f"₹{d:,.2f}"
        except Exception:
            return str(val)

    def generate_workpaper_pdf(self, db: Session, bundle: AuditBundle) -> bytes:
        """
        Generate complete, deterministic Audit Workpaper PDF as raw bytes.
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=40,
            rightMargin=40,
            topMargin=46,
            bottomMargin=46,
        )

        story = []

        # ── 1. Fetch Authoritative Data from Database ──────────────────────────
        po = db.query(PurchaseOrder).filter(PurchaseOrder.bundle_id == bundle.bundle_id).first()
        inv = db.query(Invoice).filter(Invoice.bundle_id == bundle.bundle_id).first()
        grn = db.query(GRN).filter(GRN.bundle_id == bundle.bundle_id).first()
        bs = db.query(BankStatement).filter(BankStatement.bundle_id == bundle.bundle_id).first()

        # Latest verification run
        run = (
            db.query(VerificationRun)
            .filter(VerificationRun.bundle_id == bundle.bundle_id)
            .order_by(VerificationRun.started_at.desc())
            .first()
        )

        checks = []
        discrepancies = []
        if run:
            checks = db.query(VerificationCheck).filter(VerificationCheck.run_id == run.run_id).all()
            discrepancies = db.query(Discrepancy).filter(Discrepancy.run_id == run.run_id).all()

        # User who uploaded
        uploader_email = "System / Demo"
        if bundle.uploaded_by:
            u = db.query(User).filter(User.user_id == bundle.uploaded_by).first()
            if u:
                uploader_email = f"{u.name} ({u.email})"

        # Vendor resolution
        vendor_name = "Not Identified"
        if po and po.vendor:
            vendor_name = po.vendor.name_raw
        elif inv and inv.vendor:
            vendor_name = inv.vendor.name_raw

        # Pre-existing AI narrative (if any exists in DB)
        ai_narrative = None
        report_row = (
            db.query(Report)
            .filter(Report.run_id == (run.run_id if run else None))
            .order_by(Report.generated_at.desc())
            .first()
        )
        if report_row and report_row.content_json:
            cj = report_row.content_json
            if isinstance(cj, dict):
                ai_narrative = cj.get("narrative") or cj.get("executive_summary")

        if not ai_narrative:
            audit_rep = (
                db.query(AuditReport)
                .filter(AuditReport.bundle_id == bundle.bundle_id)
                .order_by(AuditReport.generated_at.desc())
                .first()
            )
            if audit_rep and audit_rep.summary:
                ai_narrative = audit_rep.summary

        # ── 2. Header Banner & Title ───────────────────────────────────────────
        header_data = [
            [
                Paragraph("<b>DELOITTE AUDIT ADVISORY SERVICES</b>", self.styles["TableHead"]),
                Paragraph("<b>ENGAGEMENT WORKPAPER REF:</b> " + str(bundle.txn_reference), self.styles["TableCellBold"]),
            ],
            [
                Paragraph("Automated 4-Way Match Verification System", self.styles["Disclaimer"]),
                Paragraph(f"Status: <b>{(bundle.status or 'UNKNOWN').upper()}</b>", self.styles["TableCellBold"]),
            ]
        ]
        t_hdr = Table(header_data, colWidths=[280, 252])
        t_hdr.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), C_LIGHT_BG),
            ("BOX", (0, 0), (-1, -1), 1, C_BORDER_DARK),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(t_hdr)
        story.append(Spacer(1, 10))

        story.append(Paragraph("AUDIT EVIDENCE WORKPAPER", self.styles["Title"]))
        story.append(Paragraph(
            f"Comprehensive 4-Way Match Examination for Transaction Package <b>{bundle.txn_reference}</b>",
            self.styles["SubTitle"]
        ))
        story.append(HRFlowable(width="100%", thickness=1.5, color=C_ACCENT, spaceBefore=2, spaceAfter=10))

        # ── 3. Section A: Engagement / Bundle Overview ──────────────────────────
        story.append(Paragraph("A. ENGAGEMENT & BUNDLE IDENTIFICATION", self.styles["SectionHeading"]))
        
        info_rows = [
            [
                Paragraph("<b>Transaction Ref:</b>", self.styles["TableCellBold"]),
                Paragraph(str(bundle.txn_reference), self.styles["TableCellCode"]),
                Paragraph("<b>Creation Date:</b>", self.styles["TableCellBold"]),
                Paragraph(bundle.created_at.strftime("%Y-%m-%d %H:%M:%S UTC") if bundle.created_at else "—", self.styles["TableCell"]),
            ],
            [
                Paragraph("<b>Bundle UUID:</b>", self.styles["TableCellBold"]),
                Paragraph(str(bundle.bundle_id), self.styles["TableCellCode"]),
                Paragraph("<b>Assigned Auditor:</b>", self.styles["TableCellBold"]),
                Paragraph(uploader_email, self.styles["TableCell"]),
            ],
            [
                Paragraph("<b>Primary Vendor:</b>", self.styles["TableCellBold"]),
                Paragraph(vendor_name, self.styles["TableCellBold"]),
                Paragraph("<b>Evidence Documents:</b>", self.styles["TableCellBold"]),
                Paragraph(f"{len(bundle.documents)} files attached", self.styles["TableCell"]),
            ],
        ]
        t_info = Table(info_rows, colWidths=[95, 175, 105, 157])
        t_info.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#ffffff")),
            ("BOX", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(t_info)
        story.append(Spacer(1, 8))

        # ── 4. Section B: Evidence Completeness Matrix ──────────────────────────
        story.append(Paragraph("B. EVIDENCE COMPLETENESS MATRIX", self.styles["SectionHeading"]))
        comp_data = [
            [
                Paragraph("Document Type", self.styles["TableHead"]),
                Paragraph("Status", self.styles["TableHead"]),
                Paragraph("Identified Reference", self.styles["TableHead"]),
                Paragraph("Document Hash (SHA-256)", self.styles["TableHead"]),
            ]
        ]

        doc_specs = [
            ("Purchase Order (PO)", po is not None, po.po_number if po else "—", "purchase_order"),
            ("Commercial Invoice", inv is not None, inv.invoice_number if inv else "—", "invoice"),
            ("Goods Received Note (GRN)", grn is not None, grn.grn_number if grn else "—", "grn"),
            ("Bank Statement / Payment", bs is not None, bs.account_number if bs else "—", "bank_statement"),
        ]

        for label, present, ref_num, dtype in doc_specs:
            doc_rec = next((d for d in bundle.documents if d.doc_type == dtype), None)
            f_hash = doc_rec.file_hash if doc_rec else "N/A"
            badge = Paragraph("PRESENT", self.styles["BadgePass"]) if present else Paragraph("MISSING", self.styles["BadgeFail"])
            comp_data.append([
                Paragraph(label, self.styles["TableCellBold"]),
                badge,
                Paragraph(str(ref_num), self.styles["TableCellCode"]),
                Paragraph(f_hash[:32] + "..." if len(f_hash) > 32 else f_hash, self.styles["TableCellCode"]),
            ])

        t_comp = Table(comp_data, colWidths=[150, 75, 125, 182])
        t_comp.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), C_LIGHT_BG),
            ("BOX", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(t_comp)
        story.append(Spacer(1, 8))

        # ── 5. Section C: Verification Summary & Risk Assessment ───────────────
        story.append(Paragraph("C. VERIFICATION SUMMARY & RISK ASSESSMENT", self.styles["SectionHeading"]))
        
        passed_c = sum(1 for c in checks if c.status == "pass")
        failed_c = sum(1 for c in checks if c.status == "fail")
        warn_c = sum(1 for c in checks if c.status == "warning")
        total_c = len(checks)
        risk_score = float(run.overall_risk_score) if (run and run.overall_risk_score is not None) else 0.0
        overall_status = (run.overall_status if run else bundle.status or "UNKNOWN").upper()

        status_color_bg = C_PASS_BG if overall_status == "CLEAN" else (C_WARN_BG if overall_status == "FLAGGED" else C_FAIL_BG)
        status_color_txt = C_PASS_TXT if overall_status == "CLEAN" else (C_WARN_TXT if overall_status == "FLAGGED" else C_FAIL_TXT)

        summary_data = [
            [
                Paragraph("<b>Audit Verdict:</b>", self.styles["TableCellBold"]),
                Paragraph(f"<font color='{status_color_txt.hexval()}'><b>{overall_status}</b></font>", self.styles["TableCellBold"]),
                Paragraph("<b>Calculated Risk Score:</b>", self.styles["TableCellBold"]),
                Paragraph(f"<b>{risk_score:.1f} / 100.0</b>", self.styles["TableCellBold"]),
            ],
            [
                Paragraph("<b>Total Checks Executed:</b>", self.styles["TableCellBold"]),
                Paragraph(str(total_c), self.styles["TableCell"]),
                Paragraph("<b>Checks Passed / Warnings:</b>", self.styles["TableCellBold"]),
                Paragraph(f"<font color='{C_PASS_TXT.hexval()}'>{passed_c} Passed</font> / <font color='{C_WARN_TXT.hexval()}'>{warn_c} Warnings</font>", self.styles["TableCell"]),
            ],
            [
                Paragraph("<b>Failed Checks:</b>", self.styles["TableCellBold"]),
                Paragraph(f"<font color='{C_FAIL_TXT.hexval()}'><b>{failed_c} Failed</b></font>", self.styles["TableCellBold"]),
                Paragraph("<b>Total Discrepancies:</b>", self.styles["TableCellBold"]),
                Paragraph(f"<b>{len(discrepancies)} detected</b>", self.styles["TableCellBold"]),
            ],
        ]
        t_summary = Table(summary_data, colWidths=[120, 150, 130, 132])
        t_summary.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), status_color_bg),
            ("BOX", (0, 0), (-1, -1), 1, C_BORDER_DARK),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(t_summary)
        story.append(Spacer(1, 8))

        # ── 6. Section D: Authoritative Financial Ground Truth ─────────────────
        story.append(Paragraph("D. AUTHORITATIVE FINANCIAL GROUND TRUTH", self.styles["SectionHeading"]))
        
        # Pull bank transaction details
        bt_debit = Decimal("0.00")
        bt_ref = "None"
        if bs:
            matched_txns = db.query(BankTransaction).filter(BankTransaction.statement_id == bs.statement_id).all()
            if matched_txns:
                for t in matched_txns:
                    if t.debit_amount:
                        bt_debit += Decimal(str(t.debit_amount))
                        if t.extracted_ref:
                            bt_ref = t.extracted_ref

        fin_data = [
            [
                Paragraph("Financial Dimension", self.styles["TableHead"]),
                Paragraph("Purchase Order", self.styles["TableHead"]),
                Paragraph("Invoice Stated", self.styles["TableHead"]),
                Paragraph("GRN (Pre-Tax)", self.styles["TableHead"]),
                Paragraph("Bank Debit", self.styles["TableHead"]),
            ],
            [
                Paragraph("Subtotal (Pre-Tax)", self.styles["TableCellBold"]),
                Paragraph(self._fmt_curr(po.subtotal if po else None), self.styles["TableCell"]),
                Paragraph(self._fmt_curr(inv.subtotal if inv else None), self.styles["TableCell"]),
                Paragraph(self._fmt_curr(grn.total_amount if grn else None), self.styles["TableCell"]),
                Paragraph("—", self.styles["TableCell"]),
            ],
            [
                Paragraph("Tax Amount (GST/VAT)", self.styles["TableCellBold"]),
                Paragraph(self._fmt_curr(po.tax_amount if po else None), self.styles["TableCell"]),
                Paragraph(self._fmt_curr(inv.tax_amount if inv else None), self.styles["TableCell"]),
                Paragraph("0.00 (Exempt)", self.styles["TableCell"]),
                Paragraph("—", self.styles["TableCell"]),
            ],
            [
                Paragraph("<b>Total Amount</b>", self.styles["TableCellBold"]),
                Paragraph(f"<b>{self._fmt_curr(po.total_amount if po else None)}</b>", self.styles["TableCellBold"]),
                Paragraph(f"<b>{self._fmt_curr(inv.total_amount if inv else None)}</b>", self.styles["TableCellBold"]),
                Paragraph(f"<b>{self._fmt_curr(grn.total_amount if grn else None)}</b>", self.styles["TableCellBold"]),
                Paragraph(f"<b>{self._fmt_curr(bt_debit if bs else None)}</b>", self.styles["TableCellBold"]),
            ]
        ]
        t_fin = Table(fin_data, colWidths=[120, 103, 103, 103, 103])
        t_fin.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), C_LIGHT_BG),
            ("BACKGROUND", (0, 3), (-1, 3), colors.HexColor("#f1f5f9")),
            ("BOX", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(t_fin)
        story.append(Spacer(1, 10))

        # ── 7. Section E: Deterministic Verification Matrix ────────────────────
        story.append(Paragraph("E. DETERMINISTIC VERIFICATION MATRIX (4-WAY MATCH CHECKS)", self.styles["SectionHeading"]))
        
        matrix_data = [
            [
                Paragraph("Check Name", self.styles["TableHead"]),
                Paragraph("Result", self.styles["TableHead"]),
                Paragraph("Expected Value", self.styles["TableHead"]),
                Paragraph("Actual Value", self.styles["TableHead"]),
                Paragraph("Variance", self.styles["TableHead"]),
                Paragraph("Finding / Explanation", self.styles["TableHead"]),
            ]
        ]

        if not checks:
            matrix_data.append([
                Paragraph("No verification checks recorded for this bundle.", self.styles["TableCell"]),
                Paragraph("—", self.styles["TableCell"]),
                Paragraph("—", self.styles["TableCell"]),
                Paragraph("—", self.styles["TableCell"]),
                Paragraph("—", self.styles["TableCell"]),
                Paragraph("Run verification to generate deterministic check results.", self.styles["TableCell"]),
            ])
        else:
            for chk in checks:
                status_str = (chk.status or "not_applicable").lower()
                if status_str == "pass":
                    badge = Paragraph("PASS", self.styles["BadgePass"])
                elif status_str == "fail":
                    badge = Paragraph("FAIL", self.styles["BadgeFail"])
                elif status_str == "warning":
                    badge = Paragraph("WARN", self.styles["BadgeWarn"])
                else:
                    badge = Paragraph("N/A", self.styles["BadgeNA"])

                c_name = (chk.check_type or chk.check_name or "check").replace("_", " ").title()
                exp_v = str(chk.expected_value) if chk.expected_value is not None else "—"
                act_v = str(chk.actual_value) if chk.actual_value is not None else "—"
                var_v = self._fmt_curr(chk.variance) if chk.variance is not None else "—"
                expl = chk.explanation or "—"

                matrix_data.append([
                    Paragraph(f"<b>{c_name}</b>", self.styles["TableCellBold"]),
                    badge,
                    Paragraph(exp_v, self.styles["TableCellCode"]),
                    Paragraph(act_v, self.styles["TableCellCode"]),
                    Paragraph(var_v, self.styles["TableCell"]),
                    Paragraph(expl, self.styles["TableCell"]),
                ])

        t_matrix = Table(matrix_data, colWidths=[105, 45, 80, 80, 55, 167])
        t_matrix.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), C_LIGHT_BG),
            ("BOX", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t_matrix)
        story.append(Spacer(1, 10))

        # ── 8. Section F: Exceptions & Audit Findings ──────────────────────────
        story.append(Paragraph("F. EXCEPTIONS & AUDIT FINDINGS", self.styles["SectionHeading"]))
        
        if not discrepancies:
            no_disc_data = [[
                Paragraph("<b>No Audit Exceptions Detected:</b> All verified dimensions strictly conform to approved procurement policies.", self.styles["TableCellBold"])
            ]]
            t_nd = Table(no_disc_data, colWidths=[532])
            t_nd.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), C_PASS_BG),
                ("BOX", (0, 0), (-1, -1), 0.5, C_PASS_BORDER),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ]))
            story.append(t_nd)
        else:
            disc_table_data = [
                [
                    Paragraph("Category", self.styles["TableHead"]),
                    Paragraph("Severity", self.styles["TableHead"]),
                    Paragraph("Discrepancy Description", self.styles["TableHead"]),
                    Paragraph("Recommended Action", self.styles["TableHead"]),
                ]
            ]
            for d in discrepancies:
                sev = (d.severity or "medium").upper()
                badge_style = self.styles["BadgeFail"] if sev in ("CRITICAL", "HIGH") else self.styles["BadgeWarn"]
                disc_table_data.append([
                    Paragraph(d.category.replace("_", " ").title(), self.styles["TableCellBold"]),
                    Paragraph(sev, badge_style),
                    Paragraph(d.description, self.styles["TableCell"]),
                    Paragraph(d.recommended_action or "Review manually.", self.styles["TableCell"]),
                ])

            t_disc = Table(disc_table_data, colWidths=[95, 55, 200, 182])
            t_disc.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), C_LIGHT_BG),
                ("BOX", (0, 0), (-1, -1), 0.5, C_BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, C_BORDER),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(t_disc)

        story.append(Spacer(1, 10))

        # ── 9. Section G: Bundle Source Documents & Evidence Isolation ────────
        story.append(Paragraph("G. PHYSICAL SOURCE DOCUMENTS (STRICT BUNDLE ISOLATION)", self.styles["SectionHeading"]))
        
        doc_tbl_data = [
            [
                Paragraph("Document Type", self.styles["TableHead"]),
                Paragraph("Original Filename", self.styles["TableHead"]),
                Paragraph("Extraction Status", self.styles["TableHead"]),
                Paragraph("SHA-256 Hash", self.styles["TableHead"]),
            ]
        ]
        for d in bundle.documents:
            fname = d.file_path.split("/")[-1].split("\\")[-1] if d.file_path else f"{d.doc_type}.pdf"
            doc_tbl_data.append([
                Paragraph(d.doc_type.replace("_", " ").title(), self.styles["TableCellBold"]),
                Paragraph(fname, self.styles["TableCellCode"]),
                Paragraph((d.extraction_status or "pending").upper(), self.styles["TableCell"]),
                Paragraph(d.file_hash if d.file_hash else "—", self.styles["TableCellCode"]),
            ])

        t_docs = Table(doc_tbl_data, colWidths=[120, 130, 90, 192])
        t_docs.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), C_LIGHT_BG),
            ("BOX", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(t_docs)
        story.append(Spacer(1, 10))

        # ── 10. Section H: AI-Generated Explanation (If available) ─────────────
        if ai_narrative and len(ai_narrative.strip()) > 0:
            story.append(Paragraph("H. AI-GENERATED EXPLANATION (EXECUTIVE SUMMARY)", self.styles["SectionHeading"]))
            
            ai_box_data = [
                [
                    Paragraph("<b>AI Narrative Analysis:</b>", self.styles["TableCellBold"])
                ],
                [
                    Paragraph(ai_narrative.replace("\n", "<br/>"), self.styles["Body"])
                ],
                [
                    Paragraph(
                        "<b>IMPORTANT AUDIT NOTICE:</b> The above summary was generated by an AI language model for descriptive context. "
                        "All verification results, pass/fail decisions, and financial figures presented in Sections A through G "
                        "are strictly computed by deterministic rules and remain the sole authoritative basis of this workpaper.",
                        self.styles["Disclaimer"]
                    )
                ]
            ]
            t_ai = Table(ai_box_data, colWidths=[532])
            t_ai.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), C_INFO_BG),
                ("BOX", (0, 0), (-1, -1), 1, C_INFO_BORDER),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, C_INFO_BORDER),
                ("LINEBELOW", (0, 1), (-1, 1), 0.5, C_INFO_BORDER),
            ]))
            story.append(t_ai)
            story.append(Spacer(1, 10))

        # ── 11. Section I: Sign-off & Audit Trail Metadata ────────────────────
        signoff_data = [
            [
                Paragraph("<b>Audit Engine Version:</b>", self.styles["TableCellBold"]),
                Paragraph("Deloitte Deterministic Rules v1.0", self.styles["TableCell"]),
                Paragraph("<b>Audit Sign-off:</b>", self.styles["TableCellBold"]),
                Paragraph("__________________________", self.styles["TableCell"]),
            ],
            [
                Paragraph("<b>Verification Run ID:</b>", self.styles["TableCellBold"]),
                Paragraph(str(run.run_id) if run else "—", self.styles["TableCellCode"]),
                Paragraph("<b>Lead Auditor Review:</b>", self.styles["TableCellBold"]),
                Paragraph("__________________________", self.styles["TableCell"]),
            ]
        ]
        t_sign = Table(signoff_data, colWidths=[120, 150, 110, 152])
        t_sign.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), C_LIGHT_BG),
            ("BOX", (0, 0), (-1, -1), 0.5, C_BORDER_DARK),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        
        story.append(KeepTogether([
            Paragraph("I. AUDIT TRAIL METADATA & SIGN-OFF", self.styles["SectionHeading"]),
            t_sign
        ]))

        # ── 12. Build Document with NumberedCanvas ─────────────────────────────
        doc.build(story, canvasmaker=NumberedCanvas)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        return pdf_bytes


report_export_service = ReportExportService()
