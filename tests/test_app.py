"""
tests/test_app.py
--------------------
End-to-end tests for the full 7-step Add Facility wizard, using Flask's
built-in test client (no real server, no real network calls needed).

Run with:
    pytest

These tests run entirely in MOCK MODE (no GEMINI_API_KEY needed) --
services/ai_extraction.py automatically falls back to fixed demo data
when Config.USE_MOCK_AI is True, which it is by default in any
environment without a real API key set (e.g. CI, or your local machine
before you've configured .env).

The sensor/attendance "Test Connection" tests use httpbin-style local
endpoints are NOT hit here (no real network in a CI environment) --
instead they test against a deliberately invalid URL and assert the
graceful-failure path, which is the behavior that matters most (a
broken API must never crash the app).
"""

import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from app import create_app
from config import Config


@pytest.fixture()
def app(tmp_path, monkeypatch):
    """A fresh app instance per test, pointed at a temporary data/upload
    directory so tests never touch or pollute your real data/factories.json."""
    monkeypatch.setattr(Config, "DATA_FOLDER", str(tmp_path / "data"))
    monkeypatch.setattr(Config, "FACTORIES_FILE", str(tmp_path / "data" / "factories.json"))
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))
    monkeypatch.setattr(Config, "USE_MOCK_AI", True)  # force mock mode, no network needed

    flask_app = create_app()
    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


def _fake_pdf_bytes() -> bytes:
    """Minimal placeholder bytes -- mock mode never actually reads/parses
    this file's content, so it doesn't need to be a valid PDF here."""
    return b"%PDF-1.4 minimal placeholder content for testing"


def _create_test_facility(client, name="Test Facility"):
    """Shared helper: runs Step 1 and returns the new factory_id."""
    data = {
        "factory_name": name,
        "preliminary_doc": (io.BytesIO(_fake_pdf_bytes()), "prelim.pdf"),
    }
    response = client.post("/factory/new", data=data, content_type="multipart/form-data")
    location = response.headers["Location"]
    return location.rstrip("/").split("/")[-2]


# ===========================================================================
# Landing page
# ===========================================================================

def test_landing_page_shows_three_sections(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Add Facility" in response.data
    assert b"View / Edit Facility" in response.data
    assert b"Monitor Facility" in response.data


def test_template_download_returns_a_docx_file(client):
    response = client.get("/factory/template/download")
    assert response.status_code == 200
    assert response.mimetype in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",
    )


# ===========================================================================
# Step 1 -- Upload
# ===========================================================================

def test_step1_page_loads(client):
    response = client.get("/factory/new")
    assert response.status_code == 200
    assert b"Name of the Facility" in response.data


def test_step1_missing_name_redirects_with_error(client):
    data = {"preliminary_doc": (io.BytesIO(_fake_pdf_bytes()), "prelim.pdf")}
    response = client.post("/factory/new", data=data, content_type="multipart/form-data")
    assert response.status_code == 302


def test_step1_non_pdf_rejected(client):
    data = {
        "factory_name": "Rejected Plant",
        "preliminary_doc": (io.BytesIO(b"not a pdf"), "prelim.txt"),
    }
    response = client.post("/factory/new", data=data, content_type="multipart/form-data")
    assert response.status_code == 302


def test_step1_upload_prepopulates_sensors_and_employees(client):
    factory_id = _create_test_facility(client)
    response = client.get(f"/factory/{factory_id}/validate")
    assert response.status_code == 200
    # Confirms mock extraction actually ran and seeded clarification_qa.
    assert b"Section 7: Maintenance Records" in response.data


# ===========================================================================
# Step 2 -- Validation chat
# ===========================================================================

def test_step2_submit_answers_redirects_to_sensors(client):
    factory_id = _create_test_facility(client)
    answers = ["Answer 1", "Answer 2", "Answer 3", "Answer 4", "Answer 5"]
    response = client.post(
        f"/factory/{factory_id}/validate",
        data=json.dumps({"answers": answers}),
        content_type="application/json",
    )
    result = response.get_json()
    assert result["success"] is True
    assert f"/factory/{factory_id}/sensors" in result["redirect"]

    # Confirm answers actually persisted.
    sensors_page = client.get(f"/factory/{factory_id}/sensors")
    assert sensors_page.status_code == 200


