<?php
// ─────────────────────────────────────────────────────────
//  Authentication helpers — session management, CSRF,
//  role-based access control.
// ─────────────────────────────────────────────────────────

declare(strict_types=1);

require_once __DIR__ . '/db.php';

// ── Start a secure session ────────────────────────────────
function startSecureSession(): void {
    if (session_status() !== PHP_SESSION_NONE) {
        return;
    }
    $lifetime = defined('SESSION_LIFETIME') ? (int) SESSION_LIFETIME : 28800;

    ini_set('session.cookie_httponly',  '1');
    ini_set('session.cookie_samesite',  'Strict');
    ini_set('session.use_strict_mode',  '1');
    ini_set('session.gc_maxlifetime',   (string) $lifetime);
    ini_set('session.cookie_lifetime',  '0');        // expire on browser close

    if (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') {
        ini_set('session.cookie_secure', '1');
    }

    session_start();

    // Expire idle sessions
    if (isset($_SESSION['last_activity']) && (time() - $_SESSION['last_activity']) > $lifetime) {
        session_unset();
        session_destroy();
        session_start();
    }
    $_SESSION['last_activity'] = time();
}

// ── Require authenticated session ────────────────────────
function requireLogin(): void {
    startSecureSession();
    if (empty($_SESSION['user_id'])) {
        header('Location: index.php?timeout=1');
        exit;
    }
}

// ── Require specific role(s) — call after requireLogin() ─
function requireRole(array $roles): void {
    if (!in_array($_SESSION['user_role'] ?? '', $roles, true)) {
        http_response_code(403);
        include __DIR__ . '/header.php';
        echo '<div class="container"><div class="alert alert-danger">Access denied. You do not have permission to view this page.</div></div>';
        include __DIR__ . '/footer.php';
        exit;
    }
}

// ── Return current user array from session ────────────────
function currentUser(): array {
    return [
        'id'         => (int) ($_SESSION['user_id']         ?? 0),
        'username'   => (string) ($_SESSION['user_username'] ?? ''),
        'name'       => (string) ($_SESSION['user_name']     ?? ''),
        'role'       => (string) ($_SESSION['user_role']     ?? ''),
        'department' => (string) ($_SESSION['user_department'] ?? ''),
    ];
}

// ── Authenticate username/password, populate session ─────
function attemptLogin(string $username, string $password): bool {
    $pdo  = getDb();
    $stmt = $pdo->prepare(
        'SELECT id, username, password_hash, name, role, department, active
         FROM users WHERE username = ? LIMIT 1'
    );
    $stmt->execute([trim($username)]);
    $user = $stmt->fetch();

    if (!$user || !$user['active'] || !password_verify($password, $user['password_hash'])) {
        return false;
    }

    // Regenerate ID to prevent session fixation
    session_regenerate_id(true);

    $_SESSION['user_id']         = $user['id'];
    $_SESSION['user_username']   = $user['username'];
    $_SESSION['user_name']       = $user['name'];
    $_SESSION['user_role']       = $user['role'];
    $_SESSION['user_department'] = $user['department'];
    $_SESSION['last_activity']   = time();

    return true;
}

// ── Destroy session and redirect to login ─────────────────
function doLogout(): void {
    startSecureSession();
    session_unset();
    session_destroy();
    header('Location: index.php');
    exit;
}

// ── CSRF helpers ──────────────────────────────────────────
function csrfToken(): string {
    startSecureSession();
    if (empty($_SESSION['csrf_token'])) {
        $_SESSION['csrf_token'] = bin2hex(random_bytes(32));
    }
    return $_SESSION['csrf_token'];
}

function validateCsrf(string $token): bool {
    return !empty($_SESSION['csrf_token'])
        && hash_equals($_SESSION['csrf_token'], $token);
}

// ── Output a hidden CSRF field for use in forms ───────────
function csrfField(): string {
    return '<input type="hidden" name="csrf_token" value="' . htmlspecialchars(csrfToken()) . '">';
}
