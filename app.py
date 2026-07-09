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

from config import Config
from routes.main_routes import main_bp
from routes.factory_routes import factory_bp


def create_app() -> Flask:
    """Application factory — makes the app easy to import and test
    (see tests/test_app.py) without starting a real server."""
    app = Flask(__name__)
    app.config.from_object(Config)

    app.register_blueprint(main_bp)
    app.register_blueprint(factory_bp)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
