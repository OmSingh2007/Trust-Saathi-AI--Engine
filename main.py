"""
main.py — TrustSaathi AI Engine Entry Point
============================================
This is the main FastAPI application. It:
  1. Accepts file uploads via POST /extract
  2. Routes the file to the correct processor (Gemini AI for images/PDFs, Pandas for Excel/CSV)
  3. Standardizes the extracted data (dates, amounts, payment modes)
  4. Runs fuzzy duplicate detection on donor names
  5. Returns the clean JSON payload matching Developer 2's API contract
  6. Optionally forwards the data to Developer 2's backend

Run with: uvicorn main:app --reload --port 8000
"""

import httpx                               # Async HTTP client — used to forward data to Developer 2's API
from fastapi import FastAPI, File, UploadFile, HTTPException  # Core FastAPI components
from fastapi.middleware.cors import CORSMiddleware            # Enables cross-origin requests

from config import BACKEND_API_URL         # Developer 2's API URL (from .env)

# Import our processing services
from services.gemini_processor import process_image_or_pdf
from services.excel_processor import process_excel_or_csv

# Import our utility functions
from utils.standardizer import standardize_date, standardize_payment_mode, standardize_amount
from utils.deduplicator import find_duplicates


# ──────────────────────────────────────────────────────────────────────────────
# APP INITIALIZATION
# ──────────────────────────────────────────────────────────────────────────────

# FastAPI() creates the main application instance.
# title, description, version are metadata shown in the auto-generated API docs at /docs.
app = FastAPI(
    title="TrustSaathi AI Engine",
    description="AI-powered OCR and data extraction service for NGO donation documents",
    version="1.0.0",
)

# ── CORS Middleware ──
# CORS (Cross-Origin Resource Sharing) controls which websites can call our API.
# During development, we allow ALL origins (*) so any frontend can connect.
# In production, you'd restrict this to specific domains.
#
# add_middleware() attaches middleware that runs on EVERY request/response.
# Middleware is like a "filter" that processes requests before they reach your endpoint
# and processes responses before they go back to the client.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],         # Which domains can access the API ("*" = all)
    allow_credentials=True,      # Allow cookies/auth headers
    allow_methods=["*"],         # Allow all HTTP methods (GET, POST, PUT, DELETE)
    allow_headers=["*"],         # Allow all HTTP headers
)


# ──────────────────────────────────────────────────────────────────────────────
# MIME TYPE SETS — Used to route files to the correct processor
# ──────────────────────────────────────────────────────────────────────────────

# These sets define which MIME types we accept for each processing path.
# A MIME type is a standard label for file formats (like "image/jpeg" or "application/pdf").
# When a browser uploads a file, it sends the MIME type in the request header.

IMAGE_PDF_MIME_TYPES: set[str] = {
    "image/jpeg",           # .jpg, .jpeg files
    "image/png",            # .png files
    "image/webp",           # .webp files (modern web image format)
    "image/tiff",           # .tiff files (common in scanned documents)
    "application/pdf",      # .pdf files
}

EXCEL_CSV_MIME_TYPES: set[str] = {
    # This long string is the official MIME type for .xlsx files (modern Excel)
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    # Legacy .xls Excel format
    "application/vnd.ms-excel",
    "text/csv",             # .csv files
}


# ──────────────────────────────────────────────────────────────────────────────
# HEALTH CHECK ENDPOINT
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """
    Simple health check endpoint.
    Returns {"status": "healthy"} if the server is running.
    Useful for monitoring tools, load balancers, and Docker health checks.

    @app.get("/health") is a "decorator" — it tells FastAPI:
    "When someone sends a GET request to /health, run this function."
    """
    return {"status": "healthy", "service": "TrustSaathi AI Engine"}


