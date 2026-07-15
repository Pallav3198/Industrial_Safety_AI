/**
 * key_personnel.js
 * -------------------
 * Manages 3 separate Person grids (Managerial Staff / Maintenance Staff
 * / Safety Officer) on the Key Personnel page, all sharing the ONE
 * #employeeModal from partials/employee_form_modal.html (same modal the
 * Employees page uses). Deliberately a separate file rather than trying
 * to force static/js/employees.js (built around exactly one grid) to
 * handle three -- adapted copy of the same proven pattern, not a fragile
 * generalization of working code.
 *
 * Escalation Logic on this same page is a plain server-rendered form
 * (see dynamic_table.js usage inline in the template) -- no AJAX needed
 * there, it's just a simple table submitted on Next.
 */

document.addEventListener("DOMContentLoaded", () => {
    const factoryId = document.getElementById("app-data").dataset.factoryId;
    const employeeModalEl = document.getElementById("employeeModal");
    const employeeModal = new bootstrap.Modal(employeeModalEl);

    const departmentSelect = document.getElementById("employeeDepartment");
    const bloodGroupSelect = document.getElementById("employeeBloodGroup");
    const managerSelect = document.getElementById("employeeManager");

    function populateSelect(selectEl, choices) {
        selectEl.innerHTML = choices.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("");
    }
    populateSelect(departmentSelect, window.DEPARTMENT_CHOICES || []);
    populateSelect(bloodGroupSelect, window.BLOOD_GROUP_CHOICES || []);

    function populateManagerSelect(excludeId) {
        const options = (window.ALL_EMPLOYEES || [])
            .filter((p) => p.id !== excludeId)
            .map((p) => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)}</option>`)
            .join("");
        managerSelect.innerHTML = `<option value="">— No Manager / Top Level —</option>${options}`;
    }

    function escapeHtml(str) {
        const div = document.createElement("div");
        div.textContent = str ?? "";
        return div.innerHTML;
    }

    function gridForCategory(category) {
        if (category === "Managerial Staff") return document.getElementById("managerialGrid");
        if (category === "Maintenance Staff") return document.getElementById("maintenanceGrid");
        return document.getElementById("safetyGrid");
    }

    // --- Open modal in ADD mode, one handler per category button ------------
    document.querySelectorAll(".add-person-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            const category = btn.dataset.category;
            window.PERSON_CATEGORY_OVERRIDE = category;
            document.getElementById("employeeModalTitle").textContent = `Add ${category}`;
            document.getElementById("employeeId").value = "";
            document.getElementById("employeeForm").reset();
            departmentSelect.selectedIndex = 0;
            bloodGroupSelect.selectedIndex = 0;
            populateManagerSelect(null);
            managerSelect.value = "";
            employeeModal.show();
        });
    });

    // --- Event delegation across all 3 grids ---------------------------------
    document.querySelectorAll(".person-grid").forEach((grid) => {
        grid.addEventListener("click", (e) => {
            const editBtn = e.target.closest(".edit-employee-btn");
            const deleteBtn = e.target.closest(".delete-employee-btn");
            const cardCol = e.target.closest(".employee-col");
            if (!cardCol) return;
            if (editBtn) openEditModal(cardCol, grid.dataset.category);
            else if (deleteBtn) handleDelete(cardCol);
        });
    });

    function openEditModal(cardCol, category) {
        const card = cardCol.querySelector(".employee-card");
        const employeeId = cardCol.dataset.employeeId;
        window.PERSON_CATEGORY_OVERRIDE = category;
        document.getElementById("employeeModalTitle").textContent = `Edit ${category}`;
        document.getElementById("employeeId").value = employeeId;
        document.getElementById("employeeName").value = card.dataset.name;
        document.getElementById("employeeRole").value = card.dataset.role;
        document.getElementById("employeeEmail").value = card.dataset.email;
        document.getElementById("employeePhone").value = card.dataset.phone;
        document.getElementById("employeeWorkingHours").value = card.dataset.workingHours;
        document.getElementById("employeeWorkingDays").value = card.dataset.workingDays;
        document.getElementById("emergencyContactName").value = card.dataset.emergencyContactName;
        document.getElementById("emergencyContactPhone").value = card.dataset.emergencyContactPhone;
        document.getElementById("emergencyContactRelation").value = card.dataset.emergencyContactRelation;
        document.getElementById("employeeNotes").value = card.dataset.notes;
        document.getElementById("employeeCertifications").value = card.dataset.certifications || "";
        departmentSelect.value = card.dataset.department;
        bloodGroupSelect.value = card.dataset.bloodGroup;
        populateManagerSelect(employeeId);
        managerSelect.value = card.dataset.managerId || "";
        employeeModal.show();
    }

    // --- Save (Add or Edit) --------------------------------------------------
    document.getElementById("saveEmployeeBtn").addEventListener("click", async () => {
        const form = document.getElementById("employeeForm");
        if (!form.reportValidity()) return;

        const employeeId = document.getElementById("employeeId").value;
        const payload = {
            name: document.getElementById("employeeName").value.trim(),
            role: document.getElementById("employeeRole").value.trim(),
            department: departmentSelect.value,
            manager_id: managerSelect.value,
            email: document.getElementById("employeeEmail").value.trim(),
            phone: document.getElementById("employeePhone").value.trim(),
            blood_group: bloodGroupSelect.value,
            working_hours: document.getElementById("employeeWorkingHours").value.trim(),
            working_days: document.getElementById("employeeWorkingDays").value.trim(),
            emergency_contact_name: document.getElementById("emergencyContactName").value.trim(),
            emergency_contact_phone: document.getElementById("emergencyContactPhone").value.trim(),
            emergency_contact_relation: document.getElementById("emergencyContactRelation").value.trim(),
            notes: document.getElementById("employeeNotes").value.trim(),
            certifications: document.getElementById("employeeCertifications").value.trim(),
            person_category: window.PERSON_CATEGORY_OVERRIDE || "Managerial Staff",
        };

        const url = employeeId
            ? `/factory/${factoryId}/employees/${employeeId}/edit`
            : `/factory/${factoryId}/employees/add`;

        try {
            const response = await fetch(url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const result = await response.json();
            if (!result.success) {
                alert("Something went wrong saving this person: " + (result.error || "unknown error"));
                return;
            }

            const targetGrid = gridForCategory(payload.person_category);
            if (employeeId) {
                updateCardInPlace(employeeId, result.employee, targetGrid);
                const entry = window.ALL_EMPLOYEES.find((p) => p.id === employeeId);
                if (entry) entry.name = result.employee.name;
            } else {
                appendNewCard(result.employee, targetGrid);
                window.ALL_EMPLOYEES.push({ id: result.employee.id, name: result.employee.name });
            }
            employeeModal.hide();
        } catch (err) {
            alert("Network error while saving. Please try again.");
            console.error(err);
        }
    });

    async function handleDelete(cardCol) {
        const employeeId = cardCol.dataset.employeeId;
        const name = cardCol.querySelector(".card-title").textContent;
        if (!confirm(`Delete "${name}"? This can't be undone.`)) return;
        try {
            const response = await fetch(`/factory/${factoryId}/employees/${employeeId}/delete`, { method: "POST" });
            const result = await response.json();
            if (!result.success) {
                alert("Could not delete: " + (result.error || "unknown error"));
                return;
            }
            cardCol.remove();
            window.ALL_EMPLOYEES = (window.ALL_EMPLOYEES || []).filter((p) => p.id !== employeeId);
        } catch (err) {
            alert("Network error while deleting. Please try again.");
            console.error(err);
        }
    }

    function appendNewCard(employee, targetGrid) {
        const placeholder = targetGrid.querySelector(".text-muted.small");
        if (placeholder) placeholder.remove();
        const wrapper = document.createElement("div");
        wrapper.innerHTML = buildCardHtml(employee);
        targetGrid.appendChild(wrapper.firstElementChild);
    }

    function updateCardInPlace(employeeId, employee, targetGrid) {
        // The person may have been moved to a different category grid --
        // remove from wherever it currently lives, then append fresh into
        // the correct grid for its (possibly new) category.
        const existingCol = document.querySelector(`.employee-col[data-employee-id="${employeeId}"]`);
        if (existingCol) existingCol.remove();
        appendNewCard(employee, targetGrid);
    }

    // Builds the exact same markup as templates/partials/employee_card.html.
    function buildCardHtml(employee) {
        const isAi = employee.source === "AI-Extracted";
        const badgeClass = isAi ? "badge-ai" : "badge-manual";
        const badgeIcon = isAi ? "bi-robot" : "bi-person";

        return `
        <div class="col-md-6 col-lg-4 employee-col" data-employee-id="${employee.id}">
            <div class="card employee-card h-100"
                 data-name="${escapeHtml(employee.name)}"
                 data-role="${escapeHtml(employee.role)}"
                 data-department="${escapeHtml(employee.department)}"
                 data-manager-id="${escapeHtml(employee.manager_id)}"
                 data-email="${escapeHtml(employee.email)}"
                 data-phone="${escapeHtml(employee.phone)}"
                 data-blood-group="${escapeHtml(employee.blood_group)}"
                 data-working-hours="${escapeHtml(employee.working_hours)}"
                 data-working-days="${escapeHtml(employee.working_days)}"
                 data-emergency-contact-name="${escapeHtml(employee.emergency_contact_name)}"
                 data-emergency-contact-phone="${escapeHtml(employee.emergency_contact_phone)}"
                 data-emergency-contact-relation="${escapeHtml(employee.emergency_contact_relation)}"
                 data-notes="${escapeHtml(employee.notes)}"
                 data-certifications="${escapeHtml(employee.certifications)}">
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-start">
                        <span class="badge ${badgeClass}"><i class="bi ${badgeIcon}"></i> ${escapeHtml(employee.source)}</span>
                        ${employee.blood_group ? `<span class="badge text-bg-light border"><i class="bi bi-droplet"></i> ${escapeHtml(employee.blood_group)}</span>` : ""}
                    </div>
                    <h5 class="card-title mt-2 mb-1">${escapeHtml(employee.name)}</h5>
                    <p class="text-muted small mb-2">${escapeHtml(employee.role)}${employee.department ? " &middot; " + escapeHtml(employee.department) : ""}</p>
                    <div class="sensor-detail-row"><span class="label">Manager</span><span class="value">—</span></div>
                    <div class="sensor-detail-row"><span class="label">Email</span><span class="value">${escapeHtml(employee.email) || "—"}</span></div>
                    <div class="sensor-detail-row"><span class="label">Phone</span><span class="value">${escapeHtml(employee.phone) || "—"}</span></div>
                    ${employee.certifications ? `<div class="sensor-detail-row"><span class="label">Certifications</span><span class="value">${escapeHtml(employee.certifications)}</span></div>` : ""}
                </div>
                <div class="card-footer bg-transparent d-flex gap-2">
                    <button type="button" class="btn btn-sm btn-outline-primary flex-grow-1 edit-employee-btn">
                        <i class="bi bi-pencil"></i> Edit
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-danger flex-grow-1 delete-employee-btn">
                        <i class="bi bi-trash"></i> Delete
                    </button>
                </div>
            </div>
        </div>`;
    }
});