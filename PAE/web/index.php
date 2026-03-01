<?php
// ── Config check ──────────────────────────────────────────────────────────────
if (!file_exists(__DIR__ . '/config.php')) {
    die('<pre>config.php not found. Copy config.example.php to config.php and fill in your values.</pre>');
}
require_once __DIR__ . '/config.php';

// ── Session-based password gate ───────────────────────────────────────────────
session_start();

if (isset($_GET['logout'])) {
    session_destroy();
    header('Location: ' . strtok($_SERVER['REQUEST_URI'], '?'));
    exit;
}

$login_error = false;
if (!isset($_SESSION['pae_auth'])) {
    if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['pw'])) {
        if (hash_equals(DASHBOARD_PASSWORD, $_POST['pw'])) {
            $_SESSION['pae_auth'] = true;
        } else {
            $login_error = true;
        }
    }
    if (!isset($_SESSION['pae_auth'])) {
        ?><!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Monitor</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#0f1117;color:#c9d1d9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       display:flex;align-items:center;justify-content:center;min-height:100vh}
  .card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:2rem;width:320px}
  h1{font-size:1rem;color:#8b949e;margin-bottom:1.5rem;letter-spacing:.05em;text-transform:uppercase}
  input{width:100%;padding:.6rem .8rem;background:#0d1117;border:1px solid #30363d;border-radius:6px;
        color:#c9d1d9;font-size:.95rem;margin-bottom:1rem;outline:none}
  input:focus{border-color:#388bfd}
  button{width:100%;padding:.65rem;background:#238636;border:none;border-radius:6px;
         color:#fff;font-size:.95rem;cursor:pointer;font-weight:600}
  button:hover{background:#2ea043}
  .err{color:#f85149;font-size:.85rem;margin-top:.75rem;text-align:center}
</style>
</head>
<body>
<div class="card">
  <h1>Operations Monitor</h1>
  <form method="post">
    <input type="password" name="pw" placeholder="Password" autofocus autocomplete="current-password">
    <button type="submit">Sign in</button>
  </form>
  <?php if ($login_error): ?><p class="err">Incorrect password.</p><?php endif ?>
</div>
</body>
</html><?php
        exit;
    }
}

// ── Database connection ───────────────────────────────────────────────────────
$db_ok    = false;
$db_error = '';
try {
    $pdo = new PDO(
        'mysql:host=' . DB_HOST . ';port=' . DB_PORT . ';dbname=' . DB_NAME . ';charset=utf8mb4',
        DB_USER,
        DB_PASS,
        [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION, PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC]
    );
    $db_ok = true;
} catch (PDOException $e) {
    $db_error = $e->getMessage();
}

// ── Data queries ──────────────────────────────────────────────────────────────
$stats = $positions = $opportunities = $signals = $articles = $trades = [];

if ($db_ok) {
    // Stat cards
    $stats['total_articles']  = (int) $pdo->query("SELECT COUNT(*) FROM article_registry")->fetchColumn();
    $stats['articles_24h']    = (int) $pdo->query("SELECT COUNT(*) FROM article_registry WHERE first_scraped_at > DATE_SUB(NOW(), INTERVAL 24 HOUR)")->fetchColumn();
    $stats['analyses_24h']    = (int) $pdo->query("SELECT COUNT(*) FROM article_analysis  WHERE analyzed_at   > DATE_SUB(NOW(), INTERVAL 24 HOUR)")->fetchColumn();
    $stats['signals_24h']     = (int) $pdo->query("SELECT COUNT(*) FROM signals           WHERE created_at    > DATE_SUB(NOW(), INTERVAL 24 HOUR)")->fetchColumn();
    $stats['pending_opps']    = (int) $pdo->query("SELECT COUNT(*) FROM opportunities WHERE status = 'pending'")->fetchColumn();
    $stats['open_positions']  = (int) $pdo->query("SELECT COUNT(*) FROM positions")->fetchColumn();
    $stats['total_trades']    = (int) $pdo->query("SELECT COUNT(*) FROM trades WHERE action = 'buy'")->fetchColumn();
    $stats['last_scrape']     =       $pdo->query("SELECT MAX(first_scraped_at) FROM article_registry")->fetchColumn();
    $stats['last_signal']     =       $pdo->query("SELECT MAX(created_at) FROM signals")->fetchColumn();

    // Open positions
    $positions = $pdo->query("
        SELECT ticker, quantity, avg_entry_price, current_price, stop_loss, opened_at, last_updated,
               CASE WHEN avg_entry_price > 0 AND avg_entry_price IS NOT NULL AND current_price IS NOT NULL
                    THEN ROUND((current_price - avg_entry_price) / avg_entry_price * 100, 2)
                    ELSE NULL END AS pnl_pct
        FROM positions
        ORDER BY opened_at DESC
    ")->fetchAll();

    // Pending / approved opportunities
    $opportunities = $pdo->query("
        SELECT o.id, o.ticker, o.confluence_score, o.stop_loss_pct, o.status, o.created_at,
               s.name AS strategy_name,
               LEFT(o.thesis, 160) AS thesis_preview
        FROM opportunities o
        LEFT JOIN strategies s ON s.id = o.primary_strategy_id
        WHERE o.status IN ('pending','approved')
        ORDER BY o.created_at DESC
        LIMIT 20
    ")->fetchAll();

    // Recent signals
    $signals = $pdo->query("
        SELECT sg.ticker, sg.signal_type, sg.confidence, sg.created_at,
               st.name AS strategy_name
        FROM signals sg
        LEFT JOIN strategies st ON st.id = sg.strategy_id
        ORDER BY sg.created_at DESC
        LIMIT 25
    ")->fetchAll();

    // Recent articles
    $articles = $pdo->query("
        SELECT title, first_scraped_at, scrape_count
        FROM article_registry
        ORDER BY first_scraped_at DESC
        LIMIT 20
    ")->fetchAll();

    // Trade history
    $trades = $pdo->query("
        SELECT ticker, action, quantity, entry_price, exit_price, return_pct,
               executed_at, closed_at, notes
        FROM trades
        ORDER BY COALESCE(closed_at, executed_at) DESC
        LIMIT 15
    ")->fetchAll();
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function h($s): string  { return htmlspecialchars((string)$s, ENT_QUOTES, 'UTF-8'); }
function fmt_dt($dt): string {
    if (!$dt) return '—';
    $ts = strtotime($dt);
    $diff = time() - $ts;
    if ($diff < 60)   return 'just now';
    if ($diff < 3600) return round($diff/60).'m ago';
    if ($diff < 86400) return round($diff/3600).'h ago';
    return date('M j, H:i', $ts);
}
function fmt_pct($v): string { return $v !== null ? round((float)$v * 100).'%' : '—'; }
function pnl_class($v): string {
    if ($v === null || $v === '') return '';
    return (float)$v >= 0 ? 'pos' : 'neg';
}
function status_badge($s): string {
    $map = ['pending'=>'badge-warn','approved'=>'badge-ok','executed'=>'badge-ok',
            'rejected'=>'badge-mute','expired'=>'badge-mute'];
    $cls = $map[$s] ?? 'badge-mute';
    return '<span class="badge '.$cls.'">'.h($s).'</span>';
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="120">
<title>Ops Monitor</title>
<style>
/* ── Reset & base ─────────────────────────────────────────────────────────── */
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d1117;color:#c9d1d9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
     font-size:.9rem;line-height:1.5}
a{color:#58a6ff;text-decoration:none}

/* ── Layout ───────────────────────────────────────────────────────────────── */
.wrap{max-width:1280px;margin:0 auto;padding:1.25rem 1rem}
header{display:flex;align-items:center;justify-content:space-between;
       padding-bottom:1rem;border-bottom:1px solid #21262d;margin-bottom:1.25rem}
header h1{font-size:1rem;font-weight:600;color:#e6edf3;letter-spacing:.03em}
header .meta{color:#8b949e;font-size:.8rem}
header .meta a{color:#8b949e;margin-left:1rem}
header .meta a:hover{color:#c9d1d9}

/* ── Alert banner ─────────────────────────────────────────────────────────── */
.alert{background:#3d1a1a;border:1px solid #f8514955;border-radius:6px;
       padding:.75rem 1rem;margin-bottom:1rem;color:#f85149;font-size:.85rem}

/* ── Stat cards ───────────────────────────────────────────────────────────── */
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(155px,1fr));gap:.75rem;margin-bottom:1.5rem}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:1rem}
.card .label{color:#8b949e;font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.35rem}
.card .value{font-size:1.6rem;font-weight:700;color:#e6edf3;line-height:1}
.card .sub{color:#8b949e;font-size:.75rem;margin-top:.3rem}
.card.highlight .value{color:#3fb950}
.card.warn      .value{color:#d29922}

/* ── Section ──────────────────────────────────────────────────────────────── */
section{margin-bottom:1.75rem}
section h2{font-size:.8rem;font-weight:600;color:#8b949e;text-transform:uppercase;
           letter-spacing:.06em;margin-bottom:.6rem;padding-bottom:.4rem;
           border-bottom:1px solid #21262d}

/* ── Tables ───────────────────────────────────────────────────────────────── */
.tbl-wrap{overflow-x:auto;border-radius:8px;border:1px solid #30363d}
table{width:100%;border-collapse:collapse;background:#161b22}
th{background:#161b22;color:#8b949e;font-size:.75rem;font-weight:600;
   text-transform:uppercase;letter-spacing:.04em;padding:.55rem .75rem;
   text-align:left;border-bottom:1px solid #30363d;white-space:nowrap}
td{padding:.5rem .75rem;border-bottom:1px solid #21262d;vertical-align:top;color:#c9d1d9}
tr:last-child td{border-bottom:none}
tr:hover td{background:#1c2128}
.mono{font-family:'SFMono-Regular',Consolas,monospace;font-size:.83rem}
.mute{color:#8b949e}
.pos{color:#3fb950;font-weight:600}
.neg{color:#f85149;font-weight:600}
.ticker{font-weight:700;color:#e6edf3;font-size:.9rem}
.thesis-preview{color:#8b949e;font-size:.8rem;max-width:320px;
                white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* ── Badges ───────────────────────────────────────────────────────────────── */
.badge{display:inline-block;padding:.15em .55em;border-radius:20px;font-size:.72rem;font-weight:600}
.badge-ok  {background:#1a4b2a;color:#3fb950;border:1px solid #2ea04355}
.badge-warn{background:#3d2a00;color:#d29922;border:1px solid #d2992255}
.badge-mute{background:#21262d;color:#8b949e;border:1px solid #30363d}
.badge-err {background:#3d1a1a;color:#f85149;border:1px solid #f8514955}

/* ── DB status indicator ──────────────────────────────────────────────────── */
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px}
.dot-ok{background:#3fb950}
.dot-err{background:#f85149}
</style>
</head>
<body>
<div class="wrap">

<!-- ── Header ─────────────────────────────────────────────────────────────── -->
<header>
  <h1>
    <span class="dot <?= $db_ok ? 'dot-ok' : 'dot-err' ?>"></span>
    Operations Monitor
  </h1>
  <div class="meta">
    Auto-refreshes every 2 min &nbsp;·&nbsp;
    <?= date('M j, Y H:i') ?> UTC
    &nbsp;·&nbsp;
    <a href="?logout=1">Sign out</a>
  </div>
</header>

<?php if (!$db_ok): ?>
<div class="alert">
  <strong>Database unreachable:</strong> <?= h($db_error) ?>
</div>
<?php else: ?>

<!-- ── Stat cards ─────────────────────────────────────────────────────────── -->
<div class="cards">
  <div class="card">
    <div class="label">Articles (total)</div>
    <div class="value"><?= number_format($stats['total_articles']) ?></div>
    <div class="sub"><?= number_format($stats['articles_24h']) ?> in last 24 h</div>
  </div>
  <div class="card">
    <div class="label">Analyses (24 h)</div>
    <div class="value"><?= number_format($stats['analyses_24h']) ?></div>
  </div>
  <div class="card <?= $stats['signals_24h'] > 0 ? 'highlight' : '' ?>">
    <div class="label">Signals (24 h)</div>
    <div class="value"><?= number_format($stats['signals_24h']) ?></div>
    <div class="sub">last: <?= fmt_dt($stats['last_signal']) ?></div>
  </div>
  <div class="card <?= $stats['pending_opps'] > 0 ? 'warn' : '' ?>">
    <div class="label">Pending</div>
    <div class="value"><?= $stats['pending_opps'] ?></div>
    <div class="sub">opportunities</div>
  </div>
  <div class="card">
    <div class="label">Open positions</div>
    <div class="value"><?= $stats['open_positions'] ?></div>
  </div>
  <div class="card">
    <div class="label">Trades (all)</div>
    <div class="value"><?= number_format($stats['total_trades']) ?></div>
    <div class="sub">buy executions</div>
  </div>
  <div class="card">
    <div class="label">Last scrape</div>
    <div class="value" style="font-size:1rem;padding-top:.2rem"><?= fmt_dt($stats['last_scrape']) ?></div>
  </div>
</div>

<!-- ── Open positions ─────────────────────────────────────────────────────── -->
<section>
  <h2>Open Positions (<?= count($positions) ?>)</h2>
  <?php if (empty($positions)): ?>
    <p class="mute" style="font-size:.85rem;padding:.5rem 0">No open positions.</p>
  <?php else: ?>
  <div class="tbl-wrap">
    <table>
      <thead>
        <tr>
          <th>Ticker</th>
          <th>Qty</th>
          <th>Entry</th>
          <th>Current</th>
          <th>P / L</th>
          <th>Stop</th>
          <th>Opened</th>
          <th>Updated</th>
        </tr>
      </thead>
      <tbody>
        <?php foreach ($positions as $p): ?>
        <tr>
          <td><span class="ticker"><?= h($p['ticker']) ?></span></td>
          <td class="mono"><?= h($p['quantity']) ?></td>
          <td class="mono"><?= $p['avg_entry_price'] !== null ? '$'.number_format((float)$p['avg_entry_price'], 2) : '—' ?></td>
          <td class="mono"><?= $p['current_price']   !== null ? '$'.number_format((float)$p['current_price'],   2) : '—' ?></td>
          <td class="mono <?= pnl_class($p['pnl_pct']) ?>">
            <?php if ($p['pnl_pct'] !== null): ?>
              <?= (float)$p['pnl_pct'] >= 0 ? '+' : '' ?><?= number_format((float)$p['pnl_pct'], 2) ?>%
            <?php else: ?>—<?php endif ?>
          </td>
          <td class="mono mute"><?= $p['stop_loss'] !== null ? '$'.number_format((float)$p['stop_loss'], 2) : '—' ?></td>
          <td class="mute"><?= fmt_dt($p['opened_at']) ?></td>
          <td class="mute"><?= fmt_dt($p['last_updated']) ?></td>
        </tr>
        <?php endforeach ?>
      </tbody>
    </table>
  </div>
  <?php endif ?>
</section>

<!-- ── Pending opportunities ──────────────────────────────────────────────── -->
<section>
  <h2>Opportunities — Pending / Approved (<?= count($opportunities) ?>)</h2>
  <?php if (empty($opportunities)): ?>
    <p class="mute" style="font-size:.85rem;padding:.5rem 0">No pending opportunities.</p>
  <?php else: ?>
  <div class="tbl-wrap">
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>Ticker</th>
          <th>Strategy</th>
          <th>Confidence</th>
          <th>Stop %</th>
          <th>Status</th>
          <th>Created</th>
          <th>Thesis preview</th>
        </tr>
      </thead>
      <tbody>
        <?php foreach ($opportunities as $o): ?>
        <tr>
          <td class="mono mute"><?= h($o['id']) ?></td>
          <td><span class="ticker"><?= h($o['ticker']) ?></span></td>
          <td class="mute"><?= h($o['strategy_name'] ?? '—') ?></td>
          <td class="mono"><?= fmt_pct($o['confluence_score']) ?></td>
          <td class="mono"><?= $o['stop_loss_pct'] !== null ? round((float)$o['stop_loss_pct']*100,1).'%' : '—' ?></td>
          <td><?= status_badge($o['status']) ?></td>
          <td class="mute"><?= fmt_dt($o['created_at']) ?></td>
          <td><span class="thesis-preview" title="<?= h($o['thesis_preview']) ?>"><?= h($o['thesis_preview']) ?></span></td>
        </tr>
        <?php endforeach ?>
      </tbody>
    </table>
  </div>
  <?php endif ?>
</section>

<!-- ── Recent signals ─────────────────────────────────────────────────────── -->
<section>
  <h2>Recent Signals</h2>
  <?php if (empty($signals)): ?>
    <p class="mute" style="font-size:.85rem;padding:.5rem 0">No signals yet — workers may not have run yet.</p>
  <?php else: ?>
  <div class="tbl-wrap">
    <table>
      <thead>
        <tr><th>Ticker</th><th>Type</th><th>Confidence</th><th>Strategy</th><th>When</th></tr>
      </thead>
      <tbody>
        <?php foreach ($signals as $s): ?>
        <tr>
          <td><span class="ticker"><?= h($s['ticker'] ?? '—') ?></span></td>
          <td class="mute"><?= h($s['signal_type'] ?? '—') ?></td>
          <td class="mono"><?= fmt_pct($s['confidence']) ?></td>
          <td class="mute"><?= h($s['strategy_name'] ?? '—') ?></td>
          <td class="mute"><?= fmt_dt($s['created_at']) ?></td>
        </tr>
        <?php endforeach ?>
      </tbody>
    </table>
  </div>
  <?php endif ?>
</section>

<!-- ── Trade history ──────────────────────────────────────────────────────── -->
<section>
  <h2>Trade History (last 15)</h2>
  <?php if (empty($trades)): ?>
    <p class="mute" style="font-size:.85rem;padding:.5rem 0">No trades executed yet.</p>
  <?php else: ?>
  <div class="tbl-wrap">
    <table>
      <thead>
        <tr><th>Ticker</th><th>Action</th><th>Qty</th><th>Entry</th><th>Exit</th><th>Return</th><th>Executed</th><th>Closed</th></tr>
      </thead>
      <tbody>
        <?php foreach ($trades as $t): ?>
        <?php $ret = $t['return_pct']; ?>
        <tr>
          <td><span class="ticker"><?= h($t['ticker'] ?? '—') ?></span></td>
          <td>
            <span class="badge <?= $t['action'] === 'buy' ? 'badge-ok' : 'badge-warn' ?>">
              <?= h(strtoupper($t['action'] ?? '')) ?>
            </span>
          </td>
          <td class="mono"><?= h($t['quantity'] ?? '—') ?></td>
          <td class="mono"><?= $t['entry_price'] ? '$'.number_format((float)$t['entry_price'],2) : '—' ?></td>
          <td class="mono"><?= $t['exit_price']  ? '$'.number_format((float)$t['exit_price'], 2) : '—' ?></td>
          <td class="mono <?= pnl_class($ret) ?>">
            <?php if ($ret !== null): ?>
              <?= (float)$ret >= 0 ? '+' : '' ?><?= number_format((float)$ret, 2) ?>%
            <?php else: ?>—<?php endif ?>
          </td>
          <td class="mute"><?= fmt_dt($t['executed_at']) ?></td>
          <td class="mute"><?= fmt_dt($t['closed_at']) ?></td>
        </tr>
        <?php endforeach ?>
      </tbody>
    </table>
  </div>
  <?php endif ?>
</section>

<!-- ── Recent articles ────────────────────────────────────────────────────── -->
<section>
  <h2>Recently Scraped Articles (last 20)</h2>
  <?php if (empty($articles)): ?>
    <p class="mute" style="font-size:.85rem;padding:.5rem 0">No articles yet — workers may not have run yet.</p>
  <?php else: ?>
  <div class="tbl-wrap">
    <table>
      <thead>
        <tr><th>Title</th><th>First scraped</th><th>Seen count</th></tr>
      </thead>
      <tbody>
        <?php foreach ($articles as $a): ?>
        <tr>
          <td style="max-width:560px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
            <?= h($a['title'] ?? '(no title)') ?>
          </td>
          <td class="mute"><?= fmt_dt($a['first_scraped_at']) ?></td>
          <td class="mono mute"><?= (int)$a['scrape_count'] ?></td>
        </tr>
        <?php endforeach ?>
      </tbody>
    </table>
  </div>
  <?php endif ?>
</section>

<?php endif // db_ok ?>
</div><!-- /wrap -->
</body>
</html>
