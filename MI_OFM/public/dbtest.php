<?php
// ── Temporary DB connection test — DELETE THIS FILE after use ──
require_once '../config/config.php';

echo '<pre>';
echo 'DB_HOST: ' . DB_HOST . "\n";
echo 'DB_NAME: ' . DB_NAME . "\n";
echo 'DB_USER: ' . DB_USER . "\n";
echo 'DB_PASS: ' . (DB_PASS ? '(set)' : '(empty!)') . "\n\n";

try {
    $dsn = 'mysql:host=' . DB_HOST . ';dbname=' . DB_NAME . ';charset=' . DB_CHARSET;
    $pdo = new PDO($dsn, DB_USER, DB_PASS, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
    echo "✓ Connected successfully!\n";
    $v = $pdo->query('SELECT VERSION()')->fetchColumn();
    echo "  MySQL version: $v\n";
} catch (PDOException $e) {
    echo "✗ Connection FAILED:\n  " . $e->getMessage() . "\n";
}
echo '</pre>';
