"""
services/readings.py
------------------------
Simplest possible provision for continuous sensor/system readings.
Deliberately not using Kafka or a time-series-specific database --
this is a plain SQLite table (models_db.Reading) with two functions:
write a reading, read recent readings. Revisit if/when real throughput
or true streaming semantics are actually needed.
"""

from datetime import datetime, timedelta
import requests
from db import SessionLocal
from models_db import Reading

from services.api_tester import _parse_headers, REQUEST_TIMEOUT_SECONDS


def record_reading(factory_id: str, parameter_id: str, value: float = None, raw_value: str = None) -> Reading:
    """Writes one reading. Call this every time a new value comes in --
    for now that means your simulated feeder; later, whatever a real
    sensor integration calls when a new value arrives."""
    session = SessionLocal()
    reading = Reading(
        factory_id=factory_id,
        parameter_id=parameter_id,
        value=value,
        raw_value=raw_value,
        timestamp=datetime.utcnow(),
    )
    session.add(reading)
    session.commit()
    return reading


def get_recent_readings(factory_id: str, parameter_id: str = None, hours: int = 12):
    """Returns readings from the last `hours` hours (default 12, per
    the review-window requirement). Pass parameter_id to scope to one
    sensor; omit it to get every reading for the facility."""
    session = SessionLocal()
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    query = session.query(Reading).filter(
        Reading.factory_id == factory_id,
        Reading.timestamp >= cutoff,
    )
    if parameter_id:
        query = query.filter(Reading.parameter_id == parameter_id)
    return query.order_by(Reading.timestamp.asc()).all()

def _extract_value(data, json_path: str):
    """Walks a dot-path like 'data.reading.value' into a parsed JSON
    response. Falls back to the raw response if no json_path is
    configured -- covers APIs that just return a bare number."""
    if not json_path:
        return data
    current = data
    for key in json_path.split("."):
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None
    return current


def poll_sensor(factory_id: str, sensor) -> dict:
    """Fetches one live value from a sensor's configured REST API,
    records it, and returns a plain dict -- never raises, so the route
    calling this never needs a try/except."""
    if sensor.data_source_type != "REST API" or not sensor.api_url:
        return {"success": False, "reason": "no_source", "message": "No live API configured for this sensor."}

    headers = _parse_headers(sensor.api_headers)
    method = (sensor.api_method or "GET").upper()

    try:
        if method == "POST":
            response = requests.post(sensor.api_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        else:
            response = requests.get(sensor.api_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        return {"success": False, "reason": "unreachable", "message": f"Could not reach sensor API: {e}"}

    try:
        payload = response.json()
    except ValueError:
        payload = response.text

    raw_value = _extract_value(payload, sensor.api_json_path)
    if raw_value is None:
        return {"success": False, "reason": "bad_path", "message": "Configured JSON path did not match the response."}

    try:
        numeric_value = float(raw_value)
    except (TypeError, ValueError):
        numeric_value = None

    reading = record_reading(
        factory_id=factory_id,
        parameter_id=sensor.id,
        value=numeric_value,
        raw_value=str(raw_value),
    )

    return {
        "success": True,
        "value": numeric_value,
        "raw_value": str(raw_value),
        "timestamp": reading.timestamp.isoformat(),
    }