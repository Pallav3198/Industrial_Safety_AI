"""
models/sensor.py
------------------
Data model for a single sensor/system entry attached to a factory.

Extended to support live API-based readings: a sensor can now optionally
be wired to a JSON API endpoint (api_url/api_method/api_headers), tested
from the Sensors screen via a "Test Connection" button, with the result
stored in api_status ("Not Tested" / "Active" / "Inactive").

Kept as a plain dataclass (no ORM) since persistence is a flat JSON file
(see services/storage.py).
"""

from dataclasses import dataclass, field, asdict
import uuid


@dataclass
class Sensor:
    name: str
    sensor_type: str                          # see SENSOR_TYPE_CHOICES below
    location: str = ""                        # e.g. "Boiler Unit 1 - Furnace"
    unit: str = ""                             # e.g. "°C", "bar", "ppm", "RPM"
    normal_range: str = ""                    # e.g. "20 - 45"
    alarm_threshold: str = ""                 # e.g. "> 50"
    response_type: str = "Continuous Analog"  # see RESPONSE_TYPE_CHOICES below
    notes: str = ""
    source: str = "Manually Added"            # "AI-Extracted" or "Manually Added"

    # --- Live API integration fields ------------------------------------
    api_url: str = ""                         # e.g. https://plant-scada.example.com/api/sensors/FPT-101
    api_method: str = "GET"                   # "GET" or "POST"
    api_headers: str = ""                     # raw "Key: Value" lines, one per header
    api_json_path: str = ""                   # optional dot-path to the reading in the JSON response, e.g. "data.value"
    api_status: str = "Not Tested"            # "Not Tested" / "Active" / "Inactive"
    api_last_tested: str = ""                 # ISO timestamp of the last test, empty if never tested

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "Sensor":
        # Only pass through known fields -- protects against old/mismatched
        # JSON records if the schema changes later (e.g. records saved
        # before the API fields were added won't have them, and that's fine).
        known_fields = {f: data[f] for f in Sensor.__dataclass_fields__ if f in data}
        return Sensor(**known_fields)


# Dropdown choices for the Add/Edit Sensor form. Kept here so templates,
# JS, and validation all share one source of truth instead of duplicating
# this list in multiple places.
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

API_METHOD_CHOICES = ["GET", "POST"]
