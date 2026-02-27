<?php
/**
 * MI_Barcode — PDF Generation Endpoint
 *
 * Accepts POST: upc, profile_id, qty
 * Validates inputs, looks up the item and profile, then streams a PDF to the
 * browser. The form on index.php uses target="_blank" so this opens as a
 * new tab ready to print.
 *
 * GET requests are redirected back to index.php.
 */

declare(strict_types=1);

require_once dirname(__DIR__) . '/config/config.php';
require_once APP_ROOT . '/includes/db.php';
require_once APP_ROOT . '/includes/functions.php';
require_once APP_ROOT . '/includes/pdf_generator.php';

// ── Reject GET requests ───────────────────────────────────────────────────────
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    header('Location: index.php');
    exit;
}

// ── Validate inputs ───────────────────────────────────────────────────────────
$upc       = trim($_POST['upc'] ?? '');
$profileId = (int)($_POST['profile_id'] ?? 0);
$qty       = max(1, min(500, (int)($_POST['qty'] ?? 1)));

if ($upc === '') {
    printError('No UPC provided.');
}
if ($profileId <= 0) {
    printError('No label profile selected.');
}

// ── Load item ─────────────────────────────────────────────────────────────────
try {
    $item = getItemByUpc($upc);
} catch (PDOException $ex) {
    printError('Database error during UPC lookup: ' . $ex->getMessage());
}

if ($item === null) {
    printError('UPC "' . htmlspecialchars($upc, ENT_QUOTES, 'UTF-8') . '" not found in the audit database.');
}

// ── Load profile ──────────────────────────────────────────────────────────────
try {
    $profile = getProfileById($profileId);
} catch (PDOException $ex) {
    printError('Database error loading label profile: ' . $ex->getMessage());
}

if ($profile === null) {
    printError('Selected label profile no longer exists. Please choose another.');
}

// ── Generate & stream PDF ─────────────────────────────────────────────────────
// generateLabelsPDF() calls TCPDF::Output('…', 'I') which sends headers +
// body and terminates — no further code executes after this call.
generateLabelsPDF($item, $profile, $qty);

// ── Error helper ──────────────────────────────────────────────────────────────

/**
 * Output a minimal HTML error page and halt.
 * @param string $msg Plain text message (will be escaped).
 * @return never
 */
function printError(string $msg): never
{
    http_response_code(400);
    echo '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">'
       . '<title>Print Error</title>'
       . '<style>body{font-family:sans-serif;padding:2rem;background:#111;color:#f44;}'
       . 'a{color:#aaa;}</style></head><body>'
       . '<h2>Could not generate labels</h2>'
       . '<p>' . htmlspecialchars($msg, ENT_QUOTES, 'UTF-8') . '</p>'
       . '<p><a href="index.php">&larr; Back to lookup</a></p>'
       . '</body></html>';
    exit;
}
