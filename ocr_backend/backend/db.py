import pymysql
from . import config


def get_connection():
    return pymysql.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def insert_upload_file(file_id: str, filename: str, filepath: str) -> None:
    sql = """
        INSERT INTO upload_files (id, filename, filepath, status, json_payload, createdAt, processedAt)
        VALUES (%s, %s, %s, %s, NULL, NOW(), NULL)
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (file_id, filename, filepath, "queued"))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetch_next_queued_job():
    """Atomically claim one queued job. Safe for one or more worker processes."""
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, filename, filepath, status, json_payload, createdAt, processedAt
                FROM upload_files
                WHERE status = 'queued'
                ORDER BY createdAt ASC
                LIMIT 1
                FOR UPDATE
                """
            )
            job = cur.fetchone()
            if not job:
                conn.rollback()
                return None

            cur.execute(
                """
                UPDATE upload_files
                SET status = 'processing'
                WHERE id = %s
                """,
                (job["id"],),
            )
        conn.commit()
        return job
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def mark_completed(file_id: str, json_payload: str) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE upload_files
                SET status = 'success', json_payload = %s, processedAt = NOW()
                WHERE id = %s
                """,
                (json_payload, file_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def mark_failed(file_id: str, json_payload: str) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE upload_files
                SET status = 'failed', json_payload = %s, processedAt = NOW()
                WHERE id = %s
                """,
                (json_payload, file_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_files():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, filename, filepath, status, json_payload, createdAt, processedAt
                FROM upload_files
                ORDER BY createdAt DESC
                """
            )
            return cur.fetchall()
    finally:
        conn.close()


def get_file(file_id: str):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, filename, filepath, status, json_payload, createdAt, processedAt
                FROM upload_files
                WHERE id = %s
                LIMIT 1
                """,
                (file_id,),
            )
            return cur.fetchone()
    finally:
        conn.close()


def delete_file(file_id: str) -> int:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            affected = cur.execute("DELETE FROM upload_files WHERE id = %s", (file_id,))
        conn.commit()
        return affected
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
