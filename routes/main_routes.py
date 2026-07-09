"""
routes/main_routes.py
------------------------
Landing page and any top-level navigation routes.

Landing page now shows three real sections (renamed from the previous
two-card + one-placeholder layout):
  1. Add Facility        -- fully built (this is the multi-step wizard)
  2. View / Edit Facility -- placeholder, not built in this version
  3. Monitor Facility     -- placeholder, not built in this version
"""

from flask import Blueprint, render_template
from services import storage

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def landing():
    factories = storage.list_factories()
    completed_count = sum(1 for f in factories if f.setup_complete)
    return render_template(
        "landing.html",
        factory_count=len(factories),
        completed_count=completed_count,
    )
