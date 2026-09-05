import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Text, Numeric, Date, DateTime, Boolean,
    ForeignKey, UniqueConstraint, Index, JSON, Float, Integer
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.types import TypeDecorator, CHAR
from sqlalchemy.orm import relationship
from app.db.base import Base

class GUID(TypeDecorator):
    """Platform-independent GUID type.
    Uses PostgreSQL's UUID type, otherwise uses CHAR(36).
    """
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        else:
            return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == 'postgresql':
            return str(value)
        else:
            if not isinstance(value, uuid.UUID):
                return str(uuid.UUID(value))
            else:
                return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        else:
            if not isinstance(value, uuid.UUID):
                return uuid.UUID(value)
            else:
                return value

class User(Base):
    __tablename__ = 'users'

    user_id = Column(GUID, primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default='auditor')
    created_at = Column(DateTime, default=datetime.utcnow)

class Vendor(Base):
    __tablename__ = 'vendors'

    vendor_id = Column(GUID, primary_key=True, default=uuid.uuid4)
    name_raw = Column(Text, nullable=False)
    name_normalized = Column(Text, nullable=False, index=True)
    address = Column(Text, nullable=True)
    phone = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class AuditBundle(Base):
    __tablename__ = 'audit_bundles'

    bundle_id = Column(GUID, primary_key=True, default=uuid.uuid4)
    txn_reference = Column(String, unique=True, nullable=False)
    status = Column(String, nullable=False, default='uploaded')  # uploaded|extracting|verifying|investigating|reported|failed
    uploaded_by = Column(GUID, ForeignKey('users.user_id'), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    documents = relationship("Document", back_populates="bundle", cascade="all, delete-orphan")

class Document(Base):
    __tablename__ = 'documents'

    document_id = Column(GUID, primary_key=True, default=uuid.uuid4)
    bundle_id = Column(GUID, ForeignKey('audit_bundles.bundle_id', ondelete='CASCADE'), nullable=False)
    doc_type = Column(String, nullable=False)  # purchase_order|invoice|grn|bank_statement
    file_path = Column(Text, nullable=False)
    file_hash = Column(String, nullable=False)
    raw_text = Column(Text, nullable=True)
    extraction_status = Column(String, default='pending')  # pending|success|low_confidence|failed
    extraction_confidence = Column(Float, nullable=True)
    extraction_model = Column(String, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('bundle_id', 'doc_type', name='uq_bundle_doc_type'),
    )

    bundle = relationship("AuditBundle", back_populates="documents")
    purchase_order = relationship("PurchaseOrder", back_populates="document", uselist=False, cascade="all, delete-orphan")
    invoice = relationship("Invoice", back_populates="document", uselist=False, cascade="all, delete-orphan")
    grn = relationship("GRN", back_populates="document", uselist=False, cascade="all, delete-orphan")
    bank_statement = relationship("BankStatement", back_populates="document", uselist=False, cascade="all, delete-orphan")

class PurchaseOrder(Base):
    __tablename__ = 'purchase_orders'

    po_id = Column(GUID, primary_key=True, default=uuid.uuid4)
    document_id = Column(GUID, ForeignKey('documents.document_id', ondelete='CASCADE'), unique=True, nullable=False)
    bundle_id = Column(GUID, ForeignKey('audit_bundles.bundle_id'), nullable=False)
    po_number = Column(String, nullable=False, index=True)
    po_date = Column(Date, nullable=True)
    vendor_id = Column(GUID, ForeignKey('vendors.vendor_id'), nullable=True)
    requisitioner = Column(String, nullable=True)
    shipping_terms = Column(String, nullable=True)
    subtotal = Column(Numeric(14, 2), nullable=False, default=0.0)
    tax_rate = Column(Numeric(5, 2), nullable=True, default=0.0)
    tax_amount = Column(Numeric(14, 2), nullable=True, default=0.0)
    total_amount = Column(Numeric(14, 2), nullable=False, default=0.0)

    document = relationship("Document", back_populates="purchase_order")
    vendor = relationship("Vendor")
    line_items = relationship("POLineItem", back_populates="purchase_order", cascade="all, delete-orphan")

class POLineItem(Base):
    __tablename__ = 'po_line_items'

    line_id = Column(GUID, primary_key=True, default=uuid.uuid4)
    po_id = Column(GUID, ForeignKey('purchase_orders.po_id', ondelete='CASCADE'), nullable=False)
    item_code = Column(String, nullable=True)
    description = Column(Text, nullable=False)
    qty = Column(Numeric(12, 2), nullable=False, default=0.0)
    unit_price = Column(Numeric(14, 2), nullable=False, default=0.0)
    line_total = Column(Numeric(14, 2), nullable=False, default=0.0)

    purchase_order = relationship("PurchaseOrder", back_populates="line_items")

class Invoice(Base):
    __tablename__ = 'invoices'

    invoice_id = Column(GUID, primary_key=True, default=uuid.uuid4)
    document_id = Column(GUID, ForeignKey('documents.document_id', ondelete='CASCADE'), unique=True, nullable=False)
    bundle_id = Column(GUID, ForeignKey('audit_bundles.bundle_id'), nullable=False)
    invoice_number = Column(String, nullable=False, index=True)
    invoice_date = Column(Date, nullable=True)
    due_date = Column(Date, nullable=True)
    po_ref_raw = Column(String, nullable=True)
    po_id = Column(GUID, ForeignKey('purchase_orders.po_id'), nullable=True)
    vendor_id = Column(GUID, ForeignKey('vendors.vendor_id'), nullable=True)
    subtotal = Column(Numeric(14, 2), nullable=False, default=0.0)
    tax_rate = Column(Numeric(5, 2), nullable=True, default=0.0)
    tax_amount = Column(Numeric(14, 2), nullable=True, default=0.0)
    total_amount = Column(Numeric(14, 2), nullable=False, default=0.0)

    document = relationship("Document", back_populates="invoice")
    vendor = relationship("Vendor")
    purchase_order = relationship("PurchaseOrder")
    line_items = relationship("InvoiceLineItem", back_populates="invoice", cascade="all, delete-orphan")

class InvoiceLineItem(Base):
    __tablename__ = 'invoice_line_items'

    line_id = Column(GUID, primary_key=True, default=uuid.uuid4)
    invoice_id = Column(GUID, ForeignKey('invoices.invoice_id', ondelete='CASCADE'), nullable=False)
    description = Column(Text, nullable=False)
    qty = Column(Numeric(12, 2), nullable=True, default=0.0)
    unit_price = Column(Numeric(14, 2), nullable=True, default=0.0)
    line_total = Column(Numeric(14, 2), nullable=True, default=0.0)

    invoice = relationship("Invoice", back_populates="line_items")

class GRN(Base):
    __tablename__ = 'grns'

    grn_id = Column(GUID, primary_key=True, default=uuid.uuid4)
    document_id = Column(GUID, ForeignKey('documents.document_id', ondelete='CASCADE'), unique=True, nullable=False)
    bundle_id = Column(GUID, ForeignKey('audit_bundles.bundle_id'), nullable=False)
    grn_number = Column(String, nullable=False)
    grn_date = Column(Date, nullable=True)
    delivery_note_number = Column(String, nullable=True)
    po_ref_raw = Column(String, nullable=True)
    po_id = Column(GUID, ForeignKey('purchase_orders.po_id'), nullable=True)
    vendor_id = Column(GUID, ForeignKey('vendors.vendor_id'), nullable=True)
    total_amount = Column(Numeric(14, 2), nullable=False, default=0.0)
    received_condition = Column(String, nullable=True)

    document = relationship("Document", back_populates="grn")
    vendor = relationship("Vendor")
    purchase_order = relationship("PurchaseOrder")
    line_items = relationship("GRNLineItem", back_populates="grn", cascade="all, delete-orphan")

class GRNLineItem(Base):
    __tablename__ = 'grn_line_items'

    line_id = Column(GUID, primary_key=True, default=uuid.uuid4)
    grn_id = Column(GUID, ForeignKey('grns.grn_id', ondelete='CASCADE'), nullable=False)
    description = Column(Text, nullable=False)
    qty_ordered = Column(Numeric(12, 2), nullable=True, default=0.0)
    qty_received = Column(Numeric(12, 2), nullable=True, default=0.0)
    unit_price = Column(Numeric(14, 2), nullable=True, default=0.0)
    line_total = Column(Numeric(14, 2), nullable=True, default=0.0)

    grn = relationship("GRN", back_populates="line_items")

class BankStatement(Base):
    __tablename__ = 'bank_statements'

    statement_id = Column(GUID, primary_key=True, default=uuid.uuid4)
    document_id = Column(GUID, ForeignKey('documents.document_id', ondelete='CASCADE'), unique=True, nullable=False)
    bundle_id = Column(GUID, ForeignKey('audit_bundles.bundle_id'), nullable=False)
    account_number = Column(String, nullable=True)
    statement_date = Column(Date, nullable=True)
    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)
    opening_balance = Column(Numeric(14, 2), nullable=True, default=0.0)
    closing_balance = Column(Numeric(14, 2), nullable=True, default=0.0)

    document = relationship("Document", back_populates="bank_statement")
    transactions = relationship("BankTransaction", back_populates="statement", cascade="all, delete-orphan")

