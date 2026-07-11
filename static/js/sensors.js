/**
 * sensors.js
 * -----------
 * Handles all Add / Edit / Delete / Test-Connection interactions on the
 * Step 3 (Sensors & Systems) page via fetch() calls to the JSON API in
 * routes/factory_routes.py -- the page never fully reloads after the
 * initial load.
 *
 * One Bootstrap modal (#sensorModal) is reused for both "Add" and "Edit":
 *   - Add mode:  #sensorId is empty  -> POST /factory/<id>/sensors/add
 *   - Edit mode: #sensorId is filled -> POST /factory/<id>/sensors/<sensor_id>/edit
 *
 * "Test Connection" tests the sensor's SAVED API config server-side (see
 * services/api_tester.py) and updates the green/red status badge in place.
 */

document.addEventListener("DOMContentLoaded", () => {
    const factoryId = document.getElementById("app-data").dataset.factoryId;
    const sensorGrid = document.getElementById("sensorGrid");
    const sensorModalEl = document.getElementById("sensorModal");
    const sensorModal = new bootstrap.Modal(sensorModalEl);

    const sensorTypeSelect = document.getElementById("sensorType");
    const responseTypeSelect = document.getElementById("responseType");
    const apiMethodSelect = document.getElementById("apiMethod");

    populateSelect(sensorTypeSelect, window.SENSOR_TYPE_CHOICES || []);
    populateSelect(responseTypeSelect, window.RESPONSE_TYPE_CHOICES || []);
    populateSelect(apiMethodSelect, window.API_METHOD_CHOICES || ["GET", "POST"]);

    function populateSelect(selectEl, choices) {
        selectEl.innerHTML = choices
            .map((choice) => `<option value="${escapeHtml(choice)}">${escapeHtml(choice)}</option>`)
            .join("");
    }

    function escapeHtml(str) {
        const div = document.createElement("div");
        div.textContent = str ?? "";
        return div.innerHTML;
    }

    // --- Open modal in ADD mode ------------------------------------------
    document.getElementById("addSensorBtn").addEventListener("click", () => {
        document.getElementById("sensorModalTitle").textContent = "Add New Sensor/System";
        document.getElementById("sensorId").value = "";
        document.getElementById("sensorForm").reset();
        sensorTypeSelect.selectedIndex = 0;
        responseTypeSelect.selectedIndex = 0;
        apiMethodSelect.selectedIndex = 0;
        sensorModal.show();
    });

    // --- Event delegation: works for cards added after initial load too --
    sensorGrid.addEventListener("click", (e) => {
        const editBtn = e.target.closest(".edit-sensor-btn");
        const deleteBtn = e.target.closest(".delete-sensor-btn");
        const testBtn = e.target.closest(".test-sensor-btn");
        const cardCol = e.target.closest(".sensor-col");
        if (!cardCol) return;

        if (editBtn) openEditModal(cardCol);
        else if (deleteBtn) handleDelete(cardCol);
        else if (testBtn) handleTestConnection(cardCol, testBtn);
    });

    function openEditModal(cardCol) {
        const card = cardCol.querySelector(".sensor-card");
        document.getElementById("sensorModalTitle").textContent = "Edit Sensor";
        document.getElementById("sensorId").value = cardCol.dataset.sensorId;
        document.getElementById("sensorName").value = card.dataset.name;
        document.getElementById("sensorLocation").value = card.dataset.location;
        document.getElementById("sensorUnit").value = card.dataset.unit;
        document.getElementById("normalRange").value = card.dataset.normalRange;
        document.getElementById("alarmThreshold").value = card.dataset.alarmThreshold;
        document.getElementById("sensorNotes").value = card.dataset.notes;
        sensorTypeSelect.value = card.dataset.sensorType;
        responseTypeSelect.value = card.dataset.responseType;
        document.getElementById("apiUrl").value = card.dataset.apiUrl;
        document.getElementById("apiHeaders").value = card.dataset.apiHeaders;
        document.getElementById("apiJsonPath").value = card.dataset.apiJsonPath;
        apiMethodSelect.value = card.dataset.apiMethod || "GET";
        sensorModal.show();
    }

    // --- Save (Add or Edit) ------------------------------------------------
    document.getElementById("saveSensorBtn").addEventListener("click", async () => {
        const form = document.getElementById("sensorForm");
        if (!form.reportValidity()) return;

        const sensorId = document.getElementById("sensorId").value;
        const payload = {
            name: document.getElementById("sensorName").value.trim(),
            sensor_type: sensorTypeSelect.value,
            response_type: responseTypeSelect.value,
            location: document.getElementById("sensorLocation").value.trim(),
            unit: document.getElementById("sensorUnit").value.trim(),
            normal_range: document.getElementById("normalRange").value.trim(),
            alarm_threshold: document.getElementById("alarmThreshold").value.trim(),
            notes: document.getElementById("sensorNotes").value.trim(),
            api_url: document.getElementById("apiUrl").value.trim(),
            api_method: apiMethodSelect.value,
            api_headers: document.getElementById("apiHeaders").value.trim(),
            api_json_path: document.getElementById("apiJsonPath").value.trim(),
        };

        const url = sensorId
            ? `/factory/${factoryId}/sensors/${sensorId}/edit`
            : `/factory/${factoryId}/sensors/add`;

        try {
            const response = await fetch(url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const result = await response.json();

            if (!result.success) {
                alert("Something went wrong saving this sensor: " + (result.error || "unknown error"));
                return;
            }

            if (sensorId) updateCardInPlace(sensorId, result.sensor);
            else appendNewCard(result.sensor);

            sensorModal.hide();
        } catch (err) {
            alert("Network error while saving the sensor. Please try again.");
            console.error(err);
        }
    });

    // --- Delete -------------------------------------------------------------
    async function handleDelete(cardCol) {
        const sensorId = cardCol.dataset.sensorId;
        const sensorName = cardCol.querySelector(".card-title").textContent;
        if (!confirm(`Delete "${sensorName}"? This can't be undone.`)) return;

        try {
            const response = await fetch(`/factory/${factoryId}/sensors/${sensorId}/delete`, { method: "POST" });
            const result = await response.json();
            if (!result.success) {
                alert("Could not delete this sensor: " + (result.error || "unknown error"));
                return;
            }
            cardCol.remove();
            showEmptyStateIfNeeded();
        } catch (err) {
            alert("Network error while deleting the sensor. Please try again.");
            console.error(err);
        }
    }

    // --- Test Connection ------------------------------------------------------
    async function handleTestConnection(cardCol, testBtn) {
        const sensorId = cardCol.dataset.sensorId;
        const originalHtml = testBtn.innerHTML;
        testBtn.disabled = true;
        testBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Testing…';

        try {
            const response = await fetch(`/factory/${factoryId}/sensors/${sensorId}/test`, { method: "POST" });
            const result = await response.json();

            const badge = cardCol.querySelector(".api-status-badge");
            if (result.success) {
                badge.textContent = result.api_status;
                badge.className = "api-status-badge badge " + (result.api_status === "Active" ? "text-bg-success" : "text-bg-danger");
                // Brief, non-blocking feedback rather than an alert() --
                // testing a sensor is a routine action, not an error state.
                testBtn.innerHTML = `<i class="bi bi-check-circle"></i> ${result.message}`;
            } else {
                testBtn.innerHTML = `<i class="bi bi-x-circle"></i> ${result.error || "Test failed"}`;
            }
        } catch (err) {
            testBtn.innerHTML = '<i class="bi bi-x-circle"></i> Network error';
            console.error(err);
        } finally {
            setTimeout(() => {
                testBtn.disabled = false;
                testBtn.innerHTML = originalHtml;
            }, 2500);
        }
    }

    // --- DOM helpers ------------------------------------------------------

    function appendNewCard(sensor) {
        removeEmptyState();
        const wrapper = document.createElement("div");
        wrapper.innerHTML = buildCardHtml(sensor);
        sensorGrid.appendChild(wrapper.firstElementChild);
    }

    function updateCardInPlace(sensorId, sensor) {
        const existingCol = sensorGrid.querySelector(`.sensor-col[data-sensor-id="${sensorId}"]`);
        if (!existingCol) return;
        const wrapper = document.createElement("div");
        wrapper.innerHTML = buildCardHtml(sensor);
        existingCol.replaceWith(wrapper.firstElementChild);
    }

    function removeEmptyState() {
        const emptyState = document.getElementById("emptyState");
        if (emptyState) emptyState.remove();
    }

    function showEmptyStateIfNeeded() {
        if (sensorGrid.querySelectorAll(".sensor-col").length === 0) {
            const div = document.createElement("div");
            div.className = "col-12";
            div.id = "emptyState";
            div.innerHTML = `
                <div class="text-center text-muted py-5">
                    <i class="bi bi-inboxes display-4"></i>
                    <p class="mt-2">No sensors yet. Add some manually to get started.</p>
                </div>`;
            sensorGrid.appendChild(div);
        }
    }

    // Builds the exact same markup as templates/partials/sensor_card.html --
    // keep both in sync if you change one.
    function buildCardHtml(sensor) {
        const isAi = sensor.source === "AI-Extracted";
        const badgeClass = isAi ? "badge-ai" : "badge-manual";
        const badgeIcon = isAi ? "bi-robot" : "bi-person";
        const apiStatusClass = sensor.api_status === "Active" ? "text-bg-success"
            : (sensor.api_status === "Inactive" ? "text-bg-danger" : "text-bg-secondary");

        return `
        <div class="col-md-6 col-lg-4 sensor-col" data-sensor-id="${sensor.id}">
            <div class="card sensor-card h-100"
                 data-name="${escapeHtml(sensor.name)}"
                 data-sensor-type="${escapeHtml(sensor.sensor_type)}"
                 data-location="${escapeHtml(sensor.location)}"
                 data-unit="${escapeHtml(sensor.unit)}"
                 data-normal-range="${escapeHtml(sensor.normal_range)}"
                 data-alarm-threshold="${escapeHtml(sensor.alarm_threshold)}"
                 data-response-type="${escapeHtml(sensor.response_type)}"
                 data-notes="${escapeHtml(sensor.notes)}"
                 data-api-url="${escapeHtml(sensor.api_url)}"
                 data-api-method="${escapeHtml(sensor.api_method)}"
                 data-api-headers="${escapeHtml(sensor.api_headers)}"
                 data-api-json-path="${escapeHtml(sensor.api_json_path)}">
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-start">
                        <span class="badge ${badgeClass}"><i class="bi ${badgeIcon}"></i> ${escapeHtml(sensor.source)}</span>
                        <span class="badge text-bg-light border">${escapeHtml(sensor.sensor_type)}</span>
                    </div>
                    <h5 class="card-title tag-id mt-2 mb-1">${escapeHtml(sensor.name)}</h5>   // (or asset.name / permit.permit_number)
                    <p class="text-muted small mb-2"><i class="bi bi-geo-alt"></i> ${escapeHtml(sensor.location) || "Location not specified"}</p>
                    <div class="sensor-detail-row">
                        <span class="label">Normal Range</span>
                        <span class="value">${escapeHtml(sensor.normal_range) || "—"} ${escapeHtml(sensor.unit)}</span>
                    </div>
                    <div class="sensor-detail-row">
                        <span class="label">Alarm Threshold</span>
                        <span class="value">${escapeHtml(sensor.alarm_threshold) || "—"}</span>
                    </div>
                    <div class="sensor-detail-row">
                        <span class="label">Response Type</span>
                        <span class="value">${escapeHtml(sensor.response_type)}</span>
                    </div>
                    ${sensor.notes ? `<p class="small text-muted mt-2 mb-0"><i class="bi bi-sticky"></i> ${escapeHtml(sensor.notes)}</p>` : ""}
                    <hr class="my-2">
                    <div class="d-flex justify-content-between align-items-center">
                        <span class="small text-muted"><i class="bi bi-hdd-network"></i> API Status</span>
                        <span class="api-status-badge badge ${apiStatusClass}">${escapeHtml(sensor.api_status)}</span>
                    </div>
                    ${sensor.api_url
                        ? `<p class="small text-muted mb-0 text-truncate" title="${escapeHtml(sensor.api_url)}"><i class="bi bi-link-45deg"></i> ${escapeHtml(sensor.api_url)}</p>`
                        : `<p class="small text-muted mb-0 fst-italic">No API endpoint configured</p>`}
                </div>
                <div class="card-footer bg-transparent">
                    <div class="d-flex gap-2 mb-2">
                        <button type="button" class="btn btn-sm btn-outline-primary flex-grow-1 edit-sensor-btn">
                            <i class="bi bi-pencil"></i> Edit
                        </button>
                        <button type="button" class="btn btn-sm btn-outline-danger flex-grow-1 delete-sensor-btn">
                            <i class="bi bi-trash"></i> Delete
                        </button>
                    </div>
                    <button type="button" class="btn btn-sm btn-outline-secondary w-100 test-sensor-btn">
                        <i class="bi bi-plug"></i> Test Connection
                    </button>
                </div>
            </div>
        </div>`;
    }
});
