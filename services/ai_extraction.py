"""
services/ai_extraction.py
----------------------------
Calls Google's Gemini API (free tier) to read an uploaded, filled-in
Facility Onboarding Template (PDF) and extract, in a single call:

  1. A short plain-language process-understanding summary.
  2. A structured list of sensors/systems.
  3. A structured list of employees.
  4. Which template sections appear missing or incomplete.
  5. A set of clarifying questions to ask the user (Step 2 of the
     wizard) -- specifically aimed at correlating information the
     document tends to keep siloed (shift patterns vs. maintenance
     windows vs. sensor coverage vs. escalation logic), which is the
     whole point of a *compound* risk detection engine.

Everything is extracted in ONE call rather than four separate calls,
deliberately -- Gemini's free tier has meaningful per-day/per-minute
request caps (see README), and combining these into a single request
keeps the wizard's AI usage to exactly one call per uploaded document.

If no GEMINI_API_KEY is configured (Config.USE_MOCK_AI == True), this
falls back to a fixed, fully-populated mock response so the entire
wizard -- validation chat, sensors, employees -- can be built, demoed,
and tested completely offline, with zero API calls at all.

A failed real API call also falls back to mock data rather than
crashing the Add Facility flow -- a broken AI call should degrade
gracefully, not break the product.
"""

import json
import re

from config import Config
from models.sensor import Sensor
from models.employee import Employee

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
  "sensors": [
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
  "employees": [
    {
      "name": "string",
      "role": "string, e.g. Shift Engineer",
      "department": "string, e.g. Boiler Operations",
      "email": "string, empty if not given",
      "phone": "string, empty if not given",
      "blood_group": "string, empty if not given",
      "working_hours": "string, e.g. 6:00 AM - 2:00 PM",
      "working_days": "string, e.g. Mon-Fri or Rotating Shift A",
      "emergency_contact_name": "string, empty if not given",
      "emergency_contact_phone": "string, empty if not given",
      "emergency_contact_relation": "string, e.g. Spouse (empty if not given)"
    }
  ],
  "missing_sections": [
    "short label of any template section that is blank, very sparse, or clearly incomplete -- e.g. 'Section 7: Maintenance Records & Timelines' or 'Section 6: Shift Changeover Protocol'"
  ],
  "clarifying_questions": [
    "3 to 8 specific, direct questions to ask the facility contact. Prioritize questions that would let a compound-risk detection system correlate DIFFERENT categories of information -- for example, how shift changeover timing overlaps with maintenance windows, whether escalation contacts are reachable across all shifts, whether sensor alarm thresholds account for startup/shutdown transients, or how any missing section's information could be filled in. Do not ask generic questions a form field already covers."
  ]
}

Only include sensors/employees that are actually mentioned or clearly
implied by the document -- do not invent entries. If a category has no
information at all, return an empty list for it rather than inventing
one. Base missing_sections and clarifying_questions on what is ACTUALLY
absent or thin in the document, not a fixed checklist."""


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
            "sensors": [Sensor, ...],
            "employees": [Employee, ...],
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
    Gemini call or, in principle, any other source) into typed Sensor/
    Employee objects. Split out so both the real path and any future
    alternate source stay in sync automatically."""
    sensors = [
        Sensor(
            name=s.get("name", "Unnamed Sensor"),
            sensor_type=s.get("sensor_type", "Other"),
            location=s.get("location", ""),
            unit=s.get("unit", ""),
            normal_range=s.get("normal_range", ""),
            alarm_threshold=s.get("alarm_threshold", ""),
            response_type=s.get("response_type", "Continuous Analog"),
            source="AI-Extracted",
        )
        for s in parsed.get("sensors", [])
    ]

    employees = [
        Employee(
            name=e.get("name", "Unnamed Employee"),
            role=e.get("role", ""),
            department=e.get("department", ""),
            email=e.get("email", ""),
            phone=e.get("phone", ""),
            blood_group=e.get("blood_group", ""),
            working_hours=e.get("working_hours", ""),
            working_days=e.get("working_days", ""),
            emergency_contact_name=e.get("emergency_contact_name", ""),
            emergency_contact_phone=e.get("emergency_contact_phone", ""),
            emergency_contact_relation=e.get("emergency_contact_relation", ""),
            source="AI-Extracted",
        )
        for e in parsed.get("employees", [])
    ]

    return {
        "process_summary": parsed.get("process_summary", ""),
        "sensors": sensors,
        "employees": employees,
        "missing_sections": parsed.get("missing_sections", []),
        "clarifying_questions": parsed.get("clarifying_questions", []),
    }


def _mock_extraction() -> dict:
    """Fixed demo data used when no GEMINI_API_KEY is set. Lets you build
    and test the entire wizard -- validation chat, sensors, employees --
    offline, with zero API calls or cost. Modeled loosely on the Vedanta
    boiler simulation scenario."""
    mock_json = {
        "process_summary": (
            "Demo mode (no GEMINI_API_KEY configured): this is fixed sample output standing in for "
            "real AI extraction. The plant appears to be a coal-fired boiler unit with primary-air-"
            "driven combustion and standard pressure/temperature instrumentation on the furnace and header."
        ),
        "sensors": [
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
        "employees": [
            {
                "name": "Ravi Kumar",
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
            },
            {
                "name": "Anil Sharma",
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
            },
            {
                "name": "Priya Nair",
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
            },
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
