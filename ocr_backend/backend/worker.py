import time
import traceback
from pathlib import Path

from . import config
from .db import fetch_next_queued_job, mark_completed, mark_failed
from .ocr_engine import process_file, build_failed_payload, dumps_payload, ensure_upload_dir


def resolve_path(filepath: str) -> str:
    path = Path(filepath)
    if path.is_absolute():
        return str(path)
    # Database stores uploads/file.ext; uploads is at project root.
    return str((config.BASE_DIR / filepath).resolve())


def run_forever():
    ensure_upload_dir()
    print("OCR worker started")

    while True:
        job = None
        try:
            job = fetch_next_queued_job()
            if not job:
                time.sleep(config.WORKER_SLEEP_SECONDS)
                continue

            print(f"Processing {job['id']} - {job['filename']}")
            file_path = resolve_path(job["filepath"])
            payload = process_file(file_path)
            mark_completed(job["id"], dumps_payload(payload))
            print(f"Completed {job['id']}")

        except Exception:
            err = traceback.format_exc()
            print(err)
            if job and job.get("id"):
                failed_payload = build_failed_payload(err)
                mark_failed(job["id"], dumps_payload(failed_payload))
            time.sleep(2)


if __name__ == "__main__":
    run_forever()
