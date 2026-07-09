"""
models/factory.py
-------------------
Data model for a Factory record. Covers the full Add Facility wizard:
profile + uploaded document, AI extraction results (sensors, employees,
process summary), document validation (missing sections + clarifying
Q&A), incident/negligence history, and the attendance system API config.

NOTE ON NAMING: the person-facing product now calls this flow "Add
Facility" (renamed from "Add Factory"). Internally, the code still uses
"Factory"/"factory" throughout (module names, variable names, URL
routes) to avoid a large, risky rename across the whole codebase for a
label-only change. Only user-facing text says "Facility".
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict
import uuid

from models.sensor import Sensor
from models.employee import Employee


@dataclass
class Factory:
    name: str
    preliminary_doc_filename: str = ""

    # --- AI extraction results -------------------------------------------
    ai_summary: str = ""                          # process understanding write-up
    sensors: List[Sensor] = field(default_factory=list)
    employees: List[Employee] = field(default_factory=list)

    # --- Document validation (Step 2: chatbot-style gap filling) ----------
    missing_sections: List[str] = field(default_factory=list)     # sections the AI found incomplete/absent
    clarification_qa: List[Dict[str, str]] = field(default_factory=list)  # [{"question": ..., "answer": ...}, ...]
    validation_complete: bool = False

    # --- Incident / negligence history (Step 5) ----------------------------
    negligence_history: str = ""
    # --- Facility layout (Step 6) -------------------------------------------
    # A flat list of plain dicts exported by the Konva.js canvas editor,
    # e.g. [{"type": "machine", "x": 100, "y": 100, "width": 140,
    # "height": 80, "label": "Boiler Unit 1"}, {"type": "text", ...},
    # {"type": "line", "points": [x1, y1, x2, y2]}, ...]. Stored as-is --
    # these are plain dicts (not a dataclass) so no to_dict/from_dict
    # conversion is needed, unlike sensors/employees.
    layout_data: List[Dict] = field(default_factory=list)
    
    # --- Attendance system integration (Step 7) -----------------------------
    attendance_api_url: str = ""
    attendance_api_method: str = "GET"
    attendance_api_headers: str = ""
    attendance_api_status: str = "Not Tested"      # "Not Tested" / "Active" / "Inactive"
    attendance_api_last_tested: str = ""

    setup_complete: bool = False                   # True once the full wizard has been finished

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        d = asdict(self)
        # asdict() recurses into dataclasses automatically, but we keep this
        # explicit conversion so the intent is obvious and safe against
        # future edits to Sensor/Employee's structure.
        d["sensors"] = [s.to_dict() if isinstance(s, Sensor) else s for s in self.sensors]
        d["employees"] = [e.to_dict() if isinstance(e, Employee) else e for e in self.employees]
        return d

    @staticmethod
    def from_dict(data: dict) -> "Factory":
        sensors = [Sensor.from_dict(s) for s in data.get("sensors", [])]
        employees = [Employee.from_dict(e) for e in data.get("employees", [])]
        known_fields = {
            f: data[f]
            for f in Factory.__dataclass_fields__
            if f in data and f not in ("sensors", "employees")
        }
        factory = Factory(**known_fields)
        factory.sensors = sensors
        factory.employees = employees
        return factory
    
    def get_wizard_step_status(self) -> Dict[int, str]:
        """Returns {step_number: status} for all 7 Add Facility wizard
        steps, where status is one of:
          "done"    -- green check    -- the step's data is objectively complete
          "warning" -- yellow "!"     -- the step has been reached but needs attention
          "pending" -- grey           -- nothing entered for this step yet

        Used by partials/wizard_progress.html to color/icon each tab, and
        by facility_details.html to decide whether to show the
        "Train & Configure AI" button (only once every step is "done").

        These are intentionally simple, deterministic, data-presence
        checks -- not a tracked "has the user visited this page" flag,
        since steps can now be visited in any order via the clickable
        wizard tabs, not just sequentially.
        """
        status = {}

        # Step 1 (Upload): always done for any existing factory record --
        # you cannot reach any other step without having uploaded a
        # document first.
        status[1] = "done" if self.preliminary_doc_filename else "pending"

        # Step 2 (Validate): done once the chat Q&A has been submitted.
        # Not "pending" even before that, because clarification_qa is
        # always seeded immediately after Step 1's AI extraction runs --
        # there's always something here that needs an explicit answer.
        status[2] = "done" if self.validation_complete else "warning"

        # Step 3 (Sensors): done if at least one sensor is configured.
        status[3] = "done" if self.sensors else "pending"

        # Step 4 (Layout): done if at least one shape has been placed.
        status[4] = "done" if self.layout_data else "pending"

        # Step 5 (Negligence history): done if any text has been entered.
        status[5] = "done" if self.negligence_history.strip() else "pending"

        # Step 6 (Employees): done if at least one employee is on record.
        status[6] = "done" if self.employees else "pending"

        # Step 7 (Attendance): done only if the configured API actually
        # tested as reachable; warning if configured but not confirmed
        # working; pending if nothing has been entered at all.
        if self.attendance_api_status == "Active":
            status[7] = "done"
        elif self.attendance_api_url:
            status[7] = "warning"
        else:
            status[7] = "pending"

        return status

    def is_fully_configured(self) -> bool:
        """True once every wizard step reports 'done' -- used to decide
        whether to show the 'Train & Configure AI' button."""
        return all(s == "done" for s in self.get_wizard_step_status().values())