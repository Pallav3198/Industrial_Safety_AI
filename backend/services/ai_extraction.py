"""
services/ai_extraction.py
----------------------------
Calls Google's Gemini API (free tier) to read an uploaded, filled-in
Facility Onboarding Template (PDF) and extract, in a single call,
everything realistically extractable from a one-time document read:

  1. A short plain-language process-understanding summary.
  2. Facility Overview fields, process narrative, SCADA systems (Part A).
  3. Monitored parameters (sensors) and people (key personnel +
     employees, distinguished by person_category) (Parts A/B).
  4. Shift patterns and maintenance records (Parts B/C).
  5. Which template sections appear missing or incomplete.
  6. A set of clarifying questions aimed at correlating information the
     document tends to keep siloed -- the whole point of a *compound*
     risk detection engine.

Deliberately NOT extracted here: Permit-to-Work records, MOC log
entries, and PSSR checklist status (template Sections 11-13). Those are
live/operational records that change day to day -- a one-time document
snapshot shouldn't own them. They start empty and are filled by a human
directly in the portal once those sections exist.

Everything above IS extracted in ONE call rather than several separate
calls, deliberately -- Gemini's free tier has meaningful per-day/per-
minute request caps (see README), and combining these into a single
request keeps the wizard's AI usage to exactly one call per uploaded
document.

If no GEMINI_API_KEY is configured (Config.USE_MOCK_AI == True), this
falls back to a fixed, fully-populated mock response so the entire
wizard can be built, demoed, and tested completely offline, with zero
API calls at all.

A failed real API call also falls back to mock data rather than
crashing the Add Facility flow -- a broken AI call should degrade
gracefully, not break the product.
"""

import json
import re

from config import Config
from models.monitored_parameter import MonitoredParameter
from models.person import Person

# The exact JSON schema we ask Gemini to return. Kept as one constant so
# the prompt and the parsing code below can't silently drift apart.
EXTRACTION_SYSTEM_PROMPT = """You are an industrial safety document analyst reviewing a completed
"Facility Onboarding Template" -- a structured document covering facility
overview, process description, SCADA systems, sensor/instrumentation
details, key personnel, escalation logic, shift patterns, maintenance
records, incident/negligence history, employee directory, attendance
systems, utility systems, training records, and compliance certifications.

Read the document carefully and respond with ONLY a single JSON object
in exactly this shape:

{
  "process_summary": "2-4 sentence plain-language summary of what the plant does and its main process steps",

  "facility_overview": {
    "address": "string, empty if not given",
    "industry_sector": "string, e.g. Thermal Power, Steel, Chemical/Pharma, Refinery (empty if not given)",
    "operating_company": "string, empty if not given",
    "commissioning_date": "string, empty if not given",
    "installed_capacity": "string, e.g. 600 MW (empty if not given)",
    "operating_phase": "one of: Routine Operation, Commissioning/Startup, Shutdown/Turnaround (empty if not stated)",
    "upcoming_milestone_date": "string, empty if not given",
    "departments": [{"name": "string", "function": "string", "headcount": "string"}]
  },
  "process_narrative": "string -- the process flow description, empty if not given",
  "drawing_references": "string, empty if not given",

  "scada_systems": [{"name": "string", "vendor": "string", "version": "string", "function": "string", "redundant": "Y/N or empty"}],
  "historian_system": "string, empty if not given",
  "network_notes": "string, empty if not given",

  "monitored_parameters": [
    {
      "name": "string, e.g. Furnace Pressure Transmitter FPT-101",
      "sensor_type": "one of: Temperature, Pressure, Gas Concentration, Flow Rate, Vibration, Level, Speed / RPM, Digital Status (On/Off), Other",
      "location": "string, e.g. Boiler Unit 1 - Furnace",
      "unit": "string, e.g. °C, bar, ppm, RPM (empty string if not applicable)",
      "normal_range": "string, e.g. 20 - 45 (empty string if unknown)",
      "alarm_threshold": "string, e.g. > 50 (empty string if unknown)",
      "response_type": "one of: Continuous Analog, Digital ON/OFF, Threshold Alarm, Manual Log Entry"
    }
  ],

  "people": [
    {
      "name": "string",
      "person_category": "one of: Employee, Managerial Staff, Maintenance Staff, Safety Officer",
      "role": "string, e.g. Shift Engineer",
      "department": "string, e.g. Boiler Operations",
      "email": "string, empty if not given",
      "phone": "string, empty if not given",
      "blood_group": "string, empty if not given",
      "working_hours": "string, e.g. 6:00 AM - 2:00 PM",
      "working_days": "string, e.g. Mon-Fri or Rotating Shift A",
      "emergency_contact_name": "string, empty if not given",
      "emergency_contact_phone": "string, empty if not given",
      "emergency_contact_relation": "string, e.g. Spouse (empty if not given)",
      "certifications": "string, only for Maintenance Staff, empty otherwise"
    }
  ],

  "shift_patterns": [{"shift_name": "string", "start_time": "string", "end_time": "string", "headcount": "string"}],
  "shift_handover_notes": "string, empty if not given",

  "maintenance_records": [
    {"equipment": "string", "last_date": "string", "type": "string", "next_due": "string", "performed_by": "string", "deferred_notes": "string"}
  ],

  "missing_sections": [
    "short label of any template section that is blank, very sparse, or clearly incomplete -- e.g. 'Section 7: Maintenance Records & Timelines' or 'Section 6: Shift Changeover Protocol'"
  ],
  "clarifying_questions": [
    "3 to 8 specific, direct questions to ask the facility contact. Prioritize questions that would let a compound-risk detection system correlate DIFFERENT categories of information -- for example, how shift changeover timing overlaps with maintenance windows, whether escalation contacts are reachable across all shifts, whether sensor alarm thresholds account for startup/shutdown transients, or how any missing section's information could be filled in. Do not ask generic questions a form field already covers."
  ]
}

Only include entries that are actually mentioned or clearly implied by
the document -- do not invent entries. If a category has no information
at all, return an empty list/object for it rather than inventing one
(use "person_category": "Employee" as the default only when the
document clearly means a general staff member with no more specific
role indicated). Base missing_sections and clarifying_questions on what
is ACTUALLY absent or thin in the document, not a fixed checklist."""


