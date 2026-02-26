<?php
/**
 * Import Open Invoices from Sage Intelligence Export
 * 
 * Accepts: Excel (.xlsx) or CSV
 * Expected columns: InvoiceNo, InvoiceDate, Balance, Custno (format: "01-00000400"), Custname
 * 
 * Usage: php import_open_invoices.php /path/to/Unique_Invoices_wOpen_Balance.xlsx [snapshot_date]
 */

require_once __DIR__ . '/../includes/config.php';

if ($argc < 2) {
    echo "Usage: php import_open_invoices.php <file_path> [snapshot_date YYYY-MM-DD]\n";
    echo "  file_path: Path to Excel or CSV file\n";
    echo "  snapshot_date: Date of the S.I. export (default: today)\n";
    exit(1);
}

$filePath = $argv[1];
$snapshotDate = $argv[2] ?? date('Y-m-d');

if (!file_exists($filePath)) {
    echo "Error: File not found: {$filePath}\n";
    exit(1);
}

// Determine file type
$ext = strtolower(pathinfo($filePath, PATHINFO_EXTENSION));

echo "AR Cleanup - Open Invoice Import\n";
echo str_repeat("=", 60) . "\n";
echo "File: {$filePath}\n";
echo "Snapshot date: {$snapshotDate}\n";
echo "Format: {$ext}\n\n";

