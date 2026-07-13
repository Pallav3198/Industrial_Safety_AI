/**
 * facility_details.js
 * ----------------------
 * Handles inline rename on the Facility Details (View/Edit) page.
 * Everything else on that page is plain links into the existing wizard
 * step pages (sensors/employees/negligence/attendance), which already
 * have their own full edit logic -- this file only handles the one
 * piece of editing that lives directly on this page: the facility name.
 */

document.addEventListener("DOMContentLoaded", () => {
    const factoryId = document.getElementById("app-data").dataset.factoryId;
    const nameDisplay = document.getElementById("facilityNameDisplay");
    const editBtn = document.getElementById("editNameBtn");
    const editRow = document.getElementById("editNameRow");
    const nameInput = document.getElementById("facilityNameInput");
    const saveBtn = document.getElementById("saveNameBtn");
    const cancelBtn = document.getElementById("cancelNameBtn");
    const displayRow = nameDisplay.parentElement;

    function showEditMode() {
        displayRow.classList.add("d-none");
        editRow.classList.remove("d-none");
        editRow.classList.add("d-flex");
        nameInput.value = nameDisplay.textContent.trim();
        nameInput.focus();
    }

    function showDisplayMode() {
        editRow.classList.add("d-none");
        editRow.classList.remove("d-flex");
        displayRow.classList.remove("d-none");
    }

    editBtn.addEventListener("click", showEditMode);
    cancelBtn.addEventListener("click", showDisplayMode);

    nameInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); saveBtn.click(); }
        if (e.key === "Escape") { showDisplayMode(); }
    });

    saveBtn.addEventListener("click", async () => {
        const newName = nameInput.value.trim();
        if (!newName) {
            alert("Name cannot be empty.");
            return;
        }

        saveBtn.disabled = true;
        try {
            const response = await fetch(`/factory/${factoryId}/rename`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: newName }),
            });
            const result = await response.json();

            if (result.success) {
                nameDisplay.textContent = result.name;
                document.title = result.name + " — Facility Details";
                showDisplayMode();
            } else {
                alert("Could not rename: " + (result.error || "unknown error"));
            }
        } catch (err) {
            alert("Network error while renaming. Please try again.");
            console.error(err);
        } finally {
            saveBtn.disabled = false;
        }
    });
    const deleteBtn = document.getElementById("deleteFacilityBtn");
    deleteBtn.addEventListener("click", async () => {
        const currentName = nameDisplay.textContent.trim();
        const confirmed = confirm(`Delete "${currentName}"? This cannot be undone.`);
        if (!confirmed) return;

        deleteBtn.disabled = true;
        try {
            const response = await fetch(`/factory/${factoryId}/delete`, { method: "POST" });
            if (response.redirected) {
                window.location.href = response.url;
            } else {
                alert("Something went wrong deleting the facility.");
                deleteBtn.disabled = false;
            }
        } catch (err) {
            alert("Network error — please try again.");
            deleteBtn.disabled = false;
        }
    });
});