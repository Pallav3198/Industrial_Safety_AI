"""
routes/monitor_routes.py
---------------------------
Routes for the "Monitor Facility" function.

Flow (scaffold only, for now):
  GET /monitor               -> pick a fully-onboarded facility to monitor
  GET /monitor/<factory_id>  -> that facility's monitoring dashboard --
                                 six cards (Monitor Live Sensor Readings,
                                 Add Rule Engine, Monitor AI Recommendations,
                                 Reconfigure and Fine Tune AI, Manage AI
                                 Recommendations, Manage Stakeholders).
                                 None of the cards are wired up to anything
                                 yet -- each one's behavior lands in a later
                                 change.

Only facilities with setup_complete == True are selectable here -- an
in-progress facility hasn't finished onboarding yet, so there's nothing
meaningful to monitor.
"""

import json
import uuid
from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, flash, request

from services import storage
from models.rule import Rule, SEVERITY_LEVELS
from models.rule_catalog import RULE_CONDITION_CATALOG

monitor_bp = Blueprint("monitor", __name__, url_prefix="/monitor")


@monitor_bp.route("/", methods=["GET"])
def select_facility():
    """Facility picker -- lists only fully onboarded (setup_complete)
    facilities. Monitoring an in-progress facility isn't meaningful yet."""
    factories = [f for f in storage.list_factories() if f.setup_complete]
    return render_template("monitor_facility_list.html", factories=factories)


@monitor_bp.route("/<factory_id>", methods=["GET"])
def dashboard(factory_id):
    """Monitoring dashboard for one facility -- shows the six function
    cards. What each card does is intentionally not implemented yet."""
    factory = storage.get_factory(factory_id)
    if not factory or not factory.setup_complete:
        flash("Facility not found or not fully onboarded yet.", "error")
        return redirect(url_for("monitor.select_facility"))
    return render_template("monitor_dashboard.html", factory=factory)

@monitor_bp.route("/<factory_id>/stakeholders", methods=["GET", "POST"])
def stakeholders(factory_id):
    """Manage Stakeholders: assign people (pulled from the facility's
    onboarded Employee/Personnel records) to one or more severity mailing
    lists (Minor/Major/Significant/Critical). People themselves are not
    editable here -- only list membership -- since `people` is owned by
    the Add Facility wizard (factory_routes.py). A checkbox per person per
    list is submitted together and saved via this one route; removing a
    person from every list is a separate, immediate action below."""
    factory = storage.get_factory(factory_id)
    if not factory or not factory.setup_complete:
        flash("Facility not found or not fully onboarded yet.", "error")
        return redirect(url_for("monitor.select_facility"))

    if request.method == "POST":
        new_lists = {
            level: request.form.getlist(f"list_{level.lower()}")
            for level in SEVERITY_LEVELS
        }
        storage.update_factory_fields(factory_id, stakeholder_lists=new_lists)
        flash("Stakeholder mailing lists updated.", "success")
        return redirect(url_for("monitor.stakeholders", factory_id=factory_id))

    # id -> Person, used to resolve each person's manager_id to a display name
    people_by_id = {p.id: p for p in factory.people}

    return render_template(
        "monitor_stakeholders.html",
        factory=factory,
        severity_levels=SEVERITY_LEVELS,
        people_by_id=people_by_id,
    )

@monitor_bp.route("/<factory_id>/stakeholders/<person_id>/remove", methods=["POST"])
def remove_stakeholder(factory_id, person_id):
    """Removes one person from every severity mailing list in one click.
    Does not delete the person record itself -- that only happens via
    Edit Facility."""
    factory = storage.get_factory(factory_id)
    if not factory:
        flash("Facility not found.", "error")
        return redirect(url_for("monitor.select_facility"))

    updated_lists = {
        level: [pid for pid in ids if pid != person_id]
        for level, ids in factory.stakeholder_lists.items()
    }
    storage.update_factory_fields(factory_id, stakeholder_lists=updated_lists)
    flash("Person removed from all mailing lists.", "success")
    return redirect(url_for("monitor.stakeholders", factory_id=factory_id))

def _parse_condition_tree(raw_json):
    """Parses the hidden condition_tree JSON field posted by the rule
    builder. Falls back to an empty ALL group if parsing fails or the
    field is missing, rather than raising -- a malformed tree shouldn't
    crash the save."""
    try:
        tree = json.loads(raw_json)
        if isinstance(tree, dict) and tree.get("type") == "group":
            return tree
    except (TypeError, ValueError):
        pass
    return {"type": "group", "id": uuid.uuid4().hex[:8], "logic": "ALL", "children": []}


@monitor_bp.route("/<factory_id>/rules", methods=["GET"])
def rule_engine_list(factory_id):
    """Rule Engine: lists every rule for this facility -- manually
    built and (once that system exists) AI-generated -- in one place."""
    factory = storage.get_factory(factory_id)
    if not factory or not factory.setup_complete:
        flash("Facility not found or not fully onboarded yet.", "error")
        return redirect(url_for("monitor.select_facility"))
    return render_template("rule_engine_list.html", factory=factory)


