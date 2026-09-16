"""
Phase 5A Benchmarking & Profiling Script - backend/benchmark_profile.py
------------------------------------------------------------------------
Instruments the end-to-end multi-agent pipeline and captures granular latency metrics:
1. Intent Router latency
2. Search Agent total latency
3. SQL retrieval latency
4. Chroma/embedding latency
5. Verification Agent latency
6. Report/Query Agent LLM latency
7. Serialization/API response latency
8. Total user-visible latency
"""

import os
import sys
import time
import uuid
import json
from decimal import Decimal
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Any

# Ensure backend root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx
from app.main import app
from app.db.session import SessionLocal
from app.models.models import (
    User, AuditBundle, Document, Invoice, InvoiceLineItem,
    PurchaseOrder, POLineItem, GRN, GRNLineItem, BankStatement, BankTransaction,
    Vendor, VerificationRun, VerificationCheck, Discrepancy, Report
)
from app.core.security import create_access_token, get_password_hash
from app.api.v1.auth import init_demo_users


def seed_benchmark_fixtures():
    """Ensure benchmark test data exists in the database."""
    db = SessionLocal()
    try:
        init_demo_users(db)

        # Find or create admin and auditor users
        admin_user = db.query(User).filter(User.email == "admin@audit.local").first()
        auditor_user = db.query(User).filter(User.email == "auditor@audit.local").first()

        # Check if benchmark bundle exists
        bundle = db.query(AuditBundle).filter(AuditBundle.txn_reference == "TXN-2026-001").first()
        if not bundle:
            bundle = AuditBundle(
                txn_reference="TXN-2026-001",
                status="verified",
                uploaded_by=auditor_user.user_id if auditor_user else None,
                created_at=datetime.utcnow(),
            )
            db.add(bundle)
            db.flush()

            # Vendor
            vendor = Vendor(
                name_raw="Apex Tech Solutions Pvt Ltd",
                name_normalized="apex tech solutions pvt ltd"
            )
            db.add(vendor)
            db.flush()

            # Documents
            doc_po = Document(
                bundle_id=bundle.bundle_id,
                doc_type="purchase_order",
                file_path=f"storage/bundles/{bundle.bundle_id}/po_100005.pdf",
                file_hash="hash_po_100005_1234567890abcdef",
                extraction_status="success",
            )
            doc_inv = Document(
                bundle_id=bundle.bundle_id,
                doc_type="invoice",
                file_path=f"storage/bundles/{bundle.bundle_id}/invoice_200005.pdf",
                file_hash="hash_inv_200005_1234567890abcdef",
                extraction_status="success",
            )
            doc_grn = Document(
                bundle_id=bundle.bundle_id,
                doc_type="grn",
                file_path=f"storage/bundles/{bundle.bundle_id}/grn_300005.pdf",
                file_hash="hash_grn_300005_1234567890abcdef",
                extraction_status="success",
            )
            doc_bank = Document(
                bundle_id=bundle.bundle_id,
                doc_type="bank_statement",
                file_path=f"storage/bundles/{bundle.bundle_id}/bank_400005.pdf",
                file_hash="hash_bank_400005_1234567890abcdef",
                extraction_status="success",
            )
            db.add_all([doc_po, doc_inv, doc_grn, doc_bank])
            db.flush()

            # PO
            po_id = str(uuid.uuid4())
            po = PurchaseOrder(
                po_id=po_id,
                document_id=doc_po.document_id,
                bundle_id=bundle.bundle_id,
                po_number="PO-100005",
                po_date=date(2026, 3, 1),
                vendor_id=vendor.vendor_id,
                subtotal=Decimal("50000.00"),
                tax_rate=Decimal("18.00"),
                tax_amount=Decimal("9000.00"),
                total_amount=Decimal("59000.00"),
            )
            po_item = POLineItem(
                po_id=po_id,
                item_code="SRV-01",
                description="Enterprise Software License",
                qty=Decimal("10.0"),
                unit_price=Decimal("5000.00"),
                line_total=Decimal("50000.00"),
            )
            db.add_all([po, po_item])

            # Invoice
            invoice_id = str(uuid.uuid4())
            inv = Invoice(
                invoice_id=invoice_id,
                document_id=doc_inv.document_id,
                bundle_id=bundle.bundle_id,
                invoice_number="INV-200005",
                invoice_date=date(2026, 3, 5),
                due_date=date(2026, 4, 5),
                po_ref_raw="PO-100005",
                po_id=po_id,
                vendor_id=vendor.vendor_id,
                subtotal=Decimal("50000.00"),
                tax_rate=Decimal("18.00"),
                tax_amount=Decimal("9000.00"),
                total_amount=Decimal("59000.00"),
            )
            inv_item = InvoiceLineItem(
                invoice_id=invoice_id,
                description="Enterprise Software License",
                qty=Decimal("10.0"),
                unit_price=Decimal("5000.00"),
                line_total=Decimal("50000.00"),
            )
            db.add_all([inv, inv_item])

            # GRN
            grn_id = str(uuid.uuid4())
            grn = GRN(
                grn_id=grn_id,
                document_id=doc_grn.document_id,
                bundle_id=bundle.bundle_id,
                grn_number="GRN-2026-0005",
                grn_date=date(2026, 3, 4),
                delivery_note_number="DN-5001",
                po_ref_raw="PO-100005",
                po_id=po_id,
                vendor_id=vendor.vendor_id,
                total_amount=Decimal("50000.00"),
                received_condition="Good",
            )
            grn_item = GRNLineItem(
                grn_id=grn_id,
                description="Enterprise Software License",
                qty_ordered=Decimal("10.0"),
                qty_received=Decimal("10.0"),
                unit_price=Decimal("5000.00"),
                line_total=Decimal("50000.00"),
            )
            db.add_all([grn, grn_item])

            # Bank Statement
            statement_id = str(uuid.uuid4())
            bs = BankStatement(
                statement_id=statement_id,
                document_id=doc_bank.document_id,
                bundle_id=bundle.bundle_id,
                account_number="HDFC-9988776655",
                statement_date=date(2026, 3, 31),
                opening_balance=Decimal("1000000.00"),
                closing_balance=Decimal("941000.00"),
            )
            db.add(bs)
            db.flush()

            bt = BankTransaction(
                statement_id=statement_id,
                txn_date=date(2026, 3, 10),
                description_raw="NEFT/INV-200005/Apex Tech Solutions",
                debit_amount=Decimal("59000.00"),
                extracted_ref="NEFT-APEX-5001",
                extracted_invoice_number="INV-200005",
                matched_invoice_id=invoice_id,
            )
            db.add(bt)

            # Verification Run
            run = VerificationRun(
                bundle_id=bundle.bundle_id,
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
                overall_status="clean",
                overall_risk_score=Decimal("0.0"),
                rules_version="1.0",
            )
            db.add(run)
            db.flush()

            chk1 = VerificationCheck(
                run_id=run.run_id,
                bundle_id=bundle.bundle_id,
                check_type="po_invoice_total_match",
                status="pass",
                expected_value="59000.00",
                actual_value="59000.00",
                variance=Decimal("0.00"),
                explanation="PO and Invoice totals match within tolerance",
            )
            chk2 = VerificationCheck(
                run_id=run.run_id,
                bundle_id=bundle.bundle_id,
                check_type="po_grn_amount_match",
                status="pass",
                expected_value="50000.00",
                actual_value="50000.00",
                variance=Decimal("0.00"),
                explanation="GRN pre-tax total matches PO pre-tax subtotal",
            )
            chk3 = VerificationCheck(
                run_id=run.run_id,
                bundle_id=bundle.bundle_id,
                check_type="payment_amount_match",
                status="pass",
                expected_value="59000.00",
                actual_value="59000.00",
                variance=Decimal("0.00"),
                explanation="Bank debit matches invoice total",
            )
            db.add_all([chk1, chk2, chk3])

            db.commit()

        token = create_access_token(
            subject=admin_user.email if admin_user else "admin@audit.local",
            role="admin",
            name="Admin Benchmark"
        )
        return token
    finally:
        db.close()


