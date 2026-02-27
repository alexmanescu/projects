<?php
// ─────────────────────────────────────────────────────────
//  Puller Queue — a puller's personal order list
// ─────────────────────────────────────────────────────────

declare(strict_types=1);

require_once '../includes/auth.php';
require_once '../includes/functions.php';

requireLogin();
requireRole(['puller']);

$pdo  = getDb();
$user = currentUser();

// ── Handle actions ────────────────────────────────────────
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    if (!validateCsrf($_POST['csrf_token'] ?? '')) {
        flashSet('danger', 'Invalid request. Please try again.');
        header('Location: puller_queue.php');
        exit;
    }

    $action  = $_POST['action'] ?? '';
    $orderId = (int) ($_POST['order_id'] ?? 0);

    if ($action === 'claim' && $orderId) {
        // Verify order is still available (not already assigned)
        $checkStmt = $pdo->prepare("SELECT id, status FROM orders WHERE id=? AND status='new' LIMIT 1");
        $checkStmt->execute([$orderId]);
        $order = $checkStmt->fetch();

        if ($order) {
            $dept = $user['department'] ?: null;
            $ins  = $pdo->prepare(
                'INSERT INTO assignments (order_id, user_id, stage_id, department, checked_in_at, status)
                 VALUES (?, ?, 2, ?, NOW(), "active")'
            );
            $ins->execute([$orderId, $user['id'], $dept]);

            $pdo->prepare("UPDATE orders SET status='assigned', updated_at=NOW() WHERE id=?")
                ->execute([$orderId]);

            logAudit($pdo, 'claim_order', 'orders', $orderId, ['puller_id' => $user['id']]);
            flashSet('success', 'Order claimed. Get to work!');
        } else {
            flashSet('warning', 'That order is no longer available.');
        }
        header('Location: puller_queue.php');
        exit;
    }

    if ($action === 'update_status' && $orderId) {
        $newStatus = $_POST['new_status'] ?? '';
        $allowed   = ['in_progress', 'staged', 'ready_for_dock'];

        if (!in_array($newStatus, $allowed, true)) {
            flashSet('danger', 'Invalid status.');
            header('Location: puller_queue.php');
            exit;
        }

        // Verify this order belongs to the current puller
        $verifyStmt = $pdo->prepare(
            "SELECT a.id FROM assignments a
             WHERE a.order_id=? AND a.user_id=? AND a.status='active' LIMIT 1"
        );
        $verifyStmt->execute([$orderId, $user['id']]);
        $assignment = $verifyStmt->fetch();

        if ($assignment) {
            $pdo->prepare("UPDATE orders SET status=?, updated_at=NOW() WHERE id=?")
                ->execute([$newStatus, $orderId]);

            // Update stage to match
            $stageMap = ['in_progress' => 3, 'staged' => 4, 'ready_for_dock' => 5];
            $pdo->prepare("UPDATE assignments SET stage_id=? WHERE id=?")
                ->execute([$stageMap[$newStatus], $assignment['id']]);

            logAudit($pdo, 'update_status', 'orders', $orderId, [
                'new_status' => $newStatus,
                'puller_id'  => $user['id'],
            ]);

            flashSet('success', 'Status updated to "' . statusLabel($newStatus) . '".');
        } else {
            flashSet('danger', 'You cannot update this order.');
        }
        header('Location: puller_queue.php');
        exit;
    }

    if ($action === 'complete' && $orderId) {
        $verifyStmt = $pdo->prepare(
            "SELECT a.id FROM assignments a
             WHERE a.order_id=? AND a.user_id=? AND a.status='active' LIMIT 1"
        );
        $verifyStmt->execute([$orderId, $user['id']]);
        $assignment = $verifyStmt->fetch();

        if ($assignment) {
            $pdo->prepare("UPDATE assignments SET status='completed', stage_id=6, checked_out_at=NOW() WHERE id=?")
                ->execute([$assignment['id']]);
            $pdo->prepare("UPDATE orders SET status='completed', updated_at=NOW() WHERE id=?")
                ->execute([$orderId]);
            logAudit($pdo, 'complete_order', 'orders', $orderId, ['puller_id' => $user['id']]);
            flashSet('success', 'Order marked as completed. Great work!');
        }
        header('Location: puller_queue.php');
        exit;
    }
}

// ── My active assignments ─────────────────────────────────
$myOrdersStmt = $pdo->prepare(
    "SELECT o.*, a.id AS assignment_id, a.notes, a.checked_in_at
     FROM orders o
     JOIN assignments a ON a.order_id = o.id AND a.user_id = ? AND a.status = 'active'
     WHERE o.status NOT IN ('completed', 'new')
     ORDER BY o.required_ship_date ASC"
);
$myOrdersStmt->execute([$user['id']]);
$myOrders = $myOrdersStmt->fetchAll();

// ── Available orders (new, filtered by dept if applicable) ─
$availableParams = ['new'];
$availableSQL    = "SELECT o.* FROM orders o
                    WHERE o.status = 'new'";

if ($user['department']) {
    // Show orders with no active assignment that match dept, plus unfiltered ones
    $availableSQL .= ' ORDER BY o.required_ship_date ASC';
} else {
    $availableSQL .= ' ORDER BY o.required_ship_date ASC';
}

$availableStmt = $pdo->query($availableSQL);
$available     = $availableStmt->fetchAll();

$pageTitle = 'My Queue';
include '../includes/header.php';
?>

