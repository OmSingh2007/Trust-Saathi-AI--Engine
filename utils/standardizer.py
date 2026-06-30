"""
utils/standardizer.py — Data Cleaning & Standardization
========================================================
Contains three functions that clean raw extracted data into
the strict formats required by Developer 2's API contract:
  1. standardize_date()      → converts any date string to "YYYY-MM-DD"
  2. standardize_payment_mode() → normalizes payment modes to standard strings
  3. standardize_amount()    → strips symbols and converts to a clean float
"""

import re                              # Regular expressions — used to strip non-numeric chars from amounts
from dateutil import parser as dateparser  # Powerful date string parser that handles many formats automatically


# ──────────────────────────────────────────────────────────────────────────────
# 1. DATE STANDARDIZATION
# ──────────────────────────────────────────────────────────────────────────────

def standardize_date(date_string: str) -> str | None:
    """
    Converts a date string in ANY common format into "YYYY-MM-DD".

    How it works:
    - dateutil.parser.parse() is a smart parser that can understand formats like:
        "28/06/2026", "28-Jun-26", "June 28, 2026", "2026-06-28", "28 Jun 2026"
    - dayfirst=True tells the parser that in ambiguous cases (like "06/07/2026"),
      the FIRST number is the DAY, not the month. This is the Indian convention.
    - .strftime("%Y-%m-%d") formats the parsed datetime object into "YYYY-MM-DD".

    Args:
        date_string: The raw date string extracted from a document.

    Returns:
        A string in "YYYY-MM-DD" format, or None if parsing fails.

    Examples:
        standardize_date("28/06/2026")  → "2026-06-28"
        standardize_date("28-Jun-26")   → "2026-06-28"
        standardize_date("garbage")     → None
    """
    # If the input is empty or not a string, return None immediately
    if not date_string or not isinstance(date_string, str):
        return None

    try:
        # dateparser.parse() tries to intelligently parse the date string.
        # dayfirst=True: treats "28/06/2026" as June 28 (not 28th month which doesn't exist,
        # but more importantly, "06/07/2026" becomes July 6, not June 7).
        parsed_date = dateparser.parse(date_string, dayfirst=True)

        # .strftime("%Y-%m-%d") formats the datetime into our target format.
        # %Y = 4-digit year, %m = 2-digit month, %d = 2-digit day.
        return parsed_date.strftime("%Y-%m-%d")

    except (ValueError, TypeError, OverflowError):
        # If dateutil cannot parse the string at all, it raises ValueError.
        # TypeError if the input is somehow wrong type, OverflowError for extreme dates.
        # In all these cases, we return None to signal "could not parse".
        return None


# ──────────────────────────────────────────────────────────────────────────────
# 2. PAYMENT MODE STANDARDIZATION
# ──────────────────────────────────────────────────────────────────────────────

# This dictionary maps various ways people write payment modes to our standard strings.
# The keys are all LOWERCASE versions of common variations.
# When we get a raw payment mode, we lowercase it and look it up here.
PAYMENT_MODE_MAP: dict[str, str] = {
    # --- UPI variations ---
    "upi":          "UPI",
    "gpay":         "UPI",
    "google pay":   "UPI",
    "googlepay":    "UPI",
    "phonepe":      "UPI",
    "phone pe":     "UPI",
    "paytm":        "UPI",
    "paytm upi":    "UPI",
    "bhim":         "UPI",
    "bhim upi":     "UPI",

    # --- Cash variations ---
    "cash":         "CASH",
    "by hand":      "CASH",
    "naqad":        "CASH",       # "naqad" is Urdu/Hindi for "cash"
    "hand":         "CASH",
    "in hand":      "CASH",

    # --- Bank Transfer variations ---
    "bank transfer":    "BANK_TRANSFER",
    "bank":             "BANK_TRANSFER",
    "neft":             "BANK_TRANSFER",
    "rtgs":             "BANK_TRANSFER",
    "imps":             "BANK_TRANSFER",
    "wire":             "BANK_TRANSFER",
    "wire transfer":    "BANK_TRANSFER",
    "online":           "BANK_TRANSFER",
    "online transfer":  "BANK_TRANSFER",

    # --- Cheque variations ---
    "cheque":       "CHEQUE",
    "check":        "CHEQUE",
    "chq":          "CHEQUE",

    # --- Demand Draft variations ---
    "dd":               "DEMAND_DRAFT",
    "demand draft":     "DEMAND_DRAFT",
    "draft":            "DEMAND_DRAFT",
}