@monitor_bp.route("/<factory_id>/rules/new", methods=["GET", "POST"])
def new_rule(factory_id):
    factory = storage.get_factory(factory_id)
    if not factory or not factory.setup_complete:
        flash("Facility not found or not fully onboarded yet.", "error")
        return redirect(url_for("monitor.select_facility"))

    if request.method == "POST":
        rule = Rule(
            name=request.form.get("name", "").strip(),
            description=request.form.get("description", "").strip(),
            severity=request.form.get("severity", "Minor"),
            enabled=request.form.get("enabled", "1") == "1",
            condition_tree=_parse_condition_tree(request.form.get("condition_tree", "")),
        )
        # A rule can only ever be enabled if it's Approved -- see
        # Rule.is_active(). New rules built through this form are
        # always "Manually Added" and default to review_status
        # "Approved", so this is a no-op today, but it keeps this
        # route safe even if that ever changes.
        if rule.review_status != "Approved":
            rule.enabled = False
        storage.upsert_rule(factory_id, rule)
        flash(f'Rule "{rule.name}" created.', "success")
        return redirect(url_for("monitor.rule_engine_list", factory_id=factory_id))

    return render_template(
        "rule_engine_form.html",
        factory=factory,
        rule=None,
        severity_levels=SEVERITY_LEVELS,
        catalog_json=json.dumps(RULE_CONDITION_CATALOG),
    )

@monitor_bp.route("/<factory_id>/rules/<rule_id>/edit", methods=["GET", "POST"])
def edit_rule(factory_id, rule_id):
    factory = storage.get_factory(factory_id)
    if not factory or not factory.setup_complete:
        flash("Facility not found or not fully onboarded yet.", "error")
        return redirect(url_for("monitor.select_facility"))

    rule = storage.get_rule(factory_id, rule_id)
    if not rule:
        flash("Rule not found.", "error")
        return redirect(url_for("monitor.rule_engine_list", factory_id=factory_id))

    if request.method == "POST":
        rule.name = request.form.get("name", "").strip()
        rule.description = request.form.get("description", "").strip()
        rule.severity = request.form.get("severity", "Minor")
        rule.enabled = request.form.get("enabled", "1") == "1"
        rule.condition_tree = _parse_condition_tree(request.form.get("condition_tree", ""))
        # Same clamp as new_rule() -- this matters here specifically,
        # since edit_rule is the one place an AI-Generated, still-
        # Pending-Review rule could otherwise be flipped live before
        # the real Approve/Reject workflow (Step 10) exists.
        if rule.review_status != "Approved":
            rule.enabled = False
        rule.updated_at = datetime.utcnow().isoformat()
        storage.upsert_rule(factory_id, rule)
        flash(f'Rule "{rule.name}" updated.', "success")
        return redirect(url_for("monitor.rule_engine_list", factory_id=factory_id))

    return render_template(
        "rule_engine_form.html",
        factory=factory,
        rule=rule,
        severity_levels=SEVERITY_LEVELS,
        catalog_json=json.dumps(RULE_CONDITION_CATALOG),
    )

@monitor_bp.route("/<factory_id>/rules/<rule_id>/delete", methods=["POST"])
def delete_rule(factory_id, rule_id):
    storage.delete_rule(factory_id, rule_id)
    flash("Rule deleted.", "success")
    return redirect(url_for("monitor.rule_engine_list", factory_id=factory_id))


@monitor_bp.route("/<factory_id>/rules/<rule_id>/toggle", methods=["POST"])
def toggle_rule(factory_id, rule_id):
    """Immediate enable/disable, no separate save step -- matches the
    pattern used elsewhere in the app for one-click state changes."""
    rule = storage.get_rule(factory_id, rule_id)
    if rule:
        rule.enabled = not rule.enabled
        storage.upsert_rule(factory_id, rule)
    return redirect(url_for("monitor.rule_engine_list", factory_id=factory_id))

@monitor_bp.route("/<factory_id>/rules/<rule_id>/approve", methods=["POST"])
def approve_rule(factory_id, rule_id):
    """Moves a rule from Pending Review to Approved. Does not force
    `enabled` on -- it just makes enabling possible, since Rule.is_active()
    requires both enabled AND Approved. Whatever `enabled` was already
    set to (e.g. by the AI generation service that proposed it) is left
    as-is."""
    rule = storage.get_rule(factory_id, rule_id)
    if rule:
        rule.review_status = "Approved"
        rule.updated_at = datetime.utcnow().isoformat()
        storage.upsert_rule(factory_id, rule)
        flash(f'Rule "{rule.name}" approved.', "success")
    return redirect(url_for("monitor.rule_engine_list", factory_id=factory_id))

@monitor_bp.route("/<factory_id>/rules/<rule_id>/reject", methods=["POST"])
def reject_rule(factory_id, rule_id):
    """Moves a rule to Rejected, permanently (kept as a record, not
    deleted). Also force-disables it -- a rejected rule must never be
    able to fire, regardless of its enabled flag."""
    rule = storage.get_rule(factory_id, rule_id)
    if rule:
        rule.review_status = "Rejected"
        rule.enabled = False
        rule.updated_at = datetime.utcnow().isoformat()
        storage.upsert_rule(factory_id, rule)
        flash(f'Rule "{rule.name}" rejected.', "success")
    return redirect(url_for("monitor.rule_engine_list", factory_id=factory_id))