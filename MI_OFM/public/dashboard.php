<?php
// ─────────────────────────────────────────────────────────
//  Supervisor / Admin Dashboard — all orders at a glance
// ─────────────────────────────────────────────────────────

declare(strict_types=1);

require_once '../includes/auth.php';
require_once '../includes/functions.php';

requireLogin();
requireRole(['supervisor', 'admin']);

$pdo  = getDb();
$user = currentUser();

// ── Handle assign POST ────────────────────────────────────
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['action'])) {
    if (!validateCsrf($_POST['csrf_token'] ?? '')) {
        flashSet('danger', 'Invalid request token.');
        header('Location: dashboard.php');
        exit;
    }

    $action = $_POST['action'];

    if ($action === 'assign' && !empty($_POST['order_id']) && !empty($_POST['puller_id'])) {
        $orderId  = (int) $_POST['order_id'];
        $pullerId = (int) $_POST['puller_id'];
        $dept     = $_POST['department'] ?? null;
        $notes    = trim($_POST['notes'] ?? '');

        // Release any existing active assignment
        $pdo->prepare("UPDATE assignments SET status='released' WHERE order_id = ? AND status='active'")
            ->execute([$orderId]);

        // Create new assignment
        $stmt = $pdo->prepare(
            'INSERT INTO assignments (order_id, user_id, stage_id, department, notes, checked_in_at, status)
             VALUES (?, ?, 2, ?, ?, NOW(), "active")'
        );
        $stmt->execute([$orderId, $pullerId, $dept ?: null, $notes ?: null]);

        // Update order status
        $pdo->prepare("UPDATE orders SET status='assigned', updated_at=NOW() WHERE id=?")
            ->execute([$orderId]);

        logAudit($pdo, 'assign_order', 'orders', $orderId, [
            'puller_id' => $pullerId,
            'assigned_by' => $user['id'],
        ]);

        flashSet('success', 'Order assigned successfully.');
        header('Location: dashboard.php');
        exit;
    }

    if ($action === 'release' && !empty($_POST['order_id'])) {
        $orderId = (int) $_POST['order_id'];
        $pdo->prepare("UPDATE assignments SET status='released', checked_out_at=NOW() WHERE order_id=? AND status='active'")
            ->execute([$orderId]);
        $pdo->prepare("UPDATE orders SET status='new', updated_at=NOW() WHERE id=?")
            ->execute([$orderId]);
        logAudit($pdo, 'release_order', 'orders', $orderId, ['released_by' => $user['id']]);
        flashSet('success', 'Order released back to queue.');
        header('Location: dashboard.php');
        exit;
    }
}

// ── Filters ───────────────────────────────────────────────
$filterStatus = $_GET['status'] ?? '';
$filterDept   = $_GET['dept'] ?? '';

// ── Fetch orders ──────────────────────────────────────────
$filters = ['exclude_completed' => empty($filterStatus)];
if ($filterStatus) $filters['status']     = $filterStatus;
if ($filterDept)   $filters['department'] = $filterDept;

if (!empty($_GET['show_completed'])) {
    unset($filters['exclude_completed']);
}

$orders = getOrdersWithAssignment($pdo, $filters);

// ── Summary counts ────────────────────────────────────────
$counts = $pdo->query(
    "SELECT status, COUNT(*) AS cnt FROM orders GROUP BY status"
)->fetchAll(PDO::FETCH_KEY_PAIR);

// ── Pullers list for assignment modal ─────────────────────
$pullers = getPullers($pdo);

$pageTitle = 'Dashboard';
include '../includes/header.php';
?>

