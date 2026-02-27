/**
 * MI Barcode — app.js
 *
 * Handles:
 *   1. Auto-submit on scanner input (fast keystroke burst + Enter).
 *   2. Clears the UPC field after a successful print form submission so the
 *      operator can immediately scan the next item.
 *   3. Qty field: select-all on focus for quick keyboard override.
 */

(function () {
    'use strict';

    // ── 1. Scanner auto-submit ────────────────────────────────────────────────
    // Barcode scanners fire characters very quickly then send Enter.
    // If the UPC field receives Enter (keydown), submit immediately.
    const upcInput = document.getElementById('upc-input');
    const searchForm = document.getElementById('search-form');

    if (upcInput && searchForm) {
        upcInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                // Let the browser's normal form submission handle it.
                // This listener exists mainly to document the expected flow.
                // No extra JS needed — the form has no JS submission blocker.
            }
        });

        // Re-focus the UPC field after the page loads (autofocus handles initial
        // load, but this covers cases where focus is lost after results render).
        window.addEventListener('load', function () {
            if (upcInput) {
                upcInput.focus();
                // Position cursor at end of any pre-filled value.
                const len = upcInput.value.length;
                upcInput.setSelectionRange(len, len);
            }
        });
    }

    // ── 2. Qty field: select all on focus ─────────────────────────────────────
    const qtyInput = document.getElementById('qty');
    if (qtyInput) {
        qtyInput.addEventListener('focus', function () {
            this.select();
        });
    }

    // ── 3. Profile form: show thermal/sheet hint ──────────────────────────────
    // Dynamically label the mode badge in the form as the user changes rows/cols.
    const rowsInput = document.getElementById('labels_per_row');
    const colsInput = document.getElementById('labels_per_column');

    function updateModeHint() {
        const rows = parseInt(rowsInput?.value ?? '1', 10);
        const cols = parseInt(colsInput?.value ?? '1', 10);
        const hint = document.getElementById('mode-hint');
        if (!hint) return;
        if (rows === 1 && cols === 1) {
            hint.textContent = 'Thermal mode — one label per page';
            hint.className = 'badge badge--thermal';
        } else {
            hint.textContent = `Sheet mode — ${rows * cols} labels per page`;
            hint.className = 'badge badge--sheet';
        }
    }

    if (rowsInput && colsInput) {
        rowsInput.addEventListener('input', updateModeHint);
        colsInput.addEventListener('input', updateModeHint);
        updateModeHint(); // run once on load
    }

})();
