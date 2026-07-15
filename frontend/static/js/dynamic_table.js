/**
 * dynamic_table.js
 * -------------------
 * Generic add/remove-row helper for simple flat tables backed by
 * array-named form inputs (e.g. name="dept_name[]"), submitted with a
 * normal HTML form POST -- no fetch/JSON needed. Used by any section
 * that's just "a list of a few labeled fields per row" with no other
 * behavior (Departments, SCADA Systems, and later Shift Patterns,
 * Maintenance Records, Utility Systems, etc.) -- see
 * models/factory.py's Part A/B/C/E fields for the full list.
 *
 * Usage:
 *   initDynamicTable({
 *       tbodyId: "departmentRows",
 *       addButtonId: "addDepartmentRowBtn",
 *       rowHtml: (values) => `
 *           <td><input type="text" name="dept_name[]" class="form-control form-control-sm" value="${values.name || ''}"></td>
 *           <td><input type="text" name="dept_function[]" class="form-control form-control-sm" value="${values.function || ''}"></td>
 *           <td><input type="text" name="dept_headcount[]" class="form-control form-control-sm" value="${values.headcount || ''}"></td>
 *           <td><button type="button" class="btn btn-sm btn-outline-danger remove-row-btn"><i class="bi bi-trash"></i></button></td>
 *       `,
 *       existingRows: window.EXISTING_DEPARTMENTS || [],  // pre-populate on page load
 *   });
 */

function initDynamicTable({ tbodyId, addButtonId, rowHtml, existingRows }) {
    const tbody = document.getElementById(tbodyId);
    const addBtn = document.getElementById(addButtonId);

    function addRow(values) {
        const tr = document.createElement("tr");
        tr.innerHTML = rowHtml(values || {});
        tbody.appendChild(tr);
        tr.querySelector(".remove-row-btn").addEventListener("click", () => tr.remove());
    }

    addBtn.addEventListener("click", () => addRow());

    (existingRows || []).forEach((row) => addRow(row));

    // Always leave at least one blank row so the form never submits an
    // entirely empty table by accident, and so first-time users see the
    // expected field layout immediately.
    if (!existingRows || existingRows.length === 0) {
        addRow();
    }

    return { addRow };
}