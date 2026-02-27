<?php
/**
 * MI_Barcode — Label Profile Manager
 * CRUD for label_profiles: add, edit, delete label size/layout configurations.
 */

declare(strict_types=1);

require_once dirname(__DIR__) . '/config/config.php';
require_once APP_ROOT . '/includes/db.php';
require_once APP_ROOT . '/includes/functions.php';

$success = null;
$error   = null;
$editRow = null;

// ── Handle POST actions ───────────────────────────────────────────────────────
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $action = $_POST['action'] ?? '';

    if ($action === 'add' || $action === 'edit') {
        $fields = collectProfileFields();
        $validationError = validateProfileFields($fields);

        if ($validationError) {
            $error = $validationError;
            // Keep the form populated for correction.
            $editRow = ($action === 'edit')
                ? array_merge(['id' => (int)($_POST['id'] ?? 0)], $fields)
                : $fields;
        } else {
            try {
                if ($action === 'add') {
                    insertProfile($fields);
                    $success = 'Profile "' . e($fields['profile_name']) . '" added.';
                } else {
                    $id = (int)($_POST['id'] ?? 0);
                    updateProfile($id, $fields);
                    $success = 'Profile "' . e($fields['profile_name']) . '" updated.';
                }
            } catch (PDOException $ex) {
                $error = 'Database error: ' . e($ex->getMessage());
            }
        }

    } elseif ($action === 'delete') {
        $id = (int)($_POST['id'] ?? 0);
        if ($id > 0) {
            try {
                deleteProfile($id);
                $success = 'Profile deleted.';
            } catch (PDOException $ex) {
                $error = 'Could not delete profile: ' . e($ex->getMessage());
            }
        }
    }
}

// ── Load edit target from query string ────────────────────────────────────────
if ($editRow === null && isset($_GET['edit'])) {
    $editId = (int)$_GET['edit'];
    if ($editId > 0) {
        $editRow = getProfileById($editId);
    }
}

$profiles = getAllProfiles();
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title><?= e(APP_NAME) ?> — Label Profiles</title>
    <link rel="stylesheet" href="../assets/css/style.css">
</head>
<body>

<header class="app-header">
    <div class="app-header__inner">
        <span class="app-title"><?= e(APP_NAME) ?></span>
        <nav class="app-nav">
            <a href="index.php" class="nav-link">Lookup</a>
            <a href="profiles.php" class="nav-link nav-link--active">Label Profiles</a>
        </nav>
    </div>
</header>

