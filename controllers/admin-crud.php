<?php

header('Content-Type: application/json');

require_once __DIR__ . '/../config/database.php';
require_once __DIR__ . '/../config/auth-guard.php';

function jsonResponse(bool $status, string $message, array $extra = [], int $code = 200): void
{
    http_response_code($code);
    echo json_encode(array_merge([
        'status' => $status,
        'message' => $message
    ], $extra));
    exit;
}

function cleanValue($value): string
{
    return trim((string) $value);
}

function getInput(): array
{
    $contentType = $_SERVER['CONTENT_TYPE'] ?? '';

    if (stripos($contentType, 'application/json') !== false) {
        $raw = file_get_contents('php://input');
        $json = json_decode($raw, true);

        return is_array($json) ? $json : [];
    }

    return $_POST;
}

$method = $_SERVER['REQUEST_METHOD'];
$action = $_GET['action'] ?? ($_POST['action'] ?? '');

try {
    if ($method === 'GET' && $action === 'list') {
        $page = isset($_GET['page']) ? (int) $_GET['page'] : 1;
        $limit = isset($_GET['limit']) ? (int) $_GET['limit'] : 10;
        $search = cleanValue($_GET['search'] ?? '');
        $status = cleanValue($_GET['status'] ?? '');

        if ($page < 1) $page = 1;
        if ($limit < 1) $limit = 10;
        if ($limit > 100) $limit = 100;

        $offset = ($page - 1) * $limit;

        $where = [];
        $params = [];

        if ($search !== '') {
            $where[] = '(name LIKE :search OR email LIKE :search)';
            $params[':search'] = '%' . $search . '%';
        }

        if ($status !== '' && in_array($status, ['ACTIVE', 'INACTIVE'], true)) {
            $where[] = 'status = :status';
            $params[':status'] = $status;
        }

        $whereSql = count($where) ? 'WHERE ' . implode(' AND ', $where) : '';

        $countStmt = $pdo->prepare("SELECT COUNT(*) AS total FROM admins {$whereSql}");

        foreach ($params as $key => $value) {
            $countStmt->bindValue($key, $value);
        }

        $countStmt->execute();
        $total = (int) $countStmt->fetch(PDO::FETCH_ASSOC)['total'];

        $stmt = $pdo->prepare("
            SELECT
                id,
                name,
                email,
                role,
                status,
                created_at,
                updated_at
            FROM admins
            {$whereSql}
            ORDER BY id DESC
            LIMIT :limit OFFSET :offset
        ");

        foreach ($params as $key => $value) {
            $stmt->bindValue($key, $value);
        }

        $stmt->bindValue(':limit', $limit, PDO::PARAM_INT);
        $stmt->bindValue(':offset', $offset, PDO::PARAM_INT);
        $stmt->execute();

        jsonResponse(true, 'Admin data loaded', [
            'meta' => [
                'page' => $page,
                'limit' => $limit,
                'total' => $total,
                'total_page' => (int) ceil($total / $limit)
            ],
            'data' => $stmt->fetchAll(PDO::FETCH_ASSOC)
        ]);
    }

    if ($method === 'GET' && $action === 'detail') {
        $id = isset($_GET['id']) ? (int) $_GET['id'] : 0;

        if ($id < 1) {
            jsonResponse(false, 'Invalid admin ID', [], 422);
        }

        $stmt = $pdo->prepare("
            SELECT
                id,
                name,
                email,
                role,
                status,
                created_at,
                updated_at
            FROM admins
            WHERE id = :id
            LIMIT 1
        ");
        $stmt->bindValue(':id', $id, PDO::PARAM_INT);
        $stmt->execute();

        $admin = $stmt->fetch(PDO::FETCH_ASSOC);

        if (!$admin) {
            jsonResponse(false, 'Admin not found', [], 404);
        }

        jsonResponse(true, 'Admin detail loaded', [
            'data' => $admin
        ]);
    }

    if ($method !== 'POST') {
        jsonResponse(false, 'Method not allowed', [], 405);
    }

    $input = getInput();
    $action = $input['action'] ?? $action;

    if ($action === 'create') {
        $name = cleanValue($input['name'] ?? '');
        $email = cleanValue($input['email'] ?? '');
        $password = cleanValue($input['password'] ?? '');
        $role = cleanValue($input['role'] ?? 'ADMIN');
        $status = cleanValue($input['status'] ?? 'ACTIVE');

        if ($name === '') {
            jsonResponse(false, 'Name is required', [], 422);
        }

        if ($email === '' || !filter_var($email, FILTER_VALIDATE_EMAIL)) {
            jsonResponse(false, 'Valid email is required', [], 422);
        }

        if ($password === '') {
            jsonResponse(false, 'Password is required', [], 422);
        }

        if (!in_array($role, ['SUPER_ADMIN', 'ADMIN', 'OPERATOR'], true)) {
            jsonResponse(false, 'Invalid role', [], 422);
        }

        if (!in_array($status, ['ACTIVE', 'INACTIVE'], true)) {
            jsonResponse(false, 'Invalid status', [], 422);
        }

        $checkStmt = $pdo->prepare("SELECT id FROM admins WHERE email = :email LIMIT 1");
        $checkStmt->bindValue(':email', $email);
        $checkStmt->execute();

        if ($checkStmt->fetch()) {
            jsonResponse(false, 'Email already exists', [], 409);
        }

        $hash = password_hash($password, PASSWORD_BCRYPT);

        $stmt = $pdo->prepare("
            INSERT INTO admins
                (name, email, password, role, status, created_at)
            VALUES
                (:name, :email, :password, :role, :status, NOW())
        ");

        $stmt->bindValue(':name', $name);
        $stmt->bindValue(':email', $email);
        $stmt->bindValue(':password', $hash);
        $stmt->bindValue(':role', $role);
        $stmt->bindValue(':status', $status);
        $stmt->execute();

        jsonResponse(true, 'Admin created successfully', [
            'id' => (int) $pdo->lastInsertId()
        ]);
    }

    if ($action === 'update') {
        $id = isset($input['id']) ? (int) $input['id'] : 0;
        $name = cleanValue($input['name'] ?? '');
        $email = cleanValue($input['email'] ?? '');
        $password = cleanValue($input['password'] ?? '');
        $role = cleanValue($input['role'] ?? 'ADMIN');
        $status = cleanValue($input['status'] ?? 'ACTIVE');

        if ($id < 1) {
            jsonResponse(false, 'Invalid admin ID', [], 422);
        }

        if ($name === '') {
            jsonResponse(false, 'Name is required', [], 422);
        }

        if ($email === '' || !filter_var($email, FILTER_VALIDATE_EMAIL)) {
            jsonResponse(false, 'Valid email is required', [], 422);
        }

        if (!in_array($role, ['SUPER_ADMIN', 'ADMIN', 'OPERATOR'], true)) {
            jsonResponse(false, 'Invalid role', [], 422);
        }

        if (!in_array($status, ['ACTIVE', 'INACTIVE'], true)) {
            jsonResponse(false, 'Invalid status', [], 422);
        }

        $checkStmt = $pdo->prepare("SELECT id FROM admins WHERE email = :email AND id <> :id LIMIT 1");
        $checkStmt->bindValue(':email', $email);
        $checkStmt->bindValue(':id', $id, PDO::PARAM_INT);
        $checkStmt->execute();

        if ($checkStmt->fetch()) {
            jsonResponse(false, 'Email already exists', [], 409);
        }

        if ($password !== '') {
            $hash = password_hash($password, PASSWORD_BCRYPT);

            $stmt = $pdo->prepare("
                UPDATE admins
                SET
                    name = :name,
                    email = :email,
                    password = :password,
                    role = :role,
                    status = :status,
                    updated_at = NOW()
                WHERE id = :id
            ");

            $stmt->bindValue(':password', $hash);
        } else {
            $stmt = $pdo->prepare("
                UPDATE admins
                SET
                    name = :name,
                    email = :email,
                    role = :role,
                    status = :status,
                    updated_at = NOW()
                WHERE id = :id
            ");
        }

        $stmt->bindValue(':id', $id, PDO::PARAM_INT);
        $stmt->bindValue(':name', $name);
        $stmt->bindValue(':email', $email);
        $stmt->bindValue(':role', $role);
        $stmt->bindValue(':status', $status);
        $stmt->execute();

        jsonResponse(true, 'Admin updated successfully');
    }

    if ($action === 'delete') {
        $id = isset($input['id']) ? (int) $input['id'] : 0;

        if ($id < 1) {
            jsonResponse(false, 'Invalid admin ID', [], 422);
        }

        $stmt = $pdo->prepare("DELETE FROM admins WHERE id = :id");
        $stmt->bindValue(':id', $id, PDO::PARAM_INT);
        $stmt->execute();

        jsonResponse(true, 'Admin deleted successfully');
    }

    jsonResponse(false, 'Invalid action', [], 400);
} catch (Throwable $e) {
    jsonResponse(false, 'Admin request failed', [
        'error' => $e->getMessage()
    ], 500);
}