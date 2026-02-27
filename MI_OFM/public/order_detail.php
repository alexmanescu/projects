<?php
// ─────────────────────────────────────────────────────────
//  Order Detail — view a single order with lines & history
// ─────────────────────────────────────────────────────────

declare(strict_types=1);

require_once '../includes/auth.php';
require_once '../includes/functions.php';

requireLogin();

$pdo  = getDb();
$user = currentUser();

$orderId = (int) ($_GET['id'] ?? 0);
if (!$orderId) {
    header('Location: ' . ($user['role'] === 'puller' ? 'puller_queue.php' : 'dashboard.php'));
    exit;
}

// ── Fetch order ───────────────────────────────────────────
$orderStmt = $pdo->prepare('SELECT * FROM orders WHERE id = ? LIMIT 1');
$orderStmt->execute([$orderId]);
$order = $orderStmt->fetch();

if (!$order) {
    http_response_code(404);
    die('Order not found.');
}

// ── Handle status update (pullers) ────────────────────────
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    if (!validateCsrf($_POST['csrf_token'] ?? '')) {
        flashSet('danger', 'Invalid request token.');
        header("Location: order_detail.php?id=$orderId");
        exit;
    }

    $action = $_POST['action'] ?? '';

    // Update pulled quantities (puller or admin)
    if ($action === 'update_lines') {
        if (in_array($user['role'], ['puller', 'admin', 'supervisor'])) {
            $qtyData = $_POST['qty_pulled'] ?? [];
            foreach ($qtyData as $lineId => $qty) {
                $lineId = (int) $lineId;
                $qty    = max(0, (float) $qty);
                $pdo->prepare('UPDATE order_lines SET qty_pulled=? WHERE id=? AND order_id=?')
                    ->execute([$qty, $lineId, $orderId]);
            }
            logAudit($pdo, 'update_line_qtys', 'orders', $orderId, ['updated_by' => $user['id']]);
            flashSet('success', 'Quantities updated.');
        }
        header("Location: order_detail.php?id=$orderId");
        exit;
    }
}

// ── Fetch order lines ─────────────────────────────────────
$linesStmt = $pdo->prepare('SELECT * FROM order_lines WHERE order_id=? ORDER BY id');
$linesStmt->execute([$orderId]);
$lines = $linesStmt->fetchAll();

// ── Fetch active assignment ───────────────────────────────
$assignStmt = $pdo->prepare(
    "SELECT a.*, u.name AS puller_name, u.department AS puller_dept,
            l.name AS location_name, s.name AS stage_name
     FROM assignments a
     JOIN users u ON u.id = a.user_id
     LEFT JOIN locations l ON l.id = a.location_id
     LEFT JOIN stages s ON s.id = a.stage_id
     WHERE a.order_id=? AND a.status='active'
     LIMIT 1"
);
$assignStmt->execute([$orderId]);
$assignment = $assignStmt->fetch();

// ── Fetch audit log ───────────────────────────────────────
$auditLog = [];
if (in_array($user['role'], ['supervisor', 'admin'])) {
    $auditStmt = $pdo->prepare(
        "SELECT al.*, u.name AS actor_name
         FROM audit_log al
         LEFT JOIN users u ON u.id = al.user_id
         WHERE al.entity_type='orders' AND al.entity_id=?
         ORDER BY al.created_at DESC
         LIMIT 50"
    );
    $auditStmt->execute([$orderId]);
    $auditLog = $auditStmt->fetchAll();
}

// ── Progress calculation ──────────────────────────────────
$totalOrdered = array_sum(array_column($lines, 'qty_ordered'));
$totalPulled  = array_sum(array_column($lines, 'qty_pulled'));
$pct          = $totalOrdered > 0 ? round(($totalPulled / $totalOrdered) * 100) : 0;

$pageTitle = 'Order ' . $order['order_number'];
include '../includes/header.php';
?>

