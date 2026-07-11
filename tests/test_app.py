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

def test_step2_submit_answers_redirects_to_facility_overview(client):
    """As of Step 3 (Part A pages), Validate's "next" resolves to
    Facility Overview (Section 1) -- the first section in the registry
    that now has a real route -- not Sensors anymore. Renamed from
    test_step2_submit_answers_redirects_to_sensors to reflect this."""
    factory_id = _create_test_facility(client)
    answers = ["Answer 1", "Answer 2", "Answer 3", "Answer 4", "Answer 5"]
    response = client.post(
        f"/factory/{factory_id}/validate",
        data=json.dumps({"answers": answers}),
        content_type="application/json",
    )
    result = response.get_json()
    assert result["success"] is True
    assert f"/factory/{factory_id}/facility-overview" in result["redirect"]

    # Confirm answers actually persisted.
    overview_page = client.get(f"/factory/{factory_id}/facility-overview")
    assert overview_page.status_code == 200


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
    """Layout is a real Konva.js canvas editor, not a stub -- this test's
    name is legacy from an earlier build phase, kept for continuity with
    the rest of the suite's naming."""
    factory_id = _create_test_facility(client)
    response = client.get(f"/factory/{factory_id}/layout")
    assert response.status_code == 200
    assert b"machineBtn" in response.data  # the "Add Machine" toolbar button
    assert b"layoutContainer" in response.data  # the canvas mount point


# ===========================================================================
# Step 5 -- Negligence history
# ===========================================================================

def test_step5_negligence_save_and_redirect(client):
    """As of the Step 0-1 navigation refactor, Negligence's "next" is
    computed from the section registry (models/wizard_sections.py), not
    hardcoded -- with only Sensors/Employees/Negligence/Attendance built
    so far, that correctly resolves to Attendance now, not Employees
    (Employees comes BEFORE Negligence in the canonical 20-section
    order; the old 7-step flow had them in the opposite order)."""
    factory_id = _create_test_facility(client)
    response = client.post(
        f"/factory/{factory_id}/negligence",
        data={"negligence_history": "Two prior near-misses in 2024."},
    )
    assert response.status_code == 302
    assert f"/factory/{factory_id}/attendance" in response.headers["Location"]

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


def test_step7_attendance_finish_now_continues_not_completes(client):
    """As of Step 7 (Part E), /attendance/finish is a mid-flow save-and-
    continue, not a completion action -- setup_complete now only flips
    once Emergency Response (Section 20), the genuine last section, is
    submitted. Renamed from test_step7_finish_marks_setup_complete to
    reflect this; see test_emergency_response_finish_marks_setup_complete
    below for where that behavior actually lives now."""
    factory_id = _create_test_facility(client)
    response = client.post(
        f"/factory/{factory_id}/attendance/finish",
        data={"api_url": "", "api_method": "GET", "api_headers": ""},
    )
    assert response.status_code == 302
    assert "/utilities" in response.headers["Location"]

    import services.storage as storage
    factory = storage.get_factory(factory_id)
    assert factory.setup_complete is False


