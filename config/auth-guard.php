<?php

if (session_status() === PHP_SESSION_NONE) {
    session_start();
}

if (empty($_SESSION['admin_id'])) {
    http_response_code(401);

    echo json_encode([
        'status' => false,
        'message' => 'Unauthenticated. Please login first.'
    ]);

    exit;
}