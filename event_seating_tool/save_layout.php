<?php
// save_layout.php
header('Content-Type: application/json');

// 1. Sanitize the layout name
$name = $_POST['name'] ?? '';
// Only allow alphanumeric, hyphens, underscores
$cleanName = preg_replace('/[^a-zA-Z0-9_-]/', '', $name);

if (empty($cleanName)) {
    echo json_encode(['success' => false, 'message' => 'Invalid layout name.']);
    exit;
}

// 2. Prepare Directory: layouts/{LayoutName}/
$targetDir = __DIR__ . "/layouts/$cleanName";
if (!file_exists($targetDir)) {
    if (!mkdir($targetDir, 0755, true)) {
        echo json_encode(['success' => false, 'message' => 'Failed to create directory. Check server permissions.']);
        exit;
    }
}

// 3. Process the JSON Data
$layoutDataJSON = $_POST['layoutData'] ?? '{}';
$layoutData = json_decode($layoutDataJSON, true);

if (!$layoutData) {
    echo json_encode(['success' => false, 'message' => 'Invalid JSON data.']);
    exit;
}

// 4. Handle Background Image Upload
if (isset($_FILES['bgFile']) && $_FILES['bgFile']['error'] === UPLOAD_ERR_OK) {
    $fileTmpPath = $_FILES['bgFile']['tmp_name'];
    $fileName    = $_FILES['bgFile']['name'];
    $fileExt     = strtolower(pathinfo($fileName, PATHINFO_EXTENSION));
    
    // Allow only images
    $allowedExts = ['jpg', 'jpeg', 'png', 'gif', 'webp'];
    if (in_array($fileExt, $allowedExts)) {
        $newFileName = 'background.' . $fileExt;
        $destPath = "$targetDir/$newFileName";
        
        if(move_uploaded_file($fileTmpPath, $destPath)) {
            // Update the JSON to point to this file instead of Base64
            // We use a relative path so the frontend can load it
            $layoutData['bgImage'] = "layouts/$cleanName/$newFileName";
        }
    }
}

// 5. Handle CSV Upload
if (isset($_FILES['csvFile']) && $_FILES['csvFile']['error'] === UPLOAD_ERR_OK) {
    $fileTmpPath = $_FILES['csvFile']['tmp_name'];
    $destPath = "$targetDir/guests.csv";
    
    if(move_uploaded_file($fileTmpPath, $destPath)) {
        $layoutData['csvUrl'] = "layouts/$cleanName/guests.csv";
    }
}

// 6. Save the updated JSON data
// We remove the base64 string if we successfully saved the file to keep JSON light
// (The frontend logic handles this by using the 'bgImage' path we set above)
$jsonPath = "$targetDir/data.json";
if (file_put_contents($jsonPath, json_encode($layoutData))) {
    echo json_encode(['success' => true, 'message' => 'Saved successfully']);
} else {
    echo json_encode(['success' => false, 'message' => 'Failed to write JSON file.']);
}
?>