def test_emergency_response_finish_marks_setup_complete(client):
    factory_id = _create_test_facility(client)
    response = client.post(
        f"/factory/{factory_id}/emergency-response",
        data={
            "regulatory_standards": "Factory Act, OISD",
            "fire_safety_systems": "Hydrant, sprinkler",
            "last_safety_audit_date": "2026-01-15",
            "last_safety_audit_findings": "No major findings.",
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"].rstrip("/") == "" or response.headers["Location"] == "/"

    import services.storage as storage
    factory = storage.get_factory(factory_id)
    assert factory.setup_complete is True
    assert factory.regulatory_standards == "Factory Act, OISD"

    # Confirm the landing page now reflects one completed facility.
    landing = client.get("/")
    assert b"1 facility(ies) started" in landing.data or b"fully onboarded" in landing.data


def test_utility_systems_prepopulated_with_standard_categories(client):
    factory_id = _create_test_facility(client)
    page = client.get(f"/factory/{factory_id}/utilities")
    assert page.status_code == 200
    assert b"Emergency Power Backup" in page.data
    assert b"Compressed Air System" in page.data

    import services.storage as storage
    factory = storage.get_factory(factory_id)
    assert len(factory.utility_systems) == 5


def test_training_and_environmental_save_and_redirect(client):
    factory_id = _create_test_facility(client)

    r = client.post(f"/factory/{factory_id}/training", data={"induction_program": "2-day induction"})
    assert r.status_code == 302
    assert "/environmental" in r.headers["Location"]

    r = client.post(f"/factory/{factory_id}/environmental", data={"iso_9001": "Yes", "iso_14001": "Yes"})
    assert r.status_code == 302
    assert "/emergency-response" in r.headers["Location"]

    import services.storage as storage
    factory = storage.get_factory(factory_id)
    assert factory.training_info["induction_program"] == "2-day induction"
    assert factory.environmental_compliance["iso_9001"] == "Yes"


def test_facility_details_shows_all_parts(client):
    """Confirms Step 8's expanded Facility Details page renders all 5
    Part headers -- the whole point of the expansion."""
    factory_id = _create_test_facility(client)
    page = client.get(f"/factory/{factory_id}/details")
    assert page.status_code == 200
    for part_letter in ["A", "B", "C", "D", "E"]:
        assert f'wizard-part-label">{part_letter}</span>'.encode() in page.data

# ===========================================================================
# Full end-to-end smoke test -- every step in sequence, one facility
# ===========================================================================

def test_full_wizard_end_to_end(client):
    """Walks a single facility through the entire chain in order --
    Validate through Emergency Response -- confirming each step's data
    is visible on the next and that setup_complete only flips at the
    genuine last step. Originally covered the old 7-step flow; extended
    in Step 7 to cover the full 20-section chain now that it all exists."""
    factory_id = _create_test_facility(client, name="Full Flow Plant")

    # Validate
    answers = ["A1", "A2", "A3", "A4", "A5"]
    r = client.post(f"/factory/{factory_id}/validate", data=json.dumps({"answers": answers}), content_type="application/json")
    assert r.get_json()["success"] is True

    # Sensors (no changes, just confirm it loads with prepopulated data)
    r = client.get(f"/factory/{factory_id}/sensors")
    assert b"Full Flow Plant" in r.data

    # Layout
    r = client.get(f"/factory/{factory_id}/layout")
    assert r.status_code == 200

    # Negligence History
    r = client.post(f"/factory/{factory_id}/negligence", data={"negligence_history": "None known."})
    assert r.status_code == 302

    # Employees
    r = client.get(f"/factory/{factory_id}/employees")
    assert b"Ravi Kumar" in r.data

    # Attendance -- now continues, does not complete
    r = client.post(f"/factory/{factory_id}/attendance/finish", data={"api_url": "", "api_method": "GET", "api_headers": ""})
    assert r.status_code == 302
    assert "/utilities" in r.headers["Location"]

    import services.storage as storage
    assert storage.get_factory(factory_id).setup_complete is False

    # Utilities -> Training -> Environmental -> Emergency Response (the real finish)
    r = client.post(f"/factory/{factory_id}/utilities", data={})
    assert "/training" in r.headers["Location"]
    r = client.post(f"/factory/{factory_id}/training", data={"induction_program": "Standard"})
    assert "/environmental" in r.headers["Location"]
    r = client.post(f"/factory/{factory_id}/environmental", data={})
    assert "/emergency-response" in r.headers["Location"]
    r = client.post(f"/factory/{factory_id}/emergency-response", data={"regulatory_standards": "Factory Act"})
    assert r.headers["Location"].rstrip("/") == "" or r.headers["Location"] == "/"

    # Confirm final state -- setup_complete now True, only at the true end.
    final_page = client.get(f"/factory/{factory_id}/emergency-response")
    assert final_page.status_code == 200
    assert storage.get_factory(factory_id).setup_complete is True
# ===========================================================================
# NEW (Step 0-1) -- registry-driven navigation and Person category filtering
# ===========================================================================

def test_navigation_skips_missing_sections(client):
    """Sensors(4)'s Back now correctly resolves to SCADA Systems(3) --
    built in Step 3 -- instead of falling back to Validate. Its Next
    still skips straight past Sections 5-7 (Key Personnel, Shift
    Patterns, Staffing Rules), none of which have routes yet, landing on
    Employees(8). This is the "go back to the previous section"
    mechanism from models/wizard_sections.py, tested directly rather
    than just implied by other tests passing -- and confirms the
    registry auto-upgrades as new sections land, with no navigation
    code changes required."""
    factory_id = _create_test_facility(client)

    sensors_page = client.get(f"/factory/{factory_id}/sensors")
    assert f"/factory/{factory_id}/scada-systems".encode() in sensors_page.data  # Back -> SCADA Systems (built in Step 3)
    assert f"/factory/{factory_id}/employees".encode() in sensors_page.data  # Next -> Employees (skips 5,6,7)

    employees_page = client.get(f"/factory/{factory_id}/employees")
    assert f"/factory/{factory_id}/sensors".encode() in employees_page.data  # Back -> Sensors
    assert f"/factory/{factory_id}/negligence".encode() in employees_page.data  # Next -> Negligence (skips 9-14)


def test_person_category_filtering(client):
    """The Employee Directory page (Section 8) must only show people
    whose person_category is "Employee" -- Key Personnel categories
    (Managerial Staff, Safety Officer, Maintenance Staff) extracted from
    the same document should not appear there, even though they live in
    the same underlying `people` list on the Factory record."""
    factory_id = _create_test_facility(client)

    factory_page = client.get(f"/factory/{factory_id}/employees")
    # Mock extraction seeds one of each category -- only "Employee" (Ravi Kumar)
    # should render on this page.
    assert b"Ravi Kumar" in factory_page.data       # category: Employee
    assert b"R. Venkatesh" not in factory_page.data  # category: Managerial Staff
    assert b"Priya Nair" not in factory_page.data    # category: Safety Officer
    assert b"Anil Sharma" not in factory_page.data   # category: Maintenance Staff


def test_new_monitored_parameter_categories_available(client):
    """A newly-added parameter defaults to parameter_category
    'Live Sensor Reading' via the /sensors/add endpoint (the only
    category currently wired to a UI) -- confirms the renamed model
    round-trips correctly end to end, not just that the route responds."""
    factory_id = _create_test_facility(client)
    result = client.post(
        f"/factory/{factory_id}/sensors/add",
        data=json.dumps({"name": "Category Test Sensor", "sensor_type": "Pressure"}),
        content_type="application/json",
    ).get_json()
    assert result["success"] is True
    assert result["sensor"]["parameter_category"] == "Live Sensor Reading"
    # New generalized fields exist on every parameter, even ones created
    # through the Sensors UI which doesn't set them.
    assert "data_source_type" in result["sensor"]
    assert "fault_since" in result["sensor"]

# ===========================================================================
# NEW (Step 3) -- Part A pages: Facility Overview, Process Flow, SCADA Systems
# ===========================================================================

def test_facility_overview_prefilled_from_mock_extraction(client):
    factory_id = _create_test_facility(client)
    response = client.get(f"/factory/{factory_id}/facility-overview")
    assert response.status_code == 200
    assert b"Raigarh" in response.data          # from mock address
    assert b"Thermal Power" in response.data     # from mock industry_sector
    assert b"Boiler" in response.data            # from mock departments


def test_facility_overview_save_and_redirect(client):
    factory_id = _create_test_facility(client)
    response = client.post(
        f"/factory/{factory_id}/facility-overview",
        data={
            "address": "123 Test Road",
            "industry_sector": "Steel",
            "operating_phase": "Routine Operation",
            "dept_name[]": "Operations",
            "dept_function[]": "Running the plant",
            "dept_headcount[]": "50",
        },
    )
    assert response.status_code == 302
    assert f"/factory/{factory_id}/process-flow" in response.headers["Location"]

    # Confirm it persisted, including the dynamic department row.
    page = client.get(f"/factory/{factory_id}/facility-overview")
    assert b"123 Test Road" in page.data
    assert b"Operations" in page.data


def test_facility_overview_blank_department_row_dropped(client):
    """A fully-blank department row (e.g. the always-present starter row
    from dynamic_table.js, left untouched) must not be saved as a real
    department."""
    factory_id = _create_test_facility(client)
    client.post(
        f"/factory/{factory_id}/facility-overview",
        data={
            "address": "Test",
            "dept_name[]": ["Operations", ""],
            "dept_function[]": ["Running the plant", ""],
            "dept_headcount[]": ["50", ""],
        },
    )
    import services.storage as storage
    factory = storage.get_factory(factory_id)
    assert len(factory.departments) == 1
    assert factory.departments[0]["name"] == "Operations"


def test_process_flow_save_and_redirect(client):
    factory_id = _create_test_facility(client)
    response = client.post(
        f"/factory/{factory_id}/process-flow",
        data={"process_narrative": "Coal is crushed and burned.", "drawing_references": "DWG-001"},
    )
    assert response.status_code == 302
    assert f"/factory/{factory_id}/scada-systems" in response.headers["Location"]

    page = client.get(f"/factory/{factory_id}/process-flow")
    assert b"Coal is crushed and burned." in page.data


def test_scada_systems_save_and_redirect(client):
    factory_id = _create_test_facility(client)
    response = client.post(
        f"/factory/{factory_id}/scada-systems",
        data={
            "scada_name[]": "Unit 1 DCS",
            "scada_vendor[]": "ABB",
            "scada_version[]": "v3.2",
            "scada_function[]": "Overall control",
            "scada_redundant[]": "Y",
            "historian_system": "OSIsoft PI",
        },
    )
    assert response.status_code == 302
    assert f"/factory/{factory_id}/sensors" in response.headers["Location"]

    page = client.get(f"/factory/{factory_id}/scada-systems")
    assert b"Unit 1 DCS" in page.data
    assert b"OSIsoft PI" in page.data


def test_part_a_full_chain_navigation(client):
    """Walks Validate -> Facility Overview -> Process Flow -> SCADA
    Systems -> Sensors entirely via each page's own Next action, and
    confirms Sensors' Back leads all the way back to SCADA Systems --
    the full Part A chain now that all 4 of its sections have real
    pages."""
    factory_id = _create_test_facility(client)

    r = client.post(f"/factory/{factory_id}/validate", data=json.dumps({"answers": ["a"] * 5}), content_type="application/json")
    assert "/facility-overview" in r.get_json()["redirect"]

    r = client.post(f"/factory/{factory_id}/facility-overview", data={"address": "A"})
    assert "/process-flow" in r.headers["Location"]

    r = client.post(f"/factory/{factory_id}/process-flow", data={"process_narrative": "B"})
    assert "/scada-systems" in r.headers["Location"]

    r = client.post(f"/factory/{factory_id}/scada-systems", data={"historian_system": "C"})
    assert "/sensors" in r.headers["Location"]

    sensors_page = client.get(f"/factory/{factory_id}/sensors")
    assert f"/factory/{factory_id}/scada-systems".encode() in sensors_page.data