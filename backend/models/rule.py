"""
models/rule.py
------------------
Rule Engine skeleton. A Rule is a named, severity-classified condition
tree that -- once evaluation logic is built -- will be checked against
live facility data and, if triggered, notify factory.stakeholder_lists
[rule.severity].

THIS REVISION IS SKELETON ONLY: the data model, storage, and management
UI (list/add/edit/enable/disable/delete) are built and functional. What
is explicitly NOT built yet: (1) the evaluator that actually walks a
rule's condition_tree against live/stored data and decides true/false,
and (2) live "current value" fields on MonitoredParameter/shifts/
staffing needed for some condition types to mean anything. Both are
planned follow-up work. See models/rule_catalog.py for the condition
catalog and which condition types are real today vs. pending live data.

Condition tree shape (deliberately plain nested dicts, not nested
dataclasses -- consistent with how Factory already stores other nested
structured data such as escalation_logic/scada_systems as List[Dict],
and it sidesteps needing custom polymorphic (de)serialization for a
tree that can mix Group and Condition nodes at arbitrary depth):

  Group:      {"type": "group", "id": ..., "logic": "ALL" | "ANY", "children": [Group | Condition, ...]}
  Condition:  {"type": "condition", "id": ..., "section": ..., "condition_type": ...,
               "scope": "specific" | "any" | "all", "target_id": ...,
               "operator": ..., "value": ..., "notes": ...}

A bare rule with no conditions added yet defaults to an empty ALL group
(vacuously true -- the builder UI always nudges the user to add at
least one condition before saving, but the data shape stays valid
either way).
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
import uuid

# Shared across the Rule Engine (severity) and Manage Stakeholders
# (mailing lists) -- same 4 levels, single source of truth.
SEVERITY_LEVELS = ["Minor", "Major", "Significant", "Critical"]

RULE_SOURCE_CHOICES = ["Manually Added", "AI-Generated"]

RULE_LOGIC_CHOICES = ["ALL", "ANY"]

REVIEW_STATUS_CHOICES = ["Pending Review", "Approved", "Rejected"]


def _empty_root_group() -> dict:
    return {"type": "group", "id": uuid.uuid4().hex[:8], "logic": "ALL", "children": []}


@dataclass
class Rule:
    name: str
    description: str = ""
    severity: str = "Minor"                # one of SEVERITY_LEVELS

    condition_tree: dict = field(default_factory=_empty_root_group)

    enabled: bool = True                   # toggle a rule on/off without deleting it

    # "Manually Added" (built via the rule builder UI) or "AI-Generated"
    # (created by the future regulatory/standards AI rule generator --
    # see services layer, not built yet). Both show up in the same list.
    source: str = "Manually Added"
    ai_basis: str = ""                     # AI-Generated only: which regulation/standard/notification this rule is based on

    # Human review gate. Manually built rules default to "Approved" --
    # a human already wrote them directly, nothing to review. Any code
    # that creates an AI-Generated rule (the future rule-generation
    # service, Step 9) MUST explicitly pass review_status="Pending
    # Review" when constructing it -- this default alone does not do
    # that inference for you.
    review_status: str = "Approved"        # "Pending Review" | "Approved" | "Rejected"

    # Evaluation is not implemented yet (see module docstring) -- these
    # fields exist now so the UI has somewhere honest to point, and so
    # no schema change is needed once the evaluator lands.
    evaluation_status: str = "Not Evaluated"   # "Not Evaluated" | (future) "Triggered" | "Clear"
    last_evaluated: str = ""                    # ISO timestamp, "" if never evaluated

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def is_active(self) -> bool:
        """Whether this rule can actually fire. A rule must be BOTH
        enabled AND Approved -- this is the single source of truth for
        that check, so 'enabled' alone is never sufficient anywhere
        else in the codebase (evaluator, notification dispatch, etc.)."""
        return self.enabled and self.review_status == "Approved"

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "Rule":
        known_fields = {f: data[f] for f in Rule.__dataclass_fields__ if f in data}
        return Rule(**known_fields)