<div class="container">

  <!-- ── Back link ── -->
  <a href="<?= $user['role'] === 'puller' ? 'puller_queue.php' : 'dashboard.php' ?>"
     class="back-link">&#8592; Back</a>

  <!-- ── Order header ── -->
  <div class="order-detail-header">
    <div>
      <h2 class="page-title"><?= e($order['order_number']) ?></h2>
      <div class="customer-name-lg"><?= e($order['customer_name']) ?></div>
      <?php if ($order['customer_po']): ?>
        <div class="text-muted">PO: <?= e($order['customer_po']) ?></div>
      <?php endif; ?>
    </div>
    <div class="order-detail-meta">
      <span class="status-badge <?= statusClass($order['status']) ?> status-badge-lg">
        <?= statusLabel($order['status']) ?>
      </span>
      <div class="ship-date-block <?= urgencyClass($order['required_ship_date']) ?>">
        <span class="ship-date-label">Ships</span>
        <span class="ship-date-val"><?= fmtDate($order['required_ship_date']) ?></span>
        <span class="urgency-label"><?= urgencyLabel($order['required_ship_date']) ?></span>
      </div>
    </div>
  </div>

  <!-- ── Assignment info ── -->
  <?php if ($assignment): ?>
  <div class="info-card">
    <div class="info-card-title">Current Assignment</div>
    <div class="info-grid">
      <div><span class="info-label">Assigned To</span><span><?= e($assignment['puller_name']) ?></span></div>
      <div><span class="info-label">Department</span><span><?= $assignment['department'] ? e(ucfirst($assignment['department'])) : '—' ?></span></div>
      <div><span class="info-label">Stage</span><span><?= e($assignment['stage_name'] ?? '—') ?></span></div>
      <div><span class="info-label">Checked In</span><span><?= $assignment['checked_in_at'] ? fmtDateTime($assignment['checked_in_at']) : '—' ?></span></div>
      <?php if ($assignment['notes']): ?>
        <div class="info-full"><span class="info-label">Notes</span><span><?= e($assignment['notes']) ?></span></div>
      <?php endif; ?>
    </div>
  </div>
  <?php endif; ?>

  <!-- ── Pull progress ── -->
  <div class="info-card">
    <div class="info-card-title">Pull Progress</div>
    <div class="progress-bar-wrap">
      <div class="progress-bar" style="width:<?= $pct ?>%"></div>
    </div>
    <div class="progress-label"><?= $pct ?>% — <?= round($totalPulled, 1) ?> / <?= round($totalOrdered, 1) ?> units pulled</div>
  </div>

  <!-- ── Order Lines ── -->
  <div class="section-header">
    <h3 class="section-title">Order Lines</h3>
  </div>

  <?php
  // Pullers can update line quantities, supervisors/admins can too
  $canEditLines = in_array($user['role'], ['puller', 'admin', 'supervisor'])
    && ($order['status'] !== 'completed');
  // Pullers can only edit their own assignment
  if ($user['role'] === 'puller') {
      $canEditLines = $canEditLines && ($assignment['user_id'] ?? 0) == $user['id'];
  }
  ?>

  <form method="POST" action="order_detail.php?id=<?= $orderId ?>">
    <?= csrfField() ?>
    <input type="hidden" name="action" value="update_lines">

    <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>Item Code</th>
            <th>Description</th>
            <th class="col-num">Ordered</th>
            <th class="col-num">Pulled</th>
            <th class="col-num">UOM</th>
            <th class="col-num">%</th>
          </tr>
        </thead>
        <tbody>
          <?php foreach ($lines as $line):
              $linePct  = $line['qty_ordered'] > 0 ? round(($line['qty_pulled'] / $line['qty_ordered']) * 100) : 0;
              $lineClass = $linePct >= 100 ? 'line-complete' : ($linePct > 0 ? 'line-partial' : '');
          ?>
          <tr class="<?= $lineClass ?>">
            <td class="mono"><?= e($line['item_code']) ?></td>
            <td><?= e($line['description'] ?? '') ?></td>
            <td class="col-num"><?= (float) $line['qty_ordered'] ?></td>
            <td class="col-num">
              <?php if ($canEditLines): ?>
                <input
                  type="number"
                  name="qty_pulled[<?= $line['id'] ?>]"
                  value="<?= (float) $line['qty_pulled'] ?>"
                  min="0"
                  max="<?= (float) $line['qty_ordered'] ?>"
                  step="1"
                  class="qty-input"
                >
              <?php else: ?>
                <?= (float) $line['qty_pulled'] ?>
              <?php endif; ?>
            </td>
            <td class="col-num"><?= e($line['uom'] ?? '') ?></td>
            <td class="col-num">
              <span class="pct-badge <?= $linePct >= 100 ? 'pct-done' : ($linePct > 0 ? 'pct-partial' : '') ?>">
                <?= $linePct ?>%
              </span>
            </td>
          </tr>
          <?php endforeach; ?>
        </tbody>
      </table>
    </div>

    <?php if ($canEditLines): ?>
      <div style="margin-top: .75rem;">
        <button type="submit" class="btn btn-primary">Save Quantities</button>
      </div>
    <?php endif; ?>
  </form>

  <!-- ── Audit Log (supervisors/admins only) ── -->
  <?php if (!empty($auditLog)): ?>
  <div class="section-header" style="margin-top: 2rem;">
    <h3 class="section-title">Audit Log</h3>
  </div>
  <div class="audit-log">
    <?php foreach ($auditLog as $entry): ?>
    <div class="audit-entry">
      <span class="audit-time"><?= fmtDateTime($entry['created_at']) ?></span>
      <span class="audit-actor"><?= e($entry['actor_name'] ?? 'System') ?></span>
      <span class="audit-action"><?= e(str_replace('_', ' ', $entry['action'])) ?></span>
      <?php if ($entry['ip_address']): ?>
        <span class="audit-ip text-muted"><?= e($entry['ip_address']) ?></span>
      <?php endif; ?>
    </div>
    <?php endforeach; ?>
  </div>
  <?php endif; ?>

</div><!-- /container -->

<?php include '../includes/footer.php'; ?>
