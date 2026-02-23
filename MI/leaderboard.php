<?php
/**
 * Mi INC. Delivery Run — Leaderboard API
 * 
 * Flat-file JSON "database" storing top 10 scores.
 * 
 * GET  leaderboard.php          → returns JSON array of top 10
 * POST leaderboard.php          → submit a new score
 *       Body: { "name": "ABC", "score": 1234, "deliveries": 3 }
 * 
 * Upload this file + scores.json to the same directory on your server.
 * Make sure scores.json is writable by the web server (chmod 664 typically).
 */

header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');

// Handle preflight
if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(204);
    exit;
}

$DATA_FILE = __DIR__ . '/scores.json';
$MAX_ENTRIES = 10;

// --- Blocked initials (profanity filter) ---
$BLOCKED = [
    'ASS','FUK','FUC','FCK','FKU','FKC','CNT','CUM','COK','COC',
    'DIK','DIC','DKS','FAG','FAT','GAY','GOD','JEW','JIZ','KKK',
    'KYS','NIG','NGA','NGR','NUT','PIS','PUS','RAP','SEX','SHT',
    'SLT','STD','TIT','THO','TWA','VAG','WTF','WOP','XXX','666',
    'SUK','SUC','HOE','HOR','ARS','DAM','DMN','HEL','POO','BLO',
    'FEL','DIE','KIL','GUN','WAR'
];

function loadScores($file) {
    if (!file_exists($file)) return [];
    $raw = file_get_contents($file);
    $data = json_decode($raw, true);
    return is_array($data) ? $data : [];
}

function saveScores($file, $scores) {
    // Acquire an exclusive lock while writing to prevent race conditions
    file_put_contents($file, json_encode($scores, JSON_PRETTY_PRINT), LOCK_EX);
}

// ===== GET — return leaderboard =====
if ($_SERVER['REQUEST_METHOD'] === 'GET') {
    echo json_encode(loadScores($DATA_FILE));
    exit;
}

// ===== POST — submit a score =====
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $input = json_decode(file_get_contents('php://input'), true);

    // Validate
    if (!$input || !isset($input['name'], $input['score'])) {
        http_response_code(400);
        echo json_encode(['error' => 'Missing name or score']);
        exit;
    }

    $name = strtoupper(trim($input['name']));
    $score = intval($input['score']);
    $deliveries = intval($input['deliveries'] ?? 0);

    // Validate initials: exactly 3 alphanumeric characters
    if (!preg_match('/^[A-Z0-9]{3}$/', $name)) {
        http_response_code(400);
        echo json_encode(['error' => 'Initials must be 3 alphanumeric characters']);
        exit;
    }

    // Profanity check
    if (in_array($name, $BLOCKED, true)) {
        http_response_code(400);
        echo json_encode(['error' => 'Initials not allowed']);
        exit;
    }

    // Sanity check score
    if ($score < 0 || $score > 9999999) {
        http_response_code(400);
        echo json_encode(['error' => 'Invalid score']);
        exit;
    }

    // Load, insert, sort, trim, save
    $scores = loadScores($DATA_FILE);
    $scores[] = [
        'name'       => $name,
        'score'      => $score,
        'deliveries' => $deliveries,
        'date'       => date('Y-m-d H:i:s')
    ];
    usort($scores, fn($a, $b) => $b['score'] - $a['score']);
    $scores = array_slice($scores, 0, $MAX_ENTRIES);
    saveScores($DATA_FILE, $scores);

    echo json_encode(['success' => true, 'leaderboard' => $scores]);
    exit;
}

http_response_code(405);
echo json_encode(['error' => 'Method not allowed']);
