"""
models/rule_catalog.py
--------------------------
Single source of truth for what a rule condition can reference: one
entry per facility onboarding section, each with a fixed set of
condition types (never free-text) so every rule built in the UI always
maps to something real in the data model. See models/rule.py for how
this is assembled into a condition tree.

Each condition type carries:
  key            -- stored in Condition.condition_type
  label          -- shown in the builder UI
  takes_value    -- whether this condition type needs an operator+value
                     (e.g. "faulted for >= N hours") or is a plain
                     yes/no check (e.g. "maintenance overdue")
  live_data_pending -- True if this condition type can't be evaluated
                     yet because the value it checks isn't stored
                     anywhere (live sensor readings, live attendance %,
                     live headcount). False means it's evaluable today
                     from data the wizard already collects (dates,
                     configured flags, planned numbers). Purely
                     informational -- shown in the builder UI as a
                     badge -- since evaluation itself isn't built yet.
"""

RULE_CONDITION_CATALOG = {
    "sensors": {
        "label": "Sensors & Instrumentation",
        "record_source": "monitored_parameters",   # filtered to parameter_category == "Live Sensor Reading"
        "condition_types": [
            {"key": "alarm_breach", "label": "Parameter is in alarm (above/below its configured threshold)", "takes_value": False, "live_data_pending": True},
            {"key": "faulted_duration", "label": "Faulted for at least N hours", "takes_value": True, "live_data_pending": False},
            {"key": "data_source_inactive", "label": "Data source connection inactive", "takes_value": False, "live_data_pending": False},
        ],
    },
    "scada": {
        "label": "SCADA / DCS Systems",
        "record_source": "scada_systems",
        "condition_types": [
            {"key": "no_redundancy", "label": "System has no redundancy configured", "takes_value": False, "live_data_pending": False},
        ],
    },
    "attendance": {
        "label": "Attendance & Access Control",
        "record_source": None,
        "condition_types": [
            {"key": "attendance_below_pct", "label": "Attendance below X%", "takes_value": True, "live_data_pending": True},
            {"key": "api_inactive", "label": "Attendance API connection inactive", "takes_value": False, "live_data_pending": False},
        ],
    },
    "escalation": {
        "label": "Escalation Logic",
        "record_source": "escalation_logic",
        "condition_types": [
            {"key": "no_contact_configured", "label": "No contact configured for this escalation level", "takes_value": False, "live_data_pending": False},
        ],
    },
    "shifts": {
        "label": "Shift & Workforce Patterns",
        "record_source": "shift_patterns",
        "condition_types": [
            {"key": "planned_headcount_below", "label": "Planned headcount below N", "takes_value": True, "live_data_pending": False},
        ],
    },
    "staffing": {
        "label": "Minimum Staffing Per Task Rules",
        "record_source": "monitored_parameters",   # filtered to parameter_category == "Staffing Rule"
        "condition_types": [
            {"key": "understaffed", "label": "Current headcount below minimum required", "takes_value": False, "live_data_pending": True},
        ],
    },
    "maintenance": {
        "label": "Maintenance Records & Timelines",
        "record_source": "maintenance_records",
        "condition_types": [
            {"key": "overdue", "label": "Maintenance overdue (past next-due date)", "takes_value": False, "live_data_pending": False},
            {"key": "deferred", "label": "Maintenance deferred (has deferred notes)", "takes_value": False, "live_data_pending": False},
        ],
    },
    "assets": {
        "label": "Equipment / Asset Registry",
        "record_source": "monitored_parameters",   # filtered to parameter_category == "Compliance Due-Date"
        "condition_types": [
            {"key": "compliance_overdue", "label": "Compliance due-date overdue", "takes_value": False, "live_data_pending": False},
        ],
    },
    "moc": {
        "label": "Management of Change (MOC) Log",
        "record_source": "checklist_records",
        "condition_types": [
            {"key": "item_incomplete", "label": "Change item still incomplete", "takes_value": False, "live_data_pending": False},
        ],
    },
    "pssr": {
        "label": "Pre-Startup Safety Review (PSSR)",
        "record_source": "checklist_records",
        "condition_types": [
            {"key": "item_incomplete", "label": "PSSR item still incomplete", "takes_value": False, "live_data_pending": False},
        ],
    },
    "permits": {
        "label": "Permit-to-Work Register",
        "record_source": "permit_records",
        "condition_types": [
            {"key": "overdue_or_invalid", "label": "Permit overdue or invalid", "takes_value": False, "live_data_pending": False},
        ],
    },
    "contractors": {
        "label": "Contractor Oversight Register",
        "record_source": "people",   # filtered to person_category == "Contractor"
        "condition_types": [
            {"key": "no_joint_hazop", "label": "Joint HAZOP not conducted", "takes_value": False, "live_data_pending": False},
            {"key": "no_safety_induction", "label": "Safety induction not completed", "takes_value": False, "live_data_pending": False},
        ],
    },
    "training": {
        "label": "Training & Certification Records",
        "record_source": None,
        "condition_types": [
            {"key": "drill_overdue", "label": "Emergency drill overdue", "takes_value": False, "live_data_pending": False},
        ],
    },
    "environmental": {
        "label": "Environmental & Quality Compliance",
        "record_source": None,
        "condition_types": [
            {"key": "certificate_missing", "label": "A required compliance certificate is missing", "takes_value": False, "live_data_pending": False},
        ],
    },
}