def standardize_payment_mode(raw_mode: str) -> str:
    """
    Normalizes a raw payment mode string into one of our standard categories:
    "UPI", "CASH", "BANK_TRANSFER", "CHEQUE", "DEMAND_DRAFT", or "OTHER".

    How it works:
    1. Strip whitespace and convert to lowercase for consistent matching.
    2. Look up the cleaned string in our PAYMENT_MODE_MAP dictionary.
    3. If found, return the standard value. If not found, return "OTHER".

    Args:
        raw_mode: The raw payment mode string (e.g., "Gpay", "Google Pay", "Cash").

    Returns:
        A standardized string like "UPI", "CASH", etc.

    Examples:
        standardize_payment_mode("Gpay")          → "UPI"
        standardize_payment_mode("  google pay ")  → "UPI"
        standardize_payment_mode("Bitcoin")        → "OTHER"
    """
    # If input is empty or not a string, default to "OTHER"
    if not raw_mode or not isinstance(raw_mode, str):
        return "OTHER"

    # .strip() removes leading/trailing whitespace: "  Gpay  " → "Gpay"
    # .lower() converts to lowercase: "Gpay" → "gpay"
    cleaned = raw_mode.strip().lower()

    # .get(key, default) looks up the key in the dictionary.
    # If the key exists, it returns the mapped value (e.g., "UPI").
    # If the key does NOT exist, it returns the default ("OTHER").
    return PAYMENT_MODE_MAP.get(cleaned, "OTHER")


# ──────────────────────────────────────────────────────────────────────────────
# 3. AMOUNT STANDARDIZATION
# ──────────────────────────────────────────────────────────────────────────────

def standardize_amount(raw_amount) -> float | None:
    """
    Converts a raw amount value (which might contain currency symbols, commas,
    or other non-numeric characters) into a clean Python float.

    How it works:
    1. Convert the input to a string (in case it's already a number).
    2. Use regex to remove everything except digits and decimal points.
    3. Convert the cleaned string to a float.

    Args:
        raw_amount: The raw amount — could be a string like "₹1,500.00", "Rs 500",
                    or already a number like 1500 or 1500.0.

    Returns:
        A float like 1500.0, or None if conversion fails.

    Examples:
        standardize_amount("₹1,500.00")  → 1500.0
        standardize_amount("Rs. 500")     → 500.0
        standardize_amount(1500)          → 1500.0
        standardize_amount("N/A")         → None
    """
    # If input is None, return None immediately
    if raw_amount is None:
        return None

    # If it's already a plain number (int or float), just return it as float
    if isinstance(raw_amount, (int, float)):
        return float(raw_amount)

    try:
        # Convert to string in case it's some other type
        text = str(raw_amount)

        # re.sub(pattern, replacement, string) replaces all matches of `pattern`
        # with `replacement` in `string`.
        #
        # Pattern: r"[^\d.]"
        #   [^\d.]  means "any character that is NOT a digit (\d) and NOT a dot (.)"
        #   So this removes: ₹, Rs, commas, spaces, letters, etc.
        #
        # Examples:
        #   "₹1,500.00" → "1500.00"
        #   "Rs. 500"   → "500"  (the dot after Rs gets removed because it matches,
        #                          but wait — "." IS allowed by our pattern.
        #                          Actually "Rs. 500" → ".500" ... let me handle this)
        cleaned = re.sub(r"[^\d.]", "", text)

        # Edge case: if cleaning left us with an empty string or just dots
        if not cleaned or cleaned == ".":
            return None

        # Handle case where there might be leading dots (e.g., from "Rs. 500" → ".500")
        # .strip(".") would remove valid decimals, so instead we handle leading dots:
        # Actually re.sub(r"[^\d.]", "", "Rs. 500") gives ".500" — we need to handle this.
        # Let's strip leading dots that aren't part of a decimal number.
        cleaned = cleaned.lstrip(".")  # Remove leading dots: ".500" → "500"

        if not cleaned:
            return None

        return float(cleaned)

    except (ValueError, TypeError):
        # If float() conversion fails for any reason, return None
        return None
