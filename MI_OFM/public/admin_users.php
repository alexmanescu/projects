<?php
// ─────────────────────────────────────────────────────────
//  Admin: User Management — create, edit, deactivate users
// ─────────────────────────────────────────────────────────

declare(strict_types=1);

require_once '../includes/auth.php';
require_once '../includes/functions.php';

requireLogin();
requireRole(['admin']);

$pdo  = getDb();
$user = currentUser();

$errors  = [];
$success = '';

// ── Determine mode ────────────────────────────────────────
$editId  = (int) ($_GET['edit'] ?? 0);
$editUser = null;

if ($editId) {
    $stmt = $pdo->prepare('SELECT * FROM users WHERE id=? LIMIT 1');
    $stmt->execute([$editId]);
    $editUser = $stmt->fetch();
    if (!$editUser) {
        $editId   = 0;
        $editUser = null;
    }
}

// ── Handle POST ───────────────────────────────────────────
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    if (!validateCsrf($_POST['csrf_token'] ?? '')) {
        $errors[] = 'Invalid request token.';
    } else {
        $action = $_POST['action'] ?? '';

        // Toggle active flag
        if ($action === 'toggle_active' && !empty($_POST['user_id'])) {
            $uid = (int) $_POST['user_id'];
            if ($uid === $user['id']) {
                flashSet('danger', 'You cannot deactivate your own account.');
            } else {
                $pdo->prepare('UPDATE users SET active = !active WHERE id=?')->execute([$uid]);
                flashSet('success', 'User account status updated.');
            }
            header('Location: admin_users.php');
            exit;
        }

        // Create or update user
        if (in_array($action, ['create', 'update'])) {
            $uname    = trim($_POST['username'] ?? '');
            $name     = trim($_POST['name'] ?? '');
            $role     = $_POST['role'] ?? '';
            $dept     = $_POST['department'] ?? '';
            $password = $_POST['password'] ?? '';

            // Validation
            if ($err = validateLength($uname, 3, 50, 'Username'))   $errors[] = $err;
            if ($err = validateLength($name,  2, 100, 'Full name'))  $errors[] = $err;
            if (!in_array($role, ['admin', 'supervisor', 'puller'])) $errors[] = 'Invalid role.';
            if (!preg_match('/^[a-z0-9_]+$/i', $uname))             $errors[] = 'Username may only contain letters, numbers, and underscores.';

            if ($action === 'create' || $password !== '') {
                if (mb_strlen($password) < 8) $errors[] = 'Password must be at least 8 characters.';
            }

            if (empty($errors)) {
                if ($action === 'create') {
                    // Check uniqueness
                    $chk = $pdo->prepare('SELECT id FROM users WHERE username=? LIMIT 1');
                    $chk->execute([$uname]);
                    if ($chk->fetchColumn()) {
                        $errors[] = 'Username already exists.';
                    } else {
                        $hash = password_hash($password, PASSWORD_BCRYPT, ['cost' => 12]);
                        $ins  = $pdo->prepare(
                            'INSERT INTO users (username, password_hash, name, role, department, active)
                             VALUES (?, ?, ?, ?, ?, 1)'
                        );
                        $ins->execute([$uname, $hash, $name, $role, $dept ?: null]);
                        logAudit($pdo, 'create_user', 'users', (int) $pdo->lastInsertId(), ['username' => $uname]);
                        flashSet('success', "User '$name' created successfully.");
                        header('Location: admin_users.php');
                        exit;
                    }
                } else {
                    // Update
                    $uid = (int) $_POST['user_id'];
                    if ($password !== '') {
                        $hash = password_hash($password, PASSWORD_BCRYPT, ['cost' => 12]);
                        $pdo->prepare(
                            'UPDATE users SET username=?, password_hash=?, name=?, role=?, department=? WHERE id=?'
                        )->execute([$uname, $hash, $name, $role, $dept ?: null, $uid]);
                    } else {
                        $pdo->prepare(
                            'UPDATE users SET username=?, name=?, role=?, department=? WHERE id=?'
                        )->execute([$uname, $name, $role, $dept ?: null, $uid]);
                    }
                    logAudit($pdo, 'update_user', 'users', $uid, ['updated_by' => $user['id']]);
                    flashSet('success', "User '$name' updated.");
                    header('Location: admin_users.php');
                    exit;
                }
            }
        }
    }
}

// ── Fetch all users ───────────────────────────────────────
$users = $pdo->query(
    'SELECT * FROM users ORDER BY role, name'
)->fetchAll();

$pageTitle = 'User Management';
include '../includes/header.php';
?>

