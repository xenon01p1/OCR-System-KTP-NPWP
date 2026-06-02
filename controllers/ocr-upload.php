<?php

header('Content-Type: application/json');

require_once __DIR__ . '/../config/database.php';
require_once __DIR__ . '/../config/auth-guard.php';

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode([
        'status' => false,
        'message' => 'Method not allowed'
    ]);
    exit;
}

$allowedLibraries = [
    'EasyOCR',
    'Tesseract OCR',
    'OpenCV',
    'OpenCV Tesseract',
    'PaddleOCR',
    'Hybrid OCR'
];

$ocrLibrary = $_POST['ocr_library'] ?? '';

if (!in_array($ocrLibrary, $allowedLibraries, true)) {
    http_response_code(400);
    echo json_encode([
        'status' => false,
        'message' => 'Invalid OCR library'
    ]);
    exit;
}

if (!isset($_FILES['documents'])) {
    http_response_code(400);
    echo json_encode([
        'status' => false,
        'message' => 'No files uploaded'
    ]);
    exit;
}

$uploadDir = __DIR__ . '/../uploads/';

if (!is_dir($uploadDir)) {
    mkdir($uploadDir, 0775, true);
}

$allowedExtensions = ['jpg', 'jpeg', 'png', 'pdf'];
$maxFileSize = 10 * 1024 * 1024; // 10MB

$uploadedFiles = [];
$files = $_FILES['documents'];

for ($i = 0; $i < count($files['name']); $i++) {
    if ($files['error'][$i] !== UPLOAD_ERR_OK) {
        $uploadedFiles[] = [
            'filename' => $files['name'][$i],
            'status' => false,
            'message' => 'Upload error'
        ];
        continue;
    }

    $originalName = $files['name'][$i];
    $tmpName = $files['tmp_name'][$i];
    $fileSize = $files['size'][$i];

    $extension = strtolower(pathinfo($originalName, PATHINFO_EXTENSION));

    if (!in_array($extension, $allowedExtensions, true)) {
        $uploadedFiles[] = [
            'filename' => $originalName,
            'status' => false,
            'message' => 'Invalid file type'
        ];
        continue;
    }

    if ($fileSize > $maxFileSize) {
        $uploadedFiles[] = [
            'filename' => $originalName,
            'status' => false,
            'message' => 'File too large. Max 10MB'
        ];
        continue;
    }

    $storedName = date('YmdHis') . '_' . bin2hex(random_bytes(8)) . '.' . $extension;
    $targetPath = $uploadDir . $storedName;
    $dbPath = 'uploads/' . $storedName;

    if (!move_uploaded_file($tmpName, $targetPath)) {
        $uploadedFiles[] = [
            'filename' => $originalName,
            'status' => false,
            'message' => 'Failed to move uploaded file'
        ];
        continue;
    }

    $stmt = $pdo->prepare("
        INSERT INTO upload_files 
        (
            original_filename,
            stored_filename,
            filepath,
            ocr_library,
            document_type,
            status,
            json_payload,
            created_at
        )
        VALUES
        (
            :original_filename,
            :stored_filename,
            :filepath,
            :ocr_library,
            'UNKNOWN',
            'PENDING',
            NULL,
            NOW()
        )
    ");

    $stmt->execute([
        ':original_filename' => $originalName,
        ':stored_filename' => $storedName,
        ':filepath' => $dbPath,
        ':ocr_library' => $ocrLibrary
    ]);

    $uploadedFiles[] = [
        'id' => $pdo->lastInsertId(),
        'filename' => $originalName,
        'stored_filename' => $storedName,
        'ocr_library' => $ocrLibrary,
        'status' => true,
        'message' => 'Uploaded and queued'
    ];
}

echo json_encode([
    'status' => true,
    'message' => 'Upload process completed',
    'data' => $uploadedFiles
]);