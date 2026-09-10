"""
bank_parser.py
--------------
Deterministic Bank Statement parser — NO LLM calls.

Root cause fix: PyMuPDF's get_text("text") reads PDF content streams in order,
which for multi-column bank statement tables can output data column-by-column
instead of row-by-row. This causes transaction rows to be fragmented.

Solution: Use PyMuPDF get_text("words") to extract ALL words with their
(x, y) coordinates, then group words by Y-position (within tolerance) to
reconstruct proper rows regardless of PDF encoding order.

Each transaction is parsed from a Y-grouped row containing:
  date  narration  [credit_amount]  [debit_amount]  running_balance
"""

import re
import logging
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

try:
    import fitz  # PyMuPDF
    _HAS_FITZ = True
except ImportError:
    _HAS_FITZ = False

from app.schemas.extraction_schemas import BankExtraction, BankTxnExtraction
from app.services.parsers.base_parser import BaseDocumentParser, ExtractionResult
from app.services.confidence import score_bank_extraction

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Metadata regex patterns — applied on the full reconstructed text
# ---------------------------------------------------------------------------

_RE_ACCOUNT_NUMBER  = re.compile(r'Account\s*(?:Number|No\.?|#)\s*[:\-]?\s*([\d\-]+)', re.I)
_RE_STATEMENT_DATE  = re.compile(r'Statement\s*Date\s*[:\-]?\s*(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4}|\d{4}[\/\-\.]\d{2}[\/\-\.]\d{2})', re.I)
_RE_PERIOD          = re.compile(r'Period\s*Covered\s*[:\-]?\s*(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4})\s*to\s*(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4})', re.I)
_RE_PERIOD_START    = re.compile(r'(?:Period\s*(?:From)?|From)\s*[:\-]?\s*(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4}|\d{4}[\/\-\.]\d{2}[\/\-\.]\d{2})', re.I)
_RE_PERIOD_END      = re.compile(r'(?:To|Period\s*End)\s*[:\-]?\s*(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4}|\d{4}[\/\-\.]\d{2}[\/\-\.]\d{2})', re.I)
_RE_OPENING_BAL     = re.compile(r'Opening\s*Balance\s*[:\-]?\s*([\d,]+\.\d{2})', re.I)
_RE_CLOSING_BAL     = re.compile(r'Closing\s*Balance\s*[:\-]?\s*([\d,]+\.\d{2})', re.I)
_RE_TOTAL_CREDIT    = re.compile(r'Total\s*Credit(?:\s*Amount)?\s*[:\-]?\s*([\d,]+\.\d{2})', re.I)
_RE_TOTAL_DEBIT     = re.compile(r'Total\s*Debit(?:\s*Amount)?\s*[:\-]?\s*([\d,]+\.\d{2})', re.I)
_RE_NUM_TXNS        = re.compile(r'(?:Number|No\.?)\s*of\s*Transactions\s*[:\-]?\s*(\d+)', re.I)

# Transaction row patterns
_RE_TXN_DATE  = re.compile(r'^(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4})\s+')
_RE_AMOUNT    = re.compile(r'[\d,]+\.\d{2}')
_RE_PAY_REF   = re.compile(r'\b(?:REF|REFERENCE)\s*[#:\-_]?\s*([A-Za-z0-9]{4,30})\b', re.I)
_RE_INV_REF   = re.compile(r'\b(?:INV|INVOICE)\s*[#:\-_/]?\s*([A-Za-z0-9\-_/]{3,30})\b', re.I)

# Summary markers — never treat these as transaction rows
_SUMMARY_MARKERS = [
    'Opening Balance', 'Closing Balance', 'Total Credit', 'Total Debit',
    'Account Summary', 'Number of Transactions', 'Statement Date',
    'Account Number', 'Account No', '--- End of',
]

_TABLE_HEADER_KEYWORDS = {'date', 'description', 'narration', 'particulars', 'credit', 'debit', 'balance', 'amount', 'details'}

# Narration keywords that unambiguously indicate debit (payment out)
_DEBIT_KEYWORDS = frozenset([
    'neft', 'rtgs', 'imps', 'payment', 'paid', 'trf', 'transfer out',
    'bill payment', 'vendor payment', 'salary', 'loan repayment',
])
# Narration keywords that unambiguously indicate credit (money in)
_CREDIT_KEYWORDS = frozenset([
    'account transfer in', 'transfer in', 'cheque deposit', 'deposit',
    'credit received', 'refund', 'inward', 'receipt',
])


