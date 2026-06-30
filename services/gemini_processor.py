"""
services/gemini_processor.py — AI-Powered OCR & Entity Extraction
=================================================================
This module handles Image and PDF files by sending them to Google's
Gemini 1.5 Flash model for:
  1. OCR (reading handwritten/printed text from images)
  2. Entity Extraction (pulling out donor_name, amount, date, payment_mode)
  3. Document Classification (is it a register or receipt?)
  4. Confidence Scoring (how sure is the AI about each extraction?)

It uses the official `google-genai` SDK with inline byte uploads.
"""

import json                         # To parse the JSON string that Gemini returns
from google import genai             # Official Google Gen AI SDK
from google.genai import types       # Types module — contains Part.from_bytes for inline data
from config import GEMINI_API_KEY    # Our API key loaded from .env


# ──────────────────────────────────────────────────────────────────────────────
# GEMINI CLIENT — LAZY INITIALIZATION
# ──────────────────────────────────────────────────────────────────────────────

# We use "lazy initialization" here instead of creating the client immediately.
# Why? Because if we wrote `client = genai.Client(api_key=...)` at the top level,
# Python would execute that line the moment this file is imported — which happens
# when the FastAPI server starts. If the API key is missing or invalid, the
# ENTIRE server would crash on startup, even for users who only want to process Excel files.
#
# Instead, we store None and create the client only when someone actually uploads
# an image/PDF. This way the server always starts, and we get a clear error only
# when someone tries to use the Gemini feature without a key.

_client = None  # Will hold the genai.Client() once initialized


def _get_client() -> genai.Client:
    """
    Returns the Gemini client, creating it on first use (lazy initialization).

    The `global` keyword tells Python: "when I write `_client = ...` below,
    I mean the module-level _client variable, not a new local variable."
    Without `global`, Python would create a new local variable named _client
    inside this function, and the module-level _client would stay None forever.

    Raises:
        ValueError: If GEMINI_API_KEY is not set in the environment.
    """
    global _client

    # Only create the client if it hasn't been created yet
    if _client is None:
        if not GEMINI_API_KEY:
            raise ValueError(
                "GEMINI_API_KEY is not set. Please add it to your .env file. "
                "Get a key at: https://aistudio.google.com/apikey"
            )
        # Create the client and store it in the module-level variable.
        # Subsequent calls will skip this block and reuse the existing client.
        _client = genai.Client(api_key=GEMINI_API_KEY)

    return _client


# ──────────────────────────────────────────────────────────────────────────────
# THE SYSTEM PROMPT
# ──────────────────────────────────────────────────────────────────────────────
# This is the "instruction manual" we give to Gemini. It tells the AI model
# EXACTLY what to do with the image/PDF it receives.
# A well-crafted prompt is critical — it's the difference between getting
# garbage output and getting clean, structured JSON.

EXTRACTION_PROMPT = """
You are an expert OCR and data extraction system for Indian NGOs and Trusts.
You will receive an image or PDF of a handwritten donation register, receipt, or printed document.

YOUR TASKS:
1. **OCR**: Read ALL text in the document carefully, including handwritten text.
2. **Extract** the following fields for EACH donation entry you find:
   - `donor_name` (string): The name of the donor/giver.
   - `amount` (number): The donation amount. MUST be a number, not a string. Remove any currency symbols.
   - `date` (string): The date of the donation. Return in the EXACT format as written in the document.
   - `payment_mode` (string): How the payment was made (e.g., "Cash", "UPI", "Cheque", "Bank Transfer", "GPay", etc.). If not mentioned, use "Unknown".
   - `confidence_score` (number): Your confidence in the extraction accuracy, from 0.0 (no confidence) to 1.0 (fully confident). Consider legibility of handwriting, clarity of the document, and whether any fields had to be guessed.

3. **Classify** the document as one of:
   - `"handwritten_register"` — if it's a handwritten ledger/register with multiple entries
   - `"receipt"` — if it's a single donation receipt (printed or handwritten)
   - `"printed_register"` — if it's a printed/typed register with multiple entries

CRITICAL RULES:
- Return ONLY valid JSON. No markdown, no code fences, no explanatory text.
- If you find multiple entries, return ALL of them in the array.
- If a field is unreadable or missing, set it to null but still include the field.
- The `amount` MUST be a number (integer or float), NOT a string.
- Do NOT invent or hallucinate data. If you can't read something, set confidence_score lower.

RESPONSE FORMAT (return EXACTLY this JSON structure):
{
  "document_type": "handwritten_register",
  "entries": [
    {
      "donor_name": "Example Name",
      "amount": 1000,
      "date": "28/06/2026",
      "payment_mode": "Cash",
      "confidence_score": 0.95
    }
  ]
}
"""


