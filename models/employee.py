"""
models/employee.py
--------------------
Data model for a single employee record attached to a factory.

Mirrors the Sensor model's pattern exactly (same dataclass shape,
same to_dict/from_dict, same "source" AI-Extracted/Manually Added
distinction) so the Employees screen can reuse the same CRUD pattern
(and the same add/edit/delete JS logic) as the Sensors screen.
"""

from dataclasses import dataclass, field, asdict
import uuid


@dataclass
class Employee:
    name: str
    role: str = ""                     # e.g. "Shift Engineer", "Maintenance Technician"
    department: str = ""               # e.g. "Boiler Operations", "Safety"
    manager_id: str = ""               # id of another Employee on the same facility, "" = no manager / top-level
    email: str = ""
    phone: str = ""
    blood_group: str = ""              # e.g. "O+", "AB-"
    working_hours: str = ""            # e.g. "6:00 AM - 2:00 PM"
    working_days: str = ""             # e.g. "Mon-Fri", "Rotating Shift A"
    emergency_contact_name: str = ""
    emergency_contact_phone: str = ""
    emergency_contact_relation: str = ""  # e.g. "Spouse", "Parent"
    notes: str = ""
    source: str = "Manually Added"     # "AI-Extracted" or "Manually Added"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "Employee":
        known_fields = {f: data[f] for f in Employee.__dataclass_fields__ if f in data}
        return Employee(**known_fields)


# Dropdown choices for the Add/Edit Employee form.
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
