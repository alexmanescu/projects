<?php
/**
 * AR Cleanup Dashboard
 * 
 * Web interface for reviewing matches, approving/rejecting, monitoring pipeline.
 * Deploy to your webserver document root or a subdirectory.
 */

require_once __DIR__ . '/../includes/config.php';

$db = getDB();
$page = $_GET['page'] ?? 'dashboard';
$action = $_POST['action'] ?? null;

// Handle POST actions
if ($action === 'approve_match') {
    $matchId = (int) $_POST['match_id'];
    $stmt = $db->prepare("UPDATE match_results SET status = 'approved', reviewed_by = ?, reviewed_at = NOW() WHERE id = ?");
    $stmt->execute([$_SERVER['REMOTE_USER'] ?? 'admin', $matchId]);
    logMatchChange($matchId, 'status', 'pending', 'approved');
    header('Location: ?page=matches&customer=' . ($_POST['customer'] ?? '') . '&status=pending');
    exit;
}

if ($action === 'reject_match') {
    $matchId = (int) $_POST['match_id'];
    $stmt = $db->prepare("UPDATE match_results SET status = 'rejected', reviewed_by = ?, reviewed_at = NOW(), notes = ? WHERE id = ?");
    $stmt->execute([$_SERVER['REMOTE_USER'] ?? 'admin', $_POST['notes'] ?? '', $matchId]);
    logMatchChange($matchId, 'status', 'pending', 'rejected');
    // Reset the invoice and remit record
    $match = $db->query("SELECT open_invoice_id, remit_record_id FROM match_results WHERE id = {$matchId}")->fetch();
    $db->exec("UPDATE open_invoices SET resolution_status = 'open' WHERE id = {$match['open_invoice_id']}");
    if ($match['remit_record_id']) {
        $db->exec("UPDATE remit_records SET is_matched = 0, match_id = NULL WHERE id = {$match['remit_record_id']}");
    }
    header('Location: ?page=matches&customer=' . ($_POST['customer'] ?? '') . '&status=pending');
    exit;
}

if ($action === 'bulk_approve') {
    $ids = $_POST['match_ids'] ?? [];
    if (!empty($ids)) {
        $placeholders = implode(',', array_fill(0, count($ids), '?'));
        $stmt = $db->prepare("UPDATE match_results SET status = 'approved', reviewed_by = ?, reviewed_at = NOW() WHERE id IN ({$placeholders}) AND status = 'pending'");
        $stmt->execute(array_merge([$_SERVER['REMOTE_USER'] ?? 'admin'], $ids));
        foreach ($ids as $id) { logMatchChange((int)$id, 'status', 'pending', 'approved'); }
    }
    header('Location: ?page=matches&customer=' . ($_GET['customer'] ?? '') . '&status=pending');
    exit;
}