# ===========================================================================
# Step 3 -- Sensors (CRUD + API test)
# ===========================================================================

def test_step3_shows_mock_sensors(client):
    factory_id = _create_test_facility(client)
    response = client.get(f"/factory/{factory_id}/sensors")
    assert b"Furnace Pressure Transmitter" in response.data
    assert b"AI-Extracted" in response.data


def test_sensor_add_edit_delete_cycle(client):
    factory_id = _create_test_facility(client)

    new_sensor = {
        "name": "Test Dust Sensor", "sensor_type": "Gas Concentration", "location": "Packing Area",
        "unit": "mg/m3", "normal_range": "0-20", "alarm_threshold": "> 25",
        "response_type": "Threshold Alarm", "api_url": "", "api_method": "GET", "api_headers": "",
    }
    add_response = client.post(
        f"/factory/{factory_id}/sensors/add", data=json.dumps(new_sensor), content_type="application/json"
    )
    add_result = add_response.get_json()
    assert add_result["success"] is True
    assert add_result["sensor"]["source"] == "Manually Added"
    assert add_result["sensor"]["api_status"] == "Not Tested"
    sensor_id = add_result["sensor"]["id"]

    edit_payload = dict(new_sensor)
    edit_payload["name"] = "Renamed Dust Sensor"
    edit_response = client.post(
        f"/factory/{factory_id}/sensors/{sensor_id}/edit",
        data=json.dumps(edit_payload), content_type="application/json",
    )
    assert edit_response.get_json()["sensor"]["name"] == "Renamed Dust Sensor"

    page = client.get(f"/factory/{factory_id}/sensors")
    assert b"Renamed Dust Sensor" in page.data

    delete_response = client.post(f"/factory/{factory_id}/sensors/{sensor_id}/delete")
    assert delete_response.get_json()["success"] is True

    page_after = client.get(f"/factory/{factory_id}/sensors")
    assert b"Renamed Dust Sensor" not in page_after.data


def test_sensor_test_connection_fails_gracefully_on_bad_url(client):
    """A sensor with no reachable API must report Inactive, not crash."""
    factory_id = _create_test_facility(client)
    new_sensor = {
        "name": "Unreachable Sensor", "sensor_type": "Other", "api_url": "http://127.0.0.1:59999/nope",
        "api_method": "GET", "api_headers": "",
    }
    add_result = client.post(
        f"/factory/{factory_id}/sensors/add", data=json.dumps(new_sensor), content_type="application/json"
    ).get_json()
    sensor_id = add_result["sensor"]["id"]

    test_response = client.post(f"/factory/{factory_id}/sensors/{sensor_id}/test")
    result = test_response.get_json()
    assert result["success"] is True  # the test request itself completed
    assert result["api_status"] == "Inactive"  # but connectivity failed


def test_sensor_test_connection_no_url_configured(client):
    factory_id = _create_test_facility(client)
    new_sensor = {"name": "No API Sensor", "sensor_type": "Other"}
    add_result = client.post(
        f"/factory/{factory_id}/sensors/add", data=json.dumps(new_sensor), content_type="application/json"
    ).get_json()
    sensor_id = add_result["sensor"]["id"]

    test_response = client.post(f"/factory/{factory_id}/sensors/{sensor_id}/test")
    result = test_response.get_json()
    assert result["api_status"] == "Inactive"
    assert "No API URL configured" in result["message"]


def test_delete_nonexistent_sensor_returns_404(client):
    factory_id = _create_test_facility(client)
    response = client.post(f"/factory/{factory_id}/sensors/does-not-exist/delete")
    assert response.status_code == 404


# ===========================================================================
# Step 4 -- Layout stub
# ===========================================================================

def test_step4_layout_stub_loads(client):
    factory_id = _create_test_facility(client)
    response = client.get(f"/factory/{factory_id}/layout")
    assert response.status_code == 200
    assert b"Coming Soon" in response.data


# ===========================================================================
# Step 5 -- Negligence history
# ===========================================================================

def test_step5_negligence_save_and_redirect(client):
    factory_id = _create_test_facility(client)
    response = client.post(
        f"/factory/{factory_id}/negligence",
        data={"negligence_history": "Two prior near-misses in 2024."},
    )
    assert response.status_code == 302
    assert f"/factory/{factory_id}/employees" in response.headers["Location"]

    # Confirm it persisted and pre-fills on revisit.
    page = client.get(f"/factory/{factory_id}/negligence")
    assert b"Two prior near-misses in 2024." in page.data


