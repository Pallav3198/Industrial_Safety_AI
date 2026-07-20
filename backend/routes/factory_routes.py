"""
routes/factory_routes.py
---------------------------
Routes for the "Add Facility" wizard.

Currently live (7 of the eventual 20 Facility Onboarding Template
sections -- the rest land in later build phases, see
models/wizard_sections.py for the full section registry):

  GET/POST /factory/new                    -> download template, upload filled PDF
  GET/POST /factory/<id>/validate           -> chatbot-style gap-filling Q&A
  GET/POST /factory/<id>/facility-overview  -> Section 1: Facility Overview
  GET/POST /factory/<id>/process-flow       -> Section 2: Process Flow Description
  GET/POST /factory/<id>/scada-systems      -> Section 3: SCADA / DCS Systems
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
from models.person import Person, PERSON_CATEGORY_CHOICES, DEPARTMENT_CHOICES, BLOOD_GROUP_CHOICES
from models.checklist_record import ChecklistRecord, STANDARD_PSSR_ITEMS
from models.permit_record import PermitRecord, PERMIT_TYPE_CHOICES, PERMIT_STATUS_CHOICES
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


def _zip_form_lists(*lists):
    """Like zip(*lists), but pads any list shorter than the longest one
    with empty strings instead of silently truncating to the shortest.

    Plain zip() breaks silently for the dynamic-row tables (Departments,
    SCADA, Shift Patterns, Maintenance, MOC, PSSR): if any single
    array-named field is missing from the POST body entirely --
    request.form.getlist() then returns [] for just that field -- zip()
    truncates every row to length zero and the whole table is silently
    dropped, even though the other fields have real data. This shouldn't
    happen with the actual dynamic_table.js-rendered rows (every row
    always includes all of its fields), but padding defensively here
    costs nothing and removes an entire class of silent-data-loss bug."""
    max_len = max((len(lst) for lst in lists), default=0)
    padded = [list(lst) + [""] * (max_len - len(lst)) for lst in lists]
    return zip(*padded)


# ===========================================================================
# Upload + Validate (before Part A begins -- not in the section registry)
# ===========================================================================

@factory_bp.route("/template/download")
def download_template():
    """Serves the blank Facility Onboarding Template .docx for the user
    to fill in. The file ships inside static/templates_download/ as part
    of the project -- it is NOT regenerated on the fly."""
    templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "frontend", "static", "templates_download")
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
# Section 1 -- Facility Overview
# ===========================================================================

@factory_bp.route("/<factory_id>/facility-overview", methods=["GET", "POST"])
def facility_overview(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    prev_nav, next_nav = get_prev_next(
        "factory.facility_overview", factory_id,
        fallback_prev={"url": url_for("factory.validate_page", factory_id=factory_id), "label": "Validate"},
    )

    if request.method == "GET":
        return render_template("add_facility_facility_overview.html", factory=factory, prev_nav=prev_nav, next_nav=next_nav)

    # Departments come from the dynamic-row table as parallel arrays
    # (dept_name[], dept_function[], dept_headcount[]) -- zip them back
    # into a list of dicts, skipping any fully-blank row (e.g. an unused
    # extra row the user never filled in, or the always-present starter
    # blank row from dynamic_table.js).
    names = request.form.getlist("dept_name[]")
    functions = request.form.getlist("dept_function[]")
    headcounts = request.form.getlist("dept_headcount[]")
    departments = [
        {"name": n.strip(), "function": f.strip(), "headcount": h.strip()}
        for n, f, h in _zip_form_lists(names, functions, headcounts)
        if n.strip() or f.strip() or h.strip()
    ]

    storage.update_factory_fields(
        factory_id,
        address=request.form.get("address", "").strip(),
        industry_sector=request.form.get("industry_sector", "").strip(),
        operating_company=request.form.get("operating_company", "").strip(),
        commissioning_date=request.form.get("commissioning_date", "").strip(),
        installed_capacity=request.form.get("installed_capacity", "").strip(),
        operating_phase=request.form.get("operating_phase", "").strip(),
        upcoming_milestone_date=request.form.get("upcoming_milestone_date", "").strip(),
        departments=departments,
    )
    redirect_url = next_nav["url"] if next_nav else url_for("factory.facility_details", factory_id=factory_id)
    return redirect(redirect_url)


# ===========================================================================
# Section 2 -- Process Flow Description
# ===========================================================================

@factory_bp.route("/<factory_id>/process-flow", methods=["GET", "POST"])
def process_flow(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    prev_nav, next_nav = get_prev_next("factory.process_flow", factory_id)

    if request.method == "GET":
        return render_template("add_facility_process_flow.html", factory=factory, prev_nav=prev_nav, next_nav=next_nav)

    storage.update_factory_fields(
        factory_id,
        process_narrative=request.form.get("process_narrative", "").strip(),
        drawing_references=request.form.get("drawing_references", "").strip(),
    )
    redirect_url = next_nav["url"] if next_nav else url_for("factory.facility_details", factory_id=factory_id)
    return redirect(redirect_url)


# ===========================================================================
# Section 3 -- SCADA / DCS Systems
# ===========================================================================

@factory_bp.route("/<factory_id>/scada-systems", methods=["GET", "POST"])
def scada_systems(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    prev_nav, next_nav = get_prev_next("factory.scada_systems", factory_id)

    if request.method == "GET":
        return render_template("add_facility_scada_systems.html", factory=factory, prev_nav=prev_nav, next_nav=next_nav)

    names = request.form.getlist("scada_name[]")
    vendors = request.form.getlist("scada_vendor[]")
    versions = request.form.getlist("scada_version[]")
    functions = request.form.getlist("scada_function[]")
    redundants = request.form.getlist("scada_redundant[]")
    scada_list = [
        {"name": n.strip(), "vendor": v.strip(), "version": ver.strip(), "function": f.strip(), "redundant": r.strip()}
        for n, v, ver, f, r in _zip_form_lists(names, vendors, versions, functions, redundants)
        if n.strip() or v.strip() or ver.strip() or f.strip()
    ]

    storage.update_factory_fields(
        factory_id,
        scada_systems=scada_list,
        historian_system=request.form.get("historian_system", "").strip(),
        network_notes=request.form.get("network_notes", "").strip(),
    )
    redirect_url = next_nav["url"] if next_nav else url_for("factory.facility_details", factory_id=factory_id)
    return redirect(redirect_url)


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
    """Shared 'add a MonitoredParameter' endpoint -- reused by three
    different pages (Sensors, Staffing Rules, Asset Registry), each
    sending a different parameter_category. The URL/endpoint name stays
    "sensor" for historical reasons (see models/factory.py docstring on
    the Sensor/MonitoredParameter rename), but this now creates any
    parameter category, not just a live sensor reading."""
    factory = storage.get_factory(factory_id)
    if not factory:
        return jsonify({"success": False, "error": "Facility not found"}), 404

    data = request.get_json(force=True)
    parameter = MonitoredParameter(
        name=data.get("name", "Unnamed Sensor"),
        parameter_category=data.get("parameter_category", "Live Sensor Reading"),
        sensor_type=data.get("sensor_type", "Other"),
        location=data.get("location", ""),
        equipment_tag=data.get("equipment_tag", ""),
        unit=data.get("unit", ""),
        normal_range=data.get("normal_range", ""),
        alarm_threshold=data.get("alarm_threshold", ""),
        response_type=data.get("response_type", "Continuous Analog"),
        asset_type=data.get("asset_type", ""),
        last_test_date=data.get("last_test_date", ""),
        next_due_date=data.get("next_due_date", ""),
        task_name=data.get("task_name", ""),
        minimum_headcount=int(data.get("minimum_headcount") or 0),
        required_roles=data.get("required_roles", ""),
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
    """Shared 'edit a MonitoredParameter' endpoint -- see add_sensor
    above for why this serves three different pages despite the URL
    saying "sensors"."""
    factory = storage.get_factory(factory_id)
    if not factory:
        return jsonify({"success": False, "error": "Facility not found"}), 404

    existing = next((p for p in factory.monitored_parameters if p.id == sensor_id), None)
    if not existing:
        return jsonify({"success": False, "error": "Sensor not found"}), 404

    data = request.get_json(force=True)
    existing.name = data.get("name", existing.name)
    existing.parameter_category = data.get("parameter_category", existing.parameter_category)
    existing.sensor_type = data.get("sensor_type", existing.sensor_type)
    existing.location = data.get("location", existing.location)
    existing.equipment_tag = data.get("equipment_tag", existing.equipment_tag)
    existing.unit = data.get("unit", existing.unit)
    existing.normal_range = data.get("normal_range", existing.normal_range)
    existing.alarm_threshold = data.get("alarm_threshold", existing.alarm_threshold)
    existing.response_type = data.get("response_type", existing.response_type)
    existing.asset_type = data.get("asset_type", existing.asset_type)
    existing.last_test_date = data.get("last_test_date", existing.last_test_date)
    existing.next_due_date = data.get("next_due_date", existing.next_due_date)
    existing.task_name = data.get("task_name", existing.task_name)
    if "minimum_headcount" in data:
        existing.minimum_headcount = int(data.get("minimum_headcount") or 0)
    existing.required_roles = data.get("required_roles", existing.required_roles)
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
# Section 5 -- Key Personnel (Managerial / Maintenance / Safety Officer)
# ===========================================================================

@factory_bp.route("/<factory_id>/key-personnel", methods=["GET"])
def key_personnel(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    key_person_categories = ("Managerial Staff", "Maintenance Staff", "Safety Officer")
    managerial = [p for p in factory.people if p.person_category == "Managerial Staff"]
    maintenance = [p for p in factory.people if p.person_category == "Maintenance Staff"]
    safety = [p for p in factory.people if p.person_category == "Safety Officer"]
    # Used by the Manager dropdown, same pattern as the Employees page --
    # anyone on the facility can be selected as a manager, not just
    # people in these 3 categories.
    person_options = [{"id": p.id, "name": p.name} for p in factory.people]
    # Used by partials/employee_card.html (shared with the Employees
    # page) to resolve a manager_id -> name for display on each card.
    person_lookup = {p.id: p.name for p in factory.people}

    prev_nav, next_nav = get_prev_next("factory.key_personnel", factory_id)

    return render_template(
        "add_facility_key_personnel.html",
        factory=factory,
        managerial=managerial,
        maintenance=maintenance,
        safety=safety,
        person_options=person_options,
        employee_lookup=person_lookup,
        department_choices=DEPARTMENT_CHOICES,
        prev_nav=prev_nav,
        next_nav=next_nav,
    )


@factory_bp.route("/<factory_id>/key-personnel/escalation", methods=["POST"])
def save_escalation_logic(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    levels = request.form.getlist("escalation_level[]")
    triggers = request.form.getlist("escalation_trigger[]")
    contacts = request.form.getlist("escalation_contact[]")
    response_times = request.form.getlist("escalation_response_time[]")
    escalation_logic = [
        {"level": lvl.strip(), "trigger": trg.strip(), "contact_role": c.strip(), "response_time": rt.strip()}
        for lvl, trg, c, rt in _zip_form_lists(levels, triggers, contacts, response_times)
        if lvl.strip() or trg.strip() or c.strip() or rt.strip()
    ]
    storage.update_factory_fields(factory_id, escalation_logic=escalation_logic)

    _, next_nav = get_prev_next("factory.key_personnel", factory_id)
    redirect_url = next_nav["url"] if next_nav else url_for("factory.facility_details", factory_id=factory_id)
    return redirect(redirect_url)


# ===========================================================================
# Section 6 -- Shift & Workforce Patterns
# ===========================================================================

@factory_bp.route("/<factory_id>/shift-patterns", methods=["GET", "POST"])
def shift_patterns(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    prev_nav, next_nav = get_prev_next("factory.shift_patterns", factory_id)

    if request.method == "GET":
        return render_template("add_facility_shift_patterns.html", factory=factory, prev_nav=prev_nav, next_nav=next_nav)

    names = request.form.getlist("shift_name[]")
    starts = request.form.getlist("shift_start[]")
    ends = request.form.getlist("shift_end[]")
    headcounts = request.form.getlist("shift_headcount[]")
    shifts = [
        {"shift_name": n.strip(), "start_time": s.strip(), "end_time": e.strip(), "headcount": h.strip()}
        for n, s, e, h in _zip_form_lists(names, starts, ends, headcounts)
        if n.strip() or s.strip() or e.strip() or h.strip()
    ]

    storage.update_factory_fields(
        factory_id,
        shift_patterns=shifts,
        shift_handover_notes=request.form.get("shift_handover_notes", "").strip(),
    )
    redirect_url = next_nav["url"] if next_nav else url_for("factory.facility_details", factory_id=factory_id)
    return redirect(redirect_url)


# ===========================================================================
# Section 7 -- Minimum Staffing Per Task Rules
# ===========================================================================

@factory_bp.route("/<factory_id>/staffing-rules", methods=["GET"])
def staffing_rules(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    rules = [p for p in factory.monitored_parameters if p.parameter_category == "Staffing Rule"]
    prev_nav, next_nav = get_prev_next("factory.staffing_rules", factory_id)

    return render_template(
        "add_facility_staffing_rules.html",
        factory=factory,
        rules=rules,
        prev_nav=prev_nav,
        next_nav=next_nav,
    )


# ===========================================================================
# Facility Layout -- portal-only Konva.js canvas editor. Sits between
# Sensors and Key Personnel in models/wizard_sections.WIZARD_SECTIONS,
# so it's reachable via linear Back/Next like any other section, as
# well as from the wizard progress bar and Facility Details.
# ===========================================================================

@factory_bp.route("/<factory_id>/layout", methods=["GET"])
def layout_page(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    prev_nav, next_nav = get_prev_next("factory.layout_page", factory_id)

    return render_template(
        "add_facility_step4_layout.html",
        factory=factory,
        prev_nav=prev_nav,
        next_nav=next_nav,
    )


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
    """Shared 'add a Person' endpoint -- reused by three different pages
    (Employee Directory, Key Personnel, Contractor Oversight), each
    sending a different person_category. The URL/endpoint name stays
    "employee" for historical reasons (see models/factory.py docstring
    on the Sensor/Employee rename), but this now creates any Person
    category, not just "Employee"."""
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
        name=data.get("name", "Unnamed Person"),
        person_category=data.get("person_category", "Employee"),
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
        certifications=data.get("certifications", ""),
        scope_of_work=data.get("scope_of_work", ""),
        joint_hazop_conducted=data.get("joint_hazop_conducted", ""),
        last_joint_inspection_date=data.get("last_joint_inspection_date", ""),
        safety_induction_completed=data.get("safety_induction_completed", ""),
        supervising_employee=data.get("supervising_employee", ""),
        notes=data.get("notes", ""),
        source="Manually Added",
    )
    storage.upsert_person(factory_id, person)
    return jsonify({"success": True, "employee": person.to_dict()})


@factory_bp.route("/<factory_id>/employees/<employee_id>/edit", methods=["POST"])
def edit_employee(factory_id, employee_id):
    """Shared 'edit a Person' endpoint -- see add_employee above for why
    this serves three different pages despite the URL saying
    "employees"."""
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
    existing.person_category = data.get("person_category", existing.person_category)
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
    existing.certifications = data.get("certifications", existing.certifications)
    existing.scope_of_work = data.get("scope_of_work", existing.scope_of_work)
    existing.joint_hazop_conducted = data.get("joint_hazop_conducted", existing.joint_hazop_conducted)
    existing.last_joint_inspection_date = data.get("last_joint_inspection_date", existing.last_joint_inspection_date)
    existing.safety_induction_completed = data.get("safety_induction_completed", existing.safety_induction_completed)
    existing.supervising_employee = data.get("supervising_employee", existing.supervising_employee)
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
# Section 9 -- Maintenance Records & Timelines
# ===========================================================================

@factory_bp.route("/<factory_id>/maintenance", methods=["GET", "POST"])
def maintenance_records(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    prev_nav, next_nav = get_prev_next("factory.maintenance_records", factory_id)

    if request.method == "GET":
        return render_template("add_facility_maintenance_records.html", factory=factory, prev_nav=prev_nav, next_nav=next_nav)

    equipment = request.form.getlist("maint_equipment[]")
    last_dates = request.form.getlist("maint_last_date[]")
    types = request.form.getlist("maint_type[]")
    next_dues = request.form.getlist("maint_next_due[]")
    performed_bys = request.form.getlist("maint_performed_by[]")
    deferred_notes = request.form.getlist("maint_deferred_notes[]")
    records = [
        {"equipment": eq.strip(), "last_date": ld.strip(), "type": t.strip(),
         "next_due": nd.strip(), "performed_by": pb.strip(), "deferred_notes": dn.strip()}
        for eq, ld, t, nd, pb, dn in _zip_form_lists(equipment, last_dates, types, next_dues, performed_bys, deferred_notes)
        if eq.strip() or ld.strip() or t.strip() or nd.strip() or pb.strip() or dn.strip()
    ]
    storage.update_factory_fields(factory_id, maintenance_records=records)
    redirect_url = next_nav["url"] if next_nav else url_for("factory.facility_details", factory_id=factory_id)
    return redirect(redirect_url)


# ===========================================================================
# Section 10 -- Equipment / Asset Registry
# ===========================================================================

@factory_bp.route("/<factory_id>/asset-registry", methods=["GET"])
def asset_registry(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    assets = [p for p in factory.monitored_parameters if p.parameter_category == "Compliance Due-Date"]
    prev_nav, next_nav = get_prev_next("factory.asset_registry", factory_id)

    return render_template(
        "add_facility_asset_registry.html",
        factory=factory,
        assets=assets,
        prev_nav=prev_nav,
        next_nav=next_nav,
    )


# ===========================================================================
# Section 11 -- Management of Change (MOC) Log
# ===========================================================================

def _get_or_create_checklist(factory, checklist_type, default_title, default_items=None):
    """Shared helper for MOC (Section 11) and PSSR (Section 13) -- both
    are represented as exactly ONE ChecklistRecord per facility per type
    (the template shows each as a single flat table/checklist, not
    multiple named records), created lazily on first visit."""
    existing = next((c for c in factory.checklist_records if c.checklist_type == checklist_type), None)
    if existing:
        return existing
    record = ChecklistRecord(
        checklist_type=checklist_type,
        title=default_title,
        items=default_items or [],
        source="Manually Added",
    )
    storage.upsert_checklist_record(factory.id, record)
    return record


@factory_bp.route("/<factory_id>/moc-log", methods=["GET", "POST"])
def moc_log(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    record = _get_or_create_checklist(factory, "MOC", "Management of Change Log")
    prev_nav, next_nav = get_prev_next("factory.moc_log", factory_id)

    if request.method == "GET":
        return render_template("add_facility_moc_log.html", factory=factory, record=record, prev_nav=prev_nav, next_nav=next_nav)

    change_ids = request.form.getlist("moc_change_id[]")
    equipment = request.form.getlist("moc_equipment[]")
    descriptions = request.form.getlist("moc_description[]")
    dates = request.form.getlist("moc_date[]")
    completed = request.form.getlist("moc_completed[]")
    reviewed_bys = request.form.getlist("moc_reviewed_by[]")
    actions = request.form.getlist("moc_action[]")
    items = [
        {"change_id": cid.strip(), "equipment_process": eq.strip(), "description": desc.strip(),
         "date_identified": d.strip(), "moc_completed": comp.strip(), "reviewed_by": rb.strip(), "corrective_action": a.strip()}
        for cid, eq, desc, d, comp, rb, a in _zip_form_lists(change_ids, equipment, descriptions, dates, completed, reviewed_bys, actions)
        if cid.strip() or eq.strip() or desc.strip()
    ]
    record.items = items
    record.status = "Complete" if items and all(i.get("moc_completed") in ("Y", "Yes") for i in items) else "Open"
    storage.upsert_checklist_record(factory_id, record)

    redirect_url = next_nav["url"] if next_nav else url_for("factory.facility_details", factory_id=factory_id)
    return redirect(redirect_url)


# ===========================================================================
# Section 12 -- Permit-to-Work Register
# ===========================================================================

@factory_bp.route("/<factory_id>/permits", methods=["GET"])
def permits(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    prev_nav, next_nav = get_prev_next("factory.permits", factory_id)

    contractor_choices = [
        {"id": p.id, "name": p.name}
        for p in factory.people
        if p.person_category == "Contractor"
    ]

    return render_template(
        "add_facility_permits.html",
        factory=factory,
        permit_type_choices=PERMIT_TYPE_CHOICES,
        permit_status_choices=PERMIT_STATUS_CHOICES,
        contractor_choices=contractor_choices,
        prev_nav=prev_nav,
        next_nav=next_nav,
    )


@factory_bp.route("/<factory_id>/permits/add", methods=["POST"])
def add_permit(factory_id):
    factory = storage.get_factory(factory_id)
    if not factory:
        return jsonify({"success": False, "error": "Facility not found"}), 404

    data = request.get_json(force=True)
    permit = PermitRecord(
        permit_number=data.get("permit_number", "Unnumbered Permit"),
        permit_type=data.get("permit_type", ""),
        location_equipment=data.get("location_equipment", ""),
        equipment_tag=data.get("equipment_tag", ""),
        issued_to=data.get("issued_to", ""),
        contractor_id=data.get("contractor_id", ""),
        issued_at=data.get("issued_at", ""),
        expires_at=data.get("expires_at", ""),
        status=data.get("status", "Active"),
        notes=data.get("notes", ""),
        source="Manually Added",
    )
    storage.upsert_permit_record(factory_id, permit)
    return jsonify({"success": True, "permit": permit.to_dict()})


@factory_bp.route("/<factory_id>/permits/<permit_id>/edit", methods=["POST"])
def edit_permit(factory_id, permit_id):
    factory = storage.get_factory(factory_id)
    if not factory:
        return jsonify({"success": False, "error": "Facility not found"}), 404

    existing = next((p for p in factory.permit_records if p.id == permit_id), None)
    if not existing:
        return jsonify({"success": False, "error": "Permit not found"}), 404

    data = request.get_json(force=True)
    existing.permit_number = data.get("permit_number", existing.permit_number)
    existing.permit_type = data.get("permit_type", existing.permit_type)
    existing.location_equipment = data.get("location_equipment", existing.location_equipment)
    existing.equipment_tag = data.get("equipment_tag", existing.equipment_tag)
    existing.issued_to = data.get("issued_to", existing.issued_to)
    existing.contractor_id = data.get("contractor_id", existing.contractor_id)
    existing.issued_at = data.get("issued_at", existing.issued_at)
    existing.expires_at = data.get("expires_at", existing.expires_at)
    existing.status = data.get("status", existing.status)
    existing.notes = data.get("notes", existing.notes)

    storage.upsert_permit_record(factory_id, existing)
    return jsonify({"success": True, "permit": existing.to_dict()})


@factory_bp.route("/<factory_id>/permits/<permit_id>/delete", methods=["POST"])
def delete_permit(factory_id, permit_id):
    success = storage.delete_permit_record(factory_id, permit_id)
    if not success:
        return jsonify({"success": False, "error": "Permit or facility not found"}), 404
    return jsonify({"success": True})


# ===========================================================================
# Section 13 -- Pre-Startup Safety Review (PSSR) Checklist
# ===========================================================================

@factory_bp.route("/<factory_id>/pssr", methods=["GET", "POST"])
def pssr_checklist(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    # Pre-populated with the 8 standard items from the template on first
    # visit, per the build spec -- not an open-ended add-a-row table.
    default_items = [{"item": item, "completed": "", "verified_by": "", "date": ""} for item in STANDARD_PSSR_ITEMS]
    record = _get_or_create_checklist(factory, "PSSR", "Pre-Startup Safety Review", default_items)
    prev_nav, next_nav = get_prev_next("factory.pssr_checklist", factory_id)

    if request.method == "GET":
        return render_template("add_facility_pssr.html", factory=factory, record=record, prev_nav=prev_nav, next_nav=next_nav)

    items_text = request.form.getlist("pssr_item[]")
    completed = request.form.getlist("pssr_completed[]")
    verified_bys = request.form.getlist("pssr_verified_by[]")
    dates = request.form.getlist("pssr_date[]")
    items = [
        {"item": it.strip(), "completed": comp.strip(), "verified_by": vb.strip(), "date": d.strip()}
        for it, comp, vb, d in _zip_form_lists(items_text, completed, verified_bys, dates)
        if it.strip()
    ]
    record.items = items
    record.status = "Complete" if items and all(i.get("completed") in ("Y", "Yes") for i in items) else "Open"
    storage.upsert_checklist_record(factory_id, record)

    redirect_url = next_nav["url"] if next_nav else url_for("factory.facility_details", factory_id=factory_id)
    return redirect(redirect_url)


# ===========================================================================
# Section 14 -- Contractor Oversight Register
# ===========================================================================

@factory_bp.route("/<factory_id>/contractors", methods=["GET"])
def contractor_oversight(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    contractors = [p for p in factory.people if p.person_category == "Contractor"]
    # Used by the "Supervising Employee" dropdown.
    person_options = [{"id": p.id, "name": p.name} for p in factory.people if p.person_category != "Contractor"]
    prev_nav, next_nav = get_prev_next("factory.contractor_oversight", factory_id)

    return render_template(
        "add_facility_contractors.html",
        factory=factory,
        contractors=contractors,
        person_options=person_options,
        prev_nav=prev_nav,
        next_nav=next_nav,
    )


# ===========================================================================
# Section 16 -- Attendance & Access Control
# ===========================================================================

@factory_bp.route("/<factory_id>/attendance", methods=["GET"])
def attendance_page(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))
    prev_nav, next_nav = get_prev_next("factory.attendance_page", factory_id)
    return render_template("add_facility_step7_attendance.html", factory=factory, prev_nav=prev_nav, next_nav=next_nav)


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
    """Saves attendance config and continues to the next section. As of
    Step 7 (Part E), this is a normal 'save and go to next' action, NOT
    a completion action anymore -- Attendance was the last built section
    for a while, so this endpoint grew up doing double duty. Now that
    Sections 17-20 exist, setup completion has moved to Emergency
    Response (Section 20), the genuine last section of the template.
    Endpoint name and URL kept as "finish_setup" / "/attendance/finish"
    to avoid unnecessary churn, even though the name is now a bit of a
    misnomer -- it no longer finishes anything."""
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    storage.update_factory_fields(
        factory_id,
        attendance_api_url=request.form.get("api_url", "").strip(),
        attendance_api_method=request.form.get("api_method", "GET"),
        attendance_api_headers=request.form.get("api_headers", "").strip(),
    )
    _, next_nav = get_prev_next("factory.attendance_page", factory_id)
    redirect_url = next_nav["url"] if next_nav else url_for("factory.facility_details", factory_id=factory_id)
    return redirect(redirect_url)


# ===========================================================================
# Section 17 -- Utility & Support Systems
# ===========================================================================

STANDARD_UTILITY_SYSTEMS = [
    "Emergency Power Backup (DG Set / UPS)",
    "Compressed Air System",
    "Water Treatment / Cooling Water",
    "Fire Water System",
    "HVAC (Control Room / Critical Areas)",
]


@factory_bp.route("/<factory_id>/utilities", methods=["GET", "POST"])
def utility_systems(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    # Pre-populate with the 5 standard utility categories from the
    # template on first visit, persisted immediately -- same lazy-
    # default-on-first-view pattern as PSSR's standard checklist items
    # (see _get_or_create_checklist above).
    if not factory.utility_systems:
        defaults = [{"system": s, "type_vendor": "", "redundancy": "", "last_tested": ""} for s in STANDARD_UTILITY_SYSTEMS]
        storage.update_factory_fields(factory_id, utility_systems=defaults)
        factory.utility_systems = defaults

    prev_nav, next_nav = get_prev_next("factory.utility_systems", factory_id)

    if request.method == "GET":
        return render_template("add_facility_utility_systems.html", factory=factory, prev_nav=prev_nav, next_nav=next_nav)

    systems = request.form.getlist("utility_system[]")
    type_vendors = request.form.getlist("utility_type_vendor[]")
    redundancies = request.form.getlist("utility_redundancy[]")
    last_testeds = request.form.getlist("utility_last_tested[]")
    utility_list = [
        {"system": s.strip(), "type_vendor": tv.strip(), "redundancy": r.strip(), "last_tested": lt.strip()}
        for s, tv, r, lt in _zip_form_lists(systems, type_vendors, redundancies, last_testeds)
        if s.strip() or tv.strip() or r.strip() or lt.strip()
    ]
    storage.update_factory_fields(factory_id, utility_systems=utility_list)
    redirect_url = next_nav["url"] if next_nav else url_for("factory.facility_details", factory_id=factory_id)
    return redirect(redirect_url)


# ===========================================================================
# Section 18 -- Training & Certification Records
# ===========================================================================

@factory_bp.route("/<factory_id>/training", methods=["GET", "POST"])
def training_records(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    prev_nav, next_nav = get_prev_next("factory.training_records", factory_id)

    if request.method == "GET":
        return render_template("add_facility_training_records.html", factory=factory, prev_nav=prev_nav, next_nav=next_nav)

    names = request.form.getlist("training_name[]")
    types = request.form.getlist("training_type[]")
    frequencies = request.form.getlist("training_frequency[]")
    last_conducteds = request.form.getlist("training_last_conducted[]")
    notes = request.form.getlist("training_notes[]")
    records = [
        {"name": n.strip(), "type": t.strip(), "frequency": f.strip(), "last_conducted": lc.strip(), "notes": nt.strip()}
        for n, t, f, lc, nt in _zip_form_lists(names, types, frequencies, last_conducteds, notes)
        if n.strip() or t.strip() or f.strip() or lc.strip() or nt.strip()
    ]
    storage.update_factory_fields(factory_id, training_records=records)
    redirect_url = next_nav["url"] if next_nav else url_for("factory.facility_details", factory_id=factory_id)
    return redirect(redirect_url)


# ===========================================================================
# Section 19 -- Environmental & Quality Compliance
# ===========================================================================

@factory_bp.route("/<factory_id>/environmental", methods=["GET", "POST"])
def environmental_compliance(factory_id):
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    prev_nav, next_nav = get_prev_next("factory.environmental_compliance", factory_id)

    if request.method == "GET":
        return render_template("add_facility_environmental_compliance.html", factory=factory, prev_nav=prev_nav, next_nav=next_nav)

    types = request.form.getlist("env_type[]")
    references = request.form.getlist("env_reference[]")
    authorities = request.form.getlist("env_authority[]")
    valid_untils = request.form.getlist("env_valid_until[]")
    records = [
        {"type": t.strip(), "reference": r.strip(), "issuing_authority": a.strip(), "valid_until": v.strip()}
        for t, r, a, v in _zip_form_lists(types, references, authorities, valid_untils)
        if t.strip() or r.strip() or a.strip() or v.strip()
    ]
    storage.update_factory_fields(factory_id, environmental_records=records)
    redirect_url = next_nav["url"] if next_nav else url_for("factory.facility_details", factory_id=factory_id)
    return redirect(redirect_url)


# ===========================================================================
# Section 20 -- Emergency Response & Compliance (+ Finish Setup)
# ===========================================================================

@factory_bp.route("/<factory_id>/emergency-response", methods=["GET", "POST"])
def emergency_response(factory_id):
    """The genuine last section of the 20-section template -- this is
    where 'Finish Setup' / setup_complete now lives (moved from
    Attendance in Step 7, see finish_setup's docstring above)."""
    factory = _get_factory_or_404(factory_id)
    if not factory:
        return redirect(url_for("main.landing"))

    prev_nav, _ = get_prev_next("factory.emergency_response", factory_id)

    if request.method == "GET":
        return render_template("add_facility_emergency_response.html", factory=factory, prev_nav=prev_nav)

    storage.update_factory_fields(
        factory_id,
        regulatory_standards=request.form.get("regulatory_standards", "").strip(),
        fire_safety_systems=request.form.get("fire_safety_systems", "").strip(),
        last_safety_audit_date=request.form.get("last_safety_audit_date", "").strip(),
        last_safety_audit_findings=request.form.get("last_safety_audit_findings", "").strip(),
        setup_complete=True,
    )
    flash(f'"{factory.name}" onboarding complete.', "success")
    # The page submits this via fetch() so it can enable the "Configure AI"
    # button in place instead of navigating away immediately -- see
    # static/js/emergency_response.js.
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True})
    return redirect(url_for("main.landing"))

# ===========================================================================
# # VIEW / EDIT FACILITY -- lists all onboarded facilities, shows a full
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

@factory_bp.route("/<factory_id>/delete", methods=["POST"])
def delete_facility_route(factory_id):
    """Permanently deletes a facility. Triggered from the Facility
    Details page, gated by a confirm() dialog client-side (see
    static/js/facility_details.js) since this is irreversible."""
    factory = storage.get_factory(factory_id)
    if not factory:
        flash("Facility not found.", "error")
        return redirect(url_for("factory.list_facilities"))

    storage.delete_factory(factory_id)
    flash(f'"{factory.name}" was deleted.', "success")
    return redirect(url_for("factory.list_facilities"))

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
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": "Facility not found"}), 404
        flash("Facility not found.", "error")
        return redirect(url_for("factory.list_facilities"))

    flash(f'"{factory.name}" is fully configured. Train & Configure AI is not implemented yet.', "success")
    redirect_url = url_for("factory.facility_details", factory_id=factory_id)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "redirect": redirect_url})
    return redirect(redirect_url)