/**
 * employees.js
 * -------------
 * Handles all Add / Edit / Delete interactions on the Step 6 (Employee
 * Directory) page via fetch() calls to the JSON API in
 * routes/factory_routes.py. Deliberately mirrors static/js/sensors.js's
 * structure exactly (same event-delegation pattern, same Add/Edit modal
 * reuse, same in-place DOM update approach) since employees and sensors
 * follow the identical CRUD UX pattern.
 *
 * Manager field: window.ALL_EMPLOYEES (set by add_facility_step6_employees.html)
 * is kept in sync client-side as employees are added/edited/deleted, so the
 * Manager dropdown never needs a page reload to reflect the current roster.
 * Known limitation: if you rename an employee who is listed as someone
 * else's manager, that other employee's already-rendered card keeps
 * showing the old name until the page is reloaded -- only the dropdown
 * options and newly opened modals pick up the rename immediately.
 */

document.addEventListener("DOMContentLoaded", () => {
    const factoryId = document.getElementById("app-data").dataset.factoryId;
    const employeeGrid = document.getElementById("employeeGrid");
    const employeePagination = initPagination({
        gridSelector: "#employeeGrid",
        itemSelector: ".employee-col",
        controlsId: "employeePaginationControls",
    });
    const employeeModalEl = document.getElementById("employeeModal");
    const employeeModal = new bootstrap.Modal(employeeModalEl);

    const departmentSelect = document.getElementById("employeeDepartment");
    const bloodGroupSelect = document.getElementById("employeeBloodGroup");
    const managerSelect = document.getElementById("employeeManager");

    populateSelect(departmentSelect, window.DEPARTMENT_CHOICES || []);
    populateSelect(bloodGroupSelect, window.BLOOD_GROUP_CHOICES || []);

    function populateSelect(selectEl, choices) {
        selectEl.innerHTML = choices
            .map((choice) => `<option value="${escapeHtml(choice)}">${escapeHtml(choice)}</option>`)
            .join("");
    }

    // Rebuilds the Manager dropdown from the current window.ALL_EMPLOYEES
    // list. excludeId omits one employee (the one currently being edited,
    // if any) so an employee can never be selected as their own manager.
    function populateManagerSelect(excludeId) {
        const employees = window.ALL_EMPLOYEES || [];
        const options = employees
            .filter((emp) => emp.id !== excludeId)
            .map((emp) => `<option value="${escapeHtml(emp.id)}">${escapeHtml(emp.name)}</option>`)
            .join("");
        managerSelect.innerHTML = `<option value="">— No Manager / Top Level —</option>${options}`;
    }

    function getManagerName(managerId) {
        if (!managerId) return "";
        const match = (window.ALL_EMPLOYEES || []).find((emp) => emp.id === managerId);
        return match ? match.name : "";
    }

    function escapeHtml(str) {
        const div = document.createElement("div");
        div.textContent = str ?? "";
        return div.innerHTML;
    }

    // --- Open modal in ADD mode ------------------------------------------
    document.getElementById("addEmployeeBtn").addEventListener("click", () => {
        document.getElementById("employeeModalTitle").textContent = "Add New Employee";
        document.getElementById("employeeId").value = "";
        document.getElementById("employeeForm").reset();
        departmentSelect.selectedIndex = 0;
        bloodGroupSelect.selectedIndex = 0;
        populateManagerSelect(null);
        managerSelect.value = "";
        employeeModal.show();
    });

    // --- Event delegation ---------------------------------------------------
    employeeGrid.addEventListener("click", (e) => {
        const editBtn = e.target.closest(".edit-employee-btn");
        const deleteBtn = e.target.closest(".delete-employee-btn");
        const cardCol = e.target.closest(".employee-col");
        if (!cardCol) return;

        if (editBtn) openEditModal(cardCol);
        else if (deleteBtn) handleDelete(cardCol);
    });

    function openEditModal(cardCol) {
        const card = cardCol.querySelector(".employee-card");
        const employeeId = cardCol.dataset.employeeId;
        document.getElementById("employeeModalTitle").textContent = "Edit Employee";
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
        // Exclude this employee from their own Manager dropdown, then
        // restore their currently saved manager selection (if any).
        populateManagerSelect(employeeId);
        managerSelect.value = card.dataset.managerId || "";
        employeeModal.show();
    }

    // --- Save (Add or Edit) ------------------------------------------------
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
            // Defaults to "Employee" so this file's existing behavior on
            // the Employees page is unchanged. The Key Personnel page
            // overrides window.PERSON_CATEGORY_OVERRIDE before opening
            // the Add modal, so the same shared modal/JS can create a
            // Managerial Staff / Maintenance Staff / Safety Officer
            // record instead -- see add_facility_key_personnel.html.
            person_category: window.PERSON_CATEGORY_OVERRIDE || "Employee",
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
                alert("Something went wrong saving this employee: " + (result.error || "unknown error"));
                return;
            }

            if (employeeId) {
                updateCardInPlace(employeeId, result.employee);
                const entry = window.ALL_EMPLOYEES.find((emp) => emp.id === employeeId);
                if (entry) entry.name = result.employee.name;
            } else {
                appendNewCard(result.employee);
                window.ALL_EMPLOYEES.push({ id: result.employee.id, name: result.employee.name });
            }

            employeePagination.refresh();

            employeeModal.hide();
        } catch (err) {
            alert("Network error while saving the employee. Please try again.");
            console.error(err);
        }
    });

    // --- Delete -------------------------------------------------------------
    async function handleDelete(cardCol) {
        const employeeId = cardCol.dataset.employeeId;
        const employeeName = cardCol.querySelector(".card-title").textContent;
        if (!confirm(`Delete "${employeeName}"? This can't be undone.`)) return;

        try {
            const response = await fetch(`/factory/${factoryId}/employees/${employeeId}/delete`, { method: "POST" });
            const result = await response.json();
            if (!result.success) {
                alert("Could not delete this employee: " + (result.error || "unknown error"));
                return;
            }
            cardCol.remove();
            showEmptyStateIfNeeded();
            window.ALL_EMPLOYEES = (window.ALL_EMPLOYEES || []).filter((emp) => emp.id !== employeeId);
            employeePagination.refresh();
            
        } catch (err) {
            alert("Network error while deleting the employee. Please try again.");
            console.error(err);
        }
    }

    // --- DOM helpers ------------------------------------------------------

    function appendNewCard(employee) {
        removeEmptyState();
        const wrapper = document.createElement("div");
        wrapper.innerHTML = buildCardHtml(employee);
        employeeGrid.appendChild(wrapper.firstElementChild);
    }

    function updateCardInPlace(employeeId, employee) {
        const existingCol = employeeGrid.querySelector(`.employee-col[data-employee-id="${employeeId}"]`);
        if (!existingCol) return;
        const wrapper = document.createElement("div");
        wrapper.innerHTML = buildCardHtml(employee);
        existingCol.replaceWith(wrapper.firstElementChild);
    }

    function removeEmptyState() {
        const emptyState = document.getElementById("emptyState");
        if (emptyState) emptyState.remove();
    }

    function showEmptyStateIfNeeded() {
        if (employeeGrid.querySelectorAll(".employee-col").length === 0) {
            const div = document.createElement("div");
            div.className = "col-12";
            div.id = "emptyState";
            div.innerHTML = `
                <div class="text-center text-muted py-5">
                    <i class="bi bi-people display-4"></i>
                    <p class="mt-2">No employees yet. Add some manually to get started.</p>
                </div>`;
            employeeGrid.appendChild(div);
        }
    }

    // Builds the exact same markup as templates/partials/employee_card.html --
    // keep both in sync if you change one.
    function buildCardHtml(employee) {
        const isAi = employee.source === "AI-Extracted";
        const badgeClass = isAi ? "badge-ai" : "badge-manual";
        const badgeIcon = isAi ? "bi-robot" : "bi-person";
        const managerName = getManagerName(employee.manager_id);

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
                    <div class="sensor-detail-row"><span class="label">Manager</span><span class="value">${escapeHtml(managerName) || "—"}</span></div>
                    <div class="sensor-detail-row"><span class="label">Email</span><span class="value">${escapeHtml(employee.email) || "—"}</span></div>
                    <div class="sensor-detail-row"><span class="label">Phone</span><span class="value">${escapeHtml(employee.phone) || "—"}</span></div>
                    <div class="sensor-detail-row"><span class="label">Working Hours</span><span class="value">${escapeHtml(employee.working_hours) || "—"}</span></div>
                    <div class="sensor-detail-row"><span class="label">Working Days</span><span class="value">${escapeHtml(employee.working_days) || "—"}</span></div>
                    ${employee.emergency_contact_name ? `
                    <hr class="my-2">
                    <p class="small text-muted mb-0"><i class="bi bi-telephone-plus"></i> Emergency: ${escapeHtml(employee.emergency_contact_name)}
                    (${escapeHtml(employee.emergency_contact_relation) || "—"}) — ${escapeHtml(employee.emergency_contact_phone) || "no phone on file"}</p>` : ""}
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