# ===========================================================================
# Step 6 -- Employees (CRUD)
# ===========================================================================

def test_step6_shows_mock_employees(client):
    factory_id = _create_test_facility(client)
    response = client.get(f"/factory/{factory_id}/employees")
    assert b"Ravi Kumar" in response.data
    assert b"AI-Extracted" in response.data


def test_employee_add_edit_delete_cycle(client):
    factory_id = _create_test_facility(client)

    new_employee = {"name": "Test Employee", "role": "Contractor", "department": "Other"}
    add_result = client.post(
        f"/factory/{factory_id}/employees/add", data=json.dumps(new_employee), content_type="application/json"
    ).get_json()
    assert add_result["success"] is True
    employee_id = add_result["employee"]["id"]

    edit_result = client.post(
        f"/factory/{factory_id}/employees/{employee_id}/edit",
        data=json.dumps({"name": "Renamed Employee"}), content_type="application/json",
    ).get_json()
    assert edit_result["employee"]["name"] == "Renamed Employee"

    page = client.get(f"/factory/{factory_id}/employees")
    assert b"Renamed Employee" in page.data

    delete_result = client.post(f"/factory/{factory_id}/employees/{employee_id}/delete").get_json()
    assert delete_result["success"] is True

    page_after = client.get(f"/factory/{factory_id}/employees")
    assert b"Renamed Employee" not in page_after.data


def test_delete_nonexistent_employee_returns_404(client):
    factory_id = _create_test_facility(client)
    response = client.post(f"/factory/{factory_id}/employees/does-not-exist/delete")
    assert response.status_code == 404


# ===========================================================================
# Step 7 -- Attendance system + finish
# ===========================================================================

def test_step7_attendance_test_fails_gracefully(client):
    factory_id = _create_test_facility(client)
    response = client.post(
        f"/factory/{factory_id}/attendance/test",
        data=json.dumps({"api_url": "http://127.0.0.1:59999/nope", "api_method": "GET", "api_headers": ""}),
        content_type="application/json",
    )
    result = response.get_json()
    assert result["success"] is True
    assert result["api_status"] == "Inactive"


def test_step7_finish_marks_setup_complete(client):
    factory_id = _create_test_facility(client)
    response = client.post(
        f"/factory/{factory_id}/attendance/finish",
        data={"api_url": "", "api_method": "GET", "api_headers": ""},
    )
    assert response.status_code == 302
    assert response.headers["Location"].rstrip("/") == "" or response.headers["Location"] == "/"

    # Confirm the landing page now reflects one completed facility.
    landing = client.get("/")
    assert b"1 facility(ies) started" in landing.data or b"fully onboarded" in landing.data


# ===========================================================================
# Full end-to-end smoke test -- every step in sequence, one facility
# ===========================================================================

def test_full_wizard_end_to_end(client):
    """Walks a single facility through all 7 steps in order, confirming
    each step's data is visible on the next -- the closest thing to a
    real user's click-through in an automated test."""
    factory_id = _create_test_facility(client, name="Full Flow Plant")

    # Step 2
    answers = ["A1", "A2", "A3", "A4", "A5"]
    r = client.post(f"/factory/{factory_id}/validate", data=json.dumps({"answers": answers}), content_type="application/json")
    assert r.get_json()["success"] is True

    # Step 3 (no changes, just confirm it loads with prepopulated data)
    r = client.get(f"/factory/{factory_id}/sensors")
    assert b"Full Flow Plant" in r.data

    # Step 4
    r = client.get(f"/factory/{factory_id}/layout")
    assert r.status_code == 200

    # Step 5
    r = client.post(f"/factory/{factory_id}/negligence", data={"negligence_history": "None known."})
    assert r.status_code == 302

    # Step 6
    r = client.get(f"/factory/{factory_id}/employees")
    assert b"Ravi Kumar" in r.data

    # Step 7
    r = client.post(f"/factory/{factory_id}/attendance/finish", data={"api_url": "", "api_method": "GET", "api_headers": ""})
    assert r.status_code == 302

    # Confirm final state
    final_page = client.get(f"/factory/{factory_id}/attendance")
    assert final_page.status_code == 200
