<?php

header('Content-Type: application/json');

if (session_status() === PHP_SESSION_NONE) {
    session_start();
}

if (!empty($_SESSION['admin_id'])) {
    echo json_encode([
        'status' => true,
        'authenticated' => true,
        'data' => [
            'id' => (int) $_SESSION['admin_id'],
            'name' => $_SESSION['admin_name'] ?? '',
            'email' => $_SESSION['admin_email'] ?? '',
            'role' => $_SESSION['admin_role'] ?? ''
        ]
    ]);
    exit;
}

http_response_code(401);

echo json_encode([
    'status' => false,
    'authenticated' => false,
    'message' => 'Unauthenticated'
]);