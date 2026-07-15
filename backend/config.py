"""
config.py
----------
Central configuration for the Factory AI Portal.

All settings are read from environment variables (loaded from a local
".env" file if one exists, via python-dotenv). Nothing sensitive is
hard-coded here — copy .env.example to .env and fill in your own values.
"""

import os
from dotenv import load_dotenv

# Load variables from a .env file in the project root, if one exists.
# Safe to call even if no .env file is present.
load_dotenv()


class Config:
    # --- Flask -------------------------------------------------------
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-me")

    # --- File uploads --------------------------------------------------
    UPLOAD_FOLDER = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "static", "uploads"
    )
    # No upload size limit, per product requirement. Note: the underlying
    # Gemini API still has its own document size limits — see README
    # "Known Limitations" for details.
    MAX_CONTENT_LENGTH = None
    ALLOWED_EXTENSIONS = {"pdf"}

    # --- Data storage ----------------------------------------------------
    # Simple JSON-file "database" — no external DB required for this
    # prototype. See services/storage.py.
    DATA_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    FACTORIES_FILE = os.path.join(DATA_FOLDER, "factories.json")

    # --- AI extraction ----------------------------------------------------
    # Using Google's Gemini API instead of Claude -- it has a genuinely
    # free tier (no credit card, no expiring credits) with native PDF
    # support, a good fit for a hackathon prototype you need to test and
    # demo repeatedly at no cost. Get a free key at
    # https://aistudio.google.com/apikey
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    # If no API key is configured, the app automatically falls back to a
    # fixed mock extractor (services/ai_extraction.py) so the full UI/UX
    # flow can still be built, demoed, and tested completely offline.
    USE_MOCK_AI = GEMINI_API_KEY == ""
