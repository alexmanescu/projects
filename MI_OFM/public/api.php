<?php
// ─────────────────────────────────────────────────────────
//  AJAX API — lightweight JSON endpoint for live updates.
//  All requests require an active session + CSRF token.
// ─────────────────────────────────────────────────────────

declare(strict_types=1);

require_once '../includes/auth.php';
require_once '../includes/functions.php';

startSecureSession();
header('Content-Type: application/json');

// Must be logged in
if (empty($_SESSION['user_id'])) {
    http_response_code(401);
    echo json_encode(['error' => 'Unauthenticated']);
    exit;
}

// CSRF must be valid on all mutating requests
$method = $_SERVER['REQUEST_METHOD'];
$pdo    = getDb();
$user   = currentUser();

// ── Parse action from query string or POST body ───────────
$action = $_GET['action'] ?? $_POST['action'] ?? '';

// ── GET: fetch orders summary for dashboard auto-refresh ──
if ($method === 'GET' && $action === 'orders_summary') {
    requireRole(['supervisor', 'admin']);

    $orders = getOrdersWithAssignment($pdo, ['exclude_completed' => true]);

    $data = array_map(fn($o) => [
        'id'           => $o['id'],
        'order_number' => $o['order_number'],
        'customer'     => $o['customer_name'],
        'ship_date'    => $o['required_ship_date'],
        'status'       => $o['status'],
        'status_label' => statusLabel($o['status']),
        'assigned_to'  => $o['assigned_to_name'],
        'urgency'      => urgencyClass($o['required_ship_date']),
        'urgency_label'=> urgencyLabel($o['required_ship_date']),
    ], $orders);

    echo json_encode(['orders' => $data, 'ts' => time()]);
    exit;
}

// ── POST: claim an order ──────────────────────────────────
if ($method === 'POST' && $action === 'claim') {
    if (!in_array($user['role'], ['puller'], true)) {
        http_response_code(403);
        echo json_encode(['error' => 'Forbidden']);
        exit;
    }
    if (!validateCsrf($_POST['csrf_token'] ?? '')) {
        http_response_code(403);
        echo json_encode(['error' => 'Invalid CSRF token']);
        exit;
    }

    $orderId = (int) ($_POST['order_id'] ?? 0);
    $chk = $pdo->prepare("SELECT id FROM orders WHERE id=? AND status='new' LIMIT 1");
    $chk->execute([$orderId]);

    if (!$chk->fetchColumn()) {
        echo json_encode(['success' => false, 'error' => 'Order not available']);
        exit;
    }

    $ins = $pdo->prepare(
        'INSERT INTO assignments (order_id, user_id, stage_id, department, checked_in_at, status)
         VALUES (?, ?, 2, ?, NOW(), "active")'
    );
    $ins->execute([$orderId, $user['id'], $user['department'] ?: null]);
    $pdo->prepare("UPDATE orders SET status='assigned', updated_at=NOW() WHERE id=?")->execute([$orderId]);
    logAudit($pdo, 'claim_order', 'orders', $orderId, ['puller_id' => $user['id']]);

    echo json_encode(['success' => true]);
    exit;
}

// ── POST: update order status ─────────────────────────────
if ($method === 'POST' && $action === 'update_status') {
    if (!validateCsrf($_POST['csrf_token'] ?? '')) {
        http_response_code(403);
        echo json_encode(['error' => 'Invalid CSRF token']);
        exit;
    }

    $orderId   = (int) ($_POST['order_id'] ?? 0);
    $newStatus = $_POST['new_status'] ?? '';
    $allowed   = ['in_progress', 'staged', 'ready_for_dock', 'completed'];

    if (!in_array($newStatus, $allowed, true)) {
        echo json_encode(['success' => false, 'error' => 'Invalid status']);
        exit;
    }

    // Pullers can only update their own assignments
    if ($user['role'] === 'puller') {
        $verify = $pdo->prepare(
            "SELECT id FROM assignments WHERE order_id=? AND user_id=? AND status='active' LIMIT 1"
        );
        $verify->execute([$orderId, $user['id']]);
        if (!$verify->fetchColumn()) {
            echo json_encode(['success' => false, 'error' => 'Not your order']);
            exit;
        }
    }

    $pdo->prepare("UPDATE orders SET status=?, updated_at=NOW() WHERE id=?")->execute([$newStatus, $orderId]);

    if ($newStatus === 'completed') {
        $pdo->prepare("UPDATE assignments SET status='completed', checked_out_at=NOW(), stage_id=6 WHERE order_id=? AND status='active'")
            ->execute([$orderId]);
    } else {
        $stageMap = ['in_progress' => 3, 'staged' => 4, 'ready_for_dock' => 5];
        if (isset($stageMap[$newStatus])) {
            $pdo->prepare("UPDATE assignments SET stage_id=? WHERE order_id=? AND status='active'")
                ->execute([$stageMap[$newStatus], $orderId]);
        }
    }

    logAudit($pdo, 'update_status', 'orders', $orderId, ['new_status' => $newStatus, 'by' => $user['id']]);
    echo json_encode(['success' => true, 'new_status' => $newStatus]);
    exit;
}

// Unrecognized action
http_response_code(400);
echo json_encode(['error' => 'Unknown action']);
