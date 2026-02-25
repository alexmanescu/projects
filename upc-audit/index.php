<?php
require_once 'db_config.php';

// Handle clear ALL records
if (isset($_POST['clear_all'])) {
    $pdo->exec("TRUNCATE TABLE upc_lookups");
    header('Location: index.php?cleared=all');
    exit;
}

// Handle clear PENDING ONLY
if (isset($_POST['clear_pending'])) {
    $pdo->exec("DELETE FROM upc_lookups WHERE match_status = 'pending'");
    header('Location: index.php?cleared=pending');
    exit;
}

// Handle CSV upload
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_FILES['csv_file'])) {
    $file = $_FILES['csv_file'];
    
    if ($file['error'] === UPLOAD_ERR_OK) {
        $handle = fopen($file['tmp_name'], 'r');
        $header = fgetcsv($handle);
        
        // INSERT IGNORE skips rows where UPC already exists (requires UNIQUE index on upc)
        // ON DUPLICATE KEY UPDATE updates the itemcode if a better one is provided
        $stmt = $pdo->prepare("
            INSERT INTO upc_lookups (sage_itemcode, upc, match_status) 
            VALUES (?, ?, 'pending')
            ON DUPLICATE KEY UPDATE 
                sage_itemcode = IF(VALUES(sage_itemcode) != 'UNIDENTIFIED' AND sage_itemcode = 'UNIDENTIFIED', VALUES(sage_itemcode), sage_itemcode)
        ");
        
        $count = 0;
        $skipped = 0;
        while (($row = fgetcsv($handle)) !== false) {
            $itemcode = trim($row[0] ?? '');
            $upc = trim($row[1] ?? '');
            
            // Allow blank itemcodes - default to UNIDENTIFIED
            if (empty($itemcode)) {
                $itemcode = 'UNIDENTIFIED';
            }
            
            if (!empty($upc)) {
                $stmt->execute([$itemcode, $upc]);
                if ($pdo->lastInsertId() > 0) {
                    $count++;
                } else {
                    $skipped++;
                }
            }
        }
        
        fclose($handle);
        // PRG pattern: redirect after POST to prevent browser refresh from re-uploading
        header('Location: index.php?uploaded=' . $count . '&skipped=' . $skipped);
        exit;
    } else {
        $message = "Error uploading file.";
    }
}

// Count errors and pending
$error_counts = [];
$stmt = $pdo->query("SELECT api_source, COUNT(*) as count FROM upc_lookups WHERE match_status = 'error' GROUP BY api_source");
foreach ($stmt->fetchAll() as $row) {
    $error_counts[$row['api_source']] = $row['count'];
}

$pending_count = $pdo->query("SELECT COUNT(*) FROM upc_lookups WHERE match_status = 'pending'")->fetchColumn();
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>UPC Audit Tool</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 1600px; margin: 0 auto; padding: 20px; }
        .upload-section, .results-section { background: #f5f5f5; padding: 20px; margin: 20px 0; border-radius: 5px; }
        button { background: #007bff; color: white; padding: 10px 20px; border: none; border-radius: 3px; cursor: pointer; margin-right: 5px; margin-bottom: 5px; }
        button:hover:not(:disabled) { background: #0056b3; }
        button:disabled { background: #ccc; cursor: not-allowed; }
        button[name="clear_all"] { background: #dc3545; }
        button[name="clear_pending"] { background: #ffc107; color: #000; }
        .progress-container { display: none; margin: 20px 0; padding: 15px; background: #e9ecef; border-radius: 5px; }
        .progress-bar-outer { width: 100%; height: 30px; background: #fff; border-radius: 15px; overflow: hidden; box-shadow: inset 0 1px 3px rgba(0,0,0,0.2); }
        .progress-bar-inner { height: 100%; background: linear-gradient(90deg, #4caf50, #8bc34a); width: 0%; transition: width 0.3s ease; display: flex; align-items: center; justify-content: center; color: white; font-weight: bold; }
        .progress-stats { margin-top: 10px; font-size: 14px; }
        .table-container { overflow-x: auto; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 12px; }
        th, td { padding: 6px; text-align: left; border-bottom: 1px solid #ddd; white-space: nowrap; }
        th { background: #333; color: white; font-size: 11px; position: sticky; top: 0; }
        .status-pending { color: #666; }
        .status-found { color: green; font-weight: bold; }
        .status-not_found { color: red; }
        .status-error { color: orange; font-weight: bold; }
        .error-details { font-size: 10px; color: #d9534f; max-width: 300px; white-space: normal; }
        .message { padding: 10px; margin: 10px 0; background: #d4edda; border: 1px solid #c3e6cb; border-radius: 3px; }
        .warning { padding: 10px; margin: 10px 0; background: #fff3cd; border: 1px solid #ffeaa7; border-radius: 3px; }
        input[type="number"], select { padding: 8px; margin-right: 10px; }
        input[type="number"] { width: 100px; }
        select { width: 150px; }
        label { margin-right: 10px; font-weight: bold; }
        .form-row { margin-bottom: 15px; }
        .api-barcodelookup { background-color: #e3f2fd; }
        .api-upcitemdb { background-color: #f3e5f5; }
    </style>
</head>
<body>
    <h1>UPC Audit Tool</h1>
    
    <?php if (isset($_GET['reset'])): ?>
        <div class="message"><?= (int)$_GET['reset'] ?> error records reset to pending.</div>
    <?php endif; ?>
    
    <?php if (isset($_GET['uploaded'])): ?>
        <div class="message">Uploaded <?= (int)$_GET['uploaded'] ?> new UPC codes. <?= (int)($_GET['skipped'] ?? 0) ?> duplicates skipped.</div>
    <?php endif; ?>
    
    <?php if (isset($message)): ?>
        <div class="message"><?= htmlspecialchars($message) ?></div>
    <?php endif; ?>
    
    <?php if (isset($_GET['cleared'])): ?>
        <?php if ($_GET['cleared'] === 'all'): ?>
            <div class="message">All records cleared successfully!</div>
        <?php elseif ($_GET['cleared'] === 'pending'): ?>
            <div class="message">All pending records cleared successfully!</div>
        <?php endif; ?>
    <?php endif; ?>
    
    <div class="upload-section">
        <h2>Database Management</h2>
        <form method="POST" style="display: inline;" onsubmit="return confirm('Delete ALL records?');">
            <button type="submit" name="clear_all">Clear All Records</button>
        </form>
        <form method="POST" style="display: inline;" onsubmit="return confirm('Clear pending only?');">
            <button type="submit" name="clear_pending">Clear Pending Only</button>
        </form>
    </div>
    
    <div class="upload-section">
        <h2>Upload CSV File</h2>
        <p>CSV Format: First column = Sage ItemCode, Second column = UPC</p>
        <form method="POST" enctype="multipart/form-data">
            <input type="file" name="csv_file" accept=".csv" required>
            <button type="submit">Upload & Import</button>
        </form>
    </div>
    
    <div class="results-section">
        <h2>Process Lookups</h2>
        
        <div class="form-row">
            <label for="api_source">API Source:</label>
            <select name="api_source" id="api_source" required>
                <option value="">-- Select API Source --</option>
                <option value="barcodelookup">Barcode Lookup</option>
                <option value="upcitemdb">UPC Item DB</option>
            </select>
        </div>
        
        <div class="form-row">
            <label for="batch_size">Batch Size:</label>
            <input type="number" id="batch_size" value="100" min="1" max="10000">
            <button id="processBatchBtn" onclick="startProcessing(false, false)">Process Batch</button>
            <button id="processAllBtn" onclick="startProcessing(false, true)">Process All Pending (<?= $pending_count ?>)</button>
            <?php if (!empty($error_counts)): ?>
                <?php foreach ($error_counts as $source => $count): ?>
                    <button onclick="retryErrors('<?= htmlspecialchars($source) ?>')">
                        Retry <?= htmlspecialchars($source) ?> Errors (<?= $count ?>)
                    </button>
                    <button style="background:#ff9800;" onclick="resetErrors('<?= htmlspecialchars($source) ?>', <?= $count ?>)">
                        Reset <?= $count ?> <?= htmlspecialchars($source) ?> Errors → Pending
                    </button>
                <?php endforeach; ?>
            <?php endif; ?>
        </div>
        
        <div id="progressContainer" class="progress-container">
            <div class="progress-bar-outer">
                <div id="progressBar" class="progress-bar-inner">0%</div>
            </div>
            <div class="progress-stats">
                <div id="progressText">Processing...</div>
                <div>Found: <span id="foundCount">0</span> | Not Found: <span id="notFoundCount">0</span> | Errors: <span id="errorCount">0</span></div>
                <div id="rateLimitMsg" style="display:none; margin-top:10px; padding:10px; background:#fff3cd; border:1px solid #ffeaa7; border-radius:3px; font-weight:bold;"></div>
            </div>
        </div>
        
        <?php
        $stmt = $pdo->query("SELECT COUNT(*) as total, match_status, api_source FROM upc_lookups GROUP BY match_status, api_source");
        $stats = $stmt->fetchAll();
        ?>
        
        <h3>Status Summary:</h3>
        <ul>
            <?php foreach ($stats as $stat): ?>
                <li class="status-<?= $stat['match_status'] ?>">
                    <strong><?= htmlspecialchars($stat['api_source'] ?: 'pending') ?>:</strong> 
                    <?= ucfirst($stat['match_status']) ?> - <?= $stat['total'] ?>
                </li>
            <?php endforeach; ?>
        </ul>
        
        <h3>Recent Results:</h3>
        <?php
        $stmt = $pdo->query("SELECT * FROM upc_lookups ORDER BY lookup_date DESC LIMIT 50");
        $results = $stmt->fetchAll();
        ?>
        
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>API</th><th>ItemCode</th><th>UPC</th><th>Product Name</th><th>Brand</th>
                        <th>Model</th><th>ASIN</th><th>Category</th><th>Size</th><th>Color</th>
                        <th>Weight</th><th>Dimensions</th><th>Country</th><th>Price</th>
                        <th>Last Scanned</th><th>Status</th><th>Error</th><th>Date</th>
                    </tr>
                </thead>
                <tbody>
                    <?php foreach ($results as $row): ?>
                    <tr class="api-<?= htmlspecialchars($row['api_source'] ?: 'pending') ?>">
                        <td><strong><?= htmlspecialchars($row['api_source'] ?: 'Pending') ?></strong></td>
                        <td><?= htmlspecialchars($row['sage_itemcode']) ?></td>
                        <td><?= htmlspecialchars($row['upc']) ?></td>
                        <td><?= htmlspecialchars($row['product_name'] ?? '-') ?></td>
                        <td><?= htmlspecialchars($row['brand'] ?? '-') ?></td>
                        <td><?= htmlspecialchars($row['model'] ?? '-') ?></td>
                        <td><?= htmlspecialchars($row['asin'] ?? '-') ?></td>
                        <td><?= htmlspecialchars($row['category'] ?? '-') ?></td>
                        <td><?= htmlspecialchars($row['size'] ?? '-') ?></td>
                        <td><?= htmlspecialchars($row['color'] ?? '-') ?></td>
                        <td><?= htmlspecialchars($row['weight'] ?? '-') ?></td>
                        <td><?= htmlspecialchars($row['dimensions'] ?? '-') ?></td>
                        <td><?= htmlspecialchars($row['country'] ?? '-') ?></td>
                        <td><?php if($row['lowest_price']): ?><?= htmlspecialchars($row['price_currency'] ?? '') ?> <?= number_format($row['lowest_price'], 2) ?><?php else: ?>-<?php endif; ?></td>
                        <td><?= $row['last_scanned'] ? date('m/d/y', strtotime($row['last_scanned'])) : '-' ?></td>
                        <td class="status-<?= $row['match_status'] ?>"><?= ucfirst($row['match_status']) ?></td>
                        <td class="error-details"><?php if($row['match_status']==='error' && $row['api_response']){$r=json_decode($row['api_response'],true); echo htmlspecialchars($r['error']??'');}else{echo'-';} ?></td>
                        <td><?= date('m/d/y H:i', strtotime($row['lookup_date'])) ?></td>
                    </tr>
                    <?php endforeach; ?>
                </tbody>
            </table>
        </div>
        
        <h3>Export Results:</h3>
        <form method="GET" action="export.php" style="display:flex; align-items:center; gap:10px;">
            <select name="status" style="width:200px;">
                <option value="all">All Records</option>
                <option value="found">Found Only</option>
                <option value="not_found">Not Found Only</option>
                <option value="pending">Pending Only</option>
                <option value="error">Errors Only</option>
            </select>
            <button type="submit">Download CSV</button>
        </form>
    </div>

    <script>
    let processing = false;
    let totalProcessed = 0, totalFound = 0, totalNotFound = 0, totalErrors = 0;
    let estimatedTotal = 0, targetTotal = 0;

    function startProcessing(retryMode, processAll) {
        const api = document.getElementById('api_source').value;
        if (!api) { alert('Select API source'); return; }
        if (processing) { alert('Already processing'); return; }
        
        processing = true;
        totalProcessed = totalFound = totalNotFound = totalErrors = 0;
        
        if (processAll) {
            estimatedTotal = <?= $pending_count ?>;
            targetTotal = estimatedTotal;
        } else {
            const batchSize = parseInt(document.getElementById('batch_size').value);
            estimatedTotal = Math.min(batchSize, <?= $pending_count ?>);
            targetTotal = estimatedTotal;
        }
        
        document.getElementById('progressContainer').style.display = 'block';
        document.getElementById('rateLimitMsg').style.display = 'none';
        disableButtons(true);
        
        processChunk(api, retryMode);
    }

    function retryErrors(api) {
        if (processing) { alert('Already processing'); return; }
        
        const batchSize = parseInt(document.getElementById('batch_size').value);
        
        processing = true;
        totalProcessed = totalFound = totalNotFound = totalErrors = 0;
        estimatedTotal = batchSize;
        targetTotal = batchSize;
        
        document.getElementById('api_source').value = api;
        document.getElementById('progressContainer').style.display = 'block';
        document.getElementById('rateLimitMsg').style.display = 'none';
        disableButtons(true);
        
        processChunk(api, true);
    }

    function resetErrors(source, count) {
        if (!confirm('Reset ' + count + ' ' + source + ' errors back to pending?')) return;
        
        const form = new FormData();
        form.append('reset_errors', '1');
        form.append('error_source', source);
        form.append('ajax', '1');
        
        fetch('process_batch.php', { method: 'POST', body: form })
            .then(r => r.json())
            .then(data => {
                if (data.status === 'reset') {
                    location.reload();
                }
            })
            .catch(err => alert('Error: ' + err));
    }

    function processChunk(api, retryMode) {
        const batchSize = parseInt(document.getElementById('batch_size').value) || 100;
        // Send batch_size to server — for REDACTED it processes in groups of 10 UPCs per API call
        const serverBatch = Math.min(batchSize, 100); // Cap per AJAX call at 100
        
        const form = new FormData();
        form.append('api_source', api);
        form.append('batch_size', serverBatch.toString());
        form.append('ajax', '1');
        if (retryMode) form.append('retry_errors', '1');
        
        fetch('process_batch.php', { method: 'POST', body: form })
            .then(r => r.json())
            .then(data => {
                if (data.error) {
                    alert('Error: ' + data.error);
                    resetProcessing();
                    return;
                }
                
                totalProcessed += data.processed;
                totalFound += data.found || 0;
                totalNotFound += data.not_found || 0;
                totalErrors += data.errors || 0;
                
                const pct = Math.min(100, Math.round((totalProcessed / estimatedTotal) * 100));
                document.getElementById('progressBar').style.width = pct + '%';
                document.getElementById('progressBar').textContent = pct + '%';
                
                let statusText = `Processed ${totalProcessed} of ${estimatedTotal}`;
                if (data.api_calls_remaining !== undefined) {
                    statusText += ` | API calls remaining today: ${data.api_calls_remaining}`;
                }
                document.getElementById('progressText').textContent = statusText;
                document.getElementById('foundCount').textContent = totalFound;
                document.getElementById('notFoundCount').textContent = totalNotFound;
                document.getElementById('errorCount').textContent = totalErrors;
                
                // Handle rate limit
                if (data.status === 'rate_limited') {
                    document.getElementById('rateLimitMsg').style.display = 'block';
                    document.getElementById('rateLimitMsg').textContent = 
                        '⚠️ ' + (data.message || 'Rate limit reached. Processing stopped.');
                    setTimeout(() => { resetProcessing(); location.reload(); }, 2000);
                    return;
                }
                
                if (data.status === 'complete' || totalProcessed >= targetTotal) {
                    setTimeout(() => { resetProcessing(); location.reload(); }, 1000);
                } else {
                    setTimeout(() => processChunk(api, retryMode), 100);
                }
            })
            .catch(err => {
                console.error(err);
                alert('Error: ' + err);
                resetProcessing();
            });
    }

    function disableButtons(disabled) {
        document.getElementById('processBatchBtn').disabled = disabled;
        document.getElementById('processAllBtn').disabled = disabled;
    }

    function resetProcessing() {
        processing = false;
        disableButtons(false);
    }
    </script>
</body>
</html>