<div class="container">

  <!-- ── Stats bar ── -->
  <div class="stats-bar">
    <?php
    $statuses = [
        'new'            => 'New',
        'assigned'       => 'Assigned',
        'in_progress'    => 'In Progress',
        'staged'         => 'Staged',
        'ready_for_dock' => 'Ready for Dock',
        'completed'      => 'Completed',
    ];
    foreach ($statuses as $key => $label):
        $cnt = $counts[$key] ?? 0;
    ?>
    <a href="?status=<?= $key ?>" class="stat-card <?= $filterStatus === $key ? 'active' : '' ?>">
      <span class="stat-num"><?= $cnt ?></span>
      <span class="stat-label <?= statusClass($key) ?>"><?= $label ?></span>
    </a>
    <?php endforeach; ?>
    <a href="dashboard.php" class="stat-card <?= $filterStatus === '' ? 'active' : '' ?>">
      <span class="stat-num"><?= array_sum($counts) ?></span>
      <span class="stat-label">All Open</span>
    </a>
  </div>

  <!-- ── Header row ── -->
  <div class="page-header">
    <h2 class="page-title">
      <?= $filterStatus ? statusLabel($filterStatus) . ' Orders' : 'All Open Orders' ?>
      <span class="count-badge"><?= count($orders) ?></span>
    </h2>
    <div class="page-actions">
      <?php if ($user['role'] === 'admin'): ?>
        <a href="admin_orders.php?action=new" class="btn btn-primary btn-sm">+ New Order</a>
      <?php endif; ?>
      <?php if (!isset($_GET['show_completed'])): ?>
        <a href="?<?= http_build_query(array_merge($_GET, ['show_completed' => 1])) ?>" class="btn btn-outline btn-sm">Show Completed</a>
      <?php endif; ?>
    </div>
  </div>

  <!-- ── Orders table ── -->
  <?php if (empty($orders)): ?>
    <div class="empty-state">No orders match the current filter.</div>
  <?php else: ?>

  <div class="table-wrap">
    <table class="data-table" id="ordersTable">
      <thead>
        <tr>
          <th>Order #</th>
          <th>Customer</th>
          <th>Ship Date</th>
          <th>Status</th>
          <th>Assigned To</th>
          <th class="col-actions">Actions</th>
        </tr>
      </thead>
      <tbody>
        <?php foreach ($orders as $o):
            $urgClass = $o['status'] !== 'completed' ? urgencyClass($o['required_ship_date']) : '';
        ?>
        <tr class="<?= $urgClass ?>">
          <td>
            <a href="order_detail.php?id=<?= $o['id'] ?>" class="order-link">
              <?= e($o['order_number']) ?>
            </a>
          </td>
          <td>
            <span class="customer-name"><?= e($o['customer_name']) ?></span>
            <?php if ($o['customer_po']): ?>
              <span class="text-muted text-sm">PO: <?= e($o['customer_po']) ?></span>
            <?php endif; ?>
          </td>
          <td class="nowrap">
            <span><?= fmtDate($o['required_ship_date']) ?></span>
            <?php if ($o['status'] !== 'completed'): ?>
              <span class="urgency-label <?= urgencyClass($o['required_ship_date']) ?>">
                <?= urgencyLabel($o['required_ship_date']) ?>
              </span>
            <?php endif; ?>
          </td>
          <td>
            <span class="status-badge <?= statusClass($o['status']) ?>">
              <?= statusLabel($o['status']) ?>
            </span>
          </td>
          <td>
            <?php if ($o['assigned_to_name']): ?>
              <span class="puller-name"><?= e($o['assigned_to_name']) ?></span>
              <?php if ($o['assigned_dept']): ?>
                <span class="dept-chip"><?= e(ucfirst($o['assigned_dept'])) ?></span>
              <?php endif; ?>
            <?php else: ?>
              <span class="text-muted">Unassigned</span>
            <?php endif; ?>
          </td>
          <td class="col-actions">
            <a href="order_detail.php?id=<?= $o['id'] ?>" class="btn btn-outline btn-xs">View</a>

            <?php if ($o['status'] !== 'completed'): ?>
              <button class="btn btn-primary btn-xs"
                      onclick="openAssignModal(<?= $o['id'] ?>, '<?= e($o['order_number']) ?>')">
                Assign
              </button>
            <?php endif; ?>

            <?php if ($o['assignment_id'] && $o['status'] !== 'completed'): ?>
              <form method="POST" style="display:inline" onsubmit="return confirm('Release this order back to the queue?')">
                <?= csrfField() ?>
                <input type="hidden" name="action"   value="release">
                <input type="hidden" name="order_id" value="<?= $o['id'] ?>">
                <button type="submit" class="btn btn-danger btn-xs">Release</button>
              </form>
            <?php endif; ?>
          </td>
        </tr>
        <?php endforeach; ?>
      </tbody>
    </table>
  </div>
  <?php endif; ?>

</div><!-- /container -->

<!-- ── Assign Modal ── -->
<div class="modal-overlay" id="assignModal" hidden>
  <div class="modal">
    <div class="modal-header">
      <h3 class="modal-title">Assign Order <span id="modalOrderNum"></span></h3>
      <button class="modal-close" onclick="closeAssignModal()">&#10005;</button>
    </div>
    <form method="POST" action="dashboard.php">
      <?= csrfField() ?>
      <input type="hidden" name="action"   value="assign">
      <input type="hidden" name="order_id" id="modalOrderId">

      <div class="modal-body">
        <div class="form-group">
          <label for="puller_id">Assign To</label>
          <select name="puller_id" id="puller_id" class="form-control" required>
            <option value="">— Select puller —</option>
            <?php foreach ($pullers as $p): ?>
              <option value="<?= $p['id'] ?>">
                <?= e($p['name']) ?><?= $p['department'] ? ' (' . ucfirst($p['department']) . ')' : '' ?>
              </option>
            <?php endforeach; ?>
          </select>
        </div>
        <div class="form-group">
          <label for="department">Department</label>
          <select name="department" id="department" class="form-control">
            <option value="">— Any —</option>
            <option value="inside">Inside</option>
            <option value="yard">Yard</option>
          </select>
        </div>
        <div class="form-group">
          <label for="notes">Notes (optional)</label>
          <textarea name="notes" id="notes" class="form-control" rows="2" placeholder="Any special instructions..."></textarea>
        </div>
      </div>

      <div class="modal-footer">
        <button type="button" class="btn btn-outline" onclick="closeAssignModal()">Cancel</button>
        <button type="submit" class="btn btn-primary">Confirm Assignment</button>
      </div>
    </form>
  </div>
</div>

<?php include '../includes/footer.php'; ?>