def _strip_code_fences(text: str) -> str:
    """Defensive cleanup in case the model wraps JSON in ```json ... ```
    despite response_mime_type="application/json" being set."""
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    return text


def extract_from_document(file_path: str) -> dict:
    """
    Main entry point.

    Returns:
        {
            "process_summary": str,
            "facility_overview": dict,
            "process_narrative": str,
            "drawing_references": str,
            "scada_systems": [dict, ...],
            "historian_system": str,
            "network_notes": str,
            "monitored_parameters": [MonitoredParameter, ...],
            "people": [Person, ...],
            "shift_patterns": [dict, ...],
            "shift_handover_notes": str,
            "maintenance_records": [dict, ...],
            "missing_sections": [str, ...],
            "clarifying_questions": [str, ...],
        }
    """
    if Config.USE_MOCK_AI:
        return _mock_extraction()

    try:
        return _call_gemini(file_path)
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see module docstring
        print(f"[ai_extraction] Gemini extraction failed, falling back to mock data. Reason: {exc}")
        return _mock_extraction()


def _call_gemini(file_path: str) -> dict:
    from google import genai            # imported lazily -- only required when this path runs
    from google.genai import types

    client = genai.Client(api_key=Config.GEMINI_API_KEY)

    # Gemini's Files API accepts a path directly and handles PDFs natively
    # (no manual base64 encoding needed, unlike some other providers).
    uploaded_file = client.files.upload(file=file_path)

    response = client.models.generate_content(
        model=Config.GEMINI_MODEL,
        contents=[
            "Analyze this completed Facility Onboarding Template and return the JSON object described in your instructions.",
            uploaded_file,
        ],
        config=types.GenerateContentConfig(
            system_instruction=EXTRACTION_SYSTEM_PROMPT,
            response_mime_type="application/json",  # forces valid JSON output natively
        ),
    )

    cleaned = _strip_code_fences(response.text)
    parsed = json.loads(cleaned)
    return _parsed_json_to_result(parsed)


