<?php
/**
 * Import Payment Remittance Data
 * 
 * Handles multiple vendor file formats, normalizes into remit_records table.
 * Auto-detects column mapping based on header patterns.
 * 
 * Usage: php import_remit_data.php <file_path> <customer_code> [--format=auto|amazon|homedepot|staples|generic]
 */

require_once __DIR__ . '/../includes/config.php';

if ($argc < 3) {
    echo "Usage: php import_remit_data.php <file_path> <customer_code> [--format=auto]\n";
    echo "\nSupported formats: auto, amazon, homedepot, staples, orgill, lowes, tractor, generic\n";
    echo "Customer codes:\n";
    $db = getDB();
    $stmt = $db->query("SELECT customer_code, short_name FROM ecom_customers ORDER BY search_priority");
    while ($row = $stmt->fetch()) {
        echo "  {$row['customer_code']}  {$row['short_name']}\n";
    }
    exit(1);
}

$filePath = $argv[1];
$customerCode = $argv[2];
$format = 'auto';
foreach ($argv as $arg) {
    if (strpos($arg, '--format=') === 0) {
        $format = substr($arg, 9);
    }
}

if (!file_exists($filePath)) {
    echo "Error: File not found: {$filePath}\n";
    exit(1);
}

echo "AR Cleanup - Remit Data Import\n";
echo str_repeat("=", 60) . "\n";
echo "File: " . basename($filePath) . "\n";
echo "Customer: {$customerCode}\n";
echo "Format: {$format}\n\n";

// Read file into rows
$ext = strtolower(pathinfo($filePath, PATHINFO_EXTENSION));
$rows = [];
$rawHeaders = [];

