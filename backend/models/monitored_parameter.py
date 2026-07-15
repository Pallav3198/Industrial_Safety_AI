"""
models/monitored_parameter.py
--------------------------------
Generalized model for anything the platform tracks with a value and a
threshold: live sensor readings, compliance/asset due-dates, and
minimum-staffing rules. Replaces the old models/sensor.py -- Sensor is
renamed to MonitoredParameter and gains a parameter_category so one
model (and one CRUD/UI pattern) covers all three, instead of three
separate rigid tables.

Why these three specifically share one model: they're all "a value,
compared against a threshold, sourced from somewhere." A live sensor's
value is a reading; an asset's value is days-until-due; a staffing
rule's value is today's headcount. Different meaning, same shape.

Kept as a plain dataclass (no ORM) since persistence is a flat JSON file
(see services/storage.py).
"""

from dataclasses import dataclass, field, asdict
import uuid


@dataclass
class MonitoredParameter:
    name: str
    parameter_category: str = "Live Sensor Reading"
    # "Live Sensor Reading" | "Compliance Due-Date" | "Staffing Rule"
    # See PARAMETER_CATEGORY_CHOICES below. Which of the fields further
    # down are relevant depends on this value -- see the section comments.

    # --- Live Sensor Reading fields (parameter_category == "Live Sensor Reading") ---
    sensor_type: str = ""                     # see SENSOR_TYPE_CHOICES below
    location: str = ""                        # e.g. "Boiler Unit 1 - Furnace" (free-text, human-readable)
    equipment_tag: str = ""                   # e.g. "BLR-01" -- exact-match identifier, shared across
                                               # sensors/permits for the SAME physical equipment. This is
                                               # what the knowledge graph (services/graph.py) joins on --
                                               # `location` above is for display, this is for linking.
    unit: str = ""                             # e.g. "°C", "bar", "ppm", "RPM"
    normal_range: str = ""                    # e.g. "20 - 45", or "Present" for a safeguard-presence flag
    alarm_threshold: str = ""                 # e.g. "> 50", or "Absent" for a safeguard-presence flag
    response_type: str = "Continuous Analog"  # see RESPONSE_TYPE_CHOICES below
    fault_since: str = ""                     # ISO timestamp -- when this sensor entered its current fault
                                               # state, if it's currently faulted. Empty if not faulted.
                                               # Enables duration-based rules ("faulted for 4+ hours").

    # --- Compliance Due-Date fields (parameter_category == "Compliance Due-Date") ---
    # Used by the Equipment / Asset Registry (template Section 10) --
    # cylinders, fire extinguishers, calibrated instruments, etc.
    asset_type: str = ""                      # e.g. "Gas Cylinder", "Fire Extinguisher", "Pressure Vessel"
    last_test_date: str = ""
    next_due_date: str = ""

    # --- Staffing Rule fields (parameter_category == "Staffing Rule") ---
    # Used by Minimum Staffing Per Task Rules (template Section 7).
    task_name: str = ""                       # e.g. "Cylinder Filling"
    minimum_headcount: int = 0
    required_roles: str = ""

    # --- Data source fields (common to all categories) ---------------------
    data_source_type: str = "Manual Entry"    # see DATA_SOURCE_TYPE_CHOICES below
    api_url: str = ""                         # only meaningful if data_source_type is an API-based option
    api_method: str = "GET"                   # "GET" or "POST"
    api_headers: str = ""                     # raw "Key: Value" lines, one per header
    api_json_path: str = ""                   # optional dot-path to the reading in the JSON response
    api_status: str = "Not Tested"            # "Not Tested" / "Active" / "Inactive"
    api_last_tested: str = ""                 # ISO timestamp of the last test, empty if never tested

    notes: str = ""
    source: str = "Manually Added"            # "AI-Extracted" or "Manually Added"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "MonitoredParameter":
        # Only pass through known fields -- protects against old/mismatched
        # JSON records if the schema changes later.
        known_fields = {f: data[f] for f in MonitoredParameter.__dataclass_fields__ if f in data}
        return MonitoredParameter(**known_fields)


# Dropdown choices. Kept here so templates, JS, and validation all share
# a single source of truth instead of duplicating these lists.
PARAMETER_CATEGORY_CHOICES = [
    "Live Sensor Reading",
    "Compliance Due-Date",
    "Staffing Rule",
]

SENSOR_TYPE_CHOICES = [
    "Temperature",
    "Pressure",
    "Gas Concentration",
    "Flow Rate",
    "Vibration",
    "Level",
    "Speed / RPM",
    "Digital Status (On/Off)",
    "Other",
]

RESPONSE_TYPE_CHOICES = [
    "Continuous Analog",
    "Digital ON/OFF",
    "Threshold Alarm",
    "Manual Log Entry",
]

DATA_SOURCE_TYPE_CHOICES = [
    "Manual Entry",
    "REST API",
    "Protocol Gateway",
    "File Import",
]

API_METHOD_CHOICES = ["GET", "POST"]