def _parsed_json_to_result(parsed: dict) -> dict:
    """Shared conversion from the raw parsed JSON (whether from a real
    Gemini call or the mock fixture below) into typed MonitoredParameter/
    Person objects plus the plain dict/scalar fields. Split out so both
    paths stay in sync automatically."""
    monitored_parameters = [
        MonitoredParameter(
            name=s.get("name", "Unnamed Sensor"),
            parameter_category="Live Sensor Reading",
            sensor_type=s.get("sensor_type", "Other"),
            location=s.get("location", ""),
            unit=s.get("unit", ""),
            normal_range=s.get("normal_range", ""),
            alarm_threshold=s.get("alarm_threshold", ""),
            response_type=s.get("response_type", "Continuous Analog"),
            source="AI-Extracted",
        )
        for s in parsed.get("monitored_parameters", [])
    ]

    people = [
        Person(
            name=p.get("name", "Unnamed Person"),
            person_category=p.get("person_category", "Employee"),
            role=p.get("role", ""),
            department=p.get("department", ""),
            email=p.get("email", ""),
            phone=p.get("phone", ""),
            blood_group=p.get("blood_group", ""),
            working_hours=p.get("working_hours", ""),
            working_days=p.get("working_days", ""),
            emergency_contact_name=p.get("emergency_contact_name", ""),
            emergency_contact_phone=p.get("emergency_contact_phone", ""),
            emergency_contact_relation=p.get("emergency_contact_relation", ""),
            certifications=p.get("certifications", ""),
            source="AI-Extracted",
        )
        for p in parsed.get("people", [])
    ]

    facility_overview = parsed.get("facility_overview", {}) or {}

    return {
        "process_summary": parsed.get("process_summary", ""),
        "facility_overview": facility_overview,
        "process_narrative": parsed.get("process_narrative", ""),
        "drawing_references": parsed.get("drawing_references", ""),
        "scada_systems": parsed.get("scada_systems", []),
        "historian_system": parsed.get("historian_system", ""),
        "network_notes": parsed.get("network_notes", ""),
        "monitored_parameters": monitored_parameters,
        "people": people,
        "shift_patterns": parsed.get("shift_patterns", []),
        "shift_handover_notes": parsed.get("shift_handover_notes", ""),
        "maintenance_records": parsed.get("maintenance_records", []),
        "missing_sections": parsed.get("missing_sections", []),
        "clarifying_questions": parsed.get("clarifying_questions", []),
    }


