"""
utils/deduplicator.py — Fuzzy Duplicate Detection
==================================================
Uses fuzzy string matching (rapidfuzz library) to find donor names that
are similar but not exactly the same — potential duplicates.

For example: "Ramesh K." and "Ramesh Kumar" are likely the same person.
This module flags such cases WITHOUT removing or merging records.
"""

from rapidfuzz import fuzz  # Fuzzy string comparison library (faster alternative to fuzzywuzzy)


# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────

# Similarity threshold: if two names are >= 85% similar, they're flagged as duplicates.
# 85 is chosen because:
#   - "Ramesh K." vs "Ramesh Kumar" → ~88% similar (should be flagged) ✓
#   - "Ramesh Kumar" vs "Suresh Kumar" → ~70% similar (should NOT be flagged) ✓
#   - "Ramesh" vs "Ramesh" → 100% (exact match, flagged) ✓
SIMILARITY_THRESHOLD: int = 85


# ──────────────────────────────────────────────────────────────────────────────
# MAIN FUNCTION
# ──────────────────────────────────────────────────────────────────────────────

def find_duplicates(records: list[dict]) -> list[dict]:
    """
    Scans a list of extracted records and flags potential duplicate donors
    based on fuzzy name matching.

    How it works:
    1. For each record, compare its `donor_name` with EVERY OTHER record's name.
    2. Use rapidfuzz's `token_sort_ratio` to calculate similarity.
       - token_sort_ratio splits the names into words, sorts them alphabetically,
         then compares. This handles word-order differences:
         "Kumar Ramesh" vs "Ramesh Kumar" → 100% match.
    3. If similarity >= 85%, add a flag to the record.

    The function adds two new fields to each record:
    - `duplicate_flag` (bool): True if a similar name was found, False otherwise.
    - `similar_to` (list[str]): List of names that are similar to this record's name.

    IMPORTANT: This is NON-DESTRUCTIVE — no records are removed or merged.
    It's purely informational, so Developer 2 or the NGO user can review manually.

    Args:
        records: A list of dictionaries, each having at least a "donor_name" key.
                 Example: [{"donor_name": "Ramesh K.", "amount": 500}, ...]

    Returns:
        The same list of dictionaries, but with `duplicate_flag` and `similar_to`
        fields added to each record.

    Example:
        Input:  [{"donor_name": "Ramesh K."}, {"donor_name": "Ramesh Kumar"}]
        Output: [
            {"donor_name": "Ramesh K.", "duplicate_flag": True, "similar_to": ["Ramesh Kumar"]},
            {"donor_name": "Ramesh Kumar", "duplicate_flag": True, "similar_to": ["Ramesh K."]}
        ]
    """
    # Iterate over each record using enumerate to get both the index (i) and the record.
    # enumerate() gives us: (0, first_record), (1, second_record), etc.
    for i, record in enumerate(records):

        # Get the donor name from the current record.
        # If "donor_name" key doesn't exist, .get() returns "" (empty string) as default.
        name_a = record.get("donor_name", "")

        # This list will collect names of other donors that are similar to name_a.
        similar_names: list[str] = []

        # Compare name_a with every OTHER record's name.
        # We use a second loop with index j to avoid comparing a record with itself.
        for j, other_record in enumerate(records):

            # Skip comparing a record with itself (same index = same record)
            if i == j:
                continue

            name_b = other_record.get("donor_name", "")

            # Skip if either name is empty (can't compare empty strings meaningfully)
            if not name_a or not name_b:
                continue

            # ── The Core Comparison ──
            # fuzz.token_sort_ratio(string1, string2) works like this:
            #   1. Lowercases both strings
            #   2. Splits each into individual words (tokens)
            #   3. Sorts the tokens alphabetically
            #   4. Joins them back into a single string
            #   5. Computes the Levenshtein similarity ratio (0 to 100)
            #
            # Why token_sort_ratio and not just fuzz.ratio?
            #   - fuzz.ratio("Ramesh Kumar", "Kumar Ramesh") → ~50% (order matters!)
            #   - fuzz.token_sort_ratio("Ramesh Kumar", "Kumar Ramesh") → 100% ✓
            #   This is critical because handwritten registers may have names in any order.
            similarity_score = fuzz.token_sort_ratio(name_a, name_b)

            # If the score meets or exceeds our threshold, it's a potential duplicate
            if similarity_score >= SIMILARITY_THRESHOLD:
                similar_names.append(name_b)

        # Add the flags to the record.
        # bool(similar_names) is True if the list is non-empty, False if empty.
        # In Python, an empty list [] is "falsy" and a non-empty list is "truthy".
        record["duplicate_flag"] = bool(similar_names)
        record["similar_to"] = similar_names

    return records
