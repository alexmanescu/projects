<?php
/**
 * AR Cleanup - Invoice to Payment Matching Engine
 * 
 * Runs matching algorithms against remit_records and open_invoices.
 * Produces match candidates with confidence scores.
 * 
 * Usage: php run_matching.php [customer_code] [--strategy=all|exact|amount|fuzzy]
 *        php run_matching.php --all    (run for all customers with remit data)
 */

require_once __DIR__ . '/../includes/config.php';

$targetCustomer = null;
$strategy = 'all';
$runAll = false;

for ($i = 1; $i < $argc; $i++) {
    if ($argv[$i] === '--all') { $runAll = true; continue; }
    if (strpos($argv[$i], '--strategy=') === 0) { $strategy = substr($argv[$i], 11); continue; }
    if (preg_match('/^\d{8}$/', $argv[$i])) { $targetCustomer = $argv[$i]; continue; }
}

$db = getDB();

echo "AR Cleanup - Matching Engine\n";
echo str_repeat("=", 60) . "\n";

// Determine which customers to process
$customers = [];
if ($targetCustomer) {
    $customers = [$targetCustomer];
} elseif ($runAll) {
    $stmt = $db->query("SELECT DISTINCT customer_code FROM remit_records ORDER BY customer_code");
    $customers = $stmt->fetchAll(PDO::FETCH_COLUMN);
} else {
    echo "Usage: php run_matching.php <customer_code> or --all\n";
    exit(1);
}

echo "Customers to process: " . count($customers) . "\n";
echo "Strategy: {$strategy}\n\n";

$totalMatches = 0;