// Read data based on format
$rows = [];
if ($ext === 'csv') {
    $handle = fopen($filePath, 'r');
    $headers = fgetcsv($handle);
    while (($row = fgetcsv($handle)) !== false) {
        $rows[] = array_combine($headers, $row);
    }
    fclose($handle);
} elseif ($ext === 'xlsx') {
    // Use PhpSpreadsheet if available, otherwise fall back to python helper
    $tmpCsv = tempnam(sys_get_temp_dir(), 'ar_import_');
    $cmd = sprintf(
        'python3 -c "
import openpyxl, csv, sys
wb = openpyxl.load_workbook(%s, read_only=True, data_only=True)
ws = wb.active
writer = csv.writer(open(%s, \'w\', newline=\'\'))
for i, row in enumerate(ws.iter_rows(values_only=True)):
    writer.writerow([str(c) if c is not None else \'\' for c in row])
wb.close()
" 2>&1',
        escapeshellarg($filePath),
        escapeshellarg($tmpCsv)
    );
    exec($cmd, $output, $retCode);
    if ($retCode !== 0) {
        echo "Error converting xlsx: " . implode("\n", $output) . "\n";
        exit(1);
    }
    $handle = fopen($tmpCsv, 'r');
    $headers = fgetcsv($handle);
    while (($row = fgetcsv($handle)) !== false) {
        if (count($row) === count($headers)) {
            $rows[] = array_combine($headers, $row);
        }
    }
    fclose($handle);
    unlink($tmpCsv);
} else {
    echo "Error: Unsupported file format: {$ext}\n";
    exit(1);
}

echo "Rows read: " . count($rows) . "\n\n";

// Map column names (flexible matching)
function findColumn(array $headers, array $candidates): ?string {
    foreach ($candidates as $c) {
        foreach ($headers as $h) {
            if (strtolower(trim($h)) === strtolower($c)) return $h;
        }
    }
    return null;
}

$sampleHeaders = array_keys($rows[0] ?? []);
$colInvoice = findColumn($sampleHeaders, ['InvoiceNo', 'Invoice', 'Invoice No', 'InvoiceNumber', 'Inv#']);
$colDate = findColumn($sampleHeaders, ['InvoiceDate', 'Invoice Date', 'Date', 'Inv Date']);
$colBalance = findColumn($sampleHeaders, ['Balance', 'Open Balance', 'Amount', 'InvoiceBalance']);
$colCustNo = findColumn($sampleHeaders, ['Custno', 'CustomerNo', 'Customer No', 'CustNo', 'Customer']);
$colCustName = findColumn($sampleHeaders, ['Custname', 'CustomerName', 'Customer Name', 'CustName', 'Name', 'BillToName']);

echo "Column mapping:\n";
echo "  Invoice#: {$colInvoice}\n";
echo "  Date: {$colDate}\n";
echo "  Balance: {$colBalance}\n";
echo "  Customer#: {$colCustNo}\n";
echo "  Customer Name: {$colCustName}\n\n";

if (!$colInvoice || !$colBalance || !$colCustNo) {
    echo "Error: Could not find required columns (InvoiceNo, Balance, CustomerNo)\n";
    exit(1);
}

// Load ecom customer list
$db = getDB();
$ecomCodes = [];
$stmt = $db->query("SELECT customer_code FROM ecom_customers");
while ($row = $stmt->fetch()) {
    $ecomCodes[$row['customer_code']] = true;
}

// Prepare insert
$insertSql = "INSERT INTO open_invoices 
    (invoice_no, division, customer_code, customer_name, invoice_date, balance, 
     is_as400, is_ecom, age_days, age_bucket, resolution_status, snapshot_date, import_batch_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
    ON DUPLICATE KEY UPDATE 
        balance = VALUES(balance),
        customer_name = VALUES(customer_name),
        age_days = VALUES(age_days),
        age_bucket = VALUES(age_bucket),
        updated_at = CURRENT_TIMESTAMP";

$insertStmt = $db->prepare($insertSql);

$imported = 0;
$skipped = 0;
$errors = 0;
$refDate = new DateTime($snapshotDate);

$db->beginTransaction();

// Log the import
$batchId = logImport('open_invoices', basename($filePath), null, 0, 0, 0, "Import started");

foreach ($rows as $i => $row) {
    $invoiceNo = trim($row[$colInvoice] ?? '');
    $balance = (float) str_replace(['$', ',', '(', ')'], '', $row[$colBalance] ?? '0');
    $custNoFull = trim($row[$colCustNo] ?? '');
    $custName = trim($row[$colCustName] ?? '');
    
    // Skip empty rows
    if ($invoiceNo === '' || $custNoFull === '') {
        $skipped++;
        continue;
    }
    
    // Parse division from customer code (format: "01-00000400")
    $division = null;
    $custCode = $custNoFull;
    if (strpos($custNoFull, '-') !== false) {
        [$division, $custCode] = explode('-', $custNoFull, 2);
    }
    
    // Parse date
    $invoiceDate = null;
    $ageDays = null;
    if (!empty($row[$colDate])) {
        $dateRaw = $row[$colDate];
        // Handle various date formats
        if (preg_match('/^\d{4}-\d{2}-\d{2}/', $dateRaw)) {
            $invoiceDate = substr($dateRaw, 0, 10);
        } elseif (preg_match('/^\d{1,2}\/\d{1,2}\/\d{2,4}$/', $dateRaw)) {
            $d = DateTime::createFromFormat('m/d/Y', $dateRaw) ?: DateTime::createFromFormat('n/j/Y', $dateRaw);
            if ($d) $invoiceDate = $d->format('Y-m-d');
        }
        if ($invoiceDate) {
            try {
                $invDate = new DateTime($invoiceDate);
                if ($invDate->format('Y') < 2100) {
                    $ageDays = $refDate->diff($invDate)->days;
                }
            } catch (Exception $e) {
                // Skip bad dates
            }
        }
    }
    
    // Determine if AS400 (invoice starts with 0 and is 7+ digits)
    $isAs400 = (substr($invoiceNo, 0, 1) === '0' && strlen($invoiceNo) >= 6) ? 1 : 0;
    
    // Determine if ecom
    $isEcom = isset($ecomCodes[$custCode]) ? 1 : 0;
    
    // Age bucket
    $bucket = ageBucket($invoiceDate, $snapshotDate);
    
    try {
        $insertStmt->execute([
            $invoiceNo, $division, $custCode, $custName, $invoiceDate,
            $balance, $isAs400, $isEcom, $ageDays, $bucket, $snapshotDate, $batchId
        ]);
        $imported++;
    } catch (Exception $e) {
        $errors++;
        if ($errors <= 10) {
            echo "  Error row " . ($i + 2) . ": " . $e->getMessage() . "\n";
        }
    }
    
    if ($imported % 1000 === 0) {
        echo "  Processed {$imported}...\n";
    }
}

$db->commit();

// Update import log
$stmt = $db->prepare("UPDATE import_log SET records_imported = ?, records_skipped = ?, records_errored = ?, notes = ? WHERE id = ?");
$stmt->execute([$imported, $skipped, $errors, "Import complete", $batchId]);

echo "\n" . str_repeat("=", 60) . "\n";
echo "IMPORT COMPLETE\n";
echo "  Imported: {$imported}\n";
echo "  Skipped: {$skipped}\n";
echo "  Errors: {$errors}\n";
echo "  Batch ID: {$batchId}\n\n";

// Quick stats
$stats = $db->query("SELECT COUNT(*) as total, SUM(balance) as net, 
    SUM(CASE WHEN is_ecom=1 THEN 1 ELSE 0 END) as ecom_count,
    SUM(CASE WHEN is_as400=1 THEN 1 ELSE 0 END) as as400_count
    FROM open_invoices WHERE snapshot_date = '{$snapshotDate}'")->fetch();

echo "Database now contains:\n";
echo "  Total open invoices: " . number_format($stats['total']) . "\n";
echo "  Net balance: " . money((float)$stats['net']) . "\n";
echo "  Ecom invoices: " . number_format($stats['ecom_count']) . "\n";
echo "  AS400 legacy: " . number_format($stats['as400_count']) . "\n";