<div class="container">

  <!-- ── My Assignments ── -->
  <div class="section-header">
    <h2 class="page-title">
      My Orders
      <span class="count-badge"><?= count($myOrders) ?></span>
    </h2>
  </div>

  <?php if (empty($myOrders)): ?>
    <div class="empty-state">You have no active assignments. Grab an order below!</div>
  <?php else: ?>
    <div class="order-cards">
      <?php foreach ($myOrders as $o):
          $urgClass = urgencyClass($o['required_ship_date']);
      ?>
      <div class="order-card order-card-mine <?= $urgClass ?>">
        <div class="order-card-head">
          <div>
            <a href="order_detail.php?id=<?= $o['id'] ?>" class="order-number">
              <?= e($o['order_number']) ?>
            </a>
            <div class="customer-name"><?= e($o['customer_name']) ?></div>
          </div>
          <span class="status-badge <?= statusClass($o['status']) ?>">
            <?= statusLabel($o['status']) ?>
          </span>
        </div>

        <div class="order-card-meta">
          <span>Ship: <strong><?= fmtDate($o['required_ship_date']) ?></strong></span>
          <span class="urgency-label <?= $urgClass ?>"><?= urgencyLabel($o['required_ship_date']) ?></span>
          <?php if ($o['notes']): ?>
            <span class="note-text">&#9998; <?= e($o['notes']) ?></span>
          <?php endif; ?>
        </div>

        <div class="order-card-actions">
          <a href="order_detail.php?id=<?= $o['id'] ?>" class="btn btn-outline btn-sm">View Details</a>

          <?php if ($o['status'] === 'assigned'): ?>
            <form method="POST" style="display:inline">
              <?= csrfField() ?>
              <input type="hidden" name="action"     value="update_status">
              <input type="hidden" name="order_id"   value="<?= $o['id'] ?>">
              <input type="hidden" name="new_status" value="in_progress">
              <button type="submit" class="btn btn-primary btn-sm">Start Pulling</button>
            </form>

          <?php elseif ($o['status'] === 'in_progress'): ?>
            <form method="POST" style="display:inline">
              <?= csrfField() ?>
              <input type="hidden" name="action"     value="update_status">
              <input type="hidden" name="order_id"   value="<?= $o['id'] ?>">
              <input type="hidden" name="new_status" value="staged">
              <button type="submit" class="btn btn-primary btn-sm">Mark Staged</button>
            </form>

          <?php elseif ($o['status'] === 'staged'): ?>
            <form method="POST" style="display:inline">
              <?= csrfField() ?>
              <input type="hidden" name="action"     value="update_status">
              <input type="hidden" name="order_id"   value="<?= $o['id'] ?>">
              <input type="hidden" name="new_status" value="ready_for_dock">
              <button type="submit" class="btn btn-primary btn-sm">Ready for Dock</button>
            </form>

          <?php elseif ($o['status'] === 'ready_for_dock'): ?>
            <form method="POST" style="display:inline"
                  onsubmit="return confirm('Mark this order as fully completed?')">
              <?= csrfField() ?>
              <input type="hidden" name="action"   value="complete">
              <input type="hidden" name="order_id" value="<?= $o['id'] ?>">
              <button type="submit" class="btn btn-success btn-sm">Complete</button>
            </form>
          <?php endif; ?>
        </div>
      </div>
      <?php endforeach; ?>
    </div>
  <?php endif; ?>

  <!-- ── Available Orders ── -->
  <div class="section-header" style="margin-top: 2rem;">
    <h2 class="page-title">
      Available Orders
      <span class="count-badge"><?= count($available) ?></span>
    </h2>
    <?php if ($user['department']): ?>
      <span class="dept-chip">Dept: <?= e(ucfirst($user['department'])) ?></span>
    <?php endif; ?>
  </div>

  <?php if (empty($available)): ?>
    <div class="empty-state">No orders available to claim right now.</div>
  <?php else: ?>
    <div class="order-cards">
      <?php foreach ($available as $o):
          $urgClass = urgencyClass($o['required_ship_date']);
      ?>
      <div class="order-card <?= $urgClass ?>">
        <div class="order-card-head">
          <div>
            <a href="order_detail.php?id=<?= $o['id'] ?>" class="order-number">
              <?= e($o['order_number']) ?>
            </a>
            <div class="customer-name"><?= e($o['customer_name']) ?></div>
          </div>
          <div class="urgency-label <?= $urgClass ?>"><?= urgencyLabel($o['required_ship_date']) ?></div>
        </div>

        <div class="order-card-meta">
          <span>Ship: <strong><?= fmtDate($o['required_ship_date']) ?></strong></span>
          <?php if ($o['customer_po']): ?>
            <span>PO: <?= e($o['customer_po']) ?></span>
          <?php endif; ?>
        </div>

        <div class="order-card-actions">
          <a href="order_detail.php?id=<?= $o['id'] ?>" class="btn btn-outline btn-sm">Preview</a>
          <form method="POST" style="display:inline">
            <?= csrfField() ?>
            <input type="hidden" name="action"   value="claim">
            <input type="hidden" name="order_id" value="<?= $o['id'] ?>">
            <button type="submit" class="btn btn-primary btn-sm">Claim Order</button>
          </form>
        </div>
      </div>
      <?php endforeach; ?>
    </div>
  <?php endif; ?>

</div><!-- /container -->

<?php include '../includes/footer.php'; ?>
