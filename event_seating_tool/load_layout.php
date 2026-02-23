<?php
// load_layout.php
header('Content-Type: application/json');

$name = $_GET['name'] ?? '';
$cleanName = preg_replace('/[^a-zA-Z0-9_-]/', '', $name);

if (empty($cleanName)) {
    echo json_encode(['success' => false, 'message' => 'No name provided']);
    exit;
}

$file = __DIR__ . "/layouts/$cleanName/data.json";

if (file_exists($file)) {
    // Prevent caching so the user gets the latest version
    header("Cache-Control: no-store, no-cache, must-revalidate, max-age=0");
    header("Cache-Control: post-check=0, pre-check=0", false);
    header("Pragma: no-cache");
    
    $content = file_get_contents($file);
    echo json_encode(['success' => true, 'data' => json_decode($content)]);
} else {
    echo json_encode(['success' => false, 'message' => 'Layout not found']);
}
?>