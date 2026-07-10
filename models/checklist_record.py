"""
models/checklist_record.py
-----------------------------
Generalized model for gated checklists: Management of Change (MOC) logs
(template Section 11) and Pre-Startup Safety Review (PSSR) checklists
(template Section 13). Both are "a list of items that must be worked
through," just with different item shapes -- so items is a flexible
list of dicts rather than a rigid sub-model. The UI for each renders
different columns from the same underlying record.

Kept as a plain dataclass (no ORM) since persistence is a flat JSON file
(see services/storage.py).
"""

from dataclasses import dataclass, field, asdict
import uuid


@dataclass
class ChecklistRecord:
    checklist_type: str            # "PSSR" | "MOC"  -- see CHECKLIST_TYPE_CHOICES below
    title: str = ""                 # e.g. an MOC change description, or "PSSR - Unit 1 Recommissioning"
    items: list = field(default_factory=list)
    # PSSR item shape: {"item": str, "completed": "Y"/"N", "verified_by": str, "date": str}
    # MOC item shape:  {"change_id": str, "equipment_process": str, "description": str,
    #                    "date_identified": str, "moc_completed": "Y"/"N",
    #                    "reviewed_by": str, "corrective_action": str}
    linked_equipment: str = ""
    status: str = "Open"            # "Open" | "Complete"
    source: str = "Manually Added"  # "AI-Extracted" or "Manually Added"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "ChecklistRecord":
        known_fields = {f: data[f] for f in ChecklistRecord.__dataclass_fields__ if f in data}
        return ChecklistRecord(**known_fields)

    def percent_complete(self) -> float:
        """Not a dataclass field -- computed on demand from items, since
        it must always reflect current item state, never go stale."""
        if not self.items:
            return 0.0
        done_key = "completed" if self.checklist_type == "PSSR" else "moc_completed"
        done = sum(1 for i in self.items if i.get(done_key) in ("Y", "Yes", True))
        return round(100 * done / len(self.items), 1)


CHECKLIST_TYPE_CHOICES = ["PSSR", "MOC"]

# The 8 standard PSSR items from the Facility Onboarding Template --
# pre-populated on a facility's first visit to the PSSR screen if no
# PSSR checklist exists yet (see routes/factory_routes.py).
STANDARD_PSSR_ITEMS = [
    "P&IDs reflect as-built condition",
    "Safety systems (interlocks, relief devices) tested and operational",
    "Operating procedures updated and available to operators",
    "Emergency procedures reviewed with operating team",
    "All operators trained on the new/modified unit",
    "Environmental permits and clearances in place",
    "Equipment leak-tested prior to introducing hazardous material",
    "Fire and gas detection systems commissioned and tested",
]