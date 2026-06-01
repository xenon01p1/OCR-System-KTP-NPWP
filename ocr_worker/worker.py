import json
import os
import time
import traceback
from pathlib import Path

from dotenv import load_dotenv

from db import get_connection
from ocr_engine import run_ocr

load_dotenv()

PROJECT_ROOT = os.getenv("PROJECT_ROOT")
SLEEP_SECONDS = int(os.getenv("WORKER_SLEEP_SECONDS", "3"))


def get_absolute_file_path(relative_path: str) -> str:
    if not PROJECT_ROOT:
        raise ValueError("PROJECT_ROOT is not set in .env")

    return str(Path(PROJECT_ROOT) / relative_path)


def fetch_pending_job():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT 
                id,
                original_filename,
                stored_filename,
                filepath,
                ocr_library
            FROM upload_files
            WHERE status = 'PENDING'
            ORDER BY id ASC
            LIMIT 1
        """)

        job = cursor.fetchone()
        return job

    finally:
        cursor.close()
        conn.close()


def mark_processing(job_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE upload_files
            SET status = 'PROCESSING'
            WHERE id = %s
        """, (job_id,))

        conn.commit()

    finally:
        cursor.close()
        conn.close()


def mark_success(job_id: int, document_type: str, payload: dict):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE upload_files
            SET 
                status = 'SUCCESS',
                document_type = %s,
                json_payload = %s,
                error_message = NULL,
                processed_at = NOW()
            WHERE id = %s
        """, (
            document_type,
            json.dumps(payload, ensure_ascii=False),
            job_id
        ))

        conn.commit()

    finally:
        cursor.close()
        conn.close()


def mark_failed(job_id: int, error_message: str):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE upload_files
            SET 
                status = 'FAILED',
                error_message = %s,
                processed_at = NOW()
            WHERE id = %s
        """, (
            error_message,
            job_id
        ))

        conn.commit()

    finally:
        cursor.close()
        conn.close()


def process_job(job: dict):
    job_id = job["id"]
    relative_path = job["filepath"]
    library = job["ocr_library"]

    print(f"[JOB {job_id}] Processing {relative_path} using {library}")

    mark_processing(job_id)

    absolute_file_path = get_absolute_file_path(relative_path)

    result = run_ocr(
        file_path=absolute_file_path,
        library=library
    )

    document_type = result.get("document_type", "UNKNOWN")
    payload = result.get("payload", {})

    mark_success(
        job_id=job_id,
        document_type=document_type,
        payload=payload
    )

    print(f"[JOB {job_id}] SUCCESS - {document_type}")


def main():
    print("OCR worker started...")
    print(f"PROJECT_ROOT = {PROJECT_ROOT}")
    print(f"SLEEP_SECONDS = {SLEEP_SECONDS}")

    while True:
        try:
            job = fetch_pending_job()

            if not job:
                print("No pending job. Waiting...")
                time.sleep(SLEEP_SECONDS)
                continue

            try:
                process_job(job)

            except Exception as job_error:
                error_text = str(job_error)
                trace_text = traceback.format_exc()

                print(f"[JOB {job['id']}] FAILED")
                print(trace_text)

                mark_failed(
                    job_id=job["id"],
                    error_message=error_text
                )

        except KeyboardInterrupt:
            print("Worker stopped manually.")
            break

        except Exception:
            print("Worker loop error:")
            print(traceback.format_exc())
            time.sleep(SLEEP_SECONDS)


if __name__ == "__main__":
    main()