def _mock_extraction() -> dict:
    """Fixed demo data used when no GEMINI_API_KEY is set. Lets you build
    and test the entire wizard offline, with zero API calls or cost.
    Modeled loosely on the Vedanta boiler simulation scenario."""
    mock_json = {
        "process_summary": (
            "Demo mode (no GEMINI_API_KEY configured): this is fixed sample output standing in for "
            "real AI extraction. The plant appears to be a coal-fired boiler unit with primary-air-"
            "driven combustion and standard pressure/temperature instrumentation on the furnace and header."
        ),
        "facility_overview": {
            "address": "NH-49, Riverbend Industrial Corridor, Raigarh District, Chhattisgarh, India",
            "industry_sector": "Thermal Power (Coal-Fired)",
            "operating_company": "Riverbend Power Generation Ltd.",
            "commissioning_date": "March 15, 2025",
            "installed_capacity": "600 MW (Unit 1, sub-critical boiler)",
            "operating_phase": "Routine Operation",
            "upcoming_milestone_date": "",
            "departments": [
                {"name": "Boiler & Furnace Operations", "function": "Combustion and steam generation", "headcount": "38"},
                {"name": "Maintenance", "function": "Mechanical, electrical, and instrumentation upkeep", "headcount": "52"},
            ],
        },
        "process_narrative": (
            "Coal is crushed and blown into a furnace, where combustion heat boils water into high-"
            "pressure steam. Steam drives a turbine-generator to produce electricity. Flue gas passes "
            "through an electrostatic precipitator before discharge via the stack."
        ),
        "drawing_references": "PFD-RTPS-001, PID-RTPS-BLR-014",
        "scada_systems": [
            {"name": "Unit 1 DCS", "vendor": "ABB Ability Symphony Plus", "version": "v3.2", "function": "Overall unit control and monitoring", "redundant": "Y"},
        ],
        "historian_system": "OSIsoft PI System",
        "network_notes": "IT/OT segregated via firewall DMZ; SCADA network is air-gapped from corporate IT.",
        "monitored_parameters": [
            {
                "name": "Furnace Pressure Transmitter — FPT-101",
                "sensor_type": "Pressure",
                "location": "Boiler Unit 1 - Furnace",
                "unit": "bar",
                "normal_range": "1.0 - 1.4",
                "alarm_threshold": "> 1.6",
                "response_type": "Continuous Analog",
            },
            {
                "name": "Primary Air Fan Status — PAF-01",
                "sensor_type": "Digital Status (On/Off)",
                "location": "Boiler Unit 1 - Air Supply",
                "unit": "",
                "normal_range": "Running",
                "alarm_threshold": "Fault / Tripped",
                "response_type": "Digital ON/OFF",
            },
            {
                "name": "Boiler Tube Temperature — TT-204",
                "sensor_type": "Temperature",
                "location": "Boiler Unit 1 - Header",
                "unit": "°C",
                "normal_range": "480 - 540",
                "alarm_threshold": "> 560",
                "response_type": "Continuous Analog",
            },
        ],
        "people": [
            {
                "name": "R. Venkatesh",
                "person_category": "Managerial Staff",
                "role": "Plant Head",
                "department": "Management",
                "email": "r.venkatesh@riverbendpower.example.com",
                "phone": "+91 98765 10001",
                "blood_group": "",
                "working_hours": "",
                "working_days": "",
                "emergency_contact_name": "",
                "emergency_contact_phone": "",
                "emergency_contact_relation": "",
                "certifications": "",
            },
            {
                "name": "Priya Nair",
                "person_category": "Safety Officer",
                "role": "Safety Officer",
                "department": "Safety",
                "email": "priya.nair@example-plant.com",
                "phone": "+91 98765 43212",
                "blood_group": "A-",
                "working_hours": "8:00 AM - 5:00 PM",
                "working_days": "Mon-Fri",
                "emergency_contact_name": "Vijay Nair",
                "emergency_contact_phone": "+91 98765 33333",
                "emergency_contact_relation": "Spouse",
                "certifications": "",
            },
            {
                "name": "Anil Sharma",
                "person_category": "Maintenance Staff",
                "role": "Maintenance Technician",
                "department": "Maintenance",
                "email": "anil.sharma@example-plant.com",
                "phone": "+91 98765 43211",
                "blood_group": "B+",
                "working_hours": "9:00 AM - 6:00 PM",
                "working_days": "Mon-Sat",
                "emergency_contact_name": "Rakesh Sharma",
                "emergency_contact_phone": "+91 98765 22222",
                "emergency_contact_relation": "Brother",
                "certifications": "Rotating Equipment Certified",
            },
            {
                "name": "Ravi Kumar",
                "person_category": "Employee",
                "role": "Shift Engineer",
                "department": "Boiler Operations",
                "email": "ravi.kumar@example-plant.com",
                "phone": "+91 98765 43210",
                "blood_group": "O+",
                "working_hours": "6:00 AM - 2:00 PM",
                "working_days": "Rotating Shift A",
                "emergency_contact_name": "Sunita Kumar",
                "emergency_contact_phone": "+91 98765 11111",
                "emergency_contact_relation": "Spouse",
                "certifications": "",
            },
        ],
        "shift_patterns": [
            {"shift_name": "Shift A", "start_time": "6:00 AM", "end_time": "2:00 PM", "headcount": "65"},
            {"shift_name": "Shift B", "start_time": "2:00 PM", "end_time": "10:00 PM", "headcount": "60"},
        ],
        "shift_handover_notes": "15-minute overlap; outgoing and incoming shift engineers walk a shared checklist together.",
        "maintenance_records": [
            {"equipment": "Primary Air Fan (PAF-01)", "last_date": "2026-04-10", "type": "Preventive (bearing lubrication)", "next_due": "2026-07-10", "performed_by": "Anil Sharma", "deferred_notes": "On schedule"},
        ],
        "missing_sections": [
            "Section 7: Maintenance Records & Timelines",
            "Section 6: Shift Changeover Protocol (timing described, handover procedure not described)",
        ],
        "clarifying_questions": [
            "When was the Primary Air Fan (PAF-01) last serviced, and is there a scheduled maintenance date coming up?",
            "During shift changeover, is there a documented handover checklist, or is it verbal only?",
            "Does any scheduled maintenance window overlap with the shift changeover time (e.g. maintenance starting right as a new shift comes on)?",
            "Are alarm thresholds on FPT-101 and TT-204 adjusted during startup/shutdown, or are they fixed at all times?",
            "Who is contacted if a Level 1 (first responder) escalation doesn't get a response within the expected time -- is there a documented fallback?",
        ],
    }
    return _parsed_json_to_result(mock_json)