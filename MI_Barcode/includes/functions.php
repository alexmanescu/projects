<?php
/**
 * MI_Barcode — Utility functions
 */

declare(strict_types=1);

// ── HTML escaping ─────────────────────────────────────────────────────────────

function e(string $s): string
{
    return htmlspecialchars($s, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

// ── UPC lookup ────────────────────────────────────────────────────────────────

/**
 * Look up one item by exact UPC in the audit database.
 * Returns the row array on success, null if not found.
 */
function getItemByUpc(string $upc): ?array
{
    $upc = trim($upc);
    if ($upc === '') {
        return null;
    }

    $stmt = getAuditDb()->prepare(
        'SELECT upc, description, uom, part_number, model_number, sku
           FROM ' . AUDIT_TABLE . '
          WHERE upc = ?
          LIMIT 1'
    );
    $stmt->execute([$upc]);
    $row = $stmt->fetch();
    return $row ?: null;
}

// ── Part number fallback logic ────────────────────────────────────────────────

/**
 * Returns the best available identifier for a part in priority order:
 *   SKU → part_number → model_number → 'N/A'
 *
 * SKU is the preferred pick-label identifier per warehouse convention.
 */
function getDisplayPartNumber(array $item): string
{
    if (!empty($item['sku']))          return $item['sku'];
    if (!empty($item['part_number']))  return $item['part_number'];
    if (!empty($item['model_number'])) return $item['model_number'];
    return 'N/A';
}

/**
 * Returns which field name was used ('sku', 'part_number', 'model_number', or null).
 * Used in the UI to display a badge showing the data source.
 */
function getPartNumberSource(array $item): ?string
{
    if (!empty($item['sku']))          return 'SKU';
    if (!empty($item['part_number']))  return 'Part #';
    if (!empty($item['model_number'])) return 'Model #';
    return null;
}

// ── Label profile CRUD ────────────────────────────────────────────────────────

function getAllProfiles(): array
{
    $stmt = getProfilesDb()->query(
        'SELECT * FROM label_profiles ORDER BY profile_name ASC'
    );
    return $stmt->fetchAll();
}

function getProfileById(int $id): ?array
{
    $stmt = getProfilesDb()->prepare(
        'SELECT * FROM label_profiles WHERE id = ? LIMIT 1'
    );
    $stmt->execute([$id]);
    $row = $stmt->fetch();
    return $row ?: null;
}

function insertProfile(array $fields): void
{
    getProfilesDb()->prepare(
        'INSERT INTO label_profiles
            (profile_name, label_width_inches, label_height_inches,
             labels_per_row, labels_per_column,
             margin_top, margin_left, horizontal_spacing, vertical_spacing)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)'
    )->execute([
        $fields['profile_name'],
        $fields['label_width_inches'],
        $fields['label_height_inches'],
        $fields['labels_per_row'],
        $fields['labels_per_column'],
        $fields['margin_top'],
        $fields['margin_left'],
        $fields['horizontal_spacing'],
        $fields['vertical_spacing'],
    ]);
}

function updateProfile(int $id, array $fields): void
{
    getProfilesDb()->prepare(
        'UPDATE label_profiles SET
            profile_name = ?, label_width_inches = ?, label_height_inches = ?,
            labels_per_row = ?, labels_per_column = ?,
            margin_top = ?, margin_left = ?, horizontal_spacing = ?, vertical_spacing = ?
         WHERE id = ?'
    )->execute([
        $fields['profile_name'],
        $fields['label_width_inches'],
        $fields['label_height_inches'],
        $fields['labels_per_row'],
        $fields['labels_per_column'],
        $fields['margin_top'],
        $fields['margin_left'],
        $fields['horizontal_spacing'],
        $fields['vertical_spacing'],
        $id,
    ]);
}

function deleteProfile(int $id): void
{
    getProfilesDb()->prepare('DELETE FROM label_profiles WHERE id = ?')
                   ->execute([$id]);
}

// ── Input sanitisation helpers ────────────────────────────────────────────────

/**
 * Sanitise and collect profile form fields from $_POST.
 * Returns an array ready for insertProfile() / updateProfile().
 */
function collectProfileFields(): array
{
    return [
        'profile_name'        => trim($_POST['profile_name'] ?? ''),
        'label_width_inches'  => (float)($_POST['label_width_inches']  ?? 0),
        'label_height_inches' => (float)($_POST['label_height_inches'] ?? 0),
        'labels_per_row'      => max(1, (int)($_POST['labels_per_row']    ?? 1)),
        'labels_per_column'   => max(1, (int)($_POST['labels_per_column'] ?? 1)),
        'margin_top'          => (float)($_POST['margin_top']           ?? 0),
        'margin_left'         => (float)($_POST['margin_left']          ?? 0),
        'horizontal_spacing'  => (float)($_POST['horizontal_spacing']   ?? 0),
        'vertical_spacing'    => (float)($_POST['vertical_spacing']     ?? 0),
    ];
}

function validateProfileFields(array $fields): ?string
{
    if ($fields['profile_name'] === '') {
        return 'Profile name is required.';
    }
    if ($fields['label_width_inches'] <= 0 || $fields['label_height_inches'] <= 0) {
        return 'Label dimensions must be greater than zero.';
    }
    return null; // valid
}
