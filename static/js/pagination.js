/**
 * pagination.js
 * ---------------
 * Generic client-side pagination for card grids (Sensors, Employees,
 * Facility List). Items are shown/hidden (display:none) rather than
 * removed from the DOM, so it never conflicts with each page's own
 * add/edit/delete logic -- those still just query/manipulate elements
 * normally. Call refresh() after anything that changes how many cards
 * exist (add, delete); calling it after an edit too is harmless.
 *
 * Page size is responsive: fewer items per page on narrow (mobile)
 * screens, since fitting many cards on screen without scrolling is much
 * harder on a short mobile viewport.
 *
 * Usage:
 *   const sensorPagination = initPagination({
 *       gridSelector: "#sensorGrid",
 *       itemSelector: ".sensor-col",
 *       controlsId: "sensorPaginationControls",
 *   });
 *   // ... after adding/deleting a card:
 *   sensorPagination.refresh();
 */

function initPagination({ gridSelector, itemSelector, controlsId, pageSizeDesktop = 6, pageSizeMobile = 2, mobileBreakpoint = 768 }) {
    const grid = document.querySelector(gridSelector);
    const controls = document.getElementById(controlsId);
    let currentPage = 1;

    function getPageSize() {
        return window.innerWidth < mobileBreakpoint ? pageSizeMobile : pageSizeDesktop;
    }

    function getItems() {
        // Only real item cards -- the "empty state" placeholder uses a
        // different selector, so it's naturally excluded here.
        return grid ? Array.from(grid.querySelectorAll(itemSelector)) : [];
    }

    function refresh() {
        const items = getItems();
        const pageSize = getPageSize();
        const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
        if (currentPage > totalPages) currentPage = totalPages;

        const start = (currentPage - 1) * pageSize;
        const end = start + pageSize;
        items.forEach((item, index) => {
            item.style.display = (index >= start && index < end) ? "" : "none";
        });

        if (!controls) return;

        if (totalPages <= 1) {
            controls.innerHTML = "";
            return;
        }

        controls.innerHTML = `
            <button type="button" class="btn btn-sm btn-outline-secondary" id="${controlsId}-prev" ${currentPage === 1 ? "disabled" : ""}>
                <i class="bi bi-chevron-left"></i> Prev
            </button>
            <span class="page-indicator">Page ${currentPage} of ${totalPages}</span>
            <button type="button" class="btn btn-sm btn-outline-secondary" id="${controlsId}-next" ${currentPage === totalPages ? "disabled" : ""}>
                Next <i class="bi bi-chevron-right"></i>
            </button>
        `;
        document.getElementById(`${controlsId}-prev`).onclick = () => { currentPage -= 1; refresh(); };
        document.getElementById(`${controlsId}-next`).onclick = () => { currentPage += 1; refresh(); };
    }

    window.addEventListener("resize", () => refresh());
    refresh();

    return { refresh, goToPage: (n) => { currentPage = n; refresh(); } };
}

window.initPagination = initPagination;