<?php
// ─────────────────────────────────────────────────────────
//  Admin: Order Management — create and edit orders
// ─────────────────────────────────────────────────────────

declare(strict_types=1);

require_once '../includes/auth.php';
require_once '../includes/functions.php';

requireLogin();
requireRole(['admin', 'supervisor']);

$pdo  = getDb();
$user = currentUser();

$errors  = [];
$editId  = (int) ($_GET['id'] ?? 0);
$isNew   = isset($_GET['action']) && $_GET['action'] === 'new';
$editOrder = null;
$editLines = [];

if ($editId) {
    $stmt = $pdo->prepare('SELECT * FROM orders WHERE id=? LIMIT 1');
    $stmt->execute([$editId]);
    $editOrder = $stmt->fetch();
    if ($editOrder) {
        $lineStmt = $pdo->prepare('SELECT * FROM order_lines WHERE order_id=? ORDER BY id');
        $lineStmt->execute([$editId]);
        $editLines = $lineStmt->fetchAll();
    }
}

// ── Handle POST ───────────────────────────────────────────
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    if (!validateCsrf($_POST['csrf_token'] ?? '')) {
        $errors[] = 'Invalid request token.';
    } else {
        $action = $_POST['action'] ?? '';

        if (in_array($action, ['create_order', 'update_order'])) {
            $orderNum  = trim($_POST['order_number'] ?? '');
            $custName  = trim($_POST['customer_name'] ?? '');
            $custPo    = trim($_POST['customer_po'] ?? '');
            $orderDate = $_POST['order_date'] ?? '';
            $shipDate  = $_POST['required_ship_date'] ?? '';

            if ($err = validateLength($orderNum, 1, 50, 'Order number')) $errors[] = $err;
            if ($err = validateLength($custName, 1, 150, 'Customer name')) $errors[] = $err;
            if (!$orderDate || !strtotime($orderDate)) $errors[] = 'Valid order date required.';
            if (!$shipDate  || !strtotime($shipDate))  $errors[] = 'Valid ship date required.';

            // Line items
            $itemCodes  = $_POST['item_code']    ?? [];
            $descs      = $_POST['description']  ?? [];
            $qtys       = $_POST['qty_ordered']  ?? [];
            $uoms       = $_POST['uom']          ?? [];

            $validLines = [];
            foreach ($itemCodes as $i => $code) {
                $code = trim($code);
                $qty  = (float) ($qtys[$i] ?? 0);
                if ($code && $qty > 0) {
                    $validLines[] = [
                        'item_code'   => $code,
                        'description' => trim($descs[$i] ?? ''),
                        'qty_ordered' => $qty,
                        'uom'         => trim($uoms[$i] ?? ''),
                    ];
                }
            }

            if (empty($validLines)) $errors[] = 'At least one valid line item is required.';

            if (empty($errors)) {
                if ($action === 'create_order') {
                    // Check order number uniqueness
                    $chk = $pdo->prepare('SELECT id FROM orders WHERE order_number=? LIMIT 1');
                    $chk->execute([$orderNum]);
                    if ($chk->fetchColumn()) {
                        $errors[] = 'Order number already exists.';
                    } else {
                        $ins = $pdo->prepare(
                            'INSERT INTO orders (order_number, customer_name, customer_po, order_date, required_ship_date, status)
                             VALUES (?, ?, ?, ?, ?, "new")'
                        );
                        $ins->execute([$orderNum, $custName, $custPo ?: null, $orderDate, $shipDate]);
                        $newId = (int) $pdo->lastInsertId();

                        $lineIns = $pdo->prepare(
                            'INSERT INTO order_lines (order_id, item_code, description, qty_ordered, uom) VALUES (?,?,?,?,?)'
                        );
                        foreach ($validLines as $line) {
                            $lineIns->execute([$newId, $line['item_code'], $line['description'], $line['qty_ordered'], $line['uom']]);
                        }

                        logAudit($pdo, 'create_order', 'orders', $newId, ['order_number' => $orderNum]);
                        flashSet('success', "Order $orderNum created successfully.");
                        header("Location: order_detail.php?id=$newId");
                        exit;
                    }
                } else {
                    // Update existing order (admin only)
                    if ($user['role'] !== 'admin') {
                        flashSet('danger', 'Only admins can edit orders.');
                        header('Location: admin_orders.php');
                        exit;
                    }
                    $uid = (int) $_POST['order_id'];
                    $pdo->prepare(
                        'UPDATE orders SET order_number=?, customer_name=?, customer_po=?, order_date=?, required_ship_date=?, updated_at=NOW() WHERE id=?'
                    )->execute([$orderNum, $custName, $custPo ?: null, $orderDate, $shipDate, $uid]);

                    // Rebuild lines
                    $pdo->prepare('DELETE FROM order_lines WHERE order_id=?')->execute([$uid]);
                    $lineIns = $pdo->prepare(
                        'INSERT INTO order_lines (order_id, item_code, description, qty_ordered, uom) VALUES (?,?,?,?,?)'
                    );
                    foreach ($validLines as $line) {
                        $lineIns->execute([$uid, $line['item_code'], $line['description'], $line['qty_ordered'], $line['uom']]);
                    }

                    logAudit($pdo, 'update_order', 'orders', $uid, ['updated_by' => $user['id']]);
                    flashSet('success', "Order $orderNum updated.");
                    header("Location: order_detail.php?id=$uid");
                    exit;
                }
            }
        }
    }
}

