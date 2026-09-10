import re
from rapidfuzz import fuzz

def normalize_vendor_name(name: str) -> str:
    """
    Lowercases, strips punctuation and common company suffixes for reliable matching.
    """
    if not name:
        return ""
    name_clean = name.lower().strip()
    # Strip common corporate suffixes
    suffixes = [
        r'\bpvt\.?\s*ltd\.?\b', r'\bprivate\s*limited\b', r'\bltd\.?\b',
        r'\binc\.?\b', r'\bcorp\.?\b', r'\bllc\b', r'\bco\.?\b'
    ]
    for s in suffixes:
        name_clean = re.sub(s, '', name_clean)
    # Remove non-alphanumeric except space
    name_clean = re.sub(r'[^a-z0-9\s]', '', name_clean)
    return " ".join(name_clean.split())

def parse_bank_narration(description_raw: str) -> dict:
    """
    Parses bank narration text for payment references, invoice numbers, and vendor names.
    Supported reference formats: Ref6821782, Ref-6821782, reference 6821782, REF#6821782
    Supported invoice formats: INV200005, INV-200005, INV 200005, Invoice 200005, Invoice #200005
    Returns: dict with ref, vendor_fragment, invoice_number
    """
    if not description_raw:
        return {"ref": None, "vendor_fragment": None, "invoice_number": None}

    # Pattern for structured narrations: NEFT-Ref<REF>-<VENDOR>-<INV_NO>
    pattern = r'(?:NEFT|RTGS|IMPS|TRF)[-_\s]*Ref[-_\s]?(?P<ref>[A-Za-z0-9]+)[-_\s]+(?P<vendor_fragment>.+?)[-_\s]+(?P<invoice_ref>INV[A-Za-z0-9\-_/]+|\bINVOICE\s*[#:\-_/]?\s*[A-Za-z0-9\-_/]+)'
    match = re.search(pattern, description_raw, re.IGNORECASE)

    if match:
        inv_ref = match.group("invoice_ref").strip()
        return {
            "ref": match.group("ref"),
            "vendor_fragment": match.group("vendor_fragment").strip(),
            "invoice_number": inv_ref
        }

    # Fallback regexes anchored with word boundaries
    # Invoice pattern: matches INV200005, INV-200005, Invoice 200005, Invoice #200005
    inv_match = re.search(r'\b(?:INV|INVOICE)\b\s*[#:\-_/]?\s*([A-Za-z0-9\-_/]{3,30})\b|\b(INV[0-9A-Z\-_/]{3,30})\b', description_raw, re.IGNORECASE)
    inv_val = (inv_match.group(0) if inv_match else None)

    # Reference pattern: word boundary \b after REF/REFERENCE (or digits) prevents matching words like REFRESH
    ref_match = re.search(r'\b(?:REF|REFERENCE)\b\s*[#:\-_]?\s*(?P<ref>[A-Za-z0-9]{3,30})\b|\b(?:REF|REFERENCE)(?P<ref2>\d{3,30})\b', description_raw, re.IGNORECASE)
    ref_val = None
    if ref_match:
        ref_val = ref_match.group("ref") or ref_match.group("ref2")

    return {
        "ref": ref_val,
        "vendor_fragment": None,
        "invoice_number": inv_val.strip() if inv_val else None
    }

def fuzzy_vendor_match(name1: str, name2: str) -> float:
    """
    Returns similarity ratio between 0.0 and 100.0
    """
    norm1 = normalize_vendor_name(name1)
    norm2 = normalize_vendor_name(name2)
    if not norm1 or not norm2:
        return 0.0
    return float(fuzz.token_sort_ratio(norm1, norm2))
