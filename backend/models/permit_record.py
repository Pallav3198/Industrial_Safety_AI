"""
models/permit_record.py
--------------------------
Model for the Permit-to-Work Register (template Section 12) -- active
or recently-closed work authorizations (Hot Work, Confined Space,
Electrical, Working at Height, Excavation, General). This is a
time-bounded authorization record, a genuinely different shape from a
MonitoredParameter (no ongoing value/threshold) or a ChecklistRecord
(no item list) -- kept as its own small model rather than forced into
either.

Kept as a plain dataclass (no ORM) since persistence is a flat JSON file
(see services/storage.py).
"""

from dataclasses import dataclass, field, asdict
import uuid


@dataclass
class PermitRecord:
    permit_number: str
    permit_type: str = ""          # see PERMIT_TYPE_CHOICES below
    location_equipment: str = ""
    issued_to: str = ""
    issued_at: str = ""
    expires_at: str = ""
    status: str = "Active"         # "Active" | "Closed"
    notes: str = ""
    source: str = "Manually Added"  # "AI-Extracted" or "Manually Added"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "PermitRecord":
        known_fields = {f: data[f] for f in PermitRecord.__dataclass_fields__ if f in data}
        return PermitRecord(**known_fields)


PERMIT_TYPE_CHOICES = [
    "Hot Work",
    "Confined Space",
    "Electrical",
    "Working at Height",
    "Excavation",
    "General",
]

PERMIT_STATUS_CHOICES = ["Active", "Closed"]