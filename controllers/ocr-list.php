<?php

header('Content-Type: application/json');

require_once __DIR__ . '/../config/database.php';
require_once __DIR__ . '/../config/auth-guard.php';

if ($_SERVER['REQUEST_METHOD'] !== 'GET') {
    http_response_code(405);
    echo json_encode([
        'status' => false,
        'message' => 'Method not allowed'
    ]);
    exit;
}

try {
    $page = isset($_GET['page']) ? (int) $_GET['page'] : 1;
    $limit = isset($_GET['limit']) ? (int) $_GET['limit'] : 50;
    $status = $_GET['status'] ?? '';

    if ($page < 1) {
        $page = 1;
    }

    if ($limit < 1) {
        $limit = 50;
    }

    if ($limit > 100) {
        $limit = 100;
    }

    $offset = ($page - 1) * $limit;

    $allowedStatuses = ['PENDING', 'PROCESSING', 'SUCCESS', 'FAILED'];
    $where = '';
    $params = [];

    if ($status !== '' && in_array($status, $allowedStatuses, true)) {
        $where = 'WHERE status = :status';
        $params[':status'] = $status;
    }

    $countSql = "SELECT COUNT(*) AS total FROM upload_files {$where}";
    $countStmt = $pdo->prepare($countSql);

    foreach ($params as $key => $value) {
        $countStmt->bindValue($key, $value);
    }

    $countStmt->execute();
    $total = (int) $countStmt->fetch(PDO::FETCH_ASSOC)['total'];

    $sql = "
        SELECT
            id,
            original_filename,
            stored_filename,
            filepath,
            ocr_library,
            document_type,
            status,
            json_payload,
            error_message,
            created_at,
            processed_at
        FROM upload_files
        {$where}
        ORDER BY id DESC
        LIMIT :limit OFFSET :offset
    ";

    $stmt = $pdo->prepare($sql);

    foreach ($params as $key => $value) {
        $stmt->bindValue($key, $value);
    }

    $stmt->bindValue(':limit', $limit, PDO::PARAM_INT);
    $stmt->bindValue(':offset', $offset, PDO::PARAM_INT);
    $stmt->execute();

    $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);

    $data = [];

    foreach ($rows as $row) {
        $payload = null;

        if (!empty($row['json_payload'])) {
            $decoded = json_decode($row['json_payload'], true);

            if (json_last_error() === JSON_ERROR_NONE) {
                $payload = $decoded;
            }
        }

        $score = null;
        $scoreMax = null;
        $scorePercent = null;
        $manualReviewRequired = null;

        if (is_array($payload)) {
            $score = $payload['score'] ?? null;
            $scoreMax = $payload['score_max'] ?? null;
            $scorePercent = $payload['score_percent'] ?? null;
            $manualReviewRequired = $payload['manual_review_required'] ?? null;

            if ($scorePercent === null && $score !== null && $scoreMax !== null && (float) $scoreMax > 0) {
                $scorePercent = round(((float) $score / (float) $scoreMax) * 100, 2);
            }
        }

        $data[] = [
            'id' => (int) $row['id'],
            'original_filename' => $row['original_filename'],
            'stored_filename' => $row['stored_filename'],
            'filepath' => $row['filepath'],
            'file_url' => $row['filepath'],
            'ocr_library' => $row['ocr_library'],
            'document_type' => $row['document_type'],
            'status' => $row['status'],
            'score' => $score,
            'score_max' => $scoreMax,
            'score_percent' => $scorePercent,
            'manual_review_required' => $manualReviewRequired,
            'error_message' => $row['error_message'],
            'json_payload' => $payload,
            'created_at' => $row['created_at'],
            'processed_at' => $row['processed_at']
        ];
    }

    echo json_encode([
        'status' => true,
        'message' => 'Data loaded',
        'meta' => [
            'page' => $page,
            'limit' => $limit,
            'total' => $total,
            'total_page' => (int) ceil($total / $limit)
        ],
        'data' => $data
    ]);
} catch (Throwable $e) {
    http_response_code(500);

    echo json_encode([
        'status' => false,
        'message' => 'Failed to load OCR data',
        'error' => $e->getMessage()
    ]);
}