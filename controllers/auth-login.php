<?php

header('Content-Type: application/json');

require_once __DIR__ . '/../config/database.php';

if (session_status() === PHP_SESSION_NONE) {
    session_start();
}

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode([
        'status' => false,
        'message' => 'Method not allowed'
    ]);
    exit;
}

try {
    $email = trim($_POST['email'] ?? '');
    $password = (string) ($_POST['password'] ?? '');

    if ($email === '') {
        http_response_code(422);
        echo json_encode([
            'status' => false,
            'message' => 'Email is required'
        ]);
        exit;
    }

    if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
        http_response_code(422);
        echo json_encode([
            'status' => false,
            'message' => 'Invalid email format'
        ]);
        exit;
    }

    if ($password === '') {
        http_response_code(422);
        echo json_encode([
            'status' => false,
            'message' => 'Password is required'
        ]);
        exit;
    }

    $stmt = $pdo->prepare("
        SELECT
            id,
            name,
            email,
            password,
            role,
            status
        FROM admins
        WHERE email = :email
        LIMIT 1
    ");

    $stmt->bindValue(':email', $email);
    $stmt->execute();

    $admin = $stmt->fetch(PDO::FETCH_ASSOC);

    if (!$admin) {
        http_response_code(401);
        echo json_encode([
            'status' => false,
            'message' => 'Email or password is incorrect'
        ]);
        exit;
    }

    if ($admin['status'] !== 'ACTIVE') {
        http_response_code(403);
        echo json_encode([
            'status' => false,
            'message' => 'Your admin account is inactive'
        ]);
        exit;
    }

    if (!password_verify($password, $admin['password'])) {
        http_response_code(401);
        echo json_encode([
            'status' => false,
            'message' => 'Email or password is incorrect'
        ]);
        exit;
    }

    session_regenerate_id(true);

    $_SESSION['admin_id'] = (int) $admin['id'];
    $_SESSION['admin_name'] = $admin['name'];
    $_SESSION['admin_email'] = $admin['email'];
    $_SESSION['admin_role'] = $admin['role'];
    $_SESSION['logged_in_at'] = date('Y-m-d H:i:s');

    echo json_encode([
        'status' => true,
        'message' => 'Login successful',
        'data' => [
            'id' => (int) $admin['id'],
            'name' => $admin['name'],
            'email' => $admin['email'],
            'role' => $admin['role']
        ]
    ]);
} catch (Throwable $e) {
    http_response_code(500);

    echo json_encode([
        'status' => false,
        'message' => 'Login request failed',
        'error' => $e->getMessage()
    ]);
}