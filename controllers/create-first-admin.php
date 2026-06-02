<?php

header('Content-Type: application/json');

require_once __DIR__ . '/../config/database.php';

$email = 'admin@email.com';
$password = 'Admin@12345';
$name = 'Super Admin';
$role = 'SUPER_ADMIN';

try {
    $checkStmt = $pdo->prepare("SELECT id FROM admins WHERE email = :email LIMIT 1");
    $checkStmt->bindValue(':email', $email);
    $checkStmt->execute();

    if ($checkStmt->fetch()) {
        echo json_encode([
            'status' => false,
            'message' => 'Admin already exists'
        ]);
        exit;
    }

    $hash = password_hash($password, PASSWORD_BCRYPT);

    $stmt = $pdo->prepare("
        INSERT INTO admins
            (name, email, password, role, status, created_at)
        VALUES
            (:name, :email, :password, :role, 'ACTIVE', NOW())
    ");

    $stmt->bindValue(':name', $name);
    $stmt->bindValue(':email', $email);
    $stmt->bindValue(':password', $hash);
    $stmt->bindValue(':role', $role);
    $stmt->execute();

    echo json_encode([
        'status' => true,
        'message' => 'First admin created',
        'login' => [
            'email' => $email,
            'password' => $password
        ]
    ]);
} catch (Throwable $e) {
    http_response_code(500);

    echo json_encode([
        'status' => false,
        'message' => 'Failed to create first admin',
        'error' => $e->getMessage()
    ]);
}