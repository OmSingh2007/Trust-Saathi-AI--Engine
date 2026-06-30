"""
services/excel_processor.py — Excel/CSV Ingestion & Column Mapping
==================================================================
This module handles structured file formats (Excel .xlsx and CSV .csv).
Unlike image processing (which needs AI), spreadsheets are already structured —
we just need to figure out which column means what.

The challenge: NGOs use inconsistent column headers like:
  - "Name of Giver", "Donor", "Name" → all mean `donor_name`
  - "Rs", "Donation", "Amount (₹)" → all mean `amount`

This module uses fuzzy matching on column headers to intelligently map them
to our standard field names.
"""

import io                          # For wrapping bytes into file-like objects (BytesIO)
import pandas as pd                # The main library for reading/manipulating tabular data
from rapidfuzz import fuzz, process  # Fuzzy string matching for column name mapping


# ──────────────────────────────────────────────────────────────────────────────
# COLUMN MAPPING CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────

# This dictionary maps each of OUR standard field names to a list of common
# variations that NGOs might use as column headers in their Excel/CSV files.
# We'll fuzzy-match actual column names against these candidates.
COLUMN_CANDIDATES: dict[str, list[str]] = {
    "donor_name": [
        "donor name", "name", "donor", "name of giver", "giver name",
        "donated by", "given by", "contributor", "contributor name",
        "daan data naam", "naam",  # Hindi transliterations
    ],
    "amount": [
        "amount", "donation", "donation amount", "rs", "rupees",
        "amount rs", "amount (rs)", "amount (₹)", "rashi", "daan rashi",
        "contribution", "sum", "total",
    ],
    "date": [
        "date", "donation date", "payment date", "dt", "dated",
        "tarikh", "daan tarikh",  # Hindi/Urdu transliterations
        "received on", "received date",
    ],
    "payment_mode": [
        "payment mode", "mode", "mode of payment", "payment type",
        "type", "method", "payment method", "paid by", "paid via",
        "madhyam",  # Hindi for "medium/mode"
    ],
}

# Minimum fuzzy match score required to accept a column mapping.
# 65 is intentionally lower than the deduplication threshold (85)
# because column headers can be very abbreviated (e.g., "Rs" for "amount").
COLUMN_MATCH_THRESHOLD: int = 65


# ──────────────────────────────────────────────────────────────────────────────
# COLUMN MAPPING FUNCTION
# ──────────────────────────────────────────────────────────────────────────────

def map_columns(actual_columns: list[str]) -> dict[str, str]:
    """
    Maps the actual column names from an Excel/CSV file to our standard field names
    using fuzzy string matching.

    How it works:
    For each of our standard fields (donor_name, amount, date, payment_mode):
      1. Take the list of candidate names for that field (from COLUMN_CANDIDATES).
      2. For each actual column in the spreadsheet, compute a fuzzy match score
         against ALL candidates for this field.
      3. Pick the actual column with the highest match score.
      4. If the score is above our threshold (65), accept the mapping.

    Args:
        actual_columns: List of column header strings from the uploaded file.
                        Example: ["Name of Giver", "Rs", "Dt", "Mode"]

    Returns:
        A dictionary mapping standard field names to actual column names.
        Example: {"donor_name": "Name of Giver", "amount": "Rs", "date": "Dt", "payment_mode": "Mode"}
        Fields that couldn't be matched are excluded from the result.
    """
    # This will store our final mapping: {"donor_name": "Name of Giver", ...}
    column_map: dict[str, str] = {}

    # Iterate over each standard field and its candidate names
    for standard_field, candidates in COLUMN_CANDIDATES.items():
        best_score = 0        # Track the highest similarity score found
        best_column = None    # Track which actual column had the highest score

        # Check each actual column header from the file
        for actual_col in actual_columns:

            # Compare this actual column name against ALL candidate names
            # for the current standard field.
            for candidate in candidates:

                # fuzz.token_sort_ratio is used here (same as deduplication)
                # because column headers might have words in different orders:
                # "Name Donor" vs "Donor Name" → 100% match.
                score = fuzz.token_sort_ratio(
                    actual_col.lower().strip(),   # Normalize actual column name
                    candidate.lower().strip()     # Normalize candidate name
                )

                # Keep track of the best match for this standard field
                if score > best_score:
                    best_score = score
                    best_column = actual_col

        # Only accept the mapping if the score exceeds our threshold
        if best_score >= COLUMN_MATCH_THRESHOLD and best_column is not None:
            column_map[standard_field] = best_column

    return column_map


