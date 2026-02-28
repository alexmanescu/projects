<?php
/**
 * MI_Barcode — UPC Lookup & Print
 * Main search page. Auto-focuses the UPC field so a scanner can fire immediately.
 */

declare(strict_types=1);

require_once dirname(__DIR__) . '/config/config.php';
require_once APP_ROOT . '/includes/db.php';
require_once APP_ROOT . '/includes/functions.php';

$item     = null;
$error    = null;
$upcInput = '';

if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['upc'])) {
    $upcInput = trim($_POST['upc']);
    if ($upcInput === '') {
        $error = 'Please enter or scan a UPC.';
    } else {
        try {
            $item = getItemByUpc($upcInput);
            if ($item === null) {
                $error = 'UPC <strong>' . e($upcInput) . '</strong> was not found in the audit database.';
            }
        } catch (PDOException $ex) {
            $error = 'Database error — check your connection settings. (' . e($ex->getMessage()) . ')';
        }
    }
}

try {
    $profiles = getAllProfiles();
} catch (PDOException $ex) {
    $profiles = [];
    $error = $error ?? 'Could not load label profiles — is the schema installed? (' . e($ex->getMessage()) . ')';
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title><?= e(APP_NAME) ?> — Lookup</title>
    <link rel="stylesheet" href="../assets/css/style.css">
</head>
<body>

<header class="app-header">
    <div class="app-header__inner">
        <div class="app-brand">
            <img src="../assets/img/logo.png" alt="<?= e(APP_NAME) ?>" class="app-logo">
            <span class="app-title"><?= e(APP_NAME) ?></span>
        </div>
        <nav class="app-nav">
            <a href="index.php" class="nav-link nav-link--active">Lookup</a>
            <a href="profiles.php" class="nav-link">Label Profiles</a>
        </nav>
    </div>
</header>

<main class="container">

    <!-- ── UPC Search ──────────────────────────────────────────────────────── -->
    <section class="search-section">
        <form method="post" action="index.php" id="search-form" autocomplete="off">
            <div class="search-row">
                <input
                    type="text"
                    name="upc"
                    id="upc-input"
                    class="upc-input"
                    placeholder="Scan barcode or type UPC…"
                    value="<?= e($upcInput) ?>"
                    autofocus
                    required
                >
                <button type="submit" class="btn btn-primary">Look Up</button>
            </div>
        </form>
    </section>

    <!-- ── Error ───────────────────────────────────────────────────────────── -->
    <?php if ($error): ?>
    <div class="alert alert-error"><?= $error ?></div>
    <?php endif; ?>

    <!-- ── Item Details + Print Form ───────────────────────────────────────── -->
    <?php if ($item): ?>
    <section class="result-section">
        <h2 class="section-title">Item Details</h2>

        <table class="detail-table">
            <tr>
                <th>UPC</th>
                <td class="mono"><?= e($item['upc']) ?></td>
            </tr>
            <tr>
                <th>Description</th>
                <td><?= e($item['description'] ?? '—') ?></td>
            </tr>
            <tr>
                <th>UOM</th>
                <td><?= e($item['uom'] ?? '—') ?></td>
            </tr>
            <tr>
                <th>Identifier</th>
                <td>
                    <?= e(getDisplayPartNumber($item)) ?>
                    <?php $src = getPartNumberSource($item); if ($src): ?>
                    <span class="badge"><?= e($src) ?></span>
                    <?php endif; ?>
                </td>
            </tr>
        </table>

        <!-- Print form — opens PDF in a new tab -->
        <form
            method="post"
            action="print.php"
            target="_blank"
            class="print-form"
            id="print-form"
        >
            <input type="hidden" name="upc" value="<?= e($item['upc']) ?>">

            <div class="form-row">
                <div class="form-group">
                    <label for="profile_id">Label Profile</label>
                    <?php if (empty($profiles)): ?>
                        <p class="text-muted">
                            No profiles configured —
                            <a href="profiles.php">add one first</a>.
                        </p>
                    <?php else: ?>
                    <select name="profile_id" id="profile_id" class="form-control" required>
                        <?php foreach ($profiles as $p): ?>
                        <option value="<?= (int)$p['id'] ?>">
                            <?= e($p['profile_name']) ?>
                            (<?= e($p['label_width_inches']) ?>" &times; <?= e($p['label_height_inches']) ?>")
                        </option>
                        <?php endforeach; ?>
                    </select>
                    <?php endif; ?>
                </div>

                <div class="form-group form-group--narrow">
                    <label for="qty">Qty</label>
                    <input
                        type="number"
                        name="qty"
                        id="qty"
                        class="form-control qty-input"
                        value="1"
                        min="1"
                        max="500"
                        required
                    >
                </div>

                <div class="form-group form-group--align-end">
                    <button
                        type="submit"
                        class="btn btn-print"
                        <?= empty($profiles) ? 'disabled' : '' ?>
                    >
                        Print Labels
                    </button>
                </div>
            </div>
        </form>
    </section>
    <?php endif; ?>

</main>

<script src="../assets/js/app.js"></script>
</body>
</html>
