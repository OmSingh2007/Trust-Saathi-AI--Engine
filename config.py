"""
config.py — Centralized Configuration Loader
=============================================
Loads environment variables from a .env file using python-dotenv,
then exposes them as simple Python variables for the rest of the app.
"""

import os                          # Built-in module to access environment variables
from dotenv import load_dotenv     # Reads key=value pairs from a .env file and sets them as env vars

# load_dotenv() searches for a file named ".env" in the current directory
# and loads all the key=value pairs into the system's environment variables.
# This means os.getenv("KEY") will now return the value from .env.
load_dotenv()

# --- Gemini API Key ---
# os.getenv("GEMINI_API_KEY") reads the value of GEMINI_API_KEY from environment.
# If the variable is not set, it returns None (no default = will fail at runtime if missing).
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY")

# --- Developer 2's Backend URL ---
# This is the URL where we'll forward the extracted data.
# os.getenv("BACKEND_API_URL", "") provides an empty string as default,
# meaning if the variable isn't set, we just won't forward data (graceful fallback).
BACKEND_API_URL: str = os.getenv("BACKEND_API_URL", "")
