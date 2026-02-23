<?php
require_once 'db_config.php';

// Get filter parameter
$filter = $_GET['status'] ?? $_POST['status'] ?? 'all';
$valid_filters = ['all', 'found', 'not_found', 'pending', 'error'];
if (!in_array($filter, $valid_filters)) {
    $filter = 'all';
}

// Build filename
$filename = 'upc_audit_' . $filter . '_' . date('Y-m-d') . '.csv';

// Set headers for CSV download
header('Content-Type: text/csv');
header('Content-Disposition: attachment; filename="' . $filename . '"');

// Create output stream
$output = fopen('php://output', 'w');

// Write header row
fputcsv($output, [
    'API Source',
    'Sage ItemCode',
    'UPC',
    'Product Name',
    'Brand',
    'Model',
    'ASIN',
    'Category',
    'Size',
    'Color',
    'Weight',
    'Dimensions',
    'Country',
    'Lowest Price',
    'Currency',
    'Image URL',
    'Retailers',
    'Match Status',
    'Last Scanned',
    'Lookup Date',
    'Notes'
]);

// Build query with optional filter
$pdo->setAttribute(PDO::MYSQL_ATTR_USE_BUFFERED_QUERY, false);

if ($filter === 'all') {
    $stmt = $pdo->query("SELECT * FROM upc_lookups ORDER BY sage_itemcode, api_source");
} else {
    $stmt = $pdo->prepare("SELECT * FROM upc_lookups WHERE match_status = ? ORDER BY sage_itemcode, api_source");
    $stmt->execute([$filter]);
}

// Stream rows
while ($row = $stmt->fetch()) {
    fputcsv($output, [
        $row['api_source'] ?? 'unknown',
        $row['sage_itemcode'],
        $row['upc'],
        $row['product_name'] ?? '',
        $row['brand'] ?? '',
        $row['model'] ?? '',
        $row['asin'] ?? '',
        $row['category'] ?? '',
        $row['size'] ?? '',
        $row['color'] ?? '',
        $row['weight'] ?? '',
        $row['dimensions'] ?? '',
        $row['country'] ?? '',
        $row['lowest_price'] ?? '',
        $row['price_currency'] ?? '',
        $row['image_url'] ?? '',
        $row['retailer_data'] ?? '',
        $row['match_status'],
        $row['last_scanned'] ?? '',
        $row['lookup_date'],
        $row['notes'] ?? ''
    ]);
}

$pdo->setAttribute(PDO::MYSQL_ATTR_USE_BUFFERED_QUERY, true);
fclose($output);
exit;
?>