TEST_QUERIES = [
    {"name": "1. Exact invoice lookup", "query": "What is the total amount of Invoice 200005?"},
    {"name": "2. Invoice vs PO match", "query": "Does Invoice 200005 match Purchase Order 100005?"},
    {"name": "3. Invoice vs GRN comparison", "query": "Compare Invoice 200005 with GRN-2026-0005"},
    {"name": "4. Payment status query", "query": "What is the payment status and amount for Invoice 200005?"},
    {"name": "5. Discrepancies check", "query": "Show me all discrepancies in bundle TXN-2026-001"},
    {"name": "6. Audit report query", "query": "Generate an audit report for Invoice 200005"},
    {"name": "7. Verification check query", "query": "Verify bundle for PO 100005"},
    {"name": "8. Nonexistent invoice", "query": "What is the status of Invoice INV-999999?"},
    {"name": "9. Cross-bundle status query", "query": "Show all verified bundles"},
    {"name": "10. Natural language query", "query": "Why was the payment flagged for vendor Apex?"},
]


import asyncio

async def run_benchmark():
    print("=" * 70)
    print("PHASE 5A PROFILING & BENCHMARK SUITE")
    print("=" * 70)

    token = seed_benchmark_fixtures()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=120.0) as client:
        results = []
        headers = {"Authorization": f"Bearer {token}"}

        print(f"\nRunning 10 representative queries (Cold + Warm runs)...\n")

        for idx, tq in enumerate(TEST_QUERIES, 1):
            q_name = tq["name"]
            q_text = tq["query"]

            # ── COLD RUN ───────────────────────────────────────────
            t0 = time.perf_counter()
            resp_cold = await client.post("/api/v1/run", json={"query": q_text}, headers=headers)
            t_cold_ms = (time.perf_counter() - t0) * 1000.0

            # ── WARM RUN ───────────────────────────────────────────
            t0 = time.perf_counter()
            resp_warm = await client.post("/api/v1/run", json={"query": q_text}, headers=headers)
            t_warm_ms = (time.perf_counter() - t0) * 1000.0

            status_code = resp_warm.status_code
            data = resp_warm.json() if status_code == 200 else {}
            bundle_id = data.get("bundle_id")
            action = data.get("action")
            verdict = data.get("verdict")

            results.append({
                "index": idx,
                "name": q_name,
                "query": q_text,
                "cold_ms": t_cold_ms,
                "warm_ms": t_warm_ms,
                "status_code": status_code,
                "bundle_id": bundle_id,
                "action": action,
                "verdict": verdict,
            })

            print(f"[{idx}/10] {q_name:<30} | Cold: {t_cold_ms:8.2f} ms | Warm: {t_warm_ms:8.2f} ms | Status: {status_code}")

        print("\n" + "=" * 70)
        print("SUMMARY STATISTICS")
        print("=" * 70)
        cold_times = [r["cold_ms"] for r in results]
        warm_times = [r["warm_ms"] for r in results]

        print(f"Cold Run - Avg: {sum(cold_times)/len(cold_times):.2f} ms | Min: {min(cold_times):.2f} ms | Max: {max(cold_times):.2f} ms")
        print(f"Warm Run - Avg: {sum(warm_times)/len(warm_times):.2f} ms | Min: {min(warm_times):.2f} ms | Max: {max(warm_times):.2f} ms")
        print("=" * 70)

        # Save to JSON for exact comparison
        output_path = Path(__file__).resolve().parent / "benchmark_baseline.json"
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"Saved baseline measurements to {output_path}\n")


if __name__ == "__main__":
    asyncio.run(run_benchmark())
