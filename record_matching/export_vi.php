<?php
/**
 * VI Export Module
 * 
 * Generates Sage 100 Visual Integrator import-ready Excel sheets
 * from approved match_results records.
 * 
 * Usage: php export_vi.php <batch_type> [customer_code] [--threshold=20] [--dry-run]
 *        batch_type: cash_receipt | debit_memo | credit_memo | small_balance
 */

require_once __DIR__ . '/../includes/config.php';

if ($argc < 2) {
    echo "Usage: php export_vi.php <batch_type> [customer_code] [--threshold=20] [--dry-run]\n";
    echo "\nBatch types:\n";
    echo "  cash_receipt  - Export approved cash receipt matches\n";
    echo "  debit_memo    - Export approved debit memo matches\n";
    echo "  credit_memo   - Export approved credit memo matches\n";
    echo "  small_balance - Export all under-threshold invoices (no remit match needed)\n";
    exit(1);
}

$batchType = $argv[1];
$customerCode = null;
$threshold = SMALL_BALANCE_THRESHOLD;
$dryRun = false;

for ($i = 2; $i < $argc; $i++) {
    if ($argv[$i] === '--dry-run') { $dryRun = true; continue; }
    if (strpos($argv[$i], '--threshold=') === 0) { $threshold = (float)substr($argv[$i], 12); continue; }
    if (preg_match('/^\d{8}$/', $argv[$i])) { $customerCode = $argv[$i]; }
}

$db = getDB();
$datestamp = date('md');
$records = [];

echo "AR Cleanup - VI Export\n";
echo str_repeat("=", 60) . "\n";
echo "Type: {$batchType}\n";
echo "Customer: " . ($customerCode ?? 'ALL') . "\n";
echo "Dry run: " . ($dryRun ? 'YES' : 'NO') . "\n\n";

// ============================================================
// GATHER RECORDS BASED ON BATCH TYPE
// ============================================================

if ($batchType === 'small_balance') {
    // Small balance closer - pull directly from open_invoices, no match needed
    $sql = "SELECT * FROM open_invoices WHERE resolution_status = 'open' AND ABS(balance) <= ? AND ABS(balance) > 0";
    $params = [$threshold];
    if ($customerCode) { $sql .= " AND customer_code = ?"; $params[] = $customerCode; }
    $sql .= " ORDER BY customer_code, invoice_no";
    
    $stmt = $db->prepare($sql);
    $stmt->execute($params);
    $records = $stmt->fetchAll();
    
    echo "Found " . count($records) . " invoices with |balance| <= \${$threshold}\n\n";
    
} else {
    // Pull from approved match_results
    $sql = "SELECT mr.*, oi.division, oi.invoice_date, oi.po_number, oi.customer_name
        FROM match_results mr 
        JOIN open_invoices oi ON mr.open_invoice_id = oi.id
        WHERE mr.status = 'approved' AND mr.resolution_action = ?";
    $params = [$batchType];
    if ($customerCode) { $sql .= " AND mr.customer_code = ?"; $params[] = $customerCode; }
    $sql .= " ORDER BY mr.customer_code, mr.invoice_no";
    
    $stmt = $db->prepare($sql);
    $stmt->execute($params);
    $records = $stmt->fetchAll();
    
    echo "Found " . count($records) . " approved {$batchType} records\n\n";
}

if (empty($records)) {
    echo "No records to export.\n";
    exit(0);
}

// ============================================================
// GENERATE VI IMPORT SHEETS
// ============================================================

// We'll output as CSV (easily imported by VI or convertable to xlsx)
// Two files per batch: one for positive balances, one for negative

if ($batchType === 'small_balance') {
    // Split positive (need cash receipt) and negative (need debit memo)
    $posRecords = array_filter($records, fn($r) => $r['balance'] > 0);
    $negRecords = array_filter($records, fn($r) => $r['balance'] < 0);
    
    if (!empty($posRecords)) {
        $batchName = "ARCLN-SB-CR-{$datestamp}-01";
        $filename = "VI_SmallBal_CR_{$datestamp}.csv";
        exportCashReceiptCSV($posRecords, $batchName, $filename, $db, $dryRun);
    }
    
    if (!empty($negRecords)) {
        $batchName = "ARCLN-SB-DM-{$datestamp}-01";
        $filename = "VI_SmallBal_DM_{$datestamp}.csv";
        exportDebitMemoCSV($negRecords, $batchName, $filename, $db, $dryRun);
    }
    
} elseif ($batchType === 'cash_receipt') {
    $custSuffix = $customerCode ? substr($customerCode, 0, 4) : 'ALL';
    $batchName = "ARCLN-PMT-{$custSuffix}-{$datestamp}-01";
    $filename = "VI_CashReceipt_{$custSuffix}_{$datestamp}.csv";
    exportCashReceiptCSV($records, $batchName, $filename, $db, $dryRun, true);
    
} elseif ($batchType === 'debit_memo') {
    $custSuffix = $customerCode ? substr($customerCode, 0, 4) : 'ALL';
    $batchName = "ARCLN-DM-{$custSuffix}-{$datestamp}-01";
    $filename = "VI_DebitMemo_{$custSuffix}_{$datestamp}.csv";
    exportDebitMemoCSV($records, $batchName, $filename, $db, $dryRun, true);
}

