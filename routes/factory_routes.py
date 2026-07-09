"""
routes/factory_routes.py
---------------------------
Routes for the full "Add Facility" wizard (7 steps):

  Step 1  GET/POST /factory/new                    -> download template, upload filled PDF
  Step 2  GET/POST /factory/<id>/validate           -> chatbot-style gap-filling Q&A
  Step 3  GET      /factory/<id>/sensors            -> sensor list + API config + test
  Step 4  GET      /factory/<id>/layout             -> interactive facility layout editor (Konva.js canvas)
  Step 5  GET/POST /factory/<id>/negligence         -> incident/negligence history free text
  Step 6  GET      /factory/<id>/employees          -> employee list (same CRUD pattern as sensors)
  Step 7  GET      /factory/<id>/attendance         -> attendance system API config + test + finish

Plus JSON API endpoints for AJAX CRUD (sensors, employees) and the two
"Test Connection" endpoints (sensor API, attendance API), all under the
same /factory/<id>/... prefix.

NOTE ON NAMING: the product now calls this "Add Facility" in the UI.
The code keeps "factory" throughout (module name, URL prefix, variable
names) -- see models/factory.py docstring for why.
"""

import os
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, flash, send_from_directory
from werkzeug.utils import secure_filename

from config import Config
from models.factory import Factory
from models.sensor import Sensor, SENSOR_TYPE_CHOICES, RESPONSE_TYPE_CHOICES, API_METHOD_CHOICES
from models.employee import Employee, DEPARTMENT_CHOICES, BLOOD_GROUP_CHOICES
from services import storage
from services.ai_extraction import extract_from_document
from services.api_tester import test_endpoint

factory_bp = Blueprint("factory", __name__, url_prefix="/factory")


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in Config.ALLOWED_EXTENSIONS


def _get_factory_or_404(factory_id):
    """Shared lookup used by every step route. Returns the Factory, or
    None after already redirecting -- callers should `return` immediately
    if this returns None."""
    factory = storage.get_factory(factory_id)
    if not factory:
        flash("Facility not found.", "error")
        return None
    return factory


# ===========================================================================
# STEP 1 -- Download template, upload filled document
# ===========================================================================

@factory_bp.route("/template/download")
def download_template():
    """Serves the blank Facility Onboarding Template .docx for the user
    to fill in. The file ships inside static/templates_download/ as part
    of the project -- it is NOT regenerated on the fly."""
    templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static", "templates_download")
    templates_dir = os.path.abspath(templates_dir)
    return send_from_directory(
        templates_dir,
        "facility_onboarding_template.docx",
        as_attachment=True,
        download_name="Facility_Onboarding_Template.docx",
    )


@factory_bp.route("/new", methods=["GET", "POST"])
def new_factory():
    """Step 1 -- download template + facility name + upload filled PDF."""
    if request.method == "GET":
        return render_template("add_facility_step1_upload.html")

    factory_name = request.form.get("factory_name", "").strip()
    uploaded_file = request.files.get("preliminary_doc")

    if not factory_name:
        flash("Please enter a facility name.", "error")
        return redirect(url_for("factory.new_factory"))

    if not uploaded_file or uploaded_file.filename == "":
        flash("Please upload your completed Facility Onboarding Template as a PDF.", "error")
        return redirect(url_for("factory.new_factory"))

    if not _allowed_file(uploaded_file.filename):
        flash("Only PDF files are supported for the completed template.", "error")
        return redirect(url_for("factory.new_factory"))

    # Create the factory record first so we have a stable id to prefix the
    # saved filename with (avoids collisions between facilities that
    # upload a file with the same original name).
    factory = Factory(name=factory_name)

    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
    safe_name = secure_filename(uploaded_file.filename)
    stored_filename = f"{factory.id}_{safe_name}"
    file_path = os.path.join(Config.UPLOAD_FOLDER, stored_filename)
    uploaded_file.save(file_path)
    factory.preliminary_doc_filename = stored_filename

    # Single AI call extracts sensors, employees, process summary, AND
    # the document validation results (missing sections + questions) --
    # see services/ai_extraction.py for why this is one call, not four.
    result = extract_from_document(file_path)
    factory.ai_summary = result["process_summary"]
    factory.sensors = result["sensors"]
    factory.employees = result["employees"]
    factory.missing_sections = result["missing_sections"]
    # Seed clarification_qa with each question and a blank answer; the
    # Step 2 chat UI fills in the answers.
    factory.clarification_qa = [{"question": q, "answer": ""} for q in result["clarifying_questions"]]

    storage.save_factory(factory)

    return redirect(url_for("factory.validate_page", factory_id=factory.id))


