"""
routes/factory_routes.py
---------------------------
Routes for the "Add Facility" wizard.

Currently live (4 of the eventual 20 Facility Onboarding Template
sections -- the rest land in later build phases, see
models/wizard_sections.py for the full section registry):

  GET/POST /factory/new                    -> download template, upload filled PDF
  GET/POST /factory/<id>/validate           -> chatbot-style gap-filling Q&A
  GET      /factory/<id>/sensors            -> Section 4: Sensor & Instrumentation (+ API test)
  GET      /factory/<id>/layout             -> portal-only Konva.js canvas editor (not a template section)
  GET/POST /factory/<id>/negligence         -> Section 15: Incident & Negligence History
  GET      /factory/<id>/employees          -> Section 8: Employee Directory
  GET      /factory/<id>/attendance         -> Section 16: Attendance & Access Control (+ finish)

Plus JSON API endpoints for AJAX CRUD and the "Test Connection"
endpoints, all under the same /factory/<id>/... prefix.

NAVIGATION: every section page's Back/Next is computed from
models/wizard_sections.WIZARD_SECTIONS via get_prev_next(), not
hardcoded -- see that module's docstring. Layout is deliberately not
in the registry and so drops out of linear Back/Next; it stays
reachable via the wizard progress bar and the Facility Details page.

NOTE ON NAMING: the product now calls this "Add Facility" in the UI.
The code keeps "factory" throughout (module name, URL prefix, variable
names) -- see models/factory.py docstring for why. Sensor/Employee were
renamed to MonitoredParameter/Person at the model layer (also see
models/factory.py), but URL routes/endpoints deliberately keep their
old names ("sensors", "employees") to minimize blast radius.
"""

import os
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, flash, send_from_directory
from werkzeug.utils import secure_filename

from config import Config
from models.factory import Factory
from models.monitored_parameter import MonitoredParameter, SENSOR_TYPE_CHOICES, RESPONSE_TYPE_CHOICES, API_METHOD_CHOICES
from models.person import Person, DEPARTMENT_CHOICES, BLOOD_GROUP_CHOICES
from models.wizard_sections import get_prev_next, get_first_available_section
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
# Upload + Validate (before Part A begins -- not in the section registry)
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
    """Upload step -- download template + facility name + upload filled PDF."""
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

    # Single AI call extracts everything realistically extractable from a
    # one-time document read -- see services/ai_extraction.py for the
    # full schema and for why this is one call, not several.
    result = extract_from_document(file_path)
    factory.ai_summary = result["process_summary"]
    factory.monitored_parameters = result["monitored_parameters"]
    factory.people = result["people"]
    factory.missing_sections = result["missing_sections"]
    # Seed clarification_qa with each question and a blank answer; the
    # Validate chat UI fills in the answers.
    factory.clarification_qa = [{"question": q, "answer": ""} for q in result["clarifying_questions"]]

    # Part A fields (Sections 1-3) -- facility_overview is a nested dict
    # from the extraction schema; unpack its keys onto the flat Factory
    # fields of the same name. Sections 1-3 don't have dedicated pages
    # yet (later build phases), but the data is captured now rather than
    # discarded, so nothing needs to be re-extracted once those pages land.
    overview = result.get("facility_overview", {}) or {}
    factory.address = overview.get("address", "")
    factory.industry_sector = overview.get("industry_sector", "")
    factory.operating_company = overview.get("operating_company", "")
    factory.commissioning_date = overview.get("commissioning_date", "")
    factory.installed_capacity = overview.get("installed_capacity", "")
    factory.operating_phase = overview.get("operating_phase", "")
    factory.upcoming_milestone_date = overview.get("upcoming_milestone_date", "")
    factory.departments = overview.get("departments", [])
    factory.process_narrative = result.get("process_narrative", "")
    factory.drawing_references = result.get("drawing_references", "")
    factory.scada_systems = result.get("scada_systems", [])
    factory.historian_system = result.get("historian_system", "")
    factory.network_notes = result.get("network_notes", "")

    # Part B/C fields (Sections 6, 9) -- same reasoning as above.
    factory.shift_patterns = result.get("shift_patterns", [])
    factory.shift_handover_notes = result.get("shift_handover_notes", "")
    factory.maintenance_records = result.get("maintenance_records", [])

    storage.save_factory(factory)

    return redirect(url_for("factory.validate_page", factory_id=factory.id))


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

    # Validate isn't in WIZARD_SECTIONS, so its "next" is computed as
    # "whichever registered section comes first" rather than a hardcoded
    # page -- this automatically improves as Part A sections 1-3 land.
    first_section = get_first_available_section(factory_id)
    redirect_url = first_section["url"] if first_section else url_for("main.landing")
    return jsonify({"success": True, "redirect": redirect_url})