?><!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title><?= APP_NAME ?></title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f7fa; color: #333; }
  .header { background: #1B3A5C; color: #fff; padding: 16px 24px; display: flex; justify-content: space-between; align-items: center; }
  .header h1 { font-size: 18px; font-weight: 600; }
  .header .version { font-size: 12px; opacity: 0.7; }
  .nav { background: #2E75B6; padding: 0 24px; display: flex; gap: 0; }
  .nav a { color: #fff; text-decoration: none; padding: 12px 20px; font-size: 14px; opacity: 0.8; border-bottom: 3px solid transparent; }
  .nav a:hover, .nav a.active { opacity: 1; border-bottom-color: #fff; background: rgba(255,255,255,0.1); }
  .container { max-width: 1400px; margin: 0 auto; padding: 24px; }
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .card { background: #fff; border-radius: 8px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
  .card .label { font-size: 12px; color: #666; text-transform: uppercase; letter-spacing: 0.5px; }
  .card .value { font-size: 28px; font-weight: 700; color: #1B3A5C; margin-top: 4px; }
  .card .sub { font-size: 12px; color: #999; margin-top: 4px; }
  .card.green .value { color: #548235; }
  .card.red .value { color: #C00000; }
  .card.blue .value { color: #2E75B6; }
  table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 24px; }
  th { background: #1B3A5C; color: #fff; padding: 10px 12px; font-size: 12px; text-align: left; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
  td { padding: 8px 12px; font-size: 13px; border-bottom: 1px solid #eee; }
  tr:hover { background: #f8f9fa; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }
  .badge.exact { background: #E2EFDA; color: #548235; }
  .badge.partial { background: #FCE4CC; color: #ED7D31; }
  .badge.amount_only { background: #D5E8F0; color: #2E75B6; }
  .badge.cross_customer { background: #FCE4CC; color: #C00000; }
  .badge.cross_customer_dup { background: #FFF2CC; color: #ED7D31; }
  .badge.pending { background: #FFF2CC; color: #ED7D31; }
  .badge.approved { background: #E2EFDA; color: #548235; }
  .badge.exported { background: #D5E8F0; color: #2E75B6; }
  .badge.posted_prod { background: #1B3A5C; color: #fff; }
  .money { font-family: 'Courier New', monospace; text-align: right; }
  .money.neg { color: #C00000; }
  .btn { display: inline-block; padding: 6px 14px; border-radius: 4px; font-size: 12px; font-weight: 600; border: none; cursor: pointer; text-decoration: none; }
  .btn-approve { background: #548235; color: #fff; }
  .btn-reject { background: #C00000; color: #fff; }
  .btn-export { background: #2E75B6; color: #fff; }
  .btn-sm { padding: 4px 10px; font-size: 11px; }
  .filters { display: flex; gap: 12px; margin-bottom: 16px; align-items: center; }
  .filters select, .filters input { padding: 8px 12px; border: 1px solid #ddd; border-radius: 4px; font-size: 13px; }
  .section-title { font-size: 18px; font-weight: 600; color: #1B3A5C; margin-bottom: 16px; }
  .progress-bar { width: 100%; height: 8px; background: #eee; border-radius: 4px; overflow: hidden; }
  .progress-bar .fill { height: 100%; border-radius: 4px; }
  .fill.green { background: #548235; }
  .fill.blue { background: #2E75B6; }
  .fill.orange { background: #ED7D31; }
</style>
</head>
<body>

<div class="header">
  <div>
    <h1><?= APP_NAME ?></h1>
    <span class="version">Mutual Industries | Sage 100 Post-Migration | v<?= APP_VERSION ?></span>
  </div>
</div>

<div class="nav">
  <a href="?page=dashboard" class="<?= $page === 'dashboard' ? 'active' : '' ?>">Dashboard</a>
  <a href="?page=invoices" class="<?= $page === 'invoices' ? 'active' : '' ?>">Open Invoices</a>
  <a href="?page=remit" class="<?= $page === 'remit' ? 'active' : '' ?>">Remit Data</a>
  <a href="?page=matches" class="<?= $page === 'matches' ? 'active' : '' ?>">Match Review</a>
  <a href="?page=pipeline" class="<?= $page === 'pipeline' ? 'active' : '' ?>">VI Pipeline</a>
  <a href="?page=imports" class="<?= $page === 'imports' ? 'active' : '' ?>">Import Log</a>
</div>

<div class="container">

<?php if ($page === 'dashboard'): ?>
  <?php
    $totals = $db->query("SELECT COUNT(*) as total, 
      SUM(CASE WHEN balance > 0 THEN balance ELSE 0 END) as pos,
      SUM(CASE WHEN balance < 0 THEN balance ELSE 0 END) as neg,
      SUM(balance) as net,
      SUM(is_ecom) as ecom,
      SUM(is_as400) as as400,
      SUM(CASE WHEN ABS(balance) <= 20 AND ABS(balance) > 0 THEN 1 ELSE 0 END) as under20,
      SUM(CASE WHEN resolution_status = 'open' THEN 1 ELSE 0 END) as open_count,
      SUM(CASE WHEN resolution_status IN ('matched','partial_match') THEN 1 ELSE 0 END) as matched_count
      FROM open_invoices")->fetch();
    
    $remitTotals = $db->query("SELECT COUNT(*) as total, COUNT(DISTINCT customer_code) as customers,
      COUNT(DISTINCT source_file) as files, SUM(is_matched) as matched FROM remit_records")->fetch();
    
    $matchTotals = $db->query("SELECT COUNT(*) as total,
      SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
      SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) as approved,
      SUM(CASE WHEN status = 'exported' THEN 1 ELSE 0 END) as exported
      FROM match_results")->fetch();
  ?>
  
  <h2 class="section-title">Overview</h2>
  <div class="cards">
    <div class="card"><div class="label">Open Invoices</div><div class="value"><?= number_format($totals['total']) ?></div><div class="sub"><?= number_format($totals['open_count']) ?> unresolved</div></div>
    <div class="card blue"><div class="label">Net AR</div><div class="value"><?= money((float)$totals['net']) ?></div><div class="sub">Pos: <?= money((float)$totals['pos']) ?></div></div>
    <div class="card green"><div class="label">Matched</div><div class="value"><?= number_format($totals['matched_count']) ?></div><div class="sub"><?= $totals['total'] > 0 ? round($totals['matched_count'] / $totals['total'] * 100, 1) : 0 ?>% of total</div></div>
    <div class="card"><div class="label">Remit Records</div><div class="value"><?= number_format($remitTotals['total']) ?></div><div class="sub"><?= $remitTotals['files'] ?> files, <?= $remitTotals['customers'] ?> customers</div></div>
    <div class="card" style="border-left: 4px solid #ED7D31"><div class="label">Pending Review</div><div class="value"><?= number_format($matchTotals['pending']) ?></div><div class="sub"><?= number_format($matchTotals['approved']) ?> approved, <?= number_format($matchTotals['exported']) ?> exported</div></div>
    <div class="card"><div class="label">Quick Win ≤$20</div><div class="value"><?= number_format($totals['under20']) ?></div><div class="sub">Ecom: <?= number_format($totals['ecom']) ?> | AS400: <?= number_format($totals['as400']) ?></div></div>
  </div>
  
  <h2 class="section-title">Ecommerce Accounts</h2>
  <table>
    <tr><th>Customer</th><th>Open Inv</th><th>Net Balance</th><th>Remit Files</th><th>Matched</th><th>Pending</th><th>Coverage</th></tr>
    <?php
      $ecomData = $db->query("SELECT ec.customer_code, ec.short_name,
        (SELECT COUNT(*) FROM open_invoices oi WHERE oi.customer_code = ec.customer_code AND oi.resolution_status = 'open') as open_inv,
        (SELECT SUM(balance) FROM open_invoices oi WHERE oi.customer_code = ec.customer_code) as net_bal,
        (SELECT COUNT(DISTINCT source_file) FROM remit_records rr WHERE rr.customer_code = ec.customer_code) as remit_files,
        (SELECT COUNT(*) FROM match_results mr WHERE mr.customer_code = ec.customer_code AND mr.status != 'rejected') as matched,
        (SELECT COUNT(*) FROM match_results mr WHERE mr.customer_code = ec.customer_code AND mr.status = 'pending') as pending
        FROM ecom_customers ec ORDER BY ec.search_priority")->fetchAll();
      foreach ($ecomData as $ec):
        $total = $ec['open_inv'] + $ec['matched'];
        $pct = $total > 0 ? round($ec['matched'] / $total * 100) : 0;
    ?>
    <tr>
      <td><strong><?= htmlspecialchars($ec['short_name']) ?></strong><br><span style="font-size:11px;color:#999"><?= $ec['customer_code'] ?></span></td>
      <td><?= number_format($ec['open_inv']) ?></td>
      <td class="money <?= $ec['net_bal'] < 0 ? 'neg' : '' ?>"><?= money((float)($ec['net_bal'] ?? 0)) ?></td>
      <td><?= $ec['remit_files'] ?: '<span style="color:#C00000">None</span>' ?></td>
      <td><?= number_format($ec['matched']) ?></td>
      <td><?= $ec['pending'] > 0 ? "<a href='?page=matches&customer={$ec['customer_code']}&status=pending'>{$ec['pending']}</a>" : '0' ?></td>
      <td>
        <div class="progress-bar"><div class="fill green" style="width:<?= $pct ?>%"></div></div>
        <span style="font-size:11px"><?= $pct ?>%</span>
      </td>
    </tr>
    <?php endforeach; ?>
  </table>

<?php elseif ($page === 'matches'): ?>
  <?php
    $custFilter = $_GET['customer'] ?? '';
    $statusFilter = $_GET['status'] ?? 'pending';
    $typeFilter = $_GET['type'] ?? '';
    
    $where = ["1=1"];
    $params = [];
    if ($custFilter) { $where[] = "mr.customer_code = ?"; $params[] = $custFilter; }
    if ($statusFilter) { $where[] = "mr.status = ?"; $params[] = $statusFilter; }
    if ($typeFilter) { $where[] = "mr.match_type = ?"; $params[] = $typeFilter; }
    
    $whereStr = implode(' AND ', $where);
    $sql = "SELECT mr.*, oi.customer_name, oi.invoice_date, oi.is_as400, oi.age_bucket,
            rr.payment_date as remit_pay_date, rr.check_number as remit_check, rr.source_file as remit_file
            FROM match_results mr
            JOIN open_invoices oi ON mr.open_invoice_id = oi.id
            LEFT JOIN remit_records rr ON mr.remit_record_id = rr.id
            WHERE {$whereStr}
            ORDER BY mr.match_confidence DESC, ABS(mr.invoice_balance) DESC
            LIMIT 200";
    $stmt = $db->prepare($sql);
    $stmt->execute($params);
    $matches = $stmt->fetchAll();
    
    $customers = $db->query("SELECT DISTINCT customer_code FROM match_results ORDER BY customer_code")->fetchAll(PDO::FETCH_COLUMN);
  ?>
  
  <h2 class="section-title">Match Review (<?= count($matches) ?> results)</h2>
  
  <div class="filters">
    <form method="get" style="display:flex;gap:8px;align-items:center;">
      <input type="hidden" name="page" value="matches">
      <select name="customer"><option value="">All Customers</option>
        <?php foreach ($customers as $cc): ?><option value="<?= $cc ?>" <?= $cc === $custFilter ? 'selected' : '' ?>><?= $cc ?></option><?php endforeach; ?>
      </select>
      <select name="status">
        <option value="" <?= !$statusFilter ? 'selected' : '' ?>>All Status</option>
        <option value="pending" <?= $statusFilter === 'pending' ? 'selected' : '' ?>>Pending</option>
        <option value="approved" <?= $statusFilter === 'approved' ? 'selected' : '' ?>>Approved</option>
        <option value="rejected" <?= $statusFilter === 'rejected' ? 'selected' : '' ?>>Rejected</option>
        <option value="exported" <?= $statusFilter === 'exported' ? 'selected' : '' ?>>Exported</option>
      </select>
      <select name="type">
        <option value="">All Types</option>
        <option value="exact" <?= $typeFilter === 'exact' ? 'selected' : '' ?>>Exact</option>
        <option value="partial" <?= $typeFilter === 'partial' ? 'selected' : '' ?>>Partial</option>
        <option value="amount_only" <?= $typeFilter === 'amount_only' ? 'selected' : '' ?>>Amount Only</option>
        <option value="cross_customer" <?= $typeFilter === 'cross_customer' ? 'selected' : '' ?>>Cross-Customer Pos/Neg (AS400)</option>
        <option value="cross_customer_dup" <?= $typeFilter === 'cross_customer_dup' ? 'selected' : '' ?>>Cross-Customer Dup Inv# (AS400)</option>
      </select>
      <button type="submit" class="btn btn-export">Filter</button>
    </form>
    
    <?php if ($statusFilter === 'pending' && count($matches) > 0): ?>
    <form method="post" style="margin-left:auto;">
      <input type="hidden" name="action" value="bulk_approve">
      <?php foreach ($matches as $m): if ($m['match_type'] === 'exact'): ?>
        <input type="hidden" name="match_ids[]" value="<?= $m['id'] ?>">
      <?php endif; endforeach; ?>
      <button type="submit" class="btn btn-approve" onclick="return confirm('Approve all exact matches shown?')">Bulk Approve Exact Matches</button>
    </form>
    <?php endif; ?>
  </div>
  
  <table>
    <tr><th>Invoice</th><th>Customer</th><th>Inv Balance</th><th>Remit Amt</th><th>Variance</th><th>Type</th><th>Conf</th><th>Remit Check</th><th>Pay Date</th><th>Status</th><th>Actions</th></tr>
    <?php foreach ($matches as $m): ?>
    <tr>
      <td><strong><?= $m['invoice_no'] ?></strong><?= $m['is_as400'] ? '<br><span style="font-size:10px;color:#ED7D31">AS400</span>' : '' ?></td>
      <td><?= htmlspecialchars($m['customer_name'] ?? $m['customer_code']) ?></td>
      <td class="money"><?= money((float)$m['invoice_balance']) ?></td>
      <td class="money"><?= money((float)($m['remit_amount'] ?? 0)) ?></td>
      <td class="money <?= abs($m['variance'] ?? 0) > 0.01 ? 'neg' : '' ?>"><?= money((float)($m['variance'] ?? 0)) ?></td>
      <td><span class="badge <?= $m['match_type'] ?>"><?= $m['match_type'] ?></span></td>
      <td><?= number_format($m['match_confidence'], 0) ?>%</td>
      <td style="font-size:11px"><?= htmlspecialchars($m['remit_check'] ?? '-') ?></td>
      <td style="font-size:11px"><?= $m['remit_pay_date'] ?? '-' ?></td>
      <td><span class="badge <?= $m['status'] ?>"><?= $m['status'] ?></span></td>
      <td>
        <?php if ($m['status'] === 'pending'): ?>
        <form method="post" style="display:inline">
          <input type="hidden" name="match_id" value="<?= $m['id'] ?>">
          <input type="hidden" name="customer" value="<?= $custFilter ?>">
          <button name="action" value="approve_match" class="btn btn-approve btn-sm">✓</button>
          <button name="action" value="reject_match" class="btn btn-reject btn-sm">✗</button>
        </form>
        <?php else: ?>
        <span style="font-size:11px;color:#999"><?= $m['reviewed_by'] ?? '' ?></span>
        <?php endif; ?>
      </td>
    </tr>
    <?php endforeach; ?>
  </table>

<?php elseif ($page === 'pipeline'): ?>
  <h2 class="section-title">VI Export Pipeline</h2>
  <?php
    $batches = $db->query("SELECT * FROM vi_export_batches ORDER BY created_at DESC")->fetchAll();
    $pipeline = $db->query("SELECT status, resolution_action, COUNT(*) as cnt, SUM(invoice_balance) as bal 
      FROM match_results GROUP BY status, resolution_action ORDER BY FIELD(status,'pending','approved','exported','imported_test','posted_test','imported_prod','posted_prod')")->fetchAll();
  ?>
  
  <h3 style="margin-bottom:12px">Pipeline Status</h3>
  <table>
    <tr><th>Status</th><th>Action</th><th>Count</th><th>Balance</th></tr>
    <?php foreach ($pipeline as $p): ?>
    <tr>
      <td><span class="badge <?= $p['status'] ?>"><?= $p['status'] ?></span></td>
      <td><?= $p['resolution_action'] ?></td>
      <td><?= number_format($p['cnt']) ?></td>
      <td class="money"><?= money((float)$p['bal']) ?></td>
    </tr>
    <?php endforeach; ?>
  </table>
  
  <h3 style="margin-bottom:12px">Export Batches</h3>
  <table>
    <tr><th>Batch</th><th>Type</th><th>Records</th><th>Amount</th><th>GL</th><th>Status</th><th>Created</th></tr>
    <?php foreach ($batches as $b): ?>
    <tr>
      <td><strong><?= $b['batch_name'] ?></strong></td>
      <td><?= $b['batch_type'] ?></td>
      <td><?= number_format($b['record_count']) ?></td>
      <td class="money"><?= money((float)$b['total_amount']) ?></td>
      <td><?= $b['gl_account'] ?></td>
      <td><span class="badge <?= $b['status'] ?>"><?= $b['status'] ?></span></td>
      <td style="font-size:11px"><?= $b['created_at'] ?></td>
    </tr>
    <?php endforeach; ?>
  </table>

<?php elseif ($page === 'imports'): ?>
  <h2 class="section-title">Import Log</h2>
  <?php $imports = $db->query("SELECT * FROM import_log ORDER BY imported_at DESC LIMIT 50")->fetchAll(); ?>
  <table>
    <tr><th>ID</th><th>Type</th><th>File</th><th>Customer</th><th>Imported</th><th>Skipped</th><th>Errors</th><th>Notes</th><th>Date</th></tr>
    <?php foreach ($imports as $imp): ?>
    <tr>
      <td><?= $imp['id'] ?></td>
      <td><?= $imp['import_type'] ?></td>
      <td style="font-size:11px"><?= htmlspecialchars($imp['source_file']) ?></td>
      <td><?= $imp['customer_code'] ?? '-' ?></td>
      <td><?= number_format($imp['records_imported']) ?></td>
      <td><?= number_format($imp['records_skipped']) ?></td>
      <td style="<?= $imp['records_errored'] > 0 ? 'color:#C00000;font-weight:bold' : '' ?>"><?= $imp['records_errored'] ?></td>
      <td style="font-size:11px"><?= htmlspecialchars($imp['notes'] ?? '') ?></td>
      <td style="font-size:11px"><?= $imp['imported_at'] ?></td>
    </tr>
    <?php endforeach; ?>
  </table>

<?php elseif ($page === 'invoices'): ?>
  <?php
    $custFilter = $_GET['customer'] ?? '';
    $statusFilter = $_GET['status'] ?? 'open';
    $where = ["1=1"]; $params = [];
    if ($custFilter) { $where[] = "customer_code = ?"; $params[] = $custFilter; }
    if ($statusFilter) { $where[] = "resolution_status = ?"; $params[] = $statusFilter; }
    $whereStr = implode(' AND ', $where);
    $stmt = $db->prepare("SELECT * FROM open_invoices WHERE {$whereStr} ORDER BY ABS(balance) DESC LIMIT 500");
    $stmt->execute($params);
    $invoices = $stmt->fetchAll();
  ?>
  <h2 class="section-title">Open Invoices (showing <?= count($invoices) ?>)</h2>
  <table>
    <tr><th>Invoice</th><th>Customer</th><th>Date</th><th>Balance</th><th>Age</th><th>AS400</th><th>Status</th></tr>
    <?php foreach ($invoices as $inv): ?>
    <tr>
      <td><strong><?= $inv['invoice_no'] ?></strong></td>
      <td><?= htmlspecialchars($inv['customer_name'] ?? $inv['customer_code']) ?></td>
      <td><?= $inv['invoice_date'] ?></td>
      <td class="money <?= $inv['balance'] < 0 ? 'neg' : '' ?>"><?= money((float)$inv['balance']) ?></td>
      <td><?= $inv['age_bucket'] ?></td>
      <td><?= $inv['is_as400'] ? 'Yes' : '' ?></td>
      <td><span class="badge <?= $inv['resolution_status'] ?>"><?= $inv['resolution_status'] ?></span></td>
    </tr>
    <?php endforeach; ?>
  </table>

<?php elseif ($page === 'remit'): ?>
  <?php
    $coverage = $db->query("SELECT rr.customer_code, ec.short_name,
      COUNT(DISTINCT rr.source_file) as files, COUNT(*) as records,
      MIN(rr.payment_date) as earliest, MAX(rr.payment_date) as latest,
      SUM(rr.is_matched) as matched
      FROM remit_records rr LEFT JOIN ecom_customers ec ON rr.customer_code = ec.customer_code
      GROUP BY rr.customer_code, ec.short_name ORDER BY COUNT(*) DESC")->fetchAll();
  ?>
  <h2 class="section-title">Remit Data Coverage</h2>
  <table>
    <tr><th>Customer</th><th>Files</th><th>Records</th><th>Earliest</th><th>Latest</th><th>Matched</th><th>Unmatched</th></tr>
    <?php foreach ($coverage as $c): ?>
    <tr>
      <td><strong><?= htmlspecialchars($c['short_name'] ?? $c['customer_code']) ?></strong></td>
      <td><?= $c['files'] ?></td>
      <td><?= number_format($c['records']) ?></td>
      <td><?= $c['earliest'] ?></td>
      <td><?= $c['latest'] ?></td>
      <td class="money"><?= number_format($c['matched']) ?></td>
      <td class="money" style="<?= ($c['records'] - $c['matched']) > 0 ? 'color:#ED7D31' : '' ?>"><?= number_format($c['records'] - $c['matched']) ?></td>
    </tr>
    <?php endforeach; ?>
  </table>

<?php endif; ?>

</div>
</body>
</html>
