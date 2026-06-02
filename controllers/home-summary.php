<?php

header('Content-Type: application/json');

require_once __DIR__ . '/../config/database.php';

if ($_SERVER['REQUEST_METHOD'] !== 'GET') {
    http_response_code(405);
    echo json_encode([
        'status' => false,
        'message' => 'Method not allowed'
    ]);
    exit;
}

try {
    $summarySql = "
        SELECT
            COUNT(*) AS total_files,
            SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) AS pending_count,
            SUM(CASE WHEN status = 'PROCESSING' THEN 1 ELSE 0 END) AS processing_count,
            SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) AS success_count,
            SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failed_count
        FROM upload_files
    ";

    $summaryStmt = $pdo->prepare($summarySql);
    $summaryStmt->execute();
    $summary = $summaryStmt->fetch(PDO::FETCH_ASSOC);

    $totalFiles = (int) ($summary['total_files'] ?? 0);
    $successCount = (int) ($summary['success_count'] ?? 0);
    $successRate = $totalFiles > 0 ? round(($successCount / $totalFiles) * 100, 2) : 0;

    $engineStmt = $pdo->prepare("
        SELECT ocr_library
        FROM upload_files
        WHERE ocr_library IS NOT NULL AND ocr_library <> ''
        ORDER BY id DESC
        LIMIT 1
    ");
    $engineStmt->execute();
    $latestEngine = $engineStmt->fetchColumn();

    $latestStmt = $pdo->prepare("
        SELECT
            id,
            original_filename,
            ocr_library,
            document_type,
            status,
            created_at
        FROM upload_files
        ORDER BY id DESC
        LIMIT 5
    ");
    $latestStmt->execute();
    $latestRows = $latestStmt->fetchAll(PDO::FETCH_ASSOC);

    echo json_encode([
        'status' => true,
        'message' => 'Dashboard loaded',
        'data' => [
            'total_files' => $totalFiles,
            'pending_count' => (int) ($summary['pending_count'] ?? 0),
            'processing_count' => (int) ($summary['processing_count'] ?? 0),
            'success_count' => $successCount,
            'failed_count' => (int) ($summary['failed_count'] ?? 0),
            'success_rate' => $successRate,
            'latest_engine' => $latestEngine ?: '-',
            'latest_uploads' => $latestRows
        ]
    ]);
} catch (Throwable $e) {
    http_response_code(500);

    echo json_encode([
        'status' => false,
        'message' => 'Failed to load dashboard',
        'error' => $e->getMessage()
    ]);
}