"""
app.py
--------
Application entry point. Creates the Flask app and registers blueprints.

Run with:
    python app.py

Then open http://127.0.0.1:5000 in your browser.

See README.md for full setup instructions (virtual environment,
dependencies, .env configuration, and how to run the test suite).
"""

from flask import Flask

import os
from config import Config
from routes.main_routes import main_bp
from routes.factory_routes import factory_bp
from routes.monitor_routes import monitor_bp
from services.layout_extraction import warmup_ocr_async


def create_app() -> Flask:
    """Application factory — makes the app easy to import and test
    (see tests/test_app.py) without starting a real server."""
    _FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
    app = Flask(
        __name__,
        template_folder=os.path.join(_FRONTEND_DIR, "templates"),
        static_folder=os.path.join(_FRONTEND_DIR, "static"),
    )   
    app.config.from_object(Config)

    app.register_blueprint(main_bp)
    app.register_blueprint(factory_bp)
    app.register_blueprint(monitor_bp)

    from db import init_db
    init_db()

    # Best-effort, non-blocking: starts loading EasyOCR's model now
    # instead of waiting for someone to click "Detect Layout from PDF" --
    # see services/layout_extraction.py's warmup_ocr_async() docstring.
    warmup_ocr_async()

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