if ($ext === 'csv' || $ext === 'tsv') {
    $delimiter = $ext === 'tsv' ? "\t" : ',';
    $handle = fopen($filePath, 'r');
    $rawHeaders = fgetcsv($handle, 0, $delimiter);
    while (($row = fgetcsv($handle, 0, $delimiter)) !== false) {
        if (count($row) === count($rawHeaders)) {
            $rows[] = array_combine($rawHeaders, $row);
        }
    }
    fclose($handle);
} elseif ($ext === 'xlsx' || $ext === 'xls') {
    $tmpCsv = tempnam(sys_get_temp_dir(), 'remit_import_');
    $cmd = sprintf(
        'python3 -c "
import openpyxl, csv
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
    $rawHeaders = fgetcsv($handle);
    while (($row = fgetcsv($handle)) !== false) {
        if (count($row) === count($rawHeaders)) {
            $rows[] = array_combine($rawHeaders, $row);
        }
    }
    fclose($handle);
    unlink($tmpCsv);
} else {
    echo "Error: Unsupported format. Use CSV, TSV, XLSX, or XLS.\n";
    echo "For PDF files, convert to CSV first using tabula or similar tool.\n";
    exit(1);
}

echo "Headers found: " . implode(', ', $rawHeaders) . "\n";
echo "Rows read: " . count($rows) . "\n\n";

// ============================================================
// COLUMN MAPPING
// Auto-detect based on common vendor patterns
// ============================================================

class ColumnMapper {
    private array $headers;
    private string $format;
    
    // Mapping of our fields to possible column name patterns
    private array $patterns = [
        'invoice_no' => [
            'invoice.*(no|num|#|number)', 'inv.*(no|num|#)', 'invoice$', 'inv$',
            'vendor.*(inv|ref)', 'supplier.*inv', 'bill.*no'
        ],
        'po_number' => [
            'p\.?o\.?.*(no|num|#|number)', 'purchase.*order', 'order.*(no|num)',
            'customer.*po', 'po$'
        ],
        'payment_amount' => [
            'payment.*am', 'paid.*am', 'net.*pay', 'remit.*am', 'amount.*paid',
            'check.*am', 'cash.*applied', 'amt$', 'amount$', 'payment$'
        ],
        'discount_amount' => [
            'disc.*am', 'discount', 'early.*pay', 'deduction', 'adjustment',
            'disc$'
        ],
        'check_number' => [
            'check.*(no|num|#)', 'chk.*(no|num)', 'eft.*ref', 'ach.*ref',
            'payment.*ref', 'remit.*ref', 'reference.*no', 'check$'
        ],
        'payment_date' => [
            'pay.*date', 'check.*date', 'remit.*date', 'settlement.*date',
            'deposit.*date', 'payment.*dt', 'date.*paid'
        ],
        'remit_date' => [
            'remit.*date', 'advice.*date', 'statement.*date'
        ],
        'deduction_code' => [
            'deduction.*code', 'reason.*code', 'charge.*back.*code',
            'adj.*code', 'code$'
        ],
        'deduction_description' => [
            'deduction.*desc', 'reason.*desc', 'charge.*back.*desc',
            'adj.*desc', 'description'
        ],
    ];
    
    public function __construct(array $headers, string $format = 'auto') {
        $this->headers = $headers;
        $this->format = $format;
    }
    
    public function map(): array {
        $mapping = [];
        
        foreach ($this->patterns as $field => $patterns) {
            $mapping[$field] = $this->findMatch($patterns);
        }
        
        return $mapping;
    }
    
    private function findMatch(array $patterns): ?string {
        foreach ($patterns as $pattern) {
            foreach ($this->headers as $header) {
                $clean = strtolower(trim($header));
                if (preg_match('/' . $pattern . '/i', $clean)) {
                    return $header;
                }
            }
        }
        return null;
    }
}

$mapper = new ColumnMapper($rawHeaders, $format);
$colMap = $mapper->map();

echo "Column mapping (auto-detected):\n";
foreach ($colMap as $field => $col) {
    $status = $col ? "-> \"{$col}\"" : "-> NOT FOUND";
    echo "  {$field} {$status}\n";
}

if (!$colMap['invoice_no'] && !$colMap['payment_amount']) {
    echo "\nError: Could not identify invoice number or payment amount columns.\n";
    echo "Try specifying --format= or check the file headers.\n";
    echo "\nIf the column mapping looks wrong, you can create a column_map.json file:\n";
    echo '  {"invoice_no":"YourInvColumn","payment_amount":"YourAmtColumn",...}' . "\n";
    exit(1);
}

echo "\n";

// ============================================================
// IMPORT
// ============================================================

$db = getDB();
$batchId = logImport('remit_data', basename($filePath), $customerCode, 0, 0, 0, "Format: {$format}");

$insertSql = "INSERT INTO remit_records 
    (customer_code, invoice_no, invoice_no_normalized, po_number, payment_amount, 
     discount_amount, net_payment, check_number, remit_reference, payment_date, 
     remit_date, deduction_code, deduction_description, source_file, source_row, 
     source_format, import_batch_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)";

$stmt = $db->prepare($insertSql);

$imported = 0;
$skipped = 0;
$errors = 0;

$db->beginTransaction();

foreach ($rows as $i => $row) {
    // Extract values using column map
    $invoiceRaw = trim($row[$colMap['invoice_no']] ?? '');
    $poNumber = trim($row[$colMap['po_number']] ?? '');
    $payAmtRaw = $row[$colMap['payment_amount']] ?? '';
    $discAmtRaw = $row[$colMap['discount_amount']] ?? '0';
    $checkNo = trim($row[$colMap['check_number']] ?? '');
    $payDateRaw = $row[$colMap['payment_date']] ?? '';
    $remitDateRaw = $row[$colMap['remit_date']] ?? '';
    $dedCode = trim($row[$colMap['deduction_code']] ?? '');
    $dedDesc = trim($row[$colMap['deduction_description']] ?? '');
    
    // Skip empty rows
    if ($invoiceRaw === '' && $payAmtRaw === '') {
        $skipped++;
        continue;
    }
    
    // Clean amounts
    $payAmt = (float) preg_replace('/[^0-9.\-]/', '', $payAmtRaw);
    $discAmt = (float) preg_replace('/[^0-9.\-]/', '', $discAmtRaw);
    $netPay = $payAmt - abs($discAmt);
    
    // Normalize invoice number
    $invoiceNorm = normalizeInvoiceNo($invoiceRaw, $customerCode);
    
    // Parse dates
    $payDate = parseDate($payDateRaw);
    $remitDate = parseDate($remitDateRaw);
    
    // Use remit reference as check number fallback
    $remitRef = $checkNo;
    
    try {
        $stmt->execute([
            $customerCode, $invoiceRaw, $invoiceNorm, $poNumber ?: null,
            $payAmt ?: null, $discAmt, $netPay ?: null,
            $checkNo ?: null, $remitRef ?: null,
            $payDate, $remitDate,
            $dedCode ?: null, $dedDesc ?: null,
            basename($filePath), $i + 2, $ext, $batchId
        ]);
        $imported++;
    } catch (Exception $e) {
        $errors++;
        if ($errors <= 10) {
            echo "  Error row " . ($i + 2) . ": " . $e->getMessage() . "\n";
        }
    }
    
    if ($imported % 500 === 0 && $imported > 0) {
        echo "  Imported {$imported}...\n";
    }
}

$db->commit();

// Update log
$logStmt = $db->prepare("UPDATE import_log SET records_imported=?, records_skipped=?, records_errored=?, notes=? WHERE id=?");
$logStmt->execute([$imported, $skipped, $errors, "Complete. Mapping: " . json_encode(array_filter($colMap)), $batchId]);

echo "\n" . str_repeat("=", 60) . "\n";
echo "IMPORT COMPLETE\n";
echo "  Imported: {$imported}\n";
echo "  Skipped: {$skipped}\n";
echo "  Errors: {$errors}\n";
echo "  Batch ID: {$batchId}\n\n";

// Show coverage summary
$coverage = $db->prepare("SELECT MIN(payment_date) as earliest, MAX(payment_date) as latest, 
    COUNT(*) as total, COUNT(DISTINCT invoice_no_normalized) as unique_invoices
    FROM remit_records WHERE customer_code = ? AND import_batch_id = ?");
$coverage->execute([$customerCode, $batchId]);
$cov = $coverage->fetch();

echo "This import covers:\n";
echo "  Date range: {$cov['earliest']} to {$cov['latest']}\n";
echo "  Total records: {$cov['total']}\n";
echo "  Unique invoices referenced: {$cov['unique_invoices']}\n";

// ============================================================
// HELPER
// ============================================================

function parseDate(?string $raw): ?string {
    if (!$raw || $raw === 'None' || $raw === '') return null;
    $raw = trim($raw);
    
    // ISO format
    if (preg_match('/^\d{4}-\d{2}-\d{2}/', $raw)) return substr($raw, 0, 10);
    
    // US format m/d/Y
    if (preg_match('/^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/', $raw)) {
        $d = DateTime::createFromFormat('m/d/Y', $raw) ?: DateTime::createFromFormat('n/j/Y', $raw);
        if (!$d) $d = DateTime::createFromFormat('m/d/y', $raw);
        if ($d) return $d->format('Y-m-d');
    }
    
    // Excel serial date number
    if (is_numeric($raw) && (float)$raw > 40000 && (float)$raw < 50000) {
        $unix = ((float)$raw - 25569) * 86400;
        return date('Y-m-d', (int)$unix);
    }
    
    // Try generic parsing
    try {
        $d = new DateTime($raw);
        if ($d->format('Y') > 2000 && $d->format('Y') < 2100) {
            return $d->format('Y-m-d');
        }
    } catch (Exception $e) {}
    
    return null;
}