# ──────────────────────────────────────────────────────────────────────────────
# MAIN EXTRACTION ENDPOINT
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/extract")
async def extract_data(file: UploadFile = File(...)):
    """
    POST /extract — Main endpoint that accepts a file upload and returns
    standardized donation data.

    How it works:
    1. Validate the file type (is it an image, PDF, or Excel/CSV?)
    2. Read the file bytes into memory
    3. Route to the correct processor:
       - Image/PDF → Gemini AI (OCR + extraction)
       - Excel/CSV → Pandas (column mapping + extraction)
    4. Standardize all extracted data (dates, amounts, payment modes)
    5. Run duplicate detection on donor names
    6. Return the JSON payload matching Developer 2's contract
    7. Optionally forward to Developer 2's API

    Args:
        file: The uploaded file, received as multipart/form-data.
              FastAPI's UploadFile provides: .filename, .content_type, .read()
              File(...) means this parameter is REQUIRED (the "..." is Ellipsis,
              which in FastAPI means "this field is mandatory").

    Returns:
        JSON matching the exact contract:
        {
            "status": "success",
            "document_type": "handwritten_register" | "excel" | "receipt",
            "extracted_data": [ ... ]
        }
    """

    # ── Step 1: Validate File Type ──

    # file.content_type is the MIME type sent by the browser/client.
    # We check if it's in one of our supported sets.
    mime_type = file.content_type

    # Combine both sets to get ALL supported MIME types
    all_supported = IMAGE_PDF_MIME_TYPES | EXCEL_CSV_MIME_TYPES
    # The "|" operator on sets means "union" — it creates a new set containing
    # all elements from both sets.

    if mime_type not in all_supported:
        # HTTPException is FastAPI's way of returning error responses.
        # status_code=400 means "Bad Request" — the client sent something wrong.
        # detail= is the error message sent back to the client.
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type: '{mime_type}'. "
                f"Supported types: Images (JPEG, PNG, WebP, TIFF), PDF, Excel (.xlsx), CSV."
            )
        )

    # ── Step 2: Read File Bytes ──

    # await file.read() reads the entire file content into memory as bytes.
    # "await" is used because file.read() is an async operation — it doesn't
    # block the server while reading (other requests can be handled meanwhile).
    file_bytes = await file.read()

    # ── Step 3: Route to the Correct Processor ──

    try:
        if mime_type in IMAGE_PDF_MIME_TYPES:
            # Send image/PDF to Gemini AI for OCR + extraction
            result = process_image_or_pdf(file_bytes, mime_type)
        else:
            # Process Excel/CSV with pandas
            result = process_excel_or_csv(file_bytes, file.filename)

    except ValueError as e:
        # ValueError is raised by our processors for known issues
        # (e.g., Gemini returned invalid JSON, or no columns could be mapped)
        raise HTTPException(status_code=422, detail=str(e))
        # 422 = "Unprocessable Entity" — the file was received but couldn't be processed

    except Exception as e:
        # Catch any unexpected error (API failure, network issue, etc.)
        raise HTTPException(
            status_code=500,
            detail=f"Processing failed: {str(e)}"
        )
        # 500 = "Internal Server Error" — something went wrong on our side

    # ── Step 4: Standardize the Extracted Data ──

    # result["entries"] is a list of dicts, each representing one donation record.
    # We clean each record's date, amount, and payment_mode.
    entries = result.get("entries", [])

    standardized_entries: list[dict] = []

    for entry in entries:
        standardized_entry = {
            # Donor name: just strip whitespace, convert to string
            # str() ensures it's a string even if the AI returned something else.
            # .strip() removes leading/trailing spaces.
            "donor_name": str(entry.get("donor_name", "")).strip() if entry.get("donor_name") else None,

            # Amount: clean and convert to float using our utility function
            "amount": standardize_amount(entry.get("amount")),

            # Date: parse any format and convert to YYYY-MM-DD
            "date": standardize_date(str(entry.get("date", ""))) if entry.get("date") else None,

            # Payment mode: normalize to standard categories (UPI, CASH, etc.)
            "payment_mode": standardize_payment_mode(str(entry.get("payment_mode", ""))),

            # Confidence score: keep as-is, but ensure it's a float between 0 and 1
            "confidence_score": _clamp_confidence(entry.get("confidence_score", 0.5)),
        }
        standardized_entries.append(standardized_entry)

    # ── Step 5: Run Duplicate Detection ──

    # find_duplicates adds "duplicate_flag" and "similar_to" fields to each record.
    # This is non-destructive — records are flagged, not removed.
    standardized_entries = find_duplicates(standardized_entries)

    # ── Step 6: Build the Final Response ──

    # This JSON structure is the EXACT contract that Developer 2's API expects.
    response_payload = {
        "status": "success",
        "document_type": result.get("document_type", "unknown"),
        "extracted_data": standardized_entries,
    }

    # ── Step 7: Optionally Forward to Developer 2's API ──

    # Only forward if BACKEND_API_URL is configured in .env
    if BACKEND_API_URL:
        await _forward_to_backend(response_payload)

    return response_payload


# ──────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ──────────────────────────────────────────────────────────────────────────────

def _clamp_confidence(value) -> float:
    """
    Ensures the confidence score is a float between 0.0 and 1.0.

    "Clamping" means forcing a value into a range:
    - If value < 0.0, return 0.0
    - If value > 1.0, return 1.0
    - Otherwise, return the value as-is

    The built-in max() and min() functions are nested:
      max(0.0, min(1.0, value))
    This means: "take the smaller of (1.0, value), then take the larger of (0.0, result)"
    Effectively: 0.0 <= result <= 1.0

    Args:
        value: The raw confidence score (could be any number, or None).

    Returns:
        A float between 0.0 and 1.0.
    """
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        # If value is None or non-numeric, default to 0.5 (uncertain)
        return 0.5


async def _forward_to_backend(payload: dict) -> None:
    """
    Sends the extracted data to Developer 2's backend API.
    This is a "fire-and-forget" operation — if it fails, we log the error
    but don't crash the main request (the user still gets their data).

    How it works:
    - httpx.AsyncClient() creates an async HTTP client (like a browser making a request).
    - async with ... ensures the client connection is properly closed when done.
    - client.post() sends a POST request with JSON body to the target URL.
    - timeout=30.0 means we wait at most 30 seconds for a response.

    Args:
        payload: The JSON payload to send (our standardized extraction result).
    """
    try:
        # "async with" is a context manager that ensures cleanup.
        # httpx.AsyncClient() creates a client; when the block exits,
        # the client closes its connections (no resource leaks).
        async with httpx.AsyncClient() as client:
            response = await client.post(
                BACKEND_API_URL,               # The URL to send to
                json=payload,                   # Automatically serializes dict → JSON
                timeout=30.0                    # Max wait time in seconds
            )

            # response.status_code tells us if the backend accepted the data.
            # 2xx status codes (200, 201, etc.) mean success.
            if response.status_code >= 300:
                # Print a warning but don't crash — the user still gets their data
                print(
                    f"⚠️ Backend forwarding returned status {response.status_code}: "
                    f"{response.text}"
                )
            else:
                print(f"✅ Data forwarded to backend successfully.")

    except httpx.RequestError as e:
        # RequestError covers network failures: DNS errors, connection refused, timeouts, etc.
        # We print the error but don't raise it — this is non-critical functionality.
        print(f"⚠️ Could not forward to backend: {e}")
