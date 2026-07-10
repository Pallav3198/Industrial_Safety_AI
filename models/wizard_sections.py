"""
models/wizard_sections.py
----------------------------
Single source of truth for the order of the 20 Facility Onboarding
Template sections, grouped into Parts A-E. Every wizard page's Back/Next
buttons are computed FROM this list -- never hardcode "the next page is
X" in a route or template. That's what makes "go back to the previous
section" actually work across 20 sections, and what makes adding a 21st
section later a one-line change here instead of a template hunt.

Layout (the Konva canvas editor) is deliberately NOT in this list -- it
isn't a template section, it's a portal-only feature. It stays reachable
from the wizard progress bar and the Facility Details page, but not from
linear Back/Next chaining. Same for Upload and Validate, which happen
before Part A begins.

As of this revision, only 4 of the 20 sections have real routes/pages
built (Sensors, Employees, Negligence History, Attendance) -- the rest
exist here as data now so the navigation mechanism is correct and
future-proof: get_prev_next() below skips over any section whose route
isn't registered yet, and automatically starts including a section the
moment its route exists, with zero further changes to this file or to
the navigation logic in factory_routes.py.
"""

from flask import url_for

# (part, section_number, title, url_slug, route_name)
WIZARD_SECTIONS = [
    ("A", 1, "Facility Overview", "facility-overview", "factory.facility_overview"),
    ("A", 2, "Process Flow Description", "process-flow", "factory.process_flow"),
    ("A", 3, "SCADA / DCS Systems", "scada-systems", "factory.scada_systems"),
    ("A", 4, "Sensor & Instrumentation Details", "sensors", "factory.sensors_page"),
    ("B", 5, "Key Personnel", "key-personnel", "factory.key_personnel"),
    ("B", 6, "Shift & Workforce Patterns", "shift-patterns", "factory.shift_patterns"),
    ("B", 7, "Minimum Staffing Per Task Rules", "staffing-rules", "factory.staffing_rules"),
    ("B", 8, "Employee Directory", "employees", "factory.employees_page"),
    ("C", 9, "Maintenance Records & Timelines", "maintenance", "factory.maintenance_records"),
    ("C", 10, "Equipment / Asset Registry", "asset-registry", "factory.asset_registry"),
    ("C", 11, "Management of Change (MOC) Log", "moc-log", "factory.moc_log"),
    ("D", 12, "Permit-to-Work Register", "permits", "factory.permits"),
    ("D", 13, "Pre-Startup Safety Review (PSSR)", "pssr", "factory.pssr_checklist"),
    ("D", 14, "Contractor Oversight Register", "contractors", "factory.contractor_oversight"),
    ("E", 15, "Incident & Negligence History", "negligence", "factory.negligence_page"),
    ("E", 16, "Attendance & Access Control", "attendance", "factory.attendance_page"),
    ("E", 17, "Utility & Support Systems", "utilities", "factory.utility_systems"),
    ("E", 18, "Training & Certification Records", "training", "factory.training_records"),
    ("E", 19, "Environmental & Quality Compliance", "environmental", "factory.environmental_compliance"),
    ("E", 20, "Emergency Response & Compliance", "emergency-response", "factory.emergency_response"),
]


def get_section(index):
    """Returns the WIZARD_SECTIONS tuple at index, or None if out of range."""
    if 0 <= index < len(WIZARD_SECTIONS):
        return WIZARD_SECTIONS[index]
    return None


def find_section_index(route_name):
    for i, s in enumerate(WIZARD_SECTIONS):
        if s[4] == route_name:
            return i
    return -1


def safe_url_for(route_name, **kwargs):
    """Like Flask's url_for, but returns None instead of raising if the
    route isn't registered yet -- lets get_prev_next() below skip past
    template sections that don't have a page built yet without crashing."""
    try:
        return url_for(route_name, **kwargs)
    except Exception:
        return None


def get_prev_next(route_name, factory_id, fallback_prev=None, fallback_next=None):
    """
    Returns (prev_nav, next_nav), each either None or a dict
    {"url": ..., "label": ...}, for rendering Back/Next buttons.

    Skips over registry entries whose route isn't registered yet (i.e.
    sections not built in a later phase), continuing to search further
    in that direction rather than stopping there. If the search reaches
    a registry boundary without finding a buildable route, returns the
    given fallback instead (used so e.g. Sensors' Back button can still
    point at the Validate page, which isn't in this registry at all).
    """
    idx = find_section_index(route_name)
    if idx == -1:
        return fallback_prev, fallback_next

    prev_nav = fallback_prev
    for i in range(idx - 1, -1, -1):
        section = WIZARD_SECTIONS[i]
        url = safe_url_for(section[4], factory_id=factory_id)
        if url:
            prev_nav = {"url": url, "label": section[2]}
            break

    next_nav = fallback_next
    for i in range(idx + 1, len(WIZARD_SECTIONS)):
        section = WIZARD_SECTIONS[i]
        url = safe_url_for(section[4], factory_id=factory_id)
        if url:
            next_nav = {"url": url, "label": section[2]}
            break

    return prev_nav, next_nav


def get_first_available_section(factory_id):
    """Returns {"url": ..., "label": ...} for the first registry section
    whose route is registered, or None if none are yet. Used by pages
    before Part A (Upload, Validate) to know where "Next" should go,
    without hardcoding which section is currently first-in-line -- as
    Sections 1-3 land in later phases, this automatically starts
    pointing at Section 1 instead of Section 4, with no code change
    here."""
    for section in WIZARD_SECTIONS:
        url = safe_url_for(section[4], factory_id=factory_id)
        if url:
            return {"url": url, "label": section[2]}
    return None