# ===========================================================================
# STEP 2 -- Document validation / chatbot-style gap-filling Q&A
# ===========================================================================

@factory_bp.route("/<factory_id>/validate", methods=["GET"])
def validate_page(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    return render_template("add_facility_step2_validate.html", factory=factory)


@factory_bp.route("/<factory_id>/validate", methods=["POST"])
def submit_validation(factory_id):
    """Saves all chat answers at once (submitted together by the JS once
    every question has been answered) rather than one round-trip per
    message -- fewer network calls, fewer places for a partial-save bug
    to creep in."""
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    data = request.get_json(force=True) or {}
    answers = data.get("answers", [])  # list of strings, same order as clarification_qa

    updated_qa = []
    for i, qa in enumerate(factory.clarification_qa):
        answer = answers[i] if i < len(answers) else ""
        updated_qa.append({"question": qa["question"], "answer": answer})

    storage.update_factory_fields(factory_id, clarification_qa=updated_qa, validation_complete=True)
    return jsonify({"success": True, "redirect": url_for("factory.sensors_page", factory_id=factory_id)})


# ===========================================================================
# STEP 3 -- Sensors & Systems (with API config + test)
# ===========================================================================

@factory_bp.route("/<factory_id>/sensors", methods=["GET"])
def sensors_page(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    return render_template(
        "add_facility_step3_sensors.html",
        factory=factory,
        sensor_type_choices=SENSOR_TYPE_CHOICES,
        response_type_choices=RESPONSE_TYPE_CHOICES,
        api_method_choices=API_METHOD_CHOICES,
    )


@factory_bp.route("/<factory_id>/sensors/add", methods=["POST"])
def add_sensor(factory_id):
    factory = storage.get_factory(factory_id)
    if not factory:
        return jsonify({"success": False, "error": "Facility not found"}), 404

    data = request.get_json(force=True)
    sensor = Sensor(
        name=data.get("name", "Unnamed Sensor"),
        sensor_type=data.get("sensor_type", "Other"),
        location=data.get("location", ""),
        unit=data.get("unit", ""),
        normal_range=data.get("normal_range", ""),
        alarm_threshold=data.get("alarm_threshold", ""),
        response_type=data.get("response_type", "Continuous Analog"),
        notes=data.get("notes", ""),
        api_url=data.get("api_url", ""),
        api_method=data.get("api_method", "GET"),
        api_headers=data.get("api_headers", ""),
        api_json_path=data.get("api_json_path", ""),
        source="Manually Added",
    )
    storage.upsert_sensor(factory_id, sensor)
    return jsonify({"success": True, "sensor": sensor.to_dict()})


@factory_bp.route("/<factory_id>/sensors/<sensor_id>/edit", methods=["POST"])
def edit_sensor(factory_id, sensor_id):
    factory = storage.get_factory(factory_id)
    if not factory:
        return jsonify({"success": False, "error": "Facility not found"}), 404

    existing = next((s for s in factory.sensors if s.id == sensor_id), None)
    if not existing:
        return jsonify({"success": False, "error": "Sensor not found"}), 404

    data = request.get_json(force=True)
    existing.name = data.get("name", existing.name)
    existing.sensor_type = data.get("sensor_type", existing.sensor_type)
    existing.location = data.get("location", existing.location)
    existing.unit = data.get("unit", existing.unit)
    existing.normal_range = data.get("normal_range", existing.normal_range)
    existing.alarm_threshold = data.get("alarm_threshold", existing.alarm_threshold)
    existing.response_type = data.get("response_type", existing.response_type)
    existing.notes = data.get("notes", existing.notes)

    # If the API connection details changed, the last test result is no
    # longer trustworthy -- reset status so the badge doesn't lie.
    new_api_url = data.get("api_url", existing.api_url)
    new_api_method = data.get("api_method", existing.api_method)
    new_api_headers = data.get("api_headers", existing.api_headers)
    if (new_api_url, new_api_method, new_api_headers) != (existing.api_url, existing.api_method, existing.api_headers):
        existing.api_status = "Not Tested"
        existing.api_last_tested = ""
    existing.api_url = new_api_url
    existing.api_method = new_api_method
    existing.api_headers = new_api_headers
    existing.api_json_path = data.get("api_json_path", existing.api_json_path)
    # Note: editing does NOT change `source` -- a sensor the AI originally
    # extracted stays labeled "AI-Extracted" even after a human corrects it.

    storage.upsert_sensor(factory_id, existing)
    return jsonify({"success": True, "sensor": existing.to_dict()})


@factory_bp.route("/<factory_id>/sensors/<sensor_id>/delete", methods=["POST"])
def delete_sensor_route(factory_id, sensor_id):
    success = storage.delete_sensor(factory_id, sensor_id)
    if not success:
        return jsonify({"success": False, "error": "Sensor or facility not found"}), 404
    return jsonify({"success": True})


@factory_bp.route("/<factory_id>/sensors/<sensor_id>/test", methods=["POST"])
def test_sensor_connection(factory_id, sensor_id):
    """Tests the sensor's SAVED API configuration (not any unsaved edits
    currently sitting in the modal -- the user must Save first). Updates
    and persists api_status so the badge is still correct after a page
    reload, not just in the current browser session."""
    from datetime import datetime

    sensor = storage.get_sensor(factory_id, sensor_id)
    if not sensor:
        return jsonify({"success": False, "error": "Sensor not found"}), 404

    result = test_endpoint(sensor.api_url, sensor.api_method, sensor.api_headers)

    sensor.api_status = "Active" if result["success"] else "Inactive"
    sensor.api_last_tested = datetime.utcnow().isoformat()
    storage.upsert_sensor(factory_id, sensor)

    return jsonify({
        "success": True,  # the test-request itself completed (regardless of connectivity outcome)
        "api_status": sensor.api_status,
        "message": result["message"],
        "status_code": result["status_code"],
    })


# ===========================================================================
# STEP 4 -- Facility Layout (interactive Konva.js canvas editor)
# ===========================================================================

@factory_bp.route("/<factory_id>/layout", methods=["GET"])
def layout_page(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))
    return render_template("add_facility_step4_layout.html", factory=factory)


@factory_bp.route("/<factory_id>/layout/save", methods=["POST"])
def save_layout(factory_id):
    """Persists the canvas JSON export from static/js/layout_editor.js --
    a flat list of shape dicts (machines/text/lines). Called both by the
    explicit 'Save Layout' button and automatically when the user clicks
    'Next', so work is never silently lost."""
    factory = storage.get_factory(factory_id)
    if not factory:
        return jsonify({"success": False, "error": "Facility not found"}), 404

    data = request.get_json(force=True)
    layout_data = data.get("layout_data")
    if not isinstance(layout_data, list):
        return jsonify({"success": False, "error": "layout_data must be a list"}), 400

    storage.update_factory_fields(factory_id, layout_data=layout_data)
    return jsonify({"success": True, "shape_count": len(layout_data)})


# ===========================================================================
# STEP 5 -- Incident / Negligence History
# ===========================================================================

@factory_bp.route("/<factory_id>/negligence", methods=["GET", "POST"])
def negligence_page(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    if request.method == "GET":
        return render_template("add_facility_step5_negligence.html", factory=factory)

    negligence_text = request.form.get("negligence_history", "").strip()
    storage.update_factory_fields(factory_id, negligence_history=negligence_text)
    return redirect(url_for("factory.employees_page", factory_id=factory_id))


# ===========================================================================
# STEP 6 -- Employee Directory (same CRUD pattern as Sensors)
# ===========================================================================

@factory_bp.route("/<factory_id>/employees", methods=["GET"])
def employees_page(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    # employee_lookup resolves a manager_id -> name for display on each
    # card (Jinja side). employee_options is the same data reshaped for
    # the JS-side Manager <select> dropdown, since that list needs to be
    # rebuilt client-side every time an employee is added/edited/deleted
    # without a full page reload.
    employee_lookup = {e.id: e.name for e in factory.employees}
    employee_options = [{"id": e.id, "name": e.name} for e in factory.employees]

    return render_template(
        "add_facility_step6_employees.html",
        factory=factory,
        department_choices=DEPARTMENT_CHOICES,
        blood_group_choices=BLOOD_GROUP_CHOICES,
        employee_lookup=employee_lookup,
        employee_options=employee_options,
    )


@factory_bp.route("/<factory_id>/employees/add", methods=["POST"])
def add_employee(factory_id):
    factory = storage.get_factory(factory_id)
    if not factory:
        return jsonify({"success": False, "error": "Facility not found"}), 404

    data = request.get_json(force=True)

    # Defensive: only accept a manager_id that actually belongs to an
    # existing employee on this facility -- silently drop anything else
    # (stale/tampered client data) rather than 500 on a low-stakes field.
    valid_employee_ids = {e.id for e in factory.employees}
    manager_id = data.get("manager_id", "")
    if manager_id and manager_id not in valid_employee_ids:
        manager_id = ""

    employee = Employee(
        name=data.get("name", "Unnamed Employee"),
        role=data.get("role", ""),
        department=data.get("department", ""),
        manager_id=manager_id,
        email=data.get("email", ""),
        phone=data.get("phone", ""),
        blood_group=data.get("blood_group", ""),
        working_hours=data.get("working_hours", ""),
        working_days=data.get("working_days", ""),
        emergency_contact_name=data.get("emergency_contact_name", ""),
        emergency_contact_phone=data.get("emergency_contact_phone", ""),
        emergency_contact_relation=data.get("emergency_contact_relation", ""),
        notes=data.get("notes", ""),
        source="Manually Added",
    )
    storage.upsert_employee(factory_id, employee)
    return jsonify({"success": True, "employee": employee.to_dict()})


@factory_bp.route("/<factory_id>/employees/<employee_id>/edit", methods=["POST"])
def edit_employee(factory_id, employee_id):
    factory = storage.get_factory(factory_id)
    if not factory:
        return jsonify({"success": False, "error": "Facility not found"}), 404

    existing = next((e for e in factory.employees if e.id == employee_id), None)
    if not existing:
        return jsonify({"success": False, "error": "Employee not found"}), 404

    data = request.get_json(force=True)
    existing.name = data.get("name", existing.name)
    existing.role = data.get("role", existing.role)
    existing.department = data.get("department", existing.department)
    existing.email = data.get("email", existing.email)
    existing.phone = data.get("phone", existing.phone)
    existing.blood_group = data.get("blood_group", existing.blood_group)
    existing.working_hours = data.get("working_hours", existing.working_hours)
    existing.working_days = data.get("working_days", existing.working_days)
    existing.emergency_contact_name = data.get("emergency_contact_name", existing.emergency_contact_name)
    existing.emergency_contact_phone = data.get("emergency_contact_phone", existing.emergency_contact_phone)
    existing.emergency_contact_relation = data.get("emergency_contact_relation", existing.emergency_contact_relation)
    existing.notes = data.get("notes", existing.notes)

    storage.upsert_employee(factory_id, existing)
    return jsonify({"success": True, "employee": existing.to_dict()})


@factory_bp.route("/<factory_id>/employees/<employee_id>/delete", methods=["POST"])
def delete_employee_route(factory_id, employee_id):
    success = storage.delete_employee(factory_id, employee_id)
    if not success:
        return jsonify({"success": False, "error": "Employee or facility not found"}), 404
    return jsonify({"success": True})


# ===========================================================================
# STEP 7 -- Attendance System Integration (final step)
# ===========================================================================

@factory_bp.route("/<factory_id>/attendance", methods=["GET"])
def attendance_page(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))
    return render_template("add_facility_step7_attendance.html", factory=factory)


@factory_bp.route("/<factory_id>/attendance/test", methods=["POST"])
def test_attendance_connection(factory_id):
    """Tests connectivity using whatever is in the request body (NOT
    necessarily saved yet) -- unlike the sensor test, this is the very
    last step of the wizard with only one endpoint to configure, so
    testing the in-progress form values directly is low-risk and saves
    the user a click."""
    from datetime import datetime

    factory = storage.get_factory(factory_id)
    if not factory:
        return jsonify({"success": False, "error": "Facility not found"}), 404

    data = request.get_json(force=True)
    url = data.get("api_url", "")
    method = data.get("api_method", "GET")
    headers = data.get("api_headers", "")

    result = test_endpoint(url, method, headers)
    status = "Active" if result["success"] else "Inactive"

    storage.update_factory_fields(
        factory_id,
        attendance_api_url=url,
        attendance_api_method=method,
        attendance_api_headers=headers,
        attendance_api_status=status,
        attendance_api_last_tested=datetime.utcnow().isoformat(),
    )

    return jsonify({
        "success": True,
        "api_status": status,
        "message": result["message"],
        "status_code": result["status_code"],
    })


@factory_bp.route("/<factory_id>/attendance/finish", methods=["POST"])
def finish_setup(factory_id):
    """Final step of the wizard -- saves whatever attendance config is
    currently in the form and marks the facility as fully onboarded."""
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    storage.update_factory_fields(
        factory_id,
        attendance_api_url=request.form.get("api_url", "").strip(),
        attendance_api_method=request.form.get("api_method", "GET"),
        attendance_api_headers=request.form.get("api_headers", "").strip(),
        setup_complete=True,
    )
    flash(f'"{factory.name}" onboarding complete.', "success")
    return redirect(url_for("main.landing"))

# ===========================================================================
# VIEW / EDIT FACILITY -- lists all onboarded facilities, shows a full
# read view of one facility's data, and lets the user rename it inline.
# Editing any individual section (sensors, employees, negligence history,
# attendance) reuses the exact same wizard step pages/routes above --
# no separate edit-mode logic, just a link into the same page.
# ===========================================================================

@factory_bp.route("/list", methods=["GET"])
def list_facilities():
    """Landing page for the 'View / Edit Facility' section -- shows
    every facility on record, including ones still mid-wizard."""
    factories = storage.list_factories()
    factories = sorted(factories, key=lambda f: f.created_at, reverse=True)
    return render_template("facility_list.html", factories=factories)


@factory_bp.route("/<factory_id>/details", methods=["GET"])
def facility_details(factory_id):
    """Read view of everything submitted for one facility, with an
    'Edit' link into each section's existing wizard-step page."""
    factory = storage.get_factory(factory_id)
    if not factory:
        flash("Facility not found.", "error")
        return redirect(url_for("factory.list_facilities"))
    return render_template("facility_details.html", factory=factory)


@factory_bp.route("/<factory_id>/rename", methods=["POST"])
def rename_facility(factory_id):
    """Inline rename used only on the facility_details.html page."""
    factory = storage.get_factory(factory_id)
    if not factory:
        return jsonify({"success": False, "error": "Facility not found"}), 404

    data = request.get_json(force=True)
    new_name = (data.get("name") or "").strip()
    if not new_name:
        return jsonify({"success": False, "error": "Name cannot be empty"}), 400

    storage.update_factory_fields(factory_id, name=new_name)
    return jsonify({"success": True, "name": new_name})

@factory_bp.route("/<factory_id>/train", methods=["POST"])
def train_and_configure(factory_id):
    """Stub for the 'Train & Configure AI' action, shown on the Facility
    Details page once every wizard step reports 'done'. What this
    actually does is intentionally undecided for now -- this route just
    confirms the button works end-to-end (visible only when the facility
    is fully configured, clicking it round-trips to the server) without
    committing to a real implementation yet."""
    factory = storage.get_factory(factory_id)
    if not factory:
        flash("Facility not found.", "error")
        return redirect(url_for("factory.list_facilities"))

    flash(f'"{factory.name}" is fully configured. Train & Configure AI is not implemented yet.', "success")
    return redirect(url_for("factory.facility_details", factory_id=factory_id))