foreach ($customers as $custCode) {
    echo str_repeat("-", 60) . "\n";
    
    // Get customer name
    $custStmt = $db->prepare("SELECT short_name FROM ecom_customers WHERE customer_code = ?");
    $custStmt->execute([$custCode]);
    $custName = $custStmt->fetchColumn() ?: $custCode;
    
    echo "Processing: {$custCode} - {$custName}\n";
    
    // Load open invoices for this customer
    $invStmt = $db->prepare("SELECT * FROM open_invoices WHERE customer_code = ? AND resolution_status = 'open'");
    $invStmt->execute([$custCode]);
    $openInvoices = $invStmt->fetchAll();
    
    // Load unmatched remit records
    $remitStmt = $db->prepare("SELECT * FROM remit_records WHERE customer_code = ? AND is_matched = 0");
    $remitStmt->execute([$custCode]);
    $remitRecords = $remitStmt->fetchAll();
    
    echo "  Open invoices: " . count($openInvoices) . "\n";
    echo "  Unmatched remit records: " . count($remitRecords) . "\n";
    
    if (empty($openInvoices) || empty($remitRecords)) {
        echo "  Skipping - no data to match.\n";
        continue;
    }
    
    // Index invoices by normalized number for fast lookup
    $invByNo = [];
    foreach ($openInvoices as $inv) {
        $key = ltrim($inv['invoice_no'], '0');
        if ($key === '') $key = '0';
        $invByNo[$key] = $inv;
        // Also index by full number
        $invByNo[$inv['invoice_no']] = $inv;
    }
    
    // Index by balance for amount matching
    $invByBalance = [];
    foreach ($openInvoices as $inv) {
        $balKey = number_format(abs($inv['balance']), 2, '.', '');
        $invByBalance[$balKey][] = $inv;
    }
    
    $matchInsert = $db->prepare("INSERT INTO match_results 
        (open_invoice_id, remit_record_id, customer_code, invoice_no, match_type, match_confidence,
         invoice_balance, remit_amount, remit_discount, variance, status, resolution_action, gl_account, matched_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, 'system')");
    
    $updateRemit = $db->prepare("UPDATE remit_records SET is_matched = 1, match_id = ? WHERE id = ?");
    $updateInvoice = $db->prepare("UPDATE open_invoices SET resolution_status = ? WHERE id = ?");
    
    $matches = 0;
    $matchedRemitIds = [];
    $matchedInvoiceIds = [];
    
    $db->beginTransaction();
    
    // ============================================================
    // STRATEGY 1: EXACT MATCH (invoice# + amount within tolerance)
    // ============================================================
    if ($strategy === 'all' || $strategy === 'exact') {
        echo "  Running exact match...\n";
        
        foreach ($remitRecords as $remit) {
            if (in_array($remit['id'], $matchedRemitIds)) continue;
            
            $normInv = ltrim($remit['invoice_no_normalized'] ?? '', '0');
            if ($normInv === '') $normInv = '0';
            
            // Try both normalized and original
            $inv = $invByNo[$normInv] ?? $invByNo[$remit['invoice_no_normalized'] ?? ''] ?? null;
            
            if (!$inv || in_array($inv['id'], $matchedInvoiceIds)) continue;
            
            $invBal = (float) $inv['balance'];
            $remitAmt = (float) ($remit['payment_amount'] ?? 0);
            $remitDisc = (float) ($remit['discount_amount'] ?? 0);
            $totalApplied = $remitAmt + abs($remitDisc);
            
            // Check if payment matches balance (exact or with discount)
            $variance = $invBal - $totalApplied;
            
            if (abs($variance) <= MATCH_EXACT_TOLERANCE) {
                // Perfect match
                $action = $invBal > 0 ? 'cash_receipt' : 'debit_memo';
                $gl = GL_BAD_DEBT;
                
                $matchInsert->execute([
                    $inv['id'], $remit['id'], $custCode, $inv['invoice_no'],
                    'exact', 99.0, $invBal, $remitAmt, $remitDisc, $variance,
                    $action, $gl
                ]);
                $matchId = (int) $db->lastInsertId();
                $updateRemit->execute([$matchId, $remit['id']]);
                $updateInvoice->execute(['matched', $inv['id']]);
                
                $matchedRemitIds[] = $remit['id'];
                $matchedInvoiceIds[] = $inv['id'];
                $matches++;
            } elseif ($invBal > 0 && $remitAmt > 0 && abs($variance) / $invBal <= MATCH_DISCOUNT_TOLERANCE) {
                // Close match with small discount variance
                $action = 'cash_receipt';
                
                $matchInsert->execute([
                    $inv['id'], $remit['id'], $custCode, $inv['invoice_no'],
                    'exact', 90.0, $invBal, $remitAmt, $remitDisc, $variance,
                    $action, GL_BAD_DEBT
                ]);
                $matchId = (int) $db->lastInsertId();
                $updateRemit->execute([$matchId, $remit['id']]);
                $updateInvoice->execute(['matched', $inv['id']]);
                
                $matchedRemitIds[] = $remit['id'];
                $matchedInvoiceIds[] = $inv['id'];
                $matches++;
            }
        }
        echo "    Exact matches: {$matches}\n";
    }
    
    $exactMatches = $matches;
    
    // ============================================================
    // STRATEGY 2: INVOICE NUMBER MATCH (number matches, amount differs)
    // ============================================================
    if ($strategy === 'all' || $strategy === 'partial') {
        echo "  Running partial match (invoice# match, amount differs)...\n";
        $partialCount = 0;
        
        foreach ($remitRecords as $remit) {
            if (in_array($remit['id'], $matchedRemitIds)) continue;
            
            $normInv = ltrim($remit['invoice_no_normalized'] ?? '', '0');
            if ($normInv === '') continue;
            
            $inv = $invByNo[$normInv] ?? $invByNo[$remit['invoice_no_normalized'] ?? ''] ?? null;
            
            if (!$inv || in_array($inv['id'], $matchedInvoiceIds)) continue;
            
            $invBal = (float) $inv['balance'];
            $remitAmt = (float) ($remit['payment_amount'] ?? 0);
            $remitDisc = (float) ($remit['discount_amount'] ?? 0);
            $variance = $invBal - ($remitAmt + abs($remitDisc));
            
            // Invoice # matches but amount is off
            $confidence = max(50, 80 - abs($variance / max(abs($invBal), 1)) * 100);
            $action = $invBal > 0 ? 'cash_receipt' : 'debit_memo';
            
            $matchInsert->execute([
                $inv['id'], $remit['id'], $custCode, $inv['invoice_no'],
                'partial', $confidence, $invBal, $remitAmt, $remitDisc, $variance,
                $action, GL_BAD_DEBT
            ]);
            $matchId = (int) $db->lastInsertId();
            $updateRemit->execute([$matchId, $remit['id']]);
            $updateInvoice->execute(['partial_match', $inv['id']]);
            
            $matchedRemitIds[] = $remit['id'];
            $matchedInvoiceIds[] = $inv['id'];
            $matches++;
            $partialCount++;
        }
        echo "    Partial matches: {$partialCount}\n";
    }
    
    // ============================================================
    // STRATEGY 3: AMOUNT-ONLY MATCH (no invoice# but amount matches exactly)
    // ============================================================
    if ($strategy === 'all' || $strategy === 'amount') {
        echo "  Running amount-only match...\n";
        $amountCount = 0;
        
        foreach ($remitRecords as $remit) {
            if (in_array($remit['id'], $matchedRemitIds)) continue;
            
            $remitAmt = (float) ($remit['payment_amount'] ?? 0);
            if ($remitAmt == 0) continue;
            
            $balKey = number_format(abs($remitAmt), 2, '.', '');
            $candidates = $invByBalance[$balKey] ?? [];
            
            // Filter to unmatched only
            $candidates = array_filter($candidates, fn($c) => !in_array($c['id'], $matchedInvoiceIds));
            
            if (count($candidates) === 1) {
                // Single amount match - reasonable confidence
                $inv = reset($candidates);
                $invBal = (float) $inv['balance'];
                $variance = $invBal - $remitAmt;
                $action = $invBal > 0 ? 'cash_receipt' : 'debit_memo';
                
                $matchInsert->execute([
                    $inv['id'], $remit['id'], $custCode, $inv['invoice_no'],
                    'amount_only', 60.0, $invBal, $remitAmt, 0, $variance,
                    $action, GL_BAD_DEBT
                ]);
                $matchId = (int) $db->lastInsertId();
                $updateRemit->execute([$matchId, $remit['id']]);
                $updateInvoice->execute(['partial_match', $inv['id']]);
                
                $matchedRemitIds[] = $remit['id'];
                $matchedInvoiceIds[] = $inv['id'];
                $matches++;
                $amountCount++;
            }
            // If multiple candidates match the amount, skip - too ambiguous
        }
        echo "    Amount-only matches: {$amountCount}\n";
    }
    
    $db->commit();
    
    $totalMatches += $matches;
    
    // Summary for this customer
    $remaining = count($openInvoices) - count(array_unique($matchedInvoiceIds));
    $unmatchedRemit = count($remitRecords) - count(array_unique($matchedRemitIds));
    echo "  TOTAL matched: {$matches} | Invoices remaining: {$remaining} | Remit unmatched: {$unmatchedRemit}\n";
}

// ============================================================
// STRATEGY 4: CROSS-CUSTOMER AS400 MATCHING
// ============================================================
// The AS400 system allowed invoices and cash receipts to be posted to wrong customers.
// Common patterns:
//   - Invoice on Customer A, payment posted to Customer B (same inv#)
//   - SO number used as invoice number, creating duplicate inv# across customers
//   - Payment/credit imported as IN type on wrong customer (not flagged as CM/PP)
//
// Two tiers:
//   4A: Positive/negative pairs (classic mispost) — higher confidence
//   4B: Any duplicate invoice# across customers regardless of sign — lower confidence, needs investigation
// ============================================================

echo "\n" . str_repeat("=", 60) . "\n";
echo "CROSS-CUSTOMER AS400 MATCHING\n";
echo str_repeat("=", 60) . "\n";

// --- TIER 4A: Positive/Negative pairs (classic mispost) ---
echo "\n  TIER 4A: Positive/Negative pairs (likely misposted payment)\n";

$crossSql = "SELECT oi1.id as pos_id, oi1.invoice_no, oi1.customer_code as pos_customer, 
    oi1.customer_name as pos_name, oi1.balance as pos_balance,
    oi2.id as neg_id, oi2.customer_code as neg_customer, oi2.customer_name as neg_name, 
    oi2.balance as neg_balance,
    ABS(oi1.balance + oi2.balance) as variance
FROM open_invoices oi1
JOIN open_invoices oi2 ON oi1.invoice_no = oi2.invoice_no 
    AND oi1.customer_code != oi2.customer_code
WHERE oi1.is_as400 = 1 AND oi2.is_as400 = 1
    AND oi1.balance > 0 AND oi2.balance < 0
    AND oi1.resolution_status = 'open' AND oi2.resolution_status = 'open'
ORDER BY ABS(oi1.balance) DESC";

$crossMatches = $db->query($crossSql)->fetchAll();
$crossCount = 0;
$crossExact = 0;
$seenInvIds = []; // Track which invoice IDs have been paired in 4A

if (!empty($crossMatches)) {
    echo "  Found " . count($crossMatches) . " potential pos/neg pairs\n";
    
    $crossInsert = $db->prepare("INSERT INTO match_results 
        (open_invoice_id, remit_record_id, customer_code, invoice_no, match_type, match_confidence,
         invoice_balance, remit_amount, remit_discount, variance, status, resolution_action, gl_account, 
         matched_by, notes)
        VALUES (?, NULL, ?, ?, 'cross_customer', ?, ?, ?, 0, ?, 'pending', ?, ?, 'system', ?)");
    
    $updateInv = $db->prepare("UPDATE open_invoices SET resolution_status = 'partial_match' WHERE id = ?");
    
    $db->beginTransaction();
    $seen = [];
    
    foreach ($crossMatches as $cm) {
        if (isset($seen[$cm['pos_id']]) || isset($seen[$cm['neg_id']])) continue;
        
        $variance = (float) $cm['variance'];
        $isExact = $variance <= MATCH_EXACT_TOLERANCE;
        $confidence = $isExact ? 85.0 : max(60, 80 - ($variance / max(abs($cm['pos_balance']), 1)) * 100);
        
        $note = sprintf("AS400 MISPOST (pos/neg pair): Inv# %s on %s (+\$%.2f) and %s (-\$%.2f). Variance: \$%.2f. Requires paired corrections on both customers.",
            $cm['invoice_no'], $cm['pos_customer'], $cm['pos_balance'],
            $cm['neg_customer'], abs($cm['neg_balance']), $variance);
        
        $crossInsert->execute([
            $cm['pos_id'], $cm['pos_customer'], $cm['invoice_no'], $confidence,
            $cm['pos_balance'], abs($cm['neg_balance']), $variance,
            'cash_receipt', GL_BAD_DEBT, $note
        ]);
        
        $crossInsert->execute([
            $cm['neg_id'], $cm['neg_customer'], $cm['invoice_no'], $confidence,
            $cm['neg_balance'], 0, $cm['neg_balance'],
            'debit_memo', GL_BAD_DEBT, $note
        ]);
        
        $updateInv->execute([$cm['pos_id']]);
        $updateInv->execute([$cm['neg_id']]);
        
        $seen[$cm['pos_id']] = true;
        $seen[$cm['neg_id']] = true;
        $seenInvIds[$cm['pos_id']] = true;
        $seenInvIds[$cm['neg_id']] = true;
        $crossCount++;
        if ($isExact) $crossExact++;
        
        if ($crossCount <= 10) {
            echo sprintf("    %s: %s (+\$%.2f) <-> %s (-\$%.2f) var=\$%.2f %s\n",
                $cm['invoice_no'], $cm['pos_customer'], $cm['pos_balance'],
                $cm['neg_customer'], abs($cm['neg_balance']),
                $variance, $isExact ? '[EXACT]' : '');
        }
    }
    
    $db->commit();
    echo "  Tier 4A pairs: {$crossCount} ({$crossExact} exact match on amount)\n";
}

// --- TIER 4B: Any duplicate AS400 invoice# across customers (regardless of sign) ---
echo "\n  TIER 4B: Any duplicate AS400 invoice# across different customers\n";

$dupSql = "SELECT oi.invoice_no, 
    GROUP_CONCAT(DISTINCT oi.customer_code ORDER BY oi.customer_code SEPARATOR ', ') as customers,
    GROUP_CONCAT(DISTINCT CONCAT(oi.customer_code, ':', oi.balance, ':', oi.id) ORDER BY oi.customer_code SEPARATOR '|') as detail,
    COUNT(DISTINCT oi.customer_code) as cust_count,
    COUNT(*) as record_count
FROM open_invoices oi
WHERE oi.is_as400 = 1 
    AND oi.resolution_status = 'open'
    AND oi.id NOT IN (SELECT COALESCE(open_invoice_id, 0) FROM match_results WHERE match_type = 'cross_customer')
GROUP BY oi.invoice_no
HAVING COUNT(DISTINCT oi.customer_code) > 1
ORDER BY SUM(ABS(oi.balance)) DESC";

$dupResults = $db->query($dupSql)->fetchAll();
$dupCount = 0;

if (!empty($dupResults)) {
    echo "  Found " . count($dupResults) . " invoice numbers appearing on multiple customers\n";
    
    $dupInsert = $db->prepare("INSERT INTO match_results 
        (open_invoice_id, remit_record_id, customer_code, invoice_no, match_type, match_confidence,
         invoice_balance, remit_amount, remit_discount, variance, status, resolution_action, gl_account, 
         matched_by, notes)
        VALUES (?, NULL, ?, ?, 'cross_customer_dup', ?, ?, 0, 0, ?, 'pending', NULL, NULL, 'system', ?)");
    
    $updateInv2 = $db->prepare("UPDATE open_invoices SET resolution_status = 'partial_match' WHERE id = ?");
    
    $db->beginTransaction();
    
    foreach ($dupResults as $dup) {
        $details = explode('|', $dup['detail']);
        $custBalances = [];
        foreach ($details as $d) {
            [$cust, $bal, $invId] = explode(':', $d);
            $custBalances[] = ['customer' => $cust, 'balance' => (float)$bal, 'id' => (int)$invId];
        }
        
        // Build descriptive note
        $parts = [];
        foreach ($custBalances as $cb) {
            $sign = $cb['balance'] >= 0 ? '+' : '';
            $parts[] = "{$cb['customer']} ({$sign}\${$cb['balance']})";
        }
        $note = sprintf("AS400 DUPLICATE INV#: %s appears on %d customers: %s. Investigate AS400 source data to determine correct owner and resolution.",
            $dup['invoice_no'], $dup['cust_count'], implode(', ', $parts));
        
        // Confidence is lower — this needs investigation
        $confidence = 40.0;
        
        // Create a match record for each customer's copy of this invoice
        foreach ($custBalances as $cb) {
            if (isset($seenInvIds[$cb['id']])) continue; // Already handled in 4A
            
            $dupInsert->execute([
                $cb['id'], $cb['customer'], $dup['invoice_no'], $confidence,
                $cb['balance'], $cb['balance'], $note
            ]);
            
            $updateInv2->execute([$cb['id']]);
        }
        
        $dupCount++;
        
        if ($dupCount <= 15) {
            echo "    {$dup['invoice_no']}: {$dup['cust_count']} customers - " . implode(', ', $parts) . "\n";
        }
    }
    
    $db->commit();
    echo "  Tier 4B duplicate invoice#s flagged: {$dupCount}\n";
    echo "  NOTE: These are lower confidence (40%) and require AS400 source data to resolve.\n";
    echo "  Check original AS400 records to determine which customer owned the SO/invoice.\n";
}

$totalCrossCustomer = $crossCount + $dupCount;
echo "\n  CROSS-CUSTOMER TOTAL: {$totalCrossCustomer} ({$crossCount} pos/neg pairs + {$dupCount} other duplicates)\n";

$totalMatches += $totalCrossCustomer;

echo "\n" . str_repeat("=", 60) . "\n";
echo "ALL MATCHING COMPLETE\n";
echo "Total matches across all customers: {$totalMatches}\n";
echo "  (includes {$crossCount} cross-customer pos/neg pairs + {$dupCount} duplicate inv# flags)\n\n";

// Pipeline summary
$pipeline = $db->query("SELECT status, match_type, COUNT(*) as cnt, 
    SUM(invoice_balance) as bal, SUM(remit_amount) as remit, SUM(variance) as var
    FROM match_results GROUP BY status, match_type ORDER BY status, match_type");

echo "Match Pipeline:\n";
echo sprintf("  %-12s %-15s %6s %14s %14s %12s\n", 'Status', 'Type', 'Count', 'Inv Balance', 'Remit Amt', 'Variance');
echo "  " . str_repeat("-", 80) . "\n";
while ($row = $pipeline->fetch()) {
    echo sprintf("  %-12s %-15s %6d %14s %14s %12s\n",
        $row['status'], $row['match_type'], $row['cnt'],
        money((float)$row['bal']), money((float)$row['remit']), money((float)$row['var']));
}