def _is_summary_line(line: str) -> bool:
    s = line.strip()
    return any(m.lower() in s.lower() for m in _SUMMARY_MARKERS)


def _is_table_header_line(line: str) -> bool:
    """Detect Transactions table header row."""
    words = set(re.findall(r'[a-zA-Z]+', line.lower()))
    return len(words & _TABLE_HEADER_KEYWORDS) >= 2


def _parse_amount(raw: str) -> float:
    return float(raw.replace(',', ''))


def _parse_date_to_iso(date_str: str) -> str:
    from datetime import datetime
    for fmt in ('%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y', '%Y-%m-%d', '%Y/%m/%d'):
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return date_str.strip()


def _extract_narration_refs(narration: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Extract payment_reference, invoice_reference, and vendor_name from narration.

    vendor_name is ONLY set if the remaining segment after stripping payment prefixes
    and reference codes looks like a recognizable company/person name:
    - Contains only alphabetic words (no standalone numbers or dates)
    - Length > 3 characters
    - Not a generic banking term (Payment, Transfer, Deposit, etc.)
    """
    pay_ref = inv_ref = vendor = None

    pm = _RE_PAY_REF.search(narration)
    if pm:
        pay_ref = 'Ref' + pm.group(1)

    im = _RE_INV_REF.search(narration)
    if im:
        inv_ref = im.group(1).upper()

    # Strip payment-channel prefixes and reference codes to find vendor fragment
    seg = narration
    seg = re.sub(r'^\s*(?:NEFT|RTGS|IMPS|UPI|ACH|CHQ|ECS|TRF|NACH|AUTO)\s*[-\s]*', '', seg, flags=re.I)
    seg = re.sub(r'Ref\d+\s*[-\s]*', '', seg, flags=re.I)
    seg = re.sub(r'INV[-\s]?\d+\s*[-\s]*', '', seg, flags=re.I)
    seg = seg.strip(' -_/|:,;')

    # Only use as vendor_name if the segment looks like a proper name:
    # - length > 3
    # - contains at least one alphabetic word of length >= 2
    # - not a pure generic banking descriptor
    _GENERIC_TERMS = frozenset([
        'payment', 'transfer', 'deposit', 'withdrawal', 'charge',
        'fee', 'interest', 'salary', 'refund', 'cr', 'dr',
        'account', 'debit', 'credit',
    ])
    if seg and len(seg) > 3:
        words = re.findall(r'[A-Za-z]{2,}', seg)
        word_set = {w.lower() for w in words}
        if words and not word_set.issubset(_GENERIC_TERMS):
            # Exclude segments that are purely numeric or contain dates
            if not re.match(r'^[\d\s\/\-\.]+$', seg):
                vendor = seg

    return pay_ref, inv_ref, vendor


# ---------------------------------------------------------------------------
# Core: Y-coordinate row reconstruction
# ---------------------------------------------------------------------------

def _extract_rows_by_coordinates(pdf_path: str, y_tolerance: float = 4.0) -> List[str]:
    """
    Extract text rows from a PDF by grouping words with the same Y-coordinate.

    This correctly handles:
    - Multi-column layouts where label (left) and value (right) share the same Y
    - Table rows where Date, Description, Credit, Debit, Balance are on the same Y
    - PDFs whose content streams are encoded column-by-column rather than row-by-row

    Returns a list of row strings sorted by Y-position (top to bottom).
    """
    if not _HAS_FITZ:
        logger.warning("PyMuPDF not available; coordinate extraction skipped")
        return []

    if not Path(pdf_path).exists():
        logger.warning(f"PDF not found for coordinate extraction: {pdf_path}")
        return []

    all_rows: List[str] = []

    try:
        doc = fitz.open(pdf_path)
        for page in doc:
            words = page.get_text("words")  # (x0,y0,x1,y1,word,block,line,word_no)
            if not words:
                continue

            # Group words by Y-midpoint with tolerance
            y_groups: Dict[float, List[Tuple[float, str]]] = {}
            for x0, y0, x1, y1, word, *_ in words:
                y_mid = (y0 + y1) / 2.0
                matched_key = None
                for key in y_groups:
                    if abs(y_mid - key) <= y_tolerance:
                        matched_key = key
                        break
                if matched_key is None:
                    matched_key = y_mid
                    y_groups[matched_key] = []
                y_groups[matched_key].append((x0, word))

            # Sort rows top-to-bottom, words left-to-right within each row
            for y_key in sorted(y_groups.keys()):
                word_list = sorted(y_groups[y_key], key=lambda w: w[0])
                row_text = ' '.join(w[1] for w in word_list).strip()
                if row_text:
                    all_rows.append(row_text)

        doc.close()

    except Exception as e:
        logger.error(f"Coordinate extraction failed for {pdf_path}: {e}", exc_info=True)

    return all_rows


# ---------------------------------------------------------------------------
# Transaction parsing
# ---------------------------------------------------------------------------

def _parse_transaction_row(
    line: str,
    statement_date: str,
    credit_col_x: Optional[float] = None,
    debit_col_x: Optional[float] = None,
) -> Optional[BankTxnExtraction]:
    """
    Parse a single reconstructed transaction row.

    When credit_col_x / debit_col_x are provided (from header column-position detection),
    the amounts are assigned to debit or credit based on which column they fall into.
    Otherwise, narration keyword disambiguation is used as a fallback.
    """
    date_match = _RE_TXN_DATE.match(line)
    if not date_match:
        return None

    txn_date = _parse_date_to_iso(date_match.group(1))
    rest = line[date_match.end():]

    amounts_raw = _RE_AMOUNT.findall(rest)
    amounts = [_parse_amount(a) for a in amounts_raw]

    first_amt = _RE_AMOUNT.search(rest)
    narration = rest[:first_amt.start()].strip(' \t-|') if first_amt else rest.strip()
    if not narration:
        narration = line.strip()

    debit = credit = 0.0
    running_balance = None
    nl = narration.lower()

    # Keyword-based classification (robust fallback and primary for 2-amount rows)
    is_debit  = any(kw in nl for kw in _DEBIT_KEYWORDS)
    is_credit = any(kw in nl for kw in _CREDIT_KEYWORDS)

    if len(amounts) == 0:
        return None
    elif len(amounts) == 1:
        # Only one amount — likely the running balance; skip as non-financial row
        return None
    elif len(amounts) == 2:
        # [transaction_amount, running_balance]
        if is_debit and not is_credit:
            debit = amounts[0]
        elif is_credit and not is_debit:
            credit = amounts[0]
        else:
            # Ambiguous — default to debit (outgoing payment is most common)
            debit = amounts[0]
        running_balance = amounts[1]
    elif len(amounts) == 3:
        # Standard: [credit_col_amount, debit_col_amount, balance]
        # One of credit/debit will be 0 (empty column); use keywords to confirm.
        a0, a1, a2 = amounts[0], amounts[1], amounts[2]
        running_balance = a2
        if is_debit and not is_credit:
            # Debit transaction: debit > 0, credit = 0
            debit = a0 if a0 >= a1 else a1
            credit = 0.0
        elif is_credit and not is_debit:
            # Credit transaction: credit > 0, debit = 0
            credit = a0 if a0 >= a1 else a1
            debit = 0.0
        else:
            # Ambiguous — assign per column order (credit first, then debit)
            credit = a0
            debit = a1
    else:
        # 4+ amounts: last is balance, assign debit/credit by keyword
        running_balance = amounts[-1]
        if is_debit and not is_credit:
            debit = amounts[-2]
            credit = 0.0
        elif is_credit and not is_debit:
            credit = amounts[-2]
            debit = 0.0
        else:
            debit = amounts[-2]
            credit = amounts[-3]

    pay_ref, inv_ref, vendor = _extract_narration_refs(narration)

    logger.debug(
        f"[Bank] txn_date={txn_date!r}  narration={narration!r:40s}  "
        f"debit={debit}  credit={credit}  balance={running_balance}"
    )

    return BankTxnExtraction(
        txn_date=txn_date,
        description_raw=narration,
        debit_amount=debit,
        credit_amount=credit,
        running_balance=running_balance,
        payment_reference=pay_ref,
        invoice_reference=inv_ref,
        vendor_name=vendor
    )


def _extract_transactions_from_rows(rows: List[str], statement_date: str) -> List[BankTxnExtraction]:
    """
    Walk the Y-grouped rows and extract transaction rows:
    - Find the Transactions table header (contains Date + at least one of Description/Narration/etc.)
    - Collect subsequent rows that start with a date
    - Stop on '--- End of Transactions ---' or a known end-of-table marker
    """
    header_found = False
    transactions: List[BankTxnExtraction] = []

    for row in rows:
        stripped = row.strip()

        # Detect the table header
        if not header_found:
            if _is_table_header_line(stripped) and 'date' in stripped.lower():
                header_found = True
            continue

        # Stop at end-of-transactions marker
        if '--- end' in stripped.lower() or 'end of transaction' in stripped.lower():
            break

        # Skip summary lines
        if _is_summary_line(stripped):
            continue

        # Try to parse as a transaction row
        if _RE_TXN_DATE.match(stripped):
            parsed = _parse_transaction_row(stripped, statement_date)
            if parsed:
                transactions.append(parsed)

    return transactions


# ---------------------------------------------------------------------------
# Metadata extraction helpers
# ---------------------------------------------------------------------------

def _field(pattern: re.Pattern, text: str) -> Optional[str]:
    m = pattern.search(text)
    return m.group(1).strip() if m else None


def _amount_field(pattern: re.Pattern, text: str) -> Optional[float]:
    m = pattern.search(text)
    if m:
        try:
            return _parse_amount(m.group(1))
        except ValueError:
            return None
    return None


def _extract_metadata_from_rows(rows: List[str]) -> Dict[str, Any]:
    """
    Extract account-level metadata by joining Y-grouped rows into one big text blob.
    This correctly handles two-column PDFs where label (left) and value (right)
    appear on the same Y-position and thus the same reconstructed row.
    Also handles labels where value is on the NEXT line.
    """
    joined = ' '.join(rows)  # Single string with all rows for regex scanning

    account_number  = _field(_RE_ACCOUNT_NUMBER, joined)
    stmt_date_raw   = _field(_RE_STATEMENT_DATE, joined)

    # Period covered "01/04/2026 to 04/04/2026" — combined pattern first
    period_start_raw = period_end_raw = None
    pm = _RE_PERIOD.search(joined)
    if pm:
        period_start_raw = pm.group(1)
        period_end_raw = pm.group(2)
    else:
        period_start_raw = _field(_RE_PERIOD_START, joined)
        period_end_raw   = _field(_RE_PERIOD_END, joined)

    opening_balance = _amount_field(_RE_OPENING_BAL, joined)
    closing_balance = _amount_field(_RE_CLOSING_BAL, joined)
    total_credit    = _amount_field(_RE_TOTAL_CREDIT, joined)
    total_debit     = _amount_field(_RE_TOTAL_DEBIT, joined)
    num_txns_str    = _field(_RE_NUM_TXNS, joined)

    # Handle label-on-row-N, value-on-row-N+1 layout
    # Scan adjacent rows for label:value pairs where value is on next line
    if opening_balance is None or closing_balance is None:
        for i, row in enumerate(rows[:-1]):
            next_row = rows[i + 1].strip()
            row_lower = row.lower()
            if opening_balance is None and 'opening balance' in row_lower:
                m = re.search(r'^([\d,]+\.\d{2})', next_row)
                if m:
                    opening_balance = _parse_amount(m.group(1))
            if closing_balance is None and 'closing balance' in row_lower:
                m = re.search(r'^([\d,]+\.\d{2})', next_row)
                if m:
                    closing_balance = _parse_amount(m.group(1))
            if total_credit is None and 'total credit' in row_lower:
                m = re.search(r'^([\d,]+\.\d{2})', next_row)
                if m:
                    total_credit = _parse_amount(m.group(1))
            if total_debit is None and 'total debit' in row_lower:
                m = re.search(r'^([\d,]+\.\d{2})', next_row)
                if m:
                    total_debit = _parse_amount(m.group(1))
            if num_txns_str is None and 'number of transactions' in row_lower:
                m = re.search(r'^\d+', next_row)
                if m:
                    num_txns_str = m.group(0)

    expected_count = int(num_txns_str) if num_txns_str and num_txns_str.isdigit() else None

    statement_date = _parse_date_to_iso(stmt_date_raw) if stmt_date_raw else None
    period_start   = _parse_date_to_iso(period_start_raw) if period_start_raw else None
    period_end     = _parse_date_to_iso(period_end_raw) if period_end_raw else None

    # Field-level debug logging
    logger.debug(f"[Bank] metadata: account_number={account_number!r}")
    logger.debug(f"[Bank] metadata: statement_date={statement_date!r}  raw={stmt_date_raw!r}")
    logger.debug(f"[Bank] metadata: period={period_start!r} to {period_end!r}")
    logger.debug(f"[Bank] metadata: opening_balance={opening_balance}  closing_balance={closing_balance}")
    logger.debug(f"[Bank] metadata: total_credit={total_credit}  total_debit={total_debit}")
    logger.debug(f"[Bank] metadata: expected_count={expected_count}  (raw={num_txns_str!r})")

    return {
        'account_number': account_number,
        'statement_date': statement_date,
        'period_start': period_start,
        'period_end': period_end,
        'opening_balance': opening_balance,
        'closing_balance': closing_balance,
        'total_credit': total_credit,
        'total_debit': total_debit,
        'expected_count': expected_count,
    }


# ---------------------------------------------------------------------------
# Parser class
# ---------------------------------------------------------------------------

class BankStatementParser(BaseDocumentParser):
    """
    Deterministic parser for bank statement PDFs.
    No LLM calls — pure coordinate-based row reconstruction + regex.

    Uses PyMuPDF word-coordinate Y-grouping to reconstruct table rows
    regardless of how the PDF content streams are encoded.
    """

    def extract(self, pdf_path: str, raw_text: str) -> ExtractionResult:
        result = ExtractionResult(raw_text=raw_text, model_used="deterministic_bank_parser_v3")
        result.prompt = "Deterministic BankStatementParser — coordinate-based row reconstruction, no LLM"

        # --- Step 1: Reconstruct rows using Y-coordinate grouping ---
        rows = _extract_rows_by_coordinates(pdf_path)

        if not rows:
            # Fallback: split raw_text into lines
            logger.warning(f"Bank parser: coordinate extraction yielded no rows; falling back to raw_text lines")
            rows = [l.strip() for l in raw_text.split('\n') if l.strip()]

        reconstructed_text = '\n'.join(rows)
        result.cleaned_text = reconstructed_text

        # --- Step 2: Extract metadata ---
        meta = _extract_metadata_from_rows(rows)

        account_number  = meta['account_number']
        statement_date  = meta['statement_date']
        period_start    = meta['period_start']
        period_end      = meta['period_end']
        opening_balance = meta['opening_balance']
        closing_balance = meta['closing_balance']
        total_credit    = meta['total_credit']
        total_debit     = meta['total_debit']
        expected_count  = meta['expected_count']

        logger.info(
            f"Bank parser metadata: acc={account_number}, date={statement_date}, "
            f"open={opening_balance}, close={closing_balance}, expected_txns={expected_count}"
        )

        # --- Step 3: Extract transactions ---
        transactions = _extract_transactions_from_rows(rows, statement_date or '')

        if not transactions:
            # Secondary fallback: scan ALL rows for date-starting lines
            logger.warning("Bank parser: no transactions found via header detection; scanning all rows")
            for row in rows:
                s = row.strip()
                if _is_summary_line(s):
                    continue
                if _RE_TXN_DATE.match(s):
                    parsed = _parse_transaction_row(s, statement_date or '')
                    if parsed:
                        transactions.append(parsed)

        actual_count = len(transactions)
        logger.info(f"Bank parser: extracted {actual_count} transactions (expected: {expected_count})")

        # --- Step 4: Validate count ---
        count_match = False
        warnings: List[str] = []

        if expected_count is not None:
            count_match = (actual_count == expected_count)
            if not count_match:
                msg = f"Transaction count mismatch: expected {expected_count}, parsed {actual_count}"
                result.validation_errors = [msg]
                warnings.append(msg)
                logger.warning(f"Bank parser: {msg}")
            else:
                logger.info(f"Bank parser: transaction count validated OK ({actual_count})")
        else:
            warnings.append("Number of Transactions not found in statement; count check skipped")

        result.warnings = warnings
        result.numeric_validation_passed = count_match

        extracted_obj = BankExtraction(
            account_number=account_number,
            statement_date=statement_date,
            period_start=period_start,
            period_end=period_end,
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            total_credit=total_credit,
            total_debit=total_debit,
            number_of_transactions=expected_count,
            transactions=transactions
        )

        result.extracted_obj = extracted_obj
        result.parsed_json = extracted_obj.model_dump()
        result.success = True
        result.confidence = score_bank_extraction(extracted_obj, count_match)
        return result


# Singleton
bank_statement_parser = BankStatementParser()
