/**
 * permits.js
 * ------------
 * CRUD for Section 12 (Permit-to-Work Register), backed by
 * models/permit_record.py and its own dedicated routes at
 * /factory/<id>/permits/... (a genuinely distinct model, not a reuse
 * of Sensor/Person like Staffing Rules or Key Personnel -- a permit's
 * time-bounded-authorization shape doesn't fit either).
 */

document.addEventListener("DOMContentLoaded", () => {
    const factoryId = document.getElementById("app-data").dataset.factoryId;
    const permitGrid = document.getElementById("permitGrid");
    const permitModalEl = document.getElementById("permitModal");
    const permitModal = new bootstrap.Modal(permitModalEl);
    const typeSelect = document.getElementById("permitType");
    const statusSelect = document.getElementById("permitStatus");

    function populateSelect(selectEl, choices) {
        selectEl.innerHTML = choices.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("");
    }
    populateSelect(typeSelect, window.PERMIT_TYPE_CHOICES || []);
    populateSelect(statusSelect, window.PERMIT_STATUS_CHOICES || []);

    const permitPagination = initPagination({
        gridSelector: "#permitGrid",
        itemSelector: ".permit-col",
        controlsId: "permitPaginationControls",
    });

    function escapeHtml(str) {
        const div = document.createElement("div");
        div.textContent = str ?? "";
        return div.innerHTML;
    }

    document.getElementById("addPermitBtn").addEventListener("click", () => {
        document.getElementById("permitModalTitle").textContent = "Add Permit";
        document.getElementById("permitId").value = "";
        document.getElementById("permitForm").reset();
        typeSelect.selectedIndex = 0;
        statusSelect.value = "Active";
        permitModal.show();
    });

    permitGrid.addEventListener("click", (e) => {
        const editBtn = e.target.closest(".edit-permit-btn");
        const deleteBtn = e.target.closest(".delete-permit-btn");
        const cardCol = e.target.closest(".permit-col");
        if (!cardCol) return;
        if (editBtn) openEditModal(cardCol);
        else if (deleteBtn) handleDelete(cardCol);
    });

    function openEditModal(cardCol) {
        const card = cardCol.querySelector(".permit-card");
        document.getElementById("permitModalTitle").textContent = "Edit Permit";
        document.getElementById("permitId").value = cardCol.dataset.permitId;
        document.getElementById("permitNumber").value = card.dataset.permitNumber;
        typeSelect.value = card.dataset.permitType;
        statusSelect.value = card.dataset.status;
        document.getElementById("permitLocationEquipment").value = card.dataset.locationEquipment;
        document.getElementById("permitIssuedTo").value = card.dataset.issuedTo;
        document.getElementById("permitIssuedAt").value = card.dataset.issuedAt;
        document.getElementById("permitExpiresAt").value = card.dataset.expiresAt;
        document.getElementById("permitNotes").value = card.dataset.notes;
        permitModal.show();
    }

    document.getElementById("savePermitBtn").addEventListener("click", async () => {
        const form = document.getElementById("permitForm");
        if (!form.reportValidity()) return;

        const permitId = document.getElementById("permitId").value;
        const payload = {
            permit_number: document.getElementById("permitNumber").value.trim(),
            permit_type: typeSelect.value,
            status: statusSelect.value,
            location_equipment: document.getElementById("permitLocationEquipment").value.trim(),
            issued_to: document.getElementById("permitIssuedTo").value.trim(),
            issued_at: document.getElementById("permitIssuedAt").value.trim(),
            expires_at: document.getElementById("permitExpiresAt").value.trim(),
            notes: document.getElementById("permitNotes").value.trim(),
        };

        const url = permitId ? `/factory/${factoryId}/permits/${permitId}/edit` : `/factory/${factoryId}/permits/add`;
        try {
            const response = await fetch(url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const result = await response.json();
            if (!result.success) {
                alert("Something went wrong saving this permit: " + (result.error || "unknown error"));
                return;
            }
            if (permitId) updateCardInPlace(permitId, result.permit);
            else appendNewCard(result.permit);
            permitPagination.refresh();
            permitModal.hide();
        } catch (err) {
            alert("Network error while saving. Please try again.");
            console.error(err);
        }
    });

    async function handleDelete(cardCol) {
        const permitId = cardCol.dataset.permitId;
        const number = cardCol.querySelector(".card-title").textContent;
        if (!confirm(`Delete permit "${number}"? This can't be undone.`)) return;
        try {
            const response = await fetch(`/factory/${factoryId}/permits/${permitId}/delete`, { method: "POST" });
            const result = await response.json();
            if (!result.success) {
                alert("Could not delete: " + (result.error || "unknown error"));
                return;
            }
            cardCol.remove();
            showEmptyStateIfNeeded();
            permitPagination.refresh();
        } catch (err) {
            alert("Network error while deleting. Please try again.");
            console.error(err);
        }
    }

    function appendNewCard(permit) {
        removeEmptyState();
        const wrapper = document.createElement("div");
        wrapper.innerHTML = buildCardHtml(permit);
        permitGrid.appendChild(wrapper.firstElementChild);
    }

    function updateCardInPlace(permitId, permit) {
        const existingCol = permitGrid.querySelector(`.permit-col[data-permit-id="${permitId}"]`);
        if (!existingCol) return;
        const wrapper = document.createElement("div");
        wrapper.innerHTML = buildCardHtml(permit);
        existingCol.replaceWith(wrapper.firstElementChild);
    }

    function removeEmptyState() {
        const emptyState = document.getElementById("emptyState");
        if (emptyState) emptyState.remove();
    }

    function showEmptyStateIfNeeded() {
        if (permitGrid.querySelectorAll(".permit-col").length === 0) {
            const div = document.createElement("div");
            div.className = "col-12";
            div.id = "emptyState";
            div.innerHTML = `<div class="text-center text-muted py-5"><i class="bi bi-file-earmark-lock display-4"></i><p class="mt-2">No permits on record yet. Add one to get started.</p></div>`;
            permitGrid.appendChild(div);
        }
    }

    function buildCardHtml(permit) {
        return `
        <div class="col-md-6 col-lg-4 permit-col" data-permit-id="${permit.id}">
            <div class="card permit-card h-100"
                 data-permit-number="${escapeHtml(permit.permit_number)}"
                 data-permit-type="${escapeHtml(permit.permit_type)}"
                 data-location-equipment="${escapeHtml(permit.location_equipment)}"
                 data-issued-to="${escapeHtml(permit.issued_to)}"
                 data-issued-at="${escapeHtml(permit.issued_at)}"
                 data-expires-at="${escapeHtml(permit.expires_at)}"
                 data-status="${escapeHtml(permit.status)}"
                 data-notes="${escapeHtml(permit.notes)}">
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-start">
                        <span class="badge ${permit.status === "Active" ? "text-bg-success" : "text-bg-secondary"}">${escapeHtml(permit.status)}</span>
                        <span class="badge text-bg-light border">${escapeHtml(permit.permit_type)}</span>
                    </div>
                    <h5 class="card-title tag-id mt-2 mb-1">${escapeHtml(permit.permit_number)}</h5>
                    <p class="text-muted small mb-2">${escapeHtml(permit.location_equipment)}</p>
                    <div class="sensor-detail-row"><span class="label">Issued To</span><span class="value">${escapeHtml(permit.issued_to) || "—"}</span></div>
                    <div class="sensor-detail-row"><span class="label">Issued At</span><span class="value">${escapeHtml(permit.issued_at) || "—"}</span></div>
                    <div class="sensor-detail-row"><span class="label">Expires At</span><span class="value">${escapeHtml(permit.expires_at) || "—"}</span></div>
                </div>
                <div class="card-footer bg-transparent d-flex gap-2">
                    <button type="button" class="btn btn-sm btn-outline-primary flex-grow-1 edit-permit-btn"><i class="bi bi-pencil"></i> Edit</button>
                    <button type="button" class="btn btn-sm btn-outline-danger flex-grow-1 delete-permit-btn"><i class="bi bi-trash"></i> Delete</button>
                </div>
            </div>
        </div>`;
    }
});