"""
services/storage.py
---------------------
A small JSON-file-backed persistence layer.

This is intentionally NOT a real database. For a hackathon prototype, a
flat JSON file is enough to demonstrate the full Add Facility wizard
(create factory, list/edit sensors, list/edit employees, save
validation answers, save negligence history, save attendance config)
without adding SQL/ORM setup overhead.

To swap in a real database later: keep these exact function signatures
and reimplement their bodies -- routes/*.py never touch the JSON file
directly, so nothing else needs to change.
"""

import json
import os
import threading
from typing import Optional, List

from config import Config
from models.factory import Factory
from models.sensor import Sensor
from models.employee import Employee

# Guards the JSON file against corruption from concurrent requests.
# Fine for a single-process dev server; replace with real DB transactions
# before running this under multiple worker processes.
_lock = threading.Lock()


def _ensure_data_file():
    os.makedirs(Config.DATA_FOLDER, exist_ok=True)
    if not os.path.exists(Config.FACTORIES_FILE):
        with open(Config.FACTORIES_FILE, "w") as f:
            json.dump({}, f)


def _read_all() -> dict:
    _ensure_data_file()
    with open(Config.FACTORIES_FILE, "r") as f:
        return json.load(f)


def _write_all(data: dict):
    with open(Config.FACTORIES_FILE, "w") as f:
        json.dump(data, f, indent=2)


def save_factory(factory: Factory) -> None:
    """Insert a new factory record, or overwrite an existing one with the
    same id."""
    with _lock:
        data = _read_all()
        data[factory.id] = factory.to_dict()
        _write_all(data)


def get_factory(factory_id: str) -> Optional[Factory]:
    with _lock:
        data = _read_all()
        record = data.get(factory_id)
        return Factory.from_dict(record) if record else None


def list_factories() -> List[Factory]:
    with _lock:
        data = _read_all()
        return [Factory.from_dict(r) for r in data.values()]


# ---------------------------------------------------------------------------
# Sensor CRUD
# ---------------------------------------------------------------------------

def delete_sensor(factory_id: str, sensor_id: str) -> bool:
    """Returns True if a sensor was actually removed, False if the factory
    or sensor didn't exist."""
    factory = get_factory(factory_id)
    if not factory:
        return False
    before = len(factory.sensors)
    factory.sensors = [s for s in factory.sensors if s.id != sensor_id]
    save_factory(factory)
    return len(factory.sensors) < before


def upsert_sensor(factory_id: str, sensor: Sensor) -> bool:
    """Add a new sensor, or update an existing one if its id already exists
    on this factory. Returns False only if the factory itself doesn't
    exist."""
    factory = get_factory(factory_id)
    if not factory:
        return False
    for i, s in enumerate(factory.sensors):
        if s.id == sensor.id:
            factory.sensors[i] = sensor
            save_factory(factory)
            return True
    factory.sensors.append(sensor)
    save_factory(factory)
    return True


def get_sensor(factory_id: str, sensor_id: str) -> Optional[Sensor]:
    factory = get_factory(factory_id)
    if not factory:
        return None
    return next((s for s in factory.sensors if s.id == sensor_id), None)


# ---------------------------------------------------------------------------
# Employee CRUD -- mirrors the sensor CRUD functions exactly, same pattern.
# ---------------------------------------------------------------------------

def delete_employee(factory_id: str, employee_id: str) -> bool:
    factory = get_factory(factory_id)
    if not factory:
        return False
    before = len(factory.employees)
    factory.employees = [e for e in factory.employees if e.id != employee_id]
    save_factory(factory)
    return len(factory.employees) < before


def upsert_employee(factory_id: str, employee: Employee) -> bool:
    factory = get_factory(factory_id)
    if not factory:
        return False
    for i, e in enumerate(factory.employees):
        if e.id == employee.id:
            factory.employees[i] = employee
            save_factory(factory)
            return True
    factory.employees.append(employee)
    save_factory(factory)
    return True


def get_employee(factory_id: str, employee_id: str) -> Optional[Employee]:
    factory = get_factory(factory_id)
    if not factory:
        return None
    return next((e for e in factory.employees if e.id == employee_id), None)


# ---------------------------------------------------------------------------
# Generic field updates -- used by the negligence history, validation
# answers, and attendance system steps, none of which need full CRUD.
# ---------------------------------------------------------------------------

def update_factory_fields(factory_id: str, **fields) -> bool:
    """Update one or more top-level fields on a factory record directly,
    e.g. update_factory_fields(fid, negligence_history="...", validation_complete=True).
    Returns False if the factory doesn't exist or a field name is invalid."""
    factory = get_factory(factory_id)
    if not factory:
        return False
    for key, value in fields.items():
        if not hasattr(factory, key):
            return False
        setattr(factory, key, value)
    save_factory(factory)
    return True
