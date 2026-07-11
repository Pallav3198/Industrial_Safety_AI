/**
 * staffing_rules.js
 * --------------------
 * CRUD for Section 7 (Minimum Staffing Per Task Rules). Reuses the
 * generalized MonitoredParameter add/edit/delete routes at
 * /factory/<id>/sensors/... (see routes/factory_routes.py) with
 * parameter_category="Staffing Rule" -- same backend, different UI,
 * same pattern as static/js/sensors.js but with this section's own
 * (much shorter) field set and no API-testing UI, since a staffing
 * rule isn't a live reading.
 */

document.addEventListener("DOMContentLoaded", () => {
    const factoryId = document.getElementById("app-data").dataset.factoryId;
    const ruleGrid = document.getElementById("ruleGrid");
    const ruleModalEl = document.getElementById("staffingRuleModal");
    const ruleModal = new bootstrap.Modal(ruleModalEl);

    function escapeHtml(str) {
        const div = document.createElement("div");
        div.textContent = str ?? "";
        return div.innerHTML;
    }

    document.getElementById("addRuleBtn").addEventListener("click", () => {
        document.getElementById("staffingRuleModalTitle").textContent = "Add Staffing Rule";
        document.getElementById("ruleId").value = "";
        document.getElementById("staffingRuleForm").reset();
        ruleModal.show();
    });

    ruleGrid.addEventListener("click", (e) => {
        const editBtn = e.target.closest(".edit-rule-btn");
        const deleteBtn = e.target.closest(".delete-rule-btn");
        const cardCol = e.target.closest(".staffing-rule-col");
        if (!cardCol) return;
        if (editBtn) openEditModal(cardCol);
        else if (deleteBtn) handleDelete(cardCol);
    });

    function openEditModal(cardCol) {
        const card = cardCol.querySelector(".staffing-rule-card");
        document.getElementById("staffingRuleModalTitle").textContent = "Edit Staffing Rule";
        document.getElementById("ruleId").value = cardCol.dataset.ruleId;
        document.getElementById("ruleTaskName").value = card.dataset.taskName;
        document.getElementById("ruleMinimumHeadcount").value = card.dataset.minimumHeadcount;
        document.getElementById("ruleRequiredRoles").value = card.dataset.requiredRoles;
        document.getElementById("ruleNotes").value = card.dataset.notes;
        ruleModal.show();
    }

    document.getElementById("saveRuleBtn").addEventListener("click", async () => {
        const form = document.getElementById("staffingRuleForm");
        if (!form.reportValidity()) return;

        const ruleId = document.getElementById("ruleId").value;
        const taskName = document.getElementById("ruleTaskName").value.trim();
        const payload = {
            name: taskName,
            task_name: taskName,
            minimum_headcount: document.getElementById("ruleMinimumHeadcount").value,
            required_roles: document.getElementById("ruleRequiredRoles").value.trim(),
            notes: document.getElementById("ruleNotes").value.trim(),
            parameter_category: "Staffing Rule",
        };

        const url = ruleId ? `/factory/${factoryId}/sensors/${ruleId}/edit` : `/factory/${factoryId}/sensors/add`;
        try {
            const response = await fetch(url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const result = await response.json();
            if (!result.success) {
                alert("Something went wrong saving this rule: " + (result.error || "unknown error"));
                return;
            }
            if (ruleId) updateCardInPlace(ruleId, result.sensor);
            else appendNewCard(result.sensor);
            ruleModal.hide();
        } catch (err) {
            alert("Network error while saving. Please try again.");
            console.error(err);
        }
    });

    async function handleDelete(cardCol) {
        const ruleId = cardCol.dataset.ruleId;
        const name = cardCol.querySelector(".card-title").textContent;
        if (!confirm(`Delete "${name}"? This can't be undone.`)) return;
        try {
            const response = await fetch(`/factory/${factoryId}/sensors/${ruleId}/delete`, { method: "POST" });
            const result = await response.json();
            if (!result.success) {
                alert("Could not delete: " + (result.error || "unknown error"));
                return;
            }
            cardCol.remove();
            showEmptyStateIfNeeded();
        } catch (err) {
            alert("Network error while deleting. Please try again.");
            console.error(err);
        }
    }

    function appendNewCard(rule) {
        removeEmptyState();
        const wrapper = document.createElement("div");
        wrapper.innerHTML = buildCardHtml(rule);
        ruleGrid.appendChild(wrapper.firstElementChild);
    }

    function updateCardInPlace(ruleId, rule) {
        const existingCol = ruleGrid.querySelector(`.staffing-rule-col[data-rule-id="${ruleId}"]`);
        if (!existingCol) return;
        const wrapper = document.createElement("div");
        wrapper.innerHTML = buildCardHtml(rule);
        existingCol.replaceWith(wrapper.firstElementChild);
    }

    function removeEmptyState() {
        const emptyState = document.getElementById("emptyState");
        if (emptyState) emptyState.remove();
    }

    function showEmptyStateIfNeeded() {
        if (ruleGrid.querySelectorAll(".staffing-rule-col").length === 0) {
            const div = document.createElement("div");
            div.className = "col-12";
            div.id = "emptyState";
            div.innerHTML = `<div class="text-center text-muted py-5"><i class="bi bi-people display-4"></i><p class="mt-2">No staffing rules yet. Add one to get started.</p></div>`;
            ruleGrid.appendChild(div);
        }
    }

    function buildCardHtml(rule) {
        const isAi = rule.source === "AI-Extracted";
        return `
        <div class="col-md-6 col-lg-4 staffing-rule-col" data-rule-id="${rule.id}">
            <div class="card staffing-rule-card h-100"
                 data-name="${escapeHtml(rule.name)}"
                 data-task-name="${escapeHtml(rule.task_name)}"
                 data-minimum-headcount="${escapeHtml(String(rule.minimum_headcount ?? ""))}"
                 data-required-roles="${escapeHtml(rule.required_roles)}"
                 data-notes="${escapeHtml(rule.notes)}">
                <div class="card-body">
                    <span class="badge ${isAi ? "badge-ai" : "badge-manual"}"><i class="bi ${isAi ? "bi-robot" : "bi-person"}"></i> ${escapeHtml(rule.source)}</span>
                    <h5 class="card-title mt-2 mb-1">${escapeHtml(rule.task_name || rule.name)}</h5>
                    <div class="sensor-detail-row"><span class="label">Minimum Personnel</span><span class="value">${rule.minimum_headcount || "—"}</span></div>
                    <div class="sensor-detail-row"><span class="label">Roles Required</span><span class="value">${escapeHtml(rule.required_roles) || "—"}</span></div>
                    ${rule.notes ? `<p class="text-muted small mt-2 mb-0">${escapeHtml(rule.notes)}</p>` : ""}
                </div>
                <div class="card-footer bg-transparent d-flex gap-2">
                    <button type="button" class="btn btn-sm btn-outline-primary flex-grow-1 edit-rule-btn"><i class="bi bi-pencil"></i> Edit</button>
                    <button type="button" class="btn btn-sm btn-outline-danger flex-grow-1 delete-rule-btn"><i class="bi bi-trash"></i> Delete</button>
                </div>
            </div>
        </div>`;
    }
});