# ===========================================================================
# Section 4 -- Sensor & Instrumentation Details (+ API config + test)
# ===========================================================================

@factory_bp.route("/<factory_id>/sensors", methods=["GET"])
def sensors_page(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    prev_nav, next_nav = get_prev_next(
        "factory.sensors_page", factory_id,
        fallback_prev={"url": url_for("factory.validate_page", factory_id=factory_id), "label": "Validate"},
    )

    return render_template(
        "add_facility_step3_sensors.html",
        factory=factory,
        sensor_type_choices=SENSOR_TYPE_CHOICES,
        response_type_choices=RESPONSE_TYPE_CHOICES,
        api_method_choices=API_METHOD_CHOICES,
        prev_nav=prev_nav,
        next_nav=next_nav,
    )


@factory_bp.route("/<factory_id>/sensors/add", methods=["POST"])
def add_sensor(factory_id):
    factory = storage.get_factory(factory_id)
    if not factory:
        return jsonify({"success": False, "error": "Facility not found"}), 404

    data = request.get_json(force=True)
    parameter = MonitoredParameter(
        name=data.get("name", "Unnamed Sensor"),
        parameter_category="Live Sensor Reading",
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
    storage.upsert_monitored_parameter(factory_id, parameter)
    return jsonify({"success": True, "sensor": parameter.to_dict()})


@factory_bp.route("/<factory_id>/sensors/<sensor_id>/edit", methods=["POST"])
def edit_sensor(factory_id, sensor_id):
    factory = storage.get_factory(factory_id)
    if not factory:
        return jsonify({"success": False, "error": "Facility not found"}), 404

    existing = next((p for p in factory.monitored_parameters if p.id == sensor_id), None)
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

    storage.upsert_monitored_parameter(factory_id, existing)
    return jsonify({"success": True, "sensor": existing.to_dict()})


@factory_bp.route("/<factory_id>/sensors/<sensor_id>/delete", methods=["POST"])
def delete_sensor_route(factory_id, sensor_id):
    success = storage.delete_monitored_parameter(factory_id, sensor_id)
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

    parameter = storage.get_monitored_parameter(factory_id, sensor_id)
    if not parameter:
        return jsonify({"success": False, "error": "Sensor not found"}), 404

    result = test_endpoint(parameter.api_url, parameter.api_method, parameter.api_headers)

    parameter.api_status = "Active" if result["success"] else "Inactive"
    parameter.api_last_tested = datetime.utcnow().isoformat()
    storage.upsert_monitored_parameter(factory_id, parameter)

    return jsonify({
        "success": True,  # the test-request itself completed (regardless of connectivity outcome)
        "api_status": parameter.api_status,
        "message": result["message"],
        "status_code": result["status_code"],
    })


# ===========================================================================
# Facility Layout -- portal-only Konva.js canvas editor, NOT a template
# section (see models/wizard_sections.py) -- reachable from the wizard
# progress bar and Facility Details, not from linear Back/Next.
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
# Section 15 -- Incident & Negligence History
# ===========================================================================

@factory_bp.route("/<factory_id>/negligence", methods=["GET", "POST"])
def negligence_page(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    prev_nav, next_nav = get_prev_next("factory.negligence_page", factory_id)

    if request.method == "GET":
        return render_template("add_facility_step5_negligence.html", factory=factory, prev_nav=prev_nav, next_nav=next_nav)

    negligence_text = request.form.get("negligence_history", "").strip()
    storage.update_factory_fields(factory_id, negligence_history=negligence_text)
    redirect_url = next_nav["url"] if next_nav else url_for("factory.facility_details", factory_id=factory_id)
    return redirect(redirect_url)


# ===========================================================================
# Section 8 -- Employee Directory
# ===========================================================================

@factory_bp.route("/<factory_id>/employees", methods=["GET"])
def employees_page(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    # person_lookup resolves a manager_id -> name for display on each
    # card (Jinja side). person_options is the same data reshaped for
    # the JS-side Manager <select> dropdown, since that list needs to be
    # rebuilt client-side every time a person is added/edited/deleted
    # without a full page reload. Only "Employee"-category people are
    # shown/manageable here -- Key Personnel (Section 5) and Contractor
    # Oversight (Section 14) filter the same underlying list differently.
    employees = [p for p in factory.people if p.person_category == "Employee"]
    person_lookup = {p.id: p.name for p in employees}
    person_options = [{"id": p.id, "name": p.name} for p in employees]

    prev_nav, next_nav = get_prev_next("factory.employees_page", factory_id)

    return render_template(
        "add_facility_step6_employees.html",
        factory=factory,
        employees=employees,
        department_choices=DEPARTMENT_CHOICES,
        blood_group_choices=BLOOD_GROUP_CHOICES,
        employee_lookup=person_lookup,
        employee_options=person_options,
        prev_nav=prev_nav,
        next_nav=next_nav,
    )


@factory_bp.route("/<factory_id>/employees/add", methods=["POST"])
def add_employee(factory_id):
    factory = storage.get_factory(factory_id)
    if not factory:
        return jsonify({"success": False, "error": "Facility not found"}), 404

    data = request.get_json(force=True)

    # Defensive: only accept a manager_id that actually belongs to an
    # existing person on this facility -- silently drop anything else
    # (stale/tampered client data) rather than 500 on a low-stakes field.
    valid_person_ids = {p.id for p in factory.people}
    manager_id = data.get("manager_id", "")
    if manager_id and manager_id not in valid_person_ids:
        manager_id = ""

    person = Person(
        name=data.get("name", "Unnamed Employee"),
        person_category="Employee",
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
    storage.upsert_person(factory_id, person)
    return jsonify({"success": True, "employee": person.to_dict()})


@factory_bp.route("/<factory_id>/employees/<employee_id>/edit", methods=["POST"])
def edit_employee(factory_id, employee_id):
    factory = storage.get_factory(factory_id)
    if not factory:
        return jsonify({"success": False, "error": "Facility not found"}), 404

    existing = next((p for p in factory.people if p.id == employee_id), None)
    if not existing:
        return jsonify({"success": False, "error": "Employee not found"}), 404

    data = request.get_json(force=True)

    # A person can't be their own manager.
    new_manager_id = data.get("manager_id", existing.manager_id)
    if new_manager_id == employee_id:
        return jsonify({"success": False, "error": "An employee cannot be their own manager"}), 400
    # Defensive: only accept a manager_id that actually belongs to an
    # existing person on this facility (see add_employee for why).
    valid_person_ids = {p.id for p in factory.people}
    if new_manager_id and new_manager_id not in valid_person_ids:
        new_manager_id = ""

    existing.name = data.get("name", existing.name)
    existing.role = data.get("role", existing.role)
    existing.department = data.get("department", existing.department)
    existing.manager_id = new_manager_id
    existing.email = data.get("email", existing.email)
    existing.phone = data.get("phone", existing.phone)
    existing.blood_group = data.get("blood_group", existing.blood_group)
    existing.working_hours = data.get("working_hours", existing.working_hours)
    existing.working_days = data.get("working_days", existing.working_days)
    existing.emergency_contact_name = data.get("emergency_contact_name", existing.emergency_contact_name)
    existing.emergency_contact_phone = data.get("emergency_contact_phone", existing.emergency_contact_phone)
    existing.emergency_contact_relation = data.get("emergency_contact_relation", existing.emergency_contact_relation)
    existing.notes = data.get("notes", existing.notes)

    storage.upsert_person(factory_id, existing)
    return jsonify({"success": True, "employee": existing.to_dict()})


@factory_bp.route("/<factory_id>/employees/<employee_id>/delete", methods=["POST"])
def delete_employee_route(factory_id, employee_id):
    success = storage.delete_person(factory_id, employee_id)
    if not success:
        return jsonify({"success": False, "error": "Employee or facility not found"}), 404
    return jsonify({"success": True})


# ===========================================================================
# Section 16 -- Attendance & Access Control (+ Finish Setup)
# ===========================================================================

@factory_bp.route("/<factory_id>/attendance", methods=["GET"])
def attendance_page(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))
    prev_nav, next_nav = get_prev_next("factory.attendance_page", factory_id)
    return render_template("add_facility_step7_attendance.html", factory=factory, prev_nav=prev_nav)


@factory_bp.route("/<factory_id>/attendance/test", methods=["POST"])
def test_attendance_connection(factory_id):
    """Tests connectivity using whatever is in the request body (NOT
    necessarily saved yet) -- unlike the sensor test, this step's form
    only has one endpoint to configure, so testing the in-progress form
    values directly is low-risk and saves the user a click."""
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
    """Saves whatever attendance config is currently in the form and
    marks the facility as fully onboarded. Not registry-driven -- this
    is a distinct terminal action ('Finish Setup'), not a generic
    'Next', and stays that way regardless of how many more sections
    Part E eventually grows to."""
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
# Editing any individual section reuses the exact same wizard step
# pages/routes above -- no separate edit-mode logic, just a link into
# the same page.
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
    Details page once every section reports 'done'. What this actually
    does is intentionally undecided for now -- this route just confirms
    the button works end-to-end (visible only when the facility is
    fully configured, clicking it round-trips to the server) without
    committing to a real implementation yet."""
    factory = storage.get_factory(factory_id)
    if not factory:
        flash("Facility not found.", "error")
        return redirect(url_for("factory.list_facilities"))

    flash(f'"{factory.name}" is fully configured. Train & Configure AI is not implemented yet.', "success")
    return redirect(url_for("factory.facility_details", factory_id=factory_id))