# ──────────────────────────────────────────────────────────────────────────────
# MAIN PROCESSING FUNCTION
# ──────────────────────────────────────────────────────────────────────────────

def process_excel_or_csv(file_bytes: bytes, filename: str) -> dict:
    """
    Reads an Excel or CSV file from bytes, maps its columns to standard fields,
    and returns structured donation records.

    How it works:
    1. Detect file type from the filename extension.
    2. Wrap the raw bytes in a BytesIO object (pandas needs a file-like object).
    3. Read the file into a pandas DataFrame.
    4. Use map_columns() to figure out which column means what.
    5. Extract the data from mapped columns into our standard format.
    6. Set confidence_score to 0.95 (structured data = high confidence).

    Args:
        file_bytes: Raw binary content of the uploaded file.
        filename:   Original filename (needed to detect .xlsx vs .csv).

    Returns:
        A dictionary like:
        {
            "document_type": "excel",
            "entries": [
                {"donor_name": "Ramesh", "amount": 500, "date": "28/06/2026", ...},
                ...
            ]
        }

    Raises:
        ValueError: If no columns could be mapped (the file doesn't look like donation data).
    """
    # ── Step 1: Detect file type and read into DataFrame ──

    # io.BytesIO(file_bytes) wraps raw bytes into a file-like object.
    # pandas can't read raw bytes directly — it needs something that behaves
    # like a file (with .read(), .seek(), etc.). BytesIO provides exactly that.
    byte_stream = io.BytesIO(file_bytes)

    # Check the file extension to decide which pandas reader to use
    # .lower() ensures we match regardless of case (.CSV, .Csv, .csv all work)
    if filename.lower().endswith(".csv"):
        # pd.read_csv() reads a CSV file into a DataFrame.
        # A DataFrame is essentially a table — rows and columns, like a spreadsheet.
        df = pd.read_csv(byte_stream)
    else:
        # pd.read_excel() reads .xlsx files. Requires the `openpyxl` library.
        # engine="openpyxl" explicitly tells pandas which Excel parser to use.
        # openpyxl supports the modern .xlsx format.
        df = pd.read_excel(byte_stream, engine="openpyxl")

    # ── Step 2: Map columns ──

    # df.columns gives us a list-like object (Index) of all column headers.
    # .tolist() converts it to a plain Python list of strings.
    actual_columns = df.columns.tolist()

    # Use our fuzzy mapping function to match actual columns to standard fields
    column_map = map_columns(actual_columns)

    # If no columns matched at all, the file probably isn't donation data
    if not column_map:
        raise ValueError(
            f"Could not map any columns to standard fields. "
            f"Found columns: {actual_columns}. "
            f"Expected columns related to: donor name, amount, date, payment mode."
        )

    # ── Step 3: Extract data from mapped columns ──

    entries: list[dict] = []  # Will hold our standardized records

    # df.iterrows() iterates over each row of the DataFrame.
    # It yields (index, row) tuples, where:
    #   - index: the row number (0, 1, 2, ...)
    #   - row: a pandas Series (like a dictionary) mapping column_name → value
    # We use _ for the index because we don't need it.
    for _, row in df.iterrows():

        entry = {}

        # For each standard field that was successfully mapped...
        for standard_field, actual_column in column_map.items():
            # row[actual_column] gets the value in this row for the mapped column.
            # Example: if column_map = {"donor_name": "Name of Giver"},
            # then row["Name of Giver"] gives us the donor's name for this row.
            value = row[actual_column]

            # pd.isna(value) checks if the value is NaN/None/missing.
            # In pandas, empty cells become NaN (Not a Number).
            # We convert NaN to None for clean JSON output.
            if pd.isna(value):
                entry[standard_field] = None
            else:
                entry[standard_field] = value

        # Add confidence score: 0.95 for Excel data because it's already structured.
        # (We don't give it 1.0 because column mapping might have minor errors,
        # and data entry in the original spreadsheet might have mistakes.)
        entry["confidence_score"] = 0.95

        entries.append(entry)

    return {
        "document_type": "excel",
        "entries": entries
    }
