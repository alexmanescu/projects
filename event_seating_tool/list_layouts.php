<?php
// list_layouts.php
header('Content-Type: application/json');

$dir = __DIR__ . '/layouts';
$layouts = [];

if (is_dir($dir)) {
    // Get all directories inside 'layouts'
    $files = scandir($dir);
    foreach ($files as $file) {
        if ($file !== '.' && $file !== '..' && is_dir($dir . '/' . $file)) {
            // Check if it contains a data.json file
            if (file_exists($dir . '/' . $file . '/data.json')) {
                $layouts[] = $file;
            }
        }
    }
}

echo json_encode(['success' => true, 'layouts' => $layouts]);
?>

