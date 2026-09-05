from typing import List, Optional
from datetime import date
from pydantic import BaseModel, Field

# --- Purchase Order Extraction Schema ---
class POLineItemExtraction(BaseModel):
    item_code: Optional[str] = Field(None, description="Item or product code")
    description: str = Field(..., description="Description of item purchased")
    qty: float = Field(..., description="Quantity ordered")
    unit_price: float = Field(..., description="Unit price per item")
    line_total: float = Field(..., description="Line total amount (qty * unit_price)")

class POExtraction(BaseModel):
    po_number: str = Field(..., description="Purchase Order number, e.g., PO-2026-001")
    po_date: Optional[str] = Field(None, description="Date of purchase order (YYYY-MM-DD)")
    vendor_name: Optional[str] = Field(None, description="Vendor/Supplier company name — null if not confidently identified")
    vendor_address: Optional[str] = Field(None, description="Vendor address if present")
    requisitioner: Optional[str] = Field(None, description="Name or department requesting purchase")
    shipping_terms: Optional[str] = Field(None, description="Shipping terms e.g. FOB, Net 30")
    subtotal: float = Field(..., description="Pre-tax subtotal amount")
    tax_rate: Optional[float] = Field(0.0, description="Tax rate percentage, e.g. 18.0")
    tax_amount: Optional[float] = Field(0.0, description="Tax amount")
    total_amount: float = Field(..., description="Total amount inclusive of tax")
    line_items: List[POLineItemExtraction] = Field(default_factory=list, description="List of line items")

# --- Invoice Extraction Schema ---
class InvoiceLineItemExtraction(BaseModel):
    description: str = Field(..., description="Line item description")
    qty: Optional[float] = Field(None, description="Quantity invoiced")
    unit_price: Optional[float] = Field(None, description="Unit price")
    line_total: Optional[float] = Field(None, description="Line item total")

class InvoiceExtraction(BaseModel):
    invoice_number: str = Field(..., description="Invoice reference number")
    invoice_date: Optional[str] = Field(None, description="Invoice issue date (YYYY-MM-DD)")
    due_date: Optional[str] = Field(None, description="Invoice payment due date")
    po_ref_raw: Optional[str] = Field(None, description="PO number referenced on the invoice")
    vendor_name: Optional[str] = Field(None, description="Vendor company name on invoice — null if not confidently identified")
    vendor_address: Optional[str] = Field(None, description="Vendor address")
    subtotal: float = Field(..., description="Subtotal amount before tax")
    tax_rate: Optional[float] = Field(0.0, description="Tax rate percentage")
    tax_amount: Optional[float] = Field(0.0, description="Tax amount")
    total_amount: float = Field(..., description="Total invoice amount inclusive of tax")
    line_items: List[InvoiceLineItemExtraction] = Field(default_factory=list, description="Invoice line items")

# --- GRN Extraction Schema ---
class GRNLineItemExtraction(BaseModel):
    description: str = Field(..., description="Item description")
    qty_ordered: Optional[float] = Field(None, description="Quantity ordered as per PO")
    qty_received: Optional[float] = Field(None, description="Quantity actually received")
    unit_price: Optional[float] = Field(None, description="Unit price if listed")
    line_total: Optional[float] = Field(None, description="Line total if listed")

class GRNExtraction(BaseModel):
    grn_number: str = Field(..., description="Goods Received Note reference number")
    grn_date: Optional[str] = Field(None, description="Date goods were received (YYYY-MM-DD)")
    delivery_note_number: Optional[str] = Field(None, description="Delivery note/Challan reference number")
    po_ref_raw: Optional[str] = Field(None, description="PO number referenced on GRN")
    vendor_name: Optional[str] = Field(None, description="Vendor name — null if not confidently identified")
    total_amount: float = Field(..., description="Pre-tax subtotal amount on GRN")
    received_condition: Optional[str] = Field(None, description="Condition of received goods e.g. Good, Intact")
    line_items: List[GRNLineItemExtraction] = Field(default_factory=list, description="GRN line items")

# --- Bank Statement Extraction Schema ---
class BankTxnExtraction(BaseModel):
    txn_date: str = Field(..., description="Transaction date (YYYY-MM-DD)")
    description_raw: str = Field(..., description="Full raw narration/description string from bank statement")
    credit_amount: Optional[float] = Field(0.0, description="Credit amount if deposit")
    debit_amount: Optional[float] = Field(0.0, description="Debit amount if withdrawal/payment")
    running_balance: Optional[float] = Field(None, description="Account balance after transaction")
    payment_reference: Optional[str] = Field(None, description="Payment reference e.g. Ref7655194")
    invoice_reference: Optional[str] = Field(None, description="Invoice reference e.g. INV200001")
    vendor_name: Optional[str] = Field(None, description="Vendor name fragment from narration")

class BankExtraction(BaseModel):
    account_number: Optional[str] = Field(None, description="Bank account number")
    statement_date: Optional[str] = Field(None, description="Statement generation date")
    period_start: Optional[str] = Field(None, description="Start date of statement period")
    period_end: Optional[str] = Field(None, description="End date of statement period")
    opening_balance: Optional[float] = Field(0.0, description="Opening balance")
    closing_balance: Optional[float] = Field(0.0, description="Closing balance")
    total_credit: Optional[float] = Field(None, description="Total credit amount from account summary")
    total_debit: Optional[float] = Field(None, description="Total debit amount from account summary")
    number_of_transactions: Optional[int] = Field(None, description="Expected number of transactions from statement header")
    transactions: List[BankTxnExtraction] = Field(default_factory=list, description="List of bank transactions")