# ──────────────────────────────────────────────────────────────────────────────
# MAIN PROCESSING FUNCTION
# ──────────────────────────────────────────────────────────────────────────────

def process_image_or_pdf(file_bytes: bytes, mime_type: str) -> dict:
    """
    Sends an image or PDF to Gemini 1.5 Flash for OCR + entity extraction.

    How it works:
    1. Wraps the raw file bytes into a `types.Part.from_bytes` object.
       This tells the Gemini API: "here's an inline file, with this MIME type".
    2. Sends the file + our extraction prompt to the model.
    3. Parses the JSON response from the model.
    4. Returns a dictionary with `document_type` and `entries`.

    Args:
        file_bytes: The raw binary content of the uploaded file.
                    Obtained from FastAPI's UploadFile.read().
        mime_type:  The MIME type of the file, e.g., "image/jpeg", "image/png",
                    "application/pdf". This tells Gemini how to interpret the bytes.

    Returns:
        A dictionary like:
        {
            "document_type": "handwritten_register",
            "entries": [
                {"donor_name": "...", "amount": 1000, "date": "...", ...},
                ...
            ]
        }

    Raises:
        ValueError: If the model returns invalid (non-parseable) JSON.
        Exception: If the Gemini API call itself fails (network error, auth error, etc.)
    """

    # ── Step 1: Create an inline data part from the file bytes ──
    # types.Part.from_bytes() wraps raw bytes + MIME type into a format
    # that Gemini understands. This is the "inline data" approach
    # (as opposed to the File API which uploads to Google's servers first).
    # Inline data is best for files under 20MB.
    file_part = types.Part.from_bytes(
        data=file_bytes,     # The actual binary content of the image/PDF
        mime_type=mime_type   # Tells Gemini if it's JPEG, PNG, PDF, etc.
    )

    # ── Step 2: Send the file + prompt to Gemini ──
    # _get_client() returns the lazily-initialized Gemini client.
    # .models.generate_content() is the main method to get AI responses.
    # - model: which Gemini model to use. "gemini-1.5-flash" is fast and cheap.
    # - contents: a list of "parts" that make up the prompt.
    #   We send the file first, then our text instructions.
    #   The model sees both and generates a response based on both.
    client = _get_client()
    response = client.models.generate_content(
        model="gemini-1.5-flash",       # Fast multimodal model
        contents=[file_part, EXTRACTION_PROMPT]  # Image + instructions
    )

    # ── Step 3: Extract the text from the response ──
    # response.text contains the model's text output (should be JSON).
    raw_text = response.text

    # ── Step 4: Clean up the response ──
    # Sometimes the model wraps its JSON in markdown code fences like:
    # ```json
    # { ... }
    # ```
    # We need to strip those away to get pure JSON.
    # .strip() removes leading/trailing whitespace.
    cleaned_text = raw_text.strip()

    # Check if the response starts with ```json or ``` and remove it
    if cleaned_text.startswith("```json"):
        cleaned_text = cleaned_text[7:]    # Remove the first 7 chars ("```json")
    elif cleaned_text.startswith("```"):
        cleaned_text = cleaned_text[3:]    # Remove the first 3 chars ("```")

    # Remove trailing ``` if present
    if cleaned_text.endswith("```"):
        cleaned_text = cleaned_text[:-3]   # Remove the last 3 chars

    cleaned_text = cleaned_text.strip()     # Clean up any remaining whitespace

    # ── Step 5: Parse the JSON ──
    try:
        # json.loads() converts a JSON string into a Python dictionary/list.
        # If the string is not valid JSON, it raises json.JSONDecodeError.
        parsed = json.loads(cleaned_text)
    except json.JSONDecodeError as e:
        # If parsing fails, raise a clear error with the raw text for debugging.
        raise ValueError(
            f"Gemini returned invalid JSON. Raw response:\n{raw_text}\n"
            f"Parse error: {e}"
        )

    # ── Step 6: Extract and return the structured data ──
    # The parsed response should have "document_type" and "entries" keys
    # (as specified in our prompt). We use .get() with defaults for safety.
    return {
        "document_type": parsed.get("document_type", "handwritten_register"),
        "entries": parsed.get("entries", [])
    }
