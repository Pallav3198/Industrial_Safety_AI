/**
 * asset_registry.js
 * --------------------
 * CRUD for Section 10 (Equipment / Asset Registry). Reuses the
 * generalized MonitoredParameter add/edit/delete routes at
 * /factory/<id>/sensors/... with parameter_category="Compliance
 * Due-Date" -- same backend as Sensors and Staffing Rules, this
 * section's own field set, no API-testing UI (an asset's compliance
 * date isn't a live reading).
 */

document.addEventListener("DOMContentLoaded", () => {
    const factoryId = document.getElementById("app-data").dataset.factoryId;
    const assetGrid = document.getElementById("assetGrid");
    const assetModalEl = document.getElementById("assetModal");
    const assetModal = new bootstrap.Modal(assetModalEl);

    const assetPagination = initPagination({
        gridSelector: "#assetGrid",
        itemSelector: ".asset-col",
        controlsId: "assetPaginationControls",
    });

    function escapeHtml(str) {
        const div = document.createElement("div");
        div.textContent = str ?? "";
        return div.innerHTML;
    }

    document.getElementById("addAssetBtn").addEventListener("click", () => {
        document.getElementById("assetModalTitle").textContent = "Add Asset";
        document.getElementById("assetId").value = "";
        document.getElementById("assetForm").reset();
        assetModal.show();
    });

    assetGrid.addEventListener("click", (e) => {
        const editBtn = e.target.closest(".edit-asset-btn");
        const deleteBtn = e.target.closest(".delete-asset-btn");
        const cardCol = e.target.closest(".asset-col");
        if (!cardCol) return;
        if (editBtn) openEditModal(cardCol);
        else if (deleteBtn) handleDelete(cardCol);
    });

    function openEditModal(cardCol) {
        const card = cardCol.querySelector(".asset-card");
        document.getElementById("assetModalTitle").textContent = "Edit Asset";
        document.getElementById("assetId").value = cardCol.dataset.assetId;
        document.getElementById("assetName").value = card.dataset.name;
        document.getElementById("assetType").value = card.dataset.assetType;
        document.getElementById("assetLocation").value = card.dataset.location;
        document.getElementById("assetLastTestDate").value = card.dataset.lastTestDate;
        document.getElementById("assetNextDueDate").value = card.dataset.nextDueDate;
        document.getElementById("assetNotes").value = card.dataset.notes;
        assetModal.show();
    }

    document.getElementById("saveAssetBtn").addEventListener("click", async () => {
        const form = document.getElementById("assetForm");
        if (!form.reportValidity()) return;

        const assetId = document.getElementById("assetId").value;
        const payload = {
            name: document.getElementById("assetName").value.trim(),
            asset_type: document.getElementById("assetType").value.trim(),
            location: document.getElementById("assetLocation").value.trim(),
            last_test_date: document.getElementById("assetLastTestDate").value.trim(),
            next_due_date: document.getElementById("assetNextDueDate").value.trim(),
            notes: document.getElementById("assetNotes").value.trim(),
            parameter_category: "Compliance Due-Date",
        };

        const url = assetId ? `/factory/${factoryId}/sensors/${assetId}/edit` : `/factory/${factoryId}/sensors/add`;
        try {
            const response = await fetch(url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const result = await response.json();
            if (!result.success) {
                alert("Something went wrong saving this asset: " + (result.error || "unknown error"));
                return;
            }
            if (assetId) updateCardInPlace(assetId, result.sensor);
            else appendNewCard(result.sensor);
            assetPagination.refresh();
            assetModal.hide();
        } catch (err) {
            alert("Network error while saving. Please try again.");
            console.error(err);
        }
    });

    async function handleDelete(cardCol) {
        const assetId = cardCol.dataset.assetId;
        const name = cardCol.querySelector(".card-title").textContent;
        if (!confirm(`Delete "${name}"? This can't be undone.`)) return;
        try {
            const response = await fetch(`/factory/${factoryId}/sensors/${assetId}/delete`, { method: "POST" });
            const result = await response.json();
            if (!result.success) {
                alert("Could not delete: " + (result.error || "unknown error"));
                return;
            }
            cardCol.remove();
            showEmptyStateIfNeeded();
            assetPagination.refresh();
        } catch (err) {
            alert("Network error while deleting. Please try again.");
            console.error(err);
        }
    }

    function appendNewCard(asset) {
        removeEmptyState();
        const wrapper = document.createElement("div");
        wrapper.innerHTML = buildCardHtml(asset);
        assetGrid.appendChild(wrapper.firstElementChild);
    }

    function updateCardInPlace(assetId, asset) {
        const existingCol = assetGrid.querySelector(`.asset-col[data-asset-id="${assetId}"]`);
        if (!existingCol) return;
        const wrapper = document.createElement("div");
        wrapper.innerHTML = buildCardHtml(asset);
        existingCol.replaceWith(wrapper.firstElementChild);
    }

    function removeEmptyState() {
        const emptyState = document.getElementById("emptyState");
        if (emptyState) emptyState.remove();
    }

    function showEmptyStateIfNeeded() {
        if (assetGrid.querySelectorAll(".asset-col").length === 0) {
            const div = document.createElement("div");
            div.className = "col-12";
            div.id = "emptyState";
            div.innerHTML = `<div class="text-center text-muted py-5"><i class="bi bi-clipboard-check display-4"></i><p class="mt-2">No assets registered yet. Add one to get started.</p></div>`;
            assetGrid.appendChild(div);
        }
    }

    function buildCardHtml(asset) {
        const isAi = asset.source === "AI-Extracted";
        return `
        <div class="col-md-6 col-lg-4 asset-col" data-asset-id="${asset.id}">
            <div class="card asset-card h-100"
                 data-name="${escapeHtml(asset.name)}"
                 data-asset-type="${escapeHtml(asset.asset_type)}"
                 data-location="${escapeHtml(asset.location)}"
                 data-last-test-date="${escapeHtml(asset.last_test_date)}"
                 data-next-due-date="${escapeHtml(asset.next_due_date)}"
                 data-notes="${escapeHtml(asset.notes)}">
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-start">
                        <span class="badge ${isAi ? "badge-ai" : "badge-manual"}"><i class="bi ${isAi ? "bi-robot" : "bi-person"}"></i> ${escapeHtml(asset.source)}</span>
                        ${asset.next_due_date ? `<span class="badge text-bg-light border"><i class="bi bi-calendar-event"></i> Due ${escapeHtml(asset.next_due_date)}</span>` : ""}
                    </div>
                    <h5 class="card-title mt-2 mb-1">${escapeHtml(asset.name)}</h5>
                    <p class="text-muted small mb-2">${escapeHtml(asset.asset_type)}${asset.location ? " &middot; " + escapeHtml(asset.location) : ""}</p>
                    <div class="sensor-detail-row"><span class="label">Last Test Date</span><span class="value">${escapeHtml(asset.last_test_date) || "—"}</span></div>
                    <div class="sensor-detail-row"><span class="label">Next Due Date</span><span class="value">${escapeHtml(asset.next_due_date) || "—"}</span></div>
                </div>
                <div class="card-footer bg-transparent d-flex gap-2">
                    <button type="button" class="btn btn-sm btn-outline-primary flex-grow-1 edit-asset-btn"><i class="bi bi-pencil"></i> Edit</button>
                    <button type="button" class="btn btn-sm btn-outline-danger flex-grow-1 delete-asset-btn"><i class="bi bi-trash"></i> Delete</button>
                </div>
            </div>
        </div>`;
    }
});