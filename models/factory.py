"""
models/factory.py
-------------------
Data model for a Factory record. Covers the full Add Facility wizard --
all 20 Facility Onboarding Template sections across Parts A-E -- plus
document validation (missing sections + clarifying Q&A) and the
attendance system API config.

NOTE ON NAMING: the person-facing product now calls this flow "Add
Facility" (renamed from "Add Factory"). Internally, the code still uses
"Factory"/"factory" throughout (module names, variable names, URL
routes) to avoid a large, risky rename across the whole codebase for a
label-only change. Only user-facing text says "Facility".

NOTE ON MODEL RENAMES: `sensors` is now `monitored_parameters` (see
models/monitored_parameter.py) and `employees` is now `people` (see
models/person.py) -- both renamed and generalized to cover more of the
20 template sections without adding a separate rigid model per section.
URL routes/endpoints deliberately keep their old names ("sensors",
"employees") to minimize blast radius -- only the Python-internal model
layer changed.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict
import uuid

from models.monitored_parameter import MonitoredParameter
from models.person import Person
from models.checklist_record import ChecklistRecord
from models.permit_record import PermitRecord


@dataclass
class Factory:
    name: str
    preliminary_doc_filename: str = ""

    # --- AI extraction results -------------------------------------------
    ai_summary: str = ""                          # process understanding write-up
    monitored_parameters: List[MonitoredParameter] = field(default_factory=list)
    people: List[Person] = field(default_factory=list)
    checklist_records: List[ChecklistRecord] = field(default_factory=list)
    permit_records: List[PermitRecord] = field(default_factory=list)

    # --- Document validation (chatbot-style gap filling) -------------------
    missing_sections: List[str] = field(default_factory=list)     # sections the AI found incomplete/absent
    clarification_qa: List[Dict[str, str]] = field(default_factory=list)  # [{"question": ..., "answer": ...}, ...]
    validation_complete: bool = False

    # ==========================================================================
    # PART A -- Facility & Process Profile (template Sections 1-4)
    # ==========================================================================
    # Section 1: Facility Overview
    address: str = ""
    industry_sector: str = ""
    operating_company: str = ""
    commissioning_date: str = ""
    installed_capacity: str = ""
    operating_phase: str = ""              # "Routine Operation" / "Commissioning/Startup" / "Shutdown/Turnaround"
    upcoming_milestone_date: str = ""      # e.g. an inauguration or regulatory deadline
    departments: List[Dict] = field(default_factory=list)  # [{"name":.., "function":.., "headcount":..}]

    # Section 2: Process Flow Description
    process_narrative: str = ""
    drawing_references: str = ""

    # Section 3: SCADA / DCS Systems
    scada_systems: List[Dict] = field(default_factory=list)  # [{"name":.., "vendor":.., "version":.., "function":.., "redundant":..}]
    historian_system: str = ""
    network_notes: str = ""

    # Section 4: Sensor & Instrumentation Details -> monitored_parameters above

    # ==========================================================================
    # PART B -- People & Workforce (template Sections 5-8)
    # ==========================================================================
    # Section 5: Key Personnel -> people above (filtered by person_category)
    escalation_logic: List[Dict] = field(default_factory=list)  # [{"level":.., "trigger":.., "contact_role":.., "response_time":..}]

    # Section 6: Shift & Workforce Patterns
    shift_patterns: List[Dict] = field(default_factory=list)  # [{"shift_name":.., "start_time":.., "end_time":.., "headcount":..}]
    shift_handover_notes: str = ""

    # Section 7: Minimum Staffing Per Task Rules -> monitored_parameters above
    # Section 8: Employee Directory -> people above

    # ==========================================================================
    # PART C -- Maintenance, Assets & Change Management (template Sections 9-11)
    # ==========================================================================
    # Section 9: Maintenance Records & Timelines
    maintenance_records: List[Dict] = field(default_factory=list)
    # [{"equipment":.., "last_date":.., "type":.., "next_due":.., "performed_by":.., "deferred_notes":..}]

    # Section 10: Equipment / Asset Registry -> monitored_parameters above
    # Section 11: Management of Change (MOC) Log -> checklist_records above

    # ==========================================================================
    # PART D -- Work Authorization & Contractor Management (template Sections 12-14)
    # ==========================================================================
    # Section 12: Permit-to-Work Register -> permit_records above
    # Section 13: Pre-Startup Safety Review (PSSR) -> checklist_records above
    # Section 14: Contractor Oversight Register -> people above (person_category="Contractor")

    # ==========================================================================
    # PART E -- Incidents, Compliance & Support Systems (template Sections 15-20)
    # ==========================================================================
    # Section 15: Incident & Negligence History
    negligence_history: str = ""

    # Section 16: Attendance & Access Control Systems
    attendance_api_url: str = ""
    attendance_api_method: str = "GET"
    attendance_api_headers: str = ""
    attendance_api_status: str = "Not Tested"      # "Not Tested" / "Active" / "Inactive"
    attendance_api_last_tested: str = ""

    # Section 17: Utility & Support Systems
    utility_systems: List[Dict] = field(default_factory=list)  # [{"system":.., "type_vendor":.., "redundancy":.., "last_tested":..}]

    # Section 18: Training & Certification Records
    training_info: Dict = field(default_factory=dict)
    # {"induction_program":.., "drill_frequency":.., "last_drill_date":.., "contractor_training_process":..}

    # Section 19: Environmental & Quality Compliance
    environmental_compliance: Dict = field(default_factory=dict)
    # {"env_clearance":.., "pcb_registration":.., "iso_9001":.., "iso_14001":.., "iso_45001":..}

    # Section 20: Emergency Response & Compliance
    regulatory_standards: str = ""
    fire_safety_systems: str = ""
    last_safety_audit_date: str = ""
    last_safety_audit_findings: str = ""

    # --- Facility layout (portal-only feature, not a template section) -------
    # A flat list of plain dicts exported by the Konva.js canvas editor,
    # e.g. [{"type": "machine", "x": 100, "y": 100, "width": 140,
    # "height": 80, "label": "Boiler Unit 1"}, {"type": "text", ...},
    # {"type": "line", "points": [x1, y1, x2, y2]}, ...].
    layout_data: List[Dict] = field(default_factory=list)

    setup_complete: bool = False                   # True once the full wizard has been finished

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        d = asdict(self)
        # asdict() recurses into dataclasses automatically, but we keep this
        # explicit conversion so the intent is obvious and safe against
        # future edits to these models' structure.
        d["monitored_parameters"] = [p.to_dict() if isinstance(p, MonitoredParameter) else p for p in self.monitored_parameters]
        d["people"] = [p.to_dict() if isinstance(p, Person) else p for p in self.people]
        d["checklist_records"] = [c.to_dict() if isinstance(c, ChecklistRecord) else c for c in self.checklist_records]
        d["permit_records"] = [p.to_dict() if isinstance(p, PermitRecord) else p for p in self.permit_records]
        return d

    @staticmethod
    def from_dict(data: dict) -> "Factory":
        monitored_parameters = [MonitoredParameter.from_dict(p) for p in data.get("monitored_parameters", [])]
        people = [Person.from_dict(p) for p in data.get("people", [])]
        checklist_records = [ChecklistRecord.from_dict(c) for c in data.get("checklist_records", [])]
        permit_records = [PermitRecord.from_dict(p) for p in data.get("permit_records", [])]
        known_fields = {
            f: data[f]
            for f in Factory.__dataclass_fields__
            if f in data and f not in ("monitored_parameters", "people", "checklist_records", "permit_records")
        }
        factory = Factory(**known_fields)
        factory.monitored_parameters = monitored_parameters
        factory.people = people
        factory.checklist_records = checklist_records
        factory.permit_records = permit_records
        return factory

    def get_wizard_step_status(self) -> Dict[int, str]:
        """Returns {section_number: status} for all 20 Facility Onboarding
        Template sections, where status is one of:
          "done"    -- green check    -- the section's data is objectively complete
          "warning" -- yellow "!"     -- the section has been reached but needs attention
          "pending" -- grey           -- nothing entered for this section yet

        Used by partials/wizard_progress.html to color/icon each tab, and
        by facility_details.html to decide whether to show the
        "Train & Configure AI" button (only once every section is "done").

        These are intentionally simple, deterministic, data-presence
        checks -- not a tracked "has the user visited this page" flag,
        since sections can be visited in any order via the clickable
        wizard tabs, not just sequentially.

        Sections whose dedicated page hasn't been built yet (see
        models/wizard_sections.py for what's live) still get a real
        status here, computed from the underlying Factory fields added
        in this revision -- so status is accurate from day one, even
        before every section has its own editable page.
        """
        status = {}

        # Section 1: Facility Overview
        status[1] = "done" if self.address.strip() else "pending"
        # Section 2: Process Flow Description
        status[2] = "done" if self.process_narrative.strip() else "pending"
        # Section 3: SCADA / DCS Systems
        status[3] = "done" if self.scada_systems else "pending"
        # Section 4: Sensor & Instrumentation Details
        status[4] = "done" if any(p.parameter_category == "Live Sensor Reading" for p in self.monitored_parameters) else "pending"
        # Section 5: Key Personnel
        status[5] = "done" if any(p.person_category in ("Managerial Staff", "Maintenance Staff", "Safety Officer") for p in self.people) else "pending"
        # Section 6: Shift & Workforce Patterns
        status[6] = "done" if self.shift_patterns else "pending"
        # Section 7: Minimum Staffing Per Task Rules
        status[7] = "done" if any(p.parameter_category == "Staffing Rule" for p in self.monitored_parameters) else "pending"
        # Section 8: Employee Directory
        status[8] = "done" if any(p.person_category == "Employee" for p in self.people) else "pending"
        # Section 9: Maintenance Records & Timelines
        status[9] = "done" if self.maintenance_records else "pending"
        # Section 10: Equipment / Asset Registry
        status[10] = "done" if any(p.parameter_category == "Compliance Due-Date" for p in self.monitored_parameters) else "pending"
        # Section 11: Management of Change (MOC) Log
        status[11] = "done" if any(c.checklist_type == "MOC" for c in self.checklist_records) else "pending"
        # Section 12: Permit-to-Work Register
        status[12] = "done" if self.permit_records else "pending"
        # Section 13: Pre-Startup Safety Review (PSSR)
        status[13] = "done" if any(c.checklist_type == "PSSR" for c in self.checklist_records) else "pending"
        # Section 14: Contractor Oversight Register
        status[14] = "done" if any(p.person_category == "Contractor" for p in self.people) else "pending"
        # Section 15: Incident & Negligence History
        status[15] = "done" if self.negligence_history.strip() else "pending"
        # Section 16: Attendance & Access Control -- done only if the
        # configured API actually tested as reachable; warning if
        # configured but not confirmed working; pending if nothing entered.
        if self.attendance_api_status == "Active":
            status[16] = "done"
        elif self.attendance_api_url:
            status[16] = "warning"
        else:
            status[16] = "pending"
        # Section 17: Utility & Support Systems
        status[17] = "done" if self.utility_systems else "pending"
        # Section 18: Training & Certification Records
        status[18] = "done" if self.training_info else "pending"
        # Section 19: Environmental & Quality Compliance
        status[19] = "done" if self.environmental_compliance else "pending"
        # Section 20: Emergency Response & Compliance
        status[20] = "done" if self.regulatory_standards.strip() else "pending"

        return status

    def is_fully_configured(self) -> bool:
        """True once every one of the 20 sections reports 'done' -- used
        to decide whether to show the 'Train & Configure AI' button."""
        return all(s == "done" for s in self.get_wizard_step_status().values())