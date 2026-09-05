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
    Parses bank narration text.
    Observed pattern: NEFT-Ref7655194-Dora-Rana Pvt Ltd-INV200001
    Returns: dict with ref, vendor_fragment, invoice_number
    """
    if not description_raw:
        return {"ref": None, "vendor_fragment": None, "invoice_number": None}

    # Pattern: NEFT-Ref<REF>-<VENDOR>-<INV_NO>
    pattern = r'NEFT-Ref(?P<ref>[A-Za-z0-9]+)-(?P<vendor_fragment>.+?)-(?P<invoice_ref>INV[A-Za-z0-9]+|\bINV\d+\b|\b\d{5,}\b)'
    match = re.search(pattern, description_raw, re.IGNORECASE)

    if match:
        inv_ref = match.group("invoice_ref").strip()
        return {
            "ref": match.group("ref"),
            "vendor_fragment": match.group("vendor_fragment").strip(),
            "invoice_number": inv_ref
        }

    # Fallback regexes
    inv_match = re.search(r'(INV[-_]?\d+|\bINV\d+\b|\b\d{5,}\b)', description_raw, re.IGNORECASE)
    ref_match = re.search(r'Ref[-_]?(?P<ref>[A-Za-z0-9]+)', description_raw, re.IGNORECASE)

    return {
        "ref": ref_match.group("ref") if ref_match else None,
        "vendor_fragment": None,
        "invoice_number": inv_match.group(1) if inv_match else None
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
