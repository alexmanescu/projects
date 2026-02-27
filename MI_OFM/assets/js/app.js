/**
 * MI Order Fulfillment Manager — App JS
 * Vanilla ES6+, no frameworks. Handles:
 *  - Mobile nav toggle
 *  - Assign modal
 *  - Dynamic order form (add/remove line rows)
 *  - Dashboard auto-refresh
 *  - Flash message auto-dismiss
 */

(function () {
  'use strict';

  // ── Mobile nav toggle ──────────────────────────────────
  const navToggle = document.getElementById('navToggle');
  const navLinks  = document.getElementById('navLinks');

  if (navToggle && navLinks) {
    navToggle.addEventListener('click', () => {
      navLinks.classList.toggle('open');
    });
    // Close on outside click
    document.addEventListener('click', (e) => {
      if (!navToggle.contains(e.target) && !navLinks.contains(e.target)) {
        navLinks.classList.remove('open');
      }
    });
  }

  // ── Assign modal (dashboard) ───────────────────────────
  window.openAssignModal = function (orderId, orderNum) {
    const modal = document.getElementById('assignModal');
    if (!modal) return;
    document.getElementById('modalOrderId').value = orderId;
    document.getElementById('modalOrderNum').textContent = orderNum;
    modal.removeAttribute('hidden');
    modal.querySelector('.modal-close').focus();
  };

  window.closeAssignModal = function () {
    const modal = document.getElementById('assignModal');
    if (modal) modal.setAttribute('hidden', '');
  };

  // Close modal on overlay click
  const assignModal = document.getElementById('assignModal');
  if (assignModal) {
    assignModal.addEventListener('click', (e) => {
      if (e.target === assignModal) closeAssignModal();
    });
    // Trap Escape key
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !assignModal.hasAttribute('hidden')) {
        closeAssignModal();
      }
    });
  }

  // ── Dynamic order line rows (admin_orders) ─────────────
  const addLineBtn = document.getElementById('addLineBtn');
  const lineRows   = document.getElementById('lineRows');

  if (addLineBtn && lineRows) {
    addLineBtn.addEventListener('click', () => {
      const tr = document.createElement('tr');
      tr.className = 'line-row';
      tr.innerHTML = `
        <td><input type="text"   name="item_code[]"   class="form-control mono"  placeholder="ITEM-CODE" required></td>
        <td><input type="text"   name="description[]" class="form-control"       placeholder="Description"></td>
        <td><input type="number" name="qty_ordered[]" class="form-control col-num" min="0.01" step="1" required></td>
        <td><input type="text"   name="uom[]"         class="form-control" style="width:5rem" placeholder="EA"></td>
        <td><button type="button" class="btn btn-danger btn-xs remove-line">&#10005;</button></td>
      `;
      lineRows.appendChild(tr);
      tr.querySelector('input').focus();
    });

    // Remove line row (event delegation)
    lineRows.addEventListener('click', (e) => {
      if (e.target.classList.contains('remove-line')) {
        const row = e.target.closest('tr');
        if (lineRows.querySelectorAll('tr').length > 1) {
          row.remove();
        }
      }
    });
  }

  // ── Flash auto-dismiss (after 6 seconds) ──────────────
  const flash = document.querySelector('.flash');
  if (flash) {
    setTimeout(() => {
      flash.style.transition = 'opacity .4s';
      flash.style.opacity    = '0';
      setTimeout(() => flash.remove(), 400);
    }, 6000);
  }

  // ── Dashboard auto-refresh every 90 seconds ─────────────
  // Only on dashboard page — refreshes the page to show live data.
  if (document.getElementById('ordersTable')) {
    let refreshTimer = setTimeout(() => {
      window.location.reload();
    }, 90000);

    // Reset timer on user interaction (they're actively using the page)
    ['click', 'keydown', 'mousemove'].forEach((evt) => {
      document.addEventListener(evt, () => {
        clearTimeout(refreshTimer);
        refreshTimer = setTimeout(() => window.location.reload(), 90000);
      }, { passive: true, once: false });
    });
  }

  // ── Confirm destructive actions ───────────────────────
  // Any form with data-confirm gets a confirm dialog on submit.
  document.querySelectorAll('form[data-confirm]').forEach((form) => {
    form.addEventListener('submit', (e) => {
      if (!confirm(form.dataset.confirm)) {
        e.preventDefault();
      }
    });
  });

  // ── Ship date validation on order form ─────────────────
  const orderForm = document.getElementById('orderForm');
  if (orderForm) {
    const orderDateInput = document.getElementById('order_date');
    const shipDateInput  = document.getElementById('required_ship_date');

    if (orderDateInput && shipDateInput) {
      shipDateInput.addEventListener('change', () => {
        if (orderDateInput.value && shipDateInput.value) {
          if (shipDateInput.value < orderDateInput.value) {
            shipDateInput.setCustomValidity('Ship date must be on or after order date.');
          } else {
            shipDateInput.setCustomValidity('');
          }
        }
      });
    }
  }

})();
