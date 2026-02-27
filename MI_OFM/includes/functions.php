<?php
// ─────────────────────────────────────────────────────────
//  Utility functions — shared across all pages.
// ─────────────────────────────────────────────────────────

declare(strict_types=1);

// ── Audit logging ─────────────────────────────────────────
function logAudit(PDO $pdo, string $action, string $entityType = '', int $entityId = 0, array $details = []): void {
    $userId = (int) ($_SESSION['user_id'] ?? 0) ?: null;
    $ip     = $_SERVER['REMOTE_ADDR'] ?? null;

    $stmt = $pdo->prepare(
        'INSERT INTO audit_log (user_id, action, entity_type, entity_id, details, ip_address)
         VALUES (?, ?, ?, ?, ?, ?)'
    );
    $stmt->execute([
        $userId,
        $action,
        $entityType ?: null,
        $entityId   ?: null,
        $details ? json_encode($details) : null,
        $ip,
    ]);
}

// ── Order status helpers ──────────────────────────────────
function statusLabel(string $status): string {
    return match ($status) {
        'new'           => 'New',
        'assigned'      => 'Assigned',
        'in_progress'   => 'In Progress',
        'staged'        => 'Staged',
        'ready_for_dock'=> 'Ready for Dock',
        'completed'     => 'Completed',
        default         => ucfirst(str_replace('_', ' ', $status)),
    };
}

function statusClass(string $status): string {
    return match ($status) {
        'new'            => 'status-new',
        'assigned'       => 'status-assigned',
        'in_progress'    => 'status-in-progress',
        'staged'         => 'status-staged',
        'ready_for_dock' => 'status-dock',
        'completed'      => 'status-completed',
        default          => 'status-new',
    };
}

// ── Urgency helpers ───────────────────────────────────────
function daysUntilShip(string $dateStr): int {
    $today = new DateTimeImmutable('today');
    $ship  = new DateTimeImmutable($dateStr);
    return (int) $today->diff($ship)->days * ($ship >= $today ? 1 : -1);
}

function urgencyClass(string $dateStr): string {
    $days = daysUntilShip($dateStr);
    if ($days < 0)  return 'urgency-overdue';
    if ($days <= 1) return 'urgency-critical';
    if ($days <= 3) return 'urgency-high';
    if ($days <= 7) return 'urgency-medium';
    return '';
}

function urgencyLabel(string $dateStr): string {
    $days = daysUntilShip($dateStr);
    if ($days < 0)  return 'OVERDUE ' . abs($days) . 'd';
    if ($days === 0) return 'SHIPS TODAY';
    if ($days === 1) return 'SHIPS TOMORROW';
    return 'in ' . $days . ' days';
}

// ── Date formatting ───────────────────────────────────────
function fmtDate(string $dateStr): string {
    return date('M j, Y', strtotime($dateStr));
}

function fmtDateTime(string $dateStr): string {
    return date('M j, Y g:ia', strtotime($dateStr));
}

// ── HTML escaping shorthand ───────────────────────────────
function e(string $val): string {
    return htmlspecialchars($val, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

// ── Flash message helpers ─────────────────────────────────
function flashSet(string $type, string $message): void {
    $_SESSION['flash'] = ['type' => $type, 'message' => $message];
}

function flashGet(): ?array {
    if (!empty($_SESSION['flash'])) {
        $flash = $_SESSION['flash'];
        unset($_SESSION['flash']);
        return $flash;
    }
    return null;
}

// ── Fetch active pullers for assignment dropdowns ─────────
function getPullers(PDO $pdo, ?string $dept = null): array {
    if ($dept) {
        $stmt = $pdo->prepare(
            'SELECT id, name, department FROM users
             WHERE role = "puller" AND active = 1 AND (department = ? OR department IS NULL)
             ORDER BY name'
        );
        $stmt->execute([$dept]);
    } else {
        $stmt = $pdo->query(
            'SELECT id, name, department FROM users
             WHERE role = "puller" AND active = 1 ORDER BY name'
        );
    }
    return $stmt->fetchAll();
}

// ── Fetch open orders with current assignment info ────────
function getOrdersWithAssignment(PDO $pdo, array $filters = []): array {
    $where  = ['1=1'];
    $params = [];

    if (!empty($filters['status'])) {
        $where[]  = 'o.status = ?';
        $params[] = $filters['status'];
    }
    if (!empty($filters['department'])) {
        $where[]  = 'a.department = ?';
        $params[] = $filters['department'];
    }
    if (isset($filters['exclude_completed']) && $filters['exclude_completed']) {
        $where[] = "o.status != 'completed'";
    }

    $sql = "
        SELECT o.*,
               a.id          AS assignment_id,
               a.user_id     AS assigned_user_id,
               a.status      AS assignment_status,
               a.checked_in_at,
               u.name        AS assigned_to_name,
               a.department  AS assigned_dept,
               a.notes
        FROM orders o
        LEFT JOIN assignments a ON a.order_id = o.id AND a.status = 'active'
        LEFT JOIN users u ON u.id = a.user_id
        WHERE " . implode(' AND ', $where) . "
        ORDER BY o.required_ship_date ASC, o.id ASC
    ";

    $stmt = $pdo->prepare($sql);
    $stmt->execute($params);
    return $stmt->fetchAll();
}

// ── Validate input length ─────────────────────────────────
function validateLength(string $value, int $min, int $max, string $field): ?string {
    $len = mb_strlen(trim($value));
    if ($len < $min) return "$field must be at least $min characters.";
    if ($len > $max) return "$field must not exceed $max characters.";
    return null;
}
