/**
 * attendance.js
 * ---------------
 * Step 7 (final step) interactivity: "Test Connection" for the
 * attendance system API, and copying the tested values into hidden
 * fields before the "Finish Setup" form submits normally (a plain
 * form POST, not AJAX, since this is the last step and a full-page
 * redirect back to the landing page afterward is exactly what we want).
 */

document.addEventListener("DOMContentLoaded", () => {
    const factoryId = document.getElementById("app-data").dataset.factoryId;
    const urlInput = document.getElementById("attendanceApiUrl");
    const methodSelect = document.getElementById("attendanceApiMethod");
    const headersInput = document.getElementById("attendanceApiHeaders");
    const testBtn = document.getElementById("testAttendanceBtn");
    const statusBadge = document.getElementById("attendanceStatusBadge");
    const testMessage = document.getElementById("attendanceTestMessage");
    const form = document.getElementById("attendanceForm");

    testBtn.addEventListener("click", async () => {
        const originalHtml = testBtn.innerHTML;
        testBtn.disabled = true;
        testBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Testing…';

        const payload = {
            api_url: urlInput.value.trim(),
            api_method: methodSelect.value,
            api_headers: headersInput.value.trim(),
        };

        try {
            const response = await fetch(`/factory/${factoryId}/attendance/test`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const result = await response.json();

            if (result.success) {
                statusBadge.textContent = result.api_status;
                statusBadge.className = "badge " + (result.api_status === "Active" ? "text-bg-success" : "text-bg-danger");
                testMessage.textContent = result.message;
            } else {
                testMessage.textContent = result.error || "Test failed.";
            }
        } catch (err) {
            testMessage.textContent = "Network error while testing the connection.";
            console.error(err);
        } finally {
            testBtn.disabled = false;
            testBtn.innerHTML = originalHtml;
        }
    });

    // Copy current field values into the hidden inputs right before the
    // real form submit fires, so "Finish Setup" always saves whatever is
    // currently typed -- whether or not the user clicked Test first.
    form.addEventListener("submit", () => {
        document.getElementById("hiddenApiUrl").value = urlInput.value.trim();
        document.getElementById("hiddenApiMethod").value = methodSelect.value;
        document.getElementById("hiddenApiHeaders").value = headersInput.value.trim();
    });
});