<div class="container">

  <div class="page-header">
    <h2 class="page-title">User Management</h2>
    <?php if (!$editId): ?>
      <a href="?new=1" class="btn btn-primary btn-sm">+ New User</a>
    <?php endif; ?>
  </div>

  <!-- ── Create / Edit Form ── -->
  <?php if ($editId || isset($_GET['new'])): ?>
  <div class="form-card">
    <h3 class="form-card-title"><?= $editId ? 'Edit User' : 'New User' ?></h3>

    <?php foreach ($errors as $err): ?>
      <div class="alert alert-danger"><?= e($err) ?></div>
    <?php endforeach; ?>

    <form method="POST" action="admin_users.php<?= $editId ? "?edit=$editId" : '' ?>" novalidate>
      <?= csrfField() ?>
      <input type="hidden" name="action"  value="<?= $editId ? 'update' : 'create' ?>">
      <?php if ($editId): ?>
        <input type="hidden" name="user_id" value="<?= $editId ?>">
      <?php endif; ?>

      <div class="form-row">
        <div class="form-group">
          <label for="fu_username">Username</label>
          <input type="text" id="fu_username" name="username"
                 value="<?= e($editUser['username'] ?? $_POST['username'] ?? '') ?>"
                 class="form-control" required autocomplete="off">
        </div>
        <div class="form-group">
          <label for="fu_name">Full Name</label>
          <input type="text" id="fu_name" name="name"
                 value="<?= e($editUser['name'] ?? $_POST['name'] ?? '') ?>"
                 class="form-control" required>
        </div>
      </div>

      <div class="form-row">
        <div class="form-group">
          <label for="fu_role">Role</label>
          <select id="fu_role" name="role" class="form-control" required>
            <?php foreach (['admin', 'supervisor', 'puller'] as $r): ?>
              <option value="<?= $r ?>" <?= ($editUser['role'] ?? $_POST['role'] ?? '') === $r ? 'selected' : '' ?>>
                <?= ucfirst($r) ?>
              </option>
            <?php endforeach; ?>
          </select>
        </div>
        <div class="form-group">
          <label for="fu_dept">Department <span class="text-muted">(pullers only)</span></label>
          <select id="fu_dept" name="department" class="form-control">
            <option value="">— None —</option>
            <option value="inside" <?= ($editUser['department'] ?? $_POST['department'] ?? '') === 'inside' ? 'selected' : '' ?>>Inside</option>
            <option value="yard"   <?= ($editUser['department'] ?? $_POST['department'] ?? '') === 'yard'   ? 'selected' : '' ?>>Yard</option>
          </select>
        </div>
      </div>

      <div class="form-group">
        <label for="fu_password">
          Password <?= $editId ? '<span class="text-muted">(leave blank to keep current)</span>' : '' ?>
        </label>
        <input type="password" id="fu_password" name="password"
               autocomplete="new-password"
               class="form-control"
               <?= $editId ? '' : 'required' ?>
               minlength="8"
               placeholder="Minimum 8 characters">
      </div>

      <div class="form-actions">
        <a href="admin_users.php" class="btn btn-outline">Cancel</a>
        <button type="submit" class="btn btn-primary"><?= $editId ? 'Save Changes' : 'Create User' ?></button>
      </div>
    </form>
  </div>
  <?php endif; ?>

  <!-- ── Users Table ── -->
  <div class="table-wrap">
    <table class="data-table">
      <thead>
        <tr>
          <th>Name</th>
          <th>Username</th>
          <th>Role</th>
          <th>Dept</th>
          <th>Status</th>
          <th>Created</th>
          <th class="col-actions">Actions</th>
        </tr>
      </thead>
      <tbody>
        <?php foreach ($users as $u): ?>
        <tr class="<?= !$u['active'] ? 'row-inactive' : '' ?>">
          <td><?= e($u['name']) ?></td>
          <td class="mono"><?= e($u['username']) ?></td>
          <td><span class="role-chip role-<?= e($u['role']) ?>"><?= ucfirst(e($u['role'])) ?></span></td>
          <td><?= $u['department'] ? ucfirst(e($u['department'])) : '—' ?></td>
          <td>
            <span class="status-badge <?= $u['active'] ? 'status-staged' : 'status-completed' ?>">
              <?= $u['active'] ? 'Active' : 'Inactive' ?>
            </span>
          </td>
          <td class="text-muted"><?= fmtDate($u['created_at']) ?></td>
          <td class="col-actions">
            <a href="?edit=<?= $u['id'] ?>" class="btn btn-outline btn-xs">Edit</a>
            <?php if ($u['id'] !== $user['id']): ?>
              <form method="POST" style="display:inline">
                <?= csrfField() ?>
                <input type="hidden" name="action"  value="toggle_active">
                <input type="hidden" name="user_id" value="<?= $u['id'] ?>">
                <button type="submit" class="btn <?= $u['active'] ? 'btn-danger' : 'btn-outline' ?> btn-xs">
                  <?= $u['active'] ? 'Deactivate' : 'Reactivate' ?>
                </button>
              </form>
            <?php endif; ?>
          </td>
        </tr>
        <?php endforeach; ?>
      </tbody>
    </table>
  </div>

</div><!-- /container -->

<?php include '../includes/footer.php'; ?>
