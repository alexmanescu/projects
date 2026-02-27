<?php
// ─────────────────────────────────────────────────────────
//  Login page — MI Order Fulfillment Manager
// ─────────────────────────────────────────────────────────

declare(strict_types=1);

require_once '../includes/auth.php';
require_once '../includes/functions.php';

startSecureSession();

// Already logged in — redirect to appropriate home page
if (!empty($_SESSION['user_id'])) {
    $role = $_SESSION['user_role'] ?? '';
    header('Location: ' . ($role === 'puller' ? 'puller_queue.php' : 'dashboard.php'));
    exit;
}

$errors = [];

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    // Validate CSRF
    if (!validateCsrf($_POST['csrf_token'] ?? '')) {
        $errors[] = 'Invalid request. Please try again.';
    } else {
        $username = trim($_POST['username'] ?? '');
        $password = $_POST['password'] ?? '';

        if ($username === '' || $password === '') {
            $errors[] = 'Username and password are required.';
        } elseif (!attemptLogin($username, $password)) {
            $errors[] = 'Invalid username or password.';
        } else {
            // Successful login — redirect by role
            $role = $_SESSION['user_role'];
            header('Location: ' . ($role === 'puller' ? 'puller_queue.php' : 'dashboard.php'));
            exit;
        }
    }
}

$csrfToken = csrfToken();
$timeout   = !empty($_GET['timeout']);
?>
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Sign In — <?= e(APP_NAME) ?></title>
  <link rel="stylesheet" href="../assets/css/style.css">
  <meta name="robots" content="noindex,nofollow">
</head>
<body class="login-body">

<div class="login-wrap">
  <div class="login-card">

    <div class="login-header">
      <div class="login-icon">&#9783;</div>
      <h1 class="login-title"><?= e(APP_NAME) ?></h1>
      <p class="login-sub">Order Fulfillment Management</p>
    </div>

    <?php if ($timeout): ?>
      <div class="alert alert-warning">Your session expired. Please sign in again.</div>
    <?php endif; ?>

    <?php foreach ($errors as $err): ?>
      <div class="alert alert-danger"><?= e($err) ?></div>
    <?php endforeach; ?>

    <form method="POST" action="index.php" class="login-form" novalidate>
      <?= csrfField() ?>

      <div class="form-group">
        <label for="username">Username</label>
        <input
          type="text"
          id="username"
          name="username"
          value="<?= e($_POST['username'] ?? '') ?>"
          autocomplete="username"
          autofocus
          required
          class="form-control form-control-lg"
          placeholder="Enter username"
        >
      </div>

      <div class="form-group">
        <label for="password">Password</label>
        <input
          type="password"
          id="password"
          name="password"
          autocomplete="current-password"
          required
          class="form-control form-control-lg"
          placeholder="Enter password"
        >
      </div>

      <button type="submit" class="btn btn-primary btn-full btn-lg">
        Sign In
      </button>
    </form>

  </div>
</div>

<script src="../assets/js/app.js"></script>
</body>
</html>
