/**
 * upload.js
 * ----------
 * Interactivity for the Add Factory Step 1 page:
 *   - clicking the dropzone opens the file picker
 *   - drag-and-drop support with visual feedback
 *   - shows the chosen filename
 *   - shows a full-screen "processing" overlay while the form submits
 *     (the AI extraction call can take a few seconds on a real API key)
 */

document.addEventListener("DOMContentLoaded", () => {
    const dropzone = document.getElementById("dropzone");
    const fileInput = document.getElementById("preliminary_doc");
    const fileNameDisplay = document.getElementById("fileNameDisplay");
    const form = document.getElementById("factoryForm");
    const overlay = document.getElementById("processingOverlay");

    if (!dropzone || !fileInput) return;

    // Clicking anywhere in the dropzone opens the native file picker.
    dropzone.addEventListener("click", () => fileInput.click());

    fileInput.addEventListener("change", () => {
        updateFileNameDisplay();
    });

    // Drag-and-drop visual feedback + actually accepting the dropped file.
    ["dragenter", "dragover"].forEach((eventName) => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.add("dragover");
        });
    });

    ["dragleave", "drop"].forEach((eventName) => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.remove("dragover");
        });
    });

    dropzone.addEventListener("drop", (e) => {
        const dt = e.dataTransfer;
        if (dt && dt.files && dt.files.length > 0) {
            fileInput.files = dt.files;
            updateFileNameDisplay();
        }
    });

    function updateFileNameDisplay() {
        if (fileInput.files && fileInput.files.length > 0) {
            fileNameDisplay.textContent = fileInput.files[0].name;
        } else {
            fileNameDisplay.textContent = "No file selected — PDF only, no size limit";
        }
    }

    // Show the processing overlay once the form is actually submitted
    // (not on click — the browser's own "required" field validation runs
    // first, so this only fires once the form is genuinely going through).
    // AFTER
const fileError = document.getElementById("fileError");

function clearFileError() {
    dropzone.classList.remove("border-danger");
    fileError.classList.add("d-none");
}

fileInput.addEventListener("change", clearFileError);

if (form && overlay) {
    form.addEventListener("submit", (e) => {
        if (!fileInput.files || fileInput.files.length === 0) {
            e.preventDefault();
            dropzone.classList.add("border-danger");
            fileError.classList.remove("d-none");
            dropzone.scrollIntoView({ behavior: "smooth", block: "center" });
            return;
        }
        overlay.classList.remove("d-none");
    });
}
});