class BankTransaction(Base):
    __tablename__ = 'bank_transactions'

    txn_id = Column(GUID, primary_key=True, default=uuid.uuid4)
    statement_id = Column(GUID, ForeignKey('bank_statements.statement_id', ondelete='CASCADE'), nullable=False)
    txn_date = Column(Date, nullable=False)
    description_raw = Column(Text, nullable=False)
    credit_amount = Column(Numeric(14, 2), nullable=True, default=0.0)
    debit_amount = Column(Numeric(14, 2), nullable=True, default=0.0)
    running_balance = Column(Numeric(14, 2), nullable=True, default=0.0)
    extracted_ref = Column(String, nullable=True)
    extracted_invoice_number = Column(String, nullable=True, index=True)
    extracted_vendor_fragment = Column(String, nullable=True)
    matched_invoice_id = Column(GUID, ForeignKey('invoices.invoice_id'), nullable=True)

    statement = relationship("BankStatement", back_populates="transactions")
    matched_invoice = relationship("Invoice")

class VerificationRun(Base):
    __tablename__ = 'verification_runs'

    run_id = Column(GUID, primary_key=True, default=uuid.uuid4)
    bundle_id = Column(GUID, ForeignKey('audit_bundles.bundle_id', ondelete='CASCADE'), nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    overall_status = Column(String, nullable=True)  # clean|flagged|critical|incomplete
    overall_risk_score = Column(Numeric(5, 2), nullable=True, default=0.0)
    rules_version = Column(String, nullable=False, default='1.0')

class VerificationCheck(Base):
    __tablename__ = 'verification_checks'

    check_id = Column(GUID, primary_key=True, default=uuid.uuid4)
    run_id = Column(GUID, ForeignKey('verification_runs.run_id', ondelete='CASCADE'), nullable=False)
    check_type = Column(String, nullable=False)
    status = Column(String, nullable=False)  # pass|warning|fail|not_applicable
    expected_value = Column(Text, nullable=True)
    actual_value = Column(Text, nullable=True)
    variance = Column(Numeric(14, 2), nullable=True)
    severity = Column(String, nullable=True)  # low|medium|high|critical
    explanation = Column(Text, nullable=False)

class Discrepancy(Base):
    __tablename__ = 'discrepancies'

    discrepancy_id = Column(GUID, primary_key=True, default=uuid.uuid4)
    run_id = Column(GUID, ForeignKey('verification_runs.run_id', ondelete='CASCADE'), nullable=False)
    check_id = Column(GUID, ForeignKey('verification_checks.check_id'), nullable=True)
    category = Column(String, nullable=False)
    severity = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    recommended_action = Column(Text, nullable=True)
    resolved = Column(Boolean, default=False)
    resolved_by = Column(GUID, ForeignKey('users.user_id'), nullable=True)
    resolved_at = Column(DateTime, nullable=True)

class AgentExecutionLog(Base):
    __tablename__ = 'agent_execution_log'

    log_id = Column(GUID, primary_key=True, default=uuid.uuid4)
    run_id = Column(GUID, ForeignKey('verification_runs.run_id', ondelete='CASCADE'), nullable=True)
    bundle_id = Column(GUID, ForeignKey('audit_bundles.bundle_id'), nullable=True)
    agent_name = Column(String, nullable=False)
    input_snapshot = Column(JSON, nullable=True)
    output_snapshot = Column(JSON, nullable=True)
    model_used = Column(String, nullable=True)
    tokens_used = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    status = Column(String, nullable=True)  # success|error|retried
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Report(Base):
    __tablename__ = 'reports'

    report_id = Column(GUID, primary_key=True, default=uuid.uuid4)
    run_id = Column(GUID, ForeignKey('verification_runs.run_id'), nullable=False)
    format = Column(String, default='pdf')
    file_path = Column(Text, nullable=True)
    content_json = Column(JSON, nullable=False)
    generated_at = Column(DateTime, default=datetime.utcnow)
