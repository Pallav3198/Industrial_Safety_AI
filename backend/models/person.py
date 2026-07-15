"""
models/person.py
------------------
Generalized model for any person tracked at a facility: rank-and-file
employees, managerial staff, maintenance staff, safety officers, and
contractors. Replaces the old models/employee.py -- Employee is renamed
to Person and gains a person_category so the Key Personnel screen
(template Section 5), the Employee Directory (Section 8), and the
Contractor Oversight Register (Section 14) all share one model and one
CRUD/UI pattern instead of three overlapping tables that could drift
out of sync with each other.

Kept as a plain dataclass (no ORM) since persistence is a flat JSON file
(see services/storage.py).
"""

from dataclasses import dataclass, field, asdict
import uuid


@dataclass
class Person:
    name: str
    person_category: str = "Employee"
    # "Employee" | "Managerial Staff" | "Maintenance Staff" | "Safety Officer" | "Contractor"
    # See PERSON_CATEGORY_CHOICES below. Which fields further down are
    # relevant depends on this value -- see the section comments.

    role: str = ""                     # e.g. "Shift Engineer", "Maintenance Technician"
    department: str = ""               # e.g. "Boiler Operations", "Safety"
    manager_id: str = ""               # id of another Person on the same facility, "" = no manager / top-level
    email: str = ""
    phone: str = ""
    blood_group: str = ""              # e.g. "O+", "AB-"
    working_hours: str = ""            # e.g. "6:00 AM - 2:00 PM"
    working_days: str = ""             # e.g. "Mon-Fri", "Rotating Shift A"
    emergency_contact_name: str = ""
    emergency_contact_phone: str = ""
    emergency_contact_relation: str = ""  # e.g. "Spouse", "Parent"

    # --- Maintenance Staff-only field (template Section 5.2) ---------------
    certifications: str = ""

    # --- Contractor-only fields (person_category == "Contractor", template Section 14) ---
    scope_of_work: str = ""
    joint_hazop_conducted: str = ""        # "Y" / "N"
    last_joint_inspection_date: str = ""
    safety_induction_completed: str = ""   # "Y" / "N"
    supervising_employee: str = ""

    notes: str = ""
    source: str = "Manually Added"     # "AI-Extracted" or "Manually Added"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "Person":
        known_fields = {f: data[f] for f in Person.__dataclass_fields__ if f in data}
        return Person(**known_fields)


# Dropdown choices for the Add/Edit Person form.
PERSON_CATEGORY_CHOICES = [
    "Employee",
    "Managerial Staff",
    "Maintenance Staff",
    "Safety Officer",
    "Contractor",
]

DEPARTMENT_CHOICES = [
    "Management",
    "Boiler / Furnace Operations",
    "Maintenance",
    "Safety",
    "Coal / Material Handling",
    "Electrical",
    "Instrumentation & Control",
    "Security",
    "Administration",
    "Other",
]

BLOOD_GROUP_CHOICES = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-", "Unknown"]