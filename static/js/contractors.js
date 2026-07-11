/**
 * contractors.js
 * -----------------
 * CRUD for Section 14 (Contractor Oversight Register). Reuses the
 * generalized Person add/edit/delete routes at
 * /factory/<id>/employees/... with person_category="Contractor" -- same
 * backend as Employees and Key Personnel, this section's own
 * contractor-specific field set (scope of work, joint HAZOP, safety
 * induction, supervising employee) rather than the Employee modal's
 * fields, which don't apply here.
 */

document.addEventListener("DOMContentLoaded", () => {
    const factoryId = document.getElementById("app-data").dataset.factoryId;
    const contractorGrid = document.getElementById("contractorGrid");
    const contractorModalEl = document.getElementById("contractorModal");
    const contractorModal = new bootstrap.Modal(contractorModalEl);
    const supervisingSelect = document.getElementById("contractorSupervisingEmployee");

    function populateSupervisingSelect() {
        const options = (window.SUPERVISING_EMPLOYEE_OPTIONS || [])
            .map((p) => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)}</option>`)
            .join("");
        supervisingSelect.innerHTML = `<option value="">— None —</option>${options}`;
    }
    populateSupervisingSelect();

    const contractorPagination = initPagination({
        gridSelector: "#contractorGrid",
        itemSelector: ".contractor-col",
        controlsId: "contractorPaginationControls",
    });

    function escapeHtml(str) {
        const div = document.createElement("div");
        div.textContent = str ?? "";
        return div.innerHTML;
    }

    document.getElementById("addContractorBtn").addEventListener("click", () => {
        document.getElementById("contractorModalTitle").textContent = "Add Contractor";
        document.getElementById("contractorId").value = "";
        document.getElementById("contractorForm").reset();
        contractorModal.show();
    });

    contractorGrid.addEventListener("click", (e) => {
        const editBtn = e.target.closest(".edit-contractor-btn");
        const deleteBtn = e.target.closest(".delete-contractor-btn");
        const cardCol = e.target.closest(".contractor-col");
        if (!cardCol) return;
        if (editBtn) openEditModal(cardCol);
        else if (deleteBtn) handleDelete(cardCol);
    });

    function openEditModal(cardCol) {
        const card = cardCol.querySelector(".contractor-card");
        document.getElementById("contractorModalTitle").textContent = "Edit Contractor";
        document.getElementById("contractorId").value = cardCol.dataset.contractorId;
        document.getElementById("contractorName").value = card.dataset.name;
        document.getElementById("contractorScopeOfWork").value = card.dataset.scopeOfWork;
        document.getElementById("contractorJointHazop").value = card.dataset.jointHazopConducted;
        document.getElementById("contractorLastInspection").value = card.dataset.lastJointInspectionDate;
        document.getElementById("contractorSafetyInduction").value = card.dataset.safetyInductionCompleted;
        document.getElementById("contractorSupervisingEmployee").value = card.dataset.supervisingEmployee;
        document.getElementById("contractorPhone").value = card.dataset.phone;
        document.getElementById("contractorEmail").value = card.dataset.email;
        document.getElementById("contractorNotes").value = card.dataset.notes;
        contractorModal.show();
    }

    document.getElementById("saveContractorBtn").addEventListener("click", async () => {
        const form = document.getElementById("contractorForm");
        if (!form.reportValidity()) return;

        const contractorId = document.getElementById("contractorId").value;
        const payload = {
            name: document.getElementById("contractorName").value.trim(),
            scope_of_work: document.getElementById("contractorScopeOfWork").value.trim(),
            joint_hazop_conducted: document.getElementById("contractorJointHazop").value,
            last_joint_inspection_date: document.getElementById("contractorLastInspection").value.trim(),
            safety_induction_completed: document.getElementById("contractorSafetyInduction").value,
            supervising_employee: document.getElementById("contractorSupervisingEmployee").value,
            phone: document.getElementById("contractorPhone").value.trim(),
            email: document.getElementById("contractorEmail").value.trim(),
            notes: document.getElementById("contractorNotes").value.trim(),
            person_category: "Contractor",
        };

        const url = contractorId ? `/factory/${factoryId}/employees/${contractorId}/edit` : `/factory/${factoryId}/employees/add`;
        try {
            const response = await fetch(url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const result = await response.json();
            if (!result.success) {
                alert("Something went wrong saving this contractor: " + (result.error || "unknown error"));
                return;
            }
            if (contractorId) updateCardInPlace(contractorId, result.employee);
            else appendNewCard(result.employee);
            contractorPagination.refresh();
            contractorModal.hide();
        } catch (err) {
            alert("Network error while saving. Please try again.");
            console.error(err);
        }
    });

    async function handleDelete(cardCol) {
        const contractorId = cardCol.dataset.contractorId;
        const name = cardCol.querySelector(".card-title").textContent;
        if (!confirm(`Delete "${name}"? This can't be undone.`)) return;
        try {
            const response = await fetch(`/factory/${factoryId}/employees/${contractorId}/delete`, { method: "POST" });
            const result = await response.json();
            if (!result.success) {
                alert("Could not delete: " + (result.error || "unknown error"));
                return;
            }
            cardCol.remove();
            showEmptyStateIfNeeded();
            contractorPagination.refresh();
        } catch (err) {
            alert("Network error while deleting. Please try again.");
            console.error(err);
        }
    }

    function appendNewCard(contractor) {
        removeEmptyState();
        const wrapper = document.createElement("div");
        wrapper.innerHTML = buildCardHtml(contractor);
        contractorGrid.appendChild(wrapper.firstElementChild);
    }

    function updateCardInPlace(contractorId, contractor) {
        const existingCol = contractorGrid.querySelector(`.contractor-col[data-contractor-id="${contractorId}"]`);
        if (!existingCol) return;
        const wrapper = document.createElement("div");
        wrapper.innerHTML = buildCardHtml(contractor);
        existingCol.replaceWith(wrapper.firstElementChild);
    }

    function removeEmptyState() {
        const emptyState = document.getElementById("emptyState");
        if (emptyState) emptyState.remove();
    }

    function showEmptyStateIfNeeded() {
        if (contractorGrid.querySelectorAll(".contractor-col").length === 0) {
            const div = document.createElement("div");
            div.className = "col-12";
            div.id = "emptyState";
            div.innerHTML = `<div class="text-center text-muted py-5"><i class="bi bi-person-badge display-4"></i><p class="mt-2">No contractors on record yet. Add one to get started.</p></div>`;
            contractorGrid.appendChild(div);
        }
    }

    function supervisingName(id) {
        const match = (window.SUPERVISING_EMPLOYEE_OPTIONS || []).find((p) => p.id === id);
        return match ? match.name : "";
    }

    function buildCardHtml(contractor) {
        const isAi = contractor.source === "AI-Extracted";
        const supervisorName = supervisingName(contractor.supervising_employee);
        return `
        <div class="col-md-6 col-lg-4 contractor-col" data-contractor-id="${contractor.id}">
            <div class="card contractor-card h-100"
                 data-name="${escapeHtml(contractor.name)}"
                 data-scope-of-work="${escapeHtml(contractor.scope_of_work)}"
                 data-joint-hazop-conducted="${escapeHtml(contractor.joint_hazop_conducted)}"
                 data-last-joint-inspection-date="${escapeHtml(contractor.last_joint_inspection_date)}"
                 data-safety-induction-completed="${escapeHtml(contractor.safety_induction_completed)}"
                 data-supervising-employee="${escapeHtml(contractor.supervising_employee)}"
                 data-phone="${escapeHtml(contractor.phone)}"
                 data-email="${escapeHtml(contractor.email)}"
                 data-notes="${escapeHtml(contractor.notes)}">
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-start">
                        <span class="badge ${isAi ? "badge-ai" : "badge-manual"}"><i class="bi ${isAi ? "bi-robot" : "bi-person"}"></i> ${escapeHtml(contractor.source)}</span>
                        <span class="badge ${contractor.joint_hazop_conducted === "Y" ? "text-bg-success" : "text-bg-warning"}">HAZOP: ${escapeHtml(contractor.joint_hazop_conducted) || "—"}</span>
                    </div>
                    <h5 class="card-title mt-2 mb-1">${escapeHtml(contractor.name)}</h5>
                    <p class="text-muted small mb-2">${escapeHtml(contractor.scope_of_work) || "—"}</p>
                    <div class="sensor-detail-row"><span class="label">Last Joint Inspection</span><span class="value">${escapeHtml(contractor.last_joint_inspection_date) || "—"}</span></div>
                    <div class="sensor-detail-row"><span class="label">Safety Induction</span><span class="value">${escapeHtml(contractor.safety_induction_completed) || "—"}</span></div>
                    <div class="sensor-detail-row"><span class="label">Supervising Employee</span><span class="value">${escapeHtml(supervisorName) || "—"}</span></div>
                </div>
                <div class="card-footer bg-transparent d-flex gap-2">
                    <button type="button" class="btn btn-sm btn-outline-primary flex-grow-1 edit-contractor-btn"><i class="bi bi-pencil"></i> Edit</button>
                    <button type="button" class="btn btn-sm btn-outline-danger flex-grow-1 delete-contractor-btn"><i class="bi bi-trash"></i> Delete</button>
                </div>
            </div>
        </div>`;
    }
});