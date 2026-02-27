<?php
// ── Shared page header — included at the top of every public page ──
// Expects $pageTitle (string) to be set before inclusion.
// Expects auth.php + functions.php to already be included.
$user  = currentUser();
$flash = flashGet();
$title = ($pageTitle ?? 'Dashboard') . ' — ' . APP_NAME;
?>
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title><?= e($title) ?></title>
  <link rel="stylesheet" href="../assets/css/style.css">
  <meta name="robots" content="noindex,nofollow">
</head>
<body>

<nav class="topnav">
  <div class="topnav-inner">
    <a class="nav-brand" href="dashboard.php">
      <span class="nav-brand-icon">&#9783;</span>
      <?= e(APP_NAME) ?>
    </a>

    <button class="nav-toggle" id="navToggle" aria-label="Menu">&#9776;</button>

    <ul class="nav-links" id="navLinks">
      <?php if (in_array($user['role'], ['supervisor', 'admin'])): ?>
        <li><a href="dashboard.php"<?= str_ends_with($_SERVER['PHP_SELF'], 'dashboard.php')   ? ' class="active"' : '' ?>>Dashboard</a></li>
        <li><a href="admin_orders.php"<?= str_ends_with($_SERVER['PHP_SELF'], 'admin_orders.php') ? ' class="active"' : '' ?>>Orders</a></li>
      <?php endif; ?>

      <?php if ($user['role'] === 'puller'): ?>
        <li><a href="puller_queue.php"<?= str_ends_with($_SERVER['PHP_SELF'], 'puller_queue.php') ? ' class="active"' : '' ?>>My Queue</a></li>
      <?php endif; ?>

      <?php if ($user['role'] === 'admin'): ?>
        <li><a href="admin_users.php"<?= str_ends_with($_SERVER['PHP_SELF'], 'admin_users.php') ? ' class="active"' : '' ?>>Users</a></li>
      <?php endif; ?>
    </ul>

    <div class="nav-user">
      <span class="nav-username"><?= e($user['name']) ?></span>
      <span class="role-chip role-<?= e($user['role']) ?>"><?= e(ucfirst($user['role'])) ?></span>
      <a href="logout.php" class="btn-logout">Sign out</a>
    </div>
  </div>
</nav>

<?php if ($flash): ?>
<div class="flash flash-<?= e($flash['type']) ?>" role="alert">
  <?= e($flash['message']) ?>
  <button class="flash-close" onclick="this.parentElement.remove()">&#10005;</button>
</div>
<?php endif; ?>

<main class="main-content">