echo "\nExport complete.\n";

// ============================================================
// EXPORT FUNCTIONS
// ============================================================

function exportCashReceiptCSV(array $records, string $batchName, string $filename, PDO $db, bool $dryRun, bool $fromMatches = false): void {
    $filepath = EXPORT_DIR . $filename;
    
    echo "Generating Cash Receipt VI: {$filename}\n";
    echo "  Batch: {$batchName}\n";
    echo "  Records: " . count($records) . "\n";
    
    // Cash Receipt VI columns (Batch > Deposit > Lines)
    // These map to the chained VI job: AR_CashReceiptsBatchHeader > AR_CashReceiptsDeposit > AR_CashReceipts
    $headers = [
        // Batch header fields
        'BatchNo',
        // Deposit fields  
        'DepositType', 'DepositDate', 'DepositNo', 'BankCode',
        // Cash receipt line fields
        'ARDivisionNo', 'CustomerNo', 'InvoiceNo', 'CashApplied', 'DiscountApplied',
        // Reference fields
        'CheckNo', 'PostingComment',
        // Source tracking (not imported, for audit)
        '_SourceRef', '_OriginalBalance'
    ];
    
    if ($dryRun) {
        echo "  [DRY RUN - not writing file]\n";
        $handle = fopen('php://stdout', 'w');
    } else {
        $handle = fopen($filepath, 'w');
    }
    
    fputcsv($handle, $headers);
    
    $totalCash = 0;
    $totalDisc = 0;
    $depositDate = date('m/d/Y');
    
    foreach ($records as $i => $rec) {
        if ($fromMatches) {
            $division = $rec['division'] ?? '01';
            $custCode = $rec['customer_code'];
            $invoiceNo = $rec['invoice_no'];
            $cashApplied = abs((float)$rec['remit_amount']);
            $discApplied = abs((float)($rec['remit_discount'] ?? 0));
            $checkNo = $rec['check_number'] ?? '';
            $balance = (float)$rec['invoice_balance'];
            $sourceRef = "Match#{$rec['id']}";
        } else {
            // From open_invoices directly (small balance)
            $division = $rec['division'] ?? '01';
            $custCode = $rec['customer_code'];
            $invoiceNo = $rec['invoice_no'];
            $cashApplied = abs((float)$rec['balance']);
            $discApplied = 0;
            $checkNo = 'ARCLN';
            $balance = (float)$rec['balance'];
            $sourceRef = "SmallBal";
        }
        
        $row = [
            $batchName,                           // BatchNo
            'C',                                  // DepositType (C=Cash)
            $depositDate,                         // DepositDate
            str_pad($i + 1, 5, '0', STR_PAD_LEFT), // DepositNo
            'A',                                  // BankCode
            $division,                            // ARDivisionNo
            $custCode,                            // CustomerNo
            $invoiceNo,                           // InvoiceNo
            number_format($cashApplied, 2, '.', ''), // CashApplied
            number_format($discApplied, 2, '.', ''), // DiscountApplied
            $checkNo,                             // CheckNo
            "AR Cleanup - {$sourceRef}",          // PostingComment
            $sourceRef,                           // _SourceRef
            number_format($balance, 2, '.', ''),  // _OriginalBalance
        ];
        
        fputcsv($handle, $row);
        $totalCash += $cashApplied;
        $totalDisc += $discApplied;
    }
    
    if (!$dryRun) {
        fclose($handle);
        echo "  Written to: {$filepath}\n";
        
        // Record the export batch
        $batchStmt = $db->prepare("INSERT INTO vi_export_batches 
            (batch_name, batch_type, customer_code, record_count, total_amount, gl_account, status, export_file)
            VALUES (?, 'cash_receipt', ?, ?, ?, ?, 'exported', ?)");
        $batchStmt->execute([$batchName, null, count($records), $totalCash, GL_BAD_DEBT, $filename]);
        
        // Update match records
        if ($fromMatches) {
            $updateStmt = $db->prepare("UPDATE match_results SET status = 'exported', batch_name = ?, exported_at = NOW() WHERE id = ?");
            foreach ($records as $rec) {
                $updateStmt->execute([$batchName, $rec['id']]);
            }
        }
    }
    
    echo "  Total cash applied: " . money($totalCash) . "\n";
    echo "  Total discount: " . money($totalDisc) . "\n";
}

function exportDebitMemoCSV(array $records, string $batchName, string $filename, PDO $db, bool $dryRun, bool $fromMatches = false): void {
    $filepath = EXPORT_DIR . $filename;
    
    echo "Generating Debit Memo VI: {$filename}\n";
    echo "  Batch: {$batchName}\n";
    echo "  Records: " . count($records) . "\n";
    
    // DM VI columns (Batch > Header > Detail)
    // Maps to: AR_InvoiceBatchHeader > AR_InvoiceHeader > AR_InvoiceDetail
    $headers = [
        // Batch header
        'BatchNo',
        // Invoice header
        'ARDivisionNo', 'CustomerNo', 'InvoiceNo', 'InvoiceType', 'InvoiceDate',
        'ApplyToInvoiceNo',
        // Detail line
        'ItemCode', 'ItemCodeDesc', 'ExtensionAmt', 'AccountKey',
        // Reference
        'Comment', '_SourceRef', '_OriginalBalance'
    ];
    
    if ($dryRun) {
        $handle = fopen('php://stdout', 'w');
    } else {
        $handle = fopen($filepath, 'w');
    }
    
    fputcsv($handle, $headers);
    
    $totalAmt = 0;
    $dmCounter = 1;
    
    foreach ($records as $rec) {
        if ($fromMatches) {
            $division = $rec['division'] ?? '01';
            $custCode = $rec['customer_code'];
            $origInvoice = $rec['invoice_no'];
            $amount = abs((float)$rec['invoice_balance']);
            $balance = (float)$rec['invoice_balance'];
            $sourceRef = "Match#{$rec['id']}";
        } else {
            $division = $rec['division'] ?? '01';
            $custCode = $rec['customer_code'];
            $origInvoice = $rec['invoice_no'];
            $amount = abs((float)$rec['balance']);
            $balance = (float)$rec['balance'];
            $sourceRef = "SmallBal";
        }
        
        // Generate DM invoice number
        $dmInvoice = '9' . str_pad($dmCounter, 6, '0', STR_PAD_LEFT);
        $dmCounter++;
        
        $row = [
            $batchName,                           // BatchNo
            $division,                            // ARDivisionNo
            $custCode,                            // CustomerNo
            $dmInvoice,                           // InvoiceNo (new DM number)
            'DM',                                 // InvoiceType
            date('m/d/Y'),                        // InvoiceDate
            $origInvoice,                         // ApplyToInvoiceNo
            '/WRITE OFF',                         // ItemCode (misc item)
            'AR Cleanup - Bad Debt Write Off',    // ItemCodeDesc
            number_format($amount, 2, '.', ''),   // ExtensionAmt
            GL_BAD_DEBT,                          // AccountKey
            "ARCLN-{$origInvoice}",               // Comment
            $sourceRef,                           // _SourceRef
            number_format($balance, 2, '.', ''),  // _OriginalBalance
        ];
        
        fputcsv($handle, $row);
        $totalAmt += $amount;
    }
    
    if (!$dryRun) {
        fclose($handle);
        echo "  Written to: {$filepath}\n";
        
        $batchStmt = $db->prepare("INSERT INTO vi_export_batches 
            (batch_name, batch_type, customer_code, record_count, total_amount, gl_account, status, export_file)
            VALUES (?, 'debit_memo', ?, ?, ?, ?, 'exported', ?)");
        $batchStmt->execute([$batchName, null, count($records), $totalAmt, GL_BAD_DEBT, $filename]);
        
        if ($fromMatches) {
            $updateStmt = $db->prepare("UPDATE match_results SET status = 'exported', batch_name = ?, exported_at = NOW() WHERE id = ?");
            foreach ($records as $rec) {
                $updateStmt->execute([$batchName, $rec['id']]);
            }
        }
    }
    
    echo "  Total DM amount: " . money($totalAmt) . "\n";
}