<main class="container">
    <h1 class="page-title">Label Profiles</h1>

    <?php if ($success): ?>
    <div class="alert alert-success"><?= $success ?></div>
    <?php endif; ?>

    <?php if ($error): ?>
    <div class="alert alert-error"><?= $error ?></div>
    <?php endif; ?>

    <!-- ── Profile list ──────────────────────────────────────────────────── -->
    <?php if (empty($profiles)): ?>
    <p class="text-muted">No profiles yet — use the form below to create one.</p>
    <?php else: ?>
    <div class="table-wrapper">
        <table class="profiles-table">
            <thead>
                <tr>
                    <th>Name</th>
                    <th>Size (W &times; H)</th>
                    <th>Grid</th>
                    <th>Margins T / L</th>
                    <th>Spacing H / V</th>
                    <th>Mode</th>
                    <th></th>
                </tr>
            </thead>
            <tbody>
            <?php foreach ($profiles as $p):
                $isThermal = ((int)$p['labels_per_row'] === 1 && (int)$p['labels_per_column'] === 1);
            ?>
            <tr>
                <td><?= e($p['profile_name']) ?></td>
                <td class="mono"><?= e($p['label_width_inches']) ?>" &times; <?= e($p['label_height_inches']) ?>"</td>
                <td class="mono"><?= (int)$p['labels_per_row'] ?> &times; <?= (int)$p['labels_per_column'] ?></td>
                <td class="mono"><?= e($p['margin_top']) ?>" / <?= e($p['margin_left']) ?>"</td>
                <td class="mono"><?= e($p['horizontal_spacing']) ?>" / <?= e($p['vertical_spacing']) ?>"</td>
                <td>
                    <span class="badge <?= $isThermal ? 'badge--thermal' : 'badge--sheet' ?>">
                        <?= $isThermal ? 'Thermal' : 'Sheet' ?>
                    </span>
                </td>
                <td class="action-cell">
                    <a href="profiles.php?edit=<?= (int)$p['id'] ?>" class="btn btn-sm">Edit</a>
                    <form
                        method="post"
                        action="profiles.php"
                        style="display:inline"
                        onsubmit="return confirm('Delete profile &quot;<?= e(addslashes($p['profile_name'])) ?>&quot;?')"
                    >
                        <input type="hidden" name="action" value="delete">
                        <input type="hidden" name="id" value="<?= (int)$p['id'] ?>">
                        <button type="submit" class="btn btn-sm btn-danger">Delete</button>
                    </form>
                </td>
            </tr>
            <?php endforeach; ?>
            </tbody>
        </table>
    </div>
    <?php endif; ?>

    <!-- ── Add / Edit form ───────────────────────────────────────────────── -->
    <div class="card">
        <h2 class="card-title"><?= $editRow ? 'Edit Profile' : 'Add New Profile' ?></h2>

        <form method="post" action="profiles.php" class="profile-form">
            <input type="hidden" name="action" value="<?= $editRow ? 'edit' : 'add' ?>">
            <?php if ($editRow && !empty($editRow['id'])): ?>
            <input type="hidden" name="id" value="<?= (int)$editRow['id'] ?>">
            <?php endif; ?>

            <div class="form-grid">

                <div class="form-group form-group--full">
                    <label for="profile_name">Profile Name</label>
                    <input
                        type="text"
                        name="profile_name"
                        id="profile_name"
                        class="form-control"
                        value="<?= e((string)($editRow['profile_name'] ?? '')) ?>"
                        placeholder="e.g. Zebra 4&times;6 Thermal, Avery 5160"
                        required
                    >
                </div>

                <div class="form-group">
                    <label for="label_width_inches">Label Width (in)</label>
                    <input type="number" name="label_width_inches" id="label_width_inches"
                           class="form-control" step="0.125" min="0.5"
                           value="<?= e((string)($editRow['label_width_inches'] ?? '4')) ?>" required>
                </div>

                <div class="form-group">
                    <label for="label_height_inches">Label Height (in)</label>
                    <input type="number" name="label_height_inches" id="label_height_inches"
                           class="form-control" step="0.125" min="0.25"
                           value="<?= e((string)($editRow['label_height_inches'] ?? '6')) ?>" required>
                </div>

                <div class="form-group">
                    <label for="labels_per_row">
                        Labels per Row
                        <span class="label-hint">(1 = thermal)</span>
                    </label>
                    <input type="number" name="labels_per_row" id="labels_per_row"
                           class="form-control" min="1" max="10"
                           value="<?= e((string)($editRow['labels_per_row'] ?? '1')) ?>" required>
                </div>

                <div class="form-group">
                    <label for="labels_per_column">
                        Labels per Column
                        <span class="label-hint">(1 = thermal)</span>
                    </label>
                    <input type="number" name="labels_per_column" id="labels_per_column"
                           class="form-control" min="1" max="30"
                           value="<?= e((string)($editRow['labels_per_column'] ?? '1')) ?>" required>
                </div>

                <div class="form-group">
                    <label for="margin_top">Top Margin (in)</label>
                    <input type="number" name="margin_top" id="margin_top"
                           class="form-control" step="0.0625" min="0"
                           value="<?= e((string)($editRow['margin_top'] ?? '0')) ?>">
                </div>

                <div class="form-group">
                    <label for="margin_left">Left Margin (in)</label>
                    <input type="number" name="margin_left" id="margin_left"
                           class="form-control" step="0.0625" min="0"
                           value="<?= e((string)($editRow['margin_left'] ?? '0')) ?>">
                </div>

                <div class="form-group">
                    <label for="horizontal_spacing">Horizontal Gap (in)</label>
                    <input type="number" name="horizontal_spacing" id="horizontal_spacing"
                           class="form-control" step="0.0625" min="0"
                           value="<?= e((string)($editRow['horizontal_spacing'] ?? '0')) ?>">
                </div>

                <div class="form-group">
                    <label for="vertical_spacing">Vertical Gap (in)</label>
                    <input type="number" name="vertical_spacing" id="vertical_spacing"
                           class="form-control" step="0.0625" min="0"
                           value="<?= e((string)($editRow['vertical_spacing'] ?? '0')) ?>">
                </div>

            </div><!-- .form-grid -->

            <div class="form-actions">
                <span id="mode-hint" class="badge badge--thermal" style="margin-right:auto">
                    Thermal mode — one label per page
                </span>
                <?php if ($editRow): ?>
                <a href="profiles.php" class="btn">Cancel</a>
                <?php endif; ?>
                <button type="submit" class="btn btn-primary">
                    <?= $editRow ? 'Update Profile' : 'Add Profile' ?>
                </button>
            </div>

        </form>
    </div><!-- .card -->

</main>

<script src="../assets/js/app.js"></script>
</body>
</html>