// ── Fetch all orders ──────────────────────────────────────
$allOrders = getOrdersWithAssignment($pdo);

$pageTitle = 'Order Management';
include '../includes/header.php';
?>

<div class="container">

  <div class="page-header">
    <h2 class="page-title">Orders</h2>
    <?php if ($user['role'] === 'admin'): ?>
      <a href="?action=new" class="btn btn-primary btn-sm">+ New Order</a>
    <?php endif; ?>
  </div>

  <!-- ── Create / Edit Form ── -->
  <?php if ($isNew || $editId): ?>
  <div class="form-card">
    <h3 class="form-card-title"><?= $editId ? 'Edit Order' : 'New Order' ?></h3>

    <?php foreach ($errors as $err): ?>
      <div class="alert alert-danger"><?= e($err) ?></div>
    <?php endforeach; ?>

    <form method="POST" action="admin_orders.php<?= $editId ? "?id=$editId" : '' ?>" id="orderForm" novalidate>
      <?= csrfField() ?>
      <input type="hidden" name="action" value="<?= $editId ? 'update_order' : 'create_order' ?>">
      <?php if ($editId): ?><input type="hidden" name="order_id" value="<?= $editId ?>"><?php endif; ?>

      <div class="form-row">
        <div class="form-group">
          <label for="order_number">Order Number</label>
          <input type="text" id="order_number" name="order_number"
                 value="<?= e($editOrder['order_number'] ?? $_POST['order_number'] ?? '') ?>"
                 class="form-control mono" required placeholder="e.g. ORD-10050">
        </div>
        <div class="form-group">
          <label for="customer_name">Customer Name</label>
          <input type="text" id="customer_name" name="customer_name"
                 value="<?= e($editOrder['customer_name'] ?? $_POST['customer_name'] ?? '') ?>"
                 class="form-control" required>
        </div>
      </div>

      <div class="form-row">
        <div class="form-group">
          <label for="customer_po">Customer PO <span class="text-muted">(optional)</span></label>
          <input type="text" id="customer_po" name="customer_po"
                 value="<?= e($editOrder['customer_po'] ?? $_POST['customer_po'] ?? '') ?>"
                 class="form-control">
        </div>
        <div class="form-group">
          <label for="order_date">Order Date</label>
          <input type="date" id="order_date" name="order_date"
                 value="<?= e($editOrder['order_date'] ?? $_POST['order_date'] ?? date('Y-m-d')) ?>"
                 class="form-control" required>
        </div>
        <div class="form-group">
          <label for="required_ship_date">Required Ship Date</label>
          <input type="date" id="required_ship_date" name="required_ship_date"
                 value="<?= e($editOrder['required_ship_date'] ?? $_POST['required_ship_date'] ?? '') ?>"
                 class="form-control" required>
        </div>
      </div>

      <!-- ── Line Items ── -->
      <div class="section-header" style="margin-top:1.5rem">
        <h4 class="section-title">Line Items</h4>
        <button type="button" class="btn btn-outline btn-sm" id="addLineBtn">+ Add Line</button>
      </div>

      <div class="table-wrap">
        <table class="data-table" id="linesTable">
          <thead>
            <tr>
              <th>Item Code</th>
              <th>Description</th>
              <th class="col-num">Qty</th>
              <th class="col-num">UOM</th>
              <th class="col-actions"></th>
            </tr>
          </thead>
          <tbody id="lineRows">
            <?php
            $seedLines = $editLines ?: [['item_code' => '', 'description' => '', 'qty_ordered' => '', 'uom' => '']];
            foreach ($seedLines as $i => $line): ?>
            <tr class="line-row">
              <td><input type="text"   name="item_code[]"   value="<?= e($line['item_code']) ?>"   class="form-control mono"  placeholder="ITEM-CODE" required></td>
              <td><input type="text"   name="description[]" value="<?= e($line['description'] ?? '') ?>" class="form-control" placeholder="Description"></td>
              <td><input type="number" name="qty_ordered[]" value="<?= e((string)($line['qty_ordered'] ?? '')) ?>" class="form-control col-num" min="0.01" step="1" required></td>
              <td><input type="text"   name="uom[]"         value="<?= e($line['uom'] ?? '') ?>"   class="form-control" style="width:5rem" placeholder="EA"></td>
              <td><button type="button" class="btn btn-danger btn-xs remove-line">&#10005;</button></td>
            </tr>
            <?php endforeach; ?>
          </tbody>
        </table>
      </div>

      <div class="form-actions" style="margin-top:1rem">
        <a href="admin_orders.php" class="btn btn-outline">Cancel</a>
        <button type="submit" class="btn btn-primary"><?= $editId ? 'Save Changes' : 'Create Order' ?></button>
      </div>
    </form>
  </div>
  <?php endif; ?>

  <!-- ── Orders Table ── -->
  <div class="table-wrap">
    <table class="data-table">
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
        <?php foreach ($allOrders as $o):
            $urgClass = $o['status'] !== 'completed' ? urgencyClass($o['required_ship_date']) : '';
        ?>
        <tr class="<?= $urgClass ?>">
          <td><a href="order_detail.php?id=<?= $o['id'] ?>" class="order-link"><?= e($o['order_number']) ?></a></td>
          <td><?= e($o['customer_name']) ?></td>
          <td class="nowrap">
            <?= fmtDate($o['required_ship_date']) ?>
            <?php if ($o['status'] !== 'completed'): ?>
              <span class="urgency-label <?= urgencyClass($o['required_ship_date']) ?>"><?= urgencyLabel($o['required_ship_date']) ?></span>
            <?php endif; ?>
          </td>
          <td><span class="status-badge <?= statusClass($o['status']) ?>"><?= statusLabel($o['status']) ?></span></td>
          <td><?= $o['assigned_to_name'] ? e($o['assigned_to_name']) : '<span class="text-muted">—</span>' ?></td>
          <td class="col-actions">
            <a href="order_detail.php?id=<?= $o['id'] ?>" class="btn btn-outline btn-xs">View</a>
            <?php if ($user['role'] === 'admin' && $o['status'] === 'new'): ?>
              <a href="admin_orders.php?id=<?= $o['id'] ?>" class="btn btn-outline btn-xs">Edit</a>
            <?php endif; ?>
          </td>
        </tr>
        <?php endforeach; ?>
      </tbody>
    </table>
  </div>

</div><!-- /container -->

<?php include '../includes/